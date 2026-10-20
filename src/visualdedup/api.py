"""High-level Python API for VisualDedup."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, Generator, Iterable, List, Optional, Set, Tuple, Union

from visualdedup.actions.cleaner import CleanMode, CleanResult, execute_cleanup
from visualdedup.core.cache import HashCache
from visualdedup.core.clustering import cluster_duplicates
from visualdedup.core.explanation import explain_match
from visualdedup.core.hasher import extract_image_hashes, hex_to_int
from visualdedup.core.indexing import BKTree, MultiIndexHashIndex
from visualdedup.core.keeper import KeeperStrategy, select_keeper
from visualdedup.core.models import DuplicateCluster, FileRecord, MatchEvidence, ScanSummary
from visualdedup.reports.html_report import generate_html_report
from visualdedup.reports.json_report import generate_json_report

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif"
}


class VisualDedup:
    """Primary engine for image deduplication, clustering, and safe cleanup."""

    def __init__(
        self,
        cache_path: Optional[Union[str, Path]] = ".visualdedup_cache.db",
        hash_type: str = "phash",  # "phash", "dhash", "ahash", "whash", or "exact"
        threshold: int = 8,
        index_type: str = "bktree",  # "bktree", "multi_index", or "linear"
    ):
        self.cache_path = str(cache_path) if cache_path else None
        self.cache = HashCache(self.cache_path) if self.cache_path else None
        self.hash_type = hash_type.lower()
        self.threshold = threshold
        self.index_type = index_type.lower()

    def _discover_images(
        self, paths: Iterable[Union[str, Path]], recursive: bool = True
    ) -> List[str]:
        """Find all supported image files across given files or directories."""
        found_files: List[str] = []
        for p in paths:
            target = Path(p)
            if target.is_file():
                if target.suffix.lower() in SUPPORTED_EXTENSIONS:
                    found_files.append(str(target.resolve()))
            elif target.is_dir():
                pattern = "**/*" if recursive else "*"
                for entry in target.glob(pattern):
                    if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                        found_files.append(str(entry.resolve()))
        return sorted(list(set(found_files)))

    def _get_or_compute_record(self, filepath: str) -> Optional[Tuple[FileRecord, bool]]:
        """Retrieve record from cache or compute it. Returns (record, is_cached)."""
        try:
            stat = os.stat(filepath)
            size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            return None

        if self.cache:
            cached = self.cache.get_valid_record(filepath, size, mtime)
            if cached:
                return cached, True

        # Cache miss - compute hashes
        try:
            (
                w,
                h,
                fmt,
                mode,
                sha256_hash,
                dhash,
                phash,
                ahash,
                whash,
            ) = extract_image_hashes(filepath)

            record = FileRecord(
                path=filepath,
                size_bytes=size,
                mtime=mtime,
                width=w,
                height=h,
                format=fmt,
                mode=mode,
                exact_hash=sha256_hash,
                dhash=dhash,
                phash=phash,
                ahash=ahash,
                whash=whash,
            )

            if self.cache:
                self.cache.upsert_record(record)

            return record, False
        except Exception:
            # File unreadable or corrupted
            return None

    def scan(
        self,
        paths: Union[str, Path, Iterable[Union[str, Path]]],
        recursive: bool = True,
        keeper_strategy: Optional[KeeperStrategy] = KeeperStrategy.BEST_QUALITY,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[List[DuplicateCluster], ScanSummary]:
        """Scan image files and directories, discover duplicate clusters, and assign keepers.

        Returns:
            (clusters, summary)
        """
        start_time = time.time()
        if isinstance(paths, (str, Path)):
            input_paths = [paths]
        else:
            input_paths = list(paths)

        image_files = self._discover_images(input_paths, recursive=recursive)
        total_files = len(image_files)

        records: Dict[str, FileRecord] = {}
        cache_hits = 0
        cache_misses = 0

        for idx, fpath in enumerate(image_files):
            res = self._get_or_compute_record(fpath)
            if res is not None:
                rec, was_cached = res
                records[fpath] = rec
                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1

            if progress_callback:
                progress_callback(idx + 1, total_files)

        # 1. Exact SHA-256 matching
        pairwise_matches: List[Tuple[str, str, MatchEvidence]] = []
        sha_groups: Dict[str, List[FileRecord]] = {}
        for rec in records.values():
            sha_groups.setdefault(rec.exact_hash, []).append(rec)

        for sha, group in sha_groups.items():
            if len(group) > 1:
                # Add exact pairwise edges
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        ev = explain_match(group[i], group[j], "sha256", 0, 0)
                        pairwise_matches.append((group[i].path, group[j].path, ev))

        # 2. Perceptual hashing (if not exact-only)
        if self.hash_type != "exact":
            hash_getter = lambda r: getattr(r, self.hash_type, None)

            # Build index for sub-quadratic search
            if self.index_type == "multi_index":
                index = MultiIndexHashIndex[FileRecord]()
            else:
                index = BKTree[FileRecord]()

            # Query against indexed records incrementally to avoid double matching
            for rec in records.values():
                h_str = hash_getter(rec)
                if not h_str:
                    continue
                h_int = hex_to_int(h_str)

                # Query already indexed items
                neighbors = index.query(h_int, self.threshold)
                for other_rec, dist in neighbors:
                    # Avoid duplicate edge if exact hash already connected them
                    if rec.exact_hash == other_rec.exact_hash:
                        continue
                    ev = explain_match(rec, other_rec, self.hash_type, dist, self.threshold)
                    pairwise_matches.append((rec.path, other_rec.path, ev))

                # Insert into index
                index.insert(rec, h_int)

        # 3. Cluster duplicates using connected components
        clusters = cluster_duplicates(records, pairwise_matches)

        # 4. Recommend keepers
        if keeper_strategy:
            self.recommend_keepers(clusters, strategy=keeper_strategy)

        # 5. Build summary
        total_clusters = len(clusters)
        total_duplicates = sum(len(c.records) for c in clusters)
        reclaimable_bytes = sum(c.potential_savings_bytes for c in clusters)
        duration = time.time() - start_time

        summary = ScanSummary(
            total_scanned=total_files,
            total_clusters=total_clusters,
            total_duplicates=total_duplicates,
            reclaimable_bytes=reclaimable_bytes,
            duration_seconds=duration,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )

        return clusters, summary

    def recommend_keepers(
        self,
        clusters: List[DuplicateCluster],
        strategy: KeeperStrategy = KeeperStrategy.BEST_QUALITY,
        custom_sorter: Optional[Callable[[FileRecord], Any]] = None,
    ) -> None:
        """Assign keeper decisions to all clusters in-place."""
        for cluster in clusters:
            cluster.keeper_decision = select_keeper(
                cluster.records, strategy=strategy, custom_sorter=custom_sorter
            )

    def export_json(
        self,
        clusters: List[DuplicateCluster],
        summary: ScanSummary,
        output_path: Union[str, Path],
    ) -> str:
        """Export scan results as JSON."""
        return generate_json_report(clusters, summary, output_path=output_path)

    def export_html(
        self,
        clusters: List[DuplicateCluster],
        summary: ScanSummary,
        output_path: Union[str, Path],
        embed_thumbnails: bool = True,
    ) -> str:
        """Export scan results as interactive HTML."""
        return generate_html_report(
            clusters, summary, output_path=output_path, embed_thumbnails=embed_thumbnails
        )

    def clean(
        self,
        clusters: List[DuplicateCluster],
        mode: Union[str, CleanMode] = CleanMode.QUARANTINE,
        target_dir: Optional[Union[str, Path]] = None,
        dry_run: bool = True,
        audit_log_path: Optional[Union[str, Path]] = None,
    ) -> CleanResult:
        """Clean duplicates using safe keeper plan."""
        clean_mode = CleanMode(mode) if isinstance(mode, str) else mode
        return execute_cleanup(
            clusters=clusters,
            mode=clean_mode,
            target_dir=target_dir,
            dry_run=dry_run,
            audit_log_path=audit_log_path,
        )

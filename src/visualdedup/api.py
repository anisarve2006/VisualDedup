"""High-level Python API for VisualDedup."""

from __future__ import annotations

import concurrent.futures
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional, Set, Tuple, Union

from visualdedup.actions.cleaner import CleanMode, CleanResult, execute_cleanup, store_duplicates
from visualdedup.core.cache import HashCache
from visualdedup.core.clustering import cluster_duplicates
from visualdedup.core.explanation import explain_match
from visualdedup.core.hasher import extract_image_hashes, hex_to_int
from visualdedup.core.indexing import BKTree, MultiIndexHashIndex
from visualdedup.core.keeper import KeeperStrategy, select_keeper
from visualdedup.core.models import DuplicateCluster, FileRecord, MatchEvidence, ScanSummary
from visualdedup.reports.csv_report import generate_csv_report
from visualdedup.reports.html_report import generate_html_report
from visualdedup.reports.json_report import generate_json_report

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif"
}


def _worker_hash_image(item: Tuple[str, int, float, Optional[str]]) -> Optional[FileRecord]:
    """Top-level worker function for parallel processing across multiple CPU cores."""
    fpath, size, mtime, primary_only = item
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
        ) = extract_image_hashes(fpath, primary_only=primary_only)

        return FileRecord(
            path=fpath,
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
    except Exception:
        return None


class VisualDedup:
    """Primary engine for image deduplication, clustering, and safe cleanup."""

    def __init__(
        self,
        cache_path: Optional[Union[str, Path]] = ".visualdedup_cache.db",
        hash_type: str = "phash",  # "phash", "dhash", "ahash", "whash", or "exact"
        threshold: int = 8,
        index_type: str = "multi_index",  # "multi_index" (fastest) or "bktree"
        max_workers: Optional[int] = None,
    ):
        self.cache_path = str(cache_path) if cache_path else None
        self.cache = HashCache(self.cache_path) if self.cache_path else None
        self.hash_type = hash_type.lower()
        self.threshold = threshold
        self.index_type = index_type.lower()
        self.max_workers = max_workers

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

    def scan(
        self,
        paths: Union[str, Path, Iterable[Union[str, Path]]],
        recursive: bool = True,
        keeper_strategy: Optional[KeeperStrategy] = KeeperStrategy.BEST_QUALITY,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_workers: Optional[int] = None,
    ) -> Tuple[List[DuplicateCluster], ScanSummary]:
        """Scan image files and directories, discover duplicate clusters, and assign keepers.

        Utilizes multi-process parallelism, batch cache lookup, and sub-quadratic indexing.

        Returns:
            (clusters, summary)
        """
        start_time = time.time()
        workers = max_workers if max_workers is not None else self.max_workers

        if isinstance(paths, (str, Path)):
            input_paths = [paths]
        else:
            input_paths = list(paths)

        image_files = self._discover_images(input_paths, recursive=recursive)
        total_files = len(image_files)

        records: Dict[str, FileRecord] = {}
        cache_hits = 0
        cache_misses = 0

        # Step 1: Gather file stats
        file_stats: List[Tuple[str, int, float]] = []
        for fpath in image_files:
            try:
                st = os.stat(fpath)
                file_stats.append((fpath, st.st_size, st.st_mtime))
            except OSError:
                continue

        # Step 2: Batch cache retrieval
        missing_items: List[Tuple[str, int, float, Optional[str]]] = []
        cached_records: Dict[str, FileRecord] = {}

        if self.cache:
            cached_records = self.cache.get_valid_records_batch(file_stats)
            cache_hits = len(cached_records)
            records.update(cached_records)

        # Primary hash optimization: if exact-only, we don't compute perceptual hashes
        primary_only = None
        if self.hash_type in ("phash", "dhash"):
            primary_only = self.hash_type

        for fpath, size, mtime in file_stats:
            if fpath not in records:
                missing_items.append((fpath, size, mtime, primary_only))

        cache_misses = len(missing_items)

        # Step 3: Compute missing records in parallel or sequentially
        new_records: List[FileRecord] = []
        if missing_items:
            effective_workers = workers if workers is not None else min(32, (os.cpu_count() or 4) * 2)
            if len(missing_items) > 4 and effective_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
                    for rec in executor.map(_worker_hash_image, missing_items):
                        if rec is not None:
                            records[rec.path] = rec
                            new_records.append(rec)
                        if progress_callback:
                            progress_callback(len(records), total_files)
            else:
                for item in missing_items:
                    rec = _worker_hash_image(item)
                    if rec is not None:
                        records[rec.path] = rec
                        new_records.append(rec)
                    if progress_callback:
                        progress_callback(len(records), total_files)

            # Step 4: Batch upsert into SQLite cache
            if self.cache and new_records:
                self.cache.upsert_records_batch(new_records)

        if progress_callback:
            progress_callback(total_files, total_files)

        # Step 5: Exact SHA-256 matching (O(N))
        pairwise_matches: List[Tuple[str, str, MatchEvidence]] = []
        sha_groups: Dict[str, List[FileRecord]] = {}
        for rec in records.values():
            sha_groups.setdefault(rec.exact_hash, []).append(rec)

        for sha, group in sha_groups.items():
            if len(group) > 1:
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        ev = explain_match(group[i], group[j], "sha256", 0, 0)
                        pairwise_matches.append((group[i].path, group[j].path, ev))

        # Step 6: Sub-quadratic perceptual candidate search
        if self.hash_type != "exact":
            hash_getter = lambda r: getattr(r, self.hash_type, None)

            # Multi-Index Hash or BK-Tree
            if self.index_type == "bktree":
                index = BKTree[FileRecord]()
            else:
                index = MultiIndexHashIndex[FileRecord]()

            for rec in records.values():
                h_str = hash_getter(rec)
                if not h_str:
                    continue
                h_int = hex_to_int(h_str)

                # Query against already indexed items
                neighbors = index.query(h_int, self.threshold)
                for other_rec, dist in neighbors:
                    if rec.exact_hash == other_rec.exact_hash:
                        continue
                    ev = explain_match(rec, other_rec, self.hash_type, dist, self.threshold)
                    pairwise_matches.append((rec.path, other_rec.path, ev))

                index.insert(rec, h_int)

        # Step 7: Cluster duplicates using connected components
        clusters = cluster_duplicates(records, pairwise_matches)

        # Step 8: Recommend keepers
        if keeper_strategy:
            self.recommend_keepers(clusters, strategy=keeper_strategy)

        # Step 9: Build summary
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

    def export_csv(
        self,
        clusters: List[DuplicateCluster],
        output_path: Union[str, Path],
    ) -> str:
        """Export scan results as structured tabular CSV."""
        return generate_csv_report(clusters, output_path=output_path)

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

    def store_duplicates(
        self,
        clusters: List[DuplicateCluster],
        output_dir: Union[str, Path],
        action: str = "copy",  # "copy" or "move"
        include_keeper: bool = True,
        organize_by_cluster: bool = True,
        tag_filenames: bool = True,
        dry_run: bool = False,
        audit_log_path: Optional[Union[str, Path]] = None,
    ) -> CleanResult:
        """Store duplicate images in a separate output directory after processing.

        Args:
            clusters: List of duplicate clusters from scan.
            output_dir: Folder to store duplicate images into.
            action: "copy" (keeps original intact) or "move" (relocates discards).
            include_keeper: If True, copies the keeper image into the cluster folder too.
            organize_by_cluster: If True, organizes files into `output_dir/cluster_0001/` subfolders.
            tag_filenames: If True, prefixes filenames with `KEEPER_` and `DISCARD_`.
            dry_run: If True, simulates actions without modifying disk.
            audit_log_path: Path to write JSON audit manifest.

        Returns:
            CleanResult with action breakdown and file metrics.
        """
        return store_duplicates(
            clusters=clusters,
            output_dir=output_dir,
            action=action,
            include_keeper=include_keeper,
            organize_by_cluster=organize_by_cluster,
            tag_filenames=tag_filenames,
            dry_run=dry_run,
            audit_log_path=audit_log_path,
        )

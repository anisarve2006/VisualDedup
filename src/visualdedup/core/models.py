"""Core data models for VisualDedup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FileRecord:
    """Metadata and computed hashes for an individual image file."""

    path: str
    size_bytes: int
    mtime: float
    width: int
    height: int
    format: str
    mode: str
    exact_hash: str  # SHA-256 hex string
    dhash: Optional[str] = None  # 64-bit hex
    phash: Optional[str] = None  # 64-bit hex
    ahash: Optional[str] = None  # 64-bit hex
    whash: Optional[str] = None  # 64-bit hex

    @property
    def aspect_ratio(self) -> float:
        if self.height <= 0:
            return 0.0
        return round(self.width / self.height, 4)

    @property
    def megapixels(self) -> float:
        return round((self.width * self.height) / 1_000_000, 2)

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "width": self.width,
            "height": self.height,
            "aspect_ratio": self.aspect_ratio,
            "megapixels": self.megapixels,
            "format": self.format,
            "mode": self.mode,
            "exact_hash": self.exact_hash,
            "dhash": self.dhash,
            "phash": self.phash,
            "ahash": self.ahash,
            "whash": self.whash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FileRecord:
        return cls(
            path=data["path"],
            size_bytes=data["size_bytes"],
            mtime=data["mtime"],
            width=data["width"],
            height=data["height"],
            format=data.get("format", "UNKNOWN"),
            mode=data.get("mode", "RGB"),
            exact_hash=data["exact_hash"],
            dhash=data.get("dhash"),
            phash=data.get("phash"),
            ahash=data.get("ahash"),
            whash=data.get("whash"),
        )


@dataclass
class MatchEvidence:
    """Explanation and distance metrics behind a match between two images."""

    match_type: str  # "exact", "near_duplicate", "resized", "recompressed", "similar"
    hash_type: str  # "sha256", "dhash", "phash", "ahash", "whash"
    distance: int  # 0 for exact, Hamming distance for perceptual hashes
    threshold: int
    details: str
    transformations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_type": self.match_type,
            "hash_type": self.hash_type,
            "distance": self.distance,
            "threshold": self.threshold,
            "details": self.details,
            "transformations": self.transformations,
        }


@dataclass
class KeeperDecision:
    """Recommendation for which file to retain and why."""

    keeper_path: str
    discard_paths: List[str]
    reason: str
    criteria: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keeper_path": self.keeper_path,
            "discard_paths": self.discard_paths,
            "reason": self.reason,
            "criteria": self.criteria,
            "metrics": self.metrics,
        }


@dataclass
class DuplicateCluster:
    """A cluster of matching or duplicate images."""

    cluster_id: str
    records: List[FileRecord]
    match_category: str  # "exact", "near_duplicate", "mixed"
    pairwise_matches: List[Tuple[str, str, MatchEvidence]] = field(default_factory=list)
    keeper_decision: Optional[KeeperDecision] = None

    @property
    def total_files(self) -> int:
        return len(self.records)

    @property
    def total_bytes(self) -> int:
        return sum(r.size_bytes for r in self.records)

    @property
    def potential_savings_bytes(self) -> int:
        """Bytes that would be reclaimed if only the keeper is kept."""
        if not self.keeper_decision or not self.records:
            return 0
        keeper_path = self.keeper_decision.keeper_path
        return sum(r.size_bytes for r in self.records if r.path != keeper_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "match_category": self.match_category,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "potential_savings_bytes": self.potential_savings_bytes,
            "records": [r.to_dict() for r in self.records],
            "pairwise_matches": [
                {
                    "file_a": a,
                    "file_b": b,
                    "evidence": ev.to_dict(),
                }
                for a, b, ev in self.pairwise_matches
            ],
            "keeper_decision": (
                self.keeper_decision.to_dict() if self.keeper_decision else None
            ),
        }


@dataclass
class ScanSummary:
    """High-level summary of a scan run."""

    total_scanned: int
    total_clusters: int
    total_duplicates: int
    reclaimable_bytes: int
    duration_seconds: float
    cache_hits: int
    cache_misses: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "total_clusters": self.total_clusters,
            "total_duplicates": self.total_duplicates,
            "reclaimable_bytes": self.reclaimable_bytes,
            "duration_seconds": round(self.duration_seconds, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }

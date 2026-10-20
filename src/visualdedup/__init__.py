"""VisualDedup: High-performance visual duplicate detection and dataset cleaning."""

from visualdedup.actions.cleaner import CleanMode, CleanResult
from visualdedup.api import VisualDedup
from visualdedup.core.hasher import (
    compute_ahash,
    compute_dhash,
    compute_file_sha256,
    compute_phash,
    compute_whash,
    extract_image_hashes,
    hamming_distance,
)
from visualdedup.core.keeper import KeeperStrategy
from visualdedup.core.models import (
    DuplicateCluster,
    FileRecord,
    KeeperDecision,
    MatchEvidence,
    ScanSummary,
)
from visualdedup.reports.contact_sheet import generate_cluster_contact_sheet
from visualdedup.reports.html_report import generate_html_report
from visualdedup.reports.json_report import generate_json_report

__version__ = "0.2.0"
__all__ = [
    "VisualDedup",
    "KeeperStrategy",
    "CleanMode",
    "CleanResult",
    "FileRecord",
    "DuplicateCluster",
    "MatchEvidence",
    "KeeperDecision",
    "ScanSummary",
    "compute_file_sha256",
    "compute_dhash",
    "compute_phash",
    "compute_ahash",
    "compute_whash",
    "extract_image_hashes",
    "hamming_distance",
    "generate_json_report",
    "generate_html_report",
    "generate_cluster_contact_sheet",
]

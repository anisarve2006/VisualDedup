"""Intelligent keeper recommendation engine.

Selects the best file to retain from a duplicate cluster based on configurable
criteria (resolution, format fidelity, file size, timestamps) and produces
an auditable decision justification.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, List, Optional

from visualdedup.core.models import FileRecord, KeeperDecision


class KeeperStrategy(str, Enum):
    """Supported keeper selection strategies."""

    BEST_QUALITY = "best_quality"  # High res > lossless format > file size > earliest mtime
    HIGHEST_RESOLUTION = "highest_resolution"  # Maximize pixels (width * height)
    SMALLEST_FILE = "smallest_file"  # Maximize disk savings
    LARGEST_FILE = "largest_file"  # Often least compressed
    OLDEST = "oldest"  # Earliest modified time (original)
    NEWEST = "newest"  # Most recent modified time


# Format fidelity score: Higher is better
FORMAT_SCORES: Dict[str, int] = {
    "PNG": 100,
    "WEBP": 90,
    "TIFF": 85,
    "BMP": 70,
    "JPEG": 60,
    "JPG": 60,
    "GIF": 40,
    "UNKNOWN": 10,
}


def select_keeper(
    records: List[FileRecord],
    strategy: KeeperStrategy = KeeperStrategy.BEST_QUALITY,
    custom_sorter: Optional[Callable[[FileRecord], Any]] = None,
) -> KeeperDecision:
    """Select the best file to keep from a cluster of duplicates and provide justification.

    Args:
        records: List of FileRecord instances in the duplicate cluster.
        strategy: Strategy determining keeper ranking.
        custom_sorter: Optional custom sort key function.

    Returns:
        KeeperDecision with keeper_path, discard_paths, reason, and metrics.
    """
    if not records:
        raise ValueError("Cannot select keeper from empty records list.")

    if len(records) == 1:
        return KeeperDecision(
            keeper_path=records[0].path,
            discard_paths=[],
            reason="Single file in cluster, kept by default.",
            criteria=strategy.value,
            metrics={"resolution": f"{records[0].width}x{records[0].height}"},
        )

    if custom_sorter is not None:
        sorted_records = sorted(records, key=custom_sorter, reverse=True)
        keeper = sorted_records[0]
        reason = "Selected by custom sorting rule."
    elif strategy == KeeperStrategy.BEST_QUALITY:
        def quality_key(r: FileRecord):
            res = r.width * r.height
            fmt = FORMAT_SCORES.get(r.format.upper(), 20)
            size = r.size_bytes
            # Negative mtime so earlier files break ties
            return (res, fmt, size, -r.mtime)

        sorted_records = sorted(records, key=quality_key, reverse=True)
        keeper = sorted_records[0]
        runner_up = sorted_records[1]

        # Generate human justification
        reasons = []
        k_res = keeper.width * keeper.height
        ru_res = runner_up.width * runner_up.height
        if k_res > ru_res:
            reasons.append(
                f"Higher resolution: {keeper.width}x{keeper.height} ({keeper.megapixels} MP) vs {runner_up.width}x{runner_up.height} ({runner_up.megapixels} MP)"
            )
        elif FORMAT_SCORES.get(keeper.format.upper(), 0) > FORMAT_SCORES.get(runner_up.format.upper(), 0):
            reasons.append(f"Preferred lossless/fidelity format: {keeper.format.upper()} vs {runner_up.format.upper()}")
        elif keeper.size_bytes > runner_up.size_bytes:
            reasons.append(f"Higher file size/lower compression: {keeper.size_bytes // 1024} KB vs {runner_up.size_bytes // 1024} KB")
        else:
            reasons.append("Identical quality profile; retained earlier original file")

        reason = "Best Quality: " + "; ".join(reasons)

    elif strategy == KeeperStrategy.HIGHEST_RESOLUTION:
        sorted_records = sorted(records, key=lambda r: (r.width * r.height, r.size_bytes), reverse=True)
        keeper = sorted_records[0]
        reason = f"Highest resolution ({keeper.width}x{keeper.height}, {keeper.megapixels} MP)"

    elif strategy == KeeperStrategy.SMALLEST_FILE:
        sorted_records = sorted(records, key=lambda r: r.size_bytes)
        keeper = sorted_records[0]
        reason = f"Smallest file size ({keeper.size_bytes // 1024} KB) for maximum disk savings"

    elif strategy == KeeperStrategy.LARGEST_FILE:
        sorted_records = sorted(records, key=lambda r: r.size_bytes, reverse=True)
        keeper = sorted_records[0]
        reason = f"Largest file size ({keeper.size_bytes // 1024} KB), preserving maximum detail"

    elif strategy == KeeperStrategy.OLDEST:
        sorted_records = sorted(records, key=lambda r: r.mtime)
        keeper = sorted_records[0]
        reason = f"Oldest file (mtime: {keeper.mtime})"

    elif strategy == KeeperStrategy.NEWEST:
        sorted_records = sorted(records, key=lambda r: r.mtime, reverse=True)
        keeper = sorted_records[0]
        reason = f"Newest file (mtime: {keeper.mtime})"

    else:
        raise ValueError(f"Unknown keeper strategy: {strategy}")

    discard_paths = [r.path for r in sorted_records if r.path != keeper.path]

    metrics = {
        "keeper_resolution": f"{keeper.width}x{keeper.height}",
        "keeper_format": keeper.format,
        "keeper_size_bytes": keeper.size_bytes,
        "discards_count": len(discard_paths),
    }

    return KeeperDecision(
        keeper_path=keeper.path,
        discard_paths=discard_paths,
        reason=reason,
        criteria=strategy.value if hasattr(strategy, "value") else str(strategy),
        metrics=metrics,
    )

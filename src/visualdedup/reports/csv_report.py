"""Structured CSV report exporter for data pipelines, pandas, and spreadsheet workflows."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import List, Optional, Union

from visualdedup.core.models import DuplicateCluster, ScanSummary


def generate_csv_report(
    clusters: List[DuplicateCluster],
    output_path: Optional[Union[str, Path]] = None,
) -> str:
    """Generate a structured tabular CSV report of duplicate clusters and keeper decisions.

    Each row represents a file in a duplicate cluster, indicating whether it is
    marked as KEEPER or DISCARD along with resolution, format, and rationale.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "cluster_id",
        "match_category",
        "role",  # KEEPER or DISCARD
        "file_path",
        "filename",
        "width",
        "height",
        "megapixels",
        "format",
        "mode",
        "size_bytes",
        "exact_hash_sha256",
        "phash",
        "dhash",
        "keeper_reason",
        "cluster_potential_savings_bytes",
    ])

    for cluster in clusters:
        keeper_path = (
            cluster.keeper_decision.keeper_path if cluster.keeper_decision else None
        )
        keeper_reason = (
            cluster.keeper_decision.reason if cluster.keeper_decision else ""
        )

        for rec in cluster.records:
            is_keeper = (rec.path == keeper_path)
            role = "KEEPER" if is_keeper else "DISCARD"

            writer.writerow([
                cluster.cluster_id,
                cluster.match_category,
                role,
                rec.path,
                rec.filename,
                rec.width,
                rec.height,
                rec.megapixels,
                rec.format,
                rec.mode,
                rec.size_bytes,
                rec.exact_hash,
                rec.phash or "",
                rec.dhash or "",
                keeper_reason,
                cluster.potential_savings_bytes,
            ])

    csv_content = output.getvalue()

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            f.write(csv_content)

    return csv_content

"""JSON report exporter for VisualDedup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from visualdedup.core.models import DuplicateCluster, ScanSummary


def generate_json_report(
    clusters: List[DuplicateCluster],
    summary: ScanSummary,
    output_path: Optional[Union[str, Path]] = None,
    indent: int = 2,
) -> str:
    """Generate and optionally save an auditable JSON report of duplicate clusters."""
    data: Dict[str, Any] = {
        "visualdedup_version": "0.2.0",
        "summary": summary.to_dict(),
        "clusters": [cluster.to_dict() for cluster in clusters],
    }

    json_str = json.dumps(data, indent=indent)

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(json_str)

    return json_str

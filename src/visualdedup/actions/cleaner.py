"""Safe cleanup execution engine with audit trail.

Ensures no destructive file operations occur without explicit confirmation,
supporting dry-run simulations, quarantine directories, and auditable action logs.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from visualdedup.core.models import DuplicateCluster


class CleanMode(str, Enum):
    """Execution modes for dataset cleaning."""

    QUARANTINE = "quarantine"  # Move discards to quarantine folder
    BACKUP = "backup"  # Move discards to specified backup path
    DELETE = "delete"  # Permanently remove discards (requires dry_run=False)


@dataclass
class CleanAction:
    file_path: str
    action: str  # "quarantined", "deleted", "backed_up", "simulated"
    destination: Optional[str] = None
    cluster_id: Optional[str] = None
    bytes_reclaimed: int = 0
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "action": self.action,
            "destination": self.destination,
            "cluster_id": self.cluster_id,
            "bytes_reclaimed": self.bytes_reclaimed,
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class CleanResult:
    dry_run: bool
    mode: CleanMode
    actions: List[CleanAction]
    total_files_affected: int
    total_bytes_reclaimed: int
    audit_file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "mode": self.mode.value,
            "total_files_affected": self.total_files_affected,
            "total_bytes_reclaimed": self.total_bytes_reclaimed,
            "audit_file_path": self.audit_file_path,
            "actions": [a.to_dict() for a in self.actions],
        }


def execute_cleanup(
    clusters: List[DuplicateCluster],
    mode: CleanMode = CleanMode.QUARANTINE,
    target_dir: Optional[Union[str, Path]] = None,
    dry_run: bool = True,
    audit_log_path: Optional[Union[str, Path]] = None,
) -> CleanResult:
    """Execute duplicate cleanup plan based on keeper recommendations.

    Args:
        clusters: Clusters with keeper_decision populated.
        mode: CleanMode (quarantine, backup, delete).
        target_dir: Destination folder for quarantine or backup modes.
        dry_run: If True, simulates actions without modifying disk.
        audit_log_path: Where to save execution audit JSON.

    Returns:
        CleanResult containing executed actions and space reclaimed.
    """
    actions: List[CleanAction] = []
    total_bytes = 0

    if not dry_run and mode in (CleanMode.QUARANTINE, CleanMode.BACKUP):
        if not target_dir:
            target_dir = Path(".visualdedup_quarantine")
        dest_base = Path(target_dir)
        dest_base.mkdir(parents=True, exist_ok=True)
    else:
        dest_base = Path(target_dir) if target_dir else None

    for cluster in clusters:
        if not cluster.keeper_decision:
            continue

        discards = cluster.keeper_decision.discard_paths
        records_by_path = {r.path: r for r in cluster.records}

        for path in discards:
            rec = records_by_path.get(path)
            fsize = rec.size_bytes if rec else (os.path.getsize(path) if os.path.exists(path) else 0)

            if dry_run:
                actions.append(
                    CleanAction(
                        file_path=path,
                        action=f"simulated_{mode.value}",
                        destination=str(dest_base / Path(path).name) if dest_base else None,
                        cluster_id=cluster.cluster_id,
                        bytes_reclaimed=fsize,
                    )
                )
                total_bytes += fsize
                continue

            # Actual execution
            try:
                if not os.path.exists(path):
                    actions.append(
                        CleanAction(
                            file_path=path,
                            action="skipped_missing",
                            cluster_id=cluster.cluster_id,
                            error="File does not exist on disk",
                        )
                    )
                    continue

                if mode == CleanMode.DELETE:
                    os.remove(path)
                    actions.append(
                        CleanAction(
                            file_path=path,
                            action="deleted",
                            cluster_id=cluster.cluster_id,
                            bytes_reclaimed=fsize,
                        )
                    )
                    total_bytes += fsize

                elif mode in (CleanMode.QUARANTINE, CleanMode.BACKUP):
                    dest_path = dest_base / f"{cluster.cluster_id}_{Path(path).name}"
                    shutil.move(path, dest_path)
                    actions.append(
                        CleanAction(
                            file_path=path,
                            action="moved",
                            destination=str(dest_path),
                            cluster_id=cluster.cluster_id,
                            bytes_reclaimed=fsize,
                        )
                    )
                    total_bytes += fsize

            except Exception as e:
                actions.append(
                    CleanAction(
                        file_path=path,
                        action="failed",
                        cluster_id=cluster.cluster_id,
                        error=str(e),
                    )
                )

    result = CleanResult(
        dry_run=dry_run,
        mode=mode,
        actions=actions,
        total_files_affected=len([a for a in actions if not a.error and "skipped" not in a.action]),
        total_bytes_reclaimed=total_bytes,
        audit_file_path=str(audit_log_path) if audit_log_path else None,
    )

    if audit_log_path:
        p = Path(audit_log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

    return result

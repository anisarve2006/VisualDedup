"""Safe cleanup and duplicate isolation engine with audit trails.

Supports:
- Storing/organizing duplicates into a separate output directory (copy or move)
- Organizing duplicates by cluster subfolders for easy visual inspection
- Quarantine and backup isolation
- Permanent deletion with strict dry-run guards and auditable action logs
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
    """Execution modes for dataset cleaning and duplicate isolation."""

    QUARANTINE = "quarantine"  # Move discards to quarantine folder
    BACKUP = "backup"  # Move discards to specified backup path
    COPY = "copy"  # Copy duplicates to separate output folder
    MOVE = "move"  # Move duplicates to separate output folder
    DELETE = "delete"  # Permanently remove discards (requires dry_run=False)


@dataclass
class CleanAction:
    file_path: str
    action: str  # "copied", "moved", "quarantined", "deleted", "simulated"
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
    output_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "mode": self.mode.value,
            "total_files_affected": self.total_files_affected,
            "total_bytes_reclaimed": self.total_bytes_reclaimed,
            "audit_file_path": self.audit_file_path,
            "output_dir": self.output_dir,
            "actions": [a.to_dict() for a in self.actions],
        }


def store_duplicates(
    clusters: List[DuplicateCluster],
    output_dir: Union[str, Path],
    action: str = "copy",  # "copy" or "move"
    include_keeper: bool = True,  # If True, stores both keeper and discards for complete side-by-side review
    organize_by_cluster: bool = True,  # Group each duplicate set into its own cluster folder
    tag_filenames: bool = True,  # Prefix with KEEPER_ / DISCARD_
    dry_run: bool = False,
    audit_log_path: Optional[Union[str, Path]] = None,
) -> CleanResult:
    """Store duplicate images in a separate output directory after processing.

    Args:
        clusters: List of duplicate clusters.
        output_dir: Destination directory where duplicates should be stored.
        action: "copy" (safe: keeps originals intact) or "move" (relocates discards).
        include_keeper: If True, copies the keeper alongside discards for complete cluster context.
        organize_by_cluster: If True, creates subfolders per cluster (`output_dir/cluster_0001/`).
        tag_filenames: If True, prefixes files with `KEEPER_` and `DISCARD_`.
        dry_run: If True, simulates actions without disk modifications.
        audit_log_path: Optional file path to write JSON audit manifest.

    Returns:
        CleanResult containing all executed operations.
    """
    dest_base = Path(output_dir).resolve()
    clean_mode = CleanMode.MOVE if action.lower() == "move" else CleanMode.COPY
    actions: List[CleanAction] = []
    total_bytes = 0

    if not dry_run:
        dest_base.mkdir(parents=True, exist_ok=True)

    for cluster in clusters:
        keeper_path = (
            cluster.keeper_decision.keeper_path if cluster.keeper_decision else None
        )
        cluster_folder = dest_base / cluster.cluster_id if organize_by_cluster else dest_base

        if not dry_run and organize_by_cluster:
            cluster_folder.mkdir(parents=True, exist_ok=True)

        for rec in cluster.records:
            is_keeper = (rec.path == keeper_path)

            # Skip keeper if user only requested discards to be moved/copied
            if is_keeper and not include_keeper:
                continue

            # In "move" action, we never move the keeper away unless specifically requested; keeper is copied
            item_action = "copy" if (is_keeper or clean_mode == CleanMode.COPY) else "move"

            prefix = ""
            if tag_filenames:
                prefix = "KEEPER_" if is_keeper else "DISCARD_"
            elif not organize_by_cluster:
                prefix = f"{cluster.cluster_id}_{('KEEPER_' if is_keeper else 'DISCARD_')}"

            dest_filename = f"{prefix}{Path(rec.path).name}"
            dest_file = cluster_folder / dest_filename

            fsize = rec.size_bytes if rec.size_bytes > 0 else (
                os.path.getsize(rec.path) if os.path.exists(rec.path) else 0
            )

            if dry_run:
                actions.append(
                    CleanAction(
                        file_path=rec.path,
                        action=f"simulated_{item_action}",
                        destination=str(dest_file),
                        cluster_id=cluster.cluster_id,
                        bytes_reclaimed=fsize if not is_keeper else 0,
                    )
                )
                if not is_keeper:
                    total_bytes += fsize
                continue

            try:
                if not os.path.exists(rec.path):
                    actions.append(
                        CleanAction(
                            file_path=rec.path,
                            action="skipped_missing",
                            cluster_id=cluster.cluster_id,
                            error="File does not exist on disk",
                        )
                    )
                    continue

                if item_action == "move":
                    shutil.move(rec.path, dest_file)
                    actions.append(
                        CleanAction(
                            file_path=rec.path,
                            action="moved",
                            destination=str(dest_file),
                            cluster_id=cluster.cluster_id,
                            bytes_reclaimed=fsize,
                        )
                    )
                    total_bytes += fsize
                else:
                    shutil.copy2(rec.path, dest_file)
                    actions.append(
                        CleanAction(
                            file_path=rec.path,
                            action="copied",
                            destination=str(dest_file),
                            cluster_id=cluster.cluster_id,
                            bytes_reclaimed=fsize if not is_keeper else 0,
                        )
                    )
                    if not is_keeper and clean_mode == CleanMode.MOVE:
                        total_bytes += fsize

            except Exception as e:
                actions.append(
                    CleanAction(
                        file_path=rec.path,
                        action="failed",
                        cluster_id=cluster.cluster_id,
                        error=str(e),
                    )
                )

    # Save manifest inside output_dir as well
    if not dry_run:
        manifest_path = dest_base / "duplicates_manifest.json"
        manifest_data = {
            "output_directory": str(dest_base),
            "total_clusters": len(clusters),
            "clusters": [c.to_dict() for c in clusters],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

    result = CleanResult(
        dry_run=dry_run,
        mode=clean_mode,
        actions=actions,
        total_files_affected=len([a for a in actions if not a.error and "skipped" not in a.action]),
        total_bytes_reclaimed=total_bytes,
        audit_file_path=str(audit_log_path) if audit_log_path else None,
        output_dir=str(dest_base),
    )

    if audit_log_path:
        p = Path(audit_log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

    return result


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
        mode: CleanMode (quarantine, backup, copy, move, delete).
        target_dir: Destination folder for quarantine, backup, or move/copy modes.
        dry_run: If True, simulates actions without modifying disk.
        audit_log_path: Where to save execution audit JSON.

    Returns:
        CleanResult containing executed actions and space reclaimed.
    """
    if mode in (CleanMode.COPY, CleanMode.MOVE):
        return store_duplicates(
            clusters=clusters,
            output_dir=target_dir or ".visualdedup_duplicates",
            action="move" if mode == CleanMode.MOVE else "copy",
            include_keeper=True,
            organize_by_cluster=True,
            tag_filenames=True,
            dry_run=dry_run,
            audit_log_path=audit_log_path,
        )

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
        output_dir=str(dest_base) if dest_base else None,
    )

    if audit_log_path:
        p = Path(audit_log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

    return result

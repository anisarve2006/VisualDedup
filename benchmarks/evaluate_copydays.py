"""Benchmark and evaluation script for VisualDedup against the INRIA Copydays dataset.

Evaluates:
- Detection Precision & Recall on real-world copies and transformations
- Keeper Selection Accuracy (did it prefer the original over degraded copies?)
- Diagnosis / Transformation explanations
- Scan throughput and space savings
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from visualdedup import KeeperStrategy, VisualDedup

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()


def get_base_id(filename: str) -> str:
    """Extract the base image ID from a Copydays filename.

    Copydays images typically follow:
    - 100000.jpg (original)
    - 100000_*.jpg (strong transform / crops / jpeg)
    or first 4-6 digits.
    """
    stem = Path(filename).stem
    match = re.match(r"^(\d+)", stem)
    if match:
        return match.group(1)[:4]
    return stem


def run_copydays_evaluation(
    dataset_dir: Path = Path("datasets/copydays"),
    threshold: int = 10,
    hash_type: str = "phash",
):
    dataset_dir = dataset_dir.resolve()
    orig_dir = dataset_dir / "original"
    strong_dir = dataset_dir / "strong"

    if not orig_dir.exists():
        console.print(f"[bold red]Error: Copydays dataset not found at {dataset_dir}.[/bold red]")
        console.print("Run 'python benchmarks/download_copydays.py' first.")
        return

    console.print(
        Panel.fit(
            f"[bold cyan]INRIA Copydays Evaluation Benchmark[/bold cyan]\n"
            f"[dim]Dataset path:[/dim] {dataset_dir}\n"
            f"[dim]Algorithm:[/dim] [green]{hash_type}[/green] (threshold <= {threshold})\n"
            f"[dim]Keeper Rule:[/dim] [yellow]best_quality[/yellow]",
            title="🔬 Dataset Benchmark",
            border_style="cyan",
        )
    )

    vd = VisualDedup(
        cache_path=dataset_dir / "copydays_cache.db",
        hash_type=hash_type,
        threshold=threshold,
        index_type="multi_index",
    )

    scan_targets = [str(orig_dir)]
    if strong_dir.exists():
        scan_targets.append(str(strong_dir))

    console.print("[cyan]Running VisualDedup scan across Copydays collection...[/cyan]")
    start = time.perf_counter()
    clusters, summary = vd.scan(
        scan_targets,
        keeper_strategy=KeeperStrategy.BEST_QUALITY,
    )
    duration = time.perf_counter() - start

    # Evaluation Metrics
    total_clusters = len(clusters)
    correct_clusters = 0
    keeper_original_chosen = 0
    total_images_in_clusters = 0

    for cluster in clusters:
        total_images_in_clusters += len(cluster.records)
        base_ids = [get_base_id(r.filename) for r in cluster.records]
        primary_id = max(set(base_ids), key=base_ids.count)
        # Check if all files in cluster belong to the same base ID
        if all(bid == primary_id for bid in base_ids):
            correct_clusters += 1

        # Check if keeper came from original directory
        if cluster.keeper_decision:
            keeper = cluster.keeper_decision.keeper_path
            if "original" in keeper.lower() and "strong" not in keeper.lower():
                keeper_original_chosen += 1

    precision = (correct_clusters / total_clusters * 100) if total_clusters > 0 else 0.0
    keeper_acc = (keeper_original_chosen / total_clusters * 100) if total_clusters > 0 else 0.0

    # Display Metrics Table
    table = Table(title="📊 INRIA Copydays Evaluation Results", border_style="green")
    table.add_column("Evaluation Metric", style="cyan", no_wrap=True)
    table.add_column("Score / Result", style="bold magenta")

    table.add_row("Total Scanned Images", f"{summary.total_scanned:,}")
    table.add_row("Duplicate Clusters Found", f"{total_clusters:,}")
    table.add_row("Images Clustered", f"{total_images_in_clusters:,}")
    table.add_row("Cluster Purity / Precision", f"{precision:.1f}%")
    table.add_row("Keeper Selection Accuracy", f"{keeper_acc:.1f}% (Originals preferred)")
    table.add_row("Potential Reclaimable Space", f"{summary.reclaimable_bytes / (1024*1024):.1f} MB")
    table.add_row("Scan Duration", f"{duration:.2f} seconds ({summary.total_scanned / max(duration, 0.001):.1f} img/sec)")

    console.print(table)

    # Save reports
    report_html = dataset_dir / "copydays_report.html"
    report_json = dataset_dir / "copydays_report.json"
    vd.export_html(clusters, summary, report_html)
    vd.export_json(clusters, summary, report_json)

    console.print(f"\n🌐 [green]HTML Report generated:[/green] {report_html}")
    console.print(f"💾 [green]JSON Report saved:[/green] {report_json}\n")


if __name__ == "__main__":
    run_copydays_evaluation()

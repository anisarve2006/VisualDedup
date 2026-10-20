"""Command-line interface for VisualDedup."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from visualdedup import (
    CleanMode,
    KeeperStrategy,
    VisualDedup,
    compute_ahash,
    compute_dhash,
    compute_file_sha256,
    compute_phash,
    compute_whash,
    extract_image_hashes,
    generate_cluster_contact_sheet,
    hamming_distance,
)
from visualdedup.core.explanation import explain_match
from visualdedup.core.models import FileRecord

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()


def format_size(num_bytes: int) -> str:
    """Format bytes into readable string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute duplicate scan on specified paths."""
    is_json_output = getattr(args, "json", False)

    if not is_json_output:
        console.print(
            Panel.fit(
                f"[bold cyan]VisualDedup v0.2.0[/bold cyan]\n"
                f"[dim]Scanning targets:[/dim] {', '.join(args.paths)}\n"
                f"[dim]Algorithm:[/dim] [green]{args.hash}[/green] (threshold <= {args.threshold}) | [dim]Index:[/dim] {args.index}\n"
                f"[dim]Keeper Rule:[/dim] [yellow]{args.keeper}[/yellow]",
                title="🔍 Scanning Collection",
                border_style="cyan",
            )
        )

    cache_path = None if args.no_cache else args.cache
    keeper_strategy = KeeperStrategy(args.keeper)

    vd = VisualDedup(
        cache_path=cache_path,
        hash_type=args.hash,
        threshold=args.threshold,
        index_type=args.index,
    )

    if not is_json_output:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Hashing & indexing images...", total=100)

            def progress_cb(current: int, total: int):
                progress.update(task, completed=int((current / max(total, 1)) * 100))

            clusters, summary = vd.scan(
                args.paths,
                recursive=not args.no_recursive,
                keeper_strategy=keeper_strategy,
                progress_callback=progress_cb,
                max_workers=args.workers,
            )
    else:
        clusters, summary = vd.scan(
            args.paths,
            recursive=not args.no_recursive,
            keeper_strategy=keeper_strategy,
            max_workers=args.workers,
        )

    # Output structured formats
    if is_json_output:
        json_str = vd.export_json(clusters, summary, args.output)
        print(json_str)
        return 0

    # Display results table
    table = Table(title="📊 Scan Summary", border_style="blue")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Total Scanned Images", str(summary.total_scanned))
    table.add_row("Duplicate Clusters", str(summary.total_clusters))
    table.add_row("Duplicate Images", str(summary.total_duplicates))
    table.add_row("Reclaimable Disk Space", f"[bold green]{format_size(summary.reclaimable_bytes)}[/bold green]")
    table.add_row("Cache Hits / Misses", f"{summary.cache_hits} / {summary.cache_misses}")
    table.add_row("Scan Duration", f"{summary.duration_seconds:.2f} seconds")

    console.print(table)

    # Print duplicate clusters preview
    if clusters:
        console.print(f"\n[bold yellow]Found {len(clusters)} Duplicate Clusters:[/bold yellow]\n")
        for c in clusters[:5]:  # Preview up to first 5
            keeper = c.keeper_decision.keeper_path if c.keeper_decision else None
            console.print(f"[bold cyan]{c.cluster_id}[/bold cyan] ({c.match_category.upper()}) - {len(c.records)} images:")
            if c.keeper_decision:
                console.print(f"  [green]★ KEEPER:[/green] {Path(keeper).name} [dim]({c.keeper_decision.reason})[/dim]")
            for r in c.records:
                if r.path != keeper:
                    console.print(f"  [red]✖ DISCARD:[/red] {Path(r.path).name} [dim]({r.width}x{r.height}, {format_size(r.size_bytes)})[/dim]")
            console.print("")

        if len(clusters) > 5:
            console.print(f"[dim]... and {len(clusters) - 5} more clusters (see report for full list).[/dim]\n")

    # Save reports
    if args.output:
        vd.export_json(clusters, summary, args.output)
        console.print(f"💾 [green]JSON report saved:[/green] {args.output}")

    if getattr(args, "csv", None):
        vd.export_csv(clusters, args.csv)
        console.print(f"📄 [green]CSV report saved:[/green] {args.csv}")

    if args.html:
        vd.export_html(clusters, summary, args.html, embed_thumbnails=not args.no_embed)
        console.print(f"🌐 [green]Visual HTML report saved:[/green] {args.html}")

    if getattr(args, "store_duplicates", None):
        res = vd.store_duplicates(
            clusters,
            output_dir=args.store_duplicates,
            action="copy",
            include_keeper=True,
            organize_by_cluster=not getattr(args, "no_organize", False),
        )
        console.print(f"📁 [bold green]Duplicates stored (copied) in:[/bold green] {res.output_dir} ({res.total_files_affected} files)")

    if getattr(args, "move_duplicates", None):
        res = vd.store_duplicates(
            clusters,
            output_dir=args.move_duplicates,
            action="move",
            include_keeper=False,
            organize_by_cluster=not getattr(args, "no_organize", False),
        )
        console.print(f"📦 [bold green]Duplicates moved to:[/bold green] {res.output_dir} ({res.total_files_affected} files)")

    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Compare two images side-by-side with match explanation."""
    img1, img2 = args.image1, args.image2
    if not os.path.exists(img1) or not os.path.exists(img2):
        console.print("[red]Error: One or both image files do not exist.[/red]")
        return 1

    (w1, h1, fmt1, m1, sha1, dh1, ph1, ah1, wh1) = extract_image_hashes(img1)
    (w2, h2, fmt2, m2, sha2, dh2, ph2, ah2, wh2) = extract_image_hashes(img2)

    sz1 = os.path.getsize(img1)
    sz2 = os.path.getsize(img2)

    rec1 = FileRecord(img1, sz1, os.path.getmtime(img1), w1, h1, fmt1, m1, sha1, dh1, ph1, ah1, wh1)
    rec2 = FileRecord(img2, sz2, os.path.getmtime(img2), w2, h2, fmt2, m2, sha2, dh2, ph2, ah2, wh2)

    table = Table(title="🔍 Side-by-Side Image Inspection", border_style="cyan")
    table.add_column("Property", style="dim", no_wrap=True)
    table.add_column(f"Image 1 ({Path(img1).name})", style="yellow")
    table.add_column(f"Image 2 ({Path(img2).name})", style="magenta")
    table.add_column("Distance / Status", style="green")

    table.add_row("Resolution", f"{w1}x{h1} ({rec1.megapixels} MP)", f"{w2}x{h2} ({rec2.megapixels} MP)", "Identical" if (w1, h1) == (w2, h2) else "Different")
    table.add_row("Format / Mode", f"{fmt1} ({m1})", f"{fmt2} ({m2})", "Match" if (fmt1, m1) == (fmt2, m2) else "Different")
    table.add_row("File Size", format_size(sz1), format_size(sz2), "Identical" if sz1 == sz2 else f"Diff: {format_size(abs(sz1 - sz2))}")
    table.add_row("SHA-256", sha1[:16] + "...", sha2[:16] + "...", "[bold green]Match (Bit-for-bit)[/bold green]" if sha1 == sha2 else "[dim]Distinct[/dim]")

    dh_dist = hamming_distance(dh1, dh2)
    ph_dist = hamming_distance(ph1, ph2)
    ah_dist = hamming_distance(ah1, ah2)
    wh_dist = hamming_distance(wh1, wh2)

    ev = explain_match(rec1, rec2, "phash", ph_dist, 10)

    if getattr(args, "json", False):
        data = {
            "image1": rec1.to_dict(),
            "image2": rec2.to_dict(),
            "distances": {
                "dhash": dh_dist,
                "phash": ph_dist,
                "ahash": ah_dist,
                "whash": wh_dist,
            },
            "diagnosis": ev.to_dict(),
        }
        print(json.dumps(data, indent=2))
        return 0

    table.add_row("dHash (Gradient)", dh1, dh2, f"Hamming: {dh_dist}")
    table.add_row("pHash (DCT)", ph1, ph2, f"Hamming: {ph_dist}")
    table.add_row("aHash (Average)", ah1, ah2, f"Hamming: {ah_dist}")
    table.add_row("wHash (Wavelet)", wh1, wh2, f"Hamming: {wh_dist}")

    console.print(table)

    console.print(
        Panel(
            f"[bold]Diagnosis:[/bold] [yellow]{ev.match_type.upper()}[/yellow]\n"
            f"[bold]Details:[/bold] {ev.details}\n"
            f"[bold]Transformations Detected:[/bold] {', '.join(ev.transformations)}",
            title="💡 Explanation & Evidence",
            border_style="yellow",
        )
    )

    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """Execute or simulate cleanup using keeper recommendations."""
    console.print(
        Panel.fit(
            f"[bold red]VisualDedup Safe Cleanup[/bold red]\n"
            f"Mode: [yellow]{args.mode}[/yellow] | Dry Run: [green]{args.dry_run}[/green]",
            title="🛡️ Dataset Cleaner",
            border_style="red",
        )
    )

    if not args.dry_run and not args.confirm:
        console.print(
            "[bold red]SAFETY CHECK:[/bold red] Permanent changes require either '--dry-run' or '--confirm'.\n"
            "Aborting without modifying files."
        )
        return 1

    vd = VisualDedup(cache_path=args.cache)
    clusters, summary = vd.scan(args.paths, keeper_strategy=KeeperStrategy(args.keeper))

    if not clusters:
        console.print("[green]No duplicate clusters to clean.[/green]")
        return 0

    result = vd.clean(
        clusters=clusters,
        mode=CleanMode(args.mode),
        target_dir=args.target_dir,
        dry_run=args.dry_run,
        audit_log_path=args.audit_log,
    )

    console.print(
        f"Affected files: [cyan]{result.total_files_affected}[/cyan]\n"
        f"Total Space Reclaimed: [bold green]{format_size(result.total_bytes_reclaimed)}[/bold green]"
    )
    if result.audit_file_path:
        console.print(f"Audit log saved: {result.audit_file_path}")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="visualdedup",
        description="VisualDedup: Find duplicate images, explain why they match, recommend keepers, and clean safely.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Sub-commands")

    # scan sub-command
    scan_p = subparsers.add_parser("scan", help="Scan images for exact and visual duplicates")
    scan_p.add_argument("paths", nargs="+", help="Folders or image files to scan")
    scan_p.add_argument("--output", "-o", default=None, help="Save JSON report to file")
    scan_p.add_argument("--csv", default=None, help="Save structured CSV report to file")
    scan_p.add_argument("--json", action="store_true", help="Print structured JSON directly to stdout")
    scan_p.add_argument("--html", default=None, help="Generate interactive HTML visual report")
    scan_p.add_argument("--contact-sheet", default=None, help="Generate visual contact sheet image")
    scan_p.add_argument("--store-duplicates", default=None, help="Copy duplicate images into a separate output directory organized by cluster")
    scan_p.add_argument("--move-duplicates", default=None, help="Move duplicate discards into a separate output directory")
    scan_p.add_argument("--no-organize", action="store_true", help="Store files flattened without cluster subfolders")
    scan_p.add_argument(
        "--hash",
        choices=["phash", "dhash", "ahash", "whash", "exact"],
        default="phash",
        help="Hash algorithm (default: phash)",
    )
    scan_p.add_argument("--threshold", "-t", type=int, default=8, help="Max Hamming distance (default: 8)")
    scan_p.add_argument("--index", choices=["bktree", "multi_index"], default="bktree", help="Search index")
    scan_p.add_argument(
        "--keeper",
        choices=["best_quality", "highest_resolution", "smallest_file", "largest_file", "oldest", "newest"],
        default="best_quality",
        help="Keeper selection rule (default: best_quality)",
    )
    scan_p.add_argument("--cache", default=".visualdedup_cache.db", help="SQLite cache path")
    scan_p.add_argument("--workers", "-w", type=int, default=None, help="Number of CPU worker processes (default: all CPU cores)")
    scan_p.add_argument("--no-cache", action="store_true", help="Disable caching")
    scan_p.add_argument("--no-recursive", action="store_true", help="Do not search subdirectories")
    scan_p.add_argument("--no-embed", action="store_true", help="Do not embed base64 thumbnails in HTML")

    # inspect sub-command
    inspect_p = subparsers.add_parser("inspect", help="Compare two images side-by-side with diagnostics")
    inspect_p.add_argument("image1", help="Path to first image")
    inspect_p.add_argument("image2", help="Path to second image")
    inspect_p.add_argument("--json", action="store_true", help="Output structured JSON instead of table")

    # clean sub-command
    clean_p = subparsers.add_parser("clean", help="Clean duplicates using keeper recommendations")
    clean_p.add_argument("paths", nargs="+", help="Target directories to clean")
    clean_p.add_argument("--mode", choices=["quarantine", "backup", "delete"], default="quarantine")
    clean_p.add_argument("--target-dir", default=".visualdedup_quarantine", help="Quarantine/backup directory")
    clean_p.add_argument("--keeper", choices=["best_quality", "highest_resolution", "smallest_file"], default="best_quality")
    clean_p.add_argument("--dry-run", action="store_true", default=True, help="Simulate without changes")
    clean_p.add_argument("--confirm", action="store_true", help="Confirm execution (disable dry-run)")
    clean_p.add_argument("--audit-log", default="visualdedup_audit.json", help="Audit log path")
    clean_p.add_argument("--cache", default=".visualdedup_cache.db")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "scan":
        return cmd_scan(args)
    elif args.subcommand == "inspect":
        return cmd_inspect(args)
    elif args.subcommand == "clean":
        if args.confirm:
            args.dry_run = False
        return cmd_clean(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())

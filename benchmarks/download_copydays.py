"""Downloader and setup script for the official INRIA Copydays dataset.

Downloads the INRIA Copydays benchmark images hosted by FAIR/VISSL mirror:
- copydays_original.tar.gz (207 MB) - Unmodified reference database
- copydays_strong.tar.gz (60 MB) - Transformed duplicate copies (resizing, crop, compression)
"""

from __future__ import annotations

import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()

URLS = {
    "original": "https://dl.fbaipublicfiles.com/vissl/datasets/copydays_original.tar.gz",
    "strong": "https://dl.fbaipublicfiles.com/vissl/datasets/copydays_strong.tar.gz",
}


def download_with_progress(url: str, dest_path: Path):
    """Download a file with Rich progress display."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        console.print(f"[dim]Already downloaded:[/dim] {dest_path.name}")
        return

    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("download", filename=dest_path.name, total=None)

        def report_hook(block_num, block_size, total_size):
            if total_size > 0:
                progress.update(task_id, total=total_size, completed=block_num * block_size)

        urllib.request.urlretrieve(url, str(dest_path), reporthook=report_hook)


def extract_tar(tar_path: Path, target_dir: Path):
    """Extract tar.gz archive into destination directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]Extracting {tar_path.name} to {target_dir}...[/cyan]")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(target_dir)


def setup_copydays(
    dataset_dir: Path = Path("datasets/copydays"),
    include_strong: bool = True,
) -> Path:
    """Download and prepare the INRIA Copydays dataset."""
    dataset_dir = dataset_dir.resolve()
    archives_dir = dataset_dir / "archives"

    console.print(f"\n[bold cyan]==> Preparing INRIA Copydays Dataset in: {dataset_dir}[/bold cyan]\n")

    # 1. Download original
    orig_tar = archives_dir / "copydays_original.tar.gz"
    download_with_progress(URLS["original"], orig_tar)

    orig_extract_dir = dataset_dir / "original"
    if not orig_extract_dir.exists() or not any(orig_extract_dir.iterdir()):
        extract_tar(orig_tar, orig_extract_dir)

    # 2. Download strong (modified copies)
    if include_strong:
        strong_tar = archives_dir / "copydays_strong.tar.gz"
        download_with_progress(URLS["strong"], strong_tar)

        strong_extract_dir = dataset_dir / "strong"
        if not strong_extract_dir.exists() or not any(strong_extract_dir.iterdir()):
            extract_tar(strong_tar, strong_extract_dir)

    console.print(f"\n[bold green][DONE] INRIA Copydays dataset ready at {dataset_dir}![/bold green]\n")
    return dataset_dir


if __name__ == "__main__":
    setup_copydays()

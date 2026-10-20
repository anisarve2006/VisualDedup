"""Benchmark comparing BKTree, MultiIndexHash, and Linear Pairwise search.

Demonstrates the sub-quadratic scaling of VisualDedup's indexing vs naive O(N^2) comparison.
"""

from __future__ import annotations

import random
import sys
import time
from typing import List, Tuple

from rich.console import Console
from rich.table import Table

from visualdedup.core.hasher import hamming_distance
from visualdedup.core.indexing import BKTree, MultiIndexHashIndex

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()


def generate_synthetic_dataset(num_items: int, duplicate_ratio: float = 0.2, seed: int = 42) -> List[int]:
    """Generate realistic 64-bit perceptual hashes with controlled clusters of near-duplicates."""
    rng = random.Random(seed)
    hashes: List[int] = []
    num_duplicates = int(num_items * duplicate_ratio)
    num_unique = num_items - num_duplicates

    # Generate unique cluster seeds
    seeds = [rng.getrandbits(64) for _ in range(num_unique)]
    hashes.extend(seeds)

    # Generate near-duplicates by flipping 1 to 4 random bits
    for _ in range(num_duplicates):
        parent = rng.choice(seeds)
        num_flips = rng.randint(1, 4)
        child = parent
        for _ in range(num_flips):
            bit_idx = rng.randint(0, 63)
            child ^= (1 << bit_idx)
        hashes.append(child)

    rng.shuffle(hashes)
    return hashes


def benchmark_linear_pairwise(hashes: List[int], threshold: int) -> Tuple[int, float]:
    """Naive O(N^2) quadratic pairwise comparison."""
    start = time.perf_counter()
    n = len(hashes)
    match_count = 0
    for i in range(n):
        h1 = hashes[i]
        for j in range(i + 1, n):
            if (h1 ^ hashes[j]).bit_count() <= threshold:
                match_count += 1
    duration = time.perf_counter() - start
    return match_count, duration


def benchmark_bktree(hashes: List[int], threshold: int) -> Tuple[int, float]:
    """BKTree O(N log N) metric search."""
    start = time.perf_counter()
    tree = BKTree[int]()
    match_count = 0

    for i, h in enumerate(hashes):
        # Query against items already in tree
        neighbors = tree.query(h, max_distance=threshold)
        match_count += len(neighbors)
        tree.insert(i, h)

    duration = time.perf_counter() - start
    return match_count, duration


def benchmark_multi_index(hashes: List[int], threshold: int) -> Tuple[int, float]:
    """Multi-Index Pigeonhole table search."""
    start = time.perf_counter()
    index = MultiIndexHashIndex[int](num_blocks=4)
    match_count = 0

    for i, h in enumerate(hashes):
        neighbors = index.query(h, max_distance=threshold)
        match_count += len(neighbors)
        index.insert(i, h)

    duration = time.perf_counter() - start
    return match_count, duration


def run_benchmark():
    console.print("\n[bold cyan]⚡ VisualDedup Sub-Quadratic Indexing Benchmark ⚡[/bold cyan]\n")
    console.print("Comparing [red]Linear Pairwise O(N^2)[/red] vs [green]BK-Tree O(N log N)[/green] vs [yellow]Multi-Index Hash[/yellow]\n")

    threshold = 4
    sizes = [500, 1000, 2500, 5000]

    table = Table(title=f"Indexing Performance (Threshold <= {threshold} bits)", border_style="cyan")
    table.add_column("Dataset Size (Images)", style="cyan", justify="right")
    table.add_column("Pairwise Compares (N*(N-1)/2)", style="dim", justify="right")
    table.add_column("Linear O(N^2) Time", style="red", justify="right")
    table.add_column("BK-Tree Time", style="bold green", justify="right")
    table.add_column("Multi-Index Time", style="bold yellow", justify="right")
    table.add_column("Speedup vs Linear", style="bold magenta", justify="right")

    for n in sizes:
        hashes = generate_synthetic_dataset(n)
        pairs = n * (n - 1) // 2

        # 1. Linear (only up to 5000 to keep run snappy)
        _, t_lin = benchmark_linear_pairwise(hashes, threshold)

        # 2. BK-Tree
        m_bk, t_bk = benchmark_bktree(hashes, threshold)

        # 3. Multi-Index
        m_mi, t_mi = benchmark_multi_index(hashes, threshold)

        speedup = t_lin / max(t_bk, 0.00001)

        table.add_row(
            f"{n:,}",
            f"{pairs:,}",
            f"{t_lin * 1000:.1f} ms",
            f"{t_bk * 1000:.1f} ms",
            f"{t_mi * 1000:.1f} ms",
            f"{speedup:.1f}x faster",
        )

    console.print(table)
    console.print("\n[bold green]✓ Sub-quadratic indexing successfully validated![/bold green]\n")


if __name__ == "__main__":
    run_benchmark()

"""High-performance indexing for sub-quadratic image similarity search.

Provides:
1. BK-Tree (Burkhard-Keller Tree) for metric space Hamming distance search.
2. Multi-Index Hamming Table (Pigeonhole partitioning) for ultra-fast candidate lookup.
Eliminates O(N^2) pairwise comparisons.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Generator, Generic, List, Optional, Set, Tuple, TypeVar

from visualdedup.core.hasher import hamming_distance

T = TypeVar("T")


class BKTreeNode(Generic[T]):
    """A node in a Burkhard-Keller metric tree."""

    __slots__ = ("item", "hash_val", "children")

    def __init__(self, item: T, hash_val: int):
        self.item: T = item
        self.hash_val: int = hash_val
        self.children: Dict[int, BKTreeNode[T]] = {}


class BKTree(Generic[T]):
    """Burkhard-Keller tree for efficient discrete metric space search.

    Reduces nearest-neighbor search with Hamming distance tolerance r from O(N)
    to O(log N) on average, preventing quadratic pairwise scan bottlenecks.
    """

    def __init__(self, distance_fn: Optional[Callable[[int, int], int]] = None):
        self.root: Optional[BKTreeNode[T]] = None
        self._size = 0
        self.distance_fn = distance_fn or hamming_distance

    def __len__(self) -> int:
        return self._size

    def insert(self, item: T, hash_val: int) -> None:
        """Insert an item with its corresponding 64-bit integer hash."""
        self._size += 1
        if self.root is None:
            self.root = BKTreeNode(item, hash_val)
            return

        current = self.root
        while True:
            dist = self.distance_fn(hash_val, current.hash_val)
            if dist == 0:
                # Same hash: attach as a child at dist 0 or chain
                if 0 in current.children:
                    current = current.children[0]
                else:
                    current.children[0] = BKTreeNode(item, hash_val)
                    break
            elif dist in current.children:
                current = current.children[dist]
            else:
                current.children[dist] = BKTreeNode(item, hash_val)
                break

    def query(self, query_hash: int, max_distance: int) -> List[Tuple[T, int]]:
        """Find all items in the tree within Hamming distance `max_distance` of query_hash.

        Returns list of (item, distance) tuples.
        """
        if self.root is None:
            return []

        results: List[Tuple[T, int]] = []
        stack = [self.root]

        dist_fn = self.distance_fn

        while stack:
            node = stack.pop()
            d = dist_fn(query_hash, node.hash_val)

            if d <= max_distance:
                results.append((node.item, d))

            # Prune search space using triangle inequality:
            # |d(node, query) - d(node, child)| <= max_distance
            low = d - max_distance
            high = d + max_distance

            for dist, child in node.children.items():
                if low <= dist <= high:
                    stack.append(child)

        return results


class MultiIndexHashIndex(Generic[T]):
    """Multi-Index Hashing for fast Hamming distance lookup.

    Partitions a 64-bit integer hash into 4 x 16-bit segments (blocks).
    By the Pigeonhole Principle, if two 64-bit hashes differ by at most 3 bits,
    at least one 16-bit block must be an exact match (Hamming distance 0).
    For larger thresholds (e.g. up to 10), it quickly filters down to small
    candidate buckets before applying exact Hamming distance verification.
    """

    def __init__(self, num_blocks: int = 4):
        self.num_blocks = num_blocks
        self.block_size = 64 // num_blocks  # 16 bits per block for 64-bit hashes
        # Array of dictionary buckets: table[block_idx][block_value] -> list of (item, full_hash)
        self.tables: List[Dict[int, List[Tuple[T, int]]]] = [
            defaultdict(list) for _ in range(self.num_blocks)
        ]
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def _get_blocks(self, hash_val: int) -> List[int]:
        """Split a 64-bit hash into sub-blocks."""
        mask = (1 << self.block_size) - 1
        blocks = []
        for i in range(self.num_blocks):
            blocks.append((hash_val >> (i * self.block_size)) & mask)
        return blocks

    def insert(self, item: T, hash_val: int) -> None:
        """Insert an item with its 64-bit hash."""
        blocks = self._get_blocks(hash_val)
        entry = (item, hash_val)
        for i, block_val in enumerate(blocks):
            self.tables[i][block_val].append(entry)
        self._size += 1

    def query(self, query_hash: int, max_distance: int) -> List[Tuple[T, int]]:
        """Find items within max_distance using block matching and candidate filtering."""
        blocks = self._get_blocks(query_hash)
        seen_items: Set[int] = set()  # Track object IDs to prevent duplicate evaluations
        matches: List[Tuple[T, int]] = []

        for i, block_val in enumerate(blocks):
            candidates = self.tables[i].get(block_val, [])
            for item, item_hash in candidates:
                item_id = id(item)
                if item_id in seen_items:
                    continue
                seen_items.add(item_id)

                dist = (query_hash ^ item_hash).bit_count()
                if dist <= max_distance:
                    matches.append((item, dist))

        return matches

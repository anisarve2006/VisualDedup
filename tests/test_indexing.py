"""Unit tests for BKTree and MultiIndexHashIndex sub-quadratic search."""

import random

from visualdedup.core.hasher import hamming_distance
from visualdedup.core.indexing import BKTree, MultiIndexHashIndex


def test_bktree_exact_and_near_queries():
    tree = BKTree[str]()

    base_hash = 0x123456789ABCDEF0
    tree.insert("base", base_hash)

    # Hashes with 1 bit diff, 2 bit diff, and 20 bits diff
    diff1_hash = base_hash ^ (1 << 5)
    diff2_hash = base_hash ^ (1 << 12) ^ (1 << 15)
    far_hash = base_hash ^ 0xFFFFF00000000000

    tree.insert("diff1", diff1_hash)
    tree.insert("diff2", diff2_hash)
    tree.insert("far", far_hash)

    # Query with radius 0
    res_exact = tree.query(base_hash, max_distance=0)
    assert len(res_exact) == 1
    assert res_exact[0][0] == "base"
    assert res_exact[0][1] == 0

    # Query with radius 2
    res_near = tree.query(base_hash, max_distance=2)
    found_items = {item for item, d in res_near}
    assert found_items == {"base", "diff1", "diff2"}
    assert "far" not in found_items


def test_multi_index_hash_lookup():
    index = MultiIndexHashIndex[str](num_blocks=4)

    base_hash = 0xAAAAAAAAAAAAAAAA
    index.insert("item1", base_hash)

    # Differs by 2 bits in first 16-bit block, rest blocks identical
    diff2_hash = base_hash ^ 0b11
    index.insert("item2", diff2_hash)

    # Differs completely
    far_hash = 0x5555555555555555
    index.insert("item_far", far_hash)

    matches = index.query(base_hash, max_distance=3)
    found = {item for item, d in matches}
    assert "item1" in found
    assert "item2" in found
    assert "item_far" not in found


def test_indexing_scale_correctness():
    """Verify BKTree finds same ground-truth candidates as brute force across 500 items."""
    rng = random.Random(42)
    hashes = [rng.getrandbits(64) for _ in range(500)]

    tree = BKTree[int]()
    for i, h in enumerate(hashes):
        tree.insert(i, h)

    query_h = hashes[0]
    radius = 10

    # Ground truth brute force
    expected = {i for i, h in enumerate(hashes) if hamming_distance(query_h, h) <= radius}

    # BKTree search
    tree_results = {item for item, d in tree.query(query_h, max_distance=radius)}

    assert tree_results == expected

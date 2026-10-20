"""Unit tests for Keeper selection and SQLite caching."""

import os
from pathlib import Path

from visualdedup.core.cache import HashCache
from visualdedup.core.keeper import KeeperStrategy, select_keeper
from visualdedup.core.models import FileRecord


def test_keeper_best_quality_resolution_precedence():
    high_res = FileRecord("high.jpg", 30000, 100.0, 3000, 2000, "JPEG", "RGB", "sha1")
    low_res = FileRecord("low.jpg", 8000, 90.0, 1500, 1000, "JPEG", "RGB", "sha2")

    decision = select_keeper([low_res, high_res], strategy=KeeperStrategy.BEST_QUALITY)
    assert decision.keeper_path == "high.jpg"
    assert "Higher resolution" in decision.reason
    assert "low.jpg" in decision.discard_paths


def test_keeper_format_preference():
    png_lossless = FileRecord("photo.png", 50000, 100.0, 1000, 1000, "PNG", "RGB", "sha1")
    jpg_lossy = FileRecord("photo.jpg", 20000, 90.0, 1000, 1000, "JPEG", "RGB", "sha2")

    decision = select_keeper([jpg_lossy, png_lossless], strategy=KeeperStrategy.BEST_QUALITY)
    assert decision.keeper_path == "photo.png"
    assert "Preferred lossless" in decision.reason


def test_keeper_smallest_file_strategy():
    rec1 = FileRecord("big.png", 50000, 100.0, 1000, 1000, "PNG", "RGB", "sha1")
    rec2 = FileRecord("small.webp", 15000, 100.0, 1000, 1000, "WEBP", "RGB", "sha2")

    decision = select_keeper([rec1, rec2], strategy=KeeperStrategy.SMALLEST_FILE)
    assert decision.keeper_path == "small.webp"


def test_cache_hit_and_invalidation(temp_dir):
    db_file = temp_dir / "cache.db"
    cache = HashCache(db_file)

    rec = FileRecord("test.jpg", 1024, 123456.0, 800, 600, "JPEG", "RGB", "sha_x", "d1", "p1")
    cache.upsert_record(rec)

    # Exact size and mtime -> HIT
    hit = cache.get_valid_record("test.jpg", 1024, 123456.0)
    assert hit is not None
    assert hit.exact_hash == "sha_x"

    # Changed size or mtime -> MISS
    miss = cache.get_valid_record("test.jpg", 2048, 123456.0)
    assert miss is None

    cache.close()

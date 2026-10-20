"""Incremental SQLite cache for fast image hash persistence.

Ensures subsequent scans only compute hashes for modified or new files,
dramatically speeding up dataset processing.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from visualdedup.core.models import FileRecord


class HashCache:
    """SQLite-backed cache for image metadata and hashes."""

    def __init__(self, db_path: Union[str, Path] = ".visualdedup_cache.db"):
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_cache (
                    path TEXT PRIMARY KEY,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    exact_hash TEXT NOT NULL,
                    dhash TEXT,
                    phash TEXT,
                    ahash TEXT,
                    whash TEXT,
                    scanned_at REAL NOT NULL
                );
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_exact_hash ON image_cache(exact_hash);"
            )

    def get_valid_record(self, filepath: str, size: int, mtime: float) -> Optional[FileRecord]:
        """Retrieve cached record if file size and mtime still match (cache hit)."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT path, size_bytes, mtime, width, height, format, mode,
                   exact_hash, dhash, phash, ahash, whash
            FROM image_cache
            WHERE path = ? AND size_bytes = ? AND ABS(mtime - ?) < 0.001
            """,
            (filepath, size, mtime),
        )
        row = cur.fetchone()
        if not row:
            return None

        return FileRecord(
            path=row[0],
            size_bytes=row[1],
            mtime=row[2],
            width=row[3],
            height=row[4],
            format=row[5],
            mode=row[6],
            exact_hash=row[7],
            dhash=row[8],
            phash=row[9],
            ahash=row[10],
            whash=row[11],
        )

    def get_valid_records_batch(
        self, file_stats: List[Tuple[str, int, float]]
    ) -> Dict[str, FileRecord]:
        """Batch retrieve valid cached records for a list of (path, size, mtime) tuples."""
        if not file_stats:
            return {}

        results: Dict[str, FileRecord] = {}
        # Query in chunks of 500 to stay safely below SQLite variable limits
        chunk_size = 500
        cur = self.conn.cursor()

        stat_map = {item[0]: (item[1], item[2]) for item in file_stats}

        for i in range(0, len(file_stats), chunk_size):
            chunk = file_stats[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            paths = [item[0] for item in chunk]

            cur.execute(
                f"""
                SELECT path, size_bytes, mtime, width, height, format, mode,
                       exact_hash, dhash, phash, ahash, whash
                FROM image_cache
                WHERE path IN ({placeholders})
                """,
                paths,
            )

            for row in cur.fetchall():
                path, size, mtime = row[0], row[1], row[2]
                expected_size, expected_mtime = stat_map.get(path, (-1, -1))
                if size == expected_size and abs(mtime - expected_mtime) < 0.001:
                    results[path] = FileRecord(
                        path=path,
                        size_bytes=size,
                        mtime=mtime,
                        width=row[3],
                        height=row[4],
                        format=row[5],
                        mode=row[6],
                        exact_hash=row[7],
                        dhash=row[8],
                        phash=row[9],
                        ahash=row[10],
                        whash=row[11],
                    )

        return results

    def upsert_record(self, record: FileRecord) -> None:
        """Insert or replace a record in the cache."""
        now = time.time()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO image_cache (
                    path, size_bytes, mtime, width, height, format, mode,
                    exact_hash, dhash, phash, ahash, whash, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.path,
                    record.size_bytes,
                    record.mtime,
                    record.width,
                    record.height,
                    record.format,
                    record.mode,
                    record.exact_hash,
                    record.dhash,
                    record.phash,
                    record.ahash,
                    record.whash,
                    now,
                ),
            )

    def upsert_records_batch(self, records: List[FileRecord]) -> None:
        """Batch insert/update for high throughput."""
        now = time.time()
        rows = [
            (
                r.path,
                r.size_bytes,
                r.mtime,
                r.width,
                r.height,
                r.format,
                r.mode,
                r.exact_hash,
                r.dhash,
                r.phash,
                r.ahash,
                r.whash,
                now,
            )
            for r in records
        ]
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO image_cache (
                    path, size_bytes, mtime, width, height, format, mode,
                    exact_hash, dhash, phash, ahash, whash, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_exact_hash_groups(self) -> Dict[str, List[str]]:
        """Find all files with matching exact SHA-256 hashes using SQL index."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT exact_hash, path
            FROM image_cache
            WHERE exact_hash IN (
                SELECT exact_hash
                FROM image_cache
                GROUP BY exact_hash
                HAVING COUNT(*) > 1
            )
            ORDER BY exact_hash;
            """
        )
        groups: Dict[str, List[str]] = {}
        for h, path in cur.fetchall():
            if h not in groups:
                groups[h] = []
            groups[h].append(path)
        return groups

    def prune_missing(self, active_paths: Set[str]) -> int:
        """Remove entries from cache that no longer exist on disk."""
        cur = self.conn.cursor()
        cur.execute("SELECT path FROM image_cache;")
        all_cached = [row[0] for row in cur.fetchall()]
        stale = [p for p in all_cached if p not in active_paths or not os.path.exists(p)]
        if stale:
            with self.conn:
                self.conn.executemany(
                    "DELETE FROM image_cache WHERE path = ?;", [(p,) for p in stale]
                )
        return len(stale)

    def clear(self) -> None:
        """Clear all cache data."""
        with self.conn:
            self.conn.execute("DELETE FROM image_cache;")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

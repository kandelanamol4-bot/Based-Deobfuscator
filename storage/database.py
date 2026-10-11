"""SQLite job metadata (no source code). Optional via ENABLE_JOB_HISTORY."""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path


class Database:
    def __init__(self, path: Path, enabled: bool):
        self.path = path
        self.enabled = enabled
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as c:
                c.execute(
                    """CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, user_id INTEGER, filename TEXT,
                    engine TEXT, status TEXT, created REAL, duration REAL,
                    in_bytes INTEGER, out_bytes INTEGER)"""
                )

    def record(self, job, engine: str = ""):
        if not self.enabled:
            return
        try:
            with sqlite3.connect(self.path) as c:
                c.execute(
                    "INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                    (job.id, job.user_id, job.filename, engine,
                     str(job.status.value if hasattr(job.status, 'value') else job.status),
                     job.created_at, job.processing_time,
                     job.original_size, job.output_size),
                )
        except Exception:
            pass

    def recent(self, user_id: int, limit: int = 5) -> list[tuple]:
        if not self.enabled:
            return []
        try:
            with sqlite3.connect(self.path) as c:
                return c.execute(
                    "SELECT id,filename,engine,status,created,duration FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        except Exception:
            return []

    def purge_older_than(self, days: int):
        if not self.enabled:
            return
        cutoff = time.time() - days * 86400
        try:
            with sqlite3.connect(self.path) as c:
                c.execute("DELETE FROM jobs WHERE created < ?", (cutoff,))
        except Exception:
            pass

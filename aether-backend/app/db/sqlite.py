"""Thin SQLite wrapper: one connection, one process-wide lock, WAL mode.

The whole backend runs in one process with a handful of worker threads,
so a single serialized connection is simpler and safer than a pool. When
the hosted phase arrives this module is the seam: swap the connection for
PostgreSQL without touching the stores that sit on top of it.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from ..core.config import get_settings

SCHEMA_VERSION = 1

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id  TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        stage       TEXT NOT NULL DEFAULT 'CREATED',
        scene_ids   TEXT NOT NULL DEFAULT '[]',
        room_hints  TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS inputs (
        input_id     TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(project_id),
        kind         TEXT NOT NULL,
        filename     TEXT NOT NULL,
        path         TEXT NOT NULL,
        content_type TEXT NOT NULL DEFAULT '',
        size_bytes   INTEGER NOT NULL DEFAULT 0,
        meta         TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS inputs_project ON inputs(project_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(project_id),
        kind        TEXT NOT NULL,
        version     INTEGER NOT NULL DEFAULT 1,
        path        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS analyses_project ON analyses(project_id, kind, version)",
    """
    CREATE TABLE IF NOT EXISTS scene_specs (
        spec_id    TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        scene_id   TEXT NOT NULL,
        version    INTEGER NOT NULL,
        path       TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id       TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(project_id),
        type         TEXT NOT NULL,
        lane         TEXT NOT NULL,
        status       TEXT NOT NULL,
        attempt      INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        checkpoint   TEXT NOT NULL DEFAULT '',
        error        TEXT NOT NULL DEFAULT '',
        params       TEXT NOT NULL DEFAULT '{}',
        result       TEXT NOT NULL DEFAULT '{}',
        log_path     TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL,
        started_at   TEXT NOT NULL DEFAULT '',
        finished_at  TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status)",
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  TEXT NOT NULL,
        job_id      TEXT NOT NULL DEFAULT '',
        stage       TEXT NOT NULL,
        status      TEXT NOT NULL,
        message     TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        ts          TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS events_project ON events(project_id, event_id)",
    """
    CREATE TABLE IF NOT EXISTS outputs (
        output_id  TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        kind       TEXT NOT NULL,
        path       TEXT NOT NULL,
        url        TEXT NOT NULL DEFAULT '',
        meta       TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS outputs_project ON outputs(project_id, kind)",
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # ── schema ───────────────────────────────────────────────────
    def _migrate(self) -> None:
        with self.tx() as c:
            for stmt in SCHEMA:
                c.execute(stmt)
            c.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # ── access ───────────────────────────────────────────────────
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        with self.tx() as c:
            c.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db
    with _db_lock:
        if _db is None:
            _db = Database(get_settings().db_path)
        return _db


def reset_db() -> None:
    """Close and forget the singleton (tests, or data-dir switches)."""
    global _db
    with _db_lock:
        if _db is not None:
            try:
                _db.close()
            except Exception:
                pass
        _db = None

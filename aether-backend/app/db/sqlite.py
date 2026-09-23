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
from typing import Any, Callable, Iterator, Optional

from ..core.config import get_settings

SCHEMA_VERSION = 9

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
        vertical    TEXT NOT NULL DEFAULT 'residential',
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


# ── migrations ───────────────────────────────────────────────────────────
# The CREATE statements above only ever build a *fresh* database; anything
# that changes an existing one goes here. Each step takes the open
# connection, must be safe to run twice, and is appended as (version, fn)
# with version == the SCHEMA_VERSION that introduced it.


def _add_column(c: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ... ADD COLUMN, skipped when the column already exists."""
    existing = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _v2_project_vertical(c: sqlite3.Connection) -> None:
    """projects.vertical — the market a project is designed for. The NOT NULL
    DEFAULT backfills existing rows to 'residential' as SQLite adds it."""
    _add_column(c, "projects", "vertical", "TEXT NOT NULL DEFAULT 'residential'")
    c.execute("UPDATE projects SET vertical = 'residential' WHERE COALESCE(vertical, '') = ''")


def _v3_identity(c: sqlite3.Connection) -> None:
    """users + sessions — P0-SEC-001. Additive only: nothing existing changes,
    no route reads these yet, and a database that has never seen a user is
    exactly as usable afterwards as before.

    `password_hash` and `external_id` are BOTH nullable on purpose. AUTH_PLAN.md
    leaves the A/B/C identity decision open: option B fills password_hash,
    options A and C fill external_id. Shipping only one column would quietly
    make that decision inside a migration.

    CREATE TABLE IF NOT EXISTS makes this safe to run twice, which the ladder
    requires — _recorded_version() replays every step from 0 whenever the
    marker is missing or unreadable.
    """
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            role          TEXT NOT NULL DEFAULT 'homeowner',
            password_hash TEXT,
            external_id   TEXT,
            created_at    TEXT NOT NULL,
            disabled_at   TEXT
        )"""
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )"""
    )
    # Revoking every session for one user is a full scan without this, and that
    # scan is what runs on the day somebody loses a laptop.
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def _v4_project_ownership(c: sqlite3.Connection) -> None:
    """projects.owner_id + project_members — P0-SEC-002.

    `owner_id` is deliberately NULLABLE with no default. There is no user to
    point existing rows at: this database predates the users table by three
    schema versions. A NOT NULL DEFAULT would have to invent an owner, and an
    invented owner is worse than an honest NULL — NULL means "nobody has
    claimed this yet", which `authz.py` treats as unowned and only an admin may
    read. The first administrator adopts them (see `claim_unowned_projects`).

    `project_members` is the sharing join: a designer is assigned to a project
    rather than owning it. Roles here are per-project and independent of
    `users.role`, which is why this is a table and not a column.
    """
    _add_column(c, "projects", "owner_id", "TEXT")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL,
            user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role       TEXT NOT NULL DEFAULT 'designer',
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        )"""
    )
    # "which projects can I see" runs on every list; without this it is a scan.
    c.execute("CREATE INDEX IF NOT EXISTS idx_members_user ON project_members(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")


def _v5_spend_ledger(c: sqlite3.Connection) -> None:
    """spend_records + jobs.created_by — P0-SEC-003.

    Money spent has to be remembered on DISK. An in-memory counter resets on
    restart, and "restart the process" is not an acceptable way to clear a
    spending limit. Every row here is one real charge.

    `credits` is what the provider actually reported consuming. `is_estimate`
    exists so a figure we had to guess (a task that vanished, a response with
    no credit field) can never be silently added up as though it were measured
    — an estimated total that looks measured is how a budget quietly becomes
    fiction.

    `jobs.created_by` records WHO asked. It is a column rather than a key in
    `params` because `POST /projects/{id}/jobs` lets the caller supply `params`
    wholesale: a user id in there would be forgeable, which is the opposite of
    an audit trail. Empty string means the job predates this column or was
    raised by the runner itself on restart.
    """
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS spend_records (
            record_id   TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL,
            user_id     TEXT,
            job_id      TEXT NOT NULL DEFAULT '',
            provider    TEXT NOT NULL DEFAULT 'meshy',
            item_key    TEXT NOT NULL DEFAULT '',
            credits     INTEGER NOT NULL DEFAULT 0,
            is_estimate INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_spend_project ON spend_records(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_spend_user ON spend_records(user_id)")
    _add_column(c, "jobs", "created_by", "TEXT NOT NULL DEFAULT ''")


def _v6_capability_tokens(c: sqlite3.Connection) -> None:
    """capability_tokens — P0-SEC-004.

    A share link is not a session. It identifies nobody, grants exactly one
    thing on exactly one project, and can be torn up without touching anyone's
    account. That is a different shape from `sessions`, which is why it is a
    different table rather than a session with odd flags.

    Only the SHA-256 of the token is stored, as with sessions: a database leak
    must not hand over working share links.

    `scope` exists so a link can never quietly become a skeleton key. Today the
    only value is 'tour'; the column is here so widening is a deliberate act
    with a name, not an accident of reusing an existing token.
    """
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_tokens (
            token_hash TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            scope      TEXT NOT NULL DEFAULT 'tour',
            created_by TEXT,
            label      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT
        )"""
    )
    # "show me the links I have given out for this project" runs on the share
    # panel; without this it is a scan of every link ever minted.
    c.execute("CREATE INDEX IF NOT EXISTS idx_capability_project ON capability_tokens(project_id)")


def _v7_correlation_ids(c: sqlite3.Connection) -> None:
    """projects.correlation_id + jobs.correlation_id — P0-OBSERVABILITY-001.

    One id per project run, carried onto every job it spawns and every log line
    either writes. Filtering a log stream by it returns the whole run — which is
    the difference between "a customer says it failed" and knowing where.

    On the JOB as well as the project, deliberately. The runner binds log
    context before it can safely touch the project store (a lookup that itself
    fails is exactly when the ids matter), so the job row carries its own copy.
    Denormalised on purpose; it is written once and never changes.

    Existing projects get a minted id rather than an empty string: a NULL
    correlation id would mean "this run cannot be traced", which is true of
    nothing here — these projects simply predate the column.
    """
    import uuid

    _add_column(c, "projects", "correlation_id", "TEXT NOT NULL DEFAULT ''")
    _add_column(c, "jobs", "correlation_id", "TEXT NOT NULL DEFAULT ''")
    for row in c.execute(
        "SELECT project_id FROM projects WHERE COALESCE(correlation_id, '') = ''"
    ).fetchall():
        c.execute(
            "UPDATE projects SET correlation_id = ? WHERE project_id = ?",
            ("cid_" + uuid.uuid4().hex[:12], row["project_id"]),
        )
    # Jobs inherit their project's id, so a run that predates this migration is
    # still one thread rather than a job with no lineage.
    c.execute(
        "UPDATE jobs SET correlation_id = ("
        "  SELECT p.correlation_id FROM projects p WHERE p.project_id = jobs.project_id"
        ") WHERE COALESCE(correlation_id, '') = ''"
        "  AND EXISTS (SELECT 1 FROM projects p WHERE p.project_id = jobs.project_id)"
    )


def _v8_element_index(c: sqlite3.Connection) -> None:
    """elements + element_instances — P1-IDENTITY-005.

    A DERIVED INDEX, not a second record. The truth stays in
    `planning/scene_reading.json` and `planning/scene_spec.json`; these tables
    exist because the questions the chain has to answer run the wrong way for
    a file. "Which element is this rendered object?" means opening three JSON
    documents and scanning them; "which projects hold a mesh generated from
    this element?" cannot be answered from one project's files at all.

    So every row here is reproducible from disk by `index_project()`, which
    deletes the project's rows and rewrites them. That is the whole recovery
    procedure: a stale or missing index is an inconvenience, never data loss.

    No foreign keys, deliberately. An FK to `projects` would make the index a
    participant in deletion rather than a follower of it, and `PRAGMA
    foreign_keys=ON` would then turn a re-index of a project whose row is
    momentarily absent into an error. A dangling row here is a stale cache
    entry; `clear_index()` removes it when a project is deleted.

    `scene_object_id` is on the instance row rather than in a third table
    because it is one-to-one: an instance is placed once. It is empty when the
    scene has not been compiled yet, which is a normal state, not a fault.
    """
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS elements (
            project_id         TEXT NOT NULL,
            element_id         TEXT NOT NULL,
            room_id            TEXT NOT NULL DEFAULT '',
            semantic_type      TEXT NOT NULL DEFAULT '',
            canonical_name     TEXT NOT NULL DEFAULT '',
            identity_method    TEXT NOT NULL DEFAULT '',
            instance_count     INTEGER NOT NULL DEFAULT 0,
            canonical_asset_id TEXT NOT NULL DEFAULT '',
            source_element_ids TEXT NOT NULL DEFAULT '[]',
            indexed_at         TEXT NOT NULL,
            PRIMARY KEY (project_id, element_id)
        )"""
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS element_instances (
            project_id        TEXT NOT NULL,
            instance_id       TEXT NOT NULL,
            element_id        TEXT NOT NULL,
            room_id           TEXT NOT NULL DEFAULT '',
            source_element_id TEXT NOT NULL DEFAULT '',
            crop_ref          TEXT NOT NULL DEFAULT '',
            scene_object_id   TEXT NOT NULL DEFAULT '',
            asset_id          TEXT NOT NULL DEFAULT '',
            indexed_at        TEXT NOT NULL,
            PRIMARY KEY (project_id, instance_id)
        )"""
    )
    # The three lookups the provenance endpoint actually performs.
    c.execute("CREATE INDEX IF NOT EXISTS idx_elinst_object "
              "ON element_instances(project_id, scene_object_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_elinst_source "
              "ON element_instances(project_id, source_element_id)")
    # Cross-project, and the reason a file cannot answer it: "what else was
    # built from the mesh we paid for?"
    c.execute("CREATE INDEX IF NOT EXISTS idx_elements_asset "
              "ON elements(canonical_asset_id)")


def _v9_generation_tasks(c: sqlite3.Connection) -> None:
    """generation_tasks — P1-ASSET-002, the fourth spend gate.

    One row per vendor generation REQUEST, keyed by what was asked for
    (canonical piece key + the exact crop bytes + the parameters). Written the
    moment a task id comes back, before anything waits on it, so a job killed
    mid-generation leaves the receipt behind: the retry finds the row, polls
    that task, and never submits - and never pays - a second time.

    Same discipline as spend_records: on disk before it is relied on, so a
    process restart cannot forget an in-flight purchase.
    """
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_tasks (
            request_id   TEXT PRIMARY KEY,
            project_id   TEXT NOT NULL,
            job_id       TEXT NOT NULL DEFAULT '',
            item_key     TEXT NOT NULL DEFAULT '',
            element_id   TEXT NOT NULL DEFAULT '',
            image_sha256 TEXT NOT NULL DEFAULT '',
            params       TEXT NOT NULL DEFAULT '{}',
            provider     TEXT NOT NULL DEFAULT 'meshy',
            endpoint     TEXT NOT NULL DEFAULT '',
            task_id      TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'SUBMITTED',
            asset_id     TEXT NOT NULL DEFAULT '',
            credits      INTEGER,
            error        TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_gentask_project ON generation_tasks(project_id, status)")


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (2, _v2_project_vertical),
    (3, _v3_identity),
    (4, _v4_project_ownership),
    (5, _v5_spend_ledger),
    (6, _v6_capability_tokens),
    (7, _v7_correlation_ids),
    (8, _v8_element_index),
    (9, _v9_generation_tasks),
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
            current = self._recorded_version(c)
            for version, step in MIGRATIONS:
                if current < version:
                    step(c)
            c.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _recorded_version(c: sqlite3.Connection) -> int:
        """Schema version stamped in meta. An absent or unreadable marker
        means 0, which replays every step — they are all idempotent."""
        row = c.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        try:
            return int(row["value"]) if row is not None else 0
        except (TypeError, ValueError):
            return 0

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

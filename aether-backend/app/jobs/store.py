"""SQLite-backed job and event store."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from ..db import Database, get_db
from .schema import Job, JobEvent, JobLane, JobStatus


class JobNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row) -> Job:
    return Job(
        job_id=row["job_id"],
        project_id=row["project_id"],
        type=row["type"],
        lane=JobLane(row["lane"]),
        status=JobStatus(row["status"]),
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        checkpoint=row["checkpoint"],
        error=row["error"],
        params=json.loads(row["params"]),
        result=json.loads(row["result"]),
        log_path=row["log_path"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _row_to_event(row) -> JobEvent:
    return JobEvent(
        event_id=row["event_id"],
        project_id=row["project_id"],
        job_id=row["job_id"],
        stage=row["stage"],
        status=row["status"],
        message=row["message"],
        duration_ms=row["duration_ms"],
        ts=row["ts"],
    )


class JobStore:
    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()

    # ── jobs ─────────────────────────────────────────────────────
    def create(
        self,
        project_id: str,
        type: str,
        lane: JobLane,
        params: Optional[dict[str, Any]] = None,
        max_attempts: int = 3,
        log_path: str = "",
    ) -> Job:
        job = Job(
            project_id=project_id,
            type=type,
            lane=lane,
            params=params or {},
            max_attempts=max_attempts,
            log_path=log_path,
            created_at=_now(),
        )
        self._db.execute(
            """INSERT INTO jobs(job_id, project_id, type, lane, status, attempt, max_attempts,
                                checkpoint, error, params, result, log_path, created_at,
                                started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.job_id,
                job.project_id,
                job.type,
                job.lane.value,
                job.status.value,
                job.attempt,
                job.max_attempts,
                job.checkpoint,
                job.error,
                json.dumps(job.params),
                json.dumps(job.result),
                job.log_path,
                job.created_at,
                job.started_at,
                job.finished_at,
            ),
        )
        return job

    def get(self, job_id: str) -> Job:
        row = self._db.one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        if row is None:
            raise JobNotFound(job_id)
        return _row_to_job(row)

    def list_for_project(self, project_id: str, limit: int = 50) -> list[Job]:
        rows = self._db.query(
            "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_job(r) for r in rows]

    def latest_of_type(self, project_id: str, type: str) -> Optional[Job]:
        row = self._db.one(
            "SELECT * FROM jobs WHERE project_id = ? AND type = ? ORDER BY created_at DESC LIMIT 1",
            (project_id, type),
        )
        return None if row is None else _row_to_job(row)

    def unfinished(self) -> list[Job]:
        rows = self._db.query(
            "SELECT * FROM jobs WHERE status IN ('QUEUED','RUNNING','RETRYING') ORDER BY created_at ASC"
        )
        return [_row_to_job(r) for r in rows]

    def update(self, job_id: str, **fields: Any) -> Job:
        if not fields:
            return self.get(job_id)
        cols, vals = [], []
        for key, value in fields.items():
            if key in ("params", "result"):
                value = json.dumps(value)
            elif isinstance(value, (JobStatus, JobLane)):
                value = value.value
            cols.append(f"{key} = ?")
            vals.append(value)
        vals.append(job_id)
        self._db.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id = ?", tuple(vals))
        return self.get(job_id)

    # ── events ───────────────────────────────────────────────────
    def add_event(
        self,
        project_id: str,
        stage: str,
        status: str,
        message: str = "",
        job_id: str = "",
        duration_ms: int = 0,
    ) -> JobEvent:
        ts = _now()
        with self._db.tx() as c:
            cur = c.execute(
                """INSERT INTO events(project_id, job_id, stage, status, message, duration_ms, ts)
                   VALUES (?,?,?,?,?,?,?)""",
                (project_id, job_id, stage, status, message, duration_ms, ts),
            )
            event_id = cur.lastrowid
        return JobEvent(
            event_id=event_id,
            project_id=project_id,
            job_id=job_id,
            stage=stage,
            status=status,
            message=message,
            duration_ms=duration_ms,
            ts=ts,
        )

    def list_events(self, project_id: str, after: int = 0, limit: int = 200) -> list[JobEvent]:
        rows = self._db.query(
            "SELECT * FROM events WHERE project_id = ? AND event_id > ? ORDER BY event_id ASC LIMIT ?",
            (project_id, after, limit),
        )
        return [_row_to_event(r) for r in rows]

    def list_job_events(self, job_id: str) -> list[JobEvent]:
        rows = self._db.query(
            "SELECT * FROM events WHERE job_id = ? ORDER BY event_id ASC", (job_id,)
        )
        return [_row_to_event(r) for r in rows]


_store: Optional[JobStore] = None
_lock = threading.Lock()


def get_job_store() -> JobStore:
    global _store
    with _lock:
        if _store is None:
            _store = JobStore()
        return _store


def reset_job_store() -> None:
    global _store
    with _lock:
        _store = None

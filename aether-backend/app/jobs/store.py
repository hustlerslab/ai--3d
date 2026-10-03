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
        created_by=(row["created_by"] if "created_by" in row.keys() else ""),
        correlation_id=(row["correlation_id"] if "correlation_id" in row.keys() else ""),
        repair_round=(row["repair_round"] if "repair_round" in row.keys() else 0),
        params=json.loads(row["params"]),
        result=json.loads(row["result"]),
        log_path=row["log_path"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _row_to_event(row) -> JobEvent:
    keys = row.keys()

    def col(name: str, default):
        return row[name] if name in keys and row[name] is not None else default

    return JobEvent(
        event_id=row["event_id"],
        project_id=row["project_id"],
        job_id=row["job_id"],
        stage=row["stage"],
        status=row["status"],
        message=row["message"],
        duration_ms=row["duration_ms"],
        ts=row["ts"],
        schema_version=col("schema_version", ""),
        event_type=col("event_type", ""),
        severity=col("severity", ""),
        confidence=col("confidence", None),
        correlation_id=col("correlation_id", ""),
        parent_event_id=col("parent_event_id", None),
        producer=col("producer", ""),
        entity_ids=json.loads(col("entity_ids", "[]") or "[]"),
        evidence_refs=json.loads(col("evidence_refs", "[]") or "[]"),
        payload=json.loads(col("payload", "{}") or "{}"),
    )


#: The envelope version stamped on every row written from now on. Rows from
#: before the envelope carry '' and are read with empty typed fields.
EVENT_SCHEMA_VERSION = "1.0"
SEVERITIES = ("info", "warning", "error", "critical")
EVIDENCE_REF_MAX = 512


class EventContractError(ValueError):
    """An emitter broke the envelope contract. Raised BEFORE any write, and
    deliberately not swallowed by `ctx.emit`: this is a bug in the caller,
    not a failure of the writer."""


def _check_evidence_refs(refs: list[str]) -> list[str]:
    """`evidence_refs` are paths. Content - a model answer, a JSON blob, a
    data URL - is refused so a row can never grow into a memory."""
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            raise EventContractError(f"evidence_refs must be non-empty path strings, got {ref!r}")
        if len(ref) > EVIDENCE_REF_MAX or any(ch in ref for ch in "\n\r\t{}<>\"") or ref.startswith("data:"):
            raise EventContractError(f"evidence_refs must be paths, never content: {ref[:60]!r}")
        out.append(ref)
    return out


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
        created_by: str = "",
        correlation_id: str = "",
        repair_round: int = 0,
    ) -> Job:
        job = Job(
            project_id=project_id,
            type=type,
            lane=lane,
            params=params or {},
            max_attempts=max_attempts,
            log_path=log_path,
            created_by=created_by,
            correlation_id=correlation_id,
            repair_round=repair_round,
            created_at=_now(),
        )
        self._db.execute(
            """INSERT INTO jobs(job_id, project_id, type, lane, status, attempt, max_attempts,
                                checkpoint, error, params, result, log_path, created_by,
                                correlation_id, repair_round, created_at, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                job.created_by,
                job.correlation_id,
                job.repair_round,
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

    def active_of_type(self, project_id: str, type: str) -> Optional[Job]:
        """The job of this type already in flight for this project, if any.

        `latest_of_type` cannot answer this: it returns the newest row whatever
        its status, so a long-finished SUCCEEDED job looks identical to a
        running one. P16 needs the distinction to stop a double-clicked
        Generate from queueing the same work twice.
        """
        row = self._db.one(
            "SELECT * FROM jobs WHERE project_id = ? AND type = ? "
            "AND status IN ('QUEUED','RUNNING','RETRYING') ORDER BY created_at ASC LIMIT 1",
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
        *,
        event_type: str = "",
        severity: str = "",
        confidence: Optional[float] = None,
        correlation_id: str = "",
        parent_event_id: Optional[int] = None,
        producer: str = "",
        entity_ids: Optional[list[str]] = None,
        evidence_refs: Optional[list[str]] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> JobEvent:
        """Append one event. The positional part is the pre-V4 call and is
        unchanged; everything after `*` is the P1-EVENT-001 envelope.

        Contract checks come first and raise `EventContractError` - a caller
        bug. Only then is the row written; a failure of the WRITE is the
        producer's problem to swallow (see `JobContext.emit`), not this one's.
        """
        if severity and severity not in SEVERITIES:
            raise EventContractError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        refs = _check_evidence_refs(list(evidence_refs or []))
        ids = [str(i) for i in (entity_ids or []) if i]
        if parent_event_id is not None and not isinstance(parent_event_id, int):
            raise EventContractError("parent_event_id must be an event_id")
        # One id per project run, on every event of it, whoever emitted it.
        # Emitters that know it pass it; the ones that predate it are filled
        # in from the project row so a run is never split in two.
        if not correlation_id and project_id:
            row = self._db.one("SELECT correlation_id FROM projects WHERE project_id = ?", (project_id,))
            correlation_id = (row["correlation_id"] if row is not None and "correlation_id" in row.keys()
                              else "") or ""
        ts = _now()
        with self._db.tx() as c:
            cur = c.execute(
                """INSERT INTO events(project_id, job_id, stage, status, message, duration_ms, ts,
                                      schema_version, event_type, severity, confidence, correlation_id,
                                      parent_event_id, producer, entity_ids, evidence_refs, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, job_id, stage, status, message, duration_ms, ts,
                 EVENT_SCHEMA_VERSION, event_type, severity, confidence, correlation_id,
                 parent_event_id, producer, json.dumps(ids), json.dumps(refs),
                 json.dumps(payload or {}, default=str)),
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
            schema_version=EVENT_SCHEMA_VERSION,
            event_type=event_type,
            severity=severity,
            confidence=confidence,
            correlation_id=correlation_id,
            parent_event_id=parent_event_id,
            producer=producer,
            entity_ids=ids,
            evidence_refs=refs,
            payload=payload or {},
        )

    def correct_event(self, parent: JobEvent, message: str, *, status: str = "corrected",
                      severity: str = "info", payload: Optional[dict[str, Any]] = None,
                      producer: str = "") -> JobEvent:
        """P1-EVENT-003: a correction is a NEW row that names the row it
        corrects. The original is never touched - the database refuses."""
        return self.add_event(
            parent.project_id, parent.stage, status, message, job_id=parent.job_id,
            event_type=(parent.event_type + ".corrected") if parent.event_type else "event.corrected",
            severity=severity, correlation_id=parent.correlation_id, parent_event_id=parent.event_id,
            producer=producer, entity_ids=list(parent.entity_ids), evidence_refs=list(parent.evidence_refs),
            payload=payload,
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

    def list_run_events(self, correlation_id: str, after: int = 0, limit: int = 1000) -> list[JobEvent]:
        """Every event of one project run, in order - the stream the
        Supervisor reads."""
        rows = self._db.query(
            "SELECT * FROM events WHERE correlation_id = ? AND event_id > ? ORDER BY event_id ASC LIMIT ?",
            (correlation_id, after, limit),
        )
        return [_row_to_event(r) for r in rows]

    def get_event(self, event_id: int) -> Optional[JobEvent]:
        row = self._db.one("SELECT * FROM events WHERE event_id = ?", (event_id,))
        return None if row is None else _row_to_event(row)

    # ── idempotent consumption (P1-EVENT-003) ────────────────────
    def consume(self, consumer: str, events: list[JobEvent], handler) -> int:
        """Run `handler(event)` once per event_id for this consumer, ever.

        The ledger row is written in the same transaction as... nothing: the
        handler's side effects are the caller's, so the row is written AFTER
        the handler returns. A handler that raises leaves no row and is
        retried on the next replay, which is the right failure mode for an
        effect that did not happen. Returns how many events were acted on.
        """
        acted = 0
        for event in events:
            seen = self._db.one(
                "SELECT 1 FROM event_consumers WHERE consumer = ? AND event_id = ?",
                (consumer, event.event_id),
            )
            if seen is not None:
                continue
            handler(event)
            self._db.execute(
                "INSERT OR IGNORE INTO event_consumers(consumer, event_id, consumed_at) VALUES (?,?,?)",
                (consumer, event.event_id, _now()),
            )
            acted += 1
        return acted


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

"""Two-lane in-process job runner with retry and restart recovery."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.config import get_settings
from ..core.logging import bind
from ..projects.schema import ProjectStage
from ..projects.store import ProjectStore, get_project_store
from .context import JobContext
from .registry import get_spec
from .schema import Job, JobLane, JobStatus
from .store import JobStore, get_job_store

log = logging.getLogger("aether.jobs")

# Providers that run on this machine's GPU rather than over the network. Jobs
# that call one are serialised against Blender — see JobRunner._lane_for.
_LOCAL_PROVIDERS = {"ollama"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: P1-EVENT-002: every job transition, typed. `_execute` is the single choke
#: point all 13 job types pass through, so this table instruments all of them.
#: Severity is set HERE, by the emitter that knows what the transition means.
_TRANSITIONS: dict[str, tuple[str, str]] = {
    "queued":    ("job.queued",    "info"),
    "started":   ("job.started",   "info"),
    "succeeded": ("job.succeeded", "info"),
    "retrying":  ("job.retrying",  "warning"),
    "failed":    ("job.failed",    "error"),
    "resumed":   ("job.resumed",   "warning"),
}


class JobRunner:
    def __init__(
        self,
        job_store: Optional[JobStore] = None,
        project_store: Optional[ProjectStore] = None,
        ai_workers: Optional[int] = None,
        render_workers: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        settings = get_settings()
        self.jobs = job_store or get_job_store()
        self.projects = project_store or get_project_store()
        self.retry_delay = settings.jobs_retry_delay_seconds if retry_delay is None else retry_delay
        self._pools = {
            JobLane.ai: ThreadPoolExecutor(
                max_workers=ai_workers or settings.jobs_ai_workers, thread_name_prefix="aether-ai"
            ),
            JobLane.render: ThreadPoolExecutor(
                max_workers=render_workers or settings.jobs_render_workers,
                thread_name_prefix="aether-render",
            ),
        }
        self._inflight = 0
        self._cv = threading.Condition()
        self._timers: set[threading.Timer] = set()
        self._stopping = threading.Event()
        self._started = False

    # ── events ───────────────────────────────────────────────────
    def _publish(self, job: Job, transition: str, message: str = "", *, duration_ms: int = 0,
                 payload: Optional[dict[str, Any]] = None) -> None:
        """One typed event per job transition, from the one place every
        transition passes through. A failure to write it is logged and
        swallowed: the event is the record of the work, and losing the record
        must never lose - or fail - the work."""
        event_type, severity = _TRANSITIONS[transition]
        try:
            self.jobs.add_event(
                job.project_id, job.type, transition, message, job_id=job.job_id, duration_ms=duration_ms,
                event_type=event_type, severity=severity, correlation_id=job.correlation_id,
                producer="jobs.runner", payload={"attempt": job.attempt, "max_attempts": job.max_attempts,
                                                  **(payload or {})},
            )
        except Exception as exc:                          # noqa: BLE001 - never fail the job
            log.warning("event.dropped", extra={"transition": transition, "type": job.type,
                                                "reason": f"{type(exc).__name__}: {exc}"})

    # ── lifecycle ────────────────────────────────────────────────
    def start(self) -> int:
        """Resume every job that was in flight when the process last stopped."""
        self._started = True
        resumed = 0
        for job in self.jobs.unfinished():
            if job.status == JobStatus.RUNNING:
                self._publish(
                    job, "resumed",
                    f"process restarted during attempt {job.attempt}; resuming from checkpoint "
                    f"'{job.checkpoint or 'none'}'", payload={"checkpoint": job.checkpoint},
                )
                self.jobs.update(job.job_id, status=JobStatus.RETRYING)
            self._submit(job.job_id, job.lane)
            resumed += 1
        if resumed:
            log.info("Job runner resumed %d job(s)", resumed)
        return resumed

    def shutdown(self, wait: bool = False) -> None:
        self._stopping.set()
        for t in list(self._timers):
            t.cancel()
        for pool in self._pools.values():
            pool.shutdown(wait=wait, cancel_futures=True)

    # ── submission ───────────────────────────────────────────────
    def enqueue(self, project_id: str, type: str, params: Optional[dict[str, Any]] = None,
                created_by: str = "") -> Job:
        spec = get_spec(type)
        project = self.projects.get(project_id)  # raises ProjectNotFound

        # Who asked. Taken from the request context rather than from `params`,
        # which POST /projects/{id}/jobs lets the caller write wholesale. An
        # explicit argument still wins, for callers outside a request.
        if not created_by:
            from ..auth.authz import current_actor

            created_by = current_actor.get("")

        # P16 idempotency. A double-clicked "Generate 3D space" used to queue the
        # work twice: the render lane has one worker so those merely serialised,
        # but the `ai` lane has two, and two concurrent `scene_plan` jobs for one
        # project write the same planning files. Hand back the job already in
        # flight instead - the client polls a job id, so it cannot tell the
        # difference and ends up watching the run that is actually happening.
        #
        # Deliberately per (project, type) and in-flight ONLY: a finished job
        # never blocks a re-run, so `force` and genuine retries are unaffected.
        active = self.jobs.active_of_type(project_id, type)
        if active is not None:
            log.info("job.enqueue.deduped project=%s type=%s existing=%s status=%s",
                     project_id, type, active.job_id, active.status)
            return active

        job = self.jobs.create(
            project_id=project_id,
            type=type,
            lane=self._lane_for(spec),
            params=params,
            max_attempts=spec.max_attempts,
            created_by=created_by,
            # Copied, not looked up later: the runner binds log context before
            # it touches the project store, because a lookup that itself fails
            # is exactly when the ids matter.
            correlation_id=getattr(project, "correlation_id", "") or "",
        )
        self._publish(job, "queued", payload={"lane": str(job.lane.value), "created_by": created_by})
        self._submit(job.job_id, job.lane)
        return job

    # -- P1-REPAIR-001: the outer loop's bound lives HERE ---------------------
    def repair_rounds_used(self, project_id: str) -> int:
        """Automatic repair rounds since the project's last ordinary job. A
        user action (any job with repair_round 0) starts a fresh budget; no
        amount of automatic activity can."""
        from ..db import get_db

        db = get_db()
        last_user = db.scalar(
            "SELECT MAX(rowid) FROM jobs WHERE project_id = ? AND COALESCE(repair_round, 0) = 0",
            (project_id,)) or 0
        used = db.scalar(
            "SELECT MAX(repair_round) FROM jobs WHERE project_id = ? AND repair_round > 0 AND rowid > ?",
            (project_id, last_user))
        return int(used or 0)

    def request_repair(self, project_id: str, type: str, params: Optional[dict[str, Any]] = None,
                       *, requested_by: str = "orchestrator") -> Optional[Job]:
        """Dispatch an automatic repair job, or refuse. The RUNNER numbers the
        round - whatever the caller put in `params` is discarded - and refuses
        once `repair_max_rounds` is reached, however often it is asked. A
        refusal is recorded; the caller must escalate."""
        cap = get_settings().repair_max_rounds
        spec = get_spec(type)
        project = self.projects.get(project_id)
        clean = {k: v for k, v in (params or {}).items() if k not in ("repair_round", "max_rounds")}
        next_round = self.repair_rounds_used(project_id) + 1
        if next_round > cap:
            try:
                self.jobs.add_event(project_id, type, "refused",
                                    f"automatic repair refused: {cap} of {cap} round(s) already used",
                                    event_type="repair.limit_reached", severity="warning", producer="jobs.runner",
                                    correlation_id=getattr(project, "correlation_id", "") or "",
                                    payload={"requested_by": requested_by, "cap": cap, "job_type": type})
            except Exception:                              # noqa: BLE001
                log.warning("repair.limit_reached event not recorded")
            return None
        job = self.jobs.create(
            project_id=project_id, type=type, lane=self._lane_for(spec), params=clean,
            max_attempts=spec.max_attempts, created_by=requested_by,
            correlation_id=getattr(project, "correlation_id", "") or "", repair_round=next_round)
        self._publish(job, "queued", f"repair round {next_round} of {cap}",
                      payload={"lane": str(job.lane.value), "created_by": requested_by,
                               "repair_round": next_round, "max_rounds": cap})
        self.projects.set_stage(project_id, ProjectStage.REPAIRING)
        self._submit(job.job_id, job.lane)
        return job

    def _lane_for(self, spec) -> JobLane:
        """Which pool a job belongs in.

        Normally the lane the handler registered. The exception is a LOCAL
        intelligence provider: it runs on the same GPU as Blender, and the ai
        lane has two threads while the render lane has one. Leaving an Ollama
        analysis on the ai lane would let two inferences and a render fight
        over the same 6 GB. Routing them to the render lane makes the existing
        single-thread pool the GPU mutex — no new locking, and the choice is
        recorded on the job row so a resume after restart lands correctly.
        """
        if spec.lane is JobLane.render:
            return spec.lane
        # A handler that drives the GPU itself belongs behind the same mutex,
        # whoever the intelligence provider is. The moodboard's Stable
        # Diffusion pass is local even when the reading is Gemini.
        if getattr(spec, "uses_local_gpu", False) and get_settings().scene_image_enabled:
            return JobLane.render
        if not spec.uses_intelligence:
            return spec.lane
        if get_settings().intelligence_provider.lower().strip() in _LOCAL_PROVIDERS:
            log.info(
                "routing %s to the render lane: %s runs on the GPU Blender uses",
                spec.type,
                get_settings().intelligence_provider,
            )
            return JobLane.render
        return spec.lane

    def _submit(self, job_id: str, lane: JobLane) -> None:
        with self._cv:
            self._inflight += 1
        try:
            self._pools[lane].submit(self._run, job_id)
        except RuntimeError:
            # pool already shut down
            with self._cv:
                self._inflight -= 1
                self._cv.notify_all()

    def _schedule_retry(self, job_id: str, lane: JobLane, delay: float) -> None:
        def fire() -> None:
            self._timers.discard(timer)
            with self._cv:
                self._inflight -= 1
                self._cv.notify_all()
            if not self._stopping.is_set():
                self._submit(job_id, lane)

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        self._timers.add(timer)
        with self._cv:
            self._inflight += 1
        timer.start()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until no job is running or waiting to retry (tests)."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._inflight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
        return True

    # ── execution ────────────────────────────────────────────────
    def _run(self, job_id: str) -> None:
        # P0-OBSERVABILITY-001. Bound HERE, around the whole execution, rather
        # than inside _execute: a crash before the ids are set would produce
        # exactly the uncorrelated line somebody needs most. The `bind` context
        # manager restores the previous values on exit, so a failed job cannot
        # leave its ids attached to whatever this worker thread picks up next -
        # a log naming the wrong customer is worse than one naming none.
        try:
            job = self.jobs.get(job_id)
            project_id, correlation = job.project_id, job.correlation_id
        except Exception:                      # noqa: BLE001 - id lookup only
            project_id, correlation = "", ""
        with bind(project_id=project_id, job_id=job_id, correlation_id=correlation or None):
            self._run_bound(job_id)

    def _run_bound(self, job_id: str) -> None:
        try:
            self._execute(job_id)
        except Exception:  # pragma: no cover - last line of defence
            log.exception("job crashed outside the handler")
        finally:
            with self._cv:
                self._inflight -= 1
                self._cv.notify_all()

    def _execute(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job.is_terminal or self._stopping.is_set():
            return
        spec = get_spec(job.type)
        project = self.projects.get(job.project_id)
        attempt = job.attempt + 1
        job = self.jobs.update(
            job_id, status=JobStatus.RUNNING, attempt=attempt, started_at=_now(), error=""
        )
        ctx = JobContext(job, project, self.jobs, self.projects)
        self.jobs.update(job_id, log_path=str(ctx.log_path))
        self._publish(job, "started", f"attempt {attempt}/{job.max_attempts}",
                      payload={"checkpoint": job.checkpoint})
        if spec.stage_running is not None:
            self.projects.set_stage(job.project_id, spec.stage_running)

        # P16 observability: one line per job transition, carrying the two ids
        # needed to follow a single generation across the whole pipeline. The
        # per-project `events` table already records stage and status; this is
        # the server-side half, so a log file alone is enough to trace a run.
        # Ids only - never a brief, an image, a prompt or a key.
        # The ids are already on every line (see _run); this carries the rest.
        log.info("job.start", extra={
            "type": job.type, "lane": str(job.lane),
            "attempt": attempt, "max_attempts": job.max_attempts,
        })

        t0 = time.monotonic()
        try:
            result = spec.handler(ctx) or {}
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.info("job.succeeded", extra={
                "type": job.type,
                "duration_ms": duration_ms,
                # Ids only. `result` can contain anything a handler returns, so
                # named keys are copied out rather than the dict logged.
                **{k: result[k] for k in ("scene_id", "scene_version")
                   if isinstance(result, dict) and k in result},
            })
            self.jobs.update(job_id, status=JobStatus.SUCCEEDED, result=result, finished_at=_now())
            self._publish(job, "succeeded", duration_ms=duration_ms, payload={
                k: result[k] for k in ("scene_id", "scene_version")
                if isinstance(result, dict) and k in result})
            if spec.stage_done is not None:
                self.projects.set_stage(job.project_id, spec.stage_done)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            error = f"{type(exc).__name__}: {exc}"
            # P1-VALIDATOR-003: every job failure names its category.
            try:
                from ..supervisor.classify import from_exception

                failure = from_exception(exc, job_type=job.type).as_payload()
            except Exception:                              # noqa: BLE001
                failure = {}
            ctx.log.error("attempt %d failed: %s\n%s", attempt, error, traceback.format_exc())
            log.error("job.failed project=%s job=%s type=%s attempt=%d/%d ms=%d reason=%s",
                      job.project_id, job_id, job.type, attempt, job.max_attempts,
                      duration_ms, error)
            if attempt < job.max_attempts and not self._stopping.is_set():
                self.jobs.update(job_id, status=JobStatus.RETRYING, error=error)
                self._publish(
                    job, "retrying",
                    f"{error} — retry {attempt + 1}/{job.max_attempts} from checkpoint "
                    f"'{ctx.job.checkpoint or 'none'}'",
                    duration_ms=duration_ms,
                    payload={"error": error, "checkpoint": ctx.job.checkpoint, "next_attempt": attempt + 1, **failure},
                )
                self._schedule_retry(job_id, job.lane, self.retry_delay * attempt)
            else:
                self.jobs.update(job_id, status=JobStatus.FAILED, error=error, finished_at=_now())
                self._publish(job, "failed", error, duration_ms=duration_ms,
                              payload={"error": error, "project_stage": ProjectStage.FAILED.value, **failure})
                self.projects.set_stage(job.project_id, ProjectStage.FAILED)
        finally:
            ctx.close()
            job_now = self.jobs.get(job_id)
            if job_now.is_terminal:
                self._supervise(job_now.project_id, job_now.type, job_now.status, job_now)

    def _supervise(self, project_id: str, job_type: str = "", status: Any = None, job: Optional[Job] = None) -> None:
        """P1-WATCHER-001: the Watcher looks at the stream after a job ends.
        Advisory (design.md §21.6): it cannot fail, delay-fail or alter the job
        it follows, and SUPERVISOR_ENABLED=false removes it entirely."""
        if not get_settings().supervisor_enabled:
            return
        try:
            from ..supervisor.watcher import watch_project

            found = watch_project(project_id, new_only=True)
            # P1-VALIDATOR-002: after a plan or a build has produced something
            # to verify. Independent of the Watcher: it reads artifacts, not events.
            if job_type in ("scene_plan", "build", "repair_scene", "check_scene", "verify") and status == JobStatus.SUCCEEDED:
                from ..supervisor.validator import validate_project

                verdicts = validate_project(project_id)
                if verdicts:
                    log.info("supervisor.validator", extra={"verdicts": sorted({v.status for v in verdicts})})
                # P1-ORCHESTRATOR-001: decide on the verdicts; the runner's own
                # `request_repair` holds the bound on what it may dispatch.
                if job is not None:
                    from ..supervisor.orchestrator import orchestrate_project

                    decided = orchestrate_project(project_id, job, verdicts, found)
                    if decided and decided.get("decision") != "CONTINUE":
                        log.info("supervisor.orchestrator", extra={"decision": decided.get("decision")})
            if found:
                log.info("supervisor.watcher", extra={"observations": len(found),
                                                      "anomalies": sorted({o.anomaly_type for o in found})})
        except Exception:                                  # noqa: BLE001
            log.exception("supervisor failed; the job it followed is unaffected")


_runner: Optional[JobRunner] = None
_lock = threading.Lock()


def get_runner() -> JobRunner:
    global _runner
    with _lock:
        if _runner is None:
            _runner = JobRunner()
        return _runner


def reset_runner() -> None:
    global _runner
    with _lock:
        if _runner is not None:
            _runner.shutdown(wait=False)
        _runner = None

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

    # ── lifecycle ────────────────────────────────────────────────
    def start(self) -> int:
        """Resume every job that was in flight when the process last stopped."""
        self._started = True
        resumed = 0
        for job in self.jobs.unfinished():
            if job.status == JobStatus.RUNNING:
                self.jobs.add_event(
                    job.project_id, job.type, "resumed",
                    f"process restarted during attempt {job.attempt}; resuming from checkpoint "
                    f"'{job.checkpoint or 'none'}'", job_id=job.job_id,
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
    def enqueue(self, project_id: str, type: str, params: Optional[dict[str, Any]] = None) -> Job:
        spec = get_spec(type)
        self.projects.get(project_id)  # raises ProjectNotFound
        job = self.jobs.create(
            project_id=project_id,
            type=type,
            lane=self._lane_for(spec),
            params=params,
            max_attempts=spec.max_attempts,
        )
        self.jobs.add_event(project_id, type, "queued", job_id=job.job_id)
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
        try:
            self._execute(job_id)
        except Exception:  # pragma: no cover - last line of defence
            log.exception("job %s crashed outside the handler", job_id)
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
        ctx.emit(job.type, f"attempt {attempt}/{job.max_attempts}", status="started")
        if spec.stage_running is not None:
            self.projects.set_stage(job.project_id, spec.stage_running)

        t0 = time.monotonic()
        try:
            result = spec.handler(ctx) or {}
            duration_ms = int((time.monotonic() - t0) * 1000)
            self.jobs.update(job_id, status=JobStatus.SUCCEEDED, result=result, finished_at=_now())
            self.jobs.add_event(
                job.project_id, job.type, "succeeded", job_id=job_id, duration_ms=duration_ms
            )
            if spec.stage_done is not None:
                self.projects.set_stage(job.project_id, spec.stage_done)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            error = f"{type(exc).__name__}: {exc}"
            ctx.log.error("attempt %d failed: %s\n%s", attempt, error, traceback.format_exc())
            if attempt < job.max_attempts and not self._stopping.is_set():
                self.jobs.update(job_id, status=JobStatus.RETRYING, error=error)
                self.jobs.add_event(
                    job.project_id, job.type, "retrying",
                    f"{error} — retry {attempt + 1}/{job.max_attempts} from checkpoint "
                    f"'{ctx.job.checkpoint or 'none'}'",
                    job_id=job_id, duration_ms=duration_ms,
                )
                self._schedule_retry(job_id, job.lane, self.retry_delay * attempt)
            else:
                self.jobs.update(job_id, status=JobStatus.FAILED, error=error, finished_at=_now())
                self.jobs.add_event(
                    job.project_id, job.type, "failed", error, job_id=job_id, duration_ms=duration_ms
                )
                self.projects.set_stage(job.project_id, ProjectStage.FAILED)
        finally:
            ctx.close()


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

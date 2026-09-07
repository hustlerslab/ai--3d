"""Job orchestration (DPR §18, plan §5).

API request → Job(QUEUED) → a lane worker claims it → handler runs with a
JobContext → checkpoint files + events → status update → UI polls.

Two lanes: "ai" (network-bound agents, 2 threads) and "render" (one thread,
owns the GPU and runs Blender as a subprocess). Failures retry from the
last checkpoint; a restart resumes every job that was still in flight.
"""
from .context import JobContext
from .registry import JobSpec, UnknownJobType, get_spec, known_types, register
from .runner import JobRunner, get_runner, reset_runner
from .schema import Job, JobEvent, JobLane, JobStatus
from .store import JobNotFound, JobStore, get_job_store, reset_job_store

# Register built-in handlers.
from . import handlers as _handlers  # noqa: E402,F401

__all__ = [
    "Job",
    "JobContext",
    "JobEvent",
    "JobLane",
    "JobNotFound",
    "JobRunner",
    "JobSpec",
    "JobStatus",
    "JobStore",
    "UnknownJobType",
    "get_job_store",
    "get_runner",
    "get_spec",
    "known_types",
    "register",
    "reset_job_store",
    "reset_runner",
]

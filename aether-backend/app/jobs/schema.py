from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..scene.schema import new_id


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobLane(str, Enum):
    ai = "ai"
    render = "render"


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: new_id("job"))
    project_id: str
    type: str
    lane: JobLane
    status: JobStatus = JobStatus.QUEUED
    attempt: int = 0
    max_attempts: int = 3
    checkpoint: str = ""
    error: str = ""
    params: dict[str, Any] = {}
    result: dict[str, Any] = {}
    log_path: str = ""
    #: Which user asked for this job. A COLUMN, not a key in `params`,
    #: because POST /projects/{id}/jobs lets the caller supply params
    #: wholesale - a user id in there would be forgeable, which is the
    #: opposite of an audit trail. Empty means the job predates this field,
    #: or the runner raised it itself while resuming after a restart.
    created_by: str = ""
    #: The project's correlation id, copied at enqueue. Denormalised so the
    #: runner can bind log context without a project lookup - a lookup that
    #: itself fails is exactly when the ids matter.
    correlation_id: str = ""
    created_at: str
    started_at: str = ""
    finished_at: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL


class JobEvent(BaseModel):
    event_id: int
    project_id: str
    job_id: str = ""
    stage: str
    status: str
    message: str = ""
    duration_ms: int = 0
    ts: str

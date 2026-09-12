"""Job type registry: maps a job type to its handler, lane and stage effects.

    @register("analyze", lane=JobLane.ai,
              stage_running=ProjectStage.ANALYZING,
              stage_done=ProjectStage.DESIGN_SPEC_READY)
    def analyze(ctx: JobContext) -> dict: ...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..projects.schema import ProjectStage
from .schema import JobLane

Handler = Callable[["JobContext"], Optional[dict[str, Any]]]  # noqa: F821


class UnknownJobType(Exception):
    pass


@dataclass(frozen=True)
class JobSpec:
    type: str
    lane: JobLane
    handler: Handler
    max_attempts: int = 3
    stage_running: Optional[ProjectStage] = None
    stage_done: Optional[ProjectStage] = None
    description: str = ""
    # True when this handler calls the intelligence provider. Harmless for a
    # cloud provider, but a local one runs on the same GPU as Blender, so the
    # runner moves these jobs to the render lane to serialise them against it.
    uses_intelligence: bool = False


_REGISTRY: dict[str, JobSpec] = {}


def register(
    type: str,
    lane: JobLane,
    *,
    max_attempts: int = 3,
    stage_running: Optional[ProjectStage] = None,
    stage_done: Optional[ProjectStage] = None,
    description: str = "",
    uses_intelligence: bool = False,
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _REGISTRY[type] = JobSpec(
            type=type,
            lane=lane,
            handler=fn,
            max_attempts=max_attempts,
            stage_running=stage_running,
            stage_done=stage_done,
            uses_intelligence=uses_intelligence,
            description=description or (fn.__doc__ or "").strip().splitlines()[0] if (description or fn.__doc__) else "",
        )
        return fn

    return deco


def get_spec(type: str) -> JobSpec:
    try:
        return _REGISTRY[type]
    except KeyError:
        raise UnknownJobType(type) from None


def known_types() -> list[dict[str, Any]]:
    return [
        {
            "type": s.type,
            "lane": s.lane.value,
            "max_attempts": s.max_attempts,
            "stage_running": s.stage_running.value if s.stage_running else None,
            "stage_done": s.stage_done.value if s.stage_done else None,
            "description": s.description,
        }
        for s in _REGISTRY.values()
    ]


def unregister(type: str) -> None:
    _REGISTRY.pop(type, None)

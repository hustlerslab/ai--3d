"""Project records and the pipeline state machine (DPR §16)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..scene.schema import new_id


class ProjectStage(str, Enum):
    CREATED = "CREATED"
    INPUT_RECEIVED = "INPUT_RECEIVED"
    ANALYZING = "ANALYZING"
    DESIGN_SPEC_READY = "DESIGN_SPEC_READY"
    ASSET_PLANNING = "ASSET_PLANNING"
    ASSETS_READY = "ASSETS_READY"
    SCENE_BUILDING = "SCENE_BUILDING"
    SCENE_VALIDATING = "SCENE_VALIDATING"
    CAMERA_PLANNING = "CAMERA_PLANNING"
    PREVIEW_RENDERING = "PREVIEW_RENDERING"
    FINAL_RENDERING = "FINAL_RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Linear order used to decide whether a transition moves the project forward.
STAGE_ORDER: list[ProjectStage] = [
    ProjectStage.CREATED,
    ProjectStage.INPUT_RECEIVED,
    ProjectStage.ANALYZING,
    ProjectStage.DESIGN_SPEC_READY,
    ProjectStage.ASSET_PLANNING,
    ProjectStage.ASSETS_READY,
    ProjectStage.SCENE_BUILDING,
    ProjectStage.SCENE_VALIDATING,
    ProjectStage.CAMERA_PLANNING,
    ProjectStage.PREVIEW_RENDERING,
    ProjectStage.FINAL_RENDERING,
    ProjectStage.COMPLETED,
]


class Vertical(str, Enum):
    """The market a project is designed for. Deliberately three members:
    this product designs interiors, so there is no factory/manufacturing
    vertical — see the scope guard in app/api/projects_routes.py."""

    RESIDENTIAL = "residential"
    HOSPITALITY = "hospitality"
    INDUSTRIAL = "industrial"


class InputKind(str, Enum):
    description = "description"
    reference = "reference"
    dimensions = "dimensions"
    floor_plan = "floor_plan"


class RoomHint(BaseModel):
    """User-supplied room dimensions. Missing numbers are estimated later
    and flagged as such (DPR §23: every room has dimensions or is marked
    estimated)."""

    name: str
    type: str = "living_room"
    width_m: Optional[float] = None
    length_m: Optional[float] = None
    height_m: Optional[float] = None
    estimated: bool = True


class ProjectRecord(BaseModel):
    project_id: str = Field(default_factory=lambda: new_id("proj"))
    name: str
    description: str = ""
    stage: ProjectStage = ProjectStage.CREATED
    scene_ids: list[str] = []
    room_hints: list[RoomHint] = []
    vertical: Vertical = Vertical.RESIDENTIAL
    created_at: str
    updated_at: str


class InputRecord(BaseModel):
    input_id: str = Field(default_factory=lambda: new_id("in"))
    project_id: str
    kind: InputKind
    filename: str
    path: str  # relative to the project directory
    content_type: str = ""
    size_bytes: int = 0
    meta: dict[str, Any] = {}
    created_at: str

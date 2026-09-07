"""Canonical scene schema — the single source of truth for every scene.

Conventions (AETHER_SYSTEM_DESIGN_V2 §12.1 / §16):
  unit    = meter
  up      = +Y
  right   = +X
  forward = -Z
Plan-view geometry (walls, room boundaries, object footprints) lives in the
XZ plane; Y is height. Rotation on objects is yaw around +Y, radians.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


Vec2 = tuple[float, float]          # (x, z)
Vec3 = tuple[float, float, float]   # (x, y, z)


class OpeningType(str, Enum):
    DOOR = "door"
    WINDOW = "window"


class ObjectSource(str, Enum):
    CATALOG = "catalog"
    GENERATED = "generated"
    USER = "user"
    SEED = "seed"


class Confidence(BaseModel):
    value: float = 1.0
    source: str = "seed"


class Material(BaseModel):
    material_id: str = Field(default_factory=lambda: new_id("mat"))
    name: str
    base_color: str = "#cccccc"
    roughness: float = 0.8
    metalness: float = 0.0
    style_tags: list[str] = []


class Opening(BaseModel):
    opening_id: str = Field(default_factory=lambda: new_id("open"))
    type: OpeningType
    wall_id: str
    # Distance in meters from the wall's start point to the opening's center.
    position: float
    width: float
    height: float
    sill_height: float = 0.0  # 0 for doors; > 0 for windows


class Wall(BaseModel):
    wall_id: str = Field(default_factory=lambda: new_id("wall"))
    start: Vec2
    end: Vec2
    thickness: float = 0.15
    height: float = 2.8
    material: str = "paint_white"


class Room(BaseModel):
    room_id: str = Field(default_factory=lambda: new_id("room"))
    name: str
    type: str = "living_room"
    # Closed polygon in the XZ plane, counter-clockwise, no repeated last point.
    boundary: list[Vec2]
    floor_height: float = 0.0
    ceiling_height: float = 2.8
    floor_material: str = "wood_oak"
    confidence: Confidence = Confidence()
    # architecture read from the photos: cornice, wainscot, panelled_doors, ...
    features: list[str] = []


SourceStrategy = Literal["local_asset", "local_modified", "procedural", "generated"]


class SceneObject(BaseModel):
    object_id: str = Field(default_factory=lambda: new_id("obj"))
    semantic_type: str
    asset_id: Optional[str] = None
    room_id: str
    # Position of the object's bottom-center pivot.
    position: Vec3
    # Yaw around +Y in radians.
    rotation_y: float = 0.0
    scale: Vec3 = (1.0, 1.0, 1.0)
    # width (x), height (y), depth (z) in meters at scale 1.
    dimensions: Vec3
    color: str = "#8a7862"
    source: ObjectSource = ObjectSource.CATALOG
    locked: bool = False
    # floor | ceiling | wall | surface — only floor items are floor obstacles.
    mount: str = "floor"
    confidence: Confidence = Confidence()
    # Hybrid asset pipeline (plan §4.1 / DPR §9): how this object's model is sourced.
    source_strategy: SourceStrategy = "procedural"
    # slot -> material_id from app/materials (e.g. {"primary": "fabric_linen"})
    material_overrides: dict[str, str] = {}
    # planner bookkeeping: object_plan key this object was created from
    plan_key: Optional[str] = None
    # surfaces (spec 1.1): the object this one rests on (mount "surface")
    parent_id: Optional[str] = None
    # project-relative image that textures the object's face (art, rugs)
    texture_ref: Optional[str] = None
    # procedural shape hint for renderers (photo, lamp, fireplace, ...)
    shape: Optional[str] = None
    # open name from the reading, for the inspector
    name: str = ""


# ── SceneSpec extensions (plan §4.1) ────────────────────────────────────


class SceneStyle(BaseModel):
    name: str = "modern_warm_minimal"
    tags: list[str] = []
    palette: list[str] = []
    materials: list[str] = []
    lighting_mood: Literal["warm_daylight", "cool_daylight", "evening", "studio"] = "warm_daylight"


class InteriorLight(BaseModel):
    light_id: str = Field(default_factory=lambda: new_id("light"))
    room_id: str
    type: Literal["area", "point", "spot"] = "area"
    position: Vec3
    power_w: float = 60.0
    color_temp_k: int = 3200
    size_m: float = 0.6


class LightingSpec(BaseModel):
    mood: Literal["warm_daylight", "cool_daylight", "evening", "studio"] = "warm_daylight"
    sun_azimuth_deg: float = 135.0
    sun_elevation_deg: float = 40.0
    sun_strength: float = 3.0
    sky_turbidity: float = 2.5
    exposure_ev: float = 0.0
    interior_lights: list[InteriorLight] = []


class CameraKeyframe(BaseModel):
    position: Vec3
    look_at: Vec3
    duration: float = 2.0
    room_id: Optional[str] = None
    label: str = ""


class CameraPlan(BaseModel):
    type: Literal["walkthrough", "orbit", "stills"] = "walkthrough"
    duration_seconds: int = 45
    seconds_per_room: float = 8.0
    keyframes: list[CameraKeyframe] = []
    hero_shots: list[SavedView] = []


class Calibration(BaseModel):
    meters_per_unit: float = 1.0
    source: str = "seed"
    confidence: float = 1.0


class SavedView(BaseModel):
    view_id: str = Field(default_factory=lambda: new_id("view"))
    name: str
    position: Vec3
    target: Vec3
    mode: Literal["orbit", "first_person"] = "orbit"


class Scene(BaseModel):
    scene_id: str = Field(default_factory=lambda: new_id("scene"))
    project_id: str
    version: int = 0
    units: Literal["meter"] = "meter"
    coordinate_system: dict[str, str] = {"up": "Y", "right": "X", "forward": "-Z"}
    name: str = "Untitled scene"
    rooms: list[Room] = []
    walls: list[Wall] = []
    openings: list[Opening] = []
    objects: list[SceneObject] = []
    materials: list[Material] = []
    saved_views: list[SavedView] = []
    calibration: Calibration = Calibration()
    metadata: dict[str, Any] = {}
    # SceneSpec extensions (plan §4.1). Optional so older scene files still load.
    spec_version: str = "1.0"
    style: Optional[SceneStyle] = None
    lighting: Optional[LightingSpec] = None
    camera_plan: Optional[CameraPlan] = None

    # ── Lookups ────────────────────────────────────────────────
    def room(self, room_id: str) -> Optional[Room]:
        return next((r for r in self.rooms if r.room_id == room_id), None)

    def wall(self, wall_id: str) -> Optional[Wall]:
        return next((w for w in self.walls if w.wall_id == wall_id), None)

    def object(self, object_id: str) -> Optional[SceneObject]:
        return next((o for o in self.objects if o.object_id == object_id), None)

    def openings_for_wall(self, wall_id: str) -> list[Opening]:
        return [o for o in self.openings if o.wall_id == wall_id]


class Project(BaseModel):
    project_id: str = Field(default_factory=lambda: new_id("proj"))
    name: str
    created_at: str
    scene_ids: list[str] = []

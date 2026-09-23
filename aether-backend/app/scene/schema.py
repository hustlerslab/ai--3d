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


class WallFinishZone(BaseModel):
    """One finish region on one wall face (P22), read from the approved
    render. `extent` is metres along that room's edge from its left end seen
    from inside the room, then metres up from the floor; the wall segment it
    hangs on is the third coordinate. Data for the executor: Blender paints
    the whole wall in `Wall.material` until it consumes zones."""
    room_id: str
    wall_name: str                 # back | left | right | front, in that room's render frame
    material: str                  # registry material id
    material_text: str = ""        # what the reader actually said ("zellige tiles")
    color: str = ""
    pattern: str = ""
    extent: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # from_x, to_x, from_y, to_y


class Wall(BaseModel):
    wall_id: str = Field(default_factory=lambda: new_id("wall"))
    start: Vec2
    end: Vec2
    thickness: float = 0.15
    height: float = 2.8
    material: str = "paint_white"
    # P5 wall representation: generalized extrusion direction. (0,1,0) is a
    # vertical wall and reproduces every pre-P5 result exactly; a leaning wall
    # (measured ~11 deg on a photo-reconstructed room) stores its true up-vector
    # so height-aware collision checks use the right cross-section.
    extrusion_direction: Vec3 = (0.0, 1.0, 0.0)
    # P22: finish zones from the reading. Empty on every scene stored before.
    finishes: list[WallFinishZone] = []


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


class ObjectVisual(BaseModel):
    """What the client's own reference said this piece looks like.

    DESCRIPTIVE EVIDENCE, NEVER GEOMETRY. Nothing here is a position, rotation,
    scale or dimension, and nothing here is a construction or procurement
    specification - the solver keeps every geometric decision and the designer
    keeps every execution figure.

    WHY IT IS A SEPARATE BLOCK. `SceneObject.color` and `material_overrides`
    already carry the two attributes the executor can actually paint: a hex and
    one registry material id. They are RESOLVED values. This block keeps what
    the client actually said - "sage green", "quilted", "dark walnut frame" -
    which the resolved pair cannot express, and which stopped at the plan
    before P13. Kept deliberately parallel to
    `app.intelligence.design_intent.VisualAttributes` rather than importing it:
    `Scene` is the executor-facing contract and imports nothing from the
    intelligence package, so a provider change can never alter the scene type.

    `style_descriptors` and `visual_descriptors` arrive merged here as
    `descriptors` - the distinction matters when classifying a reference and
    not when describing the object it produced.
    """

    color_words: list[str] = []
    #: The material WORD the reference used ("linen"), as distinct from the
    #: registry id in `material_overrides` ("fabric_linen").
    material: str = ""
    upholstery: str = ""
    pattern: str = ""
    frame_finish: str = ""
    descriptors: list[str] = []
    #: Which design intents produced or shaped this object, so
    #: object_id -> intent_id -> reference is answerable from the scene alone.
    source_intent_ids: list[str] = []

    def is_empty(self) -> bool:
        return not any((self.color_words, self.material, self.upholstery, self.pattern,
                        self.frame_finish, self.descriptors, self.source_intent_ids))


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
    # planner bookkeeping: object_plan key this object was created from.
    # KEPT. It is the join every pre-V4 scene relies on, and the two identity
    # fields below do not replace it - they remove the need to perform it.
    plan_key: Optional[str] = None
    # P1-IDENTITY-001. Which ELEMENT this object is an occurrence of, and which
    # occurrence it is. Identity used to survive only as a join:
    # plan_key -> ObjectPlanItem.object_key -> .element_id, which nobody
    # performed, so three bar stools looked like three unrelated purchases
    # rather than one element placed three times.
    #
    # Both Optional with a None default, so a scene_spec.json written before V4
    # loads unchanged. That is the whole reason they are optional: making them
    # required would strand every scene already on disk.
    element_id: Optional[str] = None
    instance_id: Optional[str] = None
    # surfaces (spec 1.1): the object this one rests on (mount "surface")
    parent_id: Optional[str] = None
    # project-relative image that textures the object's face (art, rugs)
    texture_ref: Optional[str] = None
    # procedural shape hint for renderers (photo, lamp, fireplace, ...)
    shape: Optional[str] = None
    # open name from the reading, for the inspector
    name: str = ""
    # P13: what the client's reference said this looks like. Defaults to an
    # empty block, so every scene stored before P13 loads unchanged.
    visual: ObjectVisual = Field(default_factory=ObjectVisual)

    @property
    def source_intent_ids(self) -> list[str]:
        """Which design intents produced or shaped this object.

        A read-only accessor, not a second field. The list lives at
        `visual.source_intent_ids` and stays there: duplicating it would create
        two places to update and one of them would eventually be wrong. This
        exists because callers asking "which reference justified this piece?"
        should not have to know it is nested.
        """
        return self.visual.source_intent_ids


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

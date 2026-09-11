"""Versioned intelligence contracts (plan §4.2, DPR §8)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from ..projects.schema import RoomHint, Vertical

SCHEMA_VERSION = "1.1"

LightingMood = Literal["warm_daylight", "cool_daylight", "evening", "studio"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Inputs ───────────────────────────────────────────────────────────────


class ReferenceImage(BaseModel):
    path: str                      # absolute path on disk
    url: str = ""                  # /files/projects/... for the UI
    filename: str = ""
    content_type: str = "image/jpeg"


class InputBundle(BaseModel):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    project_name: str = ""
    description: str = ""
    # the project's market: picks the room, style and object vocabulary and
    # the JSON-schema enums the provider is constrained to. Carried here so
    # the IntelligenceProvider protocol never has to grow a parameter.
    vertical: Vertical = Vertical.RESIDENTIAL
    room_hints: list[RoomHint] = []
    references: list[ReferenceImage] = []

    @property
    def has_content(self) -> bool:
        return bool(self.description.strip()) or bool(self.references) or bool(self.room_hints)


# ── Design analysis (stage 5) ────────────────────────────────────────────


class RoomAnalysis(BaseModel):
    room_id: str                   # slug, stable across re-runs: living_room, bedroom_1
    name: str
    type: str                      # living_room | bedroom | kitchen | dining_room | bathroom | study | balcony | entry | other
    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    height_m: float = Field(default=3.0, gt=0)
    estimated: bool = True         # DPR §23: dimensions given or explicitly estimated
    notes: str = ""
    adjacent_to: list[str] = []

    @property
    def area_m2(self) -> float:
        return round(self.width_m * self.length_m, 2)

    @property
    def id_for_plan(self) -> str:
        return self.room_id


Placement = Literal["floor", "wall", "ceiling", "on_surface"]


class SpottedObject(BaseModel):
    """One item read from the photos or the brief (open vocabulary, schema 1.1).

    `name` is free text ("mahogany secretary bookcase"); `semantic_type` is the
    closest canonical type (or "other") and `family` the coarse class that
    sizes and shapes unknown types. `bbox` is [x0, y0, x1, y1] as fractions
    of the photo `image_index`, used to cut a crop for textures and
    image-to-3D; `crop_ref` is the project-relative path of that crop.
    """

    semantic_type: str
    name: str = ""
    family: str = "other"
    placement: Placement = "floor"
    support: str = ""              # name of the item it rests on (placement on_surface)
    material: str = ""
    color: str = ""                # hex when known
    approx_dimensions: Optional[tuple[float, float, float]] = None  # w, h, d metres
    room_id: Optional[str] = None
    count: int = 1
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: str = ""                # colour, material, style seen in the photo
    image_index: int = -1
    bbox: Optional[tuple[float, float, float, float]] = None
    crop_ref: str = ""


class DesignAnalysis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    version: int = 1
    intent: str
    rooms: list[RoomAnalysis]
    constraints: list[str] = []
    spotted_objects: list[SpottedObject] = []
    architecture: list[str] = []   # cornice, wainscot, panelled_doors, exposed_beams, arches
    keywords: list[str] = []
    confidence: float = Field(default=0.5, ge=0, le=1)
    provider: str = "mock"
    warnings: list[str] = []
    created_at: str = Field(default_factory=_now)

    def room(self, room_id: str) -> Optional[RoomAnalysis]:
        return next((r for r in self.rooms if r.room_id == room_id), None)


# ── Style (stage 5/6) ────────────────────────────────────────────────────


class StyleSpec(BaseModel):
    schema_version: str = SCHEMA_VERSION
    version: int = 1
    name: str                      # snake_case, e.g. modern_warm_minimal
    tags: list[str] = []
    palette: list[str] = []        # hex colours, dominant first
    materials: list[str] = []      # material_ids from app/materials
    lighting_mood: LightingMood = "warm_daylight"
    description: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    provider: str = "mock"
    warnings: list[str] = []
    created_at: str = Field(default_factory=_now)

    @field_validator("palette")
    @classmethod
    def _hex(cls, values: list[str]) -> list[str]:
        out = []
        for v in values:
            v = v.strip()
            if not v.startswith("#"):
                v = "#" + v
            if len(v) == 7 and all(c in "0123456789abcdefABCDEF" for c in v[1:]):
                out.append(v.upper())
        return out


class MoodboardSpec(BaseModel):
    """What the Studio's moodboard step shows: derived, never edited directly."""

    schema_version: str = SCHEMA_VERSION
    title: str
    style_name: str
    style_tags: list[str] = []
    palette: list[str] = []
    material_ids: list[str] = []
    lighting_mood: LightingMood = "warm_daylight"
    reference_urls: list[str] = []
    keywords: list[str] = []
    rooms: list[str] = []
    created_at: str = Field(default_factory=_now)


# ── Agent envelopes (DPR §8) ─────────────────────────────────────────────


class AgentInput(BaseModel):
    project_id: str
    stage: str
    input_references: list[str] = []
    context: dict[str, Any] = {}
    schema_version: str = SCHEMA_VERSION


class AgentOutput(BaseModel):
    project_id: str
    stage: str
    status: Literal["ok", "fallback", "failed"] = "ok"
    confidence: float = Field(default=0.5, ge=0, le=1)
    result: dict[str, Any] = {}
    warnings: list[str] = []
    next_action: str = ""
    provider: str = ""
    duration_ms: int = 0


# ── Object plan (stages 6–7) ─────────────────────────────────────────────

RelationType = Literal["in_front_of", "beside", "facing", "under", "around", "against_wall"]


class ObjectRelation(BaseModel):
    type: RelationType
    target_key: Optional[str] = None   # another item's object_key; None for against_wall


class ObjectPlanItem(BaseModel):
    object_key: str                    # stable key: "<room_id>.<semantic_type>.<n>"
    semantic_type: str
    room_id: str
    name: str = ""                     # open name from the reading ("brass floor lamp")
    family: str = ""                   # vocab.FAMILIES
    placement: Placement = "floor"
    support_key: Optional[str] = None  # object_key of the piece this sits on (on_surface)
    crop_ref: str = ""                 # project-relative crop of the item in the photo
    spotted_index: int = -1
    priority: int = Field(default=2, ge=1, le=3)   # 1 essential · 2 recommended · 3 optional
    count: int = Field(default=1, ge=1, le=12)
    approx_dimensions: Optional[tuple[float, float, float]] = None  # w, h, d metres
    relation: Optional[ObjectRelation] = None
    style_notes: str = ""
    material_hint: str = ""            # fabric | wood | metal | glass | stone
    color_hint: str = ""
    from_photo: bool = False
    unique: bool = False               # a custom piece: candidate for generation


class ObjectPlan(BaseModel):
    schema_version: str = SCHEMA_VERSION
    version: int = 1
    rooms: list[str] = []
    items: list[ObjectPlanItem] = []
    provider: str = "mock"
    confidence: float = Field(default=0.5, ge=0, le=1)
    warnings: list[str] = []
    created_at: str = Field(default_factory=_now)

    def item(self, key: str) -> Optional[ObjectPlanItem]:
        return next((i for i in self.items if i.object_key == key), None)


# ── Asset plan (stage 8) ─────────────────────────────────────────────────

Strategy = Literal["local_asset", "local_modified", "procedural", "generated"]


class AssetDecision(BaseModel):
    object_key: str
    semantic_type: str
    strategy: Strategy
    asset_id: Optional[str] = None     # registry asset or built-in catalog id
    asset_name: str = ""
    has_model: bool = False
    dimensions: tuple[float, float, float]   # catalog dims at scale 1
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    fit_score: float = 0.0
    color: str = "#8a7862"
    mount: str = "floor"
    material_overrides: dict[str, str] = {}
    shape: str = ""                    # procedural shape hint (photo, lamp, fireplace, ...)
    texture_ref: str = ""              # project-relative image used as the object's face
    generation_prompt: str = ""
    reference_image: str = ""          # crop handed to image-to-3D when generation runs
    reason: str = ""


class AssetPlan(BaseModel):
    schema_version: str = SCHEMA_VERSION
    version: int = 1
    decisions: list[AssetDecision] = []
    counts: dict[str, int] = {}
    warnings: list[str] = []
    created_at: str = Field(default_factory=_now)

    def decision(self, key: str) -> Optional[AssetDecision]:
        return next((d for d in self.decisions if d.object_key == key), None)

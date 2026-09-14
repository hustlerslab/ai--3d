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
    # The upload's own id, stable for the life of the file. Everything that
    # needs to name a photo later names it with this, never with its position
    # in the list — see InputBundle.photo_for.
    input_id: str = ""
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

    def photo_for(self, item: "SpottedObject") -> Optional[ReferenceImage]:
        """The photo an item was read from, or None if it is no longer here.

        Resolves on the upload's stable id. The model can only answer in
        positions ("the sofa is in photo 3"), so the position is turned into an
        id at coercion time, while the bundle it counted is still the one in
        hand. After that the position is dead weight: delete a photo and every
        later index is off by one, which silently re-pointed crops and the
        scene reference at the wrong file until it was caught.

        `image_index` is honoured only for analyses written before `image_ref`
        existed, and callers must treat a None here as a real condition rather
        than quietly carrying on without a photo.
        """
        if item.image_ref:
            return next((r for r in self.references if r.input_id == item.image_ref), None)
        if 0 <= item.image_index < len(self.references):
            return self.references[item.image_index]
        return None


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

# What a read item is FOR. "place" means the client owns it and it becomes
# geometry; "reference" means they photographed it as inspiration and it should
# shape the palette and materials without furnishing the room.
#
# The distinction exists because uploads are often shop or catalogue photos. On
# the sample set the reading correctly found four *different* mattresses in a
# showroom — the bedroom is not meant to contain four beds.
ItemRole = Literal["place", "reference"]


class SpottedObject(BaseModel):
    """One item read from the photos or the brief (open vocabulary, schema 1.1).

    `name` is free text ("mahogany secretary bookcase"); `semantic_type` is the
    closest canonical type (or "other") and `family` the coarse class that
    sizes and shapes unknown types. `bbox` is [x0, y0, x1, y1] as fractions
    of the photo `image_index`, used to cut a crop for textures and
    image-to-3D; `crop_ref` is the project-relative path of that crop.
    """

    # Stable name for this item, filled by `coerce.assign_ids`. The review
    # screen addresses items by this and never by their position — the lesson
    # ADR-002 §2 recorded for photos, applied the day something finally needed
    # to name an item across a request boundary.
    #
    # Derived from the item's own content rather than a random uuid, so a
    # re-read of the same photos produces the same ids and the client's
    # place/reference choices survive it.
    object_id: str = ""
    semantic_type: str
    name: str = ""
    family: str = "other"
    placement: Placement = "floor"
    role: ItemRole = "place"
    support: str = ""              # name of the item it rests on (placement on_surface)
    material: str = ""
    color: str = ""                # hex when known
    approx_dimensions: Optional[tuple[float, float, float]] = None  # w, h, d metres
    room_id: Optional[str] = None
    count: int = 1
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: str = ""                # colour, material, style seen in the photo
    # Which photo. `image_ref` is the upload's stable id and is authoritative;
    # `image_index` is the raw position the model answered with, kept only so
    # analyses written before image_ref existed still resolve. Resolve through
    # InputBundle.photo_for, never by indexing references directly.
    image_ref: str = ""
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


class RoomScene(BaseModel):
    """One room's moodboard image. `url` empty means it could not be painted;
    `error` says why, in words the client can act on."""

    room_id: str
    name: str = ""
    type: str = ""
    url: str = ""
    error: str = ""
    # Same honesty as the hero image: a render that never saw the client's
    # furniture looks exactly like one that did.
    reference_resolved: bool = False
    reference_note: str = ""
    # The prompt this image was painted from, and whether the intelligence
    # layer composed it ("llm") or it fell back to the keyword template
    # ("template"). Recorded rather than hidden: the two read very differently
    # and a reviewer should be able to see which one they are looking at.
    prompt: str = ""
    prompt_source: str = "template"
    # Hash of the recipe (framing, fixtures, rules, size, reference strength)
    # this image was painted under. Empty means "made before versioning
    # existed", which is treated as stale — the retroactive case.
    recipe_version: str = ""
    # The noise seed this image was drawn from. Recorded so a picture a reviewer
    # likes stays that picture, and so "regenerate" is a DIFFERENT draw rather
    # than a re-roll of the same dice. Seed variance is large and is not a
    # prompt defect: the same bathroom prompt gives a complete room on one seed
    # and a bathtub in an alcove on another (ADR-002 §1 on the same effect).
    seed: int = 0


class MoodboardSpec(BaseModel):
    """What the Studio's moodboard step shows: derived, never edited directly."""

    schema_version: str = SCHEMA_VERSION
    title: str
    style_name: str
    style_tags: list[str] = []
    palette: list[str] = []
    material_ids: list[str] = []
    lighting_mood: LightingMood = "warm_daylight"
    # The raw files the user uploaded. Kept for provenance — NOT what the board
    # should show, or the moodboard is just the upload step played back.
    reference_urls: list[str] = []
    # Cutouts of the pieces the reading identified, one per spotted item.
    # Data only: DO NOT put these back on the moodboard. Showing the user's own
    # uploads, cut up, is the upload step played back — it was tried and
    # rejected. The board shows the generated scene or nothing. The crops
    # themselves still earn their keep: they texture rugs and wall art in the
    # Blender build via SceneObject.texture_ref.
    piece_urls: list[str] = []
    # The generated scene: Gemini reads the references and the brief and paints
    # the room it is proposing. Empty when image generation is unavailable —
    # the board still works, it just has no hero image.
    scene_url: str = ""
    # Why there is no scene, in words a user can act on (billing, a refusal).
    scene_error: str = ""
    # One image per room in the reading. `scene_url` above stays the hero (the
    # first room) so anything written against the single-image shape keeps
    # working; this is the whole set.
    room_scenes: list[RoomScene] = []
    # Was the scene actually conditioned on one of the client's photos? A false
    # here with a scene_url present is a real degradation: the render is a
    # generic room, not their room. It is a field rather than a log line
    # because a silently unconditioned image looks exactly like a good one.
    reference_resolved: bool = False
    # Which photo, or why there was none. Shown to the user beside the scene.
    reference_note: str = ""
    keywords: list[str] = []
    rooms: list[str] = []
    created_at: str = Field(default_factory=_now)


# ── Reading the generated scene (moodboard → 3D) ─────────────────────────


ElementCheck = Literal["unchecked", "ok", "mismatch", "crowded", "duplicate", "unreadable"]
"""Verdict of the isolated second look at one crop.

`ok` the crop shows what it claims; `mismatch` it shows something else;
`crowded` no single piece fills it (a whole-room box labelled as one object);
`duplicate` another element already claims the same pixels; `unreadable` the
check itself failed, which is NOT a pass.
"""


class SceneElement(BaseModel):
    """One thing seen in a GENERATED room image.

    Distinct from `SpottedObject`, which is read from the client's own photos.
    This is read from the moodboard the client approved, so it describes the
    design being proposed rather than what they already own — and its crop is
    what image-to-3D turns into a mesh.
    """

    element_id: str = ""
    room_id: str
    name: str = ""                 # free text: "low oak sideboard"
    semantic_type: str = "other"
    # [x0, y0, x1, y1] as fractions of the room image
    bbox: Optional[tuple[float, float, float, float]] = None
    material: str = ""
    color: str = ""                # hex when known
    # Where it sits relative to the room, in the render's own terms. Used as
    # ARRANGEMENT INTENT only — the planner still decides actual metres, because
    # a 2D render has no depth and does not obey the room's real dimensions.
    placement: Placement = "floor"
    against: str = ""              # "window wall", "long wall", "corner"
    faces: str = ""                # what it is oriented towards
    confidence: float = Field(default=0.5, ge=0, le=1)
    crop_ref: str = ""             # project-relative png cut from the render
    # The crop's size BEFORE it was enlarged. Every crop is upscaled to a
    # usable input size, which would otherwise make a 59 x 88 towel rail and
    # a 586 x 420 bed look identical to whoever is reviewing them. The
    # enlargement adds no detail, so the native size is what says how much
    # was really seen.
    crop_px: tuple[int, int] = (0, 0)
    # Real size in metres for THIS piece, when the reader was sure of it.
    # Ingest scales the generated mesh to this; empty means the per-type
    # table decides, which is generic but never absurd.
    dimensions_m: Optional[tuple[float, float, float]] = None

    # A box can be structurally perfect and still be around the wrong thing —
    # a floor plank labelled "table lamp" passes every geometric guard there is.
    # So the crop is shown back to the vision model on its own, with no scene
    # context and no mention of the expected label, and asked what it is.
    check: ElementCheck = "unchecked"
    check_note: str = ""           # what the second look actually saw
    # The human's call, which is the one that gates spend. None = not yet asked.
    approved: Optional[bool] = None
    # Set once this element's crop has been turned into a mesh. Elements that
    # share a `shape_key` share one asset: three identical bar stools are one
    # generation and three placements, not three generations.
    asset_id: str = ""


class RoomSurfaces(BaseModel):
    """Walls and floor as MATERIALS, never as generated meshes.

    Room geometry stays procedural — Blender builds it from the room boundary,
    which is what keeps corners square, doors aligned and the spatial validator
    able to prove nothing blocks a doorway. Generating wall meshes from crops
    would replace geometry that is correct by construction with geometry that
    is correct by luck.
    """

    room_id: str
    wall_color: str = ""
    wall_material: str = ""
    floor_color: str = ""
    floor_material: str = ""
    notes: str = ""


class SceneReading(BaseModel):
    """Everything read out of the approved moodboard, per room."""

    schema_version: str = SCHEMA_VERSION
    version: int = 1
    elements: list[SceneElement] = []
    surfaces: list[RoomSurfaces] = []
    provider: str = "mock"
    warnings: list[str] = []
    created_at: str = Field(default_factory=_now)

    def for_room(self, room_id: str) -> list[SceneElement]:
        return [e for e in self.elements if e.room_id == room_id]


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
    # Position in the analysis this plan was built from, and only that one.
    # Same shape as the image_index bug: re-run the reading and this points at
    # a different item. It survives because nothing downstream reads it — it is
    # written, carried through the planner prompt so items are not dropped, and
    # then dropped itself. Do NOT start resolving it against a stored analysis;
    # give SpottedObject a stable id first, the way ReferenceImage has one.
    spotted_index: int = -1
    # The moodboard element this item came from, when it came from one. Carries
    # the link that lets the asset ladder pick the mesh generated from THIS
    # piece's crop instead of guessing a catalog match by size.
    element_id: str = ""
    # Arrangement intent carried over from the approved render, in its own
    # words ("window wall", "beside the sofa"). Preferences for the placement
    # engine, never instructions: a hint no valid spot satisfies is dropped,
    # and the engine's existing choice stands unchanged.
    against: str = ""
    faces: str = ""
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

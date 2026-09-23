"""Asset records — metadata and provenance for every model in the library.

Plan §16 (Phase 11): no asset enters the catalog without traceable origin
and licence metadata. Dimensions are always post-normalization meters.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..scene.schema import Vec3, new_id

# "surface" arrived with spec 1.1 (a lamp on a bedside table) but this literal
# was never widened with it, so any surface-mounted asset failed to ingest.
# The planner speaks "on_surface" and PLACEMENT_MOUNT translates it to
# "surface" — see app/planning/asset_decision.py.
Mount = Literal["floor", "ceiling", "wall", "surface"]


class AssetSource(BaseModel):
    provider: Literal["polyhaven", "upload", "meshy", "local"] = "upload"
    source_id: str = ""
    url: str = ""
    license: str = "unknown"
    license_url: str = ""
    creator: str = ""
    thumbnail_url: str = ""


class NormalizationInfo(BaseModel):
    version: str = "1"
    detected_unit: Literal["meter", "centimeter", "millimeter", "unknown"] = "unknown"
    unit_scale: float = 1.0
    yaw_offset: float = 0.0
    translation: Vec3 = (0.0, 0.0, 0.0)
    source_size: Vec3 = (0.0, 0.0, 0.0)
    strategy: str = "unit_heuristic"  # unit_heuristic | expected_dimensions | none


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["hard", "warn", "info"]
    message: str


class AssetFiles(BaseModel):
    original: str = ""      # path relative to data dir
    normalized: str = ""    # path relative to data dir
    # Same geometry, textures resized for the browser. Empty when the model was
    # already light enough to need no second copy.
    web: str = ""           # path relative to data dir


class AssetRecord(BaseModel):
    asset_id: str = Field(default_factory=lambda: new_id("asset"))
    name: str
    semantic_type: str
    status: Literal["normalized", "failed"] = "normalized"
    source: AssetSource = AssetSource()
    format: str = "glb"
    files: AssetFiles = AssetFiles()
    dimensions: Vec3 = (0.0, 0.0, 0.0)
    polycount: int = 0
    file_size: int = 0
    textures: dict[str, int] = {"count": 0, "bytes": 0}
    normalization: NormalizationInfo = NormalizationInfo()
    validation: list[ValidationIssue] = []
    mount: Mount = "floor"
    style_tags: list[str] = []
    material_tags: list[str] = []
    room_types: list[str] = []
    price_inr: int = 0
    color: str = "#8a7862"
    created_at: str = ""
    # Set when this model was generated FOR one project from that
    # project's own material. It stays out of the shared catalog: a sofa
    # generated from one client's moodboard is not a library piece, and
    # offering it to the next project would silently put one client's
    # furniture in another's home. Reached by id instead, deliberately.
    project_id: str = ""
    # P1-IDENTITY-004. Which ELEMENT this mesh was generated for, and which
    # uploaded image the crop came from. Without these the library can hold a
    # mesh that cost 30 credits and be unable to say what it is of, so the only
    # way to find out is to look at it.
    #
    # `canonical_element_id`, not `element_id`: the value is the CANONICAL key
    # (`room|type|dims-bucket|material|colour` hashed), so three bar stools
    # share one asset. Naming it `element_id` would invite somebody to store a
    # per-occurrence id here, which is exactly the mistake that made three
    # stools three purchases.
    #
    # Both default to "" so every record already in registry.json loads
    # unchanged. Empty means "not recorded", never "no element" - a Poly Haven
    # download legitimately has neither.
    canonical_element_id: str = ""
    source_image_id: str = ""

    @property
    def valid(self) -> bool:
        return self.status == "normalized" and not any(v.severity == "hard" for v in self.validation)


class IngestMeta(BaseModel):
    """What the ingester needs beyond the file itself."""
    asset_id: Optional[str] = None
    name: str
    semantic_type: str
    expected_dimensions: Optional[Vec3] = None
    yaw_offset: float = 0.0
    mount: Mount = "floor"
    style_tags: list[str] = []
    material_tags: list[str] = []
    room_types: list[str] = []
    price_inr: int = 0
    color: str = "#8a7862"
    source: AssetSource = AssetSource()
    # Set when this model was generated FOR one project from that
    # project's own material. It stays out of the shared catalog: a sofa
    # generated from one client's moodboard is not a library piece, and
    # offering it to the next project would silently put one client's
    # furniture in another's home. Reached by id instead, deliberately.
    project_id: str = ""
    # P1-IDENTITY-004. Carried through to the record so the library can answer
    # "which element is this mesh for" without re-deriving it. Both optional:
    # a Poly Haven download has neither, and an upload may have neither.
    canonical_element_id: str = ""
    source_image_id: str = ""

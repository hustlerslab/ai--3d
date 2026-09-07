"""Asset records — metadata and provenance for every model in the library.

Plan §16 (Phase 11): no asset enters the catalog without traceable origin
and licence metadata. Dimensions are always post-normalization meters.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..scene.schema import Vec3, new_id

Mount = Literal["floor", "ceiling", "wall"]


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

"""Canonical material records (plan §34).

A material is a PBR description: base colour + roughness + metalness, plus
optional texture maps (colour, normal, roughness, AO) and the physical size
one tile covers in meters so tiling is consistent across surfaces.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from ..assets.schema import AssetSource

MaterialCategory = Literal["wood", "marble", "stone", "metal", "fabric", "glass", "paint", "tile", "leather", "plaster"]


class MaterialMaps(BaseModel):
    color: Optional[str] = None       # paths relative to data dir
    normal: Optional[str] = None
    roughness: Optional[str] = None
    ao: Optional[str] = None


class MaterialRecord(BaseModel):
    material_id: str
    name: str
    category: MaterialCategory
    base_color: str = "#cccccc"
    roughness: float = 0.8
    metalness: float = 0.0
    maps: MaterialMaps = MaterialMaps()
    tile_size_m: float = 1.0
    finish: str = "matte"
    style_tags: list[str] = []
    applies_to: list[Literal["floor", "wall", "furniture", "ceiling"]] = ["furniture"]
    source: AssetSource = AssetSource(provider="local", license="n/a")

    @property
    def has_maps(self) -> bool:
        return self.maps.color is not None

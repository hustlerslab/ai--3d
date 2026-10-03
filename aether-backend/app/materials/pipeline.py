"""Attach PBR texture sets to material ids."""
from __future__ import annotations

import logging
from pathlib import Path

from ..assets.schema import AssetSource
from ..core.config import get_settings
from .registry import get_material_registry
from .schema import MaterialMaps, MaterialRecord

log = logging.getLogger("aether.materials")


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(get_settings().data_dir)).replace("\\", "/")


def attach_maps(
    material_id: str,
    files: dict[str, Path],
    source: AssetSource,
    tile_size_m: float | None = None,
    name: str | None = None,
    category: str | None = None,
    base_color: str | None = None,
    roughness: float | None = None,
    style_tags: list[str] | None = None,
    applies_to: list[str] | None = None,
) -> MaterialRecord:
    """Register/refresh a material with downloaded maps. Unknown ids are created."""
    registry = get_material_registry()
    existing = registry.get(material_id)
    record = existing or MaterialRecord(
        material_id=material_id,
        name=name or material_id,
        category=category or "paint",  # type: ignore[arg-type]
    )
    if existing is None and "roughness" in files and roughness is None:
        # P2-RENDER-001: with a map, `roughness` is the glTF factor the map is
        # multiplied by. A new scan renders exactly as scanned (factor 1.0);
        # the scalar default (0.8) is for materials that have no map.
        record.roughness = 1.0
    record.maps = MaterialMaps(
        color=_relative(files["color"]) if "color" in files else None,
        normal=_relative(files["normal"]) if "normal" in files else None,
        roughness=_relative(files["roughness"]) if "roughness" in files else None,
        ao=_relative(files["ao"]) if "ao" in files else None,
    )
    record.source = source
    if tile_size_m:
        record.tile_size_m = tile_size_m
    if name:
        record.name = name
    if category:
        record.category = category  # type: ignore[assignment]
    if base_color:
        record.base_color = base_color
    if roughness is not None:
        record.roughness = roughness
    if style_tags is not None:
        record.style_tags = style_tags
    if applies_to is not None:
        record.applies_to = applies_to  # type: ignore[assignment]
    log.info("Material %s ← maps %s", material_id, sorted(files.keys()))
    return registry.upsert(record)

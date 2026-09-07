"""Ingestion pipeline (plan §14):

    file → parse → measure → normalize → validate → pack GLB → registry

Every model — uploaded, sourced from a CC0 library, or generated — goes
through this exact path. Generated assets never bypass it (plan §28).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings
from . import gltf, normalization, validation
from .registry import get_registry
from .schema import AssetFiles, AssetRecord, IngestMeta

log = logging.getLogger("aether.assets")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(get_settings().data_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def ingest_file(source_path: Path, meta: IngestMeta) -> AssetRecord:
    """Run the full pipeline on a .glb/.gltf on disk and register the result."""
    registry = get_registry()
    asset_id = meta.asset_id or f"asset_{_slug(meta.name)}"

    doc = gltf.load(source_path)
    measurement = gltf.measure(doc)
    textures = gltf.texture_summary(doc)
    plan = normalization.plan(measurement, meta.expected_dimensions, meta.yaw_offset)
    issues = validation.validate(doc, measurement, textures, plan.dimensions)

    record = AssetRecord(
        asset_id=asset_id,
        name=meta.name,
        semantic_type=meta.semantic_type,
        source=meta.source,
        files=AssetFiles(original=_relative(source_path)),
        dimensions=plan.dimensions,
        polycount=measurement.triangles,
        textures=textures,
        normalization=plan.info,
        validation=issues,
        mount=meta.mount,
        style_tags=meta.style_tags,
        material_tags=meta.material_tags,
        room_types=meta.room_types,
        price_inr=meta.price_inr,
        color=meta.color,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    hard = [i for i in issues if i.severity == "hard"]
    if hard:
        record.status = "failed"
        log.warning("Asset %s failed validation: %s", asset_id, "; ".join(i.message for i in hard))
        return registry.upsert(record)

    out_path = registry.normalized_path(asset_id)
    out_path.write_bytes(gltf.pack_glb(doc, plan.root_transform))
    record.files.normalized = _relative(out_path)
    record.file_size = out_path.stat().st_size
    log.info(
        "Ingested %s: %.2fx%.2fx%.2f m, %s tris, unit=%s scale=%.4g",
        asset_id, *plan.dimensions, f"{measurement.triangles:,}", plan.info.detected_unit, plan.info.unit_scale,
    )
    return registry.upsert(record)


def renormalize(asset_id: str, expected_dimensions=None, yaw_offset: float | None = None) -> AssetRecord:
    """Re-run normalization on the stored original with corrected hints."""
    registry = get_registry()
    record = registry.get(asset_id)
    if record is None:
        raise KeyError(asset_id)
    original = get_settings().data_dir / record.files.original
    meta = IngestMeta(
        asset_id=asset_id,
        name=record.name,
        semantic_type=record.semantic_type,
        expected_dimensions=expected_dimensions,
        yaw_offset=record.normalization.yaw_offset if yaw_offset is None else yaw_offset,
        mount=record.mount,
        style_tags=record.style_tags,
        material_tags=record.material_tags,
        room_types=record.room_types,
        price_inr=record.price_inr,
        color=record.color,
        source=record.source,
    )
    return ingest_file(original, meta)

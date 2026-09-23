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
from . import gltf, normalization, validation, web_variant
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


def has_normalized(record: AssetRecord) -> bool:
    """Are this asset's normalized bytes actually in Allure storage? A record
    can outlive its file (a restore without assets, a cleaned disk); a record
    without bytes must never be handed to a scene as "already ours"."""
    if not record.files.normalized:
        return False
    path = get_settings().data_dir / record.files.normalized
    return path.is_file() and path.stat().st_size > 0


def persisted(record: AssetRecord, source_path: Path) -> str:
    """P1-ASSET-004 - why this asset is NOT safely in Allure storage, or "".

    Meshy keeps generated files for 3 days on non-Enterprise plans, behind
    signed, time-limited URLs. A purchase is only safe once the bytes are
    ours, so completion may be recorded only when the downloaded original AND
    the normalized copy exist here and are non-empty, and nothing on the
    record still points at a vendor file URL. Callers treat a non-empty
    answer as "not done": the task stays resumable and a retry downloads
    again while the window is open, instead of a success that names a file
    that is not there.
    """
    if not source_path.is_file() or source_path.stat().st_size == 0:
        return f"original missing or empty: {source_path.name}"
    if not record.files.normalized:
        return "no normalized copy recorded"
    if not has_normalized(record):
        return f"normalized copy missing or empty: {record.files.normalized}"
    thumb = record.source.thumbnail_url
    if record.source.provider == "meshy" and thumb.startswith(("http://", "https://")):
        return f"thumbnail still points at the vendor: {thumb[:60]}"
    return ""


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
        project_id=meta.project_id,
        canonical_element_id=meta.canonical_element_id,
        source_image_id=meta.source_image_id,
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

    # A viewer-sized copy beside it. A generated mesh carries three 2048 px
    # maps - 88 % of its bytes and 48 MB of GPU memory each - and fifteen of
    # them asked for ~900 MB of texture memory, which a 6 GB card refused
    # silently: every model showed as a placeholder. Never fatal: if this
    # fails the viewer simply loads the full-size file, as it did before.
    try:
        web_out = registry.web_path(asset_id)
        stats = web_variant.build(out_path, web_out)
        if stats["images_resized"]:
            record.files.web = _relative(web_out)
            log.info("Web variant for %s: %.1f MB -> %.1f MB, VRAM %.0f MB -> %.0f MB",
                     asset_id, stats["source_bytes"] / 2**20, stats["dest_bytes"] / 2**20,
                     stats["vram_before"] / 2**20, stats["vram_after"] / 2**20)
        else:
            web_out.unlink(missing_ok=True)      # nothing to gain; do not keep a copy
    except Exception:                            # noqa: BLE001
        log.exception("%s: web variant failed; the viewer will load the full model", asset_id)
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

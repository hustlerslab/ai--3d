"""Stage 3: turn the crops a human approved into meshes, once per project.

The moodboard is the brief, but until this job existed nothing downstream read
it: the 3D scene was assembled entirely from catalog pieces chosen off the
written brief, so the room the client approved and the room they were shown had
almost no objects in common (ADR-003 s9). This is the wire.

Three rules keep the bill down, in the order they matter:

  * Only what a human ticked. `approved_for_generation` is the sole source of
    work; `approved is None` is not consent and generates nothing.
  * One mesh per distinct piece per room. Three "black bar stool" boxes at one
    counter are three placements of one stool, not three generations.
  * The glb file IS the checkpoint. A re-run, a retry, a restart, or a second
    click of the button re-uses what is on disk and spends nothing. That is the
    same contract `generate_assets` keeps for the text-to-3D path.

Everything is submitted before anything is waited on, because the vendor queues
in parallel: five pieces took 237 s together and would have taken about twelve
minutes one after another.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from ...assets import pipeline as asset_pipeline
from ...assets.schema import AssetSource, IngestMeta
from ...core.config import Settings, get_settings
from ...intelligence.schema import SceneElement, SceneReading
from ...intelligence.scene_reading import approved_for_generation, distinct_shapes
from ...providers import meshy
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

SCENE_READING = "planning/scene_reading.json"
# Meshy image-to-3D is a flat 30 per piece: textured in one task, no
# preview/refine split. Quoted to the user before they press the button.
CREDITS_PER_PIECE = 30


class MeshyNotConfigured(Exception):
    pass


class ReadingRequired(Exception):
    pass


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:48]


def _glb_rel(key: str) -> str:
    return f"assets/elements/{_safe(key)}.glb"


def _asset_id(project_id: str, key: str) -> str:
    return f"el_{project_id[-8:]}_{_safe(key)}".lower()


def _target_dims(element: SceneElement) -> tuple[float, float, float]:
    """Real-world size for the piece, from the vocabulary, never from the crop.

    A render has no depth and does not obey the room's real size, so the crop's
    pixels say nothing about metres. Normalizing every mesh to these is also
    what stops independently generated pieces arriving at unrelated scales and
    a bedside table turning up the size of the bed.
    """
    from ...planning.asset_decision import _BUILTIN_BY_TYPE, DEFAULT_DIMS
    from ...intelligence import vocab

    # What the reader measured for THIS piece, when it was sure and the figure
    # was plausible, beats the per-type table - which cannot tell a single bed
    # from a king or a 2-seater from a 3.
    if element.dimensions_m:
        return tuple(element.dimensions_m)
    if element.semantic_type in DEFAULT_DIMS:
        return DEFAULT_DIMS[element.semantic_type][0]
    builtin = _BUILTIN_BY_TYPE.get(element.semantic_type)
    if builtin is not None:
        return builtin.dimensions
    family = vocab.family_for(element.semantic_type)
    return vocab.FAMILY_DEFAULTS.get(family, vocab.FAMILY_DEFAULTS["other"])[0]


def _mount(element: SceneElement) -> str:
    from ...planning.asset_decision import PLACEMENT_MOUNT

    return PLACEMENT_MOUNT.get(element.placement, "floor")


async def _generate_one(client: httpx.AsyncClient, ctx: JobContext, key: str,
                        element: SceneElement, settings: Settings) -> tuple[str, int]:
    crop = ctx.path(element.crop_ref)
    if not crop.is_file():
        raise meshy.MeshyError(f"crop missing on disk: {element.crop_ref}")

    task_id = await meshy.submit_image_to_3d(
        client, crop,
        should_remesh=settings.meshy_should_remesh,
        target_polycount=settings.meshy_target_polycount,
    )
    ctx.emit("elements.submit", f"{element.name}: task {task_id}")

    model = await meshy.wait_for(
        client, task_id,
        timeout_seconds=float(settings.meshy_timeout_seconds),
        poll_seconds=float(settings.meshy_poll_seconds),
        on_progress=lambda status, pct: ctx.emit("elements.task", f"{element.name}: {status.lower()} {pct}%"),
        endpoint=meshy.IMAGE_TO_3D,
    )

    dest = ctx.path(_glb_rel(key))
    await meshy.download_glb(client, model.glb_url, dest)

    record = asset_pipeline.ingest_file(
        dest,
        IngestMeta(
            asset_id=_asset_id(ctx.project_id, key),
            name=element.name or element.semantic_type.replace("_", " "),
            semantic_type=element.semantic_type,
            expected_dimensions=_target_dims(element),
            mount=_mount(element),                        # type: ignore[arg-type]
            color=element.color,
            project_id=ctx.project_id,
            source=AssetSource(
                provider="meshy",
                source_id=model.task_id,
                url=f"{meshy.BASE}/{meshy.IMAGE_TO_3D}/{model.task_id}",
                license=meshy.LICENSE,
                license_url=meshy.LICENSE_URL,
                creator="Meshy",
                thumbnail_url=model.thumbnail_url,
            ),
        ),
    )
    if record.status == "failed":
        why = "; ".join(i.message for i in record.validation if i.severity == "hard")
        # The checkpoint IS the file, so a rejected download must not survive:
        # left on disk it reads as "already done" and this piece would never be
        # retried, silently keeping a catalog stand-in forever.
        dest.unlink(missing_ok=True)
        raise meshy.MeshyError(f"generated model failed ingest validation: {why}")
    return record.asset_id, model.credits


def _ensure_registered(ctx: JobContext, key: str, element: SceneElement) -> Optional[str]:
    """Make a checkpoint on disk into an asset the scene can actually load.

    The glb file being present is what stops us re-buying it, but the SCENE
    resolves an asset id, not a path. Those two drifted: files re-keyed on disk
    kept their old registry ids, so the plan referenced nine assets that
    resolved to nothing and every one of them silently fell back to a procedural
    box. The render looked like a scene; it was stand-ins.

    So reuse verifies the id resolves, and re-ingests locally when it does not.
    Ingest is a local parse-measure-normalize; it calls no vendor and costs
    nothing.
    """
    from ...assets.registry import get_registry

    asset_id = _asset_id(ctx.project_id, key)
    record = get_registry().get(asset_id)
    if record is not None and record.status != "failed":
        return asset_id
    source = ctx.path(_glb_rel(key))
    if not source.is_file():
        return None
    try:
        rec = asset_pipeline.ingest_file(source, IngestMeta(
            asset_id=asset_id,
            name=element.name or element.semantic_type.replace("_", " "),
            semantic_type=element.semantic_type,
            expected_dimensions=_target_dims(element),
            mount=_mount(element),                       # type: ignore[arg-type]
            color=element.color,
            project_id=ctx.project_id,
            source=AssetSource(provider="meshy", source_id=key, license=meshy.LICENSE,
                               license_url=meshy.LICENSE_URL, creator="Meshy"),
        ))
    except Exception as exc:                             # noqa: BLE001
        ctx.emit("elements.reuse", f"{element.name}: cannot register existing mesh: {exc}", status="warning")
        return None
    if rec.status == "failed":
        ctx.emit("elements.reuse", f"{element.name}: existing mesh fails validation", status="warning")
        return None
    ctx.emit("elements.reuse", f"{element.name}: re-registered from disk as {asset_id} (0 credits)")
    return asset_id


async def _run(ctx: JobContext, todo: dict[str, SceneElement], settings: Settings) -> dict[str, Any]:
    made: dict[str, str] = {}
    warnings: list[str] = []
    credits = 0
    async with meshy.make_client(
        settings.meshy_api_key.get_secret_value(), float(settings.meshy_timeout_seconds)
    ) as client:
        try:
            ctx.emit("elements.balance", f"{await meshy.balance(client)} credit(s) before this batch")
        except meshy.MeshyError as exc:          # never block a batch on a status read
            ctx.emit("elements.balance", f"balance unavailable: {exc}", status="warning")

        async def one(key: str, element: SceneElement):
            try:
                return key, await _generate_one(client, ctx, key, element, settings), None
            except Exception as exc:                      # noqa: BLE001
                ctx.log.exception("%s: element generation failed", key)
                return key, None, exc

        for key, result, exc in await asyncio.gather(*(one(k, e) for k, e in todo.items())):
            name = todo[key].name
            if exc is not None:
                # One vendor failure keeps that piece's catalog match and the
                # rest of the batch stands: degradation is the point.
                warnings.append(f"{name}: {type(exc).__name__}: {exc}")
                ctx.emit("elements.failed", f"{name}: {exc}; keeping the catalog match", status="warning")
                continue
            asset_id, spent = result                      # type: ignore[misc]
            made[key] = asset_id
            credits += spent
            ctx.emit("elements.done", f"{name} -> {asset_id} ({spent} credit(s))")
    return {"made": made, "warnings": warnings, "credits": credits}


@register(
    "generate_elements",
    lane=JobLane.ai,
    max_attempts=2,
    description="Turn approved moodboard crops into meshes (Meshy image-to-3D)",
)
def generate_elements(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    if not settings.meshy_configured:
        raise MeshyNotConfigured("MESHY_API_KEY is not set; nothing to generate with")
    if not ctx.has_checkpoint(SCENE_READING):
        raise ReadingRequired("run scene_plan first: planning/scene_reading.json missing")

    reading = SceneReading.model_validate(ctx.read_json(SCENE_READING))
    ready, held = approved_for_generation(reading)
    if not ready:
        ctx.emit("elements.skip",
                 f"nothing approved yet - {len(held)} element(s) waiting on review", status="warning")
        return {"made": {}, "reused": 0, "attached": 0, "warnings": [], "credits": 0, "held": len(held)}

    groups = distinct_shapes(ready)
    limit = max(0, int(ctx.params.get("limit", settings.meshy_max_per_project)))

    todo: dict[str, SceneElement] = {}
    reused = 0
    for key, els in groups.items():
        if ctx.has_checkpoint(_glb_rel(key)):
            reused += 1                                   # already bought; never bought twice
            continue
        todo[key] = els[0]                                # the biggest crop of the group
    over = max(0, len(todo) - limit)
    todo = dict(list(todo.items())[:limit])

    ctx.emit("elements.start",
             f"{len(ready)} approved -> {len(groups)} distinct piece(s); "
             f"{reused} already generated, {len(todo)} to generate"
             + (f", {over} over the limit of {limit}" if over else ""))

    result = (asyncio.run(_run(ctx, todo, settings)) if todo
              else {"made": {}, "warnings": [], "credits": 0})
    made: dict[str, str] = result["made"]

    # Every element of a group points at that group's one mesh, including the
    # copies that were never generated: that is what makes three bar stools one
    # purchase and three placements.
    attached = 0
    for key, els in groups.items():
        asset_id: Optional[str] = made.get(key)
        if not asset_id and ctx.has_checkpoint(_glb_rel(key)):
            asset_id = _ensure_registered(ctx, key, els[0])
        if not asset_id:
            continue
        for el in els:
            el.asset_id = asset_id
            attached += 1
    reading.warnings += result["warnings"]
    ctx.write_json(SCENE_READING, reading)

    ctx.emit("elements.finish",
             f"{len(made)} generated, {reused} reused, {attached} element(s) now carry a mesh "
             f"({result['credits']} credit(s) spent)")
    return {"made": made, "reused": reused, "attached": attached,
            "warnings": result["warnings"], "credits": result["credits"],
            "skipped_over_limit": over}


__all__ = ["generate_elements"]

"""Stages 6–9: object plan → asset plan → compiled Scene (committed via patches).

Checkpoints: planning/object_plan.json, planning/asset_plan.json,
planning/scene_spec.json (a snapshot of the committed Scene). `resolve_assets`
re-runs the asset decision on the current scene after user edits.
"""
from __future__ import annotations

from typing import Any

from ...intelligence import (
    AssetPlan,
    DesignAnalysis,
    ObjectPlan,
    StyleSpec,
    build_input_bundle,
    get_provider,
)
from ...intelligence.schema import ObjectPlanItem
from ...planning import compile_scene, decide_asset, place_objects, resolve_plan
from ...planning.asset_decision import style_materials
from ...projects.schema import ProjectStage
from ...scene.patches import Patch, PatchError, ReplaceAssetOp, commit_patch
from ...scene.store import get_store
from ...spatial.validation import validate_scene
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

SCENE_READING = "planning/scene_reading.json"
OBJECT_PLAN = "planning/object_plan.json"
ASSET_PLAN = "planning/asset_plan.json"
SCENE_SPEC = "planning/scene_spec.json"
ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"


class AnalysisRequired(Exception):
    pass


def _room_images(ctx: JobContext, analysis) -> dict:
    """room_id -> the approved render, for rooms that actually have one."""
    from ...intelligence.schema import MoodboardSpec

    path = ctx.path("analysis/moodboard_spec.json")
    if not path.exists():
        return {}
    board = MoodboardSpec.model_validate(ctx.read_json("analysis/moodboard_spec.json"))
    out = {}
    for scene in board.room_scenes:
        if not scene.url:
            continue
        # scene.url is a /files/... url; the file sits under the project dir
        rel = scene.url.split(f"{ctx.project_id}/", 1)[-1]
        candidate = ctx.path(rel)
        if candidate.is_file():
            out[scene.room_id] = candidate
    return out


def _read_scene(ctx: JobContext, analysis, style, provider, *, force: bool):
    """Read every approved room render into elements, crops and surfaces.

    Optional by design: a provider without the capability, or a project whose
    moodboard was never painted, yields an empty reading and the plan proceeds
    exactly as it did before. The reading enriches the plan; it is not a
    precondition for having one.
    """
    from ...intelligence.scene_reading import (
        check_element_crops, coerce_room_reading, estimate_dimensions,
        write_element_crops)
    from ...intelligence.schema import SceneReading
    from ...projects.layout import project_dir

    if ctx.has_checkpoint(SCENE_READING) and not force:
        reading = SceneReading.model_validate(ctx.read_json(SCENE_READING))
        ctx.emit("plan.read", f"checkpoint present, skipped ({len(reading.elements)} element(s))")
        return reading

    images = _room_images(ctx, analysis)
    read = getattr(provider, "read_scene_elements", None)
    if not images or not callable(read):
        why = "no approved room images yet" if not images else f"{provider.label} cannot read renders"
        ctx.emit("plan.read", f"skipped — {why}", status="warning")
        return SceneReading(provider=getattr(provider, "label", "none"),
                            warnings=[f"scene reading skipped: {why}"])

    elements, surfaces, warnings = [], [], []
    for room in analysis.rooms:
        image = images.get(room.room_id)
        if image is None:
            warnings.append(f"{room.room_id}: no approved image; not read")
            continue
        raw = read(image, room, style, ctx.project.vertical) or {}
        if not raw:
            warnings.append(f"{room.room_id}: the reader returned nothing")
            continue
        room_elements, room_surfaces = coerce_room_reading(raw, room, ctx.project.vertical, warnings)
        elements.extend(room_elements)
        if room_surfaces is not None:
            surfaces.append(room_surfaces)
        ctx.emit("plan.read", f"{room.name}: {len(room_elements)} element(s)")

    reading = SceneReading(elements=elements, surfaces=surfaces,
                           provider=getattr(provider, "label", "unknown"), warnings=warnings)
    root = project_dir(ctx.project_id)
    reading.warnings += write_element_crops(reading, images, root, force=force)
    # Second look at each crop on its own. A box can be structurally perfect
    # and around the wrong thing, and only a fresh look at the cut-out picture
    # can tell. Optional like the read itself: a provider that cannot do it
    # leaves every element `unchecked`, which the approval gate treats as
    # needing a human, not as a pass.
    # How big each piece really is, before anything is generated from it: the
    # mesh is scaled to this at ingest, and a per-type table cannot tell a
    # single bed from a king or size a range hood at all.
    sized = estimate_dimensions(reading, {r.room_id: r for r in analysis.rooms},
                                ctx.project.vertical, provider, reading.warnings)
    if sized:
        ctx.emit("plan.size", f"{sized} piece(s) measured in metres by the reader")

    if callable(getattr(provider, "check_element_crop", None)):
        tally = check_element_crops(
            reading, {r.room_id: r.type for r in analysis.rooms},
            ctx.project.vertical, root, provider)
        ctx.emit("plan.check", ", ".join(f"{n} {k}" for k, n in sorted(tally.items())) or "nothing to check",
                 status="warning" if tally.get("ok", 0) < sum(tally.values()) else "info")
    reading.version = ctx.projects.next_analysis_version(ctx.project_id, "scene_reading")
    ctx.write_json(SCENE_READING, reading)
    ctx.projects.add_analysis(ctx.project_id, "scene_reading", SCENE_READING, reading.version)
    ctx.mark_checkpoint("scene_reading")
    cut = sum(1 for e in reading.elements if e.crop_ref)
    ctx.emit(
        "plan.read",
        f"{len(reading.elements)} element(s) across {len(images)} room(s), {cut} crop(s) cut, "
        f"{len(reading.surfaces)} surface set(s)",
    )
    return reading


def _load_specs(ctx: JobContext) -> tuple[DesignAnalysis, StyleSpec]:
    if not ctx.has_checkpoint(ANALYSIS) or not ctx.has_checkpoint(STYLE):
        raise AnalysisRequired("run the analyze job first: analysis/design_analysis.json or style_spec.json missing")
    return DesignAnalysis.model_validate(ctx.read_json(ANALYSIS)), StyleSpec.model_validate(ctx.read_json(STYLE))


@register(
    "scene_plan",
    lane=JobLane.ai,
    max_attempts=2,
    stage_running=ProjectStage.ASSET_PLANNING,
    stage_done=ProjectStage.ASSETS_READY,
    description="Object plan → asset resolution → compiled Scene",
    uses_intelligence=True,
)
def scene_plan(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    # Re-reading the moodboard is NOT part of "force". It calls the vision model
    # again, and because the answer is non-deterministic the new elements get
    # new ids and new names — which discards every approval a human made and
    # orphans every mesh already bought from those crops. Forcing a re-plan cost
    # 12 approvals and re-priced 7 pieces we already owned at 210 credits before
    # this was separated. Ask for it explicitly.
    force_read = bool(ctx.params.get("force_read", False))
    analysis, style = _load_specs(ctx)
    bundle = build_input_bundle(ctx.project_id)
    provider = get_provider()
    warnings: list[str] = []

    # ── read the approved moodboard ──────────────────────────────────────
    reading = _read_scene(ctx, analysis, style, provider, force=force_read)
    warnings += reading.warnings

    # ── object plan ──────────────────────────────────────────────────────
    if ctx.has_checkpoint(OBJECT_PLAN) and not force:
        plan = ObjectPlan.model_validate(ctx.read_json(OBJECT_PLAN))
        ctx.emit("plan.objects", "checkpoint present, skipped")
    else:
        plan = provider.plan_objects(analysis, style, bundle)
        # The approved render decides what is in the rooms it shows; the brief
        # keeps the rooms it does not. Free, and not gated on approval -
        # approval gates SPENDING, which is the generate_elements job.
        from ...intelligence.scene_reading import merge_reading_into_plan

        plan, merge_notes = merge_reading_into_plan(plan, reading)
        for note in merge_notes:
            ctx.emit("plan.merge", note)
        plan.version = ctx.projects.next_analysis_version(ctx.project_id, "object_plan")
        ctx.write_json(OBJECT_PLAN, plan)
        ctx.projects.add_analysis(ctx.project_id, "object_plan", OBJECT_PLAN, plan.version)
        ctx.mark_checkpoint("object_plan")
        ctx.emit(
            "plan.objects",
            f"{len(plan.items)} item(s) across {len(plan.rooms)} room(s) via {plan.provider} "
            f"[vertical={ctx.project.vertical.value}]",
        )
    warnings += plan.warnings

    # ── asset plan ───────────────────────────────────────────────────────
    if ctx.has_checkpoint(ASSET_PLAN) and not force:
        assets = AssetPlan.model_validate(ctx.read_json(ASSET_PLAN))
        ctx.emit("plan.assets", "checkpoint present, skipped")
    else:
        # Meshes already made from these elements' own crops outrank the
        # catalog: the client chose that piece, everything else is a substitute.
        element_assets = {e.element_id: e.asset_id for e in reading.elements if e.asset_id}
        assets = resolve_plan(plan, style, element_assets)
        if element_assets:
            ctx.emit("plan.assets", f"{len(element_assets)} element(s) carry a generated mesh")
        assets.version = ctx.projects.next_analysis_version(ctx.project_id, "asset_plan")
        ctx.write_json(ASSET_PLAN, assets)
        ctx.projects.add_analysis(ctx.project_id, "asset_plan", ASSET_PLAN, assets.version)
        ctx.mark_checkpoint("asset_plan")
        ctx.emit("plan.assets", ", ".join(f"{k}={v}" for k, v in sorted(assets.counts.items())))
    warnings += assets.warnings

    # ── scene ────────────────────────────────────────────────────────────
    store = get_store()
    if ctx.has_checkpoint(SCENE_SPEC) and not force:
        snapshot = ctx.read_json(SCENE_SPEC)
        scene = store.load(snapshot["scene_id"])
        ctx.emit("plan.scene", f"checkpoint present, skipped (scene {scene.scene_id} v{scene.version})")
    else:
        scene, layout_warnings = compile_scene(ctx.project_id, analysis, style,
                                               name=f"{ctx.project.name} · {style.name}", reading=reading)
        warnings += layout_warnings
        store.create(scene)
        ctx.emit("plan.scene", f"{len(scene.rooms)} room(s), {len(scene.walls)} wall(s), {len(scene.openings)} opening(s) laid out")

        ops, place_warnings = place_objects(scene, plan, assets)
        warnings += place_warnings
        committed = _commit_with_retry(store, scene, ops, warnings)
        scene = committed
        ctx.write_json(SCENE_SPEC, scene)
        ctx.projects.attach_scene(ctx.project_id, scene.scene_id)
        ctx.projects.add_scene_spec(ctx.project_id, scene.scene_id, scene.version, SCENE_SPEC)
        ctx.mark_checkpoint("scene_spec")
        ctx.emit("plan.scene", f"{len(scene.objects)} object(s) placed and validated · scene {scene.scene_id} v{scene.version}")

    violations = validate_scene(scene)
    hard = [v for v in violations if v.severity == "hard"]
    strategies: dict[str, int] = {}
    for o in scene.objects:
        strategies[o.source_strategy] = strategies.get(o.source_strategy, 0) + 1
    return {
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "rooms": len(scene.rooms),
        "objects": len(scene.objects),
        "strategies": strategies,
        "hard_violations": len(hard),
        "planned_items": len(plan.items),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _commit_with_retry(store, scene, ops, warnings: list[str], attempts: int = 4):
    """Commit the add operations; on hard violations drop the offending
    objects and retry, so one bad placement never blocks the whole scene."""
    current = ops
    for _ in range(attempts):
        if not current:
            return store.load(scene.scene_id)
        patch = Patch(scene_id=scene.scene_id, base_version=store.load(scene.scene_id).version, operations=current, source="system")
        try:
            return commit_patch(store, patch)
        except PatchError as exc:
            bad = {v.object_id for v in exc.violations if v.object_id} | {v.related_id for v in exc.violations if v.related_id}
            if not bad:
                raise
            dropped = [op for op in current if op.object.object_id in bad]
            for op in dropped:
                warnings.append(f"dropped {op.object.semantic_type} ({op.object.plan_key}): {exc.message}")
            current = [op for op in current if op.object.object_id not in bad]
    return store.load(scene.scene_id)


@register(
    "resolve_assets",
    lane=JobLane.ai,
    max_attempts=2,
    description="Re-run the asset decision on the current scene (after edits)",
    uses_intelligence=True,
)
def resolve_assets(ctx: JobContext) -> dict[str, Any]:
    analysis, style = _load_specs(ctx)
    if not ctx.project.scene_ids:
        raise AnalysisRequired("project has no scene yet: run scene_plan first")
    store = get_store()
    scene = store.load(ctx.project.scene_ids[-1])
    roles = style_materials(style)
    decisions = []
    ops: list[ReplaceAssetOp] = []
    for obj in scene.objects:
        if obj.locked:
            continue
        item = ObjectPlanItem(
            object_key=obj.plan_key or obj.object_id,
            semantic_type=obj.semantic_type,
            room_id=obj.room_id,
            approx_dimensions=tuple(d * s for d, s in zip(obj.dimensions, obj.scale)),  # type: ignore[arg-type]
        )
        decision = decide_asset(item, style, roles=roles)
        decisions.append(decision)
        if decision.has_model and decision.asset_id and decision.asset_id != obj.asset_id:
            ops.append(ReplaceAssetOp(object_id=obj.object_id, asset_id=decision.asset_id))
    changed = 0
    if ops:
        try:
            scene = commit_patch(store, Patch(scene_id=scene.scene_id, base_version=scene.version, operations=ops, source="system"))
            changed = len(ops)
        except PatchError as exc:
            ctx.emit("resolve.assets", f"replacement rejected: {exc.message}", status="warning")
    assets = AssetPlan(decisions=decisions, counts={}, warnings=[])
    for d in decisions:
        assets.counts[d.strategy] = assets.counts.get(d.strategy, 0) + 1
    assets.version = ctx.projects.next_analysis_version(ctx.project_id, "asset_plan")
    ctx.write_json(ASSET_PLAN, assets)
    ctx.projects.add_analysis(ctx.project_id, "asset_plan", ASSET_PLAN, assets.version)
    ctx.write_json(SCENE_SPEC, scene)
    ctx.emit("resolve.assets", f"{changed} object(s) upgraded to registry models")
    return {"scene_id": scene.scene_id, "scene_version": scene.version, "replaced": changed, "counts": assets.counts}

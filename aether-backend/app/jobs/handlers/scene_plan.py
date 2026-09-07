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

OBJECT_PLAN = "planning/object_plan.json"
ASSET_PLAN = "planning/asset_plan.json"
SCENE_SPEC = "planning/scene_spec.json"
ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"


class AnalysisRequired(Exception):
    pass


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
)
def scene_plan(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    analysis, style = _load_specs(ctx)
    bundle = build_input_bundle(ctx.project_id)
    provider = get_provider()
    warnings: list[str] = []

    # ── object plan ──────────────────────────────────────────────────────
    if ctx.has_checkpoint(OBJECT_PLAN) and not force:
        plan = ObjectPlan.model_validate(ctx.read_json(OBJECT_PLAN))
        ctx.emit("plan.objects", "checkpoint present, skipped")
    else:
        plan = provider.plan_objects(analysis, style, bundle)
        plan.version = ctx.projects.next_analysis_version(ctx.project_id, "object_plan")
        ctx.write_json(OBJECT_PLAN, plan)
        ctx.projects.add_analysis(ctx.project_id, "object_plan", OBJECT_PLAN, plan.version)
        ctx.mark_checkpoint("object_plan")
        ctx.emit("plan.objects", f"{len(plan.items)} item(s) across {len(plan.rooms)} room(s) via {plan.provider}")
    warnings += plan.warnings

    # ── asset plan ───────────────────────────────────────────────────────
    if ctx.has_checkpoint(ASSET_PLAN) and not force:
        assets = AssetPlan.model_validate(ctx.read_json(ASSET_PLAN))
        ctx.emit("plan.assets", "checkpoint present, skipped")
    else:
        assets = resolve_plan(plan, style)
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
        scene, layout_warnings = compile_scene(ctx.project_id, analysis, style, name=f"{ctx.project.name} · {style.name}")
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

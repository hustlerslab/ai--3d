"""The Orchestrator's RE_SOLVE target: run the EXISTING Repair Engine on the
committed scene (P1-ORCHESTRATOR-001 / P1-REPAIR-001).

A geometry or solver failure is repaired by `app/spatial/repair_engine.py` -
never by asking a model for coordinates. The engine's own bound
(`MAX_ITERATIONS`) is untouched; the OUTER bound is `jobs.repair_round`,
held by the runner.

Commits only through `commit_patch`, so a partially repaired scene - one that
still carries a hard violation - is never committed: the job reports it, with
its FailureCategory, and the Orchestrator decides what happens next.
"""
from __future__ import annotations

from typing import Any

from ...scene.patches import MoveObjectOp, Patch, RotateObjectOp, commit_patch
from ...scene.store import get_store
from ...spatial.repair_engine import repair_scene as run_repair_engine
from ...spatial.validation import validate_scene
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

SCENE_SPEC = "planning/scene_spec.json"
SPATIAL_CHECK = "planning/spatial_check.json"


class SceneRequired(Exception):
    pass


def spatial_report(ctx: JobContext, summary: dict[str, Any]) -> None:
    """Refresh the `repair` section of the spatial report - the deterministic
    result the Validator consumes - keeping every other section as written."""
    report = ctx.read_json(SPATIAL_CHECK) if ctx.has_checkpoint(SPATIAL_CHECK) else {}
    report["repair"] = summary
    ctx.write_json(SPATIAL_CHECK, report)


@register("check_scene", lane=JobLane.ai, max_attempts=1,
          description="Re-run the deterministic scene checks on the committed scene")
def check_scene(ctx: JobContext) -> dict[str, Any]:
    """Layers 1-7 again, on what is committed NOW - so a scene changed after
    it was planned is verified against the same gate. Deterministic; changes
    nothing; the Validator reads its report."""
    if not ctx.project.scene_ids:
        raise SceneRequired("project has no scene: run scene_plan first")
    scene = get_store().load(ctx.project.scene_ids[-1])
    hard = [v for v in validate_scene(scene) if v.severity == "hard"]
    # §31 row 8: every object the plan committed must still be there. The
    # plan's own snapshot is the reference; a piece gone from the committed
    # scene is reported for a person to confirm, never silently accepted.
    missing: list[str] = []
    if ctx.has_checkpoint(SCENE_SPEC):
        planned = {o.get("object_id") for o in ctx.read_json(SCENE_SPEC).get("objects", [])}
        missing = sorted(planned - {o.object_id for o in scene.objects})
    summary = {"terminal_state": "ALREADY_VALID" if not hard else "CHECKED", "hard_before": len(hard),
               "hard_after": len(hard), "moved": [], "scene_version": scene.version,
               "missing_objects": missing,
               "violations": [{"code": v.code, "object_id": v.object_id, "category": v.failure_category}
                              for v in hard][:50]}
    spatial_report(ctx, summary)
    if missing:
        ctx.emit("check.scene", f"{len(missing)} planned object(s) missing from the committed scene",
                 status="warning", event_type="validation.failed", severity="error", entity_ids=missing,
                 evidence_refs=[SPATIAL_CHECK, SCENE_SPEC], payload={"missing_objects": missing})
    if hard:
        ctx.emit("check.scene", f"{len(hard)} hard violation(s) in the committed scene v{scene.version}",
                 status="warning", event_type="validation.failed", severity="error",
                 entity_ids=sorted({v.object_id for v in hard if v.object_id}), evidence_refs=[SPATIAL_CHECK],
                 payload={k: summary[k] for k in ("hard_after", "scene_version")})
    return summary


@register("repair_scene", lane=JobLane.ai, max_attempts=1,
          description="Re-validate the committed scene and run the Repair Engine on hard violations")
def repair_scene(ctx: JobContext) -> dict[str, Any]:
    if not ctx.project.scene_ids:
        raise SceneRequired("project has no scene: run scene_plan first")
    store = get_store()
    scene = store.load(ctx.project.scene_ids[-1])
    hard = [v for v in validate_scene(scene) if v.severity == "hard"]
    if not hard:
        summary = {"terminal_state": "ALREADY_VALID", "hard_before": 0, "hard_after": 0, "moved": [],
                   "scene_version": scene.version, "round": ctx.job.repair_round}
        spatial_report(ctx, summary)
        ctx.emit("repair.scene", f"scene v{scene.version} already valid", event_type="repair.completed",
                 severity="info", evidence_refs=[SPATIAL_CHECK], payload=summary)
        return {"repaired": True, **summary}

    result = run_repair_engine(scene.model_copy(deep=True))
    before = {o.object_id: o for o in scene.objects}
    ops = []
    for o in result.scene.objects:
        old = before.get(o.object_id)
        if old is None:
            continue
        if tuple(o.position) != tuple(old.position):
            ops.append(MoveObjectOp(object_id=o.object_id, position=o.position))
        if o.rotation_y != old.rotation_y:
            ops.append(RotateObjectOp(object_id=o.object_id, rotation_y=o.rotation_y))
    moved = sorted({op.object_id for op in ops})
    summary = {"terminal_state": result.terminal_state, "hard_before": result.hard_before,
               "hard_after": result.hard_after, "moved": moved, "round": ctx.job.repair_round,
               "failure_category": result.failure_category}

    if result.hard_after == 0 and ops:
        committed = commit_patch(store, Patch(scene_id=scene.scene_id, base_version=scene.version,
                                              operations=ops, source="system"))
        ctx.write_json(SCENE_SPEC, committed)
        ctx.projects.add_scene_spec(ctx.project_id, committed.scene_id, committed.version, SCENE_SPEC)
        summary["scene_version"] = committed.version
        spatial_report(ctx, summary)
        ctx.emit("repair.scene", f"repaired: {len(moved)} object(s) moved, scene v{committed.version}",
                 event_type="repair.completed", severity="info", entity_ids=moved,
                 evidence_refs=[SPATIAL_CHECK, SCENE_SPEC], payload=summary)
        return {"repaired": True, **summary}

    summary["scene_version"] = scene.version
    spatial_report(ctx, summary)
    ctx.emit("repair.scene", f"not repaired: {result.terminal_state}, {result.hard_after} hard violation(s) remain",
             status="warning", event_type="validation.failed", severity="error",
             entity_ids=sorted({v.object_id for v in hard if v.object_id}), evidence_refs=[SPATIAL_CHECK],
             payload=summary)
    return {"repaired": False, **summary}

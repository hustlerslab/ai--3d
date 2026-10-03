"""P1-VALIDATOR-001 (render lane): render fresh viewpoints of the committed
scene and ray-cast their visibility, then compute `VerificationEvidence`
(design.md §16). Owns the Blender calls directly - like `build`/`preview` do -
rather than re-enqueuing the `viewpoints` job, so one `verify` run is one
Blender process for the render step and one for the visibility step.
"""
from __future__ import annotations

from typing import Any

from ...blender import BlenderRunner
from ...scene.store import get_store
from ...verification.render_verifier import default_viewpoints, verify_scene
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

BLEND = "blender/scene.blend"
REPORT = "blender/validation_report.json"
OBJECT_PLAN = "planning/object_plan.json"
VIEWS_SPEC = "blender/verify_views.json"
RENDER_DIR = "renders/verify"
EVIDENCE = "planning/render_verification.json"


class BuildRequired(Exception):
    pass


@register(
    "verify",
    lane=JobLane.render,
    max_attempts=2,
    description="Render verification: fresh viewpoints, ray-cast visibility, VerificationEvidence (design.md §16)",
)
def verify(ctx: JobContext) -> dict[str, Any]:
    if not ctx.project.scene_ids:
        raise BuildRequired("project has no scene: run scene_plan first")
    if not ctx.has_checkpoint(BLEND):
        raise BuildRequired("blender/scene.blend missing: run build first")

    scene = get_store().load(ctx.project.scene_ids[-1])
    build_report = ctx.read_json(REPORT) if ctx.has_checkpoint(REPORT) else {}
    object_plan_items = {}
    if ctx.has_checkpoint(OBJECT_PLAN):
        object_plan_items = {i["object_key"]: i for i in ctx.read_json(OBJECT_PLAN).get("items", [])}

    views = default_viewpoints(scene)
    entrance_xz = ctx.params.get("entrance_xz")
    entrance_xz = tuple(entrance_xz) if entrance_xz else None

    render_ids: list[str] = []
    visibility_detail: list[dict] = []
    if views:
        out_dir = ctx.path(RENDER_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx.write_json(VIEWS_SPEC, {"out_dir": str(out_dir), "profile": "preview", "views": views})

        runner = BlenderRunner()
        ctx.emit("verify.render", f"rendering {len(views)} verification viewpoint(s)")
        render_res = runner.run(
            "render_viewpoints.py",
            ["--spec", str(ctx.path(VIEWS_SPEC))],
            blend=ctx.path(BLEND),
            log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.verify_render.log",
            timeout=1800,
        )
        render_ids = [r["name"] for r in render_res.result.get("rendered", [])]

        ctx.emit("verify.visibility", "ray-casting object visibility (deterministic, no model)")
        vis_res = runner.run(
            "check_visibility.py",
            ["--spec", str(ctx.path(VIEWS_SPEC))],
            blend=ctx.path(BLEND),
            log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.verify_visibility.log",
            timeout=1800,
        )
        visibility_detail = vis_res.result.get("detail", [])

    evidence = verify_scene(
        scene,
        build_report=build_report,
        visibility_detail=visibility_detail,
        render_ids=render_ids,
        object_plan_items=object_plan_items,
        entrance_xz=entrance_xz,
    )
    ctx.write_json(EVIDENCE, evidence.model_dump())
    ctx.mark_checkpoint("render_verification")
    ctx.add_output("render_verification", EVIDENCE, {
        "scene_version": scene.version, "ok": evidence.ok, "coverage": evidence.summary.get("coverage"),
    })

    message = (
        f"{'VERIFIED' if evidence.ok else 'issues found'} · coverage {evidence.summary.get('coverage')} · "
        f"placement {evidence.summary.get('placement_within_tolerance')} · orientation {evidence.summary.get('orientation_match')}"
    )
    if evidence.ok:
        ctx.emit("verify.done", message, evidence_refs=[EVIDENCE], payload={"ok": True, "summary": evidence.summary})
    else:
        ctx.emit("verify.done", message, status="warning", event_type="validation.failed", severity="warning",
                 evidence_refs=[EVIDENCE], payload={"ok": False, "summary": evidence.summary,
                                                     "scene_checks": evidence.scene_checks})
    return {"verification_id": evidence.verification_id, "ok": evidence.ok, "summary": evidence.summary,
            "scene_checks": evidence.scene_checks, "outputs": {"evidence": ctx.url(EVIDENCE)}}

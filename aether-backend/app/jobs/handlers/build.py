"""Stage 9 (render lane): compile the build manifest and run Blender.

Checkpoints: blender/build_manifest.json, blender/scene.blend,
blender/validation_report.json, previews/build_preview.png.
"""
from __future__ import annotations

import json
from typing import Any

from ...blender import BlenderRunner
from ...blender.manifest import build_manifest, write_manifest
from ...projects.schema import ProjectStage
from ...scene.store import get_store
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

MANIFEST = "blender/build_manifest.json"
BLEND = "blender/scene.blend"
REPORT = "blender/validation_report.json"
PREVIEW = "previews/build_preview.png"


class SceneRequired(Exception):
    pass


@register(
    "build",
    lane=JobLane.render,
    max_attempts=2,
    stage_running=ProjectStage.SCENE_BUILDING,
    stage_done=ProjectStage.SCENE_VALIDATING,
    description="Blender build from the manifest + scene validation + preview still",
)
def build(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    want_preview = bool(ctx.params.get("preview", True))
    profile = str(ctx.params.get("preview_profile", "preview"))
    if not ctx.project.scene_ids:
        raise SceneRequired("project has no scene: run scene_plan first")
    scene = get_store().load(ctx.project.scene_ids[-1])

    # ── manifest ─────────────────────────────────────────────────────────
    manifest_path = ctx.path(MANIFEST)
    fresh = True
    if manifest_path.exists() and not force:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("scene_id") == scene.scene_id and existing.get("scene_version") == scene.version:
            fresh = False
            manifest = existing
            ctx.emit("build.manifest", f"checkpoint present, skipped (scene v{scene.version})")
    if fresh:
        manifest = build_manifest(scene, project_id=ctx.project_id, project_root=ctx.dir, preview=want_preview, preview_profile=profile)
        write_manifest(manifest, manifest_path)
        ctx.mark_checkpoint("build_manifest")
        ctx.emit(
            "build.manifest",
            f"{len(manifest['objects'])} object(s), {len(manifest['walls'])} wall(s), "
            f"{len(manifest['materials'])} material(s) · scene v{scene.version}",
        )

    # ── blender ──────────────────────────────────────────────────────────
    blend = ctx.path(BLEND)
    report_path = ctx.path(REPORT)
    if blend.exists() and report_path.exists() and not fresh and not force:
        ctx.emit("build.blender", "checkpoint present, skipped")
        result = {"reused": True}
    else:
        runner = BlenderRunner()
        ctx.emit("build.blender", f"launching Blender ({runner.blender_path})")
        args = ["--manifest", str(manifest_path)]
        if not want_preview:
            args.append("--no-preview")
        res = runner.run("build_scene.py", args, log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.blender.log", timeout=900)
        result = res.result
        ctx.mark_checkpoint("scene_blend")
        stages = result.get("stages", {})
        ctx.emit(
            "build.blender",
            f"built in {res.duration_s:.1f}s · objects {result.get('objects')} · "
            + ", ".join(f"{k} {v}s" for k, v in stages.items()),
        )

    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"ok": False, "errors": ["no report"], "warnings": []}
    ctx.emit(
        "build.validate",
        f"{'ok' if report.get('ok') else 'issues'} · {len(report.get('errors', []))} error(s), {len(report.get('warnings', []))} warning(s)",
        status="progress" if report.get("ok") else "warning",
    )

    outputs = {"blend": ctx.url(BLEND), "report": ctx.url(REPORT)}
    ctx.add_output("scene_blend", BLEND, {"scene_id": scene.scene_id, "scene_version": scene.version})
    ctx.add_output("validation_report", REPORT, {"ok": report.get("ok")})
    if ctx.path(PREVIEW).exists():
        outputs["preview"] = ctx.url(PREVIEW)
        ctx.add_output("build_preview", PREVIEW, {"profile": profile})

    return {
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "validation_ok": bool(report.get("ok")),
        "errors": report.get("errors", []),
        "warnings": report.get("warnings", []),
        "counts": report.get("counts", {}),
        "blender_seconds": result.get("seconds"),
        "outputs": outputs,
    }

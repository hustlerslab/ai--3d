"""P1-BLENDER-002 (render lane): render N camera viewpoints from the ALREADY
BUILT `scene.blend`, without rebuilding it.

`blender/scripts/render_viewpoints.py` already existed and already opens the
saved .blend rather than reconstructing the scene from the manifest - this
just gives it a registered job so a caller (verification, P1-VALIDATOR-001;
or anything else that wants a look from specific angles) can ask for it
through the runner instead of shelling out to the script directly.

This handler knows nothing about WHY the viewpoints were asked for - it takes
a list of {name, position, look_at} in Blender coordinates and renders them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...blender import BlenderRunner
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

BLEND = "blender/scene.blend"


class BuildRequired(Exception):
    pass


class ViewsRequired(Exception):
    pass


@register(
    "viewpoints",
    lane=JobLane.render,
    max_attempts=2,
    description="Render N camera viewpoints from the committed scene.blend, without rebuilding",
)
def viewpoints(ctx: JobContext) -> dict[str, Any]:
    views = ctx.params.get("views") or []
    if not views:
        raise ViewsRequired("no viewpoints given: pass params.views = [{name, position, look_at}, ...]")
    if not ctx.has_checkpoint(BLEND):
        raise BuildRequired("blender/scene.blend missing: run build first")

    profile = str(ctx.params.get("profile", "preview"))
    subdir = str(ctx.params.get("subdir", "default"))
    out_dir = ctx.path(f"renders/viewpoints/{subdir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    spec_rel = f"blender/viewpoints_spec_{subdir}.json"
    ctx.write_json(spec_rel, {"out_dir": str(out_dir), "profile": profile, "views": views})

    runner = BlenderRunner()
    ctx.emit("viewpoints.render", f"rendering {len(views)} viewpoint(s) at {profile} · lane=render (GPU mutex held)")
    res = runner.run(
        "render_viewpoints.py",
        ["--spec", str(ctx.path(spec_rel))],
        blend=ctx.path(BLEND),
        log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.viewpoints.log",
        timeout=1800,
    )
    rendered = res.result.get("rendered", [])
    device = res.result.get("device")
    rendered_urls = [
        {"name": r["name"], "url": ctx.url(Path(r["path"]).relative_to(ctx.dir).as_posix())}
        for r in rendered
    ]

    manifest_rel = f"renders/viewpoints/{subdir}/manifest.json"
    ctx.write_json(manifest_rel, {
        "subdir": subdir,
        "profile": profile,
        "device": device,
        "seconds": res.result.get("seconds"),
        "rendered": rendered_urls,
    })
    if subdir == "default":
        ctx.mark_checkpoint("viewpoints")
    ctx.add_output("viewpoints", manifest_rel, {"subdir": subdir, "count": len(rendered), "device": device})
    ctx.emit("viewpoints.done", f"{len(rendered)} viewpoint(s) rendered in {res.duration_s:.0f}s on {device}",
             event_type="render.generated", severity="info",
             evidence_refs=[manifest_rel, BLEND],
             payload={"subdir": subdir, "count": len(rendered), "device": device})
    return {"rendered": rendered_urls, "manifest": ctx.url(manifest_rel), "count": len(rendered), "device": device}

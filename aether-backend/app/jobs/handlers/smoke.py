"""Blender smoke job: renders the default cube through the render lane.

Proves the backend → subprocess → Blender → file → /files URL path end to
end (plan M0 exit check). Params: engine (CYCLES|BLENDER_EEVEE), samples.
"""
from __future__ import annotations

from ...blender.runner import BlenderRunner
from ..context import JobContext
from ..registry import register
from ..schema import JobLane


@register("blender_smoke", lane=JobLane.render, max_attempts=2, description="Blender headless smoke render")
def blender_smoke(ctx: JobContext) -> dict:
    engine = str(ctx.params.get("engine", "CYCLES"))
    samples = int(ctx.params.get("samples", 16))
    relative = f"previews/smoke_{engine.lower()}.png"
    out = ctx.path(relative)

    if out.exists() and ctx.params.get("reuse", True):
        ctx.emit("blender.smoke", "render already present, skipped")
    else:
        ctx.emit("blender.smoke", f"launching Blender ({engine}, {samples} samples)")
        runner = BlenderRunner()
        result = runner.smoke(
            out, engine=engine, samples=samples, log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.blender.log"
        )
        ctx.emit(
            "blender.smoke",
            f"rendered in {result.duration_s:.1f}s on {result.result.get('device', '?')}",
        )
        ctx.mark_checkpoint(relative)

    ctx.add_output("smoke_render", relative, {"engine": engine})
    return {"image": ctx.url(relative), "engine": engine}

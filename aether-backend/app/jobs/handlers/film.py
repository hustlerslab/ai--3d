"""Optional film export (plan M6c): the guided-tour route as an Eevee MP4.

Secondary to the in-browser tour; useful for sharing on social. Writes
renders/walkthrough_<profile>.mp4 + a poster frame and records the film in
tour.json so the share page can offer it.
"""
from __future__ import annotations

import json
from typing import Any

from ...blender import BlenderRunner
from ...blender.manifest import to_blender_xyz
from ...scene.store import get_store
from ...walkthrough import service as walkthrough_service
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

BLEND = "blender/scene.blend"
TOUR = "outputs/web/tour.json"


class BuildRequired(Exception):
    pass


@register("film", lane=JobLane.render, max_attempts=2, description="Eevee walkthrough film along the tour route")
def film(ctx: JobContext) -> dict[str, Any]:
    profile = str(ctx.params.get("profile", "preview"))
    force = bool(ctx.params.get("force", False))
    if not ctx.project.scene_ids or not ctx.has_checkpoint(BLEND):
        raise BuildRequired("run build before rendering a film")
    scene = get_store().load(ctx.project.scene_ids[-1])
    rel = f"renders/walkthrough_{profile}.mp4"
    poster_rel = f"renders/walkthrough_{profile}_poster.png"
    out = ctx.path(rel)

    if out.exists() and not force:
        ctx.emit("film.render", "film present, skipped")
        result: dict[str, Any] = {"reused": True}
    else:
        tour = walkthrough_service.generate_tour(scene)
        path_file = ctx.path(f"blender/film_path_{profile}.json")
        ctx.write_json(
            path_file.relative_to(ctx.dir).as_posix(),
            {
                "keyframes": [
                    {"position": to_blender_xyz(k.position), "look_at": to_blender_xyz(k.look_at), "duration": k.duration}
                    for k in tour.keyframes
                ],
                "total_duration": tour.total_duration,
            },
        )
        ctx.emit("film.render", f"rendering {tour.total_duration:.0f}s of film at {profile} ({len(tour.keyframes)} keyframes)")
        res = BlenderRunner().run(
            "render_walkthrough.py",
            ["--path", str(path_file), "--out", str(out), "--profile", profile, "--poster", str(ctx.path(poster_rel))],
            blend=ctx.path(BLEND),
            log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.blender.log",
            timeout=3600,
        )
        result = res.result
        ctx.emit("film.render", f"{result.get('frames')} frames in {res.duration_s:.0f}s ({result.get('seconds_of_film')}s of film)")

    ctx.mark_checkpoint("walkthrough" if profile == "standard" else rel)
    ctx.add_output("film", rel, {"profile": profile, "poster": ctx.url(poster_rel) if ctx.path(poster_rel).exists() else None})

    # advertise the film in the web package if the tour exists
    tour_path = ctx.path(TOUR)
    if tour_path.exists():
        data = json.loads(tour_path.read_text(encoding="utf-8"))
        data["film"] = {"mp4_url": ctx.url(rel), "poster_url": ctx.url(poster_rel) if ctx.path(poster_rel).exists() else "", "profile": profile}
        if "film" not in data.get("modes", []):
            data.setdefault("modes", []).append("film")
        ctx.write_json(TOUR, data)
    return {"film": ctx.url(rel), "poster": ctx.url(poster_rel) if ctx.path(poster_rel).exists() else None, "profile": profile, "frames": result.get("frames")}

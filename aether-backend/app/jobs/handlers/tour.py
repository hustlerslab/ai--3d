"""Stage 11 (render lane): camera plan → panoramas → tour.json → output package.

preview     CAMERA_PLANNING → PREVIEW_RENDERING   pano_preview profile (fast)
walkthrough FINAL_RENDERING → COMPLETED           pano_final + hero stills + manifest

Both write outputs/web/tour.json (plan §8A); the final pass upgrades the
panorama urls in place, so the share link never breaks between the two.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ...blender import BlenderRunner
from ...blender.manifest import to_blender_xyz
from ...projects.schema import ProjectStage
from ...scene.store import get_store
from ...walkthrough import service as walkthrough_service
from ...walkthrough.tour_nodes import TourNode, plan_nodes
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

BLEND = "blender/scene.blend"
CAMERA_PATH = "blender/camera_path.json"
TOUR = "outputs/web/tour.json"
OUTPUT_MANIFEST = "outputs/manifest.json"


class BuildRequired(Exception):
    pass


def _nodes_for_blender(nodes: list[TourNode]) -> dict[str, Any]:
    return {"nodes": [{"id": n.id, "location": to_blender_xyz(n.position), "rz": round(n.yaw, 6)} for n in nodes]}


def _camera_plan(ctx: JobContext, scene, force: bool) -> tuple[list[TourNode], list[str]]:
    if ctx.has_checkpoint(CAMERA_PATH) and not force:
        data = ctx.read_json(CAMERA_PATH)
        if data.get("scene_version") == scene.version:
            nodes = [TourNode.model_validate(n) for n in data["nodes"]]
            ctx.emit("tour.camera", f"checkpoint present, skipped ({len(nodes)} node(s))")
            return nodes, data["route"]
    nodes, route = plan_nodes(scene)
    tour = walkthrough_service.generate_tour(scene)
    ctx.write_json(
        CAMERA_PATH,
        {
            "scene_id": scene.scene_id,
            "scene_version": scene.version,
            "nodes": [n.model_dump() for n in nodes],
            "route": route,
            "keyframes": [k.model_dump() for k in tour.keyframes],
            "total_duration": tour.total_duration,
            "room_order": tour.room_order,
        },
    )
    ctx.mark_checkpoint("camera_path")
    ctx.emit("tour.camera", f"{len(nodes)} panorama node(s) along {' → '.join(tour.room_order)}")
    return nodes, route


def _render_panoramas(ctx: JobContext, nodes: list[TourNode], profile: str, subdir: str, force: bool) -> dict[str, str]:
    """Render nodes that are missing; return id → relative path."""
    out_dir = ctx.path(f"outputs/web/panos/{subdir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    missing = [n for n in nodes if force or not (out_dir / f"{n.id}.jpg").exists()]
    if not missing:
        ctx.emit("tour.render", f"{len(nodes)} panorama(s) present, skipped")
    else:
        nodes_file = ctx.path(f"blender/pano_nodes_{subdir}.json")
        ctx.write_json(nodes_file.relative_to(ctx.dir).as_posix(), _nodes_for_blender(missing))
        runner = BlenderRunner()
        ctx.emit("tour.render", f"rendering {len(missing)} panorama(s) at {profile}")
        res = runner.run(
            "render_panoramas.py",
            ["--nodes", str(nodes_file), "--out-dir", str(out_dir), "--profile", profile],
            blend=ctx.path(BLEND),
            log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.blender.log",
            timeout=3600,
        )
        per = ", ".join(f"{r['id']} {r['seconds']}s" for r in res.result.get("rendered", []))
        ctx.emit("tour.render", f"{len(missing)} panorama(s) in {res.duration_s:.0f}s on {res.result.get('device')} · {per}")
    return {n.id: f"outputs/web/panos/{subdir}/{n.id}.jpg" for n in nodes}


def _write_tour(ctx: JobContext, scene, nodes: list[TourNode], route: list[str], panos: dict[str, str], quality: str) -> dict:
    tour = {
        "schema_version": "1.0",
        "project_id": ctx.project_id,
        "project_name": ctx.project.name,
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "quality": quality,
        "modes": ["explore", "tour"],
        "explore": {"scene_id": scene.scene_id, "scene_url": f"/api/scenes/{scene.scene_id}"},
        "style": scene.style.model_dump() if scene.style else {},
        "rooms": [
            {"room_id": r.room_id, "name": r.name, "type": r.type, "boundary": [list(p) for p in r.boundary]}
            for r in scene.rooms
        ],
        "tour": {
            "nodes": [
                {
                    "id": n.id,
                    "room_id": n.room_id,
                    "room_name": n.room_name,
                    "label": n.label,
                    "position": list(n.position),
                    "yaw": n.yaw,
                    "yaw_deg": round(n.yaw * 57.29577951, 2),
                    "pano_url": ctx.url(panos[n.id]),
                    "links": n.links,
                }
                for n in nodes
            ],
            "route": route,
            "autoplay_seconds_per_node": 6,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ctx.write_json(TOUR, tour)
    return tour


@register(
    "preview",
    lane=JobLane.render,
    max_attempts=2,
    stage_running=ProjectStage.CAMERA_PLANNING,
    stage_done=ProjectStage.PREVIEW_RENDERING,
    description="Camera plan + preview panoramas + tour.json",
)
def preview(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    profile = str(ctx.params.get("profile", "pano_preview"))
    if not ctx.project.scene_ids:
        raise BuildRequired("no scene: run scene_plan and build first")
    if not ctx.has_checkpoint(BLEND):
        raise BuildRequired("blender/scene.blend missing: run build first")
    scene = get_store().load(ctx.project.scene_ids[-1])
    nodes, route = _camera_plan(ctx, scene, force)
    panos = _render_panoramas(ctx, nodes, profile, "preview", force)
    tour = _write_tour(ctx, scene, nodes, route, panos, "preview")
    ctx.mark_checkpoint("preview")
    ctx.add_output("tour", TOUR, {"quality": "preview", "nodes": len(nodes)})
    ctx.emit("tour.package", f"tour.json with {len(nodes)} node(s) · {ctx.url(TOUR)}")
    return {"tour": ctx.url(TOUR), "nodes": len(nodes), "route": route, "profile": profile}


@register(
    "walkthrough",
    lane=JobLane.render,
    max_attempts=2,
    stage_running=ProjectStage.FINAL_RENDERING,
    stage_done=ProjectStage.COMPLETED,
    description="Final panoramas + hero stills + output package",
)
def walkthrough(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    profile = str(ctx.params.get("profile", "pano_final"))
    stills = int(ctx.params.get("hero_stills", 2))
    if not ctx.project.scene_ids or not ctx.has_checkpoint(BLEND):
        raise BuildRequired("run build (and preview) before the final walkthrough")
    scene = get_store().load(ctx.project.scene_ids[-1])
    nodes, route = _camera_plan(ctx, scene, force)
    panos = _render_panoramas(ctx, nodes, profile, "final", force)
    tour = _write_tour(ctx, scene, nodes, route, panos, "final")

    hero_urls = _hero_stills(ctx, nodes, stills, force)

    package = {
        "project_id": ctx.project_id,
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "tour": ctx.url(TOUR),
        "panoramas": [ctx.url(p) for p in panos.values()],
        "hero_stills": hero_urls,
        "scene_blend": ctx.url(BLEND),
        "scene_spec": ctx.url("planning/scene_spec.json"),
        "validation_report": ctx.url("blender/validation_report.json"),
        "generated_at": tour["generated_at"],
    }
    ctx.write_json(OUTPUT_MANIFEST, package)
    ctx.mark_checkpoint("outputs")
    ctx.add_output("tour", TOUR, {"quality": "final", "nodes": len(nodes)})
    ctx.add_output("package", OUTPUT_MANIFEST, {"hero_stills": len(hero_urls)})
    ctx.emit("tour.package", f"final package: {len(nodes)} panorama(s), {len(hero_urls)} hero still(s)")
    return {"tour": ctx.url(TOUR), "package": ctx.url(OUTPUT_MANIFEST), "nodes": len(nodes), "hero_stills": hero_urls}


def _hero_stills(ctx: JobContext, nodes: list[TourNode], count: int, force: bool) -> list[str]:
    """Cycles stills from the first `count` nodes (hero_still profile)."""
    if count <= 0:
        return []
    from ...blender.manifest import build_manifest, write_manifest

    urls: list[str] = []
    scene = get_store().load(ctx.project.scene_ids[-1])
    for n in nodes[:count]:
        rel = f"renders/hero_{n.id}.png"
        out = ctx.path(rel)
        if out.exists() and not force:
            urls.append(ctx.url(rel))
            continue
        manifest = build_manifest(scene, project_id=ctx.project_id, project_root=ctx.dir, preview=True, preview_profile="hero_still")
        manifest["output"]["preview"] = str(out)
        manifest["camera"]["preview_shot"] = {"position": to_blender_xyz(n.position), "look_at": to_blender_xyz(n.look_at)}
        path = ctx.path(f"blender/hero_{n.id}_manifest.json")
        write_manifest(manifest, path)
        ctx.emit("tour.hero", f"rendering hero still at {n.label}")
        res = BlenderRunner().run("build_scene.py", ["--manifest", str(path)], log_path=ctx.dir / "logs" / f"{ctx.job.job_id}.hero.log", timeout=1800)
        if out.exists():
            urls.append(ctx.url(rel))
            ctx.add_output("hero_still", rel, {"node": n.id, "seconds": res.result.get("seconds")})
    return urls

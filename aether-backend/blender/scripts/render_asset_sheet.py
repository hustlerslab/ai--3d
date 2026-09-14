"""Render each GLB on a plain ground, three-quarter view, for visual review.

    blender -b --factory-startup --python-exit-code 1 \
        --python render_asset_sheet.py -- --glb a.glb b.glb --out <dir> [--size 512]

Exists so a generated mesh can be judged by looking at it beside the crop it
came from, rather than by its triangle count. Every claim about generated
geometry in this build has had to be shown: a "sparse rooms" report turned out
to be a stale .blend, and an "unresolved stand-in" turned out to be a real sofa
seen in a distorted equirect.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore
import mathutils  # type: ignore

from _common import emit_result, enable_gpu, fail, parse


def clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def bounds(objs: list) -> tuple[mathutils.Vector, float]:
    """World-space centre and half-extent over every imported mesh."""
    lo = mathutils.Vector((float("inf"),) * 3)
    hi = mathutils.Vector((float("-inf"),) * 3)
    for o in objs:
        for corner in o.bound_box:
            p = o.matrix_world @ mathutils.Vector(corner)
            for i in range(3):
                lo[i], hi[i] = min(lo[i], p[i]), max(hi[i], p[i])
    return (lo + hi) / 2, (max(hi[i] - lo[i] for i in range(3)) / 2) or 1.0


def render_one(glb: Path, out: Path, size: int) -> dict:
    clear()
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=str(glb))
    objs = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
    if not objs:
        return {"glb": glb.name, "ok": False, "error": "no meshes in file"}
    tris = 0
    for o in objs:
        o.data.calc_loop_triangles()
        tris += len(o.data.loop_triangles)
    centre, radius = bounds(objs)

    # A ground plane, so the piece is seen sitting on something. A floating
    # mesh reads as fine even when its base is missing, which is one of the
    # failures this test is looking for.
    bpy.ops.mesh.primitive_plane_add(size=radius * 30,
                                     location=(centre.x, centre.y, centre.z - radius))
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.22, 0.22, 0.24, 1)
    bpy.context.object.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    d = radius * 3.2
    cam.location = (centre.x + d * 0.75, centre.y - d * 0.75, centre.z + d * 0.5)
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    # A key sun plus a bright world fill: enough contrast to read the
    # silhouette, enough fill that nothing important hides in its own shadow.
    sun_data = bpy.data.lights.new("key", type="SUN")
    sun_data.energy = 4.0
    sun = bpy.data.objects.new("key", sun_data)
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))
    bpy.context.scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.35, 0.36, 0.40, 1)
    bg.inputs[1].default_value = 1.1
    bpy.context.scene.world = world

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 48
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    return {"glb": glb.name, "ok": True, "triangles": tris, "png": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=512)
    ns = parse(ap)
    out_dir = Path(ns.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = enable_gpu()
    rows = []
    for path in ns.glb:
        p = Path(path)
        if not p.is_file():
            rows.append({"glb": p.name, "ok": False, "error": "missing"})
            continue
        try:
            rows.append(render_one(p, out_dir / (p.stem + ".png"), ns.size))
        except Exception as exc:                  # one bad mesh never sinks the sheet
            rows.append({"glb": p.name, "ok": False, "error": str(exc)[:160]})
    if not any(r.get("ok") for r in rows):
        fail("nothing rendered", rows=rows, device=device)
    emit_result({"ok": True, "device": device, "rows": rows})


if __name__ == "__main__":
    main()

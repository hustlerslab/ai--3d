"""Render a built scene from several camera angles, for verification.

Opens the project's saved .blend - it does NOT rebuild - and shoots the room
from each viewpoint it is given. The point is to look at what Blender actually
assembled rather than at the numbers that were sent to it: a piece can sit at
the right coordinate in the spec and still be invisible, sunk into a wall, or
missing because its asset never arrived.

    blender -b scene.blend --python render_viewpoints.py -- --spec views.json

where views.json is {"out_dir": "...", "profile": "preview",
                     "views": [{"name": "...", "position": [x,y,z],
                                "look_at": [x,y,z]}]}
in BLENDER coordinates (y is depth, z is up), which is what the manifest
already speaks.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from _common import Timer, configure_engine, emit_result, fail, parse, set_output
from render_preview import PROFILES, look_at


def _camera():
    cam_data = bpy.data.cameras.new("VerifyCamera")
    cam_data.lens = 24.0          # wide enough to hold a whole small room
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 0.05
    cam = bpy.data.objects.new("VerifyCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    args = parse(ap)

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    views = spec.get("views") or []
    if not views:
        fail("no views given")
    out_dir = spec.get("out_dir") or "."
    os.makedirs(out_dir, exist_ok=True)
    prof = PROFILES.get(spec.get("profile", "preview"), PROFILES["preview"])

    timer = Timer()
    cam = _camera()
    rendered = []
    for view in views:
        cam.location = tuple(view["position"])
        look_at(cam, tuple(view["look_at"]))
        path = os.path.join(out_dir, f"{view['name']}.png")
        scene = bpy.context.scene
        scene.camera = cam
        configure_engine(scene, prof["engine"], prof["samples"])
        set_output(scene, path, prof["size"][0], prof["size"][1])
        bpy.ops.render.render(write_still=True)
        rendered.append({"name": view["name"], "path": path})

    emit_result({"ok": True, "rendered": rendered, "seconds": round(timer.seconds, 2)})


if __name__ == "__main__":
    main()

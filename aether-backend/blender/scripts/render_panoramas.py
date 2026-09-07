"""Render equirectangular panoramas at tour nodes from a built scene.blend.

    blender -b scene.blend --factory-startup --python-exit-code 1 \
        --python render_panoramas.py -- --nodes nodes.json --out-dir <dir> --profile pano_preview

nodes.json: {"nodes": [{"id", "location": [x, y, z], "rz": yaw_rad}, ...]}
(Blender coordinates, Z-up; rz is the yaw of the forward direction, +Y at 0,
the same convention as scene objects.) The image centre is the forward
direction, horizon level.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from _common import Timer, configure_engine, emit_result, fail, parse

PROFILES = {
    "pano_preview": {"samples": 32, "size": (2048, 1024), "denoise": True},
    "pano_final": {"samples": 128, "size": (4096, 2048), "denoise": True},
    "pano_test": {"samples": 4, "size": (256, 128), "denoise": False},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--profile", default="pano_preview")
    ns = parse(parser)
    with open(ns.nodes, "r", encoding="utf-8") as fh:
        nodes = json.load(fh)["nodes"]
    prof = PROFILES.get(ns.profile, PROFILES["pano_preview"])
    os.makedirs(ns.out_dir, exist_ok=True)

    scene = bpy.context.scene
    device = configure_engine(scene, "CYCLES", prof["samples"], prof["denoise"])
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.max_bounces = 6
    scene.render.resolution_x, scene.render.resolution_y = prof["size"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 90

    cam_data = bpy.data.cameras.new("PanoCamera")
    cam_data.type = "PANO"
    try:
        cam_data.panorama_type = "EQUIRECTANGULAR"
    except AttributeError:  # pre-4.0 API
        cam_data.cycles.panorama_type = "EQUIRECTANGULAR"
    cam_data.clip_start = 0.05
    cam = bpy.data.objects.new("PanoCamera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    timer = Timer()
    rendered = []
    for node in nodes:
        t0 = timer.seconds
        cam.location = node["location"]
        cam.rotation_euler = (math.pi / 2, 0.0, float(node["rz"]))
        out = os.path.join(ns.out_dir, f"{node['id']}.jpg")
        scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        if not os.path.exists(out):
            fail(f"panorama {node['id']} produced no file")
        rendered.append({"id": node["id"], "file": out, "seconds": round(timer.seconds - t0, 1)})
        print(f"ALLURE_STAGE pano.{node['id']} {timer.seconds}", flush=True)

    emit_result(
        {
            "ok": True,
            "profile": ns.profile,
            "device": device,
            "size": prof["size"],
            "samples": prof["samples"],
            "rendered": rendered,
            "seconds": timer.seconds,
            "blender": bpy.app.version_string,
        }
    )


try:
    main()
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    fail(f"{type(exc).__name__}: {exc}")

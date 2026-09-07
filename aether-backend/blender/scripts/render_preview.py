"""Preview camera and still render (fast validation output, DPR §15)."""
from __future__ import annotations

import os

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

from _common import configure_engine, set_output

PROFILES = {
    "preview": {"engine": "BLENDER_EEVEE", "samples": 16, "size": (960, 540)},
    "standard": {"engine": "BLENDER_EEVEE", "samples": 64, "size": (1920, 1080)},
    "hero_still": {"engine": "CYCLES", "samples": 256, "size": (1920, 1080)},
}


def look_at(obj, target) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_camera(manifest: dict):
    shot = manifest.get("camera", {}).get("preview_shot")
    cam_data = bpy.data.cameras.new("PreviewCamera")
    cam_data.lens = 30.0
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 0.05
    cam = bpy.data.objects.new("PreviewCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    if shot:
        cam.location = Vector(shot["position"])
        look_at(cam, shot["look_at"])
    else:
        cam.location = Vector((2.5, -6.0, 1.6))
        look_at(cam, (2.5, 0.0, 1.2))
    bpy.context.scene.camera = cam
    return cam


def render_still(manifest: dict, camera, out_path: str, profile: str = "preview") -> str:
    prof = PROFILES.get(profile, PROFILES["preview"])
    scene = bpy.context.scene
    scene.camera = camera
    configure_engine(scene, prof["engine"], prof["samples"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    set_output(scene, out_path, *prof["size"])
    bpy.ops.render.render(write_still=True)
    return out_path if os.path.exists(out_path) else ""

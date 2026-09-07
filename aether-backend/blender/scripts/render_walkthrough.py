"""Render the guided-tour camera path as an H.264 walkthrough film.

    blender -b scene.blend --factory-startup --python-exit-code 1 \
        --python render_walkthrough.py -- --path film_path.json --out walkthrough.mp4 --profile preview

film_path.json: {"keyframes": [{"position": [x,y,z], "look_at": [x,y,z], "duration": s}, ...]}
in Blender coordinates. The camera is keyframed on location and rotation
with auto-clamped Bezier easing, so the film follows exactly the route the
web viewer's guided tour plays. Encoding goes through Blender's bundled
FFmpeg; no external binary is needed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore
from mathutils import Euler, Vector  # type: ignore

from _common import Timer, configure_engine, emit_result, fail, parse

PROFILES = {
    "preview": {"fps": 12, "size": (960, 540), "samples": 16, "crf": "MEDIUM"},
    "standard": {"fps": 24, "size": (1920, 1080), "samples": 64, "crf": "HIGH"},
    "test": {"fps": 6, "size": (320, 180), "samples": 4, "crf": "LOW"},
}


def _look_rotation(position: Vector, target: Vector, previous: Euler | None) -> Euler:
    direction = target - position
    if direction.length < 1e-6:
        direction = Vector((0.0, 1.0, 0.0))
    rot = direction.to_track_quat("-Z", "Y").to_euler()
    if previous is not None:
        # keep yaw continuous so the interpolation never spins the long way round
        for i in range(3):
            while rot[i] - previous[i] > math.pi:
                rot[i] -= 2 * math.pi
            while rot[i] - previous[i] < -math.pi:
                rot[i] += 2 * math.pi
    return rot


def _enable_video_output(scene) -> bool:
    """Switch the output to Blender's FFmpeg encoder. Blender 5 gates it behind
    image_settings.media_type; older builds expose FFMPEG directly."""
    settings = scene.render.image_settings
    try:
        if hasattr(settings, "media_type"):
            settings.media_type = "VIDEO"
        settings.file_format = "FFMPEG"
        return True
    except TypeError:
        return False


def _fcurves(obj):
    """F-curves of an object's action across the legacy (4.x) and layered (5.x) APIs."""
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return []
    action = ad.action
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    curves = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                curves.extend(bag.fcurves)
    return curves


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", default="preview")
    parser.add_argument("--poster", default="")
    ns = parse(parser)
    with open(ns.path, "r", encoding="utf-8") as fh:
        keyframes = json.load(fh)["keyframes"]
    if not keyframes:
        fail("no keyframes")
    prof = PROFILES.get(ns.profile, PROFILES["preview"])
    fps = prof["fps"]

    scene = bpy.context.scene
    device = configure_engine(scene, "BLENDER_EEVEE", prof["samples"])
    scene.render.fps = fps
    scene.render.resolution_x, scene.render.resolution_y = prof["size"]
    scene.render.resolution_percentage = 100

    cam_data = bpy.data.cameras.new("FilmCamera")
    cam_data.lens = 22.0
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 0.05
    cam = bpy.data.objects.new("FilmCamera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.rotation_mode = "XYZ"

    frame = 1
    previous: Euler | None = None
    for i, kf in enumerate(keyframes):
        if i > 0:
            frame += max(1, int(round(float(kf.get("duration", 2.0)) * fps)))
        pos = Vector(kf["position"])
        rot = _look_rotation(pos, Vector(kf["look_at"]), previous)
        previous = rot
        cam.location = pos
        cam.rotation_euler = rot
        cam.keyframe_insert(data_path="location", frame=frame)
        cam.keyframe_insert(data_path="rotation_euler", frame=frame)
    scene.frame_start = 1
    scene.frame_end = frame
    for fc in _fcurves(cam):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"

    os.makedirs(os.path.dirname(ns.out), exist_ok=True)
    timer = Timer()
    encoder = "blender"
    if _enable_video_output(scene):
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = prof["crf"]
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
        scene.render.ffmpeg.gopsize = fps * 2
        scene.render.filepath = ns.out
        scene.render.use_file_extension = False
        bpy.ops.render.render(animation=True)
    else:
        # PNG sequence + system ffmpeg (installed on the render machine)
        encoder = "ffmpeg"
        frames_dir = ns.out + "_frames"
        os.makedirs(frames_dir, exist_ok=True)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = os.path.join(frames_dir, "f_")
        scene.render.use_file_extension = True
        bpy.ops.render.render(animation=True)
        import shutil
        import subprocess

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            fail("this Blender build has no video output and ffmpeg is not on PATH")
        cmd = [
            ffmpeg, "-y", "-framerate", str(fps), "-i", os.path.join(frames_dir, "f_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", ns.out,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            fail(f"ffmpeg failed: {proc.stderr[-400:]}")
        shutil.rmtree(frames_dir, ignore_errors=True)
    if not os.path.exists(ns.out):
        fail(f"film not written at {ns.out}")

    poster = ""
    if ns.poster:
        scene.frame_set(min(scene.frame_end, fps * 2))
        if hasattr(scene.render.image_settings, "media_type"):
            scene.render.image_settings.media_type = "IMAGE"
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = ns.poster
        scene.render.use_file_extension = False
        bpy.ops.render.render(write_still=True)
        poster = ns.poster if os.path.exists(ns.poster) else ""

    emit_result(
        {
            "ok": True,
            "out": ns.out,
            "poster": poster,
            "profile": ns.profile,
            "device": device,
            "encoder": encoder,
            "fps": fps,
            "frames": scene.frame_end,
            "seconds_of_film": round(scene.frame_end / fps, 1),
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

"""Ask Blender which objects a camera can actually see, and from how many views.

Why this exists: the first verification loop asked a vision model to name what
it saw in a render, and the same built scene scored 0.556, 0.778, 0.556, 0.556
across four reads - a 22 point spread, wider than any improvement worth
chasing - while inventing a dining table in all four views of a living room
that has none. A generative reader cannot be the judge of the pipeline that
feeds it.

This answers the same question deterministically. For each object and each
camera it casts rays from the camera at sample points on the object's bounding
box and counts a sample as reached when nothing intercepts it first. That
separates the three failures the loop must tell apart, which a model naming
furniture cannot:

  never in frame   no sample projects inside any camera's view
  occluded         samples project inside the view but every ray hits
                   something else first - behind the sofa, or inside a wall
  visible          at least one sample is reached

Same answer every run, no network, no credits.

    blender -b scene.blend --python check_visibility.py -- --spec views.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore
from bpy_extras.object_utils import world_to_camera_view  # type: ignore
from mathutils import Vector  # type: ignore

from _common import Timer, emit_result, fail, parse
from render_preview import look_at


def _sample_points(obj) -> list:
    """The eight bounding-box corners plus the centre: enough to catch a piece
    peeking past a sofa, cheap enough to run on every attempt."""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    centre = sum(corners, Vector((0.0, 0.0, 0.0))) / 8.0
    return corners + [centre]


def _root_of(obj):
    holder = obj
    while holder.parent is not None:
        holder = holder.parent
    return holder


def _furniture() -> list:
    """The room's contents, not the room. A wall is never "missing" in the
    sense this measures, and counting it would flatter every score."""
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        names = f"{obj.name} {_root_of(obj).name}".lower()
        # The room and its surroundings are not its contents. The exterior
        # ground plane in particular sits outside the building and can never be
        # reached by a camera standing inside it, so counting it scored a
        # correct scene at 14/15 for a piece of scenery.
        if any(w in names for w in ("wall", "floor", "ceiling", "room", "opening",
                                    "window", "door", "ground", "exterior", "sky", "sun")):
            continue
        out.append(obj)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    args = parse(ap)

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    views = spec.get("views") or []
    if not views:
        fail("no views given")

    timer = Timer()
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    cam_data = bpy.data.cameras.new("VisibilityCamera")
    cam_data.lens = 24.0
    cam_data.sensor_width = 36.0
    cam = bpy.data.objects.new("VisibilityCamera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    objects = _furniture()
    report: dict[str, dict] = {}
    for obj in objects:
        name = _root_of(obj).name
        report.setdefault(name, {"name": name, "in_frame": 0, "visible": 0, "views": []})

    for view in views:
        cam.location = Vector(tuple(view["position"]))
        look_at(cam, tuple(view["look_at"]))
        bpy.context.view_layer.update()
        origin = cam.matrix_world.translation

        for obj in objects:
            name = _root_of(obj).name
            entry = report[name]
            in_frame = reached = False
            for point in _sample_points(obj):
                ndc = world_to_camera_view(scene, cam, point)
                if not (0.0 <= ndc.x <= 1.0 and 0.0 <= ndc.y <= 1.0 and ndc.z > 0):
                    continue
                in_frame = True
                direction = point - origin
                distance = direction.length
                if distance < 1e-6:
                    continue
                hit, _, _, _, hit_obj, _ = scene.ray_cast(
                    depsgraph, origin, direction.normalized(), distance=distance + 0.02)
                # Reached if nothing intercepts it, or the thing hit is this
                # same piece - the ray landing on its own front face.
                if not hit or (hit_obj is not None and _root_of(hit_obj).name == name):
                    reached = True
                    break
            if in_frame:
                entry["in_frame"] += 1
            if reached and view["name"] not in entry["views"]:
                entry["visible"] += 1
                entry["views"].append(view["name"])

    emit_result({
        "ok": True,
        "objects": len(report),
        "visible": len([r for r in report.values() if r["visible"] > 0]),
        "occluded": [r["name"] for r in report.values() if r["visible"] == 0 and r["in_frame"] > 0],
        "never_in_frame": [r["name"] for r in report.values() if r["in_frame"] == 0],
        "detail": list(report.values()),
        "seconds": round(timer.seconds, 2),
    })


if __name__ == "__main__":
    main()

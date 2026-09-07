"""Scene validation inside Blender → validation_report.json (DPR §11, §14).

Checks: every manifest object exists with geometry; imported bounding boxes
agree with the manifest size (±25 %); objects sit inside their room; no
image texture is missing on disk; every room has a floor, a ceiling and a
light.
"""
from __future__ import annotations

import os

import bpy  # type: ignore

TOL = 0.25


def _inside(point, boundary) -> bool:
    x, y = point[0], point[1]
    inside = False
    n = len(boundary)
    for i in range(n):
        x1, y1 = boundary[i]
        x2, y2 = boundary[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def validate(manifest: dict, placed: list[dict], warnings: list[str]) -> dict:
    errors: list[str] = []
    notes: list[str] = list(warnings)
    rooms = {r["id"]: r for r in manifest["rooms"]}

    for p in placed:
        if p["parts"] == 0:
            errors.append(f"{p['id']} ({p['semantic_type']}): no geometry")
            continue
        size = [p["bbox_max"][i] - p["bbox_min"][i] for i in range(3)]
        exp = p["expected"]
        for axis, label in enumerate("xyz"):
            if exp[axis] <= 0:
                continue
            ratio = size[axis] / exp[axis] if exp[axis] else 1.0
            # yaw makes x/y swap for rotated objects: compare the footprint pair loosely
            if axis < 2:
                alt = size[1 - axis] / exp[axis]
                ok = abs(ratio - 1) <= TOL or abs(alt - 1) <= TOL
            else:
                ok = abs(ratio - 1) <= TOL
            if not ok and p["kind"] == "glb":
                notes.append(f"{p['id']} ({p['semantic_type']}): {label} size {size[axis]:.2f} vs expected {exp[axis]:.2f}")
        room = rooms.get(p["room_id"])
        if room and not _inside(p["location"], room["boundary"]):
            errors.append(f"{p['id']} ({p['semantic_type']}): pivot outside room {p['room_id']}")

    for img in bpy.data.images:
        if img.filepath and not img.packed_file:
            path = bpy.path.abspath(img.filepath)
            if not os.path.exists(path):
                errors.append(f"missing texture file: {img.name} ({path})")

    roles = {}
    for obj in bpy.data.objects:
        role = obj.get("aether_role")
        if role in ("floor", "ceiling"):
            roles.setdefault(obj.get("aether_room"), set()).add(role)
    lit = {obj.get("aether_room") for obj in bpy.data.objects if obj.type == "LIGHT"}
    for rid in rooms:
        have = roles.get(rid, set())
        if "floor" not in have:
            errors.append(f"room {rid}: no floor mesh")
        if "ceiling" not in have:
            errors.append(f"room {rid}: no ceiling mesh")
        if rid not in lit:
            notes.append(f"room {rid}: no interior light")

    expected_objects = len(manifest["objects"])
    if len(placed) != expected_objects:
        errors.append(f"placed {len(placed)} of {expected_objects} objects")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": notes,
        "counts": {
            "rooms": len(rooms),
            "walls": sum(1 for o in bpy.data.objects if o.get("aether_role") == "wall"),
            "objects": len(placed),
            "glb_objects": sum(1 for p in placed if p["kind"] == "glb"),
            "procedural_objects": sum(1 for p in placed if p["kind"] == "procedural"),
            "lights": sum(1 for o in bpy.data.objects if o.type == "LIGHT"),
            "images": len(bpy.data.images),
            "meshes": len(bpy.data.meshes),
        },
        "objects": placed,
        "blender": bpy.app.version_string,
    }

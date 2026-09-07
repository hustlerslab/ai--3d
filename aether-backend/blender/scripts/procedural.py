"""Parametric stand-ins for objects without a model (DPR §9 "procedural").

Shapes mirror the web viewer's primitives so both renderers agree:
seat, table, box, tall, pendant, panel. All are built from boxes/cylinders
sized to the manifest dimensions (w, d, h) with the origin at the bottom
centre and the front facing +Y (scene −Z).
"""
from __future__ import annotations

import math

import bmesh  # type: ignore
import bpy  # type: ignore

from build_room import make_box, new_mesh_object


def _cylinder(name, radius, height, collection, material, location=(0, 0, 0), segments=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=height)
    for v in bm.verts:
        v.co.z += height / 2
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    if material is not None:
        obj.data.materials.append(material)
    return obj


def _sphere(name, radius, collection, material, location=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=radius)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    if material is not None:
        obj.data.materials.append(material)
    return obj


def _parent_all(parts, empty):
    for p in parts:
        p.parent = empty


def build(shape: str, name: str, dims, collection, material, accent=None):
    """Return an Empty (the object's pivot) with the parts parented to it."""
    w, d, h = dims
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 0.1
    collection.objects.link(empty)
    parts = []
    accent = accent or material

    if shape == "seat":
        seat_h = min(0.45, h * 0.5)
        leg = 0.08
        parts.append(make_box(f"{name}.seat", (w, d, seat_h - leg), collection, material, (0, 0, leg)))
        parts.append(make_box(f"{name}.back", (w, d * 0.25, h - seat_h), collection, material, (0, -d * 0.375, seat_h)))
        if w > 0.9:
            arm_w = min(0.18, w * 0.12)
            for side in (-1, 1):
                parts.append(make_box(f"{name}.arm{side}", (arm_w, d, seat_h + 0.18 - leg), collection, material,
                                      (side * (w / 2 - arm_w / 2), 0, leg)))
        for sx in (-1, 1):
            for sy in (-1, 1):
                parts.append(_cylinder(f"{name}.leg{sx}{sy}", 0.025, leg, collection, accent,
                                       (sx * (w / 2 - 0.08), sy * (d / 2 - 0.08), 0)))
    elif shape == "table":
        top = min(0.05, h * 0.12)
        parts.append(make_box(f"{name}.top", (w, d, top), collection, material, (0, 0, h - top)))
        r = min(0.035, w * 0.04)
        inset = min(0.12, w * 0.1)
        for sx in (-1, 1):
            for sy in (-1, 1):
                parts.append(_cylinder(f"{name}.leg{sx}{sy}", r, h - top, collection, accent,
                                       (sx * (w / 2 - inset), sy * (d / 2 - inset), 0)))
    elif shape == "tall":
        if h > 1.5 and w < 0.7:  # floor lamp / plant
            pole_h = h * 0.72
            parts.append(_cylinder(f"{name}.base", w * 0.45, 0.04, collection, accent))
            parts.append(_cylinder(f"{name}.pole", 0.02, pole_h, collection, accent, (0, 0, 0.04)))
            parts.append(_cylinder(f"{name}.shade", w / 2, h - pole_h - 0.04, collection, material, (0, 0, pole_h + 0.04)))
        elif h > 0.9 and w < 0.8:  # plant
            pot_h = h * 0.3
            parts.append(_cylinder(f"{name}.pot", w * 0.35, pot_h, collection, accent))
            parts.append(_sphere(f"{name}.foliage", w / 2, collection, material, (0, 0, pot_h + (h - pot_h) / 2)))
        else:  # wardrobe / bookshelf
            parts.append(make_box(f"{name}.body", (w, d, h), collection, material))
            n = max(2, int(h / 0.4))
            for i in range(1, n):
                parts.append(make_box(f"{name}.line{i}", (w * 0.96, 0.01, 0.015), collection, accent, (0, d / 2, h * i / n)))
    elif shape == "pendant":
        parts.append(_cylinder(f"{name}.cord", 0.005, h * 0.5, collection, accent, (0, 0, h * 0.5)))
        parts.append(_cylinder(f"{name}.shade", w / 2, h * 0.5, collection, material))
    elif shape == "panel":
        parts.append(make_box(f"{name}.panel", (w, d, h), collection, material))
        parts.append(make_box(f"{name}.frame", (w + 0.04, d * 0.6, h + 0.04), collection, accent, (0, -d * 0.2, -0.02)))
    else:  # box: beds, tv units, bedside tables, rugs, generic
        if h < 0.06:  # rug
            parts.append(make_box(f"{name}.rug", (w, d, h), collection, material))
        elif w > 1.2 and d > 1.6 and h < 0.7:  # bed
            frame_h = min(0.25, h * 0.45)
            parts.append(make_box(f"{name}.frame", (w, d, frame_h), collection, accent))
            parts.append(make_box(f"{name}.mattress", (w * 0.96, d * 0.92, h - frame_h), collection, material, (0, d * 0.02, frame_h)))
            parts.append(make_box(f"{name}.head", (w, 0.08, h + 0.45), collection, accent, (0, -d / 2 + 0.04, 0)))
        else:
            parts.append(make_box(f"{name}.body", (w, d, h), collection, material))
    _parent_all(parts, empty)
    return empty

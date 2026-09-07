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


def build(shape: str, name: str, dims, collection, material, accent=None, library=None):
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
    elif shape == "fridge":
        steel = library.color("#B8BCC0", roughness=0.35, metallic=0.85) if library else material
        dark = library.color("#2A2C2E", roughness=0.5) if library else accent
        parts.append(make_box(f"{name}.body", (w, d, h), collection, steel))
        parts.append(make_box(f"{name}.split", (w * 0.98, 0.01, 0.012), collection, dark, (0, d / 2, h * 0.68)))
        for z in (h * 0.4, h * 0.8):
            parts.append(make_box(f"{name}.handle{int(z * 100)}", (0.025, 0.03, h * 0.22), collection, dark, (w * 0.32, d / 2 + 0.02, z - h * 0.11)))
    elif shape == "counter":
        # base cabinets + stone worktop + backsplash + upper cabinets, back against the wall (-Y)
        base_h, top_t, gap = 0.86, 0.04, 0.55
        parts.append(make_box(f"{name}.base", (w, d, base_h), collection, material))
        n_doors = max(2, int(w / 0.6))
        for i in range(n_doors):
            x = -w / 2 + (i + 0.5) * (w / n_doors)
            parts.append(make_box(f"{name}.door{i}", (w / n_doors - 0.02, 0.015, base_h - 0.12), collection, accent, (x, d / 2, 0.08)))
            parts.append(make_box(f"{name}.handle{i}", (0.12, 0.02, 0.02), collection, library.frame() if library else accent, (x, d / 2 + 0.02, base_h * 0.55)))
        stone = library.color("#DDD8CF", roughness=0.25) if library else material
        parts.append(make_box(f"{name}.top", (w + 0.02, d + 0.02, top_t), collection, stone, (0, 0.01, base_h)))
        parts.append(make_box(f"{name}.splash", (w, 0.02, gap), collection, stone, (0, -d / 2 + 0.01, base_h + top_t)))
        dark = library.color("#1E1F21", roughness=0.3, metallic=0.4) if library else accent
        steel = library.color("#C2C6C9", roughness=0.3, metallic=0.9) if library else accent
        parts.append(make_box(f"{name}.hob", (0.58, 0.5, 0.012), collection, dark, (-w * 0.25, 0.0, base_h + top_t)))
        for i, (hx, hy) in enumerate(((-0.14, -0.12), (0.14, -0.12), (-0.14, 0.12), (0.14, 0.12))):
            parts.append(_cylinder(f"{name}.burner{i}", 0.07, 0.01, collection, steel, (-w * 0.25 + hx, hy, base_h + top_t + 0.012), segments=16))
        parts.append(make_box(f"{name}.sink", (0.5, 0.42, 0.015), collection, steel, (w * 0.25, 0.0, base_h + top_t)))
        parts.append(_cylinder(f"{name}.tap", 0.012, 0.28, collection, steel, (w * 0.25, -0.16, base_h + top_t)))
        upper_h = max(0.5, h - base_h - top_t - gap)
        parts.append(make_box(f"{name}.upper", (w, d * 0.55, upper_h), collection, material, (0, -d / 2 + d * 0.275, base_h + top_t + gap)))
        for i in range(n_doors):
            x = -w / 2 + (i + 0.5) * (w / n_doors)
            parts.append(make_box(f"{name}.udoor{i}", (w / n_doors - 0.02, 0.015, upper_h - 0.04), collection, accent, (x, -d / 2 + d * 0.55, base_h + top_t + gap + 0.02)))
    elif shape == "curtains":
        # two pleated panels on a rod, hanging from near the ceiling
        rod_z = h
        rod = library.frame() if library else accent
        parts.append(_cylinder(f"{name}.rod", 0.015, w + 0.2, collection, rod))
        parts[-1].rotation_euler = (0.0, math.pi / 2, 0.0)
        parts[-1].location = (-(w + 0.2) / 2, 0.0, rod_z - 0.05)
        panel_w = w * 0.32
        for side in (-1, 1):
            x0 = side * (w / 2 - panel_w / 2)
            folds = 6
            for k in range(folds):
                fx = x0 - panel_w / 2 + (k + 0.5) * panel_w / folds
                depth = d * (0.6 if k % 2 == 0 else 1.0)
                parts.append(make_box(f"{name}.fold{side}{k}", (panel_w / folds + 0.005, depth, h - 0.08), collection, material, (fx, 0.0, 0.02)))
    elif shape == "pendant":
        parts.append(_cylinder(f"{name}.cord", 0.005, h * 0.5, collection, accent, (0, 0, h * 0.5)))
        parts.append(_cylinder(f"{name}.shade", w / 2, h * 0.5, collection, material))
    elif shape in ("panel", "photo", "mirror"):
        # a framed face: the front (+Y) carries the image / mirror, a slim frame around it
        fd = max(0.02, min(d, 0.05))
        parts.append(make_box(f"{name}.face", (w - 0.06, fd * 0.6, h - 0.06), collection, material, (0, fd * 0.2, 0.03)))
        frame = library.frame() if library else accent
        for sx in (-1, 1):
            parts.append(make_box(f"{name}.frame{sx}", (0.03, fd, h), collection, frame, (sx * (w / 2 - 0.015), 0, 0)))
        parts.append(make_box(f"{name}.frameB", (w, fd, 0.03), collection, frame, (0, 0, 0)))
        parts.append(make_box(f"{name}.frameT", (w, fd, 0.03), collection, frame, (0, 0, h - 0.03)))
        parts.append(make_box(f"{name}.back", (w, fd * 0.4, h), collection, frame, (0, -fd * 0.3, 0)))
    elif shape == "lamp":
        # table lamp: weighted base, stem, drum shade
        metal = library.color("#B08D57", roughness=0.35, metallic=0.9) if library else accent
        base_h = min(0.06, h * 0.1)
        parts.append(_cylinder(f"{name}.base", w * 0.28, base_h, collection, metal))
        stem_h = h * 0.52
        parts.append(_cylinder(f"{name}.stem", w * 0.09, stem_h, collection, metal, (0, 0, base_h)))
        shade_h = h - base_h - stem_h
        parts.append(_cylinder(f"{name}.shade", w / 2, shade_h, collection, material, (0, 0, base_h + stem_h)))
    elif shape == "sconce":
        metal = library.color("#B08D57", roughness=0.35, metallic=0.9) if library else accent
        parts.append(make_box(f"{name}.plate", (w * 0.4, 0.02, h * 0.5), collection, metal, (0, -d / 2 + 0.01, h * 0.25)))
        parts.append(_cylinder(f"{name}.arm", 0.01, d * 0.7, collection, metal, (0, -d / 2 + 0.02, h * 0.5)))
        parts[-1].rotation_euler = (-math.pi / 2, 0.0, 0.0)
        parts.append(_cylinder(f"{name}.shade", w / 2, h * 0.45, collection, material, (0, d * 0.15, h * 0.5)))
    elif shape == "shelf":
        # a wall bracket: shelf board on a scrolled support
        parts.append(make_box(f"{name}.board", (w, d, 0.03), collection, material, (0, 0, h - 0.03)))
        parts.append(make_box(f"{name}.support", (w * 0.25, d * 0.7, h - 0.03), collection, material, (0, -d * 0.15, 0)))
    elif shape == "fireplace":
        # surround + firebox recess + mantel shelf, back against the wall (-Y)
        stone = library.color("#E9E4DA", roughness=0.6) if library else material
        dark = library.color("#151412", roughness=0.9) if library else accent
        leg_w = w * 0.18
        for sx in (-1, 1):
            parts.append(make_box(f"{name}.leg{sx}", (leg_w, d, h - 0.08), collection, stone, (sx * (w / 2 - leg_w / 2), 0, 0)))
        parts.append(make_box(f"{name}.lintel", (w, d, h * 0.22), collection, stone, (0, 0, h - 0.08 - h * 0.22)))
        parts.append(make_box(f"{name}.mantel", (w + 0.12, d + 0.08, 0.08), collection, stone, (0, 0.04, h - 0.08)))
        parts.append(make_box(f"{name}.firebox", (w - 2 * leg_w, d * 0.5, h - 0.08 - h * 0.22), collection, dark, (0, -d * 0.25, 0)))
        parts.append(make_box(f"{name}.hearth", (w + 0.2, d * 0.6, 0.02), collection, stone, (0, d / 2 + d * 0.3, 0)))
    elif shape == "books":
        # a short stack of books, each a slightly offset slab
        n = max(2, min(5, int(h / 0.035)))
        book_h = h / n
        cols = [material, accent, material, accent, material]
        for i in range(n):
            off = (i % 2) * 0.02 - 0.01
            parts.append(make_box(f"{name}.book{i}", (w * (0.9 + 0.1 * (i % 2)), d, book_h - 0.003), collection, cols[i % len(cols)], (off, 0, i * book_h)))
    elif shape == "vase":
        parts.append(_cylinder(f"{name}.body", w / 2, h * 0.75, collection, material, segments=20))
        parts.append(_cylinder(f"{name}.neck", w * 0.28, h * 0.25, collection, material, (0, 0, h * 0.75), segments=16))
    elif shape == "candle":
        parts.append(_cylinder(f"{name}.holder", w / 2, h * 0.3, collection, accent, segments=16))
        parts.append(_cylinder(f"{name}.wax", w * 0.32, h * 0.7, collection, material, (0, 0, h * 0.3), segments=16))
    elif shape == "tray":
        parts.append(make_box(f"{name}.base", (w, d, max(0.008, h * 0.3)), collection, material))
        for sx in (-1, 1):
            parts.append(make_box(f"{name}.rim{sx}", (0.015, d, h), collection, accent, (sx * (w / 2 - 0.0075), 0, 0)))
        for sy in (-1, 1):
            parts.append(make_box(f"{name}.rimy{sy}", (w, 0.015, h), collection, accent, (0, sy * (d / 2 - 0.0075), 0)))
    elif shape == "pillow":
        # a cushion leaning back: a soft slab tilted against the seat back
        slab = make_box(f"{name}.cushion", (w, d, h), collection, material, (0, 0, 0))
        slab.rotation_euler = (math.radians(-12), 0.0, 0.0)
        parts.append(slab)
    elif shape == "clock":
        parts.append(_cylinder(f"{name}.face", w / 2, d, collection, material, (0, 0, h / 2), segments=32))
        parts[-1].rotation_euler = (math.pi / 2, 0.0, 0.0)
        parts[-1].location = (0, d / 2, h / 2)
    else:  # box / tv: beds, tv units, bedside tables, rugs, generic
        if h < 0.06:  # rug
            parts.append(make_box(f"{name}.rug", (w, d, h), collection, material))
        elif w > 1.2 and d > 1.6 and h < 0.7:  # bed
            frame_h = min(0.25, h * 0.45)
            parts.append(make_box(f"{name}.frame", (w, d, frame_h), collection, accent))
            parts.append(make_box(f"{name}.mattress", (w * 0.96, d * 0.92, h - frame_h), collection, material, (0, d * 0.02, frame_h)))
            parts.append(make_box(f"{name}.head", (w, 0.08, h + 0.45), collection, accent, (0, -d / 2 + 0.04, 0)))
        elif shape == "tv":
            parts.append(make_box(f"{name}.body", (w, d, h), collection, material))
            screen = library.screen() if library else accent
            parts.append(make_box(f"{name}.tv", (min(1.45, w * 0.8), 0.04, min(0.82, w * 0.45)), collection, screen, (0, 0, h + 0.05)))
        else:
            parts.append(make_box(f"{name}.body", (w, d, h), collection, material))
    _parent_all(parts, empty)
    return empty

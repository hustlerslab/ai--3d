"""Architecture: floors, ceilings and walls with openings (no booleans).

A wall is split along its length into full-height pieces, lintels above
doors, and sill/header pieces around windows. Every piece is a box whose
origin sits on the floor at the piece's centre line, so the geometry is
watertight without boolean modifiers.
"""
from __future__ import annotations

import math

import bmesh  # type: ignore
import bpy  # type: ignore
from mathutils import Vector  # type: ignore

SLAB = 0.05


def make_collections(manifest: dict) -> dict:
    scene = bpy.context.scene
    cols: dict[str, bpy.types.Collection] = {}
    for name in ("Architecture", "Furniture", "Lighting", "Cameras"):
        col = bpy.data.collections.new(name)
        scene.collection.children.link(col)
        cols[name] = col
    for room in manifest["rooms"]:
        for parent in ("Architecture", "Furniture"):
            col = bpy.data.collections.new(f"{parent}.{room['id']}")
            cols[parent].children.link(col)
            cols[f"{parent}.{room['id']}"] = col
    return cols


def new_mesh_object(name: str, verts, faces, collection, material=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if material is not None:
        obj.data.materials.append(material)
    return obj


def make_box(name: str, size, collection, material=None, location=(0, 0, 0), rz: float = 0.0):
    """Box with origin at the bottom centre; size = (x, y, z)."""
    sx, sy, sz = size
    hx, hy = sx / 2, sy / 2
    verts = [
        (-hx, -hy, 0), (hx, -hy, 0), (hx, hy, 0), (-hx, hy, 0),
        (-hx, -hy, sz), (hx, -hy, sz), (hx, hy, sz), (-hx, hy, sz),
    ]
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    obj = new_mesh_object(name, verts, faces, collection, material)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, rz)
    return obj


def prism_from_polygon(name: str, boundary, z0: float, z1: float, collection, material=None):
    n = len(boundary)
    verts = [(x, y, z0) for x, y in boundary] + [(x, y, z1) for x, y in boundary]
    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return new_mesh_object(name, verts, faces, collection, material)


def build_rooms(manifest: dict, cols: dict, materials) -> None:
    for room in manifest["rooms"]:
        col = cols[f"Architecture.{room['id']}"]
        floor_mat = materials.get(room["floor_material"], fallback_color="#B9A88F")
        z = room["floor_height"]
        floor = prism_from_polygon(f"floor.{room['id']}", room["boundary"], z - SLAB, z, col, floor_mat)
        floor["aether_role"] = "floor"
        floor["aether_room"] = room["id"]
        ceiling_mat = materials.ceiling()
        zc = z + room["ceiling_height"]
        ceiling = prism_from_polygon(f"ceiling.{room['id']}", room["boundary"], zc, zc + SLAB, col, ceiling_mat)
        ceiling["aether_role"] = "ceiling"
        ceiling["aether_room"] = room["id"]


def build_exterior(manifest: dict, cols: dict, materials) -> None:
    """A large neutral ground plane just below the floors, so doors and windows
    look onto ground rather than the sky's dark lower hemisphere."""
    xs = [p[0] for r in manifest["rooms"] for p in r["boundary"]]
    ys = [p[1] for r in manifest["rooms"] for p in r["boundary"]]
    if not xs:
        return
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys)) + 80.0
    z = min(r["floor_height"] for r in manifest["rooms"]) - SLAB - 0.01
    ground = make_box("exterior.ground", (span, span, 0.02), cols["Architecture"], materials.color("#8E8A7E", roughness=0.95), (cx, cy, z - 0.02))
    ground["aether_role"] = "ground"


def _pieces(length: float, height: float, openings: list[dict]) -> list[tuple[float, float, float, float]]:
    """(a, b, z0, z1) boxes covering the wall minus its openings."""
    pieces = []
    cursor = 0.0
    for o in sorted(openings, key=lambda o: o["position"]):
        a = max(0.0, o["position"] - o["width"] / 2)
        b = min(length, o["position"] + o["width"] / 2)
        if a > cursor:
            pieces.append((cursor, a, 0.0, height))
        if o["type"] == "door":
            top = min(height, o["height"])
            if height - top > 0.01:
                pieces.append((a, b, top, height))
        else:
            sill = o["sill_height"]
            top = min(height, sill + o["height"])
            if sill > 0.01:
                pieces.append((a, b, 0.0, sill))
            if height - top > 0.01:
                pieces.append((a, b, top, height))
        cursor = b
    if length - cursor > 0.01:
        pieces.append((cursor, length, 0.0, height))
    return pieces


def build_walls(manifest: dict, cols: dict, materials, warnings: list[str]) -> None:
    col = cols["Architecture"]
    glass = materials.glass()
    for wall in manifest["walls"]:
        s = Vector((wall["start"][0], wall["start"][1], 0.0))
        e = Vector((wall["end"][0], wall["end"][1], 0.0))
        d = e - s
        length = d.length
        if length < 1e-6:
            warnings.append(f"wall {wall['id']} has zero length")
            continue
        d.normalize()
        rz = math.atan2(d.y, d.x)
        mat = materials.get(wall["material"], fallback_color="#ECE5D8")
        t = wall["thickness"]
        for i, (a, b, z0, z1) in enumerate(_pieces(length, wall["height"], wall.get("openings", []))):
            centre = s + d * ((a + b) / 2)
            piece = make_box(f"{wall['id']}.{i}", (b - a, t, z1 - z0), col, mat, (centre.x, centre.y, z0), rz)
            piece["aether_role"] = "wall"
            piece["aether_wall"] = wall["id"]
        for o in wall.get("openings", []):
            if o["type"] != "window":
                continue
            centre = s + d * o["position"]
            pane = make_box(f"{o['id']}.glass", (o["width"], 0.02, o["height"]), col, glass, (centre.x, centre.y, o["sill_height"]), rz)
            pane["aether_role"] = "window"
            frame_mat = materials.frame()
            for side in (-1, 1):
                fc = s + d * (o["position"] + side * (o["width"] / 2 + 0.03))
                make_box(f"{o['id']}.frame{side}", (0.06, t + 0.02, o["height"]), col, frame_mat, (fc.x, fc.y, o["sill_height"]), rz)

"""Import normalized GLBs or build procedural stand-ins, then place them.

Every scene object becomes an Empty named after the object id, parented
under Furniture.<room>, carrying the manifest's location / rotation / scale.
GLB children keep their own materials; procedural parts use the style
material override (or the object colour).
"""
from __future__ import annotations

import os

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

import procedural

_glb_cache: dict[str, list] = {}


def _import_glb(path: str) -> list:
    """Import once per file, then duplicate (linked mesh data) for reuse."""
    if path in _glb_cache:
        originals = _glb_cache[path]
        copies = []
        for src in originals:
            dup = src.copy()
            dup.parent = None
            copies.append((src, dup))
        # rebuild the hierarchy among the copies
        by_src = {src: dup for src, dup in copies}
        for src, dup in copies:
            if src.parent in by_src:
                dup.parent = by_src[src.parent]
                dup.matrix_parent_inverse = src.matrix_parent_inverse.copy()
        return [dup for _, dup in copies]

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    imported = [o for o in bpy.data.objects if o not in before]
    for o in imported:
        for col in list(o.users_collection):
            col.objects.unlink(o)
    _glb_cache[path] = imported
    return imported


def _world_bbox(objs) -> tuple[Vector, Vector]:
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    found = False
    for o in objs:
        if o.type != "MESH":
            continue
        for corner in o.bound_box:
            p = o.matrix_world @ Vector(corner)
            lo.x, lo.y, lo.z = min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)
            hi.x, hi.y, hi.z = max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)
            found = True
    if not found:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return lo, hi


def build_objects(manifest: dict, cols: dict, materials, warnings: list[str]) -> list[dict]:
    placed: list[dict] = []
    for spec in manifest["objects"]:
        col = cols.get(f"Furniture.{spec['room_id']}", cols["Furniture"])
        asset = spec["asset"]
        name = spec["id"]
        dims = spec["dimensions"]
        override = spec.get("material_overrides", {}).get("primary")

        if asset["kind"] == "glb" and os.path.exists(asset["path"]):
            children = _import_glb(asset["path"])
            root = bpy.data.objects.new(name, None)
            root.empty_display_type = "ARROWS"
            root.empty_display_size = 0.2
            col.objects.link(root)
            for o in children:
                col.objects.link(o)
                if o.parent is None:
                    o.parent = root
            _apply_upholstery(children, spec, materials)
            kind = "glb"
        else:
            if asset["kind"] == "glb":
                warnings.append(f"{name}: model file missing ({asset.get('path')}); using a procedural stand-in")
            mat = materials.for_object(spec)
            accent = materials.accent(spec["color"])
            root = procedural.build(asset.get("shape", "box"), name, dims, col, mat, accent, materials)
            kind = "procedural"

        root.location = spec["location"]
        root.rotation_euler = spec["rotation_rad"]
        root.scale = spec["scale"]
        root["aether_object"] = spec["id"]
        root["aether_type"] = spec["semantic_type"]
        root["aether_room"] = spec["room_id"]
        root["aether_strategy"] = spec["strategy"]
        root["aether_kind"] = kind

        bpy.context.view_layer.update()
        descendants = [o for o in bpy.data.objects if _is_descendant(o, root)]
        lo, hi = _world_bbox(descendants)
        placed.append(
            {
                "id": spec["id"],
                "semantic_type": spec["semantic_type"],
                "room_id": spec["room_id"],
                "kind": kind,
                "location": list(spec["location"]),
                "expected": [dims[0] * spec["scale"][0], dims[1] * spec["scale"][1], dims[2] * spec["scale"][2]],
                "bbox_min": [round(v, 3) for v in lo],
                "bbox_max": [round(v, 3) for v in hi],
                "parts": len(descendants),
            }
        )
    return placed


FABRIC_TYPES = {"sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "bar_stool", "pillows", "rug", "curtains"}


def _apply_upholstery(children, spec: dict, materials) -> None:
    """Moodboard fidelity for real models: the largest mesh of a fabric piece
    (the upholstery) takes the style fabric tinted with the planned colour,
    so a black leather catalogue sofa becomes the client's linen sofa."""
    if spec.get("semantic_type") not in FABRIC_TYPES:
        return
    override = (spec.get("material_overrides") or {}).get("primary")
    if not override:
        return
    meshes = [o for o in children if o.type == "MESH" and o.data and len(o.data.polygons) > 0]
    if not meshes:
        return

    def area(o):
        return sum(p.area for p in o.data.polygons) * (o.matrix_world.to_scale().x ** 2)

    meshes.sort(key=area, reverse=True)
    total = sum(area(m) for m in meshes) or 1.0
    mat = materials.get(override, tint=spec.get("color"), tint_strength=0.85)
    for m in meshes:
        if area(m) / total < 0.12 and m is not meshes[0]:
            break  # legs, feet and trims keep their own look
        m.data = m.data.copy()
        m.data.materials.clear()
        m.data.materials.append(mat)


def _is_descendant(obj, root) -> bool:
    p = obj.parent
    while p is not None:
        if p == root:
            return True
        p = p.parent
    return False

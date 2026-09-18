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


#: Types whose facing is readable from their own geometry, and how.
#: "backrest": the tall mass sits BEHIND the seat, so forward points away from
#: it - true of every chair, sofa and bench regardless of style.
#: "thin": a flat piece faces along its thinnest horizontal axis - a screen, a
#: picture, a mirror. Which of the two directions is settled by the planner's
#: own yaw, so only the axis is taken from the mesh.
_FACING_RULE: dict[str, str] = {
    "armchair": "backrest", "chair": "backrest", "dining_chair": "backrest",
    "sofa": "backrest", "sectional": "backrest", "loveseat": "backrest",
    "bench": "backrest", "stool": "backrest", "bar_stool": "backrest",
    "rocking_chair": "backrest", "office_chair": "backrest", "accent_chair": "backrest",
    "tv": "thin", "television": "thin", "tv_unit": "thin", "wall_art": "thin",
    "mirror": "thin", "artwork": "thin",
}

#: A backrest has to be a real mass to count. Below this share of the vertices
#: sitting high, the "tall part" is a cushion or an armrest and the direction
#: it implies is noise - so nothing is corrected and the model is left alone.
_BACKREST_MIN_SHARE = 0.12
#: And it has to be off-centre: a symmetric piece gives a near-zero offset
#: whose direction is meaningless.
_BACKREST_MIN_OFFSET = 0.06


def _native_forward_yaw(children, semantic_type: str) -> float:
    """The yaw, in radians, that this mesh is ALREADY turned by.

    Returned so the caller can subtract it before applying the planner's yaw.
    Zero means "leave it alone", which is the answer for anything this cannot
    read confidently: a wrong correction is worse than none, because the
    planner's own angle is at least consistent.

    Snapped to quarter turns on purpose. Furniture in rooms is axis-aligned,
    the four-way choice is the whole question, and a continuous angle read off
    a vertex cloud would wobble between builds of the same scene.
    """
    rule = _FACING_RULE.get(semantic_type)
    if not rule:
        return 0.0
    import math

    points = []
    for obj in children:
        if obj.type != "MESH":
            continue
        for vert in obj.data.vertices:
            points.append(obj.matrix_world @ vert.co)
    if len(points) < 24:
        return 0.0

    lo = Vector((min(p[i] for p in points) for i in range(3)))
    hi = Vector((max(p[i] for p in points) for i in range(3)))
    size = hi - lo
    centre = (lo + hi) / 2.0
    if size.x < 1e-4 or size.y < 1e-4:
        return 0.0

    if rule == "thin":
        # Faces along the thinner horizontal axis; the planner's yaw decides
        # which way along it, so only the axis matters here.
        return 0.0 if size.y <= size.x else math.pi / 2

    # Weighted by the AREA each face contributes, not by how many vertices it
    # happens to carry. Raw vertex averaging is density-biased, and furniture is
    # exactly where that bites: a tufted cushion or a carved arm holds more
    # vertices than the flat panel behind it, pulling the "back" centroid
    # forwards and inverting the answer. Area is what a backrest actually is.
    high_pts: list = []
    high_w: list[float] = []
    cut = lo.z + size.z * 0.55
    faces = 0
    for obj in children:
        if obj.type != "MESH":
            continue
        mw = obj.matrix_world
        for poly in obj.data.polygons:
            faces += 1
            c = mw @ poly.center
            if c.z > cut:
                high_pts.append(c)
                high_w.append(max(poly.area, 1e-9))
    if not faces:
        return 0.0
    if not high_pts or sum(high_w) <= 0 or len(high_pts) < faces * _BACKREST_MIN_SHARE:
        return 0.0
    total = sum(high_w)
    back = Vector((sum(p.x * w for p, w in zip(high_pts, high_w)) / total,
                   sum(p.y * w for p, w in zip(high_pts, high_w)) / total, 0.0))
    offset = Vector((back.x - centre.x, back.y - centre.y, 0.0))
    # Normalised against the piece's own size, so a wide sofa and a small chair
    # are judged the same way.
    if abs(offset.x) / size.x < _BACKREST_MIN_OFFSET and abs(offset.y) / size.y < _BACKREST_MIN_OFFSET:
        return 0.0
    # Forward is away from the backrest. Blender's -Y is the scene's "into the
    # room" at yaw 0, matching the manifest's own convention.
    forward = -offset
    return round(math.atan2(forward.x, -forward.y) / (math.pi / 2)) * (math.pi / 2)


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
            _apply_frame_finish(children, spec, materials)
            kind = "glb"
        else:
            if asset["kind"] == "glb":
                warnings.append(f"{name}: model file missing ({asset.get('path')}); using a procedural stand-in")
            shape = asset.get("shape", "box")
            texture = asset.get("texture")
            if texture:
                mat = materials.image(texture, plane="xy" if dims[2] < 0.08 else "xz", fallback=spec["color"])
            elif spec.get("semantic_type") == "mirror" or shape == "mirror":
                mat = materials.mirror()
            else:
                mat = materials.for_object(spec)
            accent = materials.accent(spec["color"]) if not texture else materials.frame()
            root = procedural.build(shape, name, dims, col, mat, accent, materials)
            kind = "procedural"

        root.location = spec["location"]
        rot = list(spec["rotation_rad"])
        if kind == "glb":
            # Correct for the model's OWN facing before applying the planner's.
            # Nothing upstream knows which way a mesh faces: the registry has no
            # forward axis at all, and a generated mesh arrives in whatever
            # orientation the vendor produced. Without this, the yaw the solver
            # worked out is applied on top of an unknown starting angle - which
            # is why armchairs ended up facing the wall.
            native = _native_forward_yaw(children, spec.get("semantic_type", ""))
            if native:
                rot[2] -= native
                root["aether_forward_correction"] = round(native, 4)
        root.rotation_euler = rot
        root.scale = spec["scale"]
        root["aether_object"] = spec["id"]
        root["aether_type"] = spec["semantic_type"]
        root["aether_room"] = spec["room_id"]
        root["aether_strategy"] = spec["strategy"]
        root["aether_kind"] = kind
        root["aether_mount"] = spec.get("mount", "floor")
        if spec.get("parent"):
            root["aether_parent"] = spec["parent"]

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


def _apply_frame_finish(children, spec: dict, materials) -> None:
    """P14: paint the client's stated frame/leg finish onto the TRIM meshes.

    The counterpart of `_apply_upholstery`, and deliberately its mirror image:
    that function re-skins the meshes at or above 12% of the piece's area and
    leaves the rest alone because "legs, feet and trims keep their own look".
    Those skipped small meshes are exactly what a frame finish describes, so
    this paints them and never touches the body.

    It runs only when the manifest already decided `state == "rendered"` -
    which required the finish to resolve to a real registry material AND the
    asset to have more than one material region (48 of 58 assets have one, and
    for those the manifest says `metadata_only` and this does nothing).

    ISOLATION: `m.data.copy()` before any material assignment, exactly as
    `_apply_upholstery` does. Blender shares mesh data between linked duplicates
    and shares material datablocks by name, so assigning in place would repaint
    every other object using that mesh - and `materials.get()` returns a cached
    material per (id, tint, strength), which must never be mutated here.
    """
    finish = spec.get("finish") or {}
    if finish.get("state") != "rendered":
        return
    material_id = finish.get("frame_material")
    if not material_id:
        return

    meshes = [o for o in children if o.type == "MESH" and o.data and len(o.data.polygons) > 0]
    if len(meshes) < 2:
        return  # nothing separable: the whole piece is one skin

    def area(o):
        return sum(p.area for p in o.data.polygons) * (o.matrix_world.to_scale().x ** 2)

    meshes.sort(key=area, reverse=True)
    total = sum(area(m) for m in meshes) or 1.0
    trim = [m for m in meshes[1:] if area(m) / total < 0.12]
    if not trim:
        return

    mat = materials.get(material_id)
    for m in trim:
        m.data = m.data.copy()          # never mutate shared mesh data
        m.data.materials.clear()
        m.data.materials.append(mat)


def _apply_upholstery(children, spec: dict, materials) -> None:
    """Moodboard fidelity for real models: the largest mesh of a fabric piece
    (the upholstery) takes the style fabric tinted with the planned colour,
    so a black leather catalogue sofa becomes the client's linen sofa."""
    if spec.get("semantic_type") not in FABRIC_TYPES:
        return
    if (spec.get("asset") or {}).get("own_materials"):
        # Generated from this client's own approved render: the texture on the
        # mesh IS their fabric. Re-skinning it with the style material would
        # discard exactly what the generation bought.
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

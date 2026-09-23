"""Scene compiler (plan §9 / DPR §7 "SCENE COMPILER").

compile_scene()  DesignAnalysis + StyleSpec → Scene with rooms, walls, openings,
                 style, lighting and an empty camera plan (no objects yet).
place_objects()  ObjectPlan + AssetPlan → AddObjectOps, placed with the
                 existing spatial candidates and validated per object, so the
                 result commits through the normal patch pipeline.

Surfaces (spec 1.1): besides the floor, objects can hang on a wall at a
sensible height (art over the sofa, never over a window) or rest on the top
of another object (a lamp on a bedside table, a tray on the coffee table).
"""
from __future__ import annotations

import math
from typing import Optional

from ..design.service import _wall_aligned_candidates
from ..intelligence import vocab
from ..intelligence.schema import AssetPlan, DesignAnalysis, ObjectPlan, ObjectPlanItem, StyleSpec
from ..materials.registry import get_material_registry
from ..scene.patches import AddObjectOp
from ..scene.schema import (
    CameraPlan,
    Confidence,
    InteriorLight,
    LightingSpec,
    ObjectSource,
    ObjectVisual,
    Room,
    Scene,
    SceneObject,
    SceneStyle,
    Vec3,
    Wall,
    WallFinishZone,
)
from ..spatial import geometry as geo
from ..spatial.validation import object_footprint, validate_object
from .layout import build_walls_and_openings, layout_rooms, wall_segments

Vec2 = tuple[float, float]
Candidate = tuple[Vec2, float, Optional[float]]   # (x, z), yaw, y (None = from mount)

LIGHTING_PRESETS: dict[str, dict] = {
    "warm_daylight": {"sun_azimuth_deg": 135.0, "sun_elevation_deg": 40.0, "sun_strength": 3.0, "sky_turbidity": 2.5, "exposure_ev": 0.0, "color_temp_k": 3200},
    "cool_daylight": {"sun_azimuth_deg": 200.0, "sun_elevation_deg": 55.0, "sun_strength": 4.0, "sky_turbidity": 1.8, "exposure_ev": -0.2, "color_temp_k": 4500},
    "evening": {"sun_azimuth_deg": 260.0, "sun_elevation_deg": 8.0, "sun_strength": 1.2, "sky_turbidity": 4.0, "exposure_ev": 0.4, "color_temp_k": 2700},
    "studio": {"sun_azimuth_deg": 150.0, "sun_elevation_deg": 65.0, "sun_strength": 2.0, "sky_turbidity": 1.5, "exposure_ev": 0.0, "color_temp_k": 4000},
}

SPEC_VERSION = "1.1"


# ── rooms, walls, style, lighting ────────────────────────────────────────


# What the reader writes is free text off a picture ("wood paneling and
# wallpaper", "plaster and dark wood panelling"), and the scene needs a
# registry id. Keyword -> id, most specific first, so "dark wood" beats "wood".
# Unmatched text falls through to the style's own choice rather than guessing:
# a wrong floor everywhere is more noticeable than a default one.
_SURFACE_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("herringbone",), "wood_oak_herringbone"),
    (("walnut",), "wood_walnut"),
    (("dark wood", "dark timber", "espresso", "wenge"), "wood_dark"),
    (("oak", "light wood", "timber", "wood", "parquet", "laminate"), "wood_oak"),
    (("marble",), "marble"),
    (("terrazzo",), "terrazzo"),
    (("granite", "stone"), "stone_granite"),
    (("tile", "ceramic", "porcelain"), "tile_ivory"),
    (("lime", "limewash"), "plaster_lime"),
    (("wallpaper", "patterned", "textured"), "plaster_patterned"),
    (("sage", "green"), "paint_sage"),
    (("terracotta", "rust", "clay"), "paint_terracotta"),
    (("ivory", "cream", "beige"), "paint_ivory"),
    (("plaster", "paint", "white", "painted"), "paint_white"),
]


# The same mechanism as `_SURFACE_WORDS`, for the FRAME/LEG finish of a piece
# of furniture rather than a room surface. Every id here already exists in the
# registry and is `applies_to: furniture` - P14 invents no material to make a
# benchmark pass, and a word that routes to nothing renders nothing.
# Most specific first, so "dark walnut" beats "walnut" beats "wood".
_FINISH_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("walnut",), "veneer_walnut"),
    (("oak", "ash", "birch", "light wood", "timber", "wood", "wooden"), "veneer_oak"),
    (("brass", "bronze", "gold", "copper"), "metal_brass"),
    (("black metal", "matte black", "blackened", "gunmetal", "steel", "chrome",
      "metal", "iron"), "metal_black"),
    (("glass",), "glass_clear"),
]


def finish_material_for(text: str) -> str:
    """Registry material for a described frame/leg finish, or "" for nothing.

    Empty is a real answer and the common one: a finish the registry cannot
    represent stays metadata, because painting a sofa's legs the wrong species
    is worse than leaving the catalogue's own look alone.
    """
    low = (text or "").lower()
    if not low.strip():
        return ""
    registry = get_material_registry()
    for words, mid in _FINISH_WORDS:
        if not any(w in low for w in words):
            continue
        rec = registry.get(mid)
        if rec is not None and "furniture" in rec.applies_to:
            return mid
    return ""


def material_for(text: str, applies_to: str) -> str:
    """Registry id for a described surface, or "" when nothing matches.

    Empty is a real answer: the caller keeps the style's material, which is at
    least coherent. Guessing would put an invented floor in every room.
    """
    low = (text or "").lower()
    if not low.strip():
        return ""
    registry = get_material_registry()
    for words, mid in _SURFACE_WORDS:
        if not any(w in low for w in words):
            continue
        rec = registry.get(mid)
        if rec is not None and applies_to in rec.applies_to:
            return mid
    return ""


def room_surface_materials(reading) -> dict[str, tuple[str, str]]:
    """room_id -> (floor material id, wall material id), "" where unknown."""
    out: dict[str, tuple[str, str]] = {}
    for s in getattr(reading, "surfaces", []) or []:
        out[s.room_id] = (material_for(s.floor_material, "floor"),
                          material_for(s.wall_material, "wall"))
    return out


def _floor_and_wall_materials(style: StyleSpec) -> tuple[str, str, str]:
    """(default floor, wet-room floor, wall) material ids from the style list."""
    registry = get_material_registry()
    floor = wet = wall = ""
    for mid in style.materials:
        rec = registry.get(mid)
        if rec is None:
            continue
        if "floor" in rec.applies_to and rec.category in ("wood",) and not floor:
            floor = mid
        if "floor" in rec.applies_to and rec.category in ("tile", "stone", "marble") and not wet:
            wet = mid
        if "wall" in rec.applies_to and rec.category in ("plaster", "paint") and not wall:
            wall = mid
    floor = floor or wet or "wood_oak"
    wet = wet or floor
    wall = wall or "paint_white"
    return floor, wet, wall


def _is_named_edge(seg, room, wall_name: str) -> bool:
    """Whether a wall segment lies on the room's named edge, in the render
    frame the reading uses: back = north (min z), front = south (max z),
    left = west (min x), right = east (max x)."""
    axis, c = {"back": ("x", room.z0), "front": ("x", room.z1),
               "left": ("z", room.x0), "right": ("z", room.x1)}.get(wall_name, (None, None))
    return axis is not None and seg.axis == axis and abs(seg.c - c) < 0.01


def bind_wall_finishes(walls: list[Wall], segs, placed, reading) -> int:
    """P22: attach the reading's per-wall finish zones to the wall segments
    that room's named edge became. Additive: `Wall.material` stays the
    room-wide answer, the zones ride alongside for the executor. A segment
    shared by two rooms carries both rooms' zones, each tagged with its
    room, because the slab has two faces even if Blender paints one."""
    by_room = {s.room_id: s.walls for s in (getattr(reading, "surfaces", None) or []) if s.walls}
    if not by_room:
        return 0
    seg_by_id = {seg.wall_id: seg for seg in segs}
    bound = 0
    for room in placed:
        for fin in by_room.get(room.room_id, []):
            for w in walls:
                seg = seg_by_id.get(w.wall_id)
                if seg is None or room.room_id not in seg.rooms or not _is_named_edge(seg, room, fin.wall):
                    continue
                w.finishes.append(WallFinishZone(
                    room_id=room.room_id, wall_name=fin.wall,
                    material=material_for(fin.material, "wall") or w.material,
                    material_text=fin.material, color=fin.color, pattern=fin.pattern,
                    extent=fin.extent_m))
                bound += 1
    return bound


def reserved_wall_spans(placed, reading) -> dict[str, list[tuple[float, float]]]:
    """Where the approved picture already put something on a wall.

    Returned as wall_id -> spans in metres from that wall segment's start, the
    same coordinate `build_walls_and_openings` cuts openings in, so a window
    is simply never offered that span. Only pieces the reader MEASURED against
    a named wall count: a guess is not grounds for moving a window.
    """
    out: dict[str, list[tuple[float, float]]] = {}
    if reading is None:
        return out
    segs = wall_segments(placed)
    by_room = {p.room_id: p for p in placed}
    for el in getattr(reading, "elements", []) or []:
        if el.placement != "wall" or not el.wall or el.position_source != "read":
            continue
        if el.position_m is None:
            continue
        room = by_room.get(el.room_id)
        if room is None:
            continue
        # How wide the piece is along this wall. The reading rarely carries
        # metric dimensions - they are settled later, from the asset - but the
        # crop box does, and it is measured from the same picture in the same
        # frame as the position: the piece spans that fraction of the image,
        # and the image's width IS the wall's run. Never invented.
        run = (room.x1 - room.x0) if el.wall in ("back", "front") else (room.z1 - room.z0)
        if el.dimensions_m is not None and el.dimensions_m[0] > 0:
            width = float(el.dimensions_m[0])
        elif el.bbox is not None:
            width = (float(el.bbox[2]) - float(el.bbox[0])) * run
        else:
            continue
        if width <= 0.05:
            continue
        for seg in segs:
            if room.room_id not in seg.rooms or not _is_named_edge(seg, room, el.wall):
                continue
            # The element's own position along this wall, in the segment's
            # frame: the wall runs along x for the back and front edges, along
            # z for the left and right ones.
            world = (room.x0 + el.position_m[0], room.z0 + el.position_m[2])
            along = (world[0] if seg.axis == "x" else world[1]) - seg.p0
            half = width / 2 + 0.2          # the piece plus the gap it needs
            out.setdefault(seg.wall_id, []).append((round(along - half, 3), round(along + half, 3)))
    return out


def compile_scene(project_id: str, analysis: DesignAnalysis, style: StyleSpec, *, name: str,
                  reading=None) -> tuple[Scene, list[str]]:
    placed = layout_rooms(analysis.rooms)
    walls, openings, warnings = build_walls_and_openings(placed, reserved_wall_spans(placed, reading))
    floor, wet, wall_mat = _floor_and_wall_materials(style)
    # The approved render describes what each room is actually made of. Where it
    # does, that beats the style's blanket choice: the style picked one wood for
    # the whole flat, while the picture the client agreed to has panelling in one
    # bedroom and paint in the other. Rooms the render could not describe keep
    # the style default rather than a guess.
    per_room = room_surface_materials(reading) if reading is not None else {}
    # A wall segment borders one or two rooms (WallSeg.rooms). An exterior wall
    # takes its room's finish; an interior wall only takes one when both sides
    # agree, because a single slab cannot be panelled on one face and painted on
    # the other in this geometry, and picking a side would be arbitrary.
    segs = wall_segments(placed)
    seg_rooms = {seg.wall_id: seg.rooms for seg in segs}
    for w in walls:
        sides = {per_room.get(r, ("", ""))[1] for r in seg_rooms.get(w.wall_id, set())}
        sides.discard("")
        w.material = sides.pop() if len(sides) == 1 else wall_mat
    bind_wall_finishes(walls, segs, placed, reading)

    features = [f for f in analysis.architecture if f in vocab.ARCHITECTURE_FEATURES]
    rooms: list[Room] = []
    for p in placed:
        src = analysis.room(p.room_id)
        conf = Confidence(value=0.6 if (src and src.estimated) else 0.95, source=analysis.provider)
        rooms.append(
            Room(
                room_id=p.room_id,
                name=p.name,
                type=p.type,
                boundary=p.boundary,
                ceiling_height=p.height,
                floor_material=(per_room.get(p.room_id, ("", ""))[0]
                                or (wet if p.type in ("kitchen", "bathroom", "balcony") else floor)),
                confidence=conf,
                features=[] if p.type in ("kitchen", "bathroom", "balcony") else list(features),
            )
        )

    preset = LIGHTING_PRESETS.get(style.lighting_mood, LIGHTING_PRESETS["warm_daylight"])
    lights: list[InteriorLight] = []
    for p in placed:
        cx, cz = (p.x0 + p.x1) / 2, (p.z0 + p.z1) / 2
        area = p.width * p.depth
        lights.append(
            InteriorLight(
                room_id=p.room_id,
                type="area",
                position=(round(cx, 3), round(p.height - 0.05, 3), round(cz, 3)),
                power_w=round(max(40.0, min(200.0, area * 6.0)), 1),
                color_temp_k=preset["color_temp_k"],
                size_m=round(max(0.4, min(1.6, math.sqrt(area) * 0.3)), 2),
            )
        )

    scene = Scene(
        project_id=project_id,
        name=name,
        rooms=rooms,
        walls=walls,
        openings=openings,
        metadata={"compiled_from": {"analysis_version": analysis.version, "style_version": style.version}},
        spec_version=SPEC_VERSION,
        style=SceneStyle(
            name=style.name, tags=style.tags, palette=style.palette, materials=style.materials,
            lighting_mood=style.lighting_mood,
        ),
        lighting=LightingSpec(
            mood=style.lighting_mood,
            sun_azimuth_deg=preset["sun_azimuth_deg"],
            sun_elevation_deg=preset["sun_elevation_deg"],
            sun_strength=preset["sun_strength"],
            sky_turbidity=preset["sky_turbidity"],
            exposure_ev=preset["exposure_ev"],
            interior_lights=lights,
        ),
        camera_plan=CameraPlan(),
    )
    return scene, warnings


# ── object placement ─────────────────────────────────────────────────────


def _forward(rot: float) -> Vec2:
    return geo.rotate_point((0.0, -1.0), -rot)


def _right(rot: float) -> Vec2:
    return geo.rotate_point((1.0, 0.0), -rot)


def _relation_candidates(target: SceneObject, dims: tuple[float, float, float], rel_type: str, index: int, count: int,
                         room: Room) -> list[tuple[Vec2, float]]:
    tx, tz = target.position[0], target.position[2]
    tw, td = target.dimensions[0] * target.scale[0], target.dimensions[2] * target.scale[2]
    ow, od = dims[0], dims[2]
    f = _forward(target.rotation_y)
    r = _right(target.rotation_y)
    out: list[tuple[Vec2, float]] = []

    def at(dx: float, dz: float) -> Vec2:
        return (tx + dx, tz + dz)

    if rel_type == "in_front_of":
        for gap in (0.45, 0.7, 1.0):
            d = td / 2 + od / 2 + gap
            out.append((at(f[0] * d, f[1] * d), target.rotation_y + math.pi))
    elif rel_type == "beside":
        side = 1.0 if index % 2 == 0 else -1.0
        for gap in (0.08, 0.25, 0.5):
            d = tw / 2 + ow / 2 + gap
            out.append((at(r[0] * d * side, r[1] * d * side), target.rotation_y))
            out.append((at(-r[0] * d * side, -r[1] * d * side), target.rotation_y))
    elif rel_type == "under":
        d = max(0.0, od / 2 - td / 2 + 0.25)
        out.append((at(f[0] * d, f[1] * d), target.rotation_y))
        out.append(((tx, tz), target.rotation_y))
    elif rel_type == "around":
        # chairs on the two long sides of the target, evenly spread
        per_side = max(1, math.ceil(count / 2))
        side = 1.0 if index < per_side else -1.0
        k = index % per_side
        spread = tw * 0.8
        offset = -spread / 2 + (spread / (per_side - 1)) * k if per_side > 1 else 0.0
        d = td / 2 + od / 2 + 0.05
        pos = at(r[0] * offset + f[0] * d * side, r[1] * offset + f[1] * d * side)
        out.append((pos, target.rotation_y + (math.pi if side > 0 else 0.0)))
        d2 = tw / 2 + od / 2 + 0.05
        out.append((at(r[0] * d2 * side, r[1] * d2 * side), target.rotation_y + math.pi / 2 * side))
    elif rel_type == "facing":
        # wall candidates in front of the target, best aligned first
        cands = _wall_aligned_candidates(None, room, ow, od)  # type: ignore[arg-type]
        scored = []
        for pos, rot in cands:
            vx, vz = pos[0] - tx, pos[1] - tz
            dist = math.hypot(vx, vz)
            if dist < 0.5:
                continue
            cos = (vx * f[0] + vz * f[1]) / dist
            if cos > 0.5:
                scored.append((cos, -dist, (pos, rot)))
        scored.sort(reverse=True)
        out.extend(c for _, _, c in scored)
    return out


# lower = placed earlier within the same priority
ANCHOR_RANK: dict[str, int] = {
    "sofa": 0, "bed": 0, "kitchen_counter": 0, "desk": 0, "fireplace": 0,
    "tv_unit": 1, "wardrobe": 1, "fridge": 1,
    "coffee_table": 2, "bedside_table": 2, "rug": 3,
    "dining_table": 10, "chair": 11, "sideboard": 12, "console": 12, "dresser": 12, "bookshelf": 13,
    "armchair": 20, "loveseat": 20, "floor_lamp": 21, "side_table": 22, "table_lamp": 23, "ottoman": 24,
    "stool": 24, "pedestal": 25, "plant": 30, "wall_art": 31, "mirror": 31, "wall_shelf": 31, "sconce": 32,
    "books": 33, "tray": 33, "vase": 33, "sculpture": 33, "lantern": 33, "candle": 33, "pillows": 34,
    "throw": 34, "curtains": 40,
}

_FABRIC = {"sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "pillows", "curtains", "rug", "bar_stool", "stool", "throw"}
_WOOD = {"coffee_table", "side_table", "tv_unit", "dining_table", "wardrobe", "bedside_table", "dresser", "desk",
         "bookshelf", "sideboard", "console", "kitchen_island", "kitchen_counter", "vanity", "pedestal", "wall_shelf"}
_ACCENT_METAL = {"floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "mirror", "lantern", "sconce", "wall_clock"}
_ACCENT_DECOR = {"wall_art", "vase", "sculpture", "books", "tray", "candle", "basket"}

# wall-hung pieces like to sit above these
_HANG_ANCHORS = {"sofa", "loveseat", "bed", "sideboard", "console", "tv_unit", "desk", "dresser", "fireplace", "bookshelf"}
_EYE_LINE = 1.5          # centre height of art and mirrors
_SCONCE_HEIGHT = 1.65    # bottom of a sconce / bracket


def _object_color(item: ObjectPlanItem, decision, palette: list[str]) -> str:
    """The moodboard decides the colour: the planner's hint first, then the
    palette slot for the object's role (wall, floor, upholstery, accent, accent)."""
    if item.semantic_type == "plant":
        return decision.color  # foliage stays green whatever the palette says
    if decision.texture_ref:
        return decision.color  # the photo is the look; keep the neutral base
    if item.color_hint and item.color_hint.startswith("#") and len(item.color_hint) == 7:
        return item.color_hint.upper()
    if len(palette) >= 5:
        fam = item.family or vocab.family_for(item.semantic_type)
        if item.semantic_type in _FABRIC or fam in ("seating", "bed", "textile"):
            return palette[2]
        if item.semantic_type in _WOOD or fam in ("table", "storage"):
            return palette[1]
        if item.semantic_type in _ACCENT_METAL or fam == "lighting":
            return palette[3]
        if item.semantic_type in _ACCENT_DECOR or fam in ("art", "ornament"):
            return palette[4]
    return decision.color


def _object_visual(item: ObjectPlanItem) -> ObjectVisual:
    """Carry the reference's own words onto the scene object (P13).

    `color` and `material_overrides` hold the two RESOLVED values the executor
    can paint - a hex and one registry material id. This keeps what was
    actually said, which those two cannot express: "sage green" rather than
    #B9BFAE, "quilted" and "dark walnut frame" rather than nothing at all.

    Planner-only items produce an empty block; `style_descriptors` and
    `visual_descriptors` merge into one `descriptors` list, since the
    distinction is about classifying a reference, not describing an object.
    """
    v = item.visual
    return ObjectVisual(
        color_words=list(v.color_words),
        material=v.material,
        upholstery=v.upholstery,
        pattern=v.pattern,
        frame_finish=v.frame_finish,
        descriptors=[*v.style_descriptors, *v.visual_descriptors],
        source_intent_ids=list(item.source_intent_ids),
    )


def _on_segment(p: Vec2, a: Vec2, b: Vec2, tol: float = 1e-3) -> bool:
    return abs(geo.distance(a, p) + geo.distance(p, b) - geo.distance(a, b)) < tol


def _inside_or_near(room: Room, p: Vec2) -> bool:
    xs = [q[0] for q in room.boundary]
    zs = [q[1] for q in room.boundary]
    return min(xs) - 0.2 <= p[0] <= max(xs) + 0.2 and min(zs) - 0.2 <= p[1] <= max(zs) + 0.2


def _room_wall_ids(scene: Scene, room: Room) -> set[str]:
    wall_ids = set()
    n = len(room.boundary)
    for w in scene.walls:
        for i in range(n):
            a, b = room.boundary[i], room.boundary[(i + 1) % n]
            if geo.distance(a, w.start) + geo.distance(w.end, b) < 1e-3 or geo.distance(a, w.end) + geo.distance(w.start, b) < 1e-3:
                wall_ids.add(w.wall_id)
            elif _on_segment(w.start, a, b) and _on_segment(w.end, a, b):
                wall_ids.add(w.wall_id)
    return wall_ids


def _opening_points(scene: Scene, room: Room, kind: str) -> list[tuple[Vec2, float]]:
    """(centre, width) of every opening of `kind` on this room's walls."""
    pts: list[tuple[Vec2, float]] = []
    wall_ids = _room_wall_ids(scene, room)
    for o in scene.openings:
        if o.type.value == kind and o.wall_id in wall_ids:
            w = scene.wall(o.wall_id)
            if w is None:
                continue
            length = geo.distance(w.start, w.end) or 1.0
            pts.append((geo.segment_lerp(w.start, w.end, min(1.0, o.position / length)), o.width))
    return pts


def _window_points(scene: Scene, room: Room) -> list[Vec2]:
    return [p for p, _ in _opening_points(scene, room, "window")]


def _window_candidates(scene: Scene, room: Room, windows: list[Vec2], depth: float) -> list[tuple[Vec2, float]]:
    """(position, yaw) flush against the wall at each window centre, facing inward."""
    out: list[tuple[Vec2, float]] = []
    centroid = geo.polygon_centroid(room.boundary)
    n = len(room.boundary)
    for w in windows:
        for i in range(n):
            a, b = room.boundary[i], room.boundary[(i + 1) % n]
            if not _on_segment(w, a, b, tol=0.05):
                continue
            edge_len = geo.distance(a, b) or 1.0
            dx, dz = (b[0] - a[0]) / edge_len, (b[1] - a[1]) / edge_len
            nx, nz = -dz, dx
            if (centroid[0] - w[0]) * nx + (centroid[1] - w[1]) * nz < 0:
                nx, nz = -nx, -nz
            inset = depth / 2 + 0.06
            out.append(((w[0] + nx * inset, w[1] + nz * inset), math.atan2(-nx, -nz) + math.pi))
    return out


def _door_distance(scene: Scene, room: Room, p: Vec2) -> float:
    best = 99.0
    for c, _ in _opening_points(scene, room, "door"):
        if _inside_or_near(room, c):
            best = min(best, geo.distance(p, c))
    return best


# ── wall hanging ─────────────────────────────────────────────────────────


def _wall_hang_candidates(scene: Scene, room: Room, dims: tuple[float, float, float], sem: str) -> list[Candidate]:
    """Positions on the room's walls for a hung piece: above a matching anchor
    first (art over the sofa), then free wall, never over a window or a door,
    never overlapping another hung piece. y is the piece's bottom edge."""
    w, h, d = dims
    centroid = geo.polygon_centroid(room.boundary)
    windows = _opening_points(scene, room, "window")
    doors = _opening_points(scene, room, "door")
    hung = [o for o in scene.objects if o.room_id == room.room_id and o.mount == "wall"]
    anchors = [o for o in scene.objects if o.room_id == room.room_id and o.mount == "floor" and o.semantic_type in _HANG_ANCHORS]
    scored: list[tuple[float, Candidate]] = []
    n = len(room.boundary)
    for i in range(n):
        a, b = room.boundary[i], room.boundary[(i + 1) % n]
        edge_len = geo.distance(a, b)
        if edge_len < w + 0.2:
            continue
        dx, dz = (b[0] - a[0]) / edge_len, (b[1] - a[1]) / edge_len
        nx, nz = -dz, dx
        mid = geo.segment_lerp(a, b, 0.5)
        if (centroid[0] - mid[0]) * nx + (centroid[1] - mid[1]) * nz < 0:
            nx, nz = -nx, -nz
        rotation = math.atan2(-nx, -nz)
        inset = d / 2 + 0.10

        def along(p: Vec2) -> float:
            return (p[0] - a[0]) * dx + (p[1] - a[1]) * dz

        def off(p: Vec2) -> float:
            return abs((p[0] - a[0]) * nx + (p[1] - a[1]) * nz)

        # anchor-led positions: centred on a piece standing against this edge
        ts: list[tuple[float, float, Optional[SceneObject]]] = []
        for o in anchors:
            oc = (o.position[0], o.position[2])
            depth = o.dimensions[2] * o.scale[2]
            if off(oc) < depth / 2 + 0.45 and 0 < along(oc) < edge_len:
                ts.append((along(oc) / edge_len, 0.0, o))
        for t in (0.5, 0.35, 0.65, 0.22, 0.78):
            ts.append((t, 1.0, None))
        # Then a sweep of the whole wall, scored below the preferred five so an
        # unobstructed wall is placed exactly as before.
        #
        # Those five all sit between 22% and 78%, which is the middle of the
        # wall - and a window is usually in the middle of a wall too. Measured
        # on proj_a25a006c88: a 1.8 m window centred on a 5.8 m wall put every
        # one of the five inside the "not over a window" margin, so the
        # generator offered NOTHING on that wall and the client's television
        # hung on a different one, facing the wrong way. The wall had 2 m of
        # clear span at either end; nothing ever looked there.
        step = 0.25
        if edge_len > 2 * step:
            offset = step
            while offset < edge_len - step:
                ts.append((offset / edge_len, 2.0, None))
                offset += step
        for t, base_score, anchor in ts:
            s = along_pt = t * edge_len
            if s - w / 2 < 0.15 or s + w / 2 > edge_len - 0.15:
                continue
            p = (a[0] + dx * s, a[1] + dz * s)
            # never over a window or a doorway on this edge
            blocked = False
            for (c, ow) in windows + doors:
                if off(c) < 0.2 and abs(along(c) - s) < ow / 2 + w / 2 + 0.15:
                    blocked = True
                    break
            if blocked:
                continue
            for o in hung:
                oc = (o.position[0], o.position[2])
                if off(oc) < 0.3 and abs(along(oc) - s) < (o.dimensions[0] * o.scale[0] + w) / 2 + 0.1:
                    blocked = True
                    break
            if blocked:
                continue
            if sem in ("sconce", "wall_shelf"):
                y = _SCONCE_HEIGHT
            else:
                y = _EYE_LINE - h / 2
                if anchor is not None:
                    top = anchor.position[1] + anchor.dimensions[1] * anchor.scale[1]
                    y = max(y, top + 0.18)
                    if anchor.semantic_type == "fireplace":
                        y = top + 0.12
            y = min(y, room.ceiling_height - h - 0.15)
            pos = (p[0] + nx * inset, p[1] + nz * inset)
            scored.append((base_score + abs(t - 0.5) * 0.1, (pos, rotation, round(y, 3))))
    scored.sort(key=lambda s: s[0])
    return [c for _, c in scored]


# ── surfaces ─────────────────────────────────────────────────────────────


def _surface_top(obj: SceneObject) -> float:
    h = vocab.SURFACE_HEIGHT.get(obj.semantic_type)
    return obj.position[1] + (h if h is not None else obj.dimensions[1] * obj.scale[1])


def _surface_candidates(support: SceneObject, dims: tuple[float, float, float], siblings: list[SceneObject],
                        sem: str) -> list[Candidate]:
    """Spots on the top face of `support` where a (w, d) footprint fits and
    does not overlap what is already there."""
    sw, sd = support.dimensions[0] * support.scale[0], support.dimensions[2] * support.scale[2]
    ow, od = dims[0], dims[2]
    if ow > sw - 0.02 or od > sd - 0.02:
        return []
    f = _forward(support.rotation_y)
    r = _right(support.rotation_y)
    top = _surface_top(support)
    tx, tz = support.position[0], support.position[2]
    # local offsets (right, forward): centre, then along the width, then the corners
    offsets: list[tuple[float, float]] = [(0.0, 0.0)]
    for k in (0.25, 0.35, 0.15):
        offsets += [(k * sw, 0.0), (-k * sw, 0.0)]
    for k in (0.25, 0.35):
        offsets += [(0.0, -k * sd), (0.0, k * sd), (k * sw, -k * sd), (-k * sw, -k * sd)]
    if sem in ("pillows", "throw") and support.semantic_type in ("sofa", "loveseat", "armchair", "bed"):
        # cushions sit at the back of the seat, in the corners
        offsets = [(sw / 2 - ow / 2 - 0.05, -sd / 2 + od / 2 + 0.05), (-(sw / 2 - ow / 2 - 0.05), -sd / 2 + od / 2 + 0.05),
                   (0.0, -sd / 2 + od / 2 + 0.05)]
    out: list[Candidate] = []
    for lx, lf in offsets:
        if abs(lx) + ow / 2 > sw / 2 - 0.02 or abs(lf) + od / 2 > sd / 2 - 0.02:
            continue
        pos = (tx + r[0] * lx + f[0] * lf, tz + r[1] * lx + f[1] * lf)
        probe = SceneObject(semantic_type=sem, room_id=support.room_id, position=(pos[0], top, pos[1]),
                            rotation_y=support.rotation_y, dimensions=dims)
        fp = object_footprint(probe)
        if any(geo.convex_polygons_overlap(fp, object_footprint(s)) for s in siblings):
            continue
        out.append((pos, support.rotation_y, round(top, 3)))
    return out


def _pick_support(working: Scene, room: Room, item: ObjectPlanItem, dims: tuple[float, float, float],
                  placed_by_key: dict[str, SceneObject]) -> list[SceneObject]:
    """Supports to try for an on-surface item: the planned one, then the
    type's preferred hosts already in the room, largest top first."""
    out: list[SceneObject] = []
    if item.support_key and item.support_key in placed_by_key:
        out.append(placed_by_key[item.support_key])
    prefs = vocab.SUPPORT_PREFERENCE.get(item.semantic_type, [])
    hosts = [o for o in working.objects if o.room_id == room.room_id and o.mount == "floor"
             and o.semantic_type in vocab.SURFACE_HEIGHT and o not in out]

    def rank(o: SceneObject) -> tuple[int, float]:
        pref = prefs.index(o.semantic_type) if o.semantic_type in prefs else len(prefs) + 5
        return (pref, -(o.dimensions[0] * o.scale[0] * o.dimensions[2] * o.scale[2]))

    hosts.sort(key=rank)
    # seats and beds only host what asks for them (cushions, throws), never a lamp or a model
    hosts = [h for h in hosts if h.semantic_type in prefs or h.semantic_type not in ("sofa", "loveseat", "armchair", "bed")]
    return out + hosts


def _ordered(plan: ObjectPlan) -> list[ObjectPlanItem]:
    """Priority, then room anchors, then the rest; items whose relation
    target or support is not placed yet wait for it."""
    def footprint(i: ObjectPlanItem) -> float:  # big on-surface pieces claim their host first
        d = i.approx_dimensions
        return -(d[0] * d[2]) if (d and i.placement == "on_surface") else 0.0

    def rank(i: ObjectPlanItem) -> int:  # everything on a surface competes by size, not by type
        return 33 if i.placement == "on_surface" else ANCHOR_RANK.get(i.semantic_type, 50)

    pending = sorted(plan.items, key=lambda i: (i.priority, rank(i), footprint(i), i.object_key))
    ordered: list[ObjectPlanItem] = []
    guard = 0
    while pending and guard < 10:
        guard += 1
        rest = []
        done = {i.object_key for i in ordered}
        for item in pending:
            deps = [k for k in ((item.relation.target_key if item.relation else None), item.support_key) if k]
            if all(k in done or plan.item(k) is None for k in deps):
                ordered.append(item)
                done.add(item.object_key)
            else:
                rest.append(item)
        if len(rest) == len(pending):
            ordered += rest
            break
        pending = rest
    return ordered


def place_objects(scene: Scene, plan: ObjectPlan, assets: AssetPlan, *,
                  reading=None) -> tuple[list[AddObjectOp], list[str]]:
    """Place every planned item, carrying element identity onto each object.

    `reading` is optional and keyword-only so the nine existing call sites keep
    working untouched. When it IS supplied, the plan's `count` is checked
    against how many occurrences of that element the approved reading actually
    holds, and any divergence is warned about rather than tolerated: planning
    four stools from a picture showing two is a decision somebody should see,
    not something to discover at the point of paying for four meshes.
    """
    working = scene.model_copy(deep=True)
    ops: list[AddObjectOp] = []
    warnings: list[str] = []
    placed_by_key: dict[str, SceneObject] = {}
    palette = list(scene.style.palette) if scene.style else []

    # P1-IDENTITY-002: occurrences per element, as READ, not as planned.
    occurrences: dict[str, int] = {}
    for element in getattr(reading, "elements", None) or []:
        key = getattr(element, "element_id", "") or ""
        if key:
            occurrences[key] = occurrences.get(key, 0) + 1

    for item in _ordered(plan):
        decision = assets.decision(item.object_key)
        if decision is None:
            warnings.append(f"{item.object_key}: no asset decision")
            continue
        room = working.room(item.room_id)
        if room is None:
            warnings.append(f"{item.object_key}: room {item.room_id} not in scene")
            continue
        dims = tuple(d * s for d, s in zip(decision.dimensions, decision.scale))
        color = _object_color(item, decision, palette)
        placement = item.placement if item.semantic_type != "curtains" else "floor"

        # The divergence check. Only when a reading was supplied AND it knows
        # this element: a reading that has never seen the element says nothing
        # about it, and treating silence as "zero occurrences" would warn on
        # every catalog item the planner legitimately added.
        if item.element_id and item.element_id in occurrences:
            read_count = occurrences[item.element_id]
            if read_count != item.count:
                warnings.append(
                    f"{item.object_key}: plan says {item.count}, the approved reading "
                    f"has {read_count} occurrence(s) of {item.element_id}"
                )

        for n in range(item.count):
            parent: Optional[SceneObject] = None
            mount = decision.mount
            candidates: list[Candidate] = []

            if placement == "on_surface":
                mount = "surface"
                for support in _pick_support(working, room, item, dims, placed_by_key):
                    siblings = [o for o in working.objects if o.parent_id == support.object_id]
                    cands = _surface_candidates(support, dims, siblings, item.semantic_type)
                    if cands:
                        parent = support
                        candidates = cands
                        break
                if parent is None:
                    if item.semantic_type in ("plant", "lantern", "basket", "sculpture", "vase"):
                        placement, mount = "floor", "floor"   # a floor-standing version is fine
                    else:
                        warnings.append(f"{item.object_key}: no surface in {room.name} to rest on; skipped")
                        break
            if placement == "wall":
                mount = "wall"
                candidates = _prefer_anchor(
                    _wall_hang_candidates(working, room, dims, item.semantic_type), item, room)
            elif placement == "ceiling":
                mount = "ceiling"
                c = geo.polygon_centroid(room.boundary)
                target = placed_by_key.get(item.relation.target_key) if (item.relation and item.relation.target_key) else None
                if target is not None:
                    c = (target.position[0], target.position[2])
                candidates = [(c, 0.0, round(room.ceiling_height - dims[1], 3))]
            elif placement == "floor":
                mount = "floor" if decision.mount in ("surface", "wall") and item.semantic_type != "curtains" else decision.mount
                candidates = [(p, r, None) for p, r in _floor_candidates(working, room, item, dims, n, placed_by_key)]

            placed: Optional[SceneObject] = None
            shrink_steps = (1.0, 0.8, 0.65) if item.semantic_type in ("kitchen_counter", "wardrobe", "curtains", "bookshelf", "sideboard") else (1.0,)
            for shrink in shrink_steps:
                if placed is not None:
                    break
                if shrink < 1.0:
                    dims = (dims[0] * shrink, dims[1], dims[2])
                    candidates = [(p, r, None) for p, r in _wall_aligned_candidates(working, room, dims[0], dims[2])]
                    if item.semantic_type == "curtains" and _window_points(working, room):
                        wp = _window_points(working, room)
                        candidates.sort(key=lambda c: min(geo.distance(c[0], w) for w in wp))
                for pos, rot, y_fixed in candidates:
                    if y_fixed is not None:
                        y = y_fixed
                    elif mount == "floor" or item.semantic_type == "curtains":
                        y = room.floor_height
                    elif mount == "ceiling":
                        y = room.ceiling_height - decision.dimensions[1]
                    else:
                        y = 1.4
                    scale = decision.scale if shrink == 1.0 else (decision.scale[0] * shrink, decision.scale[1], decision.scale[2])
                    candidate = SceneObject(
                        semantic_type=item.semantic_type,
                        asset_id=decision.asset_id,
                        room_id=room.room_id,
                        position=(round(pos[0], 3), round(y, 3), round(pos[1], 3)),
                        rotation_y=round(rot % (2 * math.pi), 4),
                        scale=scale,
                        dimensions=decision.dimensions,
                        color=color,
                        source=ObjectSource.CATALOG,
                        mount=mount,
                        confidence=Confidence(value=0.7, source=plan.provider),
                        source_strategy=decision.strategy,
                        material_overrides=decision.material_overrides,
                        plan_key=item.object_key if n == 0 else f"{item.object_key}#{n + 1}",
                        # P1-IDENTITY-002. This is the one place identity was
                        # lost: `item.element_id` was in scope and unused, so
                        # three bar stools became three unrelated objects and
                        # the link back to the element that justified them
                        # survived only as a join nobody performed.
                        #
                        # `instance_id` is DERIVED from element_id and the loop
                        # index, not resolved from ElementInstance rows
                        # (design.md TDR-004): resolving them would make
                        # app/planning import from app/intelligence, crossing a
                        # boundary app/scene/schema.py exists to keep. Derived
                        # also means deterministic - two compiles of one plan
                        # produce identical ids, with no uuid and no clock.
                        element_id=item.element_id or None,
                        instance_id=f"{item.element_id}#{n}" if item.element_id else None,
                        parent_id=parent.object_id if parent else None,
                        texture_ref=decision.texture_ref or None,
                        shape=decision.shape or None,
                        name=item.name,
                        visual=_object_visual(item),
                    )
                    working.objects.append(candidate)
                    if not validate_object(working, candidate):
                        placed = candidate
                        break
                    working.objects.pop()
            if placed is None:
                warnings.append(f"{item.object_key}: no valid position in {room.name} (priority {item.priority})")
                break
            ops.append(AddObjectOp(object=placed))
            if n == 0:
                placed_by_key[item.object_key] = placed
    return ops, warnings


# Arrangement hints from the approved render, used as PREFERENCES only.
#
# What is usable and what is not. The reader answers in the picture's own frame
# ("back wall", "left wall", "front"), and a render has no fixed orientation
# relative to the floor plan - its "left wall" is whichever wall the camera
# happened to face. Mapping those onto real walls would be inventing a fact, so
# they are deliberately ignored and the engine's existing order stands.
#
# What survives the translation is frame-independent. `against` says WHERE:
#   * "centre" / "middle"          - free-standing, not against a wall
#   * "corner"                     - in a corner
#   * anything naming a window     - a wall that has one
#   * the name of another piece    - beside that piece
#
# and `faces` says WHICH WAY ROUND:
#   * the name of another piece    - turned towards it
#   * anything naming a window     - turned towards the glazing
#   * "into the room" / "centre"   - turned inward rather than at a wall
#
# Both are read off the same render and both are preferences. They rank on
# separate axes, so a candidate can satisfy one, the other, or both.
#
# Nothing here filters: every candidate the engine produced stays in the list,
# in the same order among equals. A hint only moves matching spots earlier, so
# an unsatisfiable hint costs nothing and the fallback path is byte-for-byte
# what runs today for an element with no hint at all.
_CENTRE_WORDS = ("centre", "center", "middle", "central", "free-standing", "freestanding")
_CORNER_WORDS = ("corner",)
_WINDOW_WORDS = ("window", "glazing", "french door")
_INWARD_WORDS = ("room", "centre", "center", "middle", "inward", "inwards", "inside")
# Cosine of the half-angle that counts as "pointing at". Candidates arrive at
# 90 degree intervals (wall normals), so 60 degrees admits at most one of them
# per direction and never the one facing away.
_FACES_COS = 0.5


def _edge_has_window(scene: Scene, room: Room, pos: Vec2) -> bool:
    windows = _window_points(scene, room) if scene is not None else []
    return any(geo.distance(pos, w) <= 1.6 for w in windows)


def _near_corner(room: Room, pos: Vec2) -> bool:
    return any(geo.distance(pos, v) <= 1.2 for v in room.boundary)


def _points_at(candidate: tuple[Vec2, float], target: Vec2) -> bool:
    """Does this candidate's forward vector point at `target`?"""
    pos, rot = candidate[0], candidate[1]
    vx, vz = target[0] - pos[0], target[1] - pos[1]
    dist = math.hypot(vx, vz)
    if dist < 1e-6:                      # standing on it: no direction to judge
        return False
    fx, fz = _forward(rot)
    return (fx * vx + fz * vz) / dist >= _FACES_COS


def _faces_rank(candidate: tuple[Vec2, float], item: ObjectPlanItem, scene: Scene, room: Room,
                placed_by_key: dict[str, SceneObject]) -> int:
    """0 = this rotation satisfies `faces`, 1 = it does not.

    The other half of the arrangement hint, and until now the unused half: the
    reader has always answered which way a piece is turned, and nothing read it,
    so rotation came only from whichever wall the candidate sat against. A sofa
    "facing the tv" was placed facing whatever the wall normal happened to be.

    Resolves the same frame-independent targets `_hint_rank` does, for the same
    reason: "faces north" is unusable because the render has no fixed
    orientation against the floor plan, but "faces the tv" is a fact about two
    objects and survives the translation.
    """
    hint = (item.faces or "").strip().lower()
    if not hint:
        return 1
    # A piece already standing in this room, named in the hint.
    for obj in placed_by_key.values():
        name = (obj.semantic_type or "").replace("_", " ")
        if obj.room_id == room.room_id and name and name in hint:
            if _points_at(candidate, (obj.position[0], obj.position[2])):
                return 0
    if any(w in hint for w in _WINDOW_WORDS):
        for point in (_window_points(scene, room) if scene is not None else []):
            if _points_at(candidate, point):
                return 0
    if any(w in hint for w in _INWARD_WORDS):
        if _points_at(candidate, geo.polygon_centroid(room.boundary)):
            return 0
    return 1


def _hint_rank(candidate: tuple[Vec2, float], item: ObjectPlanItem, scene: Scene, room: Room,
               placed_by_key: dict[str, SceneObject]) -> int:
    """0 = matches the hint, 1 = does not. Lower sorts first; ties keep order."""
    hint = (item.against or "").strip().lower()
    if not hint:
        return 1
    pos = candidate[0]
    centroid = geo.polygon_centroid(room.boundary)
    if any(w in hint for w in _WINDOW_WORDS) and _edge_has_window(scene, room, pos):
        return 0
    if any(w in hint for w in _CORNER_WORDS) and _near_corner(room, pos):
        return 0
    if any(w in hint for w in _CENTRE_WORDS) and geo.distance(pos, centroid) <= 1.0:
        return 0
    # "against the sofa": beside a piece already standing in this room.
    for key, obj in placed_by_key.items():
        name = (obj.semantic_type or "").replace("_", " ")
        if obj.room_id == room.room_id and name and name in hint:
            if geo.distance(pos, (obj.position[0], obj.position[2])) <= 1.8:
                return 0
    return 1


def anchor_world(item: ObjectPlanItem, room: Room) -> Optional[Vec3]:
    """The reading's render-frame anchor in world metres (P22).

    Room rectangles are axis-aligned, and the reading's frame is bound to
    them by convention: the picture's back wall is the room's north edge
    (min z), its left wall the west edge (min x). So room-local (x, y, z) is
    an offset from the north-west corner. Nothing here is a placement.
    """
    if item.anchor_m is None:
        return None
    xs = [p[0] for p in room.boundary]
    zs = [p[1] for p in room.boundary]
    ax, ay, az = item.anchor_m
    return (min(xs) + ax, ay, min(zs) + az)


#: How close two candidates must be to the pictured spot to count as a tie, in
#: metres. Below this the named relations ("against the sofa") break the tie;
#: above it the measured position decides. A knob, not a constant, because the
#: verification loop in research/placement_loop.py turns it and measures what
#: happens rather than anyone arguing for a number.
# Measured, not argued: the verification loop turned this knob across four
# settings on a real project and 0.01 was the only one that put every piece
# facing the way the picture showed it (orientation 80% -> 100%, accuracy
# 93% -> 98%). A wide band let vague text - "against wall", true of nearly
# every candidate - override a position the reader actually measured.
ANCHOR_TIE_BAND_M = 0.01
#: Whether an anchor ESTIMATED from the crop box also leads the named hints.
#: On: the reasoning for "off" was that an estimate is not more specific than
#: a stated relation, and the measurement disagreed - a box-derived position
#: names one spot, while "into the room" names half the room. Evidence is one
#: project; the loop re-checks it on any other.
ANCHOR_LEADS_WHEN_DERIVED = True


#: Types with a front you can see, and therefore an orientation worth honouring
#: and worth grading. A rug, a basket or a vase has no front: the reader still
#: answers "into the room" for them because it answers for everything, and
#: turning one 180 degrees changes nothing on screen. Counting those as
#: orientation failures measures the vocabulary, not the room.
ORIENTED_TYPES: frozenset[str] = frozenset({
    "sofa", "loveseat", "armchair", "chair", "dining_chair", "bench", "stool",
    "bar_stool", "rocking_chair", "office_chair", "accent_chair", "sectional",
    "bed", "desk", "television", "tv_unit", "sideboard", "console", "dresser",
    "wardrobe", "bookshelf", "fireplace", "vanity", "kitchen_counter",
})


def _rotation_facing(direction: Optional[tuple[float, float]]) -> float:
    """The quarter turn whose forward best matches the pictured facing.

    Chosen against `_forward` rather than derived, so it cannot drift from
    whatever yaw convention the placer uses.
    """
    if direction is None:
        return 0.0
    best, score = 0.0, -2.0
    for k in range(4):
        rot = k * math.pi / 2
        fx, fz = _forward(rot)
        s = fx * direction[0] + fz * direction[1]
        if s > score:
            best, score = rot, s
    return best


#: Which way "into the room" points from each named wall, in the render frame
#: the plan adopts: back is the north edge (min z), left the west edge (min x).
_INWARD: dict[str, Vec2] = {"back": (0.0, 1.0), "front": (0.0, -1.0),
                           "left": (1.0, 0.0), "right": (-1.0, 0.0)}


def anchor_spot(item: ObjectPlanItem, room: Room, depth_m: float = 0.0) -> Optional[Vec2]:
    """Where the piece's CENTRE goes if the picture is taken literally.

    The reader answers with the wall line - "against the back wall" is z = 0 -
    but z = 0 is where the wall is, and an object centred there has half of
    itself inside it. So a piece against a named wall is pushed into the room
    by half its depth. Without this the anchor was both unreachable and
    unfairly graded: the candidate was rejected for intersecting the wall, and
    a correctly placed piece still measured half a depth away from its own
    anchor. Measured before this: placement stuck at 55% across every knob the
    verification loop turned, because no knob addressed it.
    """
    a = anchor_world(item, room)
    if a is None:
        return None
    x, z = a[0], a[2]
    inward = _INWARD.get(item.wall)
    if inward is not None and depth_m > 0:
        x += inward[0] * depth_m / 2.0
        z += inward[1] * depth_m / 2.0
    return (round(x, 3), round(z, 3))


def _anchor_candidate(item: ObjectPlanItem, room: Room, dims: Optional[tuple[float, float, float]] = None,
                      ) -> Optional[tuple[Vec2, float]]:
    """The spot the picture actually put the piece, as a candidate of its own.

    Preference alone could only pick the nearest spot the generator had
    already produced, and those hug the walls: measured on proj_a25a006c88, a
    coffee table read at 2.25 m into the room was reordered among wall spots
    and still came out at 4.08 m, against the far wall. Offering the anchor
    itself is what makes the read position reachable at all.

    Offered, never imposed: it goes through exactly the same validation as
    every other candidate, so an anchor that collides, overhangs the room or
    blocks a doorway is rejected and the generator's own spots take over.
    """
    spot = anchor_spot(item, room, dims[2] if dims else 0.0)
    if spot is None:
        return None
    return (spot, _rotation_facing(item.facing_dir))


def _prefer_anchor(candidates: list[Candidate], item: ObjectPlanItem, room: Room) -> list[Candidate]:
    """Order hung spots by how close they are to the pictured one.

    The hung path never read the arrangement evidence at all: a television
    read against the back wall was hung on whichever wall the generator
    happened to offer first (measured: the right wall). Reorders only - the
    height stays the generator's, which keeps art clear of windows and other
    hung pieces; only the wall and the position along it come from the
    picture.
    """
    a = anchor_world(item, room)
    if a is None or not candidates:
        return candidates

    xs = [p[0] for p in room.boundary]
    zs = [p[1] for p in room.boundary]
    edge = {"back": ("z", min(zs)), "front": ("z", max(zs)),
            "left": ("x", min(xs)), "right": ("x", max(xs))}.get(item.wall)

    def off_named_wall(c: Candidate) -> int:
        """0 when this spot is on the wall the reader named.

        Sorting on distance alone hops walls: the client's television was read
        against the back wall, the window occupies the middle of that wall so
        the spot beside it lost to a nearer spot round the corner, and the TV
        hung on the left wall - displacing the picture that belonged there.
        The wall is the stronger half of the claim; sliding along it to clear a
        window keeps the piece where it was seen, and 5.8 m of wall has room
        either side of a 1.8 m window.
        """
        if edge is None:
            return 0
        axis, value = edge
        return 0 if abs((c[0][0] if axis == "x" else c[0][1]) - value) <= 0.6 else 1

    return sorted(candidates, key=lambda c: (off_named_wall(c), geo.distance(c[0], (a[0], a[2]))))


def _anchor_distance(candidate: tuple[Vec2, float], item: ObjectPlanItem, room: Room,
                     depth_m: float = 0.0) -> float:
    spot = anchor_spot(item, room, depth_m)
    if spot is None:
        return 0.0
    return round(geo.distance(candidate[0], spot), 2)


def _facing_dir_rank(candidate: tuple[Vec2, float], item: ObjectPlanItem) -> int:
    """0 = this rotation faces the wall the piece was pictured facing."""
    if item.facing_dir is None:
        return 0
    fx, fz = _forward(candidate[1])
    dx, dz = item.facing_dir
    return 0 if fx * dx + fz * dz >= _FACES_COS else 1


def _prefer_hint(candidates: list[tuple[Vec2, float]], item: ObjectPlanItem, scene: Scene,
                 room: Room, placed_by_key: dict[str, SceneObject],
                 depth_m: float = 0.0) -> list[tuple[Vec2, float]]:
    """Re-order, never re-select. Same list, matching spots first.

    Position leads and orientation breaks its ties: which wall a piece stands
    against is a stronger claim than which way round it is, and a candidate that
    satisfies both should beat one that satisfies either. `sorted` is stable, so
    candidates matching neither hint keep the engine's own order among
    themselves.

    Which evidence leads depends on how good it is. A position the reader
    MEASURED is the most specific thing anyone said about this piece, so it
    leads: measured live, `against: 'wall'` and `faces: 'into the room'` -
    true of almost every candidate - were beating an anchor that named one
    spot, and a floor lamp read against the back wall was placed by
    `against: 'the tv unit'` instead. Distances within a quarter metre count
    as a tie, so the named relations still break near-ties, and they lead
    outright when the anchor was only ESTIMATED from the crop box.
    """
    if not ((item.against or "").strip() or (item.faces or "").strip()
            or item.anchor_m is not None or item.facing_dir is not None):
        return candidates

    def band(c: tuple[Vec2, float]) -> int:
        return round(_anchor_distance(c, item, room, depth_m) / max(0.01, ANCHOR_TIE_BAND_M))

    leads = item.anchor_m is not None and (
        item.anchor_source == "read" or ANCHOR_LEADS_WHEN_DERIVED)
    if leads:
        return sorted(candidates, key=lambda c: (band(c),
                                                 _hint_rank(c, item, scene, room, placed_by_key),
                                                 _faces_rank(c, item, scene, room, placed_by_key),
                                                 _facing_dir_rank(c, item)))
    return sorted(candidates, key=lambda c: (_hint_rank(c, item, scene, room, placed_by_key),
                                             _faces_rank(c, item, scene, room, placed_by_key),
                                             band(c),
                                             _facing_dir_rank(c, item)))


def _floor_candidates(working: Scene, room: Room, item: ObjectPlanItem, dims: tuple[float, float, float], n: int,
                      placed_by_key: dict[str, SceneObject]) -> list[tuple[Vec2, float]]:
    candidates: list[tuple[Vec2, float]] = []
    rel = item.relation
    target = placed_by_key.get(rel.target_key) if (rel and rel.target_key) else None
    if rel and target is not None and rel.type != "against_wall":
        candidates += _relation_candidates(target, dims, rel.type, n, item.count, room)  # type: ignore[arg-type]
    if item.semantic_type == "rug" and not candidates:
        c = geo.polygon_centroid(room.boundary)
        candidates.append((c, 0.0))
    # a dining table for four or more stands off the wall so chairs fit behind it
    inset_extra = 0.75 if item.semantic_type == "dining_table" else 0.0
    wall_candidates = _wall_aligned_candidates(working, room, dims[0], dims[2], inset_extra=inset_extra)
    if item.semantic_type == "curtains":
        # curtains hang on the window: centred on it, flush to the wall, facing the room
        windows = _window_points(working, room)
        if windows:
            wall_candidates.sort(key=lambda c: min(geo.distance(c[0], w) for w in windows))
            wall_candidates = _window_candidates(working, room, windows, dims[2]) + wall_candidates
    elif item.semantic_type == "dining_table":
        sofa = next((o for o in working.objects if o.room_id == room.room_id and o.semantic_type == "sofa"), None)
        if sofa is not None:
            wall_candidates.sort(key=lambda c: -geo.distance(c[0], (sofa.position[0], sofa.position[2])))
    elif item.semantic_type in ("kitchen_counter", "fireplace"):
        # counters and chimney breasts run along the longest wall, away from the door
        wall_candidates.sort(key=lambda c: _door_distance(working, room, c[0]), reverse=True)
    candidates += wall_candidates
    # The pictured spot, offered alongside the generator's own. Validation
    # still decides whether it survives.
    anchored = _anchor_candidate(item, room, dims)
    if anchored is not None:
        candidates.insert(0, anchored)
    # Every spot, offered FIRST with the way the reader saw the piece turned.
    #
    # Until now a piece took the rotation of whatever candidate it landed on,
    # which is the wall's normal - so an armchair read as facing the
    # television faced whichever wall it ended up against instead. Measured on
    # proj_a25a006c88: 8 of 11 pieces ended up turned the way the picture
    # showed, and the three that did not had simply inherited a wall.
    #
    # The originals stay in the list, after these, so a rotation that will not
    # fit - a wide sofa turned side-on into an alcove - still falls back to a
    # spot that does rather than failing to place at all.
    if item.facing_dir is not None and item.semantic_type in ORIENTED_TYPES:
        wanted = _rotation_facing(item.facing_dir)
        candidates = [(pos, wanted) for pos, _ in candidates] + candidates
    # Preference pass, last: everything above decided WHICH spots are valid and
    # in what default order; this only moves the ones the approved render
    # points at earlier among them.
    return _prefer_hint(candidates, item, working, room, placed_by_key, dims[2])

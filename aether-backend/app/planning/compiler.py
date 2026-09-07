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
    Room,
    Scene,
    SceneObject,
    SceneStyle,
)
from ..spatial import geometry as geo
from ..spatial.validation import object_footprint, validate_object
from .layout import build_walls_and_openings, layout_rooms

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


def compile_scene(project_id: str, analysis: DesignAnalysis, style: StyleSpec, *, name: str) -> tuple[Scene, list[str]]:
    placed = layout_rooms(analysis.rooms)
    walls, openings, warnings = build_walls_and_openings(placed)
    floor, wet, wall_mat = _floor_and_wall_materials(style)
    for w in walls:
        w.material = wall_mat

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
                floor_material=wet if p.type in ("kitchen", "bathroom", "balcony") else floor,
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
    if not prefs:
        hosts = [h for h in hosts if h.semantic_type not in ("sofa", "loveseat", "armchair", "bed")]
    return out + hosts


def _ordered(plan: ObjectPlan) -> list[ObjectPlanItem]:
    """Priority, then room anchors, then the rest; items whose relation
    target or support is not placed yet wait for it."""
    pending = sorted(plan.items, key=lambda i: (i.priority, ANCHOR_RANK.get(i.semantic_type, 50), i.object_key))
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


def place_objects(scene: Scene, plan: ObjectPlan, assets: AssetPlan) -> tuple[list[AddObjectOp], list[str]]:
    working = scene.model_copy(deep=True)
    ops: list[AddObjectOp] = []
    warnings: list[str] = []
    placed_by_key: dict[str, SceneObject] = {}
    palette = list(scene.style.palette) if scene.style else []

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
                candidates = _wall_hang_candidates(working, room, dims, item.semantic_type)
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
                        parent_id=parent.object_id if parent else None,
                        texture_ref=decision.texture_ref or None,
                        shape=decision.shape or None,
                        name=item.name,
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
    return candidates

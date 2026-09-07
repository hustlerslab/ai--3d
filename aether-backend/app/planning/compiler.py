"""Scene compiler (plan §9 / DPR §7 "SCENE COMPILER").

compile_scene()  DesignAnalysis + StyleSpec → Scene with rooms, walls, openings,
                 style, lighting and an empty camera plan (no objects yet).
place_objects()  ObjectPlan + AssetPlan → AddObjectOps, placed with the
                 existing spatial candidates and validated per object, so the
                 result commits through the normal patch pipeline.
"""
from __future__ import annotations

import math
from typing import Optional

from ..design.service import _wall_aligned_candidates
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
from ..spatial.validation import validate_object
from .layout import build_walls_and_openings, layout_rooms

Vec2 = tuple[float, float]

LIGHTING_PRESETS: dict[str, dict] = {
    "warm_daylight": {"sun_azimuth_deg": 135.0, "sun_elevation_deg": 40.0, "sun_strength": 3.0, "sky_turbidity": 2.5, "exposure_ev": 0.0, "color_temp_k": 3200},
    "cool_daylight": {"sun_azimuth_deg": 200.0, "sun_elevation_deg": 55.0, "sun_strength": 4.0, "sky_turbidity": 1.8, "exposure_ev": -0.2, "color_temp_k": 4500},
    "evening": {"sun_azimuth_deg": 260.0, "sun_elevation_deg": 8.0, "sun_strength": 1.2, "sky_turbidity": 4.0, "exposure_ev": 0.4, "color_temp_k": 2700},
    "studio": {"sun_azimuth_deg": 150.0, "sun_elevation_deg": 65.0, "sun_strength": 2.0, "sky_turbidity": 1.5, "exposure_ev": 0.0, "color_temp_k": 4000},
}


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
    "sofa": 0, "bed": 0, "kitchen_counter": 0, "desk": 0,
    "tv_unit": 1, "wardrobe": 1, "fridge": 1,
    "coffee_table": 2, "bedside_table": 2, "rug": 3,
    "dining_table": 10, "chair": 11, "sideboard": 12,
    "armchair": 20, "floor_lamp": 21, "side_table": 22, "plant": 30, "wall_art": 31, "curtains": 40,
}

_FABRIC = {"sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "pillows", "curtains", "rug", "bar_stool"}
_WOOD = {"coffee_table", "side_table", "tv_unit", "dining_table", "wardrobe", "bedside_table", "dresser", "desk",
         "bookshelf", "sideboard", "console", "kitchen_island", "kitchen_counter", "vanity"}


def _object_color(item: ObjectPlanItem, decision, palette: list[str]) -> str:
    """The moodboard decides the colour: the planner's hint first, then the
    palette slot for the object's role (wall, floor, upholstery, accent, accent)."""
    if item.semantic_type == "plant":
        return decision.color  # foliage stays green whatever the palette says
    if item.color_hint and item.color_hint.startswith("#") and len(item.color_hint) == 7:
        return item.color_hint.upper()
    if len(palette) >= 5:
        if item.semantic_type in _FABRIC:
            return palette[2]
        if item.semantic_type in _WOOD:
            return palette[1]
        if item.semantic_type in ("floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "mirror", "lantern"):
            return palette[3]
        if item.semantic_type in ("wall_art", "vase", "sculpture", "plant"):
            return palette[4]
    return decision.color


def _window_points(scene: Scene, room: Room) -> list[Vec2]:
    pts: list[Vec2] = []
    wall_ids = set()
    n = len(room.boundary)
    for w in scene.walls:
        for i in range(n):
            a, b = room.boundary[i], room.boundary[(i + 1) % n]
            if geo.distance(a, w.start) + geo.distance(w.end, b) < 1e-3 or geo.distance(a, w.end) + geo.distance(w.start, b) < 1e-3:
                wall_ids.add(w.wall_id)
            elif _on_segment(w.start, a, b) and _on_segment(w.end, a, b):
                wall_ids.add(w.wall_id)
    for o in scene.openings:
        if o.type.value == "window" and o.wall_id in wall_ids:
            w = scene.wall(o.wall_id)
            if w is None:
                continue
            length = geo.distance(w.start, w.end) or 1.0
            pts.append(geo.segment_lerp(w.start, w.end, min(1.0, o.position / length)))
    return pts


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
    for o in scene.openings:
        if o.type.value != "door":
            continue
        w = scene.wall(o.wall_id)
        if w is None:
            continue
        length = geo.distance(w.start, w.end) or 1.0
        c = geo.segment_lerp(w.start, w.end, min(1.0, o.position / length))
        if _inside_or_near(room, c):
            best = min(best, geo.distance(p, c))
    return best


def _on_segment(p: Vec2, a: Vec2, b: Vec2, tol: float = 1e-3) -> bool:
    return abs(geo.distance(a, p) + geo.distance(p, b) - geo.distance(a, b)) < tol


def _inside_or_near(room: Room, p: Vec2) -> bool:
    xs = [q[0] for q in room.boundary]
    zs = [q[1] for q in room.boundary]
    return min(xs) - 0.2 <= p[0] <= max(xs) + 0.2 and min(zs) - 0.2 <= p[1] <= max(zs) + 0.2


def place_objects(scene: Scene, plan: ObjectPlan, assets: AssetPlan) -> tuple[list[AddObjectOp], list[str]]:
    working = scene.model_copy(deep=True)
    ops: list[AddObjectOp] = []
    warnings: list[str] = []
    placed_by_key: dict[str, SceneObject] = {}

    # order: priority, then room anchors (the pieces everything else arranges
    # around), then the rest; items whose relation target is not placed yet wait
    pending = sorted(plan.items, key=lambda i: (i.priority, ANCHOR_RANK.get(i.semantic_type, 50), i.object_key))
    ordered: list[ObjectPlanItem] = []
    guard = 0
    while pending and guard < 10:
        guard += 1
        rest = []
        for item in pending:
            target = item.relation.target_key if item.relation else None
            if target is None or target in {i.object_key for i in ordered} or plan.item(target) is None:
                ordered.append(item)
            else:
                rest.append(item)
        if len(rest) == len(pending):
            ordered += rest
            break
        pending = rest

    palette = list(scene.style.palette) if scene.style else []

    for item in ordered:
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
        for n in range(item.count):
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
            elif item.semantic_type == "kitchen_counter":
                # counters run along the longest wall, away from the door
                wall_candidates.sort(key=lambda c: _door_distance(working, room, c[0]), reverse=True)
            candidates += wall_candidates

            placed: Optional[SceneObject] = None
            # pieces that can shrink to fit (a counter run, a wardrobe) get smaller tries too
            shrink_steps = (1.0, 0.8, 0.65) if item.semantic_type in ("kitchen_counter", "wardrobe", "curtains", "bookshelf", "sideboard") else (1.0,)
            for shrink in shrink_steps:
                if placed is not None:
                    break
                if shrink < 1.0:
                    dims = (dims[0] * shrink, dims[1], dims[2])
                    candidates = list(_wall_aligned_candidates(working, room, dims[0], dims[2]))
                    if item.semantic_type == "curtains" and _window_points(working, room):
                        wp = _window_points(working, room)
                        candidates.sort(key=lambda c: min(geo.distance(c[0], w) for w in wp))
                for pos, rot in candidates:
                    if decision.mount == "floor" or item.semantic_type == "curtains":
                        y = room.floor_height
                    elif decision.mount == "ceiling":
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
                        mount=decision.mount,
                        confidence=Confidence(value=0.7, source=plan.provider),
                        source_strategy=decision.strategy,
                        material_overrides=decision.material_overrides,
                        plan_key=item.object_key if n == 0 else f"{item.object_key}#{n + 1}",
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

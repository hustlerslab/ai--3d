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


def place_objects(scene: Scene, plan: ObjectPlan, assets: AssetPlan) -> tuple[list[AddObjectOp], list[str]]:
    working = scene.model_copy(deep=True)
    ops: list[AddObjectOp] = []
    warnings: list[str] = []
    placed_by_key: dict[str, SceneObject] = {}

    # order: priority, then items whose relation target is already placed
    pending = sorted(plan.items, key=lambda i: (i.priority, i.object_key))
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
        for n in range(item.count):
            candidates: list[tuple[Vec2, float]] = []
            rel = item.relation
            target = placed_by_key.get(rel.target_key) if (rel and rel.target_key) else None
            if rel and target is not None and rel.type != "against_wall":
                candidates += _relation_candidates(target, dims, rel.type, n, item.count, room)  # type: ignore[arg-type]
            if item.semantic_type == "rug" and not candidates:
                c = geo.polygon_centroid(room.boundary)
                candidates.append((c, 0.0))
            candidates += _wall_aligned_candidates(working, room, dims[0], dims[2])

            placed: Optional[SceneObject] = None
            for pos, rot in candidates:
                y = room.floor_height if decision.mount == "floor" else (room.ceiling_height - decision.dimensions[1] if decision.mount == "ceiling" else 1.4)
                candidate = SceneObject(
                    semantic_type=item.semantic_type,
                    asset_id=decision.asset_id,
                    room_id=room.room_id,
                    position=(round(pos[0], 3), round(y, 3), round(pos[1], 3)),
                    rotation_y=round(rot % (2 * math.pi), 4),
                    scale=decision.scale,
                    dimensions=decision.dimensions,
                    color=decision.color,
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

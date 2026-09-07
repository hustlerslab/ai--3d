"""Walkthrough service — camera intelligence over the canonical scene.

Provides:
  * guided tour path: an ordered set of camera keyframes that visits every
    room, passing through doors between adjacent rooms
  * first-person spawn point: a guaranteed-clear standing position
  * position validation: is a proposed camera position walkable?

All geometry is deterministic and derived from the scene — nothing here
mutates it. Camera state itself stays frontend state (plan §36).
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

from ..scene.schema import Opening, OpeningType, Room, Scene, Vec3
from ..spatial import geometry as geo
from ..spatial.validation import object_footprint

EYE_HEIGHT = 1.6
PERSON_RADIUS = 0.3


class TourKeyframe(BaseModel):
    position: Vec3
    look_at: Vec3
    duration: float  # seconds spent traveling TO this keyframe
    room_id: Optional[str] = None
    label: str = ""


class TourPath(BaseModel):
    scene_id: str
    keyframes: list[TourKeyframe]
    total_duration: float
    room_order: list[str]


class PositionCheck(BaseModel):
    valid: bool
    reason: Optional[str] = None
    room_id: Optional[str] = None
    corrected: Optional[Vec3] = None


# ── Position validation ─────────────────────────────────────────────────


def _room_at(scene: Scene, p: geo.Vec2) -> Optional[Room]:
    for room in scene.rooms:
        if geo.point_inside_polygon(p, room.boundary):
            return room
    return None


def _door_spans(scene: Scene) -> list[tuple[geo.Vec2, geo.Vec2, float]]:
    """(door_center, wall_direction, half_width) for each door."""
    spans = []
    for opening in scene.openings:
        if opening.type != OpeningType.DOOR:
            continue
        wall = scene.wall(opening.wall_id)
        if wall is None:
            continue
        length = geo.distance(wall.start, wall.end)
        if length < 1e-9:
            continue
        t = opening.position / length
        center = geo.segment_lerp(wall.start, wall.end, t)
        direction = (
            (wall.end[0] - wall.start[0]) / length,
            (wall.end[1] - wall.start[1]) / length,
        )
        spans.append((center, direction, opening.width / 2.0))
    return spans


def _near_door(scene: Scene, p: geo.Vec2, slack: float = 0.4) -> bool:
    for center, direction, half_width in _door_spans(scene):
        along = abs(
            (p[0] - center[0]) * direction[0] + (p[1] - center[1]) * direction[1]
        )
        across = abs(
            -(p[0] - center[0]) * direction[1] + (p[1] - center[1]) * direction[0]
        )
        if along <= half_width and across <= slack + PERSON_RADIUS:
            return True
    return False


def check_position(scene: Scene, x: float, z: float) -> PositionCheck:
    p = (x, z)
    room = _room_at(scene, p)
    if room is None:
        if _near_door(scene, p):
            return PositionCheck(valid=True, room_id=None)
        return PositionCheck(valid=False, reason="OUTSIDE_ROOMS")

    # Walls block movement — unless standing in a doorway.
    for wall in scene.walls:
        dist = geo.point_segment_distance(p, wall.start, wall.end)
        if dist < wall.thickness / 2.0 + PERSON_RADIUS:
            if not _near_door(scene, p):
                return PositionCheck(
                    valid=False, reason="COLLIDES_WALL", room_id=room.room_id
                )

    # Furniture blocks movement (flat items like rugs do not).
    for obj in scene.objects:
        if obj.dimensions[1] * obj.scale[1] <= 0.1:
            continue
        footprint = object_footprint(obj)
        expanded = _expand_polygon(footprint, PERSON_RADIUS)
        if geo.point_inside_polygon(p, expanded):
            return PositionCheck(
                valid=False, reason="COLLIDES_OBJECT", room_id=room.room_id
            )

    return PositionCheck(valid=True, room_id=room.room_id)


def _expand_polygon(poly: list[geo.Vec2], margin: float) -> list[geo.Vec2]:
    cx, cz = geo.polygon_centroid(poly)
    out = []
    for x, z in poly:
        dx, dz = x - cx, z - cz
        length = math.hypot(dx, dz)
        if length < 1e-9:
            out.append((x, z))
        else:
            factor = (length + margin) / length
            out.append((cx + dx * factor, cz + dz * factor))
    return out


# ── Spawn ───────────────────────────────────────────────────────────────


def spawn_point(scene: Scene) -> tuple[Vec3, Vec3]:
    """A clear standing position plus an initial look target.

    Tries each room centroid, then a coarse grid, largest rooms first.
    """
    rooms = sorted(scene.rooms, key=lambda r: -geo.polygon_area(r.boundary))
    for room in rooms:
        candidates = [geo.polygon_centroid(room.boundary)]
        candidates += _grid_points(room, step=0.5)
        for c in candidates:
            if check_position(scene, c[0], c[1]).valid:
                look = _room_look_target(scene, room, c)
                return (c[0], EYE_HEIGHT, c[1]), look
    # Degenerate scene — stand at origin.
    return (0.0, EYE_HEIGHT, 0.0), (0.0, EYE_HEIGHT, -1.0)


def _grid_points(room: Room, step: float) -> list[geo.Vec2]:
    xs = [p[0] for p in room.boundary]
    zs = [p[1] for p in room.boundary]
    points = []
    x = min(xs) + step
    while x < max(xs):
        z = min(zs) + step
        while z < max(zs):
            if geo.point_inside_polygon((x, z), room.boundary):
                points.append((x, z))
            z += step
        x += step
    # Deterministic order: nearest to centroid first.
    centroid = geo.polygon_centroid(room.boundary)
    points.sort(key=lambda p: geo.distance(p, centroid))
    return points


def _room_look_target(scene: Scene, room: Room, from_point: geo.Vec2) -> Vec3:
    """Look toward the room's most interesting content: its largest object,
    else the farthest boundary corner."""
    objs = [o for o in scene.objects if o.room_id == room.room_id]
    if objs:
        biggest = max(objs, key=lambda o: o.dimensions[0] * o.dimensions[2])
        return (biggest.position[0], 1.1, biggest.position[2])
    corner = max(room.boundary, key=lambda c: geo.distance(c, from_point))
    return (corner[0], EYE_HEIGHT, corner[1])


# ── Guided tour ─────────────────────────────────────────────────────────


def _shared_door(scene: Scene, room_a: Room, room_b: Room) -> Optional[Opening]:
    """A door whose wall touches both room boundaries (heuristic: door center
    within tolerance of both polygons)."""
    for opening in scene.openings:
        if opening.type != OpeningType.DOOR:
            continue
        wall = scene.wall(opening.wall_id)
        if wall is None:
            continue
        length = geo.distance(wall.start, wall.end)
        if length < 1e-9:
            continue
        center = geo.segment_lerp(wall.start, wall.end, opening.position / length)
        tol = wall.thickness + 0.3
        if geo.point_inside_polygon(center, room_a.boundary, tol) and geo.point_inside_polygon(
            center, room_b.boundary, tol
        ):
            return opening
    return None


def _door_center(scene: Scene, opening: Opening) -> Optional[geo.Vec2]:
    wall = scene.wall(opening.wall_id)
    if wall is None:
        return None
    length = geo.distance(wall.start, wall.end)
    if length < 1e-9:
        return None
    return geo.segment_lerp(wall.start, wall.end, opening.position / length)


def _clear_point_in_room(scene: Scene, room: Room) -> geo.Vec2:
    centroid = geo.polygon_centroid(room.boundary)
    if check_position(scene, centroid[0], centroid[1]).valid:
        return centroid
    for p in _grid_points(room, step=0.5):
        if check_position(scene, p[0], p[1]).valid:
            return p
    return centroid


def generate_tour(scene: Scene, seconds_per_room: float = 6.0) -> TourPath:
    keyframes: list[TourKeyframe] = []
    rooms = sorted(scene.rooms, key=lambda r: -geo.polygon_area(r.boundary))
    if not rooms:
        return TourPath(scene_id=scene.scene_id, keyframes=[], total_duration=0, room_order=[])

    # Greedy room ordering: start with the largest, then always move to the
    # nearest unvisited room (prefer ones connected by a door).
    ordered = [rooms[0]]
    remaining = rooms[1:]
    while remaining:
        current = ordered[-1]
        connected = [r for r in remaining if _shared_door(scene, current, r)]
        pool = connected or remaining
        cur_c = geo.polygon_centroid(current.boundary)
        nxt = min(pool, key=lambda r: geo.distance(geo.polygon_centroid(r.boundary), cur_c))
        ordered.append(nxt)
        remaining.remove(nxt)

    total = 0.0
    for i, room in enumerate(ordered):
        stand = _clear_point_in_room(scene, room)
        look = _room_look_target(scene, room, stand)

        # Travel through the connecting door when there is one.
        if i > 0:
            door = _shared_door(scene, ordered[i - 1], room)
            if door is not None:
                center = _door_center(scene, door)
                if center is not None:
                    travel = 1.6
                    keyframes.append(
                        TourKeyframe(
                            position=(center[0], EYE_HEIGHT, center[1]),
                            look_at=(stand[0], EYE_HEIGHT, stand[1]),
                            duration=travel,
                            room_id=room.room_id,
                            label=f"Through to {room.name}",
                        )
                    )
                    total += travel

        arrive = 2.0 if i > 0 else 0.0
        keyframes.append(
            TourKeyframe(
                position=(stand[0], EYE_HEIGHT, stand[1]),
                look_at=look,
                duration=arrive,
                room_id=room.room_id,
                label=room.name,
            )
        )
        total += arrive

        # Pan around the room: look at up to three furniture pieces, largest first.
        # Pan targets: the three largest *standing* pieces. Rugs and other flat
        # objects would drag the camera to the floor; wall/ceiling mounts are
        # not where a visitor looks first either.
        objs = sorted(
            (
                o
                for o in scene.objects
                if o.room_id == room.room_id and o.mount == "floor" and o.dimensions[1] * o.scale[1] >= 0.3
            ),
            key=lambda o: -(o.dimensions[0] * o.dimensions[2]),
        )[:3]
        dwell = max(seconds_per_room - arrive, 2.0)
        per_target = dwell / max(len(objs), 1)
        for obj in objs:
            keyframes.append(
                TourKeyframe(
                    position=(stand[0], EYE_HEIGHT, stand[1]),
                    look_at=(obj.position[0], max(0.8, min(1.5, obj.dimensions[1] * obj.scale[1] * 0.7)), obj.position[2]),
                    duration=per_target,
                    room_id=room.room_id,
                    label=obj.semantic_type.replace("_", " "),
                )
            )
            total += per_target
        if not objs:
            keyframes.append(
                TourKeyframe(
                    position=(stand[0], EYE_HEIGHT, stand[1]),
                    look_at=look,
                    duration=dwell,
                    room_id=room.room_id,
                    label=room.name,
                )
            )
            total += dwell

    return TourPath(
        scene_id=scene.scene_id,
        keyframes=keyframes,
        total_duration=round(total, 2),
        room_order=[r.room_id for r in ordered],
    )

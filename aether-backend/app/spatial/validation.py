"""Scene validation — the gate every mutation passes before commit.

Hard constraints (violations block commit):
  H1  object footprint inside its room boundary
  H2  object does not intersect any wall
  H3  object does not intersect another object
  H4  object does not block a door clearance zone
  H5  referenced room/wall/asset ids exist

`validate_scene` returns a list of violations; empty list == valid.
Deterministic: same scene in, same violations out.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..scene.schema import Opening, OpeningType, Scene, SceneObject
from . import geometry as geo

# A person needs this much clear space in front of / behind a door.
DOOR_CLEARANCE_DEPTH = 0.75
BOUNDARY_TOLERANCE = 0.09  # lets furniture sit flush against walls


class Violation(BaseModel):
    code: str
    severity: str = "hard"
    message: str
    object_id: str | None = None
    related_id: str | None = None


def object_footprint(obj: SceneObject) -> list[geo.Vec2]:
    width = obj.dimensions[0] * obj.scale[0]
    depth = obj.dimensions[2] * obj.scale[2]
    return geo.footprint_corners(
        (obj.position[0], obj.position[2]), width, depth, obj.rotation_y
    )


def door_clearance_rects(scene: Scene, opening: Opening) -> list[list[geo.Vec2]]:
    """Two rectangles (either side of the wall) that must stay clear."""
    wall = scene.wall(opening.wall_id)
    if wall is None:
        return []
    length = geo.distance(wall.start, wall.end)
    if length < 1e-9:
        return []
    t = max(0.0, min(1.0, opening.position / length))
    center = geo.segment_lerp(wall.start, wall.end, t)
    dx = (wall.end[0] - wall.start[0]) / length
    dz = (wall.end[1] - wall.start[1]) / length
    nx, nz = -dz, dx
    half_w = opening.width / 2.0
    rects: list[list[geo.Vec2]] = []
    for side in (1.0, -1.0):
        offset = side * (wall.thickness / 2.0 + DOOR_CLEARANCE_DEPTH / 2.0)
        c = (center[0] + nx * offset, center[1] + nz * offset)
        rects.append(
            [
                (c[0] - dx * half_w - nx * DOOR_CLEARANCE_DEPTH / 2, c[1] - dz * half_w - nz * DOOR_CLEARANCE_DEPTH / 2),
                (c[0] + dx * half_w - nx * DOOR_CLEARANCE_DEPTH / 2, c[1] + dz * half_w - nz * DOOR_CLEARANCE_DEPTH / 2),
                (c[0] + dx * half_w + nx * DOOR_CLEARANCE_DEPTH / 2, c[1] + dz * half_w + nz * DOOR_CLEARANCE_DEPTH / 2),
                (c[0] - dx * half_w + nx * DOOR_CLEARANCE_DEPTH / 2, c[1] - dz * half_w + nz * DOOR_CLEARANCE_DEPTH / 2),
            ]
        )
    return rects


def validate_object(scene: Scene, obj: SceneObject) -> list[Violation]:
    violations: list[Violation] = []
    footprint = object_footprint(obj)

    # H5 — referenced room exists
    room = scene.room(obj.room_id)
    if room is None:
        return [
            Violation(
                code="ROOM_NOT_FOUND",
                message=f"Object {obj.object_id} references missing room {obj.room_id}.",
                object_id=obj.object_id,
            )
        ]

    # H1 — inside room boundary
    for corner in footprint:
        if not geo.point_inside_polygon(corner, room.boundary, BOUNDARY_TOLERANCE):
            violations.append(
                Violation(
                    code="OUTSIDE_ROOM",
                    message=f"{obj.semantic_type} extends outside room '{room.name}'.",
                    object_id=obj.object_id,
                    related_id=room.room_id,
                )
            )
            break

    # H2 — wall intersection (openings do not exempt furniture)
    for wall in scene.walls:
        rect = geo.wall_rectangle(wall.start, wall.end, wall.thickness)
        if geo.convex_polygons_overlap(footprint, rect):
            violations.append(
                Violation(
                    code="COLLIDES_WALL",
                    message=f"{obj.semantic_type} intersects a wall.",
                    object_id=obj.object_id,
                    related_id=wall.wall_id,
                )
            )
            break

    # Ceiling- and wall-mounted items (pendants, art, mirrors) are not floor
    # obstacles: they cannot collide with furniture or block a doorway.
    if obj.mount != "floor":
        return violations

    # H3 — object-object collision
    for other in scene.objects:
        if other.object_id == obj.object_id:
            continue
        if other.mount != "floor":
            continue
        # A rug can sit under furniture; skip flat objects (height <= 5 cm).
        if obj.dimensions[1] * obj.scale[1] <= 0.05 or other.dimensions[1] * other.scale[1] <= 0.05:
            continue
        if geo.convex_polygons_overlap(footprint, object_footprint(other)):
            violations.append(
                Violation(
                    code="COLLIDES_OBJECT",
                    message=f"{obj.semantic_type} collides with {other.semantic_type}.",
                    object_id=obj.object_id,
                    related_id=other.object_id,
                )
            )
            break

    # H4 — door clearance
    for opening in scene.openings:
        if opening.type != OpeningType.DOOR:
            continue
        for rect in door_clearance_rects(scene, opening):
            if geo.convex_polygons_overlap(footprint, rect):
                violations.append(
                    Violation(
                        code="BLOCKS_DOOR",
                        message=f"{obj.semantic_type} blocks a door clearance zone.",
                        object_id=obj.object_id,
                        related_id=opening.opening_id,
                    )
                )
                break
        else:
            continue
        break

    return violations


def validate_scene(scene: Scene) -> list[Violation]:
    violations: list[Violation] = []

    # Topology: openings must reference existing walls and fit within them.
    for opening in scene.openings:
        wall = scene.wall(opening.wall_id)
        if wall is None:
            violations.append(
                Violation(
                    code="ORPHAN_OPENING",
                    message=f"Opening {opening.opening_id} references missing wall.",
                    related_id=opening.wall_id,
                )
            )
            continue
        length = geo.distance(wall.start, wall.end)
        if opening.position - opening.width / 2 < -1e-6 or opening.position + opening.width / 2 > length + 1e-6:
            violations.append(
                Violation(
                    code="OPENING_OUTSIDE_WALL",
                    message=f"Opening {opening.opening_id} does not fit inside its wall.",
                    related_id=wall.wall_id,
                )
            )

    for room in scene.rooms:
        if len(room.boundary) < 3 or geo.polygon_area(room.boundary) < 1e-6:
            violations.append(
                Violation(
                    code="INVALID_ROOM_POLYGON",
                    message=f"Room '{room.name}' has a degenerate boundary.",
                    related_id=room.room_id,
                )
            )

    for obj in scene.objects:
        violations.extend(validate_object(scene, obj))

    return violations

"""P2 clearance engine: collision-free is not the same as usable.

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. Reuses the same three geometry primitives P1 reused
(`footprint_corners`, `convex_polygons_overlap`, `point_segment_distance`)
plus `point_inside_polygon`; adds no new collision algorithm, no dependency.
See docs/spatial_architecture/clearance.md for the research behind every
threshold and representation choice below - nothing here is invented on the
spot.

FOUR SEPARATE CHECKS, ONE VIOLATION SHAPE. `pairwise_clearance_violations`
(scalar minimum distance between two footprint polygons, CLEARANCE),
`functional_clearance_violations` (a wardrobe's door-swing envelope,
FUNCTIONAL), `door_swing_violations` (a door's own swing arc, FUNCTIONAL),
and `circulation_violations` (grid + widest-path, CIRCULATION) all emit the
same `ClearanceViolation` - see docs/spatial_architecture/clearance.md P2.2
for why `severity` and `category` are two small attributes on one type
rather than four parallel violation classes.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Optional


from app.scene.schema import OpeningType, Scene, SceneObject
from app.spatial.geometry import (
    Vec2, convex_polygons_overlap, footprint_corners,
    point_inside_polygon, point_segment_distance, polygon_centroid,
    wall_rectangle)
from app.spatial.validation import object_footprint

# -- P2.3 policy, every figure sourced in clearance.md ----------------------

#: (frozenset of two semantic_types) -> minimum clear gap between footprints,
#: metres. Order-independent. Only pairs with a real researched source are
#: listed - an unlisted pair emits no constraint (clearance.md P2.3).
CLEARANCE_POLICY: dict[frozenset, float] = {
    frozenset({"sofa", "coffee_table"}): 0.30,
    frozenset({"loveseat", "coffee_table"}): 0.30,
    frozenset({"armchair", "coffee_table"}): 0.30,
    frozenset({"bed", "wardrobe"}): 0.60,
    frozenset({"bed", "bedside_table"}): 0.60,
    frozenset({"kitchen_counter", "kitchen_island"}): 1.05,
    frozenset({"kitchen_counter", "kitchen_counter"}): 1.05,
    frozenset({"kitchen_island", "bar_counter"}): 1.05,
}

#: front-envelope depth for an object's operating clearance, metres.
FUNCTIONAL_ENVELOPE_POLICY: dict[str, float] = {"wardrobe": 0.90}

PRIMARY_WALKWAY_MIN_M = 0.90
SECONDARY_WALKWAY_MIN_M = 0.65
#: half a person's shoulder width - the Minkowski "shrink the walker to a
#: point, grow the obstacles" radius (clearance.md P2.1), NOT a walkway width.
PEDESTRIAN_INFLATION_M = 0.275

GRID_CELL_M = 0.05


@dataclass(frozen=True)
class ClearanceViolation:
    subject_id: str
    target_id: str
    category: str        # "CLEARANCE" | "FUNCTIONAL" | "CIRCULATION"
    constraint: str
    required_m: float
    actual_m: float
    deficit_m: float
    severity: str         # "hard" | "soft"
    coordinate_frame: str = "floor_plan"


def _polygon_distance(a: list[Vec2], b: list[Vec2]) -> float:
    """Minimum distance between two convex, non-overlapping polygons: the
    minimum over every (vertex, opposite edge) pair - exact for convex
    polygons, reusing the existing `point_segment_distance` primitive."""
    best = math.inf
    for poly, other in ((a, b), (b, a)):
        n = len(other)
        for p in poly:
            for i in range(n):
                best = min(best, point_segment_distance(p, other[i], other[(i + 1) % n]))
    return best


def _front_envelope(obj: SceneObject, depth_m: float) -> list[Vec2]:
    """A rectangle the object's own width, `depth_m` deep, immediately in
    front of it - "front" = local +Z, the same local axis `footprint_corners`
    rotates (clearance.md P2.1: an assumed convention, no per-object hinge
    evidence exists, which is why functional violations default to soft)."""
    w = obj.dimensions[0] * obj.scale[0]
    d = obj.dimensions[2] * obj.scale[2]
    front = (math.sin(obj.rotation_y), math.cos(obj.rotation_y))
    cx = obj.position[0] + front[0] * (d / 2.0 + depth_m / 2.0)
    cz = obj.position[2] + front[1] * (d / 2.0 + depth_m / 2.0)
    return footprint_corners((cx, cz), w, depth_m, obj.rotation_y)


def pairwise_clearance_violations(scene: Scene) -> list[ClearanceViolation]:
    """CLEARANCE: two floor-mounted objects closer than their policy minimum,
    but not overlapping (an overlap is P1's COLLIDES_OBJECT, not this)."""
    out: list[ClearanceViolation] = []
    objs = [o for o in scene.objects if o.mount == "floor"]
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            required = CLEARANCE_POLICY.get(frozenset({a.semantic_type, b.semantic_type}))
            if required is None:
                continue
            fa, fb = object_footprint(a), object_footprint(b)
            if convex_polygons_overlap(fa, fb):
                continue  # a collision, not a clearance deficit - P1's job
            actual = _polygon_distance(fa, fb)
            if actual < required:
                out.append(ClearanceViolation(
                    a.object_id, b.object_id, "CLEARANCE",
                    f"{a.semantic_type}<->{b.semantic_type} minimum clearance",
                    round(required, 4), round(actual, 4), round(required - actual, 4), "soft"))
    return out


def functional_clearance_violations(scene: Scene) -> list[ClearanceViolation]:
    """FUNCTIONAL: an object's front operating envelope (e.g. a wardrobe's
    door swing) overlapped by another floor-mounted object's footprint."""
    out: list[ClearanceViolation] = []
    objs = [o for o in scene.objects if o.mount == "floor"]
    for obj in objs:
        depth = FUNCTIONAL_ENVELOPE_POLICY.get(obj.semantic_type)
        if depth is None:
            continue
        envelope = _front_envelope(obj, depth)
        for other in objs:
            if other.object_id == obj.object_id:
                continue
            if convex_polygons_overlap(envelope, object_footprint(other)):
                out.append(ClearanceViolation(
                    obj.object_id, other.object_id, "FUNCTIONAL",
                    f"{obj.semantic_type} operating envelope",
                    depth, 0.0, depth, "soft"))
    return out


def _door_swing_polygon(scene: Scene, opening, segments: int = 6) -> Optional[list[Vec2]]:
    """A convex circular-sector polygon: hinge at the opening's wall-start
    side, sweeping 90 degrees from along-the-wall (closed) to perpendicular-
    into-the-room (open) - the one deterministic default clearance.md P2.1
    adopts, since no per-door hinge/swing evidence exists in the pipeline."""
    wall = scene.wall(opening.wall_id)
    if wall is None:
        return None
    dx, dz = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
    length = math.hypot(dx, dz) or 1.0
    tangent = (dx / length, dz / length)
    hinge = (wall.start[0] + tangent[0] * (opening.position - opening.width / 2.0),
             wall.start[1] + tangent[1] * (opening.position - opening.width / 2.0))
    room = next((r for r in scene.rooms), None)
    perp = (-tangent[1], tangent[0])
    if room is not None and room.boundary:
        cx, cz = polygon_centroid(room.boundary)
        if (cx - hinge[0]) * perp[0] + (cz - hinge[1]) * perp[1] < 0:
            perp = (-perp[0], -perp[1])
    radius = opening.width
    points = [hinge]
    for i in range(segments + 1):
        angle = (math.pi / 2.0) * (i / segments)
        d = (tangent[0] * math.cos(angle) + perp[0] * math.sin(angle),
             tangent[1] * math.cos(angle) + perp[1] * math.sin(angle))
        points.append((hinge[0] + d[0] * radius, hinge[1] + d[1] * radius))
    return points


def door_swing_violations(scene: Scene) -> list[ClearanceViolation]:
    """FUNCTIONAL: a door's own swing arc blocked by floor-mounted furniture."""
    out: list[ClearanceViolation] = []
    objs = [o for o in scene.objects if o.mount == "floor"]
    for opening in scene.openings:
        if opening.type != OpeningType.DOOR:
            continue
        arc = _door_swing_polygon(scene, opening)
        if arc is None:
            continue
        for obj in objs:
            if convex_polygons_overlap(arc, object_footprint(obj)):
                out.append(ClearanceViolation(
                    f"door:{opening.opening_id}", obj.object_id, "FUNCTIONAL",
                    "door swing arc", opening.width, 0.0, opening.width, "soft"))
    return out


def _clearance_field(point: Vec2, objs: list[SceneObject], walls, wall_thickness: float) -> float:
    """Distance from `point` to the nearest floor-mounted footprint or wall
    (0.0 if inside one) - the distance-transform value the widest-path search
    below runs on, computed on demand per cell rather than as a stored grid,
    since Allure's room scale makes recomputation cheap and avoids a second
    grid data structure."""
    best = math.inf
    for obj in objs:
        poly = object_footprint(obj)
        if point_inside_polygon(point, poly):
            return 0.0
        n = len(poly)
        for i in range(n):
            best = min(best, point_segment_distance(point, poly[i], poly[(i + 1) % n]))
    for w in walls:
        rect = wall_rectangle(w.start, w.end, w.thickness)
        if point_inside_polygon(point, rect):
            return 0.0
        n = len(rect)
        for i in range(n):
            best = min(best, point_segment_distance(point, rect[i], rect[(i + 1) % n]))
    return best


def circulation_violations(scene: Scene, entrance_xz: Vec2) -> list[ClearanceViolation]:
    """CIRCULATION: for every floor-mounted object, is it reachable from
    `entrance_xz` at all (hard, if not) and if so, how wide is the widest
    available path (soft, if narrower than SECONDARY_WALKWAY_MIN_M)?

    Grid + widest-path (clearance.md P2.1): a 0.05 m grid over the room's
    bounding box, a cell is passable if it is inside the room boundary and at
    least PEDESTRIAN_INFLATION_M from every obstacle (the Minkowski "shrink
    the walker to a point" step), and a Dijkstra-style search from the
    entrance maximizes the *minimum* clearance-field value along each path
    (the textbook widest-path / bottleneck-shortest-path algorithm) rather
    than plain BFS, so the reported width is a real bottleneck, not a guess.
    """
    room = scene.rooms[0] if scene.rooms else None
    if room is None or not room.boundary:
        return []
    objs = [o for o in scene.objects if o.mount == "floor"]
    xs = [p[0] for p in room.boundary]
    zs = [p[1] for p in room.boundary]
    nx = max(1, int((max(xs) - min(xs)) / GRID_CELL_M) + 1)
    nz = max(1, int((max(zs) - min(zs)) / GRID_CELL_M) + 1)

    def cell_center(i: int, j: int) -> Vec2:
        return (min(xs) + (i + 0.5) * GRID_CELL_M, min(zs) + (j + 0.5) * GRID_CELL_M)

    def passable(i: int, j: int) -> Optional[float]:
        p = cell_center(i, j)
        if not point_inside_polygon(p, room.boundary):
            return None
        field = _clearance_field(p, objs, scene.walls, 0.15)
        return field if field >= PEDESTRIAN_INFLATION_M else None

    def nearest_cell(xz: Vec2) -> tuple[int, int]:
        return (int(round((xz[0] - min(xs)) / GRID_CELL_M)), int(round((xz[1] - min(zs)) / GRID_CELL_M)))

    start = nearest_cell(entrance_xz)
    best_width: dict[tuple, float] = {}
    field0 = passable(*start)
    if field0 is None:
        # search a small ring for the nearest passable cell to the entrance
        for r in range(1, 6):
            found = None
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    f = passable(start[0] + di, start[1] + dj)
                    if f is not None:
                        found = ((start[0] + di, start[1] + dj), f)
                        break
                if found:
                    break
            if found:
                start, field0 = found
                break
    if field0 is None:
        # The entrance itself has no usable floor nearby - the room fails
        # circulation entirely. Silently returning [] here would make an
        # impossible room look like a clean report; report it as the single
        # most severe circulation failure instead of going quiet.
        return [ClearanceViolation("entrance", "room", "CIRCULATION",
                                   "entrance has no reachable floor space",
                                   0.0, 0.0, 0.0, "hard")]

    heap = [(-field0, start)]
    best_width[start] = field0
    while heap:
        neg_w, cell = heapq.heappop(heap)
        w = -neg_w
        if w < best_width.get(cell, -1):
            continue
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (cell[0] + di, cell[1] + dj)
            if not (0 <= nb[0] < nx and 0 <= nb[1] < nz):
                continue
            f = passable(*nb)
            if f is None:
                continue
            new_w = min(w, f)
            if new_w > best_width.get(nb, -1.0):
                best_width[nb] = new_w
                heapq.heappush(heap, (-new_w, nb))

    out: list[ClearanceViolation] = []
    for obj in objs:
        poly = object_footprint(obj)
        cx, cz = polygon_centroid(poly)
        w = obj.dimensions[0] * obj.scale[0]
        d = obj.dimensions[2] * obj.scale[2]
        # Sample outside the object's OWN bounding circle plus the pedestrian
        # inflation margin - otherwise a ring point can land inside the
        # object's own inflated halo and every direction reads "blocked",
        # which would flag every object as circulation-unreachable to itself.
        ring_radius = 0.5 * math.hypot(w, d) + PEDESTRIAN_INFLATION_M + 0.05
        ring = [(cx + math.cos(a) * ring_radius, cz + math.sin(a) * ring_radius) for a in
                (i * math.pi / 4.0 for i in range(8))]
        reached = [best_width[c] for c in (nearest_cell(p) for p in ring) if c in best_width]
        if not reached:
            out.append(ClearanceViolation(
                "entrance", obj.object_id, "CIRCULATION", "reachability",
                0.0, 0.0, 0.0, "hard"))
            continue
        corridor_width = round(max(reached) * 2.0, 4)
        if corridor_width < SECONDARY_WALKWAY_MIN_M:
            out.append(ClearanceViolation(
                "entrance", obj.object_id, "CIRCULATION", "widest available path",
                SECONDARY_WALKWAY_MIN_M, corridor_width,
                round(SECONDARY_WALKWAY_MIN_M - corridor_width, 4), "soft"))
    return out


def all_clearance_violations(scene: Scene, entrance_xz: Optional[Vec2] = None) -> list[ClearanceViolation]:
    out = pairwise_clearance_violations(scene) + functional_clearance_violations(scene) + door_swing_violations(scene)
    if entrance_xz is not None:
        out += circulation_violations(scene, entrance_xz)
    return out


__all__ = ["ClearanceViolation", "CLEARANCE_POLICY", "FUNCTIONAL_ENVELOPE_POLICY",
           "PRIMARY_WALKWAY_MIN_M", "SECONDARY_WALKWAY_MIN_M", "PEDESTRIAN_INFLATION_M",
           "pairwise_clearance_violations", "functional_clearance_violations",
           "door_swing_violations", "circulation_violations", "all_clearance_violations"]

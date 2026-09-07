"""Deterministic 2D geometry kernel (plan view, XZ plane).

Pure functions only — no scene knowledge, no randomness, no IO.
"""
from __future__ import annotations

import math

Vec2 = tuple[float, float]
EPS = 1e-9


def distance(a: Vec2, b: Vec2) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def rotate_point(p: Vec2, angle: float, origin: Vec2 = (0.0, 0.0)) -> Vec2:
    c, s = math.cos(angle), math.sin(angle)
    x, z = p[0] - origin[0], p[1] - origin[1]
    return (origin[0] + x * c - z * s, origin[1] + x * s + z * c)


def polygon_area(poly: list[Vec2]) -> float:
    area = 0.0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        area += x1 * z2 - x2 * z1
    return abs(area) / 2.0


def polygon_centroid(poly: list[Vec2]) -> Vec2:
    signed = 0.0
    cx = cz = 0.0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        cross = x1 * z2 - x2 * z1
        signed += cross
        cx += (x1 + x2) * cross
        cz += (z1 + z2) * cross
    if abs(signed) < EPS:
        xs = [p[0] for p in poly]
        zs = [p[1] for p in poly]
        return (sum(xs) / n, sum(zs) / n)
    signed *= 0.5
    return (cx / (6 * signed), cz / (6 * signed))


def point_inside_polygon(p: Vec2, poly: list[Vec2], tolerance: float = 0.0) -> bool:
    """Ray-cast test. `tolerance` > 0 also accepts points within that distance
    of the boundary (used so furniture flush against a wall still counts)."""
    x, z = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        if (z1 > z) != (z2 > z):
            x_int = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
            if x < x_int:
                inside = not inside
    if inside:
        return True
    if tolerance > 0:
        for i in range(n):
            if point_segment_distance(p, poly[i], poly[(i + 1) % n]) <= tolerance:
                return True
    return False


def point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    ax, az = a
    bx, bz = b
    px, pz = p
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    if length_sq < EPS:
        return distance(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length_sq))
    return distance(p, (ax + t * dx, az + t * dz))


def project_onto_segment(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Parametric t in [0,1] of the closest point on segment ab to p."""
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    if length_sq < EPS:
        return 0.0
    return max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - az) * dz) / length_sq))


def segments_intersect(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2) -> bool:
    def orient(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_seg(p: Vec2, q: Vec2, r: Vec2) -> bool:
        return (
            min(p[0], r[0]) - EPS <= q[0] <= max(p[0], r[0]) + EPS
            and min(p[1], r[1]) - EPS <= q[1] <= max(p[1], r[1]) + EPS
        )

    o1, o2 = orient(a1, a2, b1), orient(a1, a2, b2)
    o3, o4 = orient(b1, b2, a1), orient(b1, b2, a2)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)):
        return True
    if abs(o1) < EPS and on_seg(a1, b1, a2):
        return True
    if abs(o2) < EPS and on_seg(a1, b2, a2):
        return True
    if abs(o3) < EPS and on_seg(b1, a1, b2):
        return True
    if abs(o4) < EPS and on_seg(b1, a2, b2):
        return True
    return False


# ── Oriented rectangles (object footprints) ─────────────────────────────


def footprint_corners(
    center: Vec2, width: float, depth: float, rotation: float
) -> list[Vec2]:
    """Corners of a width×depth rectangle centered at `center`, rotated by yaw.

    Note: a positive Three.js Y-rotation is counter-clockwise seen from above
    (+Y down at the XZ plane); this uses the same convention so backend and
    renderer agree.
    """
    hw, hd = width / 2.0, depth / 2.0
    local = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    c, s = math.cos(-rotation), math.sin(-rotation)
    return [(center[0] + x * c - z * s, center[1] + x * s + z * c) for x, z in local]


def _project_polygon(axis: Vec2, poly: list[Vec2]) -> tuple[float, float]:
    dots = [p[0] * axis[0] + p[1] * axis[1] for p in poly]
    return min(dots), max(dots)


def convex_polygons_overlap(a: list[Vec2], b: list[Vec2]) -> bool:
    """Separating Axis Theorem for two convex polygons. Touching edges
    (zero-area overlap) do NOT count as overlap."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, z1 = poly[i]
            x2, z2 = poly[(i + 1) % n]
            axis = (-(z2 - z1), x2 - x1)
            length = math.hypot(*axis)
            if length < EPS:
                continue
            axis = (axis[0] / length, axis[1] / length)
            min_a, max_a = _project_polygon(axis, a)
            min_b, max_b = _project_polygon(axis, b)
            if max_a <= min_b + 1e-6 or max_b <= min_a + 1e-6:
                return False
    return True


def wall_rectangle(start: Vec2, end: Vec2, thickness: float) -> list[Vec2]:
    """The wall's plan-view footprint as a rectangle around its centerline."""
    dx, dz = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dz)
    if length < EPS:
        return [start, start, start, start]
    nx, nz = -dz / length * thickness / 2.0, dx / length * thickness / 2.0
    return [
        (start[0] + nx, start[1] + nz),
        (end[0] + nx, end[1] + nz),
        (end[0] - nx, end[1] - nz),
        (start[0] - nx, start[1] - nz),
    ]


def segment_lerp(a: Vec2, b: Vec2, t: float) -> Vec2:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

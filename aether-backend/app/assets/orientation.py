"""P1-ASSET-005: measure an asset's forward axis at ingest.

Canonical convention (normalization.py): up = +Y, forward = -Z. The yaw
returned here is the rotation `normalization.plan` bakes into the normalized
file so the model's front faces -Z. Zero means either "already canonical" or
"nothing readable" - a wrong correction is worse than none, because the
planner's own angle is at least consistent.

This is the reading `blender/scripts/import_assets.py:_native_forward_yaw`
used to make on every build, moved to ingest so it is made once and stored.
Same rules and thresholds, in glTF's Y-up frame instead of Blender's Z-up:

  "backrest"  the tall mass sits BEHIND the seat, so forward points away from
              it - true of every chair, sofa and bench regardless of style.
  "thin"      a flat piece faces along its thinnest horizontal axis - a
              screen, a picture, a mirror. Which of the two directions along
              it is the planner's call, so only the axis is taken from the
              mesh.

One deliberate difference from the Blender version: the tall part is the
surface area ABOVE the cut plane, each triangle clipped against it, not
"faces whose centre is above the cut". On a coarse mesh the two triangles of
a quad have centroids on opposite sides of the diagonal, so whole-face
selection can take one and leave the other and invent an offset where the
geometry has none - a 12-triangle box read as needing a quarter turn.
Clipping is exact for planar faces and converges to the same answer on
dense ones.

Snapped to quarter turns on purpose. Furniture in rooms is axis-aligned, the
four-way choice is the whole question, and a continuous angle read off a
vertex cloud would wobble between ingests of the same file.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import gltf

FACING_RULE: dict[str, str] = {
    "armchair": "backrest", "chair": "backrest", "dining_chair": "backrest",
    "sofa": "backrest", "sectional": "backrest", "loveseat": "backrest",
    "bench": "backrest", "stool": "backrest", "bar_stool": "backrest",
    "rocking_chair": "backrest", "office_chair": "backrest", "accent_chair": "backrest",
    "tv": "thin", "television": "thin", "tv_unit": "thin", "wall_art": "thin",
    "mirror": "thin", "artwork": "thin",
}

#: A backrest has to be a real mass to count. Below this share of the surface
#: sitting high, the "tall part" is a cushion or an armrest and the direction
#: it implies is noise.
BACKREST_MIN_SHARE = 0.12
#: And it has to be off-centre: a symmetric piece gives a near-zero offset
#: whose direction is meaningless.
BACKREST_MIN_OFFSET = 0.06
#: The share of the height above which surface counts as "the tall part".
BACKREST_CUT = 0.55
MIN_TRIANGLES = 8

QUARTER_TURN = math.pi / 2

Point = tuple[float, float, float]


@dataclass(frozen=True)
class TallPart:
    """Where the surface above the cut plane sits, as an area-weighted centroid."""
    centroid_x: float
    centroid_z: float
    area: float
    total_area: float
    bbox_min: Point
    bbox_max: Point

    @property
    def share(self) -> float:
        return self.area / self.total_area if self.total_area > 0 else 0.0

    @property
    def size(self) -> Point:
        return tuple(self.bbox_max[i] - self.bbox_min[i] for i in range(3))  # type: ignore[return-value]


def snap_quarter(yaw: float) -> float:
    snapped = round(yaw / QUARTER_TURN) * QUARTER_TURN
    if snapped <= -math.pi + 1e-9:
        snapped = math.pi
    return 0.0 if abs(snapped) < 1e-12 else snapped


def _area_centroid(poly: list[Point]) -> tuple[float, float, float]:
    """(area, centroid_x, centroid_z) of a planar polygon, fanned from poly[0]."""
    area = 0.0
    cx = 0.0
    cz = 0.0
    a = poly[0]
    for i in range(1, len(poly) - 1):
        b, c = poly[i], poly[i + 1]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        w = 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
        area += w
        cx += w * (a[0] + b[0] + c[0]) / 3.0
        cz += w * (a[2] + b[2] + c[2]) / 3.0
    return area, cx, cz


def _clip_above(tri, cut: float) -> list[Point]:
    """The part of a triangle with y >= cut, as a polygon (0, 3 or 4 vertices)."""
    out: list[Point] = []
    n = len(tri)
    for i in range(n):
        p, q = tri[i], tri[(i + 1) % n]
        p_in, q_in = p[1] >= cut, q[1] >= cut
        if p_in:
            out.append(p)
        if p_in != q_in:
            t = (cut - p[1]) / (q[1] - p[1])
            out.append((p[0] + t * (q[0] - p[0]), cut, p[2] + t * (q[2] - p[2])))
    return out


def tall_part(doc: gltf.GltfDocument, cut_share: float = BACKREST_CUT) -> TallPart | None:
    """Read the mesh's surface above `cut_share` of its height. None when
    there is too little geometry to read anything."""
    triangles = list(gltf.world_triangles(doc))
    if len(triangles) < MIN_TRIANGLES:
        return None
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for tri in triangles:
        for p in tri:
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    cut = lo[1] + (hi[1] - lo[1]) * cut_share
    total = 0.0
    area = 0.0
    sum_x = 0.0
    sum_z = 0.0
    for tri in triangles:
        w, _, _ = _area_centroid(list(tri))
        total += w
        above = _clip_above(tri, cut)
        if len(above) >= 3:
            w, cx, cz = _area_centroid(above)
            area += w
            sum_x += cx
            sum_z += cz
    if area <= 0:
        return TallPart(0.0, 0.0, 0.0, total, tuple(lo), tuple(hi))  # type: ignore[arg-type]
    return TallPart(sum_x / area, sum_z / area, area, total, tuple(lo), tuple(hi))  # type: ignore[arg-type]


def measure_forward_yaw(doc: gltf.GltfDocument, semantic_type: str) -> float:
    """The yaw, in radians, that turns this mesh's front to face -Z."""
    rule = FACING_RULE.get(semantic_type)
    if not rule:
        return 0.0
    part = tall_part(doc)
    if part is None:
        return 0.0
    size = part.size
    if size[0] < 1e-4 or size[2] < 1e-4:
        return 0.0

    if rule == "thin":
        return 0.0 if size[2] <= size[0] else QUARTER_TURN

    if part.share < BACKREST_MIN_SHARE:
        return 0.0
    offset_x = part.centroid_x - (part.bbox_min[0] + part.bbox_max[0]) / 2.0
    offset_z = part.centroid_z - (part.bbox_min[2] + part.bbox_max[2]) / 2.0
    # Normalised against the piece's own size, so a wide sofa and a small
    # chair are judged the same way.
    if abs(offset_x) / size[0] < BACKREST_MIN_OFFSET and abs(offset_z) / size[2] < BACKREST_MIN_OFFSET:
        return 0.0

    # Forward is away from the backrest; normalization._rotate_y turns
    # (fx, fz) by this yaw onto (0, -1).
    forward_x, forward_z = -offset_x, -offset_z
    return snap_quarter(math.atan2(forward_x, -forward_z))


__all__ = ["FACING_RULE", "TallPart", "measure_forward_yaw", "snap_quarter", "tall_part"]

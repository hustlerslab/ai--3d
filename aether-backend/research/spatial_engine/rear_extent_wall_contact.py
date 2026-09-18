"""Wall contact from the object's REAR EXTENT along the wall normal.

Research only. `app/spatial/planes.py` is imported read-only and is NOT modified;
nothing in `app/` imports this file.

WHAT PHASE 3 PROVED, AND WHY THIS EXISTS. Phase 2 fixed the geometry and Phase 3
fixed the object footprint, and the wall decision still failed: false-wall 21.6%,
positive recall collapsed 54.5% -> 18.2%, balanced accuracy 48.3% (below chance),
and both grounding methods hit the same 74.7% ceiling one threshold-notch apart.
The diagnosis was that the measured quantity is wrong.

    `app.spatial.planes.wall_contact` computes

        d = percentile(|signed_distance(object points)|, 10)

    which is the object's NEAREST point to the plane, on either side of it.

Note in passing that the docstring of that function describes the value as "the
distance from the object's REAR surface"; the code computes the nearest surface.
The discrepancy is recorded in the Phase 4 report and the production module is
left untouched.

Measuring the nearest visible surface is wrong for furniture. A sofa's visible
surface is its front; its back is against the wall and is occluded. Phase 3
measured that directly: masking away the wall pixels inside the box pushed every
distance outward (positives +0.155 m, negatives +0.243 m), because the box had
been supplying wall pixels at distance ~0 and thereby getting solid objects right
for the wrong reason.

WHAT THIS MODULE MEASURES INSTEAD. The object's extent along the wall normal,
oriented so that positive points from the wall INTO THE ROOM:

        q_i = s * (n . p_i + offset)        s = +1 or -1, chosen per wall

    rear extent = percentile(q, 10)         the extremal object surface
                                            toward the wall
    gap         = max(0, rear extent)       a negative rear extent means the
                                            object reaches past the plane,
                                            which is contact, not a gap

TWO CHOICES FROZEN BEFORE ANY BENCHMARK NUMBER WAS READ.

1. THE PERCENTILE IS 10, reused from Phase 3 rather than invented. The brief's
   instruction was explicit: "If the existing Phase 3 10th-percentile convention
   can be reused by reversing the projection direction, prefer that rather than
   introducing a new arbitrary hyperparameter." The only change is that the
   projection is signed and room-oriented instead of absolute. A percentile
   SENSITIVITY sweep is computed by the benchmark as a diagnostic; it does not
   decide the gate.

2. ORIENTATION COMES FROM ROOM GEOMETRY, NOT THE CAMERA. A fitted plane's normal
   may point either way; RANSAC does not care. The interior direction is the side
   the room's own robust centroid lies on. The camera position is not used: it is
   not part of the frozen Phase 2 geometry definition, and "the side the camera is
   on" is a different question from "the side the room is on". Where the centroid
   lies too close to the plane for the sign to be safe, orientation is reported
   UNKNOWN and the wall is skipped rather than guessed.

EVERYTHING ELSE IS A COPY OF THE FROZEN PHASE 3 PATH. Same coverage floor, same
32-point minimum, same one-sided rejection of planes that cut through the object,
same nearest-wall selection rule, same metric/relative threshold routing, same
0.12 m threshold. Only the statistic changes.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402

#: Reused from Phase 3's `percentile(|signed|, 10)`, applied to the signed,
#: room-oriented projection instead. Frozen before the benchmark ran.
REAR_EXTENT_PERCENTILE = 10.0

#: The room centroid must sit at least this fraction of the scene's own extent
#: away from a wall plane before its side is trusted to orient that plane. Below
#: it, the centroid is effectively ON the plane and the sign is a coin toss, so
#: orientation is reported UNKNOWN. Frozen before the benchmark ran.
MIN_ORIENTATION_MARGIN_FRACTION = 0.01


@dataclass
class WallProjection:
    """One object measured against one wall, with the full audit trail."""

    wall_index: int
    wall_normal: tuple
    wall_offset: float
    wall_confidence: float
    orientation_sign: float            # +1 or -1; multiplies signed_distance
    orientation_source: str
    orientation_margin: float          # |centroid distance| / scene scale
    projection_min: float              # closest observed point, signed
    projection_max: float              # farthest observed point, signed
    rear_extent: float                 # percentile(q, REAR_EXTENT_PERCENTILE)
    gap: float                         # max(0, rear_extent)
    nearest_surface: float             # the Phase 3 statistic, for comparison
    rejected: Optional[str] = None


@dataclass
class RearExtentContact:
    """Mirrors `planes.WallContact`, plus the Phase 4 diagnostics."""

    decision: P.Decision
    distance: Optional[float]
    relative_distance: Optional[float]
    wall_index: Optional[int]
    wall_confidence: Optional[float]
    object_geometric_confidence: float
    depth_coverage: float
    metric_source: P.MetricSource
    threshold_used: Optional[float]
    failure_reason: Optional[str]
    rear_extent: Optional[float] = None
    nearest_surface: Optional[float] = None
    projection_min: Optional[float] = None
    projection_max: Optional[float] = None
    valid_point_count: int = 0
    orientation_source: Optional[str] = None
    orientation_margin: Optional[float] = None
    percentile_used: float = REAR_EXTENT_PERCENTILE
    projections: list = field(default_factory=list)


def room_centroid(pointmap: P.PointMap):
    """A point known to lie inside the room volume, from geometry alone.

    The median of the reconstructed surface points. The room is bounded by its
    own walls and floor, so the centroid of those surfaces falls inside the
    volume they enclose, and therefore on the interior side of every wall. The
    median rather than the mean, so a few points at the far end of a doorway
    cannot drag it through a wall.
    """
    pts = pointmap.valid_points()
    if pts.shape[0] < 64:
        return None
    return np.median(pts, axis=0)


def orient_to_room(plane: P.Plane, centre, scene_scale: float) -> tuple:
    """Which way along `plane.normal` is "into the room"?

    Returns (sign, source, margin). `sign` multiplies `signed_distance` so that
    positive means "away from the wall, into the room". `margin` is how far the
    centroid sits from the plane as a fraction of the scene's extent; below
    MIN_ORIENTATION_MARGIN_FRACTION the sign is not trustworthy and `sign` is
    returned as 0.0, meaning UNKNOWN.
    """
    if centre is None:
        return 0.0, "no room centroid available", 0.0
    signed = float(plane.signed_distance(centre.reshape(1, 3))[0])
    margin = abs(signed) / scene_scale if scene_scale > 0 else 0.0
    if margin < MIN_ORIENTATION_MARGIN_FRACTION:
        return 0.0, "room centroid lies on the plane; orientation ambiguous", margin
    return (1.0 if signed > 0 else -1.0), "room centroid side", margin


def rear_extent_wall_contact(
        pointmap: P.PointMap, room: P.RoomGeometry, object_mask: np.ndarray, *,
        percentile: float = REAR_EXTENT_PERCENTILE,
        distance_m: float = P.WALL_CONTACT_DISTANCE_M,
        relative_tolerance: float = P.WALL_CONTACT_RELATIVE_TOLERANCE,
        min_confidence: float = P.MIN_OBJECT_GEOMETRIC_CONFIDENCE) -> RearExtentContact:
    """Is this object against a wall, judged by its extent toward the wall?

    Structurally identical to `planes.wall_contact`. The ONE difference is the
    statistic: where that function takes `percentile(|signed|, 10)`, this takes
    `percentile(signed * orientation, 10)` and clamps a negative result to zero.
    """
    coverage_total = int(object_mask.sum())
    usable = object_mask & pointmap.valid
    coverage = (float(usable.sum()) / coverage_total) if coverage_total else 0.0

    def give_up(reason: str) -> RearExtentContact:
        return RearExtentContact(
            decision=P.Decision.UNKNOWN, distance=None, relative_distance=None,
            wall_index=None, wall_confidence=None,
            object_geometric_confidence=round(coverage, 4),
            depth_coverage=round(coverage, 4),
            metric_source=pointmap.metric_source, threshold_used=None,
            failure_reason=reason, percentile_used=percentile)

    # -- the frozen Phase 3 gates, unchanged ------------------------------
    if coverage_total == 0:
        return give_up("object mask is empty")
    if coverage < min_confidence:
        return give_up(f"depth coverage {coverage:.2f} below {min_confidence}")
    if not room.ok:
        return give_up("no usable room frame")

    candidates = [(i, w) for i, w in enumerate(room.walls) if not w.uncertain]
    if not candidates:
        return give_up("no wall plane passed its checks")

    points = pointmap.points[usable]
    if points.shape[0] < 32:
        return give_up(f"only {points.shape[0]} object points with depth")

    scale = room.scene_scale or pointmap.scene_scale()
    centre = room_centroid(pointmap)

    projections = []
    best = None
    rejected_through = rejected_orientation = 0
    for index, fit in candidates:
        signed = fit.plane.signed_distance(points)

        # Identical to the frozen path: a plane that cuts through the object is
        # a plane fitted to the object, not a wall behind it.
        on_positive = float((signed > 0).mean())
        if P.MIN_ONE_SIDED_FRACTION > on_positive > (1.0 - P.MIN_ONE_SIDED_FRACTION):
            rejected_through += 1
            projections.append(WallProjection(
                wall_index=index, wall_normal=fit.plane.normal,
                wall_offset=fit.plane.offset,
                wall_confidence=round(float(fit.inlier_fraction), 4),
                orientation_sign=0.0, orientation_source="not evaluated",
                orientation_margin=0.0, projection_min=0.0, projection_max=0.0,
                rear_extent=0.0, gap=0.0, nearest_surface=0.0,
                rejected="plane cuts through the object"))
            continue

        sign, source, margin = orient_to_room(fit.plane, centre, scale)
        if sign == 0.0:
            rejected_orientation += 1
            projections.append(WallProjection(
                wall_index=index, wall_normal=fit.plane.normal,
                wall_offset=fit.plane.offset,
                wall_confidence=round(float(fit.inlier_fraction), 4),
                orientation_sign=0.0, orientation_source=source,
                orientation_margin=round(margin, 5), projection_min=0.0,
                projection_max=0.0, rear_extent=0.0, gap=0.0, nearest_surface=0.0,
                rejected="wall normal orientation could not be established"))
            continue

        # THE PHASE 4 CHANGE, and the only one. q is the object's extent along
        # the wall normal with positive pointing into the room.
        q = sign * signed
        rear = float(np.percentile(q, percentile))
        gap = max(0.0, rear)
        nearest = float(np.percentile(np.abs(signed), percentile))

        projection = WallProjection(
            wall_index=index, wall_normal=fit.plane.normal,
            wall_offset=fit.plane.offset,
            wall_confidence=round(float(fit.inlier_fraction), 4),
            orientation_sign=sign, orientation_source=source,
            orientation_margin=round(margin, 5),
            projection_min=round(float(q.min()), 5),
            projection_max=round(float(q.max()), 5),
            rear_extent=round(rear, 5), gap=round(gap, 5),
            nearest_surface=round(nearest, 5))
        projections.append(projection)
        if best is None or gap < best.gap:
            best = projection

    if best is None:
        reasons = []
        if rejected_through:
            reasons.append(f"{rejected_through} cut through the object")
        if rejected_orientation:
            reasons.append(f"{rejected_orientation} could not be oriented")
        return give_up("no usable wall: " + ", ".join(reasons or ["none offered"]))

    relative = (best.gap / scale) if scale > 0 else None
    if pointmap.metric_source is P.MetricSource.UNSCALED:
        threshold, measured = relative_tolerance, relative
    else:
        threshold, measured = distance_m, best.gap

    if measured is None:
        return give_up("scene scale is zero; no threshold applies")

    return RearExtentContact(
        decision=P.Decision.YES if measured <= threshold else P.Decision.NO,
        distance=round(best.gap, 5),
        relative_distance=round(relative, 5) if relative is not None else None,
        wall_index=best.wall_index, wall_confidence=best.wall_confidence,
        object_geometric_confidence=round(coverage, 4),
        depth_coverage=round(coverage, 4), metric_source=pointmap.metric_source,
        threshold_used=threshold, failure_reason=None,
        rear_extent=best.rear_extent, nearest_surface=best.nearest_surface,
        projection_min=best.projection_min, projection_max=best.projection_max,
        valid_point_count=int(points.shape[0]),
        orientation_source=best.orientation_source,
        orientation_margin=best.orientation_margin,
        percentile_used=percentile, projections=projections)


def _self_check() -> None:
    """A synthetic room where the right answer is known by construction.

    Not a benchmark case and not part of the 48 - a unit check that the sign
    convention does what the docstring claims, which no aggregate percentage
    would reveal if it were backwards.
    """
    h = w = 64
    # A wall at z = -3 (the canonical frame looks down -Z), room centred near
    # z = -1.5, object occupying z in [-2.9, -2.4].
    pts = np.zeros((h, w, 3), dtype=np.float64)
    rng = np.random.default_rng(0)
    pts[..., 0] = rng.uniform(-1.0, 1.0, (h, w))
    pts[..., 1] = rng.uniform(0.0, 1.0, (h, w))
    pts[..., 2] = rng.uniform(-2.9, -2.4, (h, w))
    valid = np.ones((h, w), dtype=bool)

    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)      # z = -3
    centre = np.array([0.0, 0.5, -1.5])
    scale = 4.0
    sign, source, _margin = orient_to_room(plane, centre, scale)
    assert sign == 1.0, f"expected +1 (room lies at z > -3), got {sign} via {source}"

    q = sign * plane.signed_distance(pts[valid])
    rear = float(np.percentile(q, REAR_EXTENT_PERCENTILE))
    nearest = float(np.percentile(np.abs(plane.signed_distance(pts[valid])),
                                  REAR_EXTENT_PERCENTILE))
    # Every point is on one side here, so both statistics must agree; what is
    # being checked is that the sign convention points the right way.
    assert 0.05 < rear < 0.20, f"rear extent {rear} not near the expected 0.1"
    assert abs(rear - nearest) < 1e-9, "one-sided object: the two must agree"

    # Now push the object THROUGH the wall. The rear extent must go negative
    # while the absolute statistic folds it back to a positive number, which is
    # exactly the failure mode Phase 4 exists to avoid.
    through = pts.copy()
    through[..., 2] -= 0.6                                   # z in [-3.5, -3.0]
    q2 = sign * plane.signed_distance(through[valid])
    rear2 = float(np.percentile(q2, REAR_EXTENT_PERCENTILE))
    near2 = float(np.percentile(np.abs(plane.signed_distance(through[valid])),
                                REAR_EXTENT_PERCENTILE))
    assert rear2 < 0.0, f"an object behind the wall must give a negative rear ({rear2})"
    assert near2 > 0.0, "the absolute statistic cannot express penetration"
    assert max(0.0, rear2) == 0.0, "penetration must clamp to a zero gap"
    print(f"self-check OK: rear={rear:.3f} nearest={nearest:.3f} | "
          f"through-wall rear={rear2:.3f} abs={near2:.3f} gap={max(0.0, rear2):.3f}")


__all__ = ["RearExtentContact", "WallProjection", "rear_extent_wall_contact",
           "orient_to_room", "room_centroid", "REAR_EXTENT_PERCENTILE",
           "MIN_ORIENTATION_MARGIN_FRACTION"]


if __name__ == "__main__":
    _self_check()

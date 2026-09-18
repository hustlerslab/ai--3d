"""Manual amodal 3D geometry oracle, and the wall contact computed from it.

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

WHAT THIS IS FOR. Phases 2, 3 and 4 improved the inputs - metric geometry, then
segmentation, then the measured statistic - and left the wall decision near
chance. Phase 4 established WHY: the object's rear extent is occluded and simply
absent from a single-view point cloud, proven by 32 of 48 cases returning a value
identical to the phase before.

That raises a question no further perception model can answer for us:

    if the geometry engine were GIVEN the object's full physical extent,
    including the hidden back, would it get wall contact right?

This module supplies that extent by hand and lets the existing geometry decide.
It is a CEILING measurement, not a method.

WHAT THE ORACLE IS ALLOWED TO KNOW, AND WHAT IT IS NOT. It knows the object's
physical size, because that is a property of the furniture rather than of the
scene: a sofa is about 0.9 m deep whether it stands against a wall or in the
middle of the floor. It does NOT know where the object sits, which way it faces,
how far it is from anything, or what the benchmark says the answer is.

    supplied by hand   width, depth, height  (oracle_geometry.json)
    derived from data  position, orientation (this module)
    computed           the wall gap and the YES/NO decision

THE POSITIONING RULE, AND WHY IT CANNOT LEAK THE ANSWER. The box is never placed
by hand. It is anchored to the object's own visible points by one physical fact
that holds for every object in every scene:

    hidden geometry lies BEHIND visible geometry, away from the camera.

So the box's near face sits at the nearest visible surface and the box extends
away from the camera by the measured depth. Nothing in that rule consults a wall,
a distance or a label. If the object is against a wall the box will reach the
wall on its own, and if it is not, it will not.

ORIENTATION IS DERIVED, NOT GUESSED. The object's width axis is the dominant
horizontal direction of its own visible points; the depth axis is perpendicular
to it in the room's horizontal plane. For the near-square objects that dominate
this subset (chairs, stools, poufs, side tables) the assignment barely matters;
for the elongated ones (sofas, the bed, the counter) the visible front face is a
long horizontal strip, which is exactly what a principal direction recovers.

HEIGHT BARELY MATTERS AND IS NOT PRETENDED TO. Walls are vertical, so the
projection onto a wall normal is horizontal and the vertical placement of the box
has almost no effect on the gap. The box is seated at the lowest visible point and
given the measured height. Recorded so no one later mistakes it for a careful
vertical fit.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)

MEASUREMENTS = Path(__file__).resolve().parent / "oracle_geometry.json"

#: Minimum visible points before an oracle box may be built. Same spirit as the
#: 32-point floor the frozen path applies to its own measurement.
MIN_ORACLE_POINTS = 32


@dataclass
class OracleObjectGeometry:
    """One hand-measured object envelope, plus where the derivation put it."""

    case_id: str
    object_type: str
    width_m: float
    depth_m: float
    height_m: float
    uncertainty_m: float
    notes: str
    source: str = "manual estimate from the source image"
    coordinate_frame: str = "canonical: +X right, +Y up, -Z forward, metres"
    # filled in by `place`
    center: Optional[tuple] = None
    width_axis: Optional[tuple] = None
    depth_axis: Optional[tuple] = None
    yaw_source: str = "derived: dominant horizontal direction of visible points"
    corners: Optional[np.ndarray] = None
    visible_points: int = 0
    visible_depth_extent: Optional[float] = None
    depth_underestimated: bool = False
    failure_reason: Optional[str] = None


@dataclass
class OracleContact:
    """A wall decision computed from the oracle box alone."""

    decision: P.Decision
    distance: Optional[float]
    wall_index: Optional[int]
    wall_confidence: Optional[float]
    threshold_used: Optional[float]
    failure_reason: Optional[str]
    margin: Optional[float] = None            # |gap - threshold|
    borderline: bool = False
    walls_considered: int = 0
    walls_rejected_far_side: int = 0
    per_wall: list = field(default_factory=list)


def load_measurements() -> dict:
    data = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    out = {}
    for row in data["measurements"]:
        out[row["case_id"]] = OracleObjectGeometry(
            case_id=row["case_id"], object_type=row["object_type"],
            width_m=float(row["width_m"]), depth_m=float(row["depth_m"]),
            height_m=float(row["height_m"]),
            uncertainty_m=float(row["uncertainty_m"]), notes=row["notes"])
    return out


def place(oracle: OracleObjectGeometry, points: np.ndarray, room: P.RoomGeometry,
          *, d_scale: float = 1.0, w_scale: float = 1.0,
          shift_m: float = 0.0) -> OracleObjectGeometry:
    """Anchor the hand-measured envelope to the object's visible points.

    `d_scale`, `w_scale` and `shift_m` exist ONLY for the uncertainty
    perturbation in the benchmark; at their defaults this is the primary
    construction. `shift_m` slides the box along the depth axis, positive meaning
    further from the camera.
    """
    if points.shape[0] < MIN_ORACLE_POINTS:
        oracle.failure_reason = f"only {points.shape[0]} visible points"
        return oracle

    up = np.asarray(room.up, dtype=np.float64)
    up = up / (np.linalg.norm(up) or 1.0)

    # Horizontal component of each point, then the dominant horizontal direction.
    centred = points - points.mean(axis=0)
    horizontal = centred - np.outer(centred @ up, up)
    if not np.isfinite(horizontal).all() or horizontal.shape[0] < 3:
        oracle.failure_reason = "cannot form a horizontal basis"
        return oracle
    _u, _s, vt = np.linalg.svd(horizontal, full_matrices=False)
    e1 = vt[0] - up * float(vt[0] @ up)             # width axis, horizontal
    n1 = np.linalg.norm(e1)
    if n1 < 1e-9:
        oracle.failure_reason = "degenerate horizontal spread"
        return oracle
    e1 = e1 / n1
    e2 = np.cross(up, e1)                            # depth axis, horizontal
    e2 = e2 / (np.linalg.norm(e2) or 1.0)

    # The camera sits at the origin of the canonical frame, so the direction
    # "away from the camera" along e2 is the one the object's centroid lies in.
    centroid = points.mean(axis=0)
    f = e2 * (1.0 if float(e2 @ centroid) > 0 else -1.0)

    w = oracle.width_m * w_scale
    d = oracle.depth_m * d_scale
    h = oracle.height_m

    a = points @ e1
    t = points @ f
    g = points @ up

    # Width: centred on what is visible. Depth: near face at the nearest visible
    # surface, extending AWAY from the camera. Height: seated at the lowest
    # visible point.
    a_mid = 0.5 * (float(a.min()) + float(a.max()))
    a_lo, a_hi = a_mid - w / 2.0, a_mid + w / 2.0
    t_lo = float(t.min()) + shift_m
    t_hi = t_lo + d
    g_lo = float(g.min())
    g_hi = g_lo + h

    corners = np.array([lo1 * e1 + lo2 * f + lo3 * up
                        for lo1 in (a_lo, a_hi)
                        for lo2 in (t_lo, t_hi)
                        for lo3 in (g_lo, g_hi)], dtype=np.float64)

    visible_depth = float(t.max() - t.min())
    oracle.center = tuple(np.round(corners.mean(axis=0), 5))
    oracle.width_axis = tuple(np.round(e1, 5))
    oracle.depth_axis = tuple(np.round(f, 5))
    oracle.corners = corners
    oracle.visible_points = int(points.shape[0])
    oracle.visible_depth_extent = round(visible_depth, 4)
    # If the object's own visible surface is deeper than the measured depth, the
    # measurement is too small. Recorded, never silently widened.
    oracle.depth_underestimated = bool(visible_depth > d + 1e-6)
    return oracle


def oracle_wall_contact(oracle: OracleObjectGeometry, pointmap: P.PointMap,
                        room: P.RoomGeometry, *, sanity_gate: bool,
                        distance_m: float = P.WALL_CONTACT_DISTANCE_M,
                        borderline_margin: float = 0.05) -> OracleContact:
    """Wall contact from the oracle box alone. No SAM points, no MoGe points.

    `sanity_gate=False` is Oracle A: the candidate-wall selection exactly as it
    stands today. `sanity_gate=True` is Oracle B, which additionally refuses a
    wall that the ENTIRE object lies on the far side of - the failure Phase 4
    measured 13 times, where clamping an impossible geometry to a zero gap
    manufactured a contact.
    """
    def give_up(reason: str) -> OracleContact:
        return OracleContact(decision=P.Decision.UNKNOWN, distance=None,
                             wall_index=None, wall_confidence=None,
                             threshold_used=None, failure_reason=reason)

    if oracle.failure_reason or oracle.corners is None:
        return give_up(oracle.failure_reason or "no oracle box")
    if not room.ok:
        return give_up("no usable room frame")

    candidates = [(i, w) for i, w in enumerate(room.walls) if not w.uncertain]
    if not candidates:
        return give_up("no wall plane passed its checks")

    scale = room.scene_scale or pointmap.scene_scale()
    centre = room_centroid(pointmap)

    best = None
    rejected_far = 0
    per_wall = []
    for index, fit in candidates:
        sign, source, margin = orient_to_room(fit.plane, centre, scale)
        if sign == 0.0:
            per_wall.append({"wall_index": index, "rejected": source})
            continue
        q = sign * fit.plane.signed_distance(oracle.corners)
        q_min, q_max = float(q.min()), float(q.max())
        entirely_far_side = q_max < 0.0
        row = {"wall_index": index,
               "wall_confidence": round(float(fit.inlier_fraction), 4),
               "orientation_margin": round(margin, 5),
               "obb_projection_min": round(q_min, 5),
               "obb_projection_max": round(q_max, 5),
               "gap": round(max(0.0, q_min), 5),
               "entirely_far_side": entirely_far_side}
        if sanity_gate and entirely_far_side:
            rejected_far += 1
            row["rejected"] = ("the whole object lies on the far side of this "
                               "plane from the room interior")
            per_wall.append(row)
            continue
        per_wall.append(row)
        gap = max(0.0, q_min)
        if best is None or gap < best[1]:
            best = (index, gap, fit)

    if best is None:
        return give_up(f"no usable wall ({rejected_far} rejected as far-side)")

    index, gap, fit = best
    margin = abs(gap - distance_m)
    return OracleContact(
        decision=P.Decision.YES if gap <= distance_m else P.Decision.NO,
        distance=round(gap, 5), wall_index=index,
        wall_confidence=round(float(fit.inlier_fraction), 4),
        threshold_used=distance_m, failure_reason=None,
        margin=round(margin, 5), borderline=bool(margin < borderline_margin),
        walls_considered=len(candidates), walls_rejected_far_side=rejected_far,
        per_wall=per_wall)


def _self_check() -> None:
    """A synthetic room where the oracle must recover an occluded rear face.

    This is the whole premise of Phase 5 in miniature: a 'sofa' whose visible
    surface is 0.9 m from the wall but whose body reaches it. The nearest-visible
    statistic must say 0.9 m; the oracle box must say about zero.
    """
    h = w = 48
    up = np.array([0.0, 1.0, 0.0])
    # Wall at z = -3. Visible front face of a 0.9 m deep sofa whose back touches
    # the wall: the visible slab sits at z in [-2.15, -2.10].
    rng = np.random.default_rng(1)
    pts = np.stack([rng.uniform(-1.0, 1.0, (h, w)),
                    rng.uniform(0.0, 0.8, (h, w)),
                    rng.uniform(-2.15, -2.10, (h, w))], axis=-1)
    points = pts.reshape(-1, 3)

    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)
    fit = P.PlaneFitResult(plane=plane, inlier_count=1000, total_points=1000,
                           inlier_fraction=0.9, residual_mean=0.0,
                           residual_median=0.0, residual_p95=0.0, threshold=0.01)
    room = P.RoomGeometry(floor=fit, walls=[fit], up=tuple(up), boundary=None,
                          metric_source=P.MetricSource.METRIC_MODEL,
                          scene_scale=4.0)
    pointmap = P.PointMap(points=pts, valid=np.ones((h, w), dtype=bool),
                          disparity=np.ones((h, w)),
                          metric_source=P.MetricSource.METRIC_MODEL, fov_deg=60.0)

    nearest = float(np.percentile(np.abs(plane.signed_distance(points)), 10))
    oracle = OracleObjectGeometry(case_id="synthetic.sofa", object_type="sofa",
                                  width_m=2.0, depth_m=0.9, height_m=0.8,
                                  uncertainty_m=0.1, notes="self-check")
    place(oracle, points, room)
    contact = oracle_wall_contact(oracle, pointmap, room, sanity_gate=False)

    assert 0.80 < nearest < 1.00, f"visible surface should read ~0.9, got {nearest}"
    assert contact.distance is not None and contact.distance < 0.06, (
        f"oracle should reach the wall, got {contact.distance}")
    assert contact.decision is P.Decision.YES
    print(f"self-check OK: nearest visible={nearest:.3f} m -> "
          f"oracle rear={contact.distance:.3f} m ({contact.decision.value})")


__all__ = ["OracleObjectGeometry", "OracleContact", "load_measurements", "place",
           "oracle_wall_contact", "MIN_ORACLE_POINTS"]


if __name__ == "__main__":
    _self_check()

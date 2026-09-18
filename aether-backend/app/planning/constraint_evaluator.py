"""P8 constraint evaluator: `evaluate(constraint, spatial_scene) ->
ConstraintResult`, dispatched by `ConstraintType`. Strictly read-only - no
function in this module writes to `spatial_scene.scene` or
`spatial_scene.relations`; verified by `test_constraint_evaluator.
test_evaluate_all_never_mutates_the_scene`.

Every geometric check reuses an EXISTING, already-tested primitive
(`app.spatial.geometry`, P7's `AGAINST_WALL_TOLERANCE_M`, P2's
`clearance_engine`) rather than reimplementing collision/distance/
containment math a second time (§41: do not duplicate validation).
"""
from __future__ import annotations

import math
from typing import Optional


from app.spatial import geometry as geo
from app.spatial.validation import object_footprint
from app.spatial.clearance_engine import (
    pairwise_clearance_violations)
from app.planning.constraint_model import (
    Constraint, ConstraintResult, ConstraintType, Verdict)
from app.spatial.scene_graph import AGAINST_WALL_TOLERANCE_M
from app.spatial.scene_model import SpatialScene

#: §15: production's OWN "points at" tolerance (`app/planning/compiler.py`'s
#: `_FACES_COS = 0.5`, i.e. within 60 degrees of dead-on) - reused here as
#: the default, rather than inventing a second, different orientation
#: tolerance the solver and the evaluator would silently disagree about.
DEFAULT_ORIENTATION_TOLERANCE_DEG = 60.0

#: §19: NEAR has no metric default anywhere in this program (production's
#: own `NEAR_DISTANCE = 0.25` in `app/planning/spatial_graph.py` is a
#: fraction of an IMAGE, not a metre distance - reusing it here would be
#: exactly the "fake precision" §19 forbids). When an intent gives an
#: explicit `distance_m`, this is the ONLY new metric number this module
#: introduces, and it is sized the same way P7 sized `AGAINST_WALL_
#: TOLERANCE_M`: loose enough to absorb ordinary placement jitter, tight
#: enough to catch a real miss.
DEFAULT_DISTANCE_TOLERANCE_M = 0.3


def _forward(rotation_y: float) -> tuple[float, float]:
    """Identical formula to `app/planning/compiler.py::_forward` /
    P1's `scene_forward(yaw) = (-sin(yaw), -cos(yaw))` - reimplemented
    directly (two lines) rather than importing a leading-underscore private
    function across a module boundary; both compute the exact same vector,
    verified by `test_orientation_matches_compiler_forward_convention`."""
    return (-math.sin(rotation_y), -math.cos(rotation_y))


def _angular_error_deg(subject_xz: tuple[float, float], rotation_y: float,
                       target_xz: tuple[float, float]) -> Optional[float]:
    dx, dz = target_xz[0] - subject_xz[0], target_xz[1] - subject_xz[1]
    dist = math.hypot(dx, dz)
    if dist < 1e-6:
        return None    # standing on the target: no direction is defined (§15 "same position")
    fx, fz = _forward(rotation_y)
    cos_angle = max(-1.0, min(1.0, (fx * dx + fz * dz) / dist))
    return math.degrees(math.acos(cos_angle))


def _evaluate_orientation(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    obj = spatial.scene.object(c.subject_id)
    target = spatial.scene.object(c.target_id)
    if obj is None or target is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or target not found in scene")
    error = _angular_error_deg((obj.position[0], obj.position[2]), obj.rotation_y,
                               (target.position[0], target.position[2]))
    if error is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject and target occupy the same position; "
                                       "no facing direction is defined")
    tolerance = float(c.parameters.get("tolerance_deg", DEFAULT_ORIENTATION_TOLERANCE_DEG))
    verdict = Verdict.SATISFIED if error <= tolerance else Verdict.VIOLATED
    return ConstraintResult(c.constraint_id, verdict, error=round(error, 2),
                           error_kind="angular_deg",
                           message=f"angular error {error:.1f} deg (tolerance {tolerance:.1f} deg)")


def _evaluate_distance(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    obj = spatial.scene.object(c.subject_id)
    target = spatial.scene.object(c.target_id) or spatial.scene.wall(c.target_id)
    if obj is None or target is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or target not found in scene")
    if "distance_m" not in c.parameters:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="no explicit distance was given (§19: NEAR alone is "
                                       "not converted into a fabricated metric threshold)")
    target_xz = (target.position[0], target.position[2]) if hasattr(target, "position") else None
    if target_xz is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN, message="target has no position")
    actual = geo.distance((obj.position[0], obj.position[2]), target_xz)
    wanted = float(c.parameters["distance_m"])
    tolerance = float(c.parameters.get("tolerance_m", DEFAULT_DISTANCE_TOLERANCE_M))
    error = abs(actual - wanted)
    verdict = Verdict.SATISFIED if error <= tolerance else Verdict.VIOLATED
    return ConstraintResult(c.constraint_id, verdict, error=round(error, 3), error_kind="distance_m",
                           message=f"actual {actual:.2f} m vs requested {wanted:.2f} m "
                                  f"+/- {tolerance:.2f} m")


def _evaluate_contact(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    """§16: reuses the EXACT distance-to-wall-segment check and tolerance P7
    already built and benchmarked (`scene_graph.AGAINST_WALL_TOLERANCE_M`) -
    not a second, independently-tuned wall-contact rule."""
    obj = spatial.scene.object(c.subject_id)
    wall = spatial.scene.wall(c.target_id)
    if obj is None or wall is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or wall not found in scene")
    gap = geo.point_segment_distance((obj.position[0], obj.position[2]), wall.start, wall.end)
    gap -= wall.thickness / 2.0
    tolerance = float(c.parameters.get("tolerance_m", AGAINST_WALL_TOLERANCE_M))
    verdict = Verdict.SATISFIED if gap <= tolerance else Verdict.VIOLATED
    return ConstraintResult(c.constraint_id, verdict, error=round(gap, 3), error_kind="distance_m",
                           message=f"gap to wall {gap:.3f} m (tolerance {tolerance:.3f} m)")


def _evaluate_support(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    from app.intelligence.vocab import SURFACE_HEIGHT
    obj = spatial.scene.object(c.subject_id)
    if obj is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN, message="subject not found")
    room = spatial.scene.room(c.target_id)
    target = spatial.scene.object(c.target_id)
    if room is not None:  # "supported by the room" == resting on the floor
        verdict = Verdict.SATISFIED if obj.mount == "floor" else Verdict.VIOLATED
        error = abs(obj.position[1] - room.floor_height)
        return ConstraintResult(c.constraint_id, verdict, error=round(error, 3),
                               error_kind="distance_m", message=f"floor gap {error:.3f} m")
    if target is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN, message="target not found in scene")
    if obj.parent_id is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject has not been assigned any support yet")
    if obj.parent_id != target.object_id:
        return ConstraintResult(c.constraint_id, Verdict.VIOLATED,
                               message=f"subject is supported by {obj.parent_id}, not {target.object_id}")
    surface_h = SURFACE_HEIGHT.get(target.semantic_type)
    target_top = target.position[1] + (surface_h if surface_h is not None
                                       else target.dimensions[1] * target.scale[1])
    error = abs(obj.position[1] - target_top)
    return ConstraintResult(c.constraint_id, Verdict.SATISFIED, error=round(error, 3),
                           error_kind="distance_m", message=f"vertical gap {error:.3f} m")


def _target_polygon(spatial: SpatialScene, target_id: str):
    room = spatial.scene.room(target_id)
    if room is not None:
        return room.boundary
    obj = spatial.scene.object(target_id)
    if obj is not None:
        return object_footprint(obj)
    return None


def _evaluate_containment(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    """§18: INSIDE(subject, target) - subject inside target's polygon.
    CONTAINS(subject, target) is the mirror direction (subject's polygon
    contains target's point) - both compiled to CONTAINMENT
    (`constraint_compiler.PREDICATE_TO_TYPE`), disambiguated here via the
    original predicate carried in `parameters["_predicate"]`."""
    predicate = c.parameters.get("_predicate", "INSIDE")
    contained_id, container_id = ((c.target_id, c.subject_id) if predicate == "CONTAINS"
                                  else (c.subject_id, c.target_id))
    contained_obj = spatial.scene.object(contained_id)
    container_poly = _target_polygon(spatial, container_id)
    if contained_obj is None or container_poly is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or target not found in scene")
    point = (contained_obj.position[0], contained_obj.position[2])
    inside = geo.point_inside_polygon(point, container_poly, tolerance=0.0)
    verdict = Verdict.SATISFIED if inside else Verdict.VIOLATED
    return ConstraintResult(c.constraint_id, verdict, message=f"{contained_id} inside "
                           f"{container_id}: {inside}")


def _evaluate_position(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    """§20 (BETWEEN) and §21 (CENTERED_IN_ROOM, the only CENTERED variant
    built - see constraint_contract.md for why the other three were scoped
    out)."""
    if "between_a_id" in c.parameters or "between_b_id" in c.parameters:
        return _evaluate_between(c, spatial)
    return _evaluate_centered(c, spatial)


def _evaluate_between(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    obj = spatial.scene.object(c.subject_id)
    a = spatial.scene.object(c.parameters.get("between_a_id", ""))
    b = spatial.scene.object(c.parameters.get("between_b_id", ""))
    if obj is None or a is None or b is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or one of the two 'between' targets not found")
    p = (obj.position[0], obj.position[2])
    pa, pb = (a.position[0], a.position[2]), (b.position[0], b.position[2])
    # unclamped projection - `geo.project_onto_segment` clamps to [0,1] by
    # design for its own callers, but BETWEEN needs to know whether the
    # point falls OUTSIDE the segment (§20's "order along an axis"), so the
    # unclamped parametric t is computed directly here (same formula).
    dx, dz = pb[0] - pa[0], pb[1] - pa[1]
    length_sq = dx * dx + dz * dz
    if length_sq < 1e-9:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="the two 'between' targets occupy the same position")
    t_unclamped = ((p[0] - pa[0]) * dx + (p[1] - pa[1]) * dz) / length_sq
    lateral = geo.point_segment_distance(p, pa, pb)
    tolerance = float(c.parameters.get("tolerance_m", DEFAULT_DISTANCE_TOLERANCE_M))
    on_segment = -1e-6 <= t_unclamped <= 1.0 + 1e-6
    if not on_segment:
        return ConstraintResult(c.constraint_id, Verdict.VIOLATED, error=round(lateral, 3),
                               error_kind="distance_m",
                               message=f"beyond the segment endpoints (t={t_unclamped:.2f})")
    if lateral <= tolerance:
        return ConstraintResult(c.constraint_id, Verdict.SATISFIED, error=round(lateral, 3),
                               error_kind="distance_m", message=f"lateral offset {lateral:.3f} m")
    return ConstraintResult(c.constraint_id, Verdict.PARTIAL, error=round(lateral, 3),
                           error_kind="distance_m",
                           message=f"on the segment but {lateral:.3f} m off-axis "
                                  f"(tolerance {tolerance:.3f} m)")


def _evaluate_centered(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    obj = spatial.scene.object(c.subject_id)
    room = spatial.scene.room(c.target_id)
    if obj is None or room is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or room not found in scene")
    centroid = geo.polygon_centroid(room.boundary)
    error = geo.distance((obj.position[0], obj.position[2]), centroid)
    tolerance = float(c.parameters.get("tolerance_m", 1.0))
    verdict = Verdict.SATISFIED if error <= tolerance else Verdict.VIOLATED
    return ConstraintResult(c.constraint_id, verdict, error=round(error, 3), error_kind="distance_m",
                           message=f"{error:.2f} m from room centroid (tolerance {tolerance:.2f} m)")


def _evaluate_clearance(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    """Wraps P2's `pairwise_clearance_violations` - not reimplemented."""
    obj = spatial.scene.object(c.subject_id)
    target = spatial.scene.object(c.target_id)
    if obj is None or target is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message="subject or target not found in scene")
    pair = {c.subject_id, c.target_id}
    for v in pairwise_clearance_violations(spatial.scene):
        if {v.subject_id, v.target_id} == pair:
            return ConstraintResult(c.constraint_id, Verdict.VIOLATED, error=round(v.deficit_m, 3),
                                   error_kind="clearance_deficit_m",
                                   message=f"{v.constraint}: deficit {v.deficit_m:.3f} m")
    return ConstraintResult(c.constraint_id, Verdict.SATISFIED, message="no clearance violation found")


_DISPATCH = {
    ConstraintType.ORIENTATION: _evaluate_orientation,
    ConstraintType.DISTANCE: _evaluate_distance,
    ConstraintType.CONTACT: _evaluate_contact,
    ConstraintType.SUPPORT: _evaluate_support,
    ConstraintType.CONTAINMENT: _evaluate_containment,
    ConstraintType.POSITION: _evaluate_position,
    ConstraintType.CLEARANCE: _evaluate_clearance,
}


def evaluate(c: Constraint, spatial: SpatialScene) -> ConstraintResult:
    """Read-only. §10's reserved types (ALIGNMENT/RELATION/CIRCULATION) have
    no evaluator and resolve to UNKNOWN rather than raising - a reserved
    type reaching here means a future caller constructed one without also
    adding its evaluator, which is a real gap to surface, not a crash."""
    fn = _DISPATCH.get(c.constraint_type)
    if fn is None:
        return ConstraintResult(c.constraint_id, Verdict.UNKNOWN,
                               message=f"no evaluator implemented for {c.constraint_type.value}")
    return fn(c, spatial)


def evaluate_all(constraints, spatial: SpatialScene) -> tuple[ConstraintResult, ...]:
    return tuple(evaluate(c, spatial) for c in constraints)


__all__ = ["evaluate", "evaluate_all", "DEFAULT_ORIENTATION_TOLERANCE_DEG",
           "DEFAULT_DISTANCE_TOLERANCE_M"]

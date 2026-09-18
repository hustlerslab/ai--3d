"""P9 candidate generators: the NEW candidate content production has no
vocabulary for - a metric-distance ring (§11-13) and a between-two-targets
region (§14). Both are pure functions: read a `Constraint` + `SpatialScene`,
return `Candidate`s. Neither places anything or touches the scene.

WHY ONLY THESE TWO, AND WHY ORIENTATION HAS NO GENERATOR HERE. P8's FACES
failure was root-caused (docs/spatial_architecture/decisions.md's P9 entry)
to a WIRING problem, not a missing candidate: production's own
`_relation_candidates("facing", ...)` (app/planning/compiler.py) already
generates exactly the right, cosine-filtered, best-aligned-first candidates
- the fix was routing `constraint_compiler.apply_constraints_to_plan`
through `ObjectRelation(type="facing", ...)` instead of the free-text
`.faces` field, which ALSO fixed the real root cause (a missing entry in
`_ordered()`'s dependency graph). No new ORIENTATION candidate generator
was needed, and building one anyway - duplicating logic that already works
correctly in production - would violate this program's own "reuse, never
fork" discipline for a problem that measurably does not exist. DISTANCE
(with an explicit number) and BETWEEN are different: no `RelationType`
value in production can express a numeric metre distance or a two-target
segment region at all, so a real gap exists there, and these two functions
close it.

INTEGRATION POINT: `regenerate_after_placement`, run AFTER `place_objects`
has already produced a scene - the exact "repair -> regenerate local
candidates -> validate -> choose" shape (§33) P4's own `_try_nudge` already
uses (remove the object, generate candidates, validate each, keep the first
that passes, re-add) - reusing that established idiom, not inventing a new
one, and reusing `app.spatial.validation.validate_object` for the ONLY hard-
feasibility check anywhere in this phase (never reimplemented).
"""
from __future__ import annotations

import math
from dataclasses import replace as dc_replace
from typing import Optional


from app.planning.candidate_filters import filter_feasible
from app.planning.candidate_model import (
    Candidate, CandidateSource, dedupe)
from app.planning.candidate_ranker import (
    rank_by_ideal_distance, rank_between)
from app.planning.constraint_model import Constraint
from app.spatial.scene_model import SpatialScene

#: §13: bounded, not arbitrary - measured in candidate_benchmark.py's own
#: performance sweep (§23) to stay well under the P3-established "candidate
#: growth must remain bounded" bar. 16 samples is the same order of
#: magnitude as P1's own `_radial_candidates` ring density
#: (collision_solver.py), reused here as a precedent for "how many angular
#: samples has this program already measured as sufficient," not invented.
RING_SAMPLES = 16


def distance_candidates(constraint: Constraint, spatial: SpatialScene,
                        dims: tuple[float, float, float]) -> list[Candidate]:
    """§11/§12/§13: a ring of candidates at the constraint's own explicit
    `distance_m` around the target. Returns `[]` - never a fabricated
    default - when no explicit distance was given, exactly matching
    `constraint_evaluator`'s own UNKNOWN policy for a bare NEAR (§19's "do
    not hardcode NEAR=0.8m unless explicitly sourced"): if evaluation cannot
    honestly judge a bare NEAR, generation cannot honestly aim for one
    either."""
    if "distance_m" not in constraint.parameters:
        return []
    target = spatial.scene.object(constraint.target_id)
    if target is None:
        return []
    distance_m = float(constraint.parameters["distance_m"])
    out: list[Candidate] = []
    for k in range(RING_SAMPLES):
        angle = 2.0 * math.pi * k / RING_SAMPLES
        # sin/cos on (x, z), matching the same (x, z) plan-view convention
        # `app.spatial.geometry`/`app.planning.compiler` use throughout.
        pos = (target.position[0] + distance_m * math.sin(angle),
              target.position[2] + distance_m * math.cos(angle))
        # rotation defaults to the TARGET's own orientation, matching
        # `_relation_candidates("beside", ...)`'s own existing convention
        # (app/planning/compiler.py) - not a new convention invented here.
        out.append(Candidate(position=(round(pos[0], 4), round(pos[1], 4)),
                             rotation_y=round(target.rotation_y, 6), y=None,
                             source=CandidateSource.DISTANCE, constraint_id=constraint.constraint_id,
                             provenance=f"ring sample {k}/{RING_SAMPLES} at {distance_m} m "
                                       f"from {constraint.target_id}"))
    return out


#: §14: a small, deterministic grid - not an arbitrary huge candidate set
#: (§13's own warning, which applies equally here). `_T_VALUES` centred on
#: the midpoint (0.5) since that is the modal "between" reading; `_LATERAL_M`
#: lets a candidate step off the exact segment when the segment itself is
#: obstructed (§14's own "do not simply use the midpoint if it creates
#: collisions").
_T_VALUES = (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65)
_LATERAL_M = (0.0, 0.15, -0.15, 0.3, -0.3)


def between_candidates(constraint: Constraint, spatial: SpatialScene) -> list[Candidate]:
    """§14: candidates on (and, if needed, laterally offset from) the
    segment between the constraint's two named targets."""
    a = spatial.scene.object(constraint.parameters.get("between_a_id", ""))
    b = spatial.scene.object(constraint.parameters.get("between_b_id", ""))
    if a is None or b is None:
        return []
    pa, pb = (a.position[0], a.position[2]), (b.position[0], b.position[2])
    dx, dz = pb[0] - pa[0], pb[1] - pa[1]
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return []
    ux, uz = dx / length, dz / length      # unit vector along the segment
    nx, nz = -uz, ux                        # unit vector perpendicular to it

    out: list[Candidate] = []
    for t in _T_VALUES:
        base = (pa[0] + ux * length * t, pa[1] + uz * length * t)
        for lateral in _LATERAL_M:
            pos = (base[0] + nx * lateral, base[1] + nz * lateral)
            out.append(Candidate(position=(round(pos[0], 4), round(pos[1], 4)),
                                 rotation_y=round(a.rotation_y, 6), y=None,
                                 source=CandidateSource.BETWEEN, constraint_id=constraint.constraint_id,
                                 provenance=f"t={t}, lateral={lateral} m between "
                                           f"{constraint.parameters.get('between_a_id')} and "
                                           f"{constraint.parameters.get('between_b_id')}"))
    return out


def regenerate_after_placement(constraint: Constraint, spatial: SpatialScene,
                               dims: tuple[float, float, float]
                               ) -> Optional[tuple[float, float, float, float]]:
    """§33: the repair-shaped regeneration step. Removes the subject (if
    present) from a WORKING COPY, generates DISTANCE or BETWEEN candidates,
    filters through `validate_object` (the same, only, hard-feasibility gate
    this whole program uses, called inside `candidate_filters.
    filter_feasible`), ranks deterministically, and returns
    `(x, y, z, rotation_y)` for the caller to apply - or `None` if nothing
    both feasible and generatable exists. Never mutates `spatial`."""
    subject = spatial.scene.object(constraint.subject_id)
    room = spatial.scene.room(subject.room_id) if subject is not None else None
    if subject is None or room is None:
        return None

    working = spatial.scene.model_copy(update={
        "objects": [o for o in spatial.scene.objects if o.object_id != constraint.subject_id]})
    working_spatial = dc_replace(spatial, scene=working)

    if "between_a_id" in constraint.parameters or "between_b_id" in constraint.parameters:
        raw = between_candidates(constraint, working_spatial)
        target_a = working.object(constraint.parameters.get("between_a_id", ""))
        target_b = working.object(constraint.parameters.get("between_b_id", ""))
        if target_a is None or target_b is None:
            return None
        anchor_a = (target_a.position[0], target_a.position[2])
        anchor_b = (target_b.position[0], target_b.position[2])
    else:
        raw = distance_candidates(constraint, working_spatial, dims)
        anchor_a = anchor_b = None

    raw = dedupe(raw)
    feasible = filter_feasible(raw, working, room, dims, constraint.subject_id)
    if not feasible:
        return None

    if anchor_a is not None:
        ranked = rank_between(feasible, anchor_a, anchor_b)
    else:
        target = working.object(constraint.target_id)
        ideal = float(constraint.parameters.get("distance_m", 0.0))
        target_xz = (target.position[0], target.position[2]) if target is not None else (0.0, 0.0)
        ranked = rank_by_ideal_distance(feasible, ideal, target_xz)
    if not ranked:
        return None
    best = ranked[0]
    y = best.y if best.y is not None else subject.position[1]
    return (best.position[0], y, best.position[1], best.rotation_y)


__all__ = ["RING_SAMPLES", "distance_candidates", "between_candidates",
           "regenerate_after_placement"]

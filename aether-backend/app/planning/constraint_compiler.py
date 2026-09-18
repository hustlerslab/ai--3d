"""P8 constraint compiler: Intent/GeometricRelation -> ConstraintSet.

Reads a `SpatialScene` (P7) and a sequence of `Intent` (this phase) and
produces formal, typed `Constraint` objects (`constraint_model.py`) - never
places an object, never calls the solver, never touches `scene.objects`.

RELATION -> CONSTRAINT MAPPING (§14). Only the predicates with a real
evaluator (`constraint_evaluator.py`) are mapped; everything else is
recorded in `ConstraintSet.unsupported` rather than silently dropped.
"""
from __future__ import annotations

from typing import Sequence


from app.intelligence.schema import ObjectPlanItem, ObjectRelation
from app.spatial import geometry as geo
from app.planning.constraint_model import (
    Constraint, ConstraintConflict, ConstraintSet, ConstraintStatus,
    ConstraintType, Hardness, constraint_id)
from app.planning.intent_model import Intent
from app.spatial.scene_model import SpatialScene

#: §14's mapping, plus CENTERED (§21, room case only). Two-target predicates
#: (BETWEEN) store their second target in `parameters["between_a_id"]` -
#: `Constraint` was not given a second target field for one predicate's sake
#: (§9: no field without a consumer beyond this one type).
PREDICATE_TO_TYPE: dict[str, ConstraintType] = {
    "AGAINST_WALL": ConstraintType.CONTACT,
    "FACES": ConstraintType.ORIENTATION,
    "NEAR": ConstraintType.DISTANCE,
    "BETWEEN": ConstraintType.POSITION,
    "CENTERED_IN_ROOM": ConstraintType.POSITION,
    "SUPPORTED_BY": ConstraintType.SUPPORT,
    "ON_TOP_OF": ConstraintType.SUPPORT,
    "INSIDE": ConstraintType.CONTAINMENT,
    "CONTAINS": ConstraintType.CONTAINMENT,
    "CLEAR_OF": ConstraintType.CLEARANCE,
}

#: Every constraint this phase compiles is SOFT - see constraint_model.py's
#: `Hardness` docstring for the full policy reasoning. Named here as one
#: constant rather than a per-type table because the reasoning is the same
#: for every type (no solver mechanism exists to reject a scene on any of
#: them), not because some future type could not need HARD - if one does, it
#: earns its own entry then, with its own justification.
DEFAULT_HARDNESS = Hardness.SOFT


def _compile_one(intent: Intent) -> Constraint:
    ctype = PREDICATE_TO_TYPE[intent.predicate]
    params = dict(intent.parameters)
    # The original predicate string is kept in `parameters["_predicate"]`
    # rather than adding a field to `Constraint` for it: `ConstraintType`
    # already carries the CATEGORY, but CONTAINMENT is reached by two
    # opposite-direction predicates (INSIDE vs CONTAINS) that need
    # disambiguating in `constraint_evaluator.py`, and §39's explanation
    # output wants the original predicate anyway - one field, two uses.
    params["_predicate"] = intent.predicate
    cid = constraint_id(intent.subject_id, ctype, intent.target_id, params)
    return Constraint(
        constraint_id=cid, constraint_type=ctype, subject_id=intent.subject_id,
        target_id=intent.target_id, parameters=params, source_intent_id=intent.intent_id,
        provenance=f"intent:{intent.intent_id} ({intent.provenance})",
        priority=int(intent.priority), hardness=DEFAULT_HARDNESS,
        confidence=intent.confidence, status=ConstraintStatus.COMPILED)


def _detect_orientation_conflicts(constraints: Sequence[Constraint]) -> list[ConstraintConflict]:
    by_subject: dict[str, list[Constraint]] = {}
    for c in constraints:
        if c.constraint_type == ConstraintType.ORIENTATION:
            by_subject.setdefault(c.subject_id, []).append(c)
    out = []
    for subject, cs in sorted(by_subject.items()):
        targets = sorted({c.target_id for c in cs})
        if len(targets) > 1:
            out.append(ConstraintConflict(
                code="CONFLICTING_ORIENTATION", subject_id=subject,
                constraint_ids=tuple(sorted(c.constraint_id for c in cs)),
                message=f"{subject} must FACE {len(targets)} different targets at once: {targets}"))
    return out


def _detect_contact_conflicts(constraints: Sequence[Constraint]) -> list[ConstraintConflict]:
    by_subject: dict[str, list[Constraint]] = {}
    for c in constraints:
        if c.constraint_type == ConstraintType.CONTACT:
            by_subject.setdefault(c.subject_id, []).append(c)
    out = []
    for subject, cs in sorted(by_subject.items()):
        targets = sorted({c.target_id for c in cs})
        if len(targets) > 1:
            out.append(ConstraintConflict(
                code="CONFLICTING_WALL_CONTACT", subject_id=subject,
                constraint_ids=tuple(sorted(c.constraint_id for c in cs)),
                message=f"{subject} must be AGAINST_WALL {len(targets)} different walls "
                       f"at once: {targets} (a real corner is possible but not assumed here)"))
    return out


def _check_wall_capacity(constraints: Sequence[Constraint], spatial: SpatialScene
                         ) -> list[ConstraintConflict]:
    """§33: the smallest feasibility mechanism consistent with P1/P3 - simple
    arithmetic (sum of required widths vs. wall length), not a solver run.
    Catches an UNSAT case (two wide objects required against a short wall)
    BEFORE any placement is attempted."""
    by_wall: dict[str, list[Constraint]] = {}
    for c in constraints:
        if c.constraint_type == ConstraintType.CONTACT:
            by_wall.setdefault(c.target_id, []).append(c)
    out = []
    for wall_id, cs in sorted(by_wall.items()):
        wall = spatial.scene.wall(wall_id)
        if wall is None:
            continue
        length = geo.distance(wall.start, wall.end)
        total_width = 0.0
        for c in cs:
            obj = spatial.scene.object(c.subject_id)
            if obj is not None:
                total_width += obj.dimensions[0] * obj.scale[0]
        if total_width > length:
            out.append(ConstraintConflict(
                code="INFEASIBLE_WALL_CAPACITY", subject_id=wall_id,
                constraint_ids=tuple(sorted(c.constraint_id for c in cs)),
                message=f"{len(cs)} object(s) require {total_width:.2f} m of {wall_id}, "
                       f"which is only {length:.2f} m long"))
    return out


def compile_intents(spatial: SpatialScene, intents: Sequence[Intent]) -> ConstraintSet:
    """SpatialScene + Intent[] -> ConstraintSet. Never places anything."""
    constraints: list[Constraint] = []
    unsupported: list[str] = []

    for intent in intents:
        if intent.predicate not in PREDICATE_TO_TYPE:
            unsupported.append(intent.intent_id)
            continue
        constraints.append(_compile_one(intent))

    conflicts = (_detect_orientation_conflicts(constraints)
                + _detect_contact_conflicts(constraints)
                + _check_wall_capacity(constraints, spatial))

    return ConstraintSet(constraints=tuple(constraints),
                         unsupported=tuple(sorted(unsupported)),
                         conflicts=tuple(sorted(conflicts, key=lambda c: (c.code, c.subject_id))))


# ── §31: constraint -> candidate-generation hints for the EXISTING solver ──
#
# This does NOT call the solver and does NOT place anything - it fills the
# SAME `ObjectPlanItem.relation`/`.support_key`/`.faces` fields
# `app/planning/compiler.py::place_objects` already reads (via
# `_relation_candidates`/`_pick_support`/`_faces_rank`), so the existing,
# unmodified solver narrows/orders its own candidates exactly as it does
# today for a moodboard-derived hint. `app/planning/compiler.py` is not
# imported or modified by this function - only its DATA CONTRACT
# (`ObjectPlanItem`'s fields) is targeted, from research code.
#
# HONEST LIMITATION, NAMED RATHER THAN HIDDEN: production's `RelationType`
# (`in_front_of, beside, under, around, facing, against_wall`) has no
# "between" or "centered" value. POSITION-type constraints (BETWEEN,
# CENTERED_IN_ROOM) can be EVALUATED against the final scene
# (constraint_evaluator.py) but cannot bias candidate generation through
# this bridge without adding a new `RelationType` to production - out of
# this phase's minimal-footprint scope (§53). They are approximated here as
# "beside" the nearer of their two targets, which is the closest existing
# lever, and the approximation is recorded in the returned notes so nothing
# is silently pretended to be a real BETWEEN placement bias.
#
# P9 CORRECTION (docs/spatial_architecture/decisions.md's P9 entry, "P8
# Failure Reproduction"): ORIENTATION used to set `ObjectPlanItem.faces`
# (free text) instead of `.relation`. That was the measured root cause of
# P8's own FACES failure - `_ordered()` (app/planning/compiler.py) only
# tracks a dependency via `item.relation.target_key`, never `.faces`, so
# when the subject's `ANCHOR_RANK` is lower than its target's (a sofa
# ranks 0, a tv_unit ranks 1), the target had not been placed yet at the
# moment `_faces_rank` needed its position - the hint had NO EFFECT, not
# because no satisfying candidate existed (one always did - production's
# own `_relation_candidates("facing", ...)` already generates exactly the
# right, cosine-filtered, best-aligned-first candidates) but because
# nothing told the compiler to place the target first. Routing ORIENTATION
# through `ObjectRelation(type="facing", ...)` fixes BOTH problems at once,
# with ZERO new candidate-generation code: it enters `_ordered()`'s
# existing dependency graph (target places first) AND reuses production's
# own already-correct analytical facing-candidate generator. Verified by a
# standalone critical experiment (P9 §41) before this fix was written:
# switching only this one wire, nothing else, took the angular error from
# 100.1 degrees to 0.0 degrees on the exact P8 brief-demo scene.
_TYPE_TO_RELATION: dict[ConstraintType, str] = {
    ConstraintType.CONTACT: "against_wall",
    ConstraintType.ORIENTATION: "facing",  # P9 fix - see note above
    ConstraintType.DISTANCE: "beside",     # approximation - see candidate_generators.py for the P9 fix
    ConstraintType.POSITION: "beside",     # approximation - see candidate_generators.py for the P9 fix
}


def apply_constraints_to_plan(items: list[ObjectPlanItem], constraint_set: ConstraintSet,
                              spatial: SpatialScene) -> list[str]:
    """Mutates `items` (matched by `object_key == subject_id`, the demo's own
    convention - see constraint_benchmark.py) with `.relation`/`.support_key`
    fields derived from constraints, WITHOUT overwriting anything the caller
    already set (matching `apply_spatial_graph`'s own "never overwrite what
    the planner decided" rule one stage upstream). Returns human-readable
    notes, never raises on an unmapped case.

    Runs BEFORE placement (this is what biases candidate generation AND
    participates in `_ordered()`'s dependency graph via `.relation.
    target_key`), so a constraint's target is looked up among the PLAN
    ITEMS (by object_key), never in `spatial.scene` - the scene has no
    objects yet at this point in the pipeline (`place_objects` has not
    run), which is also why this function never needs `spatial` for
    geometry, only `known_entity_ids`-style existence checks are
    meaningless here; `spatial` is accepted for a future caller that
    pre-populates some objects (e.g. the photo path) but is not read for
    object lookups today.

    DISTANCE (with an explicit `distance_m`) and POSITION (BETWEEN) are
    deliberately NOT routed to `.relation` here even though `_TYPE_TO_
    RELATION` names an approximate "beside" type for them - `place_objects`
    cannot represent an explicit metric distance or a between-two-targets
    region through any existing `RelationType` (§3 of `candidate_contract.md`),
    so P9 handles those through `candidate_generators.py`'s own post-
    placement candidate regeneration (`regenerate_after_placement`)
    instead, which can express a real numeric distance/segment constraint
    that `ObjectRelation` cannot. Only `CONTACT`/`ORIENTATION`/`SUPPORT`
    route through the plan-item bridge below.
    """
    by_key = {i.object_key: i for i in items}
    notes: list[str] = []

    for c in constraint_set.constraints:
        item = by_key.get(c.subject_id)
        if item is None:
            continue

        if c.constraint_type == ConstraintType.SUPPORT and not item.support_key:
            item.support_key = c.target_id
            notes.append(f"{c.subject_id}: support_key <- {c.target_id} (from {c.constraint_id})")

        elif (c.constraint_type in (ConstraintType.CONTACT, ConstraintType.ORIENTATION)
             and item.relation is None):
            rel_type = _TYPE_TO_RELATION[c.constraint_type]
            target_key = c.target_id if rel_type != "against_wall" else None
            item.relation = ObjectRelation(type=rel_type, target_key=target_key)  # type: ignore[arg-type]
            notes.append(f"{c.subject_id}: relation <- {rel_type}({target_key}) "
                        f"(from {c.constraint_id})")

    return notes


__all__ = ["PREDICATE_TO_TYPE", "DEFAULT_HARDNESS", "compile_intents",
           "apply_constraints_to_plan"]

"""P8 constraint model: a formal, typed, evaluatable requirement derived
from an `Intent` (intent_model.py) or a P7 `GeometricRelation`.

TWO SEPARATE AXES, KEPT SEPARATE ON PURPOSE. A `Constraint` has a lifecycle
STAGE (`ConstraintStatus`: where is this object in its own processing) and,
once evaluated, a VERDICT (`Verdict`: what did evaluating it find). The P8
brief's §9/§23/§27 could be read as wanting one combined status field
(CREATED -> ... -> SATISFIED/VIOLATED/UNKNOWN); this implementation keeps
them as two enums because collapsing them is exactly the mistake P7 avoided
for relations (`RelationStatus` there also does not conflate "has this been
checked" with "what did the check find" - CONTRADICTED vs UNRESOLVED are
different questions). Concretely: a constraint can be COMPILED (a lifecycle
stage) and its most recent evaluation can be VIOLATED (a verdict) - asking
"what stage is it at" and "is it currently satisfied" independently is what
lets `constraint_evaluator.evaluate_all` be called again after repair (§40)
without needing to re-run compilation.

`ConstraintResult` is a SEPARATE, small immutable record (not a field
mutated on `Constraint` itself) precisely so `Constraint` stays exactly as
immutable as `GeometricRelation`/`Intent` - re-evaluating never edits the
constraint, it produces a new `ConstraintResult` a caller pairs with it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

SpatialConfidence = str   # "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN" - see intent_model.py


class ConstraintType(str, Enum):
    """§10: the ten named categories. Only the ones with a real geometric
    evaluator (constraint_evaluator.py) and a real relation/intent source
    are ever constructed by `constraint_compiler.compile_intents` - the rest
    are named here, complete, and documented as reserved so a future
    predicate has a home without a breaking enum change (the exact pattern
    P7's `relation_contract.md` already used for GEOMETRIC_INVARIANT/
    FUNCTIONAL)."""

    POSITION = "position"          # BETWEEN, CENTERED_IN_ROOM - built (§20/§21, room case only)
    ORIENTATION = "orientation"    # FACES - built (§15)
    DISTANCE = "distance"          # NEAR / explicit user distance - built (§19)
    CONTACT = "contact"            # AGAINST_WALL - built (§16, reuses P7's own verifier logic)
    SUPPORT = "support"            # SUPPORTED_BY / ON_TOP_OF - built (§17)
    CONTAINMENT = "containment"    # INSIDE / CONTAINS - built (§18)
    CLEARANCE = "clearance"        # CLEAR_OF - built (§14), wraps P2's clearance_engine, not reimplemented
    ALIGNMENT = "alignment"        # reserved - no current downstream consumer (§22)
    RELATION = "relation"          # reserved - generic bucket, no distinct evaluator justified
    CIRCULATION = "circulation"    # reserved - P2's circulation_violations already validates this
                                    # directly on Scene (§41: do not duplicate validation)


class Hardness(str, Enum):
    """§11/§34: HARD would mean failure blocks scene acceptance; SOFT means a
    preference that was not satisfied. See constraint_contract.md's "hard/
    soft policy" for why every constraint this phase constructs is SOFT -
    the short version: the existing solver (`app.planning.compiler.
    place_objects`) has exactly one mechanism for consuming a relation-
    derived preference today (candidate re-ordering), and re-ordering cannot
    reject a scene - claiming HARD without an enforcement mechanism would be
    reporting a guarantee this architecture does not keep. Allure's REAL
    hard constraints (collision, room-bounds, door-clearance) remain exactly
    where they already were: `app.spatial.validation`, untouched, never
    duplicated here (§41)."""

    HARD = "hard"
    SOFT = "soft"


class ConstraintStatus(str, Enum):
    """§27's lifecycle stage - advanced by `constraint_compiler`/a caller,
    never inferred from geometry (that is `Verdict`'s job)."""

    CREATED = "created"
    NORMALIZED = "normalized"
    COMPILED = "compiled"
    REPAIRED = "repaired"          # set by a caller after invoking P4 repair (§40)
    RE_EVALUATED = "re_evaluated"  # set by a caller after a second evaluate_all() pass


class Verdict(str, Enum):
    """§23: what evaluating a constraint against the CURRENT scene found.
    Never derived by sampling/scoring - always by a deterministic rule."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"     # §38: insufficient geometry, ambiguous target, unsupported relation
    PARTIAL = "partial"     # used only where "partially satisfied" is a real, distinct outcome
                            # (e.g. BETWEEN: on the segment but outside the lateral tolerance)


def constraint_id(subject_id: str, constraint_type: ConstraintType, target_id: str,
                  parameters: dict) -> str:
    """Deterministic, content-addressed - identical discipline to P7's
    `relation_id` and this phase's own `intent_id`: `hashlib.sha1`, never
    Python's salted builtin `hash()`."""
    param_repr = ",".join(f"{k}={parameters[k]!r}" for k in sorted(parameters))
    raw = f"{subject_id}|{constraint_type.value}|{target_id}|{param_repr}".encode("utf-8")
    return f"constraint_{hashlib.sha1(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class Constraint:
    """§9's canonical constraint object. Answers, per field:
    what/relative-to-what (subject_id/target_id), what condition
    (constraint_type + parameters), where from (source/provenance), how
    important (priority), can it fail the scene (hardness), how sure
    (confidence), where in its life (status)."""

    constraint_id: str
    constraint_type: ConstraintType
    subject_id: str
    target_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    source_intent_id: str = ""     # the Intent (or "" if none) this was compiled from
    provenance: str = ""
    priority: int = 4              # IntentPriority value - int here to avoid a hard import cycle
    hardness: Hardness = Hardness.SOFT
    confidence: SpatialConfidence = "MEDIUM"
    status: ConstraintStatus = ConstraintStatus.CREATED


@dataclass(frozen=True)
class ConstraintResult:
    """§23/§24/§39: the outcome of one `evaluate()` call. `error`/`error_kind`
    are populated whenever the constraint type has a natural numeric error
    (angular degrees, metres, ...) - never coerced to a bare boolean, per §24."""

    constraint_id: str
    verdict: Verdict
    error: Optional[float] = None
    error_kind: str = ""            # "angular_deg" | "distance_m" | "lateral_deficit_m" | ...
    message: str = ""


@dataclass(frozen=True)
class ConstraintConflict:
    """§35: two (or more) constraints on the same subject that cannot both
    hold - detected at COMPILE time (before the solver ever runs), never
    silently resolved by picking whichever was inserted last."""

    code: str
    subject_id: str
    constraint_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ConstraintSet:
    """The compiler's output: every constraint it could formally represent,
    every intent it could not (kept, never discarded - §14 "do not allow
    arbitrary text to become constraints" cuts both ways: an unsupported
    relation is also not silently dropped), and the conflicts/feasibility
    findings from compile-time analysis (§33/§35)."""

    constraints: tuple[Constraint, ...] = field(default_factory=tuple)
    unsupported: tuple[str, ...] = field(default_factory=tuple)   # intent_ids with no mapping
    conflicts: tuple[ConstraintConflict, ...] = field(default_factory=tuple)

    def for_subject(self, subject_id: str) -> tuple[Constraint, ...]:
        return tuple(c for c in self.constraints if c.subject_id == subject_id)

    def by_type(self, constraint_type: ConstraintType) -> tuple[Constraint, ...]:
        return tuple(c for c in self.constraints if c.constraint_type == constraint_type)


__all__ = ["ConstraintType", "Hardness", "ConstraintStatus", "Verdict", "constraint_id",
           "Constraint", "ConstraintResult", "ConstraintConflict", "ConstraintSet"]

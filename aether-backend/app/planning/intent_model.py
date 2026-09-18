"""P8 intent model: what someone (a user or a model) WANTS, kept distinct
from what P7's `GeometricRelation` observes/derives.

WHY A SEPARATE TYPE, NOT A SECOND GRAPH. §7 of the P8 brief asks whether
intent should reuse `relation_model.GeometricRelation`, a specialised type,
or a thin extension - and explicitly forbids "a second parallel graph."
`Intent` is the thin extension: it lives in the SAME `SpatialScene`-adjacent
world P7 built (an `Intent` names the same entities `GeometricRelation`
does, subject/predicate/object), passed alongside a `SpatialScene` to the
compiler as a second, small argument - not a second scene, not a second
container type with its own lookup machinery. It needed its OWN dataclass
rather than reusing `GeometricRelation` for two concrete reasons, not
aesthetic ones:

  1. `parameters: dict` - a WANT can carry a number the observation-side
     relation never needs ("keep 1.5 m away", "15 degree tolerance").
     `GeometricRelation` has no such field and none of P7's five call sites
     need one - adding it there for P8's sake would be widening a frozen,
     tested P7 type for a P8-only need.
  2. `IntentSource` is a five-way split (USER_ASSERTED / MODEL_INFERRED /
     OBSERVED / DERIVED / SOLVER_DECIDED) - richer than P7's four-way
     `SpatialSource` (semantic/geometry/semantic+geometry/placement), because
     P8 must distinguish a user's own words from a model's inference in a
     way P7 never had to (P7's photo bridge never received free-standing
     user text at all).

`relation_model.py` (P7) is UNCHANGED by this phase - confirmed by this
phase's own regression run (docs/spatial_architecture/decisions.md's P8
entry). `Intent` and `GeometricRelation` are siblings a `ConstraintCompiler`
reads from, not a hierarchy.

NO `status` FIELD, UNLIKE THE BRIEF'S OWN SKETCH. The brief's §7 sketch
lists `status` on `Intent` itself. This implementation omits it: no caller
in this program ever withdraws or supersedes an intent once created (no
review/editing UI exists yet that would produce SUPERSEDED/WITHDRAWN), so a
mutable-seeming lifecycle field with only ever one value would be exactly
the "field with no consumer" §9 warns against for `Constraint`. Lifecycle
instead lives entirely on the DERIVED `Constraint` (see `constraint_model.py`
- `ConstraintStatus`), which real code (`ConstraintCompiler`,
`constraint_evaluator`) actually advances. `Intent` itself is an immutable
fact record, exactly like `GeometricRelation`: "this was asked for," full
stop - `Intent` is never marked stale or re-verified, because unlike a
DERIVED_GEOMETRY relation an intent is not a claim about current geometry to
begin with, it is a request. If a future caller needs to retract one, that
caller simply stops including it in the next `compile_intents` call - no
mutation needed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

SpatialConfidence = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]


class IntentSource(str, Enum):
    """§8: five sources, kept distinct so a model's guess can never be
    silently promoted to a user's request."""

    #: The user said so, in their own words ("put the sofa against the
    #: north wall") - this program's highest-precedence source (§12/§46).
    USER_ASSERTED = "user_asserted"
    #: A model (VLM/LLM) proposed it without the user stating it - e.g. a
    #: moodboard reader's free-text `against`/`faces` hint, or a future
    #: brief-parser's guess at an unstated preference.
    MODEL_INFERRED = "model_inferred"
    #: Read directly off evidence - what P7 calls a FACT (a photo's
    #: measured wall contact). An "intent" sourced this way is really "keep
    #: it where it already, verifiably, is" - included so a caller can
    #: express "preserve the observed state" as an intent the compiler
    #: understands the same way as any other, rather than a special case.
    OBSERVED = "observed"
    #: Computed from other intents/relations by a deterministic rule (e.g.
    #: a functional template, §45, expanding into several constraints) -
    #: never itself the original ask.
    DERIVED = "derived"
    #: What the solver actually chose - included so `IntentSource` is a
    #: complete, closed set a switch statement can exhaustively handle, not
    #: because any constructor in this phase produces an `Intent` at this
    #: source (a decision is recorded as geometry + provenance, per P7, not
    #: as a new intent - see `constraint_lifecycle.md`).
    SOLVER_DECIDED = "solver_decided"


class IntentPriority(int, Enum):
    """§12/§46: a deterministic PRECEDENCE CONTRACT, not a numeric
    optimisation score - lower value always outranks higher, with no
    in-between weighting. `SYSTEM_REQUIRED` and `GEOMETRIC_VALIDITY` are
    reserved (see class docstring): nothing in this phase constructs an
    `Intent` at either level, because Allure's existing hard geometric
    checks (collision/room-bounds/door-clearance) live in `validate_object`,
    never pass through the intent/constraint layer at all (§41 - do not
    duplicate validation) - the levels are named so a future caller has a
    place for them without a breaking enum change, not populated
    speculatively now."""

    USER_EXPLICIT = 0
    USER_IMPLICIT = 1
    SYSTEM_REQUIRED = 2       # reserved - see class docstring
    GEOMETRIC_VALIDITY = 3    # reserved - see class docstring
    MODEL_INFERRED = 4
    STYLE_PREFERENCE = 5


#: The source -> default-priority mapping this phase actually uses. A
#: caller may always override priority explicitly (`Intent(..., priority=)`);
#: this is only the sensible default so most callers never need to.
DEFAULT_PRIORITY: dict[IntentSource, IntentPriority] = {
    IntentSource.USER_ASSERTED: IntentPriority.USER_EXPLICIT,
    IntentSource.MODEL_INFERRED: IntentPriority.MODEL_INFERRED,
    IntentSource.OBSERVED: IntentPriority.USER_IMPLICIT,
    IntentSource.DERIVED: IntentPriority.MODEL_INFERRED,
    IntentSource.SOLVER_DECIDED: IntentPriority.SYSTEM_REQUIRED,
}


def intent_id(subject_id: str, predicate: str, target_id: str, parameters: dict) -> str:
    """Deterministic, content-addressed - the same discipline as P7's
    `relation_model.relation_id`: `hashlib.sha1`, never Python's salted
    builtin `hash()`. `parameters` is included in the digest (sorted, so key
    order never matters) because two intents naming the same pair with
    different numeric asks (e.g. two different explicit distances) are
    genuinely different intents and must not collide."""
    param_repr = ",".join(f"{k}={parameters[k]!r}" for k in sorted(parameters))
    raw = f"{subject_id}|{predicate}|{target_id}|{param_repr}".encode("utf-8")
    return f"intent_{hashlib.sha1(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class Intent:
    """One want, named as `subject -> predicate -> target`, exactly like a
    `GeometricRelation` - see the module docstring for why this is a sibling
    type, not a rewrite of that one."""

    intent_id: str
    subject_id: str
    predicate: str
    target_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    source: IntentSource = IntentSource.MODEL_INFERRED
    provenance: str = ""
    confidence: SpatialConfidence = "MEDIUM"
    priority: IntentPriority = IntentPriority.MODEL_INFERRED

    @classmethod
    def create(cls, subject_id: str, predicate: str, target_id: str = "", *,
              parameters: dict | None = None, source: IntentSource = IntentSource.MODEL_INFERRED,
              provenance: str, confidence: SpatialConfidence = "MEDIUM",
              priority: IntentPriority | None = None) -> "Intent":
        """The one real constructor (bare `Intent(...)` still works for tests
        that want full control, but every production-shaped caller should use
        this): assigns the deterministic id and, if `priority` is not given,
        the source's own sensible default (`DEFAULT_PRIORITY`) rather than
        silently defaulting every intent to the same weight regardless of
        who asked. NOTE: `priority or DEFAULT_PRIORITY[source]` would be
        wrong here - `IntentPriority.USER_EXPLICIT == 0`, which is falsy in
        Python, so an explicit highest-precedence priority would be silently
        replaced by the default. `is None` is required."""
        params = dict(parameters or {})
        resolved_priority = priority if priority is not None else DEFAULT_PRIORITY[source]
        return cls(intent_id=intent_id(subject_id, predicate, target_id, params),
                  subject_id=subject_id, predicate=predicate, target_id=target_id,
                  parameters=params, source=source, provenance=provenance,
                  confidence=confidence, priority=resolved_priority)


__all__ = ["IntentSource", "IntentPriority", "DEFAULT_PRIORITY", "Intent", "intent_id"]

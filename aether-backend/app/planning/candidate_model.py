"""P9 candidate model: an explicit, typed, provenance-carrying placement
candidate - what `app/planning/compiler.py`'s own
`Candidate = tuple[Vec2, float, Optional[float]]` has always been
structurally, made inspectable.

WHY THIS EXISTS ALONGSIDE PRODUCTION'S OWN TUPLE CANDIDATE, NOT INSTEAD OF
IT. `place_objects` is unmodified in this phase (§38, §32 - no second
solver) and still consumes its own `(Vec2, float, Optional[float])` tuples
internally. This typed `Candidate` is used ONLY by the code this phase adds
(`candidate_generators.py`'s NEW distance/between generators, run as a
post-placement regeneration step - see that module's docstring for why) -
it never needs to become `app/`'s own candidate shape, because it never
enters `place_objects`'s internal loop. Where P9's fix for ORIENTATION did
NOT need a new candidate type at all (routing through production's existing
`"facing"` `RelationType` was sufficient - see `candidate_contract.md`'s
"critical experiment" section), this typed candidate exists specifically
for the NEW candidate content (DISTANCE, BETWEEN) production has no
vocabulary for.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

Vec2 = tuple[float, float]


class CandidateSource(str, Enum):
    """§25: every candidate must be explainable. Named per the constraint
    category that produced it - matches `constraint_model.ConstraintType`
    exactly where a generator exists for that type."""

    DISTANCE = "distance"      # ring-sampled around a target at a requested metric distance
    BETWEEN = "between"        # segment-sampled between two targets


@dataclass(frozen=True)
class Candidate:
    """§6's minimum necessary fields - position, orientation, and enough
    provenance to answer "why does this candidate exist" without a field
    nothing reads (no separate `placement_class`/`anchor_entity` fields:
    `constraint_id` + `source` already answer §25's own worked example)."""

    position: Vec2
    rotation_y: float
    y: Optional[float]              # None = caller's own default floor height, matching compiler.py's own tuple shape
    source: CandidateSource
    constraint_id: str
    provenance: str


def candidate_key(c: Candidate) -> tuple:
    """§24: deterministic identity for deduplication - position and
    orientation, rounded to the same precision `app/planning/compiler.py`
    itself rounds a placed object's `position`/`rotation_y` to (3 and 4
    decimal places respectively) before it ever reaches `Scene`, so two
    candidates that would place indistinguishably in the final scene are
    treated as the same candidate regardless of which generator proposed
    them first."""
    return (round(c.position[0], 3), round(c.position[1], 3), round(c.rotation_y, 4))


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Keeps the FIRST occurrence of each distinct pose, in input order -
    deterministic because the input order is itself deterministic (every
    generator in `candidate_generators.py` produces its output in a fixed,
    seed-free order). Never lets a duplicate change ranking: a pose that
    happens to satisfy two different generators counts once."""
    seen: set[tuple] = set()
    out: list[Candidate] = []
    for c in candidates:
        key = candidate_key(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


__all__ = ["CandidateSource", "Candidate", "candidate_key", "dedupe"]

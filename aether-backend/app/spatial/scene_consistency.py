"""P7 consistency layer: DIAGNOSE a `SpatialScene`, never repair it.

Repair already exists and is out of scope here (P4's `repair_engine.py`,
frozen and tested). This module answers a narrower, read-only question: given
a `SpatialScene` as it stands right now, what contradicts what? It never
calls `recompute_relations` (that MUTATES relation status, i.e. it changes
belief) and never touches `scene.objects` - `check_consistency` takes a
`SpatialScene` and returns findings, full stop, matching the "validation must
be strictly read-only" contract this phase's docs (scene_state_lifecycle.md)
require of every reader in this position, exactly like `app.spatial.
validation.validate_scene` never writes to the `Scene` it inspects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.spatial.relation_model import (
    RelationKind, RelationStatus)
from app.spatial.scene_model import SpatialScene

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ConsistencyFinding:
    code: str
    severity: Severity
    subject_id: str
    object_id: str
    message: str


def _orphan_references(spatial: SpatialScene) -> list[ConsistencyFinding]:
    known = spatial.known_entity_ids()
    out = []
    for rel in spatial.relations:
        missing = [e for e in (rel.subject_id, rel.object_id)
                  if e and e not in known]
        if missing:
            out.append(ConsistencyFinding(
                code="ORPHAN_REFERENCE", severity="error", subject_id=rel.subject_id,
                object_id=rel.object_id,
                message=f"{rel.predicate} names {missing} which is not in the scene"))
    return out


def _duplicate_relations(spatial: SpatialScene) -> list[ConsistencyFinding]:
    seen: dict[tuple, int] = {}
    for rel in spatial.relations:
        key = (rel.subject_id, rel.predicate, rel.object_id)
        seen[key] = seen.get(key, 0) + 1
    out = []
    for (subject, predicate, obj), count in seen.items():
        if count > 1:
            out.append(ConsistencyFinding(
                code="DUPLICATE_RELATION", severity="warning", subject_id=subject,
                object_id=obj, message=f"{predicate} recorded {count} times for the same pair"))
    return out


def _contradictory_wall_assignment(spatial: SpatialScene) -> list[ConsistencyFinding]:
    """One object cannot be genuinely AGAINST_WALL two different walls at
    once (unless it sits exactly in a corner, which this program's wall
    model represents as two separate, individually-true relations only when
    both gaps are within tolerance - a real corner case, not a bug; this
    check fires only when BOTH relations are asserted with status other than
    CONTRADICTED, i.e. both currently claimed true)."""
    by_subject: dict[str, list] = {}
    for rel in spatial.relations:
        if rel.predicate == "AGAINST_WALL" and rel.status != RelationStatus.CONTRADICTED:
            by_subject.setdefault(rel.subject_id, []).append(rel)
    out = []
    for subject, rels in by_subject.items():
        walls = {r.object_id for r in rels}
        if len(walls) > 1:
            out.append(ConsistencyFinding(
                code="MULTIPLE_WALL_CLAIMS", severity="warning", subject_id=subject,
                object_id=",".join(sorted(walls)),
                message=f"claims AGAINST_WALL for {len(walls)} different walls at once "
                       f"(possibly a real corner - not auto-resolved here)"))
    return out


def _conflicting_faces(spatial: SpatialScene) -> list[ConsistencyFinding]:
    """A single object facing two different, non-adjacent targets at once is
    a claim this program cannot make sense of - unlike AGAINST_WALL (a real
    corner can touch two walls), an object has one front. Flags it as a
    conflict for a human/upstream reader to resolve, exactly the same
    "surface, do not silently pick a winner" rule `SpatialConflict` already
    applies one stage upstream."""
    by_subject: dict[str, list] = {}
    for rel in spatial.relations:
        if rel.predicate == "FACES" and rel.status != RelationStatus.CONTRADICTED:
            by_subject.setdefault(rel.subject_id, []).append(rel)
    out = []
    for subject, rels in by_subject.items():
        targets = {r.object_id for r in rels}
        if len(targets) > 1:
            out.append(ConsistencyFinding(
                code="CONFLICTING_FACES", severity="warning", subject_id=subject,
                object_id=",".join(sorted(targets)),
                message=f"claims FACES for {len(targets)} different targets at once"))
    return out


def _circular_containment(spatial: SpatialScene) -> list[ConsistencyFinding]:
    """A CONTAINS B and B CONTAINS A (directly, not transitively - transitive
    cycle detection is not built because no scenario measured here produces
    a containment chain longer than two hops) is geometrically impossible:
    two solid footprints cannot each lie inside the other."""
    contains_pairs = {(r.subject_id, r.object_id) for r in spatial.relations
                      if r.predicate == "CONTAINS" and r.status != RelationStatus.CONTRADICTED}
    cyclic_pairs: dict[tuple, ConsistencyFinding] = {}
    for a, b in sorted(contains_pairs):
        if (b, a) in contains_pairs:
            key = tuple(sorted((a, b)))
            cyclic_pairs.setdefault(key, ConsistencyFinding(
                code="CIRCULAR_CONTAINMENT", severity="error", subject_id=key[0], object_id=key[1],
                message=f"{key[0]} CONTAINS {key[1]} and {key[1]} CONTAINS {key[0]} - "
                       f"not geometrically possible"))
    return list(cyclic_pairs.values())


def _stale_or_contradicted(spatial: SpatialScene) -> list[ConsistencyFinding]:
    out = []
    for rel in spatial.relations:
        if rel.status == RelationStatus.STALE:
            out.append(ConsistencyFinding(
                code="STALE_RELATION", severity="warning", subject_id=rel.subject_id,
                object_id=rel.object_id,
                message=f"{rel.predicate} has not been re-verified since the subject moved"))
        elif rel.status == RelationStatus.CONTRADICTED:
            out.append(ConsistencyFinding(
                code="CONTRADICTED_RELATION", severity="error", subject_id=rel.subject_id,
                object_id=rel.object_id,
                message=f"{rel.predicate} was checked against current geometry and found false"))
    return out


def _unsupported_hypotheses(spatial: SpatialScene) -> list[ConsistencyFinding]:
    """A SEMANTIC_HYPOTHESIS or EVIDENCE_CLAIM relation with no evidence
    trail at all is not automatically wrong, but it is a claim this program
    cannot explain if asked "why do we believe this?" - the fifth of the P7
    brief's five questions - so it is surfaced, not silently trusted."""
    out = []
    for rel in spatial.relations:
        if (rel.kind in (RelationKind.SEMANTIC_HYPOTHESIS, RelationKind.EVIDENCE_CLAIM)
                and not rel.evidence_refs and not rel.provenance):
            out.append(ConsistencyFinding(
                code="UNSUPPORTED_HYPOTHESIS", severity="warning", subject_id=rel.subject_id,
                object_id=rel.object_id,
                message=f"{rel.predicate} carries no evidence_refs and no provenance"))
    return out


def check_consistency(spatial: SpatialScene) -> list[ConsistencyFinding]:
    """Read-only. Returns findings sorted deterministically (never in set/dict
    iteration order) so two runs over the same scene produce byte-identical
    output - the same discipline P4/P6 required of solver tie-breaks."""
    findings = (
        _orphan_references(spatial) + _duplicate_relations(spatial)
        + _contradictory_wall_assignment(spatial) + _conflicting_faces(spatial)
        + _circular_containment(spatial) + _stale_or_contradicted(spatial)
        + _unsupported_hypotheses(spatial))
    return sorted(findings, key=lambda f: (f.code, f.subject_id, f.object_id))


__all__ = ["ConsistencyFinding", "check_consistency"]

"""P7 relation taxonomy: what kind of claim a relation is, and whether it
currently holds. Wraps production's own `SpatialPredicate`
(`app/intelligence/schema.py`) - it does not invent a second predicate
vocabulary, it classifies the one that already exists, plus the two
predicates the photo bridge already emits as raw dicts
(`AGAINST_WALL`, `SUPPORTED_BY` - `research/spatial_architecture/
scene_from_photo.py`).

See docs/spatial_architecture/relation_contract.md for the six-category
research and the contradiction-status research this operationalises.

DETERMINISTIC IDS. `relation_id` uses `hashlib.sha1`, never Python's builtin
`hash()`, which is salted per-process (`PYTHONHASHSEED`) unless disabled -
exactly the class of bug P4 found in `object_id` generation and P6's report
flagged as a must-not-recur risk (dict/set iteration order, hash-based tie
breaks). sha1 of a fixed, ordered string is bit-identical across processes
and Python versions.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

Vec3 = tuple[float, float, float]

# Re-exported literal shapes, matching app/intelligence/schema.py exactly so
# a GeometricRelation can carry a real SpatialRelation's confidence/source/
# frame without translation.
SpatialConfidence = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
SpatialSource = Literal["semantic", "geometry", "semantic+geometry", "placement"]
Frame = Literal["floor_plan", "camera"]


class RelationKind(str, Enum):
    """Six categories, per the P7 brief. A relation is exactly one of these -
    never inferred at read time, always assigned when the relation is built."""

    #: True by construction of the geometry itself (a wall's own start/end,
    #: an object's own footprint) - not really a "relation" between two
    #: entities so much as a property, listed for completeness; no predicate
    #: in this codebase is currently modelled at this level (Scene's fields
    #: already carry these directly, so wrapping them as a relation would be
    #: redundant data with two owners - see scene_model.md's invariants).
    GEOMETRIC_INVARIANT = "geometric_invariant"
    #: Computed FROM the current geometry, and therefore only true as long as
    #: the geometry it was computed from hasn't changed - AGAINST_WALL,
    #: SUPPORTED_BY, NEAR, ADJACENT_TO, OVERLAPS, ABOVE/BELOW/LEFT_OF/RIGHT_OF,
    #: ON_TOP_OF. Subject to staleness; see `scene_graph.recompute_relations`.
    DERIVED_GEOMETRY = "derived_geometry"
    #: A model's claim about meaning, not measured geometry - FACES,
    #: FACES_ROOM, GROUPED_WITH. Can be evidenced by geometry corroborating it
    #: (promoted confidence) but is never ITSELF a geometric fact.
    SEMANTIC_HYPOTHESIS = "semantic_hypothesis"
    #: A usability claim about a pair, from P2's clearance engine - not
    #: currently reified as a SpatialRelation (clearance_engine.py emits
    #: ClearanceViolation, not a positive relation), named here so the
    #: taxonomy has a slot ready rather than silently omitting a whole
    #: category the brief asks for.
    FUNCTIONAL = "functional"
    #: A placement DECISION the solver made and recorded, not evidence about
    #: the world - e.g. "object X was moved to satisfy AGAINST_WALL". P4's
    #: RepairRecord is this category's existing, working implementation;
    #: not re-modelled here, only classified.
    SOLVER_CONSTRAINT = "solver_constraint"
    #: A raw perception claim that has not yet been geometrically verified -
    #: the `against`/`faces` free-text hints `_semantic_relations`
    #: (app/planning/spatial_graph.py) turns into AGAINST/FACES/AGAINST_WALL
    #: at LOW confidence, before any geometry corroborates them.
    EVIDENCE_CLAIM = "evidence_claim"


#: Every predicate this codebase currently produces, classified once. Two
#: predicates (AGAINST_WALL, SUPPORTED_BY) appear in both the moodboard-stage
#: SpatialPredicate enum AND the photo-bridge's raw relation dicts; the
#: classification is the same claim either way - the CALLER decides
#: EVIDENCE_CLAIM vs DERIVED_GEOMETRY by which `source` produced it (see
#: `classify`), because production's own reader emits `AGAINST_WALL` at
#: `source="semantic"` before any wall is known, and the photo bridge emits
#: the identical predicate at `source="geometry"` once one is.
#: CONTAINS / INSIDE are formalised here per the P7 brief's explicit request
#: (§32) even though no production reader emits them yet (no built container
#: object - a cabinet, a drawer - has a containment detector). They are
#: DERIVED_GEOMETRY, not invented predicates with no geometric test: a real
#: implementation would be "B's footprint lies inside A's footprint", exactly
#: as measurable as AGAINST_WALL's "distance to a wall segment" is. Kept out
#: of `app.intelligence.schema.SpatialPredicate` (unchanged, per the
#: reuse-not-fork rule) - CONTAINS/INSIDE exist only in this research-layer
#: taxonomy until a real evidence source produces one.
_GEOMETRY_SOURCED = frozenset({
    "NEAR", "ADJACENT_TO", "OVERLAPS", "ON_TOP_OF", "SUPPORTED_BY",
    "AGAINST_WALL", "LEFT_OF", "RIGHT_OF", "ABOVE", "BELOW",
    "CONTAINS", "INSIDE",
})

#: Directional inverse pairs - A CONTAINS B implies B INSIDE A and vice
#: versa. Used only by the circular-containment consistency check; not a
#: general inference engine (that would be building the "relation ->
#: constraint" bridge into something more general than any measured need
#: justifies - see relation_contract.md's rejected-sophistication note).
INVERSE_PREDICATES: dict[str, str] = {"CONTAINS": "INSIDE", "INSIDE": "CONTAINS"}
_SEMANTIC_ONLY = frozenset({"FACES", "FACES_ROOM", "GROUPED_WITH", "AGAINST"})


def classify(predicate: str, source: SpatialSource) -> RelationKind:
    """One predicate can be evidence-claim or derived-geometry depending on
    HOW it was produced (a stated hint vs. a geometric measurement) - the
    exact distinction `_merge` in `app/planning/spatial_graph.py` already
    tracks via `source`, reused here rather than re-derived. `"placement"`
    counts as geometry-grounded, not a raw guess: production's own
    `_semantic_relations` emits SUPPORTED_BY/ON_TOP_OF at `source="placement"`
    for an item the reader recorded as physically resting on something - the
    claim is about where the object already sits, not a stated preference."""
    if predicate in _SEMANTIC_ONLY:
        return RelationKind.SEMANTIC_HYPOTHESIS
    if predicate in _GEOMETRY_SOURCED:
        if source in ("geometry", "semantic+geometry", "placement"):
            return RelationKind.DERIVED_GEOMETRY
        return RelationKind.EVIDENCE_CLAIM
    # Unknown predicate (future extension): conservative default - a claim,
    # not yet a verified geometric fact.
    return RelationKind.EVIDENCE_CLAIM


class RelationStatus(str, Enum):
    """Deterministic, not probabilistic - a status is set by a rule
    (`scene_consistency.py` / `scene_graph.recompute_relations`), never
    sampled or scored. See relation_contract.md's contradiction-model
    research."""

    #: Geometry was checked against the claim and agrees.
    SUPPORTED = "supported"
    #: Geometry was checked and disagrees. Kept, never deleted - the same
    #: "both kept, neither silently dropped" rule `SpatialConflict` already
    #: uses one stage upstream.
    CONTRADICTED = "contradicted"
    #: No check has been run yet (freshly built, or a kind with no known
    #: geometric test - e.g. SEMANTIC_HYPOTHESIS).
    UNRESOLVED = "unresolved"
    #: Computed by a deterministic rule from other facts (not observed
    #: directly) and currently believed consistent - the resting state for a
    #: DERIVED_GEOMETRY relation just (re)computed from current geometry.
    DERIVED = "derived"
    #: Was SUPPORTED or DERIVED, but the geometry it was computed from has
    #: since changed (the subject moved) and it has not been re-verified.
    #: This is the state `resolve_collisions`/`repair_scene` today produce
    #: silently and invisibly - see scene_graph.py's module docstring for the
    #: measured case.
    STALE = "stale"
    #: A human or an upstream authority confirmed it; nothing in this
    #: program currently sets this (no review step consumes GeometricRelation
    #: yet) - included so the enum is complete for a future caller rather
    #: than added later as a breaking change.
    ACCEPTED = "accepted"


def relation_id(subject_id: str, predicate: str, object_id: str) -> str:
    """Deterministic, content-addressed id - never `uuid4()`, never a
    counter, never Python's salted `hash()`. Two processes building the same
    relation from the same facts get the same id, which is what makes
    `scene_serialization.py`'s byte-identical round trip and
    `scene_benchmark.py`'s determinism check meaningful."""
    raw = f"{subject_id}|{predicate}|{object_id}".encode("utf-8")
    return f"rel_{hashlib.sha1(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class GeometricRelation:
    """One classified, provenance-carrying relation between scene entities.

    Distinct from `app.intelligence.schema.SpatialRelation`: that type is the
    pre-metric, image-only relation (no Scene exists yet when it is built).
    This type is POST-metric - it always names entities that exist in a real
    `Scene`, and it carries a `RelationKind` + `RelationStatus` neither
    predecessor type has. `from_spatial_relation` / `from_bridge_dict` are the
    only two ways to build one - both take real upstream data, never
    fabricate a claim.
    """

    relation_id: str
    subject_id: str
    predicate: str
    object_id: str
    kind: RelationKind
    status: RelationStatus
    confidence: SpatialConfidence
    source: SpatialSource
    frame: Frame = "floor_plan"
    note: str = ""
    #: Free-form provenance string: which system/function produced this claim
    #: and from what evidence - never empty, per the evidence-restriction
    #: principle (a relation is never promoted to FACT without a named
    #: source).
    provenance: str = ""
    #: The subject's position AT THE TIME this relation was last verified
    #: true - the snapshot `recompute_relations` compares the CURRENT scene
    #: against to detect staleness. None for relations with no geometric
    #: subject position yet.
    verified_at_position: Optional[Vec3] = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_bridge_dict(cls, d: dict, *, status: RelationStatus = RelationStatus.UNRESOLVED,
                         verified_at_position: Optional[Vec3] = None,
                         provenance: str = "scene_from_photo.grounding_to_scene"
                         ) -> "GeometricRelation":
        """The photo bridge's own raw shape (`BridgeResult.relations`,
        `list[dict]` with subject_id/predicate/object_id/confidence/source/
        frame/note) - classified and content-addressed, nothing recomputed."""
        subject, predicate, obj = d["subject_id"], d["predicate"], d.get("object_id", "")
        source = d.get("source", "geometry")
        return cls(relation_id=relation_id(subject, predicate, obj), subject_id=subject,
                  predicate=predicate, object_id=obj, kind=classify(predicate, source),
                  status=status, confidence=d.get("confidence", "LOW"), source=source,
                  frame=d.get("frame", "floor_plan"), note=d.get("note", ""),
                  provenance=provenance, verified_at_position=verified_at_position,
                  evidence_refs=(d.get("note", ""),) if d.get("note") else ())

    @classmethod
    def from_spatial_relation(cls, rel, *, status: RelationStatus = RelationStatus.UNRESOLVED,
                              provenance: str = "app.planning.spatial_graph"
                              ) -> "GeometricRelation":
        """From a production `app.intelligence.schema.SpatialRelation`
        (the moodboard-stage graph) - same classification rule, so a relation
        built before a Scene existed and one built after are comparable."""
        return cls(relation_id=relation_id(rel.subject_id, rel.predicate, rel.object_id or ""),
                  subject_id=rel.subject_id, predicate=rel.predicate,
                  object_id=rel.object_id or "", kind=classify(rel.predicate, rel.source),
                  status=status, confidence=rel.confidence, source=rel.source,
                  frame=rel.frame, note=rel.note, provenance=provenance,
                  evidence_refs=(rel.note,) if rel.note else ())


__all__ = ["RelationKind", "RelationStatus", "GeometricRelation", "classify",
           "relation_id", "SpatialConfidence", "SpatialSource", "Frame",
           "INVERSE_PREDICATES"]

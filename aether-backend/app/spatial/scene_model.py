"""P7 canonical scene representation: `SpatialScene`.

ARCHITECTURE DECISION (candidate A of five - see docs/spatial_architecture/
scene_model.md §5 for the full comparison table, which extends this
program's own prior Candidate-A decision in architecture_decision.md):
extend the existing `app.scene.schema.Scene` with an explicit, typed relation
layer, rather than replacing it, forking it, or building a parallel
entity-component / graph-database / dual-store system.

`Scene` already IS the geometry layer this program needs (Room, Wall,
Opening, SceneObject with a stable, deterministic `object_id` since P4's
fix) - re-deriving a parallel geometric model would create the exact
"two owners of the same fact" problem the P7 brief calls out. What `Scene`
never had is a persistent, typed, classified RELATION layer: relations exist
today only as (a) a pre-metric `SpatialGraph` at the moodboard stage,
discarded after `apply_spatial_graph` folds it into `ObjectPlanItem.relation`,
or (b) a raw `list[dict]` the photo bridge computes once and hands to
`resolve_collisions`/`repair_scene` as a read-only lookup table that is
NEVER invalidated after those functions move the object the relation was
about. `SpatialScene` is the minimal fix: `Scene` (unchanged) + a tuple of
classified, provenance-carrying `GeometricRelation` (relation_model.py),
with the operations (`recompute_relations`, `scene_consistency.check`) that
keep the two in sync.

FIVE QUESTIONS, ANSWERED FOR EVERY RELATION AND EVERY OBJECT (per the P7
brief's own framing):
  1. What is it?              GeometricRelation.predicate / SceneObject.semantic_type
  2. Where is it?              SceneObject.position / Wall.start,end
  3. Which frame is it in?     Scene.coordinate_system (P6); relations are
                               plan-view (Vec2, XZ) like the geometry they sit over
  4. Why do we believe it?     GeometricRelation.provenance + evidence_refs
  5. Who is allowed to change it? see scene_state_lifecycle.md's ownership table

FACT / HYPOTHESIS / DECISION, made general (P1's `GroundingHypothesis` was
the first, object-scoped instance of this split):
  FACT       Scene geometry (Room.boundary, Wall.start/end, SceneObject.
             position once placed) + GeometricRelation.status == SUPPORTED
  HYPOTHESIS GeometricRelation.status in (UNRESOLVED, DERIVED) - believed
             but not independently re-verified against the LATEST geometry
  DECISION   SceneObject fields the solver/repair engine wrote (P1/P3/P4);
             GeometricRelation.status == ACCEPTED (reserved for a future
             review step - see relation_model.py)

Nothing in `app/` imports this module. Everything downstream of the `Scene`
this module wraps (`validate_scene`, `build_manifest`, `BlenderRunner`,
`resolve_collisions`, `repair_scene`) is unmodified production/P1-P4 research
code - `SpatialScene.scene` IS that same `Scene` object, not a copy or a
re-derivation, so passing `spatial_scene.scene` to any of them is passing
their expected type unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


from app.scene.schema import Scene
from app.spatial.relation_model import (
    GeometricRelation, RelationKind, RelationStatus)


@dataclass(frozen=True)
class SpatialScene:
    """`Scene` (geometry, unmodified production type) + a tuple of classified
    `GeometricRelation` (this phase's new relation layer). Immutable by
    convention - every operation that changes relations (`recompute_relations`)
    returns a NEW `SpatialScene` rather than mutating in place, so a caller
    holding a reference never sees it change under them. `scene` itself is
    still the same mutable pydantic `Scene` production code expects; this
    dataclass adds an association, not a new geometry representation.
    """

    scene: Scene
    relations: tuple[GeometricRelation, ...] = field(default_factory=tuple)

    # ── lookups (read-only; no method here mutates `scene` or `relations`) ──

    def object_ids(self) -> frozenset[str]:
        return frozenset(o.object_id for o in self.scene.objects)

    def wall_ids(self) -> frozenset[str]:
        return frozenset(w.wall_id for w in self.scene.walls)

    def known_entity_ids(self) -> frozenset[str]:
        """Everything a relation is allowed to name: objects, walls, rooms."""
        return (self.object_ids() | self.wall_ids()
               | frozenset(r.room_id for r in self.scene.rooms))

    def relations_for(self, entity_id: str) -> tuple[GeometricRelation, ...]:
        """Every relation where `entity_id` is subject OR object - the
        adjacency query a consistency check or a repair-time lookup needs."""
        return tuple(r for r in self.relations
                    if r.subject_id == entity_id or r.object_id == entity_id)

    def relations_by_kind(self, kind: RelationKind) -> tuple[GeometricRelation, ...]:
        return tuple(r for r in self.relations if r.kind == kind)

    def relations_by_status(self, status: RelationStatus) -> tuple[GeometricRelation, ...]:
        return tuple(r for r in self.relations if r.status == status)

    def relation(self, relation_id: str) -> Optional[GeometricRelation]:
        return next((r for r in self.relations if r.relation_id == relation_id), None)

    def with_relations(self, relations: tuple[GeometricRelation, ...]) -> "SpatialScene":
        """The one way to get a new relation set - never assign
        `.relations` in place (the dataclass is frozen precisely to prevent
        that), always go through this so every caller reasons about
        `SpatialScene` as a value, not a mutable node."""
        return SpatialScene(scene=self.scene, relations=relations)


__all__ = ["SpatialScene"]

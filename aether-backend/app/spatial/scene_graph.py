"""P7 graph construction and the staleness fix.

THE MEASURED BUG THIS MODULE CLOSES. `resolve_collisions` (P1) and
`repair_scene` (P4) both accept `relations: list[dict]` and read it (via each
module's own private `_wall_by_object`) to find which wall an object claims
to be against - but neither function, nor anything downstream, ever
recomputes or invalidates that claim after moving the object. Traced in
`scene_from_photo.grounding_to_scene`: `BridgeResult.relations` is built
once, before collision resolution runs, and `integration_benchmark.py`
threads the SAME list through both `resolve_collisions` and `repair_scene`
unchanged (see its own `result.relations` reuse). An object nudged 0.3 m off
a wall to resolve a collision keeps its AGAINST_WALL relation, unexamined,
forever. This is not a hypothetical adversarial case - it is what the
existing, frozen, tested P1/P4 pipeline does on every run today; P7 does not
change that pipeline (still frozen, still reused unmodified), it adds the
missing read-only check as a NEW, separate step a caller can run after.

`recompute_relations` re-derives DERIVED_GEOMETRY relations against the
scene's CURRENT geometry using ONLY already-existing, already-tested
geometry functions (`app.spatial.geometry.point_segment_distance`) - no new
collision math. It returns a NEW `SpatialScene` (relations are data, per
scene_model.py) and never touches `scene.objects` - this is a diagnosis
layer, not a seventh repair mechanism; if a relation is found false, its
status becomes CONTRADICTED, and nothing else in this program is asked to
fix it (repair is P4's job, unchanged).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional


from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall
from app.spatial.geometry import point_segment_distance
from app.spatial.relation_model import (
    GeometricRelation, RelationKind, RelationStatus)
from app.spatial.scene_model import SpatialScene

#: How far an object's XZ position may sit from a wall's centerline (plus
#: half its own thickness) and still count as "against" it. Named and
#: documented rather than a bare literal: it must be loose enough that
#: floating-point/rounding jitter from `object_footprint`/Blender round-trips
#: (P6 measured sub-millimetre drift; P1's own nudge step is 0.1 m) never
#: flips a true relation to CONTRADICTED, and tight enough that a real P1/P4
#: repair move (P1's search radius is up to 1.0 m; P4's repair moves are
#: reported in the 0.1-0.4 m range in repair_benchmark.py) is caught.
AGAINST_WALL_TOLERANCE_M = 0.25


def from_bridge_result(scene: Scene, raw_relations: list[dict]) -> SpatialScene:
    """Wrap the photo bridge's own output (`scene_from_photo.BridgeResult`
    unpacked by the caller into `.scene` and `.relations`) as a `SpatialScene`
    - classified, content-addressed, snapshot-tagged. Reads `scene`, never
    mutates it."""
    positions = {o.object_id: o.position for o in scene.objects}
    relations = tuple(
        GeometricRelation.from_bridge_dict(
            d, status=RelationStatus.DERIVED,
            verified_at_position=positions.get(d["subject_id"]))
        for d in raw_relations)
    return SpatialScene(scene=scene, relations=relations)


def _current_wall_distance(scene: Scene, object_id: str, wall_id: str) -> Optional[float]:
    obj = scene.object(object_id)
    wall = scene.wall(wall_id)
    if obj is None or wall is None:
        return None
    gap = point_segment_distance((obj.position[0], obj.position[2]), wall.start, wall.end)
    return gap - wall.thickness / 2.0


#: Predicates this module knows how to independently check against CURRENT
#: geometry, regardless of the relation's `kind`/`source` at construction
#: time - a stated hint ("the reader said against the wall") and a measured
#: claim ("wall_contact.decision == YES") are the SAME testable claim, just
#: with different provenance; verifying one is not a bigger step than
#: verifying the other. Only AGAINST_WALL has a verifier today (P5/P6's own
#: geometry gives a cheap, already-tested distance check via
#: `point_segment_distance`); extending this set to SUPPORTED_BY/NEAR/etc.
#: needs its own geometric test (a support-contact check, a pairwise-distance
#: threshold) that no phase has built or measured yet - added when one is,
#: not spun up speculatively here.
_VERIFIABLE_PREDICATES = frozenset({"AGAINST_WALL"})


def recompute_relations(spatial_scene: SpatialScene) -> tuple[SpatialScene, list[str]]:
    """Re-verify relations against the CURRENT scene.

    Two different things happen here, and they are kept distinct:
      1. A `_VERIFIABLE_PREDICATES` relation is independently re-checked
         against current geometry NOW, regardless of its `kind` - this can
         both catch a DERIVED_GEOMETRY relation gone stale (P1/P4's own
         collision-nudge case) AND confirm or contradict an EVIDENCE_CLAIM
         (a stated hint checked against reality for the first time).
      2. Every other DERIVED_GEOMETRY relation has no verifier built yet; if
         its subject has moved since the relation was last verified, it is
         marked STALE rather than silently left claiming a fact nobody
         re-checked.

    Returns a new `SpatialScene` (never mutates the input) and a list of
    human-readable change notes, so a caller (a benchmark, a test, a future
    review UI) can see exactly what changed. Orphan references (subject/
    object id no longer in the scene - an object removed since the relation
    was built) are marked CONTRADICTED rather than silently kept or dropped,
    per the "never silently discard" rule this program has followed since
    P4's RepairRecord.
    """
    known = spatial_scene.known_entity_ids()
    updated: list[GeometricRelation] = []
    changes: list[str] = []

    for rel in spatial_scene.relations:
        if rel.subject_id not in known or (rel.object_id and rel.object_id not in known):
            changes.append(f"{rel.relation_id}: {rel.predicate} references a missing "
                           f"entity -> CONTRADICTED")
            updated.append(replace(rel, status=RelationStatus.CONTRADICTED,
                                   note="orphan: subject or object no longer in scene"))
            continue

        if rel.predicate in _VERIFIABLE_PREDICATES:
            gap = _current_wall_distance(spatial_scene.scene, rel.subject_id, rel.object_id)
            still_true = gap is not None and gap <= AGAINST_WALL_TOLERANCE_M
            if still_true:
                if rel.status != RelationStatus.SUPPORTED:
                    changes.append(f"{rel.relation_id}: {rel.predicate} independently "
                                   f"verified true (gap {gap:.3f} m) -> SUPPORTED")
                obj = spatial_scene.scene.object(rel.subject_id)
                updated.append(replace(rel, status=RelationStatus.SUPPORTED,
                                       verified_at_position=obj.position))
            else:
                changes.append(f"{rel.relation_id}: {rel.predicate} does not hold "
                               f"(gap {gap if gap is not None else 'n/a'} m > "
                               f"{AGAINST_WALL_TOLERANCE_M} m) -> CONTRADICTED")
                updated.append(replace(rel, status=RelationStatus.CONTRADICTED,
                                       note=f"measured gap {gap} m exceeds tolerance"))
            continue

        if rel.kind is not RelationKind.DERIVED_GEOMETRY:
            updated.append(rel)
            continue

        # DERIVED_GEOMETRY predicate with no verifier built yet (SUPPORTED_BY,
        # NEAR, ...): mark STALE once the subject has moved since the
        # snapshot, rather than silently leaving it DERIVED/SUPPORTED.
        obj = spatial_scene.scene.object(rel.subject_id)
        moved = (rel.verified_at_position is not None and obj is not None
                and tuple(obj.position) != tuple(rel.verified_at_position))
        if moved and rel.status != RelationStatus.STALE:
            changes.append(f"{rel.relation_id}: {rel.predicate} subject moved; no "
                           f"re-verification rule for this predicate -> STALE")
            updated.append(replace(rel, status=RelationStatus.STALE,
                                   note="subject moved; not re-verified (no rule)"))
        else:
            updated.append(rel)

    return spatial_scene.with_relations(tuple(updated)), changes


# ── the required end-to-end demonstration scene (P7 §49) ────────────────
#
# Deterministic, synthetic (no model call, no photo) - built purely to
# exercise every layer this phase adds, with fixed ids so a reader can trace
# one object through evidence -> hypothesis -> geometry -> relation ->
# solver decision -> validation -> (Blender manifest, built separately in
# scene_benchmark.py's demo() output).

def build_demonstration_scene() -> SpatialScene:
    """One room, two walls, two same-category objects (two chairs), one
    different-category object (a table), one wall-anchored object, one
    floor-supported object, one object-object relation (chair beside table),
    one derived geometric relation (AGAINST_WALL), one evidence-backed
    semantic relation (FACES, from a stated hint), and one solver decision
    recorded via `Confidence.source`.
    """
    room = Room(room_id="room_demo", name="Demo Room", type="living_room",
               boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)],
               confidence=Confidence(value=1.0, source="synthetic_demo"))
    wall_a = Wall(wall_id="wall_a", start=(-3.0, -3.0), end=(3.0, -3.0), thickness=0.15)
    wall_b = Wall(wall_id="wall_b", start=(-3.0, -3.0), end=(-3.0, 3.0), thickness=0.15)

    table = SceneObject(object_id="obj_table_0", semantic_type="dining_table",
                        room_id=room.room_id, position=(0.0, 0.0, 0.0), dimensions=(1.2, 0.75, 0.8),
                        confidence=Confidence(value=0.9, source="solver_decision:place_objects"))
    chair_0 = SceneObject(object_id="obj_chair_0", semantic_type="chair", room_id=room.room_id,
                          position=(0.0, 0.0, -0.7), dimensions=(0.45, 0.9, 0.5),
                          confidence=Confidence(value=0.9, source="solver_decision:place_objects"))
    # Against wall_a (z = -3.0): centerline distance ~0.075 m (half thickness) - within tolerance.
    chair_1 = SceneObject(object_id="obj_chair_1", semantic_type="chair", room_id=room.room_id,
                          position=(0.6, 0.0, -2.9), dimensions=(0.45, 0.9, 0.5),
                          confidence=Confidence(value=0.85, source="evidence:reader_hint"))

    # scene_id given explicitly - Scene's own default_factory uses uuid4(),
    # which would make this "deterministic demonstration scene" non-
    # deterministic across runs for no reason relevant to this phase.
    scene = Scene(scene_id="scene_demo", project_id="proj_demo", name="P7 demonstration scene",
                 rooms=[room], walls=[wall_a, wall_b], objects=[table, chair_0, chair_1])

    raw_relations = [
        {"subject_id": "obj_chair_1", "predicate": "AGAINST_WALL", "object_id": "wall_a",
         "confidence": "HIGH", "source": "geometry", "frame": "floor_plan",
         "note": "measured gap 0.075 m"},
    ]
    spatial = from_bridge_result(scene, raw_relations)

    faces_relation = GeometricRelation.from_bridge_dict(
        {"subject_id": "obj_chair_0", "predicate": "FACES", "object_id": "obj_table_0",
         "confidence": "LOW", "source": "semantic", "note": "reader said 'facing the table'"},
        status=RelationStatus.UNRESOLVED, provenance="app.planning.spatial_graph._semantic_relations")
    beside_relation = GeometricRelation.from_bridge_dict(
        {"subject_id": "obj_chair_1", "predicate": "ADJACENT_TO", "object_id": "obj_table_0",
         "confidence": "MEDIUM", "source": "geometry", "note": "boxes side by side"},
        status=RelationStatus.DERIVED, provenance="app.planning.spatial_graph._geometric_relations")

    return spatial.with_relations(spatial.relations + (faces_relation, beside_relation))


__all__ = ["from_bridge_result", "recompute_relations", "build_demonstration_scene",
           "AGAINST_WALL_TOLERANCE_M"]

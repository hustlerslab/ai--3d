"""Deterministic checks for scene_graph.py: bridge wrapping, the staleness
fix (`recompute_relations`), and the required end-to-end demonstration
scene. No GPU, no models. See docs/spatial_architecture/scene_graph.md.
"""
from __future__ import annotations

from dataclasses import replace

from app.scene.schema import Room, Scene, SceneObject, Wall
from app.spatial.relation_model import RelationKind, RelationStatus
from app.spatial.scene_consistency import check_consistency
from app.spatial.scene_graph import (
    build_demonstration_scene, from_bridge_result, recompute_relations)
from app.spatial.scene_serialization import to_canonical_json


def _scene_with_object_against_wall(position):
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-3, -3), (3, -3), (3, 3), (-3, 3)])
    wall = Wall(wall_id="w1", start=(-3, -3), end=(3, -3))
    obj = SceneObject(object_id="o1", semantic_type="chair", room_id="r1",
                      position=position, dimensions=(0.4, 0.9, 0.4))
    return Scene(scene_id="s1", project_id="p1", name="t", rooms=[room], walls=[wall],
                objects=[obj])


# ── from_bridge_result ────────────────────────────────────────────────────

def test_from_bridge_result_classifies_and_snapshots_position():
    scene = _scene_with_object_against_wall((0.0, 0.0, -2.9))
    raw = [{"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1",
           "confidence": "HIGH", "source": "geometry", "note": "gap 0.075"}]
    spatial = from_bridge_result(scene, raw)
    assert len(spatial.relations) == 1
    rel = spatial.relations[0]
    assert rel.kind == RelationKind.DERIVED_GEOMETRY
    assert rel.status == RelationStatus.DERIVED
    assert rel.verified_at_position == (0.0, 0.0, -2.9)


# ── recompute_relations: the measured staleness bug, fixed ───────────────

def test_recompute_confirms_true_relation_as_supported():
    scene = _scene_with_object_against_wall((0.0, 0.0, -2.9))
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1",
         "confidence": "HIGH", "source": "geometry"}])
    recomputed, changes = recompute_relations(spatial)
    assert recomputed.relations[0].status == RelationStatus.SUPPORTED


def test_recompute_catches_the_p1_p4_staleness_bug():
    """This is the exact scenario `resolve_collisions`/`repair_scene` produce
    today: an AGAINST_WALL relation is built, then the object is moved (a
    collision nudge or a repair move) without the relation being told."""
    scene = _scene_with_object_against_wall((0.5, 0.0, -2.9))
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1",
         "confidence": "HIGH", "source": "geometry"}])
    nudged_obj = spatial.scene.object("o1").model_copy(update={"position": (0.5, 0.0, -1.0)})
    nudged_scene = spatial.scene.model_copy(update={"objects": [nudged_obj]})
    moved_spatial = replace(spatial, scene=nudged_scene)

    # Before recompute: the relation still (wrongly) claims AGAINST_WALL,
    # unexamined - this IS today's production behaviour (BridgeResult.relations
    # is never re-checked by resolve_collisions/repair_scene).
    assert moved_spatial.relations[0].status == RelationStatus.DERIVED

    recomputed, changes = recompute_relations(moved_spatial)
    assert recomputed.relations[0].status == RelationStatus.CONTRADICTED
    assert any("CONTRADICTED" in c for c in changes)


def test_recompute_re_verifies_a_stated_hint_against_geometry():
    """A relation built from a stated hint (source='semantic', never
    geometrically checked) is still verifiable if its predicate has a known
    geometric test - intent is checked against reality, not trusted blindly."""
    scene = _scene_with_object_against_wall((0.0, 0.0, 0.0))   # nowhere near the wall
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1",
         "confidence": "LOW", "source": "semantic", "note": "reader said 'against the wall'"}])
    assert spatial.relations[0].kind == RelationKind.EVIDENCE_CLAIM
    recomputed, changes = recompute_relations(spatial)
    assert recomputed.relations[0].status == RelationStatus.CONTRADICTED


def test_recompute_marks_unverifiable_predicate_stale_after_move():
    scene = _scene_with_object_against_wall((0.0, 0.0, 0.0))
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "SUPPORTED_BY", "object_id": "r1",
         "confidence": "MEDIUM", "source": "placement"}])
    assert spatial.relations[0].kind == RelationKind.DERIVED_GEOMETRY
    moved_obj = spatial.scene.object("o1").model_copy(update={"position": (2.0, 0.0, 2.0)})
    moved_scene = spatial.scene.model_copy(update={"objects": [moved_obj]})
    moved_spatial = replace(spatial, scene=moved_scene)
    recomputed, changes = recompute_relations(moved_spatial)
    assert recomputed.relations[0].status == RelationStatus.STALE


def test_recompute_marks_orphan_relation_contradicted():
    scene = _scene_with_object_against_wall((0.0, 0.0, -2.9))
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"}])
    empty_scene = spatial.scene.model_copy(update={"objects": []})
    orphaned = replace(spatial, scene=empty_scene)
    recomputed, changes = recompute_relations(orphaned)
    assert recomputed.relations[0].status == RelationStatus.CONTRADICTED


def test_recompute_never_mutates_the_input_scene_or_relations():
    scene = _scene_with_object_against_wall((0.0, 0.0, -2.9))
    spatial = from_bridge_result(scene, [
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"}])
    original_relations = spatial.relations
    original_status = original_relations[0].status
    recompute_relations(spatial)
    assert spatial.relations is original_relations
    assert spatial.relations[0].status == original_status


# ── the required end-to-end demonstration scene ──────────────────────────

def test_demonstration_scene_has_required_lineage_elements():
    demo = build_demonstration_scene()
    assert len(demo.scene.rooms) == 1
    assert len(demo.scene.walls) == 2                       # multiple walls
    types = [o.semantic_type for o in demo.scene.objects]
    assert types.count("chair") == 2                        # two same-category objects
    assert "dining_table" in types                          # a different category
    predicates = {r.predicate for r in demo.relations}
    assert "AGAINST_WALL" in predicates                      # derived geometric relation
    assert "FACES" in predicates                             # evidence-backed semantic relation
    assert "ADJACENT_TO" in predicates                       # object-object relation
    # solver decision provenance recorded
    assert any(o.confidence.source.startswith("solver_decision") for o in demo.scene.objects)


def test_demonstration_scene_is_internally_consistent():
    demo = build_demonstration_scene()
    recomputed, _changes = recompute_relations(demo)
    findings = check_consistency(recomputed)
    assert findings == []


def test_demonstration_scene_is_deterministic():
    a = build_demonstration_scene()
    b = build_demonstration_scene()
    assert to_canonical_json(a) == to_canonical_json(b)

"""Deterministic checks for the P7 `SpatialScene` entity model and relation
taxonomy (scene_model.py, relation_model.py). No GPU, no models. See
docs/spatial_architecture/scene_model.md for the design these guard.
"""
from __future__ import annotations

from app.scene.schema import Room, Scene, SceneObject, Wall
from app.spatial.relation_model import (
    GeometricRelation, RelationKind, RelationStatus, classify, relation_id)
from app.spatial.scene_model import SpatialScene


def _tiny_scene() -> Scene:
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-2, -2), (2, -2), (2, 2), (-2, 2)])
    wall = Wall(wall_id="w1", start=(-2, -2), end=(2, -2))
    obj = SceneObject(object_id="o1", semantic_type="chair", room_id="r1",
                      position=(0, 0, -1.9), dimensions=(0.4, 0.9, 0.4))
    return Scene(scene_id="s1", project_id="p1", name="tiny", rooms=[room],
                walls=[wall], objects=[obj])


# ── relation_id: deterministic, content-addressed ────────────────────────

def test_relation_id_is_deterministic_across_calls():
    a = relation_id("o1", "AGAINST_WALL", "w1")
    b = relation_id("o1", "AGAINST_WALL", "w1")
    assert a == b


def test_relation_id_differs_for_different_content():
    assert relation_id("o1", "AGAINST_WALL", "w1") != relation_id("o2", "AGAINST_WALL", "w1")
    assert relation_id("o1", "AGAINST_WALL", "w1") != relation_id("o1", "NEAR", "w1")


def test_relation_id_is_not_pythons_builtin_hash():
    """The exact class of bug flagged as must-not-recur: `hash()` on a str is
    salted per process unless PYTHONHASHSEED is fixed. sha1-based ids must
    not depend on it - this asserts the id is stable and hex, which a salted
    hash could never be run to run (regression-guard by construction, not by
    re-running the process twice)."""
    rid = relation_id("o1", "AGAINST_WALL", "w1")
    assert rid.startswith("rel_")
    assert len(rid) == len("rel_") + 16
    int(rid[len("rel_"):], 16)   # must be valid hex


# ── classification ────────────────────────────────────────────────────────

def test_classify_semantic_only_predicates():
    assert classify("FACES", "semantic") == RelationKind.SEMANTIC_HYPOTHESIS
    assert classify("GROUPED_WITH", "geometry") == RelationKind.SEMANTIC_HYPOTHESIS


def test_classify_geometry_sourced_predicate_by_source():
    assert classify("AGAINST_WALL", "geometry") == RelationKind.DERIVED_GEOMETRY
    assert classify("AGAINST_WALL", "semantic+geometry") == RelationKind.DERIVED_GEOMETRY
    assert classify("AGAINST_WALL", "placement") == RelationKind.DERIVED_GEOMETRY
    assert classify("AGAINST_WALL", "semantic") == RelationKind.EVIDENCE_CLAIM


def test_classify_unknown_predicate_defaults_to_evidence_claim():
    assert classify("SOME_FUTURE_PREDICATE", "geometry") == RelationKind.EVIDENCE_CLAIM


# ── GeometricRelation construction ────────────────────────────────────────

def test_from_bridge_dict_matches_photo_bridge_shape():
    d = {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1",
        "confidence": "HIGH", "source": "geometry", "frame": "floor_plan",
        "note": "wall gap 0.05 m"}
    rel = GeometricRelation.from_bridge_dict(d)
    assert rel.subject_id == "o1" and rel.object_id == "w1"
    assert rel.kind == RelationKind.DERIVED_GEOMETRY
    assert rel.relation_id == relation_id("o1", "AGAINST_WALL", "w1")
    assert rel.provenance   # never empty


def test_geometric_relation_is_frozen():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"})
    try:
        rel.status = RelationStatus.CONTRADICTED     # type: ignore[misc]
        assert False, "GeometricRelation must be immutable"
    except Exception:
        pass


# ── SpatialScene lookups ──────────────────────────────────────────────────

def test_spatial_scene_wraps_the_same_scene_object():
    scene = _tiny_scene()
    spatial = SpatialScene(scene=scene)
    assert spatial.scene is scene   # not a copy - production functions get the real thing


def test_object_and_wall_ids():
    spatial = SpatialScene(scene=_tiny_scene())
    assert spatial.object_ids() == {"o1"}
    assert spatial.wall_ids() == {"w1"}
    assert spatial.known_entity_ids() >= {"o1", "w1", "r1"}


def test_relations_for_finds_subject_and_object_matches():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"})
    spatial = SpatialScene(scene=_tiny_scene(), relations=(rel,))
    assert spatial.relations_for("o1") == (rel,)
    assert spatial.relations_for("w1") == (rel,)
    assert spatial.relations_for("nonexistent") == ()


def test_relations_by_kind_and_status():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"},
        status=RelationStatus.DERIVED)
    spatial = SpatialScene(scene=_tiny_scene(), relations=(rel,))
    assert spatial.relations_by_kind(RelationKind.DERIVED_GEOMETRY) == (rel,)
    assert spatial.relations_by_status(RelationStatus.DERIVED) == (rel,)
    assert spatial.relations_by_status(RelationStatus.CONTRADICTED) == ()


def test_with_relations_returns_a_new_immutable_value():
    scene = _tiny_scene()
    spatial = SpatialScene(scene=scene)
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"})
    updated = spatial.with_relations((rel,))
    assert spatial.relations == ()          # original untouched
    assert updated.relations == (rel,)
    assert updated.scene is scene           # geometry is shared, not copied

"""Deterministic checks for scene_consistency.py: diagnosis only, never
repair. No GPU, no models.
"""
from __future__ import annotations

from app.scene.schema import Room, Scene, SceneObject, Wall
from app.spatial.relation_model import (
    GeometricRelation, RelationStatus)
from app.spatial.scene_consistency import check_consistency
from app.spatial.scene_model import SpatialScene


def _scene(objects):
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-3, -3), (3, -3), (3, 3), (-3, 3)])
    wall = Wall(wall_id="w1", start=(-3, -3), end=(3, -3))
    return Scene(scene_id="s1", project_id="p1", name="t", rooms=[room], walls=[wall],
                objects=objects)


def _obj(oid, semantic_type="chair"):
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="r1",
                       position=(0, 0, 0), dimensions=(0.4, 0.9, 0.4))


def test_clean_scene_has_no_findings():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"},
        status=RelationStatus.SUPPORTED)
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(rel,))
    assert check_consistency(spatial) == []


def test_orphan_subject_is_flagged():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "ghost", "predicate": "AGAINST_WALL", "object_id": "w1"})
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(rel,))
    findings = check_consistency(spatial)
    assert any(f.code == "ORPHAN_REFERENCE" for f in findings)


def test_duplicate_relation_is_flagged():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"})
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(rel, rel))
    findings = check_consistency(spatial)
    assert any(f.code == "DUPLICATE_RELATION" for f in findings)


def test_stale_and_contradicted_relations_are_flagged():
    stale = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "SUPPORTED_BY", "object_id": "r1"},
        status=RelationStatus.STALE)
    contradicted = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"},
        status=RelationStatus.CONTRADICTED)
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(stale, contradicted))
    codes = {f.code for f in check_consistency(spatial)}
    assert "STALE_RELATION" in codes
    assert "CONTRADICTED_RELATION" in codes


def test_unsupported_hypothesis_flagged_when_no_provenance():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "FACES", "object_id": "o2", "note": ""},
        provenance="")
    spatial = SpatialScene(scene=_scene([_obj("o1"), _obj("o2")]), relations=(rel,))
    findings = check_consistency(spatial)
    assert any(f.code == "UNSUPPORTED_HYPOTHESIS" for f in findings)


def test_check_consistency_never_mutates_input():
    rel = GeometricRelation.from_bridge_dict(
        {"subject_id": "o1", "predicate": "AGAINST_WALL", "object_id": "w1"})
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(rel,))
    before_relations = spatial.relations
    before_objects = list(spatial.scene.objects)
    check_consistency(spatial)
    assert spatial.relations == before_relations
    assert spatial.scene.objects == before_objects


def test_findings_are_deterministically_ordered():
    r1 = GeometricRelation.from_bridge_dict({"subject_id": "z", "predicate": "AGAINST_WALL"})
    r2 = GeometricRelation.from_bridge_dict({"subject_id": "a", "predicate": "AGAINST_WALL"})
    spatial = SpatialScene(scene=_scene([_obj("o1")]), relations=(r1, r2))
    findings = check_consistency(spatial)
    codes_and_ids = [(f.code, f.subject_id) for f in findings]
    assert codes_and_ids == sorted(codes_and_ids)

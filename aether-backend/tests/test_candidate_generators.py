"""Deterministic checks for candidate_generators.py: distance ring, between
region, and the post-placement regeneration step. No GPU, no models.
"""
from __future__ import annotations

import math

from app.scene.schema import Room, Scene, SceneObject
from app.planning.candidate_generators import (
    RING_SAMPLES, between_candidates, distance_candidates, regenerate_after_placement)
from app.planning.constraint_model import Constraint, ConstraintType, constraint_id
from app.spatial.scene_model import SpatialScene


def _scene(objects, boundary=None):
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=boundary or [(-5, -5), (5, -5), (5, 5), (-5, 5)])
    return Scene(scene_id="s1", project_id="p1", name="t", rooms=[room], objects=objects)


def _obj(oid, pos, semantic_type="chair", rotation_y=0.0, dims=(0.45, 0.9, 0.5)):
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="r1",
                      position=pos, rotation_y=rotation_y, dimensions=dims)


def _c(ctype, subject, target, **params):
    return Constraint(constraint_id=constraint_id(subject, ctype, target, params),
                     constraint_type=ctype, subject_id=subject, target_id=target, parameters=params)


# ── distance_candidates ───────────────────────────────────────────────────

def test_distance_candidates_returns_empty_without_explicit_distance():
    target = _obj("target", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([target]))
    c = _c(ConstraintType.DISTANCE, "s", "target")
    assert distance_candidates(c, spatial, (0.5, 0.5, 0.5)) == []


def test_distance_candidates_returns_empty_when_target_missing():
    spatial = SpatialScene(scene=_scene([]))
    c = _c(ConstraintType.DISTANCE, "s", "ghost", distance_m=1.0)
    assert distance_candidates(c, spatial, (0.5, 0.5, 0.5)) == []


def test_distance_candidates_all_at_requested_distance():
    target = _obj("target", (1.0, 0, 1.0))
    spatial = SpatialScene(scene=_scene([target]))
    c = _c(ConstraintType.DISTANCE, "s", "target", distance_m=2.0)
    cands = distance_candidates(c, spatial, (0.5, 0.5, 0.5))
    assert len(cands) == RING_SAMPLES
    for cnd in cands:
        d = math.hypot(cnd.position[0] - 1.0, cnd.position[1] - 1.0)
        assert math.isclose(d, 2.0, abs_tol=1e-3)


def test_distance_candidates_default_rotation_matches_target():
    target = _obj("target", (0, 0, 0), rotation_y=0.77)
    spatial = SpatialScene(scene=_scene([target]))
    c = _c(ConstraintType.DISTANCE, "s", "target", distance_m=1.0)
    cands = distance_candidates(c, spatial, (0.5, 0.5, 0.5))
    assert all(math.isclose(cnd.rotation_y, 0.77, abs_tol=1e-6) for cnd in cands)


# ── between_candidates ────────────────────────────────────────────────────

def test_between_candidates_returns_empty_when_a_target_missing():
    b = _obj("b", (1, 0, 1))
    spatial = SpatialScene(scene=_scene([b]))
    c = _c(ConstraintType.POSITION, "s", "", between_a_id="ghost", between_b_id="b")
    assert between_candidates(c, spatial) == []


def test_between_candidates_returns_empty_for_coincident_targets():
    a, b = _obj("a", (1, 0, 1)), _obj("b", (1, 0, 1))
    spatial = SpatialScene(scene=_scene([a, b]))
    c = _c(ConstraintType.POSITION, "s", "", between_a_id="a", between_b_id="b")
    assert between_candidates(c, spatial) == []


def test_between_candidates_midpoint_is_generated():
    a, b = _obj("a", (0, 0, -2)), _obj("b", (0, 0, 2))
    spatial = SpatialScene(scene=_scene([a, b]))
    c = _c(ConstraintType.POSITION, "s", "", between_a_id="a", between_b_id="b")
    cands = between_candidates(c, spatial)
    assert any(math.isclose(cnd.position[0], 0.0, abs_tol=1e-6)
              and math.isclose(cnd.position[1], 0.0, abs_tol=1e-6) for cnd in cands)


# ── regenerate_after_placement: the P4-shaped repair pattern ─────────────

def test_regenerate_finds_exact_distance_when_feasible():
    sofa = _obj("sofa", (0, 0, 0), "sofa", dims=(2.1, 0.85, 0.9))
    chair = _obj("chair", (5, 0, 0), "armchair", dims=(0.8, 0.8, 0.85))
    spatial = SpatialScene(scene=_scene([sofa, chair]))
    c = _c(ConstraintType.DISTANCE, "chair", "sofa", distance_m=1.2)
    pose = regenerate_after_placement(c, spatial, (0.8, 0.8, 0.85))
    assert pose is not None
    x, y, z, yaw = pose
    assert math.isclose(math.hypot(x, z), 1.2, abs_tol=1e-3)


def test_regenerate_never_returns_a_colliding_pose():
    sofa = _obj("sofa", (0, 0, 0), "sofa", dims=(2.1, 0.85, 0.9))
    blocker = _obj("blocker", (0, 0, 1.2), "bookshelf", dims=(3.0, 1.8, 3.0))
    chair = _obj("chair", (5, 0, 0), "armchair", dims=(0.8, 0.8, 0.85))
    spatial = SpatialScene(scene=_scene([sofa, blocker, chair]))
    c = _c(ConstraintType.DISTANCE, "chair", "sofa", distance_m=1.2)
    pose = regenerate_after_placement(c, spatial, (0.8, 0.8, 0.85))
    if pose is not None:
        from app.spatial.validation import validate_object
        probe = SceneObject(object_id="chair", semantic_type="armchair", room_id="r1",
                            position=(pose[0], pose[1], pose[2]), rotation_y=pose[3],
                            dimensions=(0.8, 0.8, 0.85))
        scene_without_chair = spatial.scene.model_copy(update={
            "objects": [o for o in spatial.scene.objects if o.object_id != "chair"]})
        assert validate_object(scene_without_chair, probe) == []


def test_regenerate_returns_none_when_nothing_feasible():
    sofa = _obj("sofa", (0, 0, 0), "sofa")
    chair = _obj("chair", (0.1, 0, 0.1), "armchair", dims=(0.8, 0.8, 0.85))
    tiny_boundary = [(-0.4, -0.4), (0.4, -0.4), (0.4, 0.4), (-0.4, 0.4)]
    spatial = SpatialScene(scene=_scene([sofa, chair], boundary=tiny_boundary))
    c = _c(ConstraintType.DISTANCE, "chair", "sofa", distance_m=5.0)
    assert regenerate_after_placement(c, spatial, (0.8, 0.8, 0.85)) is None


def test_regenerate_never_mutates_input_scene():
    sofa = _obj("sofa", (0, 0, 0), "sofa", dims=(2.1, 0.85, 0.9))
    chair = _obj("chair", (5, 0, 0), "armchair", dims=(0.8, 0.8, 0.85))
    scene = _scene([sofa, chair])
    spatial = SpatialScene(scene=scene)
    before = [(o.object_id, o.position) for o in scene.objects]
    c = _c(ConstraintType.DISTANCE, "chair", "sofa", distance_m=1.2)
    regenerate_after_placement(c, spatial, (0.8, 0.8, 0.85))
    after = [(o.object_id, o.position) for o in scene.objects]
    assert before == after

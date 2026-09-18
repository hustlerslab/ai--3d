"""Deterministic checks for constraint_evaluator.py: per-type verdicts,
numeric error, and read-only purity. No GPU, no models.
"""
from __future__ import annotations

import math

from app.scene.schema import Room, Scene, SceneObject, Wall
from app.planning.constraint_evaluator import evaluate, evaluate_all
from app.planning.constraint_model import (
    Constraint, ConstraintType, Verdict, constraint_id)
from app.spatial.scene_model import SpatialScene


def _scene(objects, walls=None):
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-3, -3), (3, -3), (3, 3), (-3, 3)])
    wall = Wall(wall_id="w1", start=(-3, -3), end=(3, -3))
    return Scene(scene_id="s1", project_id="p1", name="t", rooms=[room],
                walls=list(walls) if walls is not None else [wall], objects=objects)


def _obj(oid, pos, rotation_y=0.0, semantic_type="chair", dims=(0.45, 0.9, 0.5), parent_id=None,
        mount="floor"):
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="r1", position=pos,
                      rotation_y=rotation_y, dimensions=dims, parent_id=parent_id, mount=mount)


def _c(ctype, subject, target, **params):
    return Constraint(constraint_id=constraint_id(subject, ctype, target, params),
                     constraint_type=ctype, subject_id=subject, target_id=target, parameters=params)


def test_orientation_satisfied_when_facing_target():
    sofa = _obj("sofa", (0, 0, 0), rotation_y=math.pi)   # forward flips toward +Z
    tv = _obj("tv", (0, 0, 2.0))
    spatial = SpatialScene(scene=_scene([sofa, tv]))
    r = evaluate(_c(ConstraintType.ORIENTATION, "sofa", "tv"), spatial)
    assert r.verdict == Verdict.SATISFIED
    assert r.error is not None and r.error < 1.0


def test_orientation_matches_compiler_forward_convention():
    """Same formula as `app/planning/compiler.py::_forward` /
    `scene_forward(yaw) = (-sin(yaw), -cos(yaw))` - verified numerically."""
    from app.planning.constraint_evaluator import _forward
    for yaw in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
        fx, fz = _forward(yaw)
        assert math.isclose(fx, -math.sin(yaw), abs_tol=1e-9)
        assert math.isclose(fz, -math.cos(yaw), abs_tol=1e-9)


def test_orientation_unknown_when_same_position():
    sofa = _obj("sofa", (0, 0, 0))
    tv = _obj("tv", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([sofa, tv]))
    r = evaluate(_c(ConstraintType.ORIENTATION, "sofa", "tv"), spatial)
    assert r.verdict == Verdict.UNKNOWN


def test_distance_unknown_without_explicit_number():
    a, b = _obj("a", (0, 0, 0)), _obj("b", (0.5, 0, 0))
    spatial = SpatialScene(scene=_scene([a, b]))
    r = evaluate(_c(ConstraintType.DISTANCE, "a", "b"), spatial)
    assert r.verdict == Verdict.UNKNOWN


def test_distance_satisfied_with_explicit_number():
    a, b = _obj("a", (0, 0, 0)), _obj("b", (1.5, 0, 0))
    spatial = SpatialScene(scene=_scene([a, b]))
    r = evaluate(_c(ConstraintType.DISTANCE, "a", "b", distance_m=1.5), spatial)
    assert r.verdict == Verdict.SATISFIED
    assert r.error_kind == "distance_m"


def test_contact_reuses_p7_tolerance_constant():
    from app.spatial.scene_graph import AGAINST_WALL_TOLERANCE_M
    obj = _obj("o", (0, 0, -3.0 + AGAINST_WALL_TOLERANCE_M / 2))
    spatial = SpatialScene(scene=_scene([obj]))
    r = evaluate(_c(ConstraintType.CONTACT, "o", "w1"), spatial)
    assert r.verdict == Verdict.SATISFIED


def test_support_unknown_before_any_support_assigned():
    table = _obj("table", (0, 0, 0), semantic_type="coffee_table")
    lamp = _obj("lamp", (0, 0.4, 0), semantic_type="table_lamp", parent_id=None)
    spatial = SpatialScene(scene=_scene([table, lamp]))
    r = evaluate(_c(ConstraintType.SUPPORT, "lamp", "table"), spatial)
    assert r.verdict == Verdict.UNKNOWN


def test_support_violated_when_parent_differs():
    table = _obj("table", (0, 0, 0), semantic_type="coffee_table")
    other = _obj("other", (2, 0, 0), semantic_type="side_table")
    lamp = _obj("lamp", (0, 0.4, 0), semantic_type="table_lamp", parent_id="other")
    spatial = SpatialScene(scene=_scene([table, other, lamp]))
    r = evaluate(_c(ConstraintType.SUPPORT, "lamp", "table"), spatial)
    assert r.verdict == Verdict.VIOLATED


def test_containment_inside_satisfied_for_object_in_room():
    obj = _obj("o", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([obj]))
    r = evaluate(_c(ConstraintType.CONTAINMENT, "o", "r1", _predicate="INSIDE"), spatial)
    assert r.verdict == Verdict.SATISFIED


def test_containment_contains_direction_is_the_mirror_of_inside():
    obj = _obj("o", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([obj]))
    r = evaluate(_c(ConstraintType.CONTAINMENT, "r1", "o", _predicate="CONTAINS"), spatial)
    assert r.verdict == Verdict.SATISFIED


def test_between_satisfied_on_segment():
    sofa, tv, table = _obj("sofa", (0, 0, -2)), _obj("tv", (0, 0, 2)), _obj("table", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([sofa, tv, table]))
    r = evaluate(_c(ConstraintType.POSITION, "table", "", between_a_id="sofa", between_b_id="tv"), spatial)
    assert r.verdict == Verdict.SATISFIED


def test_between_violated_beyond_endpoints():
    sofa, tv, table = _obj("sofa", (0, 0, -2)), _obj("tv", (0, 0, 2)), _obj("table", (0, 0, 5))
    spatial = SpatialScene(scene=_scene([sofa, tv, table]))
    r = evaluate(_c(ConstraintType.POSITION, "table", "", between_a_id="sofa", between_b_id="tv"), spatial)
    assert r.verdict == Verdict.VIOLATED


def test_between_partial_when_off_axis_beyond_tolerance():
    sofa, tv, table = _obj("sofa", (0, 0, -2)), _obj("tv", (0, 0, 2)), _obj("table", (5.0, 0, 0))
    spatial = SpatialScene(scene=_scene([sofa, tv, table]))
    r = evaluate(_c(ConstraintType.POSITION, "table", "", between_a_id="sofa", between_b_id="tv"), spatial)
    assert r.verdict == Verdict.PARTIAL


def test_missing_entity_is_unknown_not_a_crash():
    obj = _obj("o", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([obj]))
    r = evaluate(_c(ConstraintType.ORIENTATION, "o", "ghost"), spatial)
    assert r.verdict == Verdict.UNKNOWN


def test_reserved_type_returns_unknown_not_exception():
    obj = _obj("o", (0, 0, 0))
    spatial = SpatialScene(scene=_scene([obj]))
    r = evaluate(_c(ConstraintType.ALIGNMENT, "o", "w1"), spatial)
    assert r.verdict == Verdict.UNKNOWN


def test_evaluate_all_never_mutates_the_scene():
    sofa = _obj("sofa", (0, 0, -2.9))
    tv = _obj("tv", (0, 0, 2.0))
    scene = _scene([sofa, tv])
    spatial = SpatialScene(scene=scene)
    before = [(o.object_id, o.position, o.rotation_y) for o in scene.objects]
    constraints = (_c(ConstraintType.CONTACT, "sofa", "w1"), _c(ConstraintType.ORIENTATION, "sofa", "tv"))
    evaluate_all(constraints, spatial)
    after = [(o.object_id, o.position, o.rotation_y) for o in scene.objects]
    assert before == after

"""Deterministic checks for the P1 collision resolver
(research/spatial_architecture/collision_solver.py).

No GPU, no models: synthetic Scenes with a known-correct answer. See
docs/spatial_architecture/collision.md for the design these guard.
"""
from __future__ import annotations

from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall
from app.spatial.validation import validate_scene
from app.spatial.collision_solver import resolve_collisions

ROOM = Room(name="Living Room", type="living_room",
            boundary=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])


def _obj(object_id: str, x: float, z: float, conf: float, w: float = 1.0, d: float = 1.0) -> SceneObject:
    return SceneObject(object_id=object_id, semantic_type="sofa", room_id=ROOM.room_id,
                       position=(x, 0.0, z), dimensions=(w, 0.8, d),
                       confidence=Confidence(value=conf, source="test"))


def test_overlapping_pair_resolves_without_violation():
    a, b = _obj("obj_a", 0.0, 0.0, 0.9), _obj("obj_b", 0.1, 0.0, 0.4)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    resolved, resolutions = resolve_collisions(scene, relations=[])
    assert validate_scene(resolved) == []
    by_id = {r.object_id: r for r in resolutions}
    assert by_id["obj_a"].status == "kept"        # higher confidence, placed first
    assert by_id["obj_b"].status == "moved"
    assert by_id["obj_b"].distance_moved_m > 0.0


def test_wall_anchored_object_slides_along_tangent_not_off_the_wall():
    # wall centerline z=-3, thickness 0.15 -> inner (room-side) face z=-2.925.
    # -2.425 puts each object's near edge exactly flush against that face.
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("obj_a", 0.0, -2.425, 0.9)      # sits against the wall already
    b = _obj("obj_b", 0.1, -2.425, 0.4)      # overlaps a, also against the wall
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a, b])
    relations = [{"subject_id": "obj_b", "predicate": "AGAINST_WALL", "object_id": "wall_0"}]
    resolved, resolutions = resolve_collisions(scene, relations)
    assert validate_scene(resolved) == []
    moved = next(o for o in resolved.objects if o.object_id == "obj_b")
    assert moved.position[2] == -2.425, "sliding along a wall running in X must not change Z"
    assert moved.position[0] != 0.1


def test_wall_embedded_object_falls_back_to_a_small_perpendicular_nudge():
    # near edge at z=-2.955, 0.03 m inside the wall's inner face (-2.925) -
    # a footprint-residual-scale embedding a tangent slide can never clear.
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("obj_a", 0.0, -2.455, 0.9)
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a])
    relations = [{"subject_id": "obj_a", "predicate": "AGAINST_WALL", "object_id": "wall_0"}]
    resolved, resolutions = resolve_collisions(scene, relations)
    assert validate_scene(resolved) == []
    moved = next(o for o in resolved.objects if o.object_id == "obj_a")
    assert moved.position[0] == 0.0, "the perpendicular fallback must not shift the wall-tangent spot"
    assert moved.position[2] > -2.455, "must move away from the wall, into the room"
    assert moved.position[2] - (-2.455) <= 0.2 + 1e-9


def test_equal_confidence_ties_break_by_object_id():
    a, b = _obj("obj_z", 0.0, 0.0, 0.5), _obj("obj_a", 0.1, 0.0, 0.5)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    _, resolutions = resolve_collisions(scene, relations=[])
    order = [r.object_id for r in resolutions]
    assert order == ["obj_a", "obj_z"], "ties must break by object_id, not input order"
    assert next(r for r in resolutions if r.object_id == "obj_a").status == "kept"


def test_unresolvable_conflict_is_reported_not_fabricated():
    tight_room = Room(name="Closet", type="other",
                      boundary=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)])
    a = _obj("obj_a", 0.0, 0.0, 0.9)
    b = _obj("obj_b", 0.0, 0.0, 0.4)
    scene = Scene(project_id="p", rooms=[tight_room], objects=[a, b])
    resolved, resolutions = resolve_collisions(scene, relations=[])
    b_res = next(r for r in resolutions if r.object_id == "obj_b")
    assert b_res.status == "unresolved"
    assert b_res.candidates_tried > 0
    still_there = next(o for o in resolved.objects if o.object_id == "obj_b")
    assert still_there.position == (0.0, 0.0, 0.0), "unresolved objects are left where evidence put them"


def test_determinism_across_repeated_runs():
    a, b, c = _obj("obj_a", 0.0, 0.0, 0.9), _obj("obj_b", 0.05, 0.0, 0.6), _obj("obj_c", -0.05, 0.05, 0.3)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b, c])
    runs = []
    for _ in range(10):
        resolved, resolutions = resolve_collisions(scene.model_copy(deep=True), relations=[])
        runs.append(([o.position for o in resolved.objects],
                     [(r.object_id, r.status, r.distance_moved_m) for r in resolutions]))
    assert all(r == runs[0] for r in runs[1:])

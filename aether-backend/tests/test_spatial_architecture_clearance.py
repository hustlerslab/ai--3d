"""Deterministic checks for the P2 clearance engine
(research/spatial_architecture/clearance_engine.py).

No GPU, no models: synthetic Scenes with a known-correct answer. See
docs/spatial_architecture/clearance.md for the sourced thresholds these
tests exercise.
"""
from __future__ import annotations

from app.scene.schema import Opening, OpeningType, Room, Scene, SceneObject, Wall
from app.spatial.clearance_engine import (
    circulation_violations, door_swing_violations,
    functional_clearance_violations, pairwise_clearance_violations)

BIG_ROOM = Room(name="Room", type="living_room",
                boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])


def _obj(object_id, semantic_type, x, z, w=1.0, h=0.5, d=1.0, rotation_y=0.0):
    return SceneObject(object_id=object_id, semantic_type=semantic_type, room_id=BIG_ROOM.room_id,
                       position=(x, 0.0, z), rotation_y=rotation_y, dimensions=(w, h, d))


def test_pairwise_clearance_violation_when_gap_below_policy_minimum():
    sofa = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)          # z in [-0.45, 0.45]
    table = _obj("table_1", "coffee_table", 0.0, 0.9, w=1.2, d=0.6)  # z in [0.6, 1.2]
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[sofa, table])
    v = pairwise_clearance_violations(scene)
    assert len(v) == 1
    assert v[0].category == "CLEARANCE" and v[0].severity == "soft"
    assert v[0].required_m == 0.30
    assert abs(v[0].actual_m - 0.15) < 1e-6
    assert abs(v[0].deficit_m - 0.15) < 1e-6


def test_pairwise_clearance_ok_when_gap_meets_policy_minimum():
    sofa = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)
    table = _obj("table_1", "coffee_table", 0.0, 1.5, w=1.2, d=0.6)  # z in [1.2, 1.8], gap 0.75
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[sofa, table])
    assert pairwise_clearance_violations(scene) == []


def test_pairwise_clearance_skips_pairs_with_no_policy():
    a = _obj("a", "sofa", 0.0, 0.0, w=1.0, d=1.0)
    b = _obj("b", "plant", 0.0, 0.55, w=0.3, d=0.3)   # 0.05 m gap, but no sofa<->plant policy
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[a, b])
    assert pairwise_clearance_violations(scene) == []


def test_functional_envelope_blocked_by_obstruction():
    wardrobe = _obj("wardrobe_1", "wardrobe", 0.0, 0.0, w=1.0, d=0.6)   # front = +Z
    blocker = _obj("blocker_1", "plant", 0.0, 0.7, w=0.5, d=0.5)        # sits in the swing zone
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[wardrobe, blocker])
    v = functional_clearance_violations(scene)
    assert len(v) == 1
    assert v[0].subject_id == "wardrobe_1" and v[0].target_id == "blocker_1"
    assert v[0].category == "FUNCTIONAL" and v[0].severity == "soft"


def test_functional_envelope_clear_when_nothing_in_front():
    wardrobe = _obj("wardrobe_1", "wardrobe", 0.0, 0.0, w=1.0, d=0.6)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[wardrobe])
    assert functional_clearance_violations(scene) == []


def test_door_swing_blocked_by_furniture():
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    opening = Opening(opening_id="door_1", type=OpeningType.DOOR, wall_id="wall_0",
                      position=3.0, width=0.9, height=2.1)
    blocker = _obj("blocker_1", "plant", 0.0, -2.7, w=0.4, d=0.4)  # inside the swing sector
    scene = Scene(project_id="p", rooms=[BIG_ROOM], walls=[wall], openings=[opening], objects=[blocker])
    v = door_swing_violations(scene)
    assert len(v) == 1
    assert v[0].category == "FUNCTIONAL" and v[0].target_id == "blocker_1"


def test_door_swing_clear_when_nothing_in_the_arc():
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    opening = Opening(opening_id="door_1", type=OpeningType.DOOR, wall_id="wall_0",
                      position=3.0, width=0.9, height=2.1)
    far = _obj("far_1", "plant", 2.5, 2.5, w=0.4, d=0.4)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], walls=[wall], openings=[opening], objects=[far])
    assert door_swing_violations(scene) == []


def test_circulation_reports_when_entrance_itself_is_unreachable():
    # A filler that exactly matches the room boundary leaves no passable
    # floor anywhere. The engine must report this as a hard violation, not
    # silently return [] - an empty list here would make the single most
    # broken room this engine can see look like a clean report.
    filler = _obj("filler_1", "bookshelf", 0.0, 0.0, w=6.0, h=0.5, d=6.0)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[filler])
    v = circulation_violations(scene, entrance_xz=(-2.9, -2.9))
    assert len(v) == 1
    assert v[0].severity == "hard" and v[0].category == "CIRCULATION"


def test_circulation_hard_violation_when_object_fully_walled_off():
    barrier = _obj("barrier_1", "bookshelf", 0.0, 0.0, w=10.0, h=0.5, d=0.2)  # spans the whole room
    target = _obj("target_1", "sofa", 0.0, 2.0, w=0.5, d=0.5)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[barrier, target])
    v = circulation_violations(scene, entrance_xz=(0.0, -2.5))
    assert any(x.target_id == "target_1" and x.severity == "hard" for x in v)


def test_circulation_soft_violation_for_a_narrow_but_passable_gap():
    # a 0.64 m gap between two 2.7 m barriers - passable (> 2*PEDESTRIAN_INFLATION_M)
    # but narrower than SECONDARY_WALKWAY_MIN_M, with comfortable margin either
    # side of both thresholds against grid-quantization noise.
    left = _obj("left_1", "bookshelf", -1.67, 0.0, w=2.7, h=0.5, d=0.2)
    right = _obj("right_1", "bookshelf", 1.67, 0.0, w=2.7, h=0.5, d=0.2)
    target = _obj("target_1", "sofa", 0.0, 2.0, w=0.5, d=0.5)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[left, right, target])
    v = circulation_violations(scene, entrance_xz=(0.0, -2.5))
    target_v = [x for x in v if x.target_id == "target_1"]
    assert len(target_v) == 1
    assert target_v[0].severity == "soft"
    assert 0.0 < target_v[0].actual_m < 0.65


def test_circulation_no_violation_when_room_is_open():
    target = _obj("target_1", "sofa", 0.0, 2.0, w=0.5, d=0.5)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[target])
    assert circulation_violations(scene, entrance_xz=(0.0, -2.5)) == []


def test_determinism_across_repeated_runs():
    sofa = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)
    table = _obj("table_1", "coffee_table", 0.0, 0.9, w=1.2, d=0.6)
    wardrobe = _obj("wardrobe_1", "wardrobe", -2.0, -2.0, w=1.0, d=0.6)
    blocker = _obj("blocker_1", "plant", -2.0, -1.3, w=0.5, d=0.5)
    scene = Scene(project_id="p", rooms=[BIG_ROOM], objects=[sofa, table, wardrobe, blocker])
    runs = []
    for _ in range(5):
        pv = pairwise_clearance_violations(scene)
        fv = functional_clearance_violations(scene)
        cv = circulation_violations(scene, entrance_xz=(2.5, 2.5))
        runs.append(([(v.subject_id, v.target_id, v.required_m, v.actual_m) for v in pv],
                     [(v.subject_id, v.target_id) for v in fv],
                     [(v.target_id, v.severity, v.actual_m) for v in cv]))
    assert all(r == runs[0] for r in runs[1:])

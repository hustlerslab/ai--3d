"""Deterministic checks for the P4 repair engine
(research/spatial_architecture/repair_engine.py).

No GPU, no models: synthetic Scenes with a known-correct answer. See
docs/spatial_architecture/repair.md for the design these guard.
"""
from __future__ import annotations

from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall
from app.spatial.repair_engine import (
    TerminalState, classify_and_get_movers, identify_blocking_object,
    is_duplicate_pair, repair_scene)

ROOM = Room(name="Room", type="living_room",
           boundary=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])


def _obj(oid, st, x, z, w=1.0, d=1.0, conf=0.7):
    return SceneObject(object_id=oid, semantic_type=st, room_id=ROOM.room_id,
                       position=(x, 0.0, z), dimensions=(w, 0.5, d),
                       confidence=Confidence(value=conf, source="test"))


def test_already_valid_scene_is_a_noop():
    a = _obj("a", "sofa", 0.0, 0.0)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a])
    r = repair_scene(scene)
    assert r.terminal_state == TerminalState.ALREADY_VALID.value
    assert r.records == ()


def test_ordinary_collision_is_locally_repaired():
    a = _obj("a", "sofa", 0.0, 0.0, conf=0.9)
    b = _obj("b", "coffee_table", 0.1, 0.0, w=0.5, d=0.5, conf=0.4)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    r = repair_scene(scene)
    assert r.terminal_state == TerminalState.REPAIRED.value
    assert r.hard_after == 0
    moved_ids = {rec.subject_id for rec in r.records if rec.outcome == "MOVED"}
    assert "b" in moved_ids, "the lower-confidence object should move, not the higher-confidence one"
    kept_a = next(o for o in r.scene.objects if o.object_id == "a")
    assert kept_a.position == a.position, "the higher-confidence object must stay put"


def test_wall_collision_has_a_single_mover():
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("a", "sofa", 0.0, -2.99)   # embedded slightly in the wall
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a])
    r = repair_scene(scene)
    assert r.terminal_state == TerminalState.REPAIRED.value


def test_duplicate_pair_is_never_moved():
    a = _obj("a", "tv_unit", 0.0, 0.0, w=1.0, d=0.5, conf=0.7)
    b = _obj("b", "tv_unit", 0.02, 0.0, w=1.0, d=0.5, conf=0.65)
    assert is_duplicate_pair(a, b)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    r = repair_scene(scene)
    assert r.terminal_state == TerminalState.UPSTREAM_REQUIRED.value
    assert r.hard_after > 0, "a duplicate pair must remain flagged, not silently accepted"
    for rec in r.records:
        assert rec.outcome != "MOVED", "no repair action may move a suspected-duplicate pair"


def test_distinct_close_objects_are_not_misclassified_as_duplicates():
    a = _obj("a", "armchair", 0.0, 0.0, w=0.8, d=0.8)
    b = _obj("b", "armchair", 1.5, 0.0, w=0.8, d=0.8)
    assert not is_duplicate_pair(a, b)


def test_circulation_blocker_is_identified_and_can_be_repaired():
    # A 6x6 m room with explicit Wall objects (needed: circulation's
    # inflation logic only treats real Wall entities as obstacles, not the
    # bare boundary polygon - a bare-boundary-adjacent gap is lenient, a
    # limitation carried over unchanged from P2). 5.3 m wide, CENTERED:
    # 0.35 m on each side - both below the passable threshold, so currently
    # fully blocked. The 0.7 m of total slack, concentrated onto one side by
    # a nudge well within the lattice's search bound, opens a genuinely
    # passable gap - unlike a barrier with no slack at all (unrepairable by
    # any translation, tested in test_impossible_scene... above in spirit).
    small_room = Room(name="Room", type="living_room",
                      boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])
    walls = [
        Wall(wall_id="w_s", start=(-3.0, -3.0), end=(3.0, -3.0)),
        Wall(wall_id="w_e", start=(3.0, -3.0), end=(3.0, 3.0)),
        Wall(wall_id="w_n", start=(3.0, 3.0), end=(-3.0, 3.0)),
        Wall(wall_id="w_w", start=(-3.0, 3.0), end=(-3.0, -3.0)),
    ]
    barrier = SceneObject(object_id="barrier", semantic_type="bookshelf", room_id=small_room.room_id,
                          position=(0.0, 0.0, 0.0), dimensions=(5.3, 0.5, 0.2),
                          confidence=Confidence(value=0.3, source="test"))
    target = SceneObject(object_id="target", semantic_type="chair", room_id=small_room.room_id,
                         position=(0.0, 0.0, 2.0), dimensions=(0.5, 0.5, 0.5),
                         confidence=Confidence(value=0.9, source="test"))
    scene = Scene(project_id="p", rooms=[small_room], walls=walls, objects=[barrier, target])
    blocker = identify_blocking_object(scene, (0.0, -2.5), "target")
    assert blocker == "barrier"
    r = repair_scene(scene, entrance_xz=(0.0, -2.5))
    assert r.terminal_state in (TerminalState.REPAIRED.value, TerminalState.ESCALATE.value)


def test_no_blocking_object_found_is_upstream_required():
    # target simply outside the room boundary in a way no object explains -
    # identify_blocking_object must return None, not guess.
    scene = Scene(project_id="p", rooms=[ROOM], objects=[_obj("only", "chair", 0.0, 0.0)])
    assert identify_blocking_object(scene, (0.0, -2.5), "only") is None


def test_impossible_scene_terminates_explicitly_not_silently():
    tiny_room = Room(name="Tiny", type="other",
                     boundary=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)])
    a = _obj("a", "sofa", 0.0, 0.0, w=1.0, d=1.0, conf=0.9)
    b = _obj("b", "coffee_table", 0.0, 0.0, w=1.0, d=1.0, conf=0.3)
    scene = Scene(project_id="p", rooms=[tiny_room], objects=[a, b])
    r = repair_scene(scene)
    assert r.terminal_state in (TerminalState.ESCALATE.value, TerminalState.UNREPAIRABLE.value)
    assert r.hard_after > 0


def test_determinism_across_repeated_runs():
    a = _obj("a", "sofa", 0.0, 0.0, conf=0.9)
    b = _obj("b", "coffee_table", 0.1, 0.0, w=0.5, d=0.5, conf=0.4)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    runs = []
    for _ in range(20):
        r = repair_scene(scene.model_copy(deep=True))
        sig = (r.terminal_state, r.hard_after, round(r.soft_after, 6),
              tuple(sorted((o.object_id, o.position, o.rotation_y) for o in r.scene.objects)),
              tuple((rec.repair_type, rec.subject_id, rec.target_id, rec.outcome) for rec in r.records))
        runs.append(sig)
    assert all(r == runs[0] for r in runs[1:])

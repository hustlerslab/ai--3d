"""Deterministic checks for the P3 search-strategy harness
(research/spatial_architecture/scene_optimizer.py).

No GPU, no models: synthetic Scenes with a known-correct answer. See
docs/spatial_architecture/optimization.md and decisions.md's P3 entry for
the design these guard.
"""
from __future__ import annotations

from app.scene.schema import Confidence, Room, Scene, SceneObject
from research.spatial_architecture.scene_optimizer import (
    PlacementTask, solve_backtracking, solve_beam, solve_greedy,
    solve_greedy_then_repair)

ROOM = Room(name="Room", type="living_room",
           boundary=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])
BASE = Scene(project_id="p", rooms=[ROOM])


def _cand(oid, st, x, z, w=0.5, d=0.5, conf=0.7):
    return SceneObject(object_id=oid, semantic_type=st, room_id=ROOM.room_id,
                       position=(x, 0.0, z), dimensions=(w, 0.5, d),
                       confidence=Confidence(value=conf, source="test"))


def _dead_end_tasks():
    # object A's only two candidates: A1 (best-ranked) blocks B entirely;
    # A2 (second-ranked) leaves room for B. Mirrors optimization_baseline.md
    # P3.0 §4's constructed failure class in miniature.
    a1 = _cand("a", "box", 0.0, 0.0, w=1.0, d=1.0)     # centered - blocks b everywhere
    a2 = _cand("a", "box", -1.5, 0.0, w=1.0, d=1.0)    # off to one side - leaves room
    b1 = _cand("b", "box", 0.0, 0.0, w=1.0, d=1.0)     # only candidate, collides with a1
    return [PlacementTask("a", (a1, a2)), PlacementTask("b", (b1,))]


def test_greedy_hits_the_dead_end():
    r = solve_greedy(BASE, _dead_end_tasks())
    assert r.unplaced == ("b",)


def test_deep_backtracking_escapes_the_dead_end():
    r = solve_backtracking(BASE, _dead_end_tasks(), node_budget=1000, label="dfs")
    assert r.unplaced == ()
    assert r.hard_count == 0


def test_bounded_search_never_places_fewer_than_one_candidate_each_allows():
    # A budget that runs out mid-recursion must still return the best
    # PARTIAL assignment found, not discard every valid commitment - the
    # regression this test locks in (found by the optimization_benchmark.py
    # n=20/30 scaling runs: budget exhaustion was unwinding successfully
    # placed objects back to entirely empty).
    tasks = [PlacementTask(f"o{i}", (_cand(f"o{i}", "box", i * 2.0, 0.0),)) for i in range(5)]
    r = solve_backtracking(BASE, tasks, node_budget=2, label="bt")
    assert len(r.unplaced) < 5, "a tiny budget must not discard commitments already found valid"


def test_greedy_then_repair_cannot_fix_a_dead_end_it_did_not_cause():
    # Repair only reacts to a conflict AT commit time for the object being
    # placed; it never revisits an earlier object whose choice created the
    # dead end - this is a real, documented limitation, not a bug.
    r = solve_greedy_then_repair(BASE, _dead_end_tasks())
    assert r.unplaced == ("b",)


def test_beam_search_can_still_miss_when_width_is_too_small():
    # With only one plausible first-step candidate per beam slot and width 1,
    # beam search degenerates to greedy.
    r = solve_beam(BASE, _dead_end_tasks(), beam_width=1)
    assert r.unplaced == ("b",)


def test_determinism_across_repeated_runs():
    tasks = _dead_end_tasks()
    runs = []
    for _ in range(20):
        g = solve_greedy(BASE, tasks)
        bt = solve_backtracking(BASE, tasks, 1000, "dfs")
        bm = solve_beam(BASE, tasks, 3)
        runs.append(((g.unplaced, g.hard_count), (bt.unplaced, bt.hard_count),
                     (bm.unplaced, bm.hard_count)))
    assert all(r == runs[0] for r in runs[1:])

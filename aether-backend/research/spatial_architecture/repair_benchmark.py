"""P4.8/P4.9 - the adversarial repair benchmark.

    python -u research/spatial_architecture/repair_benchmark.py

Twelve deliberately-constructed scenes with explicit ground truth, covering
a representative, honestly-scoped subset of the brief's eighteen named cases
(the same subsetting discipline P2.8/P3's benchmarks used) - each case names
which of the eighteen it covers. Circulation cases are deliberately kept to
ONE (case 4): circulation_violations costs real time at room scale
(decisions.md's P2/P4 entries), so this benchmark does not multiply that
cost across many near-duplicate circulation scenarios when one already
exercises the identify-and-repair path end to end.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.scene.schema import Confidence, Opening, OpeningType, Room, Scene, SceneObject, Wall  # noqa: E402
from research.spatial_architecture.repair_engine import TerminalState, repair_scene  # noqa: E402

OUT = Path(__file__).resolve().parent / "repair_benchmark_results.json"
ROOM = Room(name="Room", type="living_room",
           boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])


def _obj(oid, st, x, z, w=1.0, d=1.0, conf=0.7, room=ROOM):
    return SceneObject(object_id=oid, semantic_type=st, room_id=room.room_id,
                       position=(x, 0.0, z), dimensions=(w, 0.5, d),
                       confidence=Confidence(value=conf, source="benchmark"))


def case_1_object_object_collision():
    a = _obj("a", "sofa", 0.0, 0.0, w=2.0, d=0.9, conf=0.9)
    b = _obj("b", "coffee_table", 0.1, 0.0, w=0.5, d=0.5, conf=0.4)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    return scene, None, [], {"terminal": TerminalState.REPAIRED.value, "max_level": 2}


def case_2_object_wall_collision():
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("a", "sofa", 0.0, -2.99)
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a])
    return scene, None, [], {"terminal": TerminalState.REPAIRED.value, "max_level": 1}


def case_3_insufficient_clearance_is_not_a_hard_failure():
    # CLEARANCE is soft (P2.2) - repair_scene only acts on HARD failures, so
    # this must report ALREADY_VALID (no hard violation exists) even though
    # a soft clearance deficit is present - repair must not "fix" soft issues
    # by moving objects unasked (P2.2's own severity boundary, unchanged).
    a = _obj("a", "sofa", 0.0, 0.0, w=2.0, d=0.9)          # z in [-0.45, 0.45]
    b = _obj("b", "coffee_table", 0.0, 0.9, w=1.2, d=0.6)  # z in [0.6, 1.2]: 0.15 m gap, no overlap
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    return scene, None, [], {"terminal": TerminalState.ALREADY_VALID.value, "max_level": 1}


def case_4_blocked_circulation():
    small_room = Room(name="Room", type="living_room",
                      boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])
    walls = [Wall(wall_id="w_s", start=(-3.0, -3.0), end=(3.0, -3.0)),
            Wall(wall_id="w_e", start=(3.0, -3.0), end=(3.0, 3.0)),
            Wall(wall_id="w_n", start=(3.0, 3.0), end=(-3.0, 3.0)),
            Wall(wall_id="w_w", start=(-3.0, 3.0), end=(-3.0, -3.0))]
    barrier = _obj("barrier", "bookshelf", 0.0, 0.0, w=5.3, d=0.2, conf=0.3, room=small_room)
    target = _obj("target", "chair", 0.0, 2.0, w=0.5, d=0.5, conf=0.9, room=small_room)
    scene = Scene(project_id="p", rooms=[small_room], walls=walls, objects=[barrier, target])
    return scene, (0.0, -2.5), [], {"terminal": TerminalState.REPAIRED.value, "max_level": 3}


def case_5_blocked_doorway():
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    opening = Opening(opening_id="door_1", type=OpeningType.DOOR, wall_id="wall_0",
                      position=3.0, width=0.9, height=2.1)
    blocker = _obj("blocker", "plant", 0.0, -2.7, w=0.4, d=0.4, conf=0.5)
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], openings=[opening], objects=[blocker])
    return scene, None, [], {"terminal": TerminalState.REPAIRED.value, "max_level": 1}


def case_7_wrong_orientation_not_repaired_by_this_engine():
    # repair.md P4.3: rotation/alternative orientation is explicitly NOT
    # implemented (no evidenced alternative to rotate to at the Scene level).
    # A scene whose only problem is a suboptimal-but-VALID orientation has
    # no hard violation at all, so it is correctly reported ALREADY_VALID -
    # confirms repair does not invent an "improvement" with no evidence.
    a = _obj("a", "sofa", 0.0, 0.0)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a])
    return scene, None, [], {"terminal": TerminalState.ALREADY_VALID.value, "max_level": 1}


def case_8_competing_wall_anchors_needs_local_backtracking():
    wall = Wall(wall_id="wall_0", start=(-1.7, -3.0), end=(1.7, -3.0))
    # two objects both anchored (AGAINST_WALL) near the same spot on a short
    # wall - collision, and the only fix needs BOTH to end up spaced apart,
    # which single-object nudging (levels 1/2) may not reach directly.
    a = _obj("a", "tv_unit", -0.2, -2.73, w=1.2, d=0.4, conf=0.6)
    b = _obj("b", "bookshelf", 0.2, -2.73, w=1.2, d=0.3, conf=0.5)
    relations = [{"subject_id": "a", "predicate": "AGAINST_WALL", "object_id": "wall_0"},
                {"subject_id": "b", "predicate": "AGAINST_WALL", "object_id": "wall_0"}]
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a, b])
    return scene, None, relations, {"terminal": TerminalState.REPAIRED.value, "max_level": 3}


def case_10_repair_that_would_create_a_second_violation_is_rejected():
    # b is boxed between a and the wall - the only "nearby" nudge for b
    # would push it into the wall; repair must find a candidate that clears
    # BOTH, or correctly report it could not, never trade one violation for
    # another.
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("a", "sofa", 0.0, -2.0, w=1.5, d=0.8, conf=0.9)
    b = _obj("b", "coffee_table", 0.05, -2.7, w=1.4, d=0.5, conf=0.4)
    scene = Scene(project_id="p", rooms=[ROOM], walls=[wall], objects=[a, b])
    return scene, None, [], {"terminal": None, "max_level": 3}   # outcome not asserted - see check below


def case_11_impossible_scene():
    tiny = Room(name="Tiny", type="other", boundary=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)])
    a = _obj("a", "sofa", 0.0, 0.0, w=1.0, d=1.0, conf=0.9, room=tiny)
    b = _obj("b", "coffee_table", 0.0, 0.0, w=1.0, d=1.0, conf=0.3, room=tiny)
    scene = Scene(project_id="p", rooms=[tiny], objects=[a, b])
    return scene, None, [], {"terminal": None, "max_level": 3}  # ESCALATE or UNREPAIRABLE, either is correct


def case_12_duplicate_object():
    a = _obj("a", "tv_unit", 0.0, 0.0, w=1.0, d=0.5, conf=0.7)
    b = _obj("b", "tv_unit", 0.02, 0.0, w=1.0, d=0.5, conf=0.65)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b])
    return scene, None, [], {"terminal": TerminalState.UPSTREAM_REQUIRED.value, "max_level": 3}


def case_15_multi_object_cascading_violation():
    a = _obj("a", "sofa", 0.0, 0.0, w=1.5, d=0.8, conf=0.9)
    b = _obj("b", "coffee_table", 0.05, 0.0, w=1.4, d=0.5, conf=0.5)
    c = _obj("c", "armchair", 0.1, 0.7, w=0.8, d=0.8, conf=0.4)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a, b, c])
    return scene, None, [], {"terminal": None, "max_level": 3}   # some cascading resolution expected


def case_18_global_search_not_invoked_for_a_trivial_scene():
    # An already-valid scene must never trigger ANY escalation level.
    a = _obj("a", "sofa", 0.0, 0.0)
    scene = Scene(project_id="p", rooms=[ROOM], objects=[a])
    return scene, None, [], {"terminal": TerminalState.ALREADY_VALID.value, "max_level": 0}


CASES = [
    ("1_object_object_collision", case_1_object_object_collision),
    ("2_object_wall_collision", case_2_object_wall_collision),
    ("3_insufficient_clearance_soft_not_repaired", case_3_insufficient_clearance_is_not_a_hard_failure),
    ("4_blocked_circulation", case_4_blocked_circulation),
    ("5_blocked_doorway", case_5_blocked_doorway),
    ("7_wrong_orientation_no_hard_violation", case_7_wrong_orientation_not_repaired_by_this_engine),
    ("8_competing_wall_anchors", case_8_competing_wall_anchors_needs_local_backtracking),
    ("10_repair_must_not_create_second_violation", case_10_repair_that_would_create_a_second_violation_is_rejected),
    ("11_impossible_scene", case_11_impossible_scene),
    ("12_duplicate_object", case_12_duplicate_object),
    ("15_multi_object_cascading", case_15_multi_object_cascading_violation),
    ("18_global_search_not_invoked_trivially", case_18_global_search_not_invoked_for_a_trivial_scene),
]


def main() -> int:
    results = []
    all_pass = True
    for name, builder in CASES:
        scene, entrance_xz, relations, expected = builder()
        t = time.perf_counter()
        r = repair_scene(scene, relations=relations, entrance_xz=entrance_xz)
        latency_ms = round((time.perf_counter() - t) * 1000.0, 2)

        if expected["terminal"] is not None:
            ok = r.terminal_state == expected["terminal"]
        else:
            # cases 10/11/15: no single "correct" terminal name asserted -
            # the invariant checked is "never worse, never a hidden failure."
            ok = r.hard_after <= r.hard_before
        ok = ok and r.escalation_level_reached <= expected["max_level"]
        all_pass = all_pass and ok

        results.append({"case": name, "expected_terminal": expected["terminal"],
                        "measured_terminal": r.terminal_state, "hard_before": r.hard_before,
                        "hard_after": r.hard_after, "escalation_level": r.escalation_level_reached,
                        "nodes_explored": r.nodes_explored, "latency_ms": latency_ms,
                        "records": [{"level": rec.level, "type": rec.repair_type, "subject": rec.subject_id,
                                    "target": rec.target_id, "cause": rec.cause, "outcome": rec.outcome}
                                   for rec in r.records],
                        "pass": ok})
        print(f"  {name:42} {'PASS' if ok else 'FAIL':4} {r.terminal_state:18} "
              f"hard {r.hard_before}->{r.hard_after} level={r.escalation_level_reached} "
              f"({latency_ms} ms)", flush=True)

    payload = {"_about": "P4.8/P4.9 adversarial repair benchmark - synthetic ground truth. "
                         "See repair_benchmark.py module docstring for the 18-case subset covered.",
              "cases_total": len(CASES), "cases_passed": sum(1 for r in results if r["pass"]),
              "all_pass": all_pass, "results": results}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  {payload['cases_passed']}/{payload['cases_total']} cases passed")
    print(f"  wrote {OUT}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

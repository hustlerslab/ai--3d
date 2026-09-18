"""P2.8 - the adversarial clearance benchmark.

    python -u research/spatial_architecture/clearance_benchmark.py

Ten deliberately-constructed scenes with explicit ground truth (not sampled
from real photos - P2's real-photo measurement lives in
integration_benchmark.py, and reported ZERO clearance violations because the
21-image/46-object fixture never grounds two policy-covered semantic_types
close together in the same scene; that absence is explained, not hidden, in
docs/spatial_architecture/clearance.md's P2 follow-up). This benchmark exists
specifically to prove detection works when the underlying condition is
actually present.

SCOPE, STATED HONESTLY. Covers: collision-vs-clearance independence, pairwise
clearance (met/violated), functional envelopes (wardrobe, door swing),
circulation (blocked/narrow/open), a combined dense-room case, and a room
that is physically non-functional end to end. Does NOT cover: dining-chair
pull-back clearance or kitchen-counter/island clearance against a WALL
(only object<->object pairwise clearance is implemented - a wall-relative
check needs a "front" convention, and for a dining chair "front" means "away
from its table," a different, unverified convention from the wardrobe's
"away from the wall," not built here without evidence for which is right -
see docs/spatial_architecture/clearance.md). "Irregular room" is not a
distinct code path (every check already operates on `Room.boundary` as an
arbitrary polygon) so it is not a separate case here.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.scene.schema import Opening, OpeningType, Room, Scene, SceneObject, Wall  # noqa: E402
from app.spatial.validation import validate_scene  # noqa: E402
from research.spatial_architecture.clearance_engine import (          # noqa: E402
    all_clearance_violations, circulation_violations, door_swing_violations,
    functional_clearance_violations, pairwise_clearance_violations)

OUT = Path(__file__).resolve().parent / "clearance_benchmark_results.json"

ROOM = Room(name="Room", type="living_room",
           boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])


def _obj(oid, st, x, z, w=1.0, h=0.5, d=1.0, ry=0.0):
    return SceneObject(object_id=oid, semantic_type=st, room_id=ROOM.room_id,
                       position=(x, 0.0, z), rotation_y=ry, dimensions=(w, h, d))


def case_collision_but_would_be_ok_clearance():
    # validate_scene reports a symmetric pair as TWO violations (one from
    # each object's own perspective) - existing, unchanged production
    # behaviour (app/spatial/validation.py:validate_scene), not new to P2.
    a = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)
    b = _obj("table_1", "coffee_table", 0.0, 0.2, w=1.2, d=0.6)   # overlaps a
    return Scene(project_id="p", rooms=[ROOM], objects=[a, b]), None, {
        "collision_hard": 2, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 0, "circulation_soft": 0}


def case_no_collision_bad_clearance():
    a = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)
    b = _obj("table_1", "coffee_table", 0.0, 0.9, w=1.2, d=0.6)   # 0.15 m gap
    return Scene(project_id="p", rooms=[ROOM], objects=[a, b]), None, {
        "collision_hard": 0, "clearance_soft": 1, "functional_soft": 0,
        "circulation_hard": 0, "circulation_soft": 0}


def case_adequate_clearance():
    a = _obj("sofa_1", "sofa", 0.0, 0.0, w=2.0, d=0.9)
    b = _obj("table_1", "coffee_table", 0.0, 1.5, w=1.2, d=0.6)   # 0.75 m gap
    return Scene(project_id="p", rooms=[ROOM], objects=[a, b]), None, {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 0, "circulation_soft": 0}


def case_wardrobe_unusable():
    a = _obj("wardrobe_1", "wardrobe", -2.0, -2.0, w=1.0, d=0.6)
    b = _obj("box_1", "plant", -2.0, -1.3, w=0.5, d=0.5)          # in the swing zone
    return Scene(project_id="p", rooms=[ROOM], objects=[a, b]), None, {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 1,
        "circulation_hard": 0, "circulation_soft": 0}


def case_blocked_doorway():
    # Also trips production's OWN pre-existing H4 BLOCKS_DOOR (a fixed 0.75 m
    # clearance rectangle, app/spatial/validation.py) in addition to the new
    # FUNCTIONAL door-swing check - two independent mechanisms correctly
    # agreeing on the same real obstruction, not a double-count bug.
    wall = Wall(wall_id="wall_0", start=(-3.0, -3.0), end=(3.0, -3.0))
    opening = Opening(opening_id="door_1", type=OpeningType.DOOR, wall_id="wall_0",
                      position=3.0, width=0.9, height=2.1)
    blocker = _obj("blocker_1", "plant", 0.0, -2.7, w=0.4, d=0.4)
    return Scene(project_id="p", rooms=[ROOM], walls=[wall], openings=[opening], objects=[blocker]), None, {
        "collision_hard": 1, "clearance_soft": 0, "functional_soft": 1,
        "circulation_hard": 0, "circulation_soft": 0}


def case_bed_circulation_blocked():
    # 5.9 m fits inside the 6 m room (no spurious OUTSIDE_ROOM) while still
    # sealing the bed's side off from the entrance.
    barrier = _obj("barrier_1", "bookshelf", 0.0, 0.0, w=5.9, h=0.5, d=0.2)
    bed = _obj("bed_1", "bed", 0.0, 2.0, w=1.5, d=2.0)
    return Scene(project_id="p", rooms=[ROOM], objects=[barrier, bed]), (0.0, -2.5), {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 1, "circulation_soft": 0}


def case_narrow_but_passable_corridor():
    left = _obj("left_1", "bookshelf", -1.67, 0.0, w=2.7, h=0.5, d=0.2)
    right = _obj("right_1", "bookshelf", 1.67, 0.0, w=2.7, h=0.5, d=0.2)
    target = _obj("target_1", "armchair", 0.0, 2.0, w=0.5, d=0.5)
    return Scene(project_id="p", rooms=[ROOM], objects=[left, right, target]), (0.0, -2.5), {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 0, "circulation_soft": 1}


def case_open_plan_no_false_positives():
    sofa = _obj("sofa_1", "sofa", -1.5, -1.5, w=2.0, d=0.9)
    table = _obj("table_1", "coffee_table", -1.5, -0.3, w=1.2, d=0.6)
    bed = _obj("bed_1", "bed", 1.5, 1.5, w=1.5, d=2.0)
    plant = _obj("plant_1", "plant", 2.5, -2.5, w=0.3, d=0.3)
    return Scene(project_id="p", rooms=[ROOM], objects=[sofa, table, bed, plant]), (0.0, -2.9), {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 0, "circulation_soft": 0}


def case_dense_room_combined_violations():
    sofa = _obj("sofa_1", "sofa", 0.0, -1.0, w=2.0, d=0.9)          # z in [-1.45, -0.55]
    table = _obj("table_1", "coffee_table", 0.0, -0.2, w=1.2, d=0.6)  # z in [-0.5, 0.1]: 0.05 m gap
    wardrobe = _obj("wardrobe_1", "wardrobe", -2.3, 1.5, w=1.0, d=0.6)
    blocker = _obj("blocker_1", "plant", -2.3, 2.2, w=0.5, d=0.5)      # functional soft
    barrier = _obj("barrier_1", "bookshelf", 1.8, 0.0, w=0.3, d=3.0)   # thin, corner - no full block
    overlap_a = _obj("chair_1", "armchair", 2.0, 2.0, w=0.8, d=0.8)
    overlap_b = _obj("chair_2", "armchair", 2.1, 2.0, w=0.8, d=0.8)    # collides with chair_1
    return Scene(project_id="p", rooms=[ROOM],
                objects=[sofa, table, wardrobe, blocker, barrier, overlap_a, overlap_b]), (0.0, -2.9), {
        "collision_hard": 2, "clearance_soft": 1, "functional_soft": 1,
        "circulation_hard": 0, "circulation_soft": 0}


def case_impossible_room():
    # Fills the room exactly (6x6, matching the boundary within tolerance, so
    # no spurious OUTSIDE_ROOM/collision noise) leaving NO usable floor at
    # all - even the entrance point has nowhere passable nearby. This is the
    # single most severe circulation failure the engine can report; the fix
    # in clearance_engine.py's circulation_violations makes it report one
    # explicit hard violation instead of silently returning [] (an empty
    # violation list would make an impossible room look clean).
    filler = _obj("filler_1", "bookshelf", 0.0, 0.0, w=6.0, h=0.5, d=6.0)
    return Scene(project_id="p", rooms=[ROOM], objects=[filler]), (-2.9, -2.9), {
        "collision_hard": 0, "clearance_soft": 0, "functional_soft": 0,
        "circulation_hard": 1, "circulation_soft": 0}


CASES = [
    ("collision_but_ok_clearance", case_collision_but_would_be_ok_clearance),
    ("no_collision_bad_clearance", case_no_collision_bad_clearance),
    ("adequate_clearance", case_adequate_clearance),
    ("wardrobe_unusable", case_wardrobe_unusable),
    ("blocked_doorway", case_blocked_doorway),
    ("bed_circulation_blocked", case_bed_circulation_blocked),
    ("narrow_but_passable_corridor", case_narrow_but_passable_corridor),
    ("open_plan_no_false_positives", case_open_plan_no_false_positives),
    ("dense_room_combined_violations", case_dense_room_combined_violations),
    ("impossible_room", case_impossible_room),
]


def measure(scene: Scene, entrance_xz) -> dict:
    hard = [v for v in validate_scene(scene) if v.severity == "hard"]
    clearance = pairwise_clearance_violations(scene)
    functional = functional_clearance_violations(scene) + door_swing_violations(scene)
    circulation = circulation_violations(scene, entrance_xz) if entrance_xz else []
    return {
        "collision_hard": len(hard),
        "clearance_soft": sum(1 for v in clearance if v.severity == "soft"),
        "functional_soft": sum(1 for v in functional if v.severity == "soft"),
        "circulation_hard": sum(1 for v in circulation if v.severity == "hard"),
        "circulation_soft": sum(1 for v in circulation if v.severity == "soft"),
    }


def main() -> int:
    results = []
    all_pass = True
    for name, builder in CASES:
        scene, entrance, expected = builder()
        t = time.perf_counter()
        measured = measure(scene, entrance)
        solver_ms = round((time.perf_counter() - t) * 1000.0, 2)

        t2 = time.perf_counter()
        measured2 = measure(scene, entrance)
        deterministic = measured == measured2
        validator_ms = round((time.perf_counter() - t2) * 1000.0, 2)

        ok = measured == expected
        all_pass = all_pass and ok and deterministic
        results.append({"case": name, "expected": expected, "measured": measured,
                        "pass": ok, "deterministic": deterministic,
                        "latency_ms": solver_ms, "validator_latency_ms": validator_ms})
        print(f"  {name:34} {'PASS' if ok else 'FAIL':4} "
              f"det={deterministic} {measured} ({solver_ms} ms)", flush=True)

    payload = {"_about": "P2.8 adversarial clearance benchmark - synthetic ground truth, "
                         "not real photos. See clearance_benchmark.py module docstring "
                         "for scope.",
              "cases_total": len(CASES), "cases_passed": sum(1 for r in results if r["pass"]),
              "all_deterministic": all(r["deterministic"] for r in results),
              "all_pass": all_pass, "results": results}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  {payload['cases_passed']}/{payload['cases_total']} cases passed, "
          f"deterministic={payload['all_deterministic']}")
    print(f"  wrote {OUT}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

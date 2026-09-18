"""P3.2/P3.6/P3.9 - the comparative search-strategy benchmark.

    python -u research/spatial_architecture/optimization_benchmark.py

Two parts:
  1. ADVERSARIAL: `wall_dead_end`, built directly from the constructible
     failure class optimization_baseline.md P3.0 §4 names - two wall-anchored
     objects whose combined width exceeds the only long wall, where the
     greedy-preferred (centered) placement for the first blocks the second,
     but a non-centered split fits both. Plus `regular_baseline`, a
     non-adversarial sanity scene every strategy should solve identically.
  2. SCALING: N in {5, 10, 15, 20, 30} objects on a deterministic golden-angle
     spiral (a fixed, reproducible layout - not random), measuring latency and
     explored-node count per strategy as N grows (P3.8's complexity input).

Determinism (P3.9): every case is run 20 times per strategy; results must be
byte-identical (object positions, hard/soft score, nodes explored) across all
20 runs, since nothing in scene_optimizer.py has any randomness.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall  # noqa: E402
from research.spatial_architecture.scene_optimizer import PlacementTask, STRATEGIES  # noqa: E402

OUT = Path(__file__).resolve().parent / "optimization_benchmark_results.json"
BIG_ROOM = Room(name="Room", type="living_room",
                boundary=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])
GOLDEN_ANGLE = math.pi * (3 - 5 ** 0.5)


def _mk(oid: str, st: str, x: float, z: float, w: float, d: float, conf: float = 0.7) -> SceneObject:
    return SceneObject(object_id=oid, semantic_type=st, room_id=BIG_ROOM.room_id,
                       position=(x, 0.0, z), dimensions=(w, 0.5, d),
                       confidence=Confidence(value=conf, source="benchmark"))


def _wall_candidates(oid: str, st: str, wall: Wall, w: float, d: float,
                     room_center_z: float, step: float = 0.1) -> tuple[SceneObject, ...]:
    """Ranked positions along `wall`, closest-to-centered first, object
    pushed `d/2 + gap` off the wall into the room - the same shape of
    candidate `_wall_aligned_candidates` (compiler.py) already produces."""
    dx, dz = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
    length = math.hypot(dx, dz)
    tangent = (dx / length, dz / length)
    normal = (-tangent[1], tangent[0])
    if (room_center_z - wall.start[1]) * normal[1] < 0:
        normal = (-normal[0], -normal[1])
    center_t = length / 2.0
    lo, hi = w / 2.0, length - w / 2.0
    ts = []
    t = lo
    while t <= hi + 1e-9:
        ts.append(round(t, 4))
        t += step
    ts.sort(key=lambda tt: (abs(tt - center_t), tt))
    # offset from the wall's CENTERLINE must clear its own half-thickness
    # first, then the object's own half-depth plus a small gap - forgetting
    # the half-thickness term (an already-documented P1 lesson,
    # scene_from_photo.py's wall-centerline fix) places the object inside
    # the wall's own collision rectangle, so every candidate fails COLLIDES_WALL.
    off = wall.thickness / 2.0 + d / 2.0 + 0.02
    out = []
    for t in ts:
        px = wall.start[0] + tangent[0] * t + normal[0] * off
        pz = wall.start[1] + tangent[1] * t + normal[1] * off
        yaw = math.atan2(-normal[0], -normal[1])
        out.append(SceneObject(object_id=oid, semantic_type=st, room_id=BIG_ROOM.room_id,
                               position=(round(px, 4), 0.0, round(pz, 4)), rotation_y=round(yaw, 4),
                               dimensions=(w, 0.5, d), confidence=Confidence(value=0.7, source="benchmark")))
    return tuple(out)


def case_wall_dead_end():
    """Wall length 3.4 m. TV (1.8 m) centered leaves two 0.8 m stubs -
    too short for the 1.6 m bookshelf anywhere. TV flush to one end leaves a
    1.6 m span that fits the bookshelf exactly. Greedy's first (centered)
    TV candidate creates the dead end; any strategy that explores beyond it
    finds the split that fits both."""
    wall = Wall(wall_id="wall_0", start=(-1.7, -3.0), end=(1.7, -3.0))
    tv_cands = _wall_candidates("tv_1", "tv_unit", wall, 1.8, 0.5, room_center_z=0.0)
    shelf_cands = _wall_candidates("shelf_1", "bookshelf", wall, 1.6, 0.3, room_center_z=0.0)
    tasks = [PlacementTask("tv_1", tv_cands), PlacementTask("shelf_1", shelf_cands)]
    base = Scene(project_id="p", rooms=[BIG_ROOM], walls=[wall])
    return base, tasks


def case_regular_baseline():
    wall = Wall(wall_id="wall_0", start=(-4.0, -5.0), end=(4.0, -5.0))
    sofa_cands = tuple(_mk("sofa_1", "sofa", x, -2.0, 2.0, 0.9) for x in (0.0,))
    table_cands = tuple(_mk("table_1", "coffee_table", x, -0.5, 1.2, 0.6) for x in (0.0, 0.3, -0.3))
    tv_cands = _wall_candidates("tv_1", "tv_unit", wall, 1.6, 0.4, room_center_z=0.0)
    shelf_cands = tuple(_mk("shelf_1", "bookshelf", x, 3.0, 1.0, 0.3) for x in (-3.0, -2.5, -2.0))
    tasks = [PlacementTask("sofa_1", sofa_cands), PlacementTask("table_1", table_cands),
            PlacementTask("tv_1", tv_cands), PlacementTask("shelf_1", shelf_cands)]
    base = Scene(project_id="p", rooms=[BIG_ROOM], walls=[wall])
    return base, tasks


def scaling_tasks(n: int, k_candidates: int = 6) -> list[PlacementTask]:
    tasks = []
    for i in range(n):
        oid = f"box_{i:02d}"
        angle = i * GOLDEN_ANGLE
        cands = tuple(_mk(oid, "box", round(0.4 + 0.35 * k, 4) * math.cos(angle),
                         round(0.4 + 0.35 * k, 4) * math.sin(angle), 0.5, 0.5, conf=0.5 + 0.01 * i)
                     for k in range(k_candidates))
        tasks.append(PlacementTask(oid, cands))
    return tasks


def run_case(name: str, base: Scene, tasks: list[PlacementTask]) -> dict:
    out = {"case": name, "n_objects": len(tasks)}
    for strat_name, fn in STRATEGIES.items():
        t = time.perf_counter()
        result = fn(base, tasks)
        latency_ms = round((time.perf_counter() - t) * 1000.0, 3)
        out[strat_name] = {"hard": result.hard_count, "soft_deficit": round(result.soft_deficit, 4),
                           "unplaced": list(result.unplaced), "nodes_explored": result.nodes_explored,
                           "latency_ms": latency_ms}
    return out


def determinism_check(base: Scene, tasks: list[PlacementTask], runs: int = 20) -> dict:
    out = {}
    for strat_name, fn in STRATEGIES.items():
        signatures = []
        for _ in range(runs):
            r = fn(base, tasks)
            sig = (tuple(sorted((o.object_id, o.position, o.rotation_y) for o in r.scene.objects)),
                  r.hard_count, round(r.soft_deficit, 6), r.nodes_explored, r.unplaced)
            signatures.append(sig)
        out[strat_name] = all(s == signatures[0] for s in signatures[1:])
    return out


def main() -> int:
    results = {"adversarial": [], "scaling": [], "determinism": {}}

    print("-- adversarial --", flush=True)
    for name, builder in (("wall_dead_end", case_wall_dead_end), ("regular_baseline", case_regular_baseline)):
        base, tasks = builder()
        entry = run_case(name, base, tasks)
        results["adversarial"].append(entry)
        for strat in STRATEGIES:
            print(f"  {name:20} {strat:22} hard={entry[strat]['hard']} "
                  f"unplaced={entry[strat]['unplaced']} nodes={entry[strat]['nodes_explored']} "
                  f"({entry[strat]['latency_ms']} ms)", flush=True)

    print("\n-- scaling --", flush=True)
    for n in (5, 10, 15, 20, 30):
        base = Scene(project_id="p", rooms=[BIG_ROOM])
        tasks = scaling_tasks(n)
        entry = run_case(f"n{n}", base, tasks)
        results["scaling"].append(entry)
        for strat in STRATEGIES:
            print(f"  n={n:2} {strat:22} hard={entry[strat]['hard']} "
                  f"nodes={entry[strat]['nodes_explored']:5} ({entry[strat]['latency_ms']} ms)", flush=True)

    print("\n-- determinism (20 runs) --", flush=True)
    base, tasks = case_wall_dead_end()
    results["determinism"]["wall_dead_end"] = determinism_check(base, tasks)
    base2 = Scene(project_id="p", rooms=[BIG_ROOM])
    results["determinism"]["n15"] = determinism_check(base2, scaling_tasks(15))
    for case_name, det in results["determinism"].items():
        print(f"  {case_name}: {det}", flush=True)

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

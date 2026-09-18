"""P5.9/P5.13/P5.14 - the tilted-wall sweep, performance, and determinism
benchmark.

    python -u research/spatial_architecture/wall_benchmark.py

P5.9: reproduces the historical ~11 degree tilted-wall failure as a
controlled sweep (0/5/10/11/15/20 degrees), comparing OLD (production's own
`wall_rectangle`, a single fixed-height cross-section) against NEW
(`object_wall_collides`, height-aware) on a SHORT and a TALL object, both
placed with the same small, realistic gap (0.05 m) at the floor reference -
never at exactly zero gap, since real photo evidence never measures exactly
zero either (wall_geometry.py's own test docstrings explain why exact-zero
is a degenerate case for a leaning wall).

P5.13: representation size, construction latency, and collision-check
latency at 1/4/10/50/100 walls - confirms the fix stays practical at
residential scale, not just correct.

P5.14: 20 repeated runs of the same tilted-wall case, comparing every
computed field for exact equality - the representation must not be merely
correct once, but reproducibly correct.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.scene.schema import Confidence, SceneObject                    # noqa: E402
from app.spatial.geometry import convex_polygons_overlap, wall_rectangle  # noqa: E402
from app.spatial.validation import object_footprint                     # noqa: E402
from research.spatial_architecture.wall_geometry import (               # noqa: E402
    TiltedWall, cross_section_at_height, object_wall_collides, up_from_normal)

OUT = Path(__file__).resolve().parent / "wall_benchmark_results.json"


def _obj(z: float, h: float, d: float = 0.7, w: float = 1.5) -> SceneObject:
    return SceneObject(object_id="o", semantic_type="bed", room_id="r",
                       position=(0.0, 0.0, z), dimensions=(w, h, d),
                       confidence=Confidence(value=0.9))


def _wall_at_tilt(tilt_deg: float) -> TiltedWall:
    """A wall whose fitted normal has exactly `tilt_deg` of Y-component,
    same horizontal bearing as the real measured master_bedroom case
    (nx:nz ratio preserved), so 0 degrees is a byte-identical ordinary
    vertical wall and 20 degrees is a controlled extrapolation past the
    real measured ~11 degree case."""
    ny = math.sin(math.radians(tilt_deg))
    horiz_scale = math.sqrt(max(0.0, 1.0 - ny * ny))
    # bearing ratio from the real measured normal (0.06009, -0.98018) in XZ
    bearing = (0.06009, -0.98018)
    mag = math.hypot(*bearing)
    nx, nz = bearing[0] / mag * horiz_scale, bearing[1] / mag * horiz_scale
    normal = (nx, ny, nz)
    up = up_from_normal(normal)
    return TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0), extrusion_direction=up)


def old_collides(obj: SceneObject, wall: TiltedWall) -> bool:
    """Production's own check, exactly: ONE fixed-height rectangle
    (`wall.start`/`wall.end`, the floor reference), object height never
    read at all."""
    rect = wall_rectangle(wall.start, wall.end, wall.thickness)
    return convex_polygons_overlap(object_footprint(obj), rect)


def tilt_sweep() -> list[dict]:
    results = []
    for tilt_deg in (0, 5, 10, 11, 15, 20):
        wall = _wall_at_tilt(tilt_deg)
        s0, e0 = cross_section_at_height(wall, 0.0)
        inner_face_z = min(s0[1], e0[1]) + wall.thickness / 2.0
        gap = 0.05
        short_obj = _obj(inner_face_z + gap + 0.35, h=0.15)   # bedside-table scale
        tall_obj = _obj(inner_face_z + gap + 0.35, h=2.0)     # wardrobe scale
        entry = {
            "tilt_deg": tilt_deg,
            "short_object": {"old_collides": old_collides(short_obj, wall),
                             "new_collides": object_wall_collides(short_obj, wall)},
            "tall_object": {"old_collides": old_collides(tall_obj, wall),
                            "new_collides": object_wall_collides(tall_obj, wall)},
        }
        results.append(entry)
    return results


def performance_sweep() -> list[dict]:
    results = []
    for n in (1, 4, 10, 50, 100):
        t0 = time.perf_counter()
        walls = [_wall_at_tilt(11.0) for _ in range(n)]
        construct_ms = (time.perf_counter() - t0) * 1000.0
        obj = _obj(-2.6, h=1.0)
        t1 = time.perf_counter()
        for w in walls:
            object_wall_collides(obj, w)
        collide_ms = (time.perf_counter() - t1) * 1000.0
        results.append({"n_walls": n, "construct_ms": round(construct_ms, 4),
                        "collide_all_ms": round(collide_ms, 4),
                        "collide_per_wall_us": round(collide_ms * 1000.0 / n, 2)})
    return results


def determinism_check(runs: int = 20) -> bool:
    wall = _wall_at_tilt(11.0)
    obj = _obj(-2.6, h=1.0)
    signatures = []
    for _ in range(runs):
        w = _wall_at_tilt(11.0)
        sig = (w.extrusion_direction, cross_section_at_height(w, 0.5),
              cross_section_at_height(w, 1.5), object_wall_collides(obj, w))
        signatures.append(sig)
    return all(s == signatures[0] for s in signatures[1:])


def main() -> int:
    print("-- P5.9 tilt sweep (OLD vs NEW) --", flush=True)
    sweep = tilt_sweep()
    for e in sweep:
        print(f"  {e['tilt_deg']:2}deg  short: old={e['short_object']['old_collides']!s:5} "
              f"new={e['short_object']['new_collides']!s:5}   "
              f"tall: old={e['tall_object']['old_collides']!s:5} "
              f"new={e['tall_object']['new_collides']!s:5}", flush=True)

    print("\n-- P5.13 performance --", flush=True)
    perf = performance_sweep()
    for e in perf:
        print(f"  n={e['n_walls']:3}  construct={e['construct_ms']} ms  "
              f"collide_all={e['collide_all_ms']} ms  per_wall={e['collide_per_wall_us']} us", flush=True)

    print("\n-- P5.14 determinism (20 runs) --", flush=True)
    det = determinism_check()
    print(f"  deterministic: {det}", flush=True)

    payload = {"_about": "P5.9/P5.13/P5.14 tilted-wall benchmark", "tilt_sweep": sweep,
              "performance": perf, "deterministic": det}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

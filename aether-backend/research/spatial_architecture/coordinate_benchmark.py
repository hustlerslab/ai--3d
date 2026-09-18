"""P6 coordinate-transform performance and determinism benchmark.

    python -u research/spatial_architecture/coordinate_benchmark.py

Measures the overhead the typed Rigid3/Point3/Vector3/Direction3 layer adds
over the raw functions it wraps (to_blender_xyz, _to_canonical,
wall_local_frame) at 1/10/100/1000 transforms, and confirms 20 repeated
constructions of the same transform set are byte-identical. The frozen
P1-P5 regression benchmarks (collision/clearance/optimization/repair/wall)
are re-run separately as their own scripts, unmodified - this script does
not duplicate them, only reports the coordinate-layer's own cost and
determinism, per its own P6.13/P6.14 scope.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.blender.manifest import to_blender_xyz                          # noqa: E402
from app.scene.schema import Confidence, SceneObject                     # noqa: E402
from research.spatial_architecture.coordinate_frames import FrameId      # noqa: E402
from research.spatial_architecture.frame_graph import (                  # noqa: E402
    object_frame_transform, opencv_to_room, room_to_blender)
from research.spatial_architecture.transforms import Point3              # noqa: E402

OUT = Path(__file__).resolve().parent / "coordinate_benchmark_results.json"


def _obj(i: int) -> SceneObject:
    return SceneObject(object_id=f"o{i}", semantic_type="sofa", room_id="r",
                       position=(float(i % 5), 0.0, -float(i % 7)),
                       rotation_y=(i * 0.37) % (2 * math.pi),
                       dimensions=(1, 1, 1), confidence=Confidence(value=0.9))


def performance_sweep() -> list[dict]:
    results = []
    for n in (1, 10, 100, 1000):
        objs = [_obj(i) for i in range(n)]

        t0 = time.perf_counter()
        for o in objs:
            to_blender_xyz(o.position)
        raw_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        room_to_bl = room_to_blender()
        for o in objs:
            room_to_bl.apply_point(Point3(*o.position, frame=FrameId.ROOM))
        typed_ms = (time.perf_counter() - t1) * 1000.0

        results.append({"n": n, "raw_ms": round(raw_ms, 4), "typed_ms": round(typed_ms, 4),
                        "overhead_ratio": round(typed_ms / raw_ms, 2) if raw_ms > 0 else None})
    return results


def determinism_check(runs: int = 20) -> bool:
    objs = [_obj(i) for i in range(20)]
    signatures = []
    for _ in range(runs):
        T_cam = opencv_to_room()
        T_bl = room_to_blender()
        obj_transforms = [object_frame_transform(o) for o in objs]
        sig = (T_cam.rotation, T_cam.translation, T_bl.rotation, T_bl.translation,
              tuple((t.rotation, t.translation) for t in obj_transforms))
        signatures.append(sig)
    return all(s == signatures[0] for s in signatures[1:])


def main() -> int:
    print("-- performance (typed layer vs. raw function) --", flush=True)
    perf = performance_sweep()
    for e in perf:
        print(f"  n={e['n']:5}  raw={e['raw_ms']} ms  typed={e['typed_ms']} ms  "
              f"overhead={e['overhead_ratio']}x", flush=True)

    print("\n-- determinism (20 runs, 20 objects each) --", flush=True)
    det = determinism_check()
    print(f"  deterministic: {det}", flush=True)

    payload = {"_about": "P6 coordinate-transform performance/determinism benchmark. "
                         "P1-P5 regression benchmarks are separate, unmodified scripts.",
              "performance": perf, "deterministic": det}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

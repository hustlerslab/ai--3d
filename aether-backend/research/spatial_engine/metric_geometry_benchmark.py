"""Spatial engine Phase 2: does METRIC geometry repair the Phase 1 failure?

    python -u research/spatial_engine/metric_geometry_benchmark.py

Research only. Production imports unchanged; `app.spatial.planes` still has zero
production importers.

THE CONTROLLED VARIABLE IS THE GEOMETRY MODEL, AND NOTHING ELSE. Same 48 cases,
same images, same annotated boxes, same labels, same RANSAC seed and iteration
count, same extent and inlier requirements, same object exclusion, same
object-cut rejection, same metrics. Phase 1's arm is re-run here through the same
harness rather than quoted, so the comparison cannot drift on incidentals.

One threshold DOES change between arms, by design rather than by tuning: a metric
point map routes `wall_contact` to the absolute 0.12 m rule, an unscaled one to
the 0.04-of-room-extent rule. That switch is what "metric" means, it is driven by
`MetricGeometryResult.metric_scale`, and a provider cannot claim metres it does
not have.

GEOMETRY DIAGNOSTICS ARE READ BEFORE ACCURACY. Phase 1's real finding was not its
false-wall rate, it was Manhattan residuals of 20-30 degrees and an 8.4x spread in
scene scale - a point cloud that was not Euclidean. If those two numbers do not
move, a better accuracy score would be luck; if they move but accuracy does not,
the fault has relocated to the wall-distance formulation. So Step 4 is computed
and reported first.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.metric_geometry import (                 # noqa: E402
    HEIGHT, WIDTH, DepthAnythingRelativeProvider, MoGe2Provider)

DATASET = ROOT / "research" / "phase1g" / "dataset.json"
FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
PHASE_1H = ROOT / "research" / "phase1h" / "results.json"
PHASE_1 = HERE / "geometric_wall_contact_results.json"
OUT_BENCH = HERE / "metric_geometry_benchmark.json"
OUT_RESULTS = HERE / "metric_geometry_results.json"

#: Recorded from primary sources this session. UniDepthV2 is excluded on BOTH a
#: licence ground and a platform ground, and the reasons are kept verbatim rather
#: than summarised to "unavailable".
LICENCES = [
    {"model": "MoGe-2", "checkpoint": "Ruicheng/moge-2-vitl",
     "code_licence": "MIT (vendored DINOv2 under Apache-2.0)",
     "checkpoint_licence": "MIT (stated on the Hugging Face model card)",
     "commercial_use": "PERMITTED",
     "source": "https://github.com/microsoft/MoGe , "
               "https://huggingface.co/Ruicheng/moge-2-vitl"},
    {"model": "UniDepthV2", "checkpoint": "not fetched",
     "code_licence": "Creative Commons BY-NC 4.0",
     "checkpoint_licence": "not separately stated",
     "commercial_use": "PROHIBITED - non-commercial licence",
     "source": "https://github.com/lpiccinelli-eth/UniDepth",
     "blocked": "TWO independent blockers. (1) LICENCE: CC BY-NC 4.0 forbids "
                "commercial use, and Allure is a commercial product, so a good "
                "score would not be usable. (2) PLATFORM: the repository requires "
                "Linux and compiles custom CUDA ops; this host is Windows. Not "
                "run, not estimated."},
    {"model": "Depth Anything V2 Small",
     "checkpoint": "depth-anything/Depth-Anything-V2-Small-hf",
     "code_licence": "Apache-2.0",
     "checkpoint_licence": "Apache-2.0 (Small only; Base/Large/Giant are "
                           "CC-BY-NC-4.0)",
     "commercial_use": "PERMITTED",
     "source": "https://github.com/DepthAnything/Depth-Anything-V2"},
]


def gpu_used_mib() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:                                              # noqa: BLE001
        return -1


def system_ram() -> dict:
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        s = MS()
        s.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return {"total_gb": round(s.ullTotalPhys / 1e9, 1),
                "available_gb": round(s.ullAvailPhys / 1e9, 1),
                "load_pct": s.dwMemoryLoad}
    except Exception:                                              # noqa: BLE001
        return {}


def wilson(successes: int, total: int):
    if not total:
        return None
    z = 1.959963985
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return [round(100 * max(0.0, centre - half), 1),
            round(100 * min(1.0, centre + half), 1)]


def load_cases() -> list[dict]:
    """Identical to Phase 1: the 1g dataset plus the 5 historical negatives."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = [{
        "case_id": c["case_id"], "scene_id": c["scene_id"], "image": c["image_path"],
        "object_id": c["object_id"], "object_type": c["object_type"],
        "bbox": c["bbox"], "category": c["category"],
        "truth": c["ground_truth_against_wall"],
        "source_domain": "generated" if c["origin"] == "phase1g" else "historical",
    } for c in data["cases"]]

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for room in fixture["rooms"]:
        by_id = {o["id"]: o for o in room["objects"]}
        for truth in room.get("binary_relations", []):
            if (truth["chain"] == "against" and truth["verdict"] == "TRUE"
                    and truth.get("wall") is False):
                obj = by_id[truth["source"]]
                cases.append({
                    "case_id": f"hist_neg.{obj['id']}",
                    "scene_id": f"hist_{room['room_key']}", "image": room["image"],
                    "object_id": obj["id"], "object_type": obj["type"],
                    "bbox": obj["bbox"],
                    "category": "A" if obj["type"] in ("ottoman", "coffee_table") else "B",
                    "truth": False, "source_domain": "historical"})
    return cases


def summarise(subset: list[dict]) -> dict:
    neg = [r for r in subset if r["ground_truth_against_wall"] is False]
    pos = [r for r in subset if r["ground_truth_against_wall"] is True]
    dn = [r for r in neg if r["predicted_against_wall"] is not None]
    dp = [r for r in pos if r["predicted_against_wall"] is not None]
    tn = sum(1 for r in dn if r["predicted_against_wall"] is False)
    fp = len(dn) - tn
    tp = sum(1 for r in dp if r["predicted_against_wall"] is True)
    fn = len(dp) - tp

    def pct(a, b):
        return None if not b else round(100.0 * a / b, 1)

    return {
        "cases": len(subset), "negatives": len(neg), "positives": len(pos),
        "tn": tn, "fp": fp, "tp": tp, "fn": fn,
        "unknown_negatives": len(neg) - len(dn),
        "unknown_positives": len(pos) - len(dp),
        "unknown_rate_negatives_pct": pct(len(neg) - len(dn), len(neg)),
        "false_wall_rate_decided_pct": pct(fp, len(dn)),
        "false_wall_ci95_decided": wilson(fp, len(dn)),
        "false_wall_rate_all_pct": pct(fp, len(neg)),
        "no_recall_decided_pct": pct(tn, len(dn)),
        "no_recall_ci95_decided": wilson(tn, len(dn)),
        "positive_recall_decided_pct": pct(tp, len(dp)),
        "precision_pct": pct(tp, tp + fp),
        "balanced_accuracy_pct": (round(50.0 * (tn / len(dn) + tp / len(dp)), 1)
                                  if dn and dp else None),
        "accuracy_decided_pct": pct(tn + tp, len(dn) + len(dp)),
        "coverage_pct": pct(len(dn) + len(dp), len(subset)),
    }


def auc(pos: list[float], neg: list[float]):
    """P(a wall-contact case scores closer than a free-standing one)."""
    if not pos or not neg:
        return None
    wins = sum(1 for p in pos for n in neg if p < n)
    ties = sum(1 for p in pos for n in neg if p == n)
    return round((wins + 0.5 * ties) / (len(pos) * len(neg)), 4)


def benchmark_model(provider, image: Path, warm_iters: int = 5) -> dict:
    """Step 1: cost and output characteristics for one provider."""
    import torch

    row = {"name": provider.name, "version": provider.version, "status": "ok"}
    ram_before = system_ram().get("available_gb")
    torch.cuda.reset_peak_memory_stats()

    started = time.perf_counter()
    try:
        provider.load()
    except Exception as exc:                                       # noqa: BLE001
        row.update(status="FAILED", blocker=f"load: {type(exc).__name__}: {exc}"[:300])
        return row
    row["load_s"] = round(time.perf_counter() - started, 2)

    started = time.perf_counter()
    try:
        first = provider.predict(image)
    except Exception as exc:                                       # noqa: BLE001
        row.update(status="FAILED",
                   blocker=f"predict: {type(exc).__name__}: {exc}"[:300])
        provider.unload()
        return row
    row["cold_inference_s"] = round(time.perf_counter() - started, 2)

    timings = []
    last = first
    for _ in range(warm_iters):
        started = time.perf_counter()
        last = provider.predict(image)
        timings.append(time.perf_counter() - started)
    row["warm_median_s"] = round(statistics.median(timings), 3)
    row["warm_p95_s"] = round(sorted(timings)[-1], 3)

    # Determinism: identical input twice, largest absolute disagreement.
    both = first.valid & last.valid
    row["determinism_max_abs_diff"] = (
        float(np.abs(first.point_map[both] - last.point_map[both]).max())
        if both.any() else None)

    row.update({
        "peak_vram_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2),
        "vram_used_while_loaded_mib": gpu_used_mib(),
        "cpu_ram_delta_gb": (round(ram_before - system_ram().get("available_gb", 0), 2)
                             if ram_before else None),
        "output_resolution": f"{first.point_map.shape[1]}x{first.point_map.shape[0]}",
        "output_type": ("dense point map + depth + intrinsics"
                        if first.camera_intrinsics is not None else "dense point map"),
        "dense_point_map": True,
        "metric": first.metric_scale,
        "units": first.units,
        "intrinsics_predicted": first.camera_intrinsics is not None,
        "fov_deg": first.fov_deg, "fov_source": first.fov_source,
        "valid_fraction": round(float(first.valid.mean()), 4),
        "coordinate_frame": first.coordinate_frame,
        "source_frame": first.source_frame,
        "notes": first.notes,
    })
    provider.unload()
    time.sleep(1.5)
    row["vram_after_unload_mib"] = gpu_used_mib()
    return row


def run_arm(provider, cases: list[dict], *, up_hint=None, label: str) -> dict:
    """Step 4 + Step 5 for one provider. Geometry first, then accuracy."""
    boxes_by_image: dict[str, list] = {}
    for case in cases:
        boxes_by_image.setdefault(case["image"], []).append(case["bbox"])

    provider.load()
    rooms: dict[str, tuple] = {}
    rows = []
    for case in cases:
        key = case["image"]
        if key not in rooms:
            started = time.perf_counter()
            result = provider.predict(ROOT / key)
            pointmap = result.as_pointmap()
            exclude = np.zeros((pointmap.height, pointmap.width), dtype=bool)
            for box in boxes_by_image[key]:
                exclude |= P.mask_from_box(pointmap.height, pointmap.width, box)
            room = P.fit_room(pointmap, exclude=exclude, up_hint=up_hint)
            rooms[key] = (pointmap, room, result,
                          round(time.perf_counter() - started, 2))
            print(f"    {key.split('/')[-1]:34} floor="
                  f"{bool(room.floor and room.floor.ok)} walls={len(room.walls)} "
                  f"usable={sum(1 for w in room.walls if not w.uncertain)} "
                  f"scale={room.scene_scale:.3f}", flush=True)
        pointmap, room, result, _ = rooms[key]

        mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
        contact = P.wall_contact(pointmap, room, mask)
        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)
        rows.append({
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"], "category": case["category"],
            "source_domain": case["source_domain"],
            "ground_truth_against_wall": case["truth"],
            "predicted_against_wall": predicted,
            "decision": contact.decision.value,
            "correct": (predicted == case["truth"]) if predicted is not None else None,
            "wall_distance": contact.distance,
            "relative_distance": contact.relative_distance,
            "wall_plane_confidence": contact.wall_confidence,
            "object_geometry_confidence": contact.object_geometric_confidence,
            "depth_coverage": contact.depth_coverage,
            "threshold_used": contact.threshold_used,
            "metric_source": contact.metric_source.value,
            "failure_reason": contact.failure_reason,
        })
    provider.unload()

    # ── Step 4 diagnostics, computed before anything else is read ───────
    manhattan = [w.manhattan_residual_deg for _, r, _, _ in rooms.values()
                 for w in r.walls if w.manhattan_residual_deg is not None]
    residuals = [w.residual_median for _, r, _, _ in rooms.values()
                 for w in r.walls if w.plane is not None]
    scales = [r.scene_scale for _, r, _, _ in rooms.values() if r.scene_scale > 0]
    usable = [sum(1 for w in r.walls if not w.uncertain) for _, r, _, _ in rooms.values()]
    extents = []
    for pm, _r, _res, _s in rooms.values():
        pts = pm.valid_points()
        if pts.shape[0] > 16:
            extents.append(np.percentile(pts, 95, axis=0) - np.percentile(pts, 5, axis=0))

    # For a metric arm the decision uses absolute metres, so score separation on
    # `wall_distance`; for an unscaled arm on the relative one.
    metric_arm = bool(rows) and rows[0]["metric_source"] == P.MetricSource.METRIC_MODEL.value
    field = "wall_distance" if metric_arm else "relative_distance"
    measured = [r for r in rows if r.get(field) is not None]
    pos_d = [r[field] for r in measured if r["ground_truth_against_wall"]]
    neg_d = [r[field] for r in measured if not r["ground_truth_against_wall"]]

    diagnostics = {
        "floor_fit_success":
            f"{sum(1 for _, r, _, _ in rooms.values() if r.floor and r.floor.ok)}"
            f"/{len(rooms)}",
        "images": len(rooms),
        "walls_fitted_total": sum(len(r.walls) for _, r, _, _ in rooms.values()),
        "walls_usable_total": int(sum(usable)),
        "images_with_zero_usable_walls": int(sum(1 for u in usable if u == 0)),
        "usable_walls_per_image_median": float(np.median(usable)) if usable else None,
        "manhattan_residual_deg": {
            "n": len(manhattan),
            "median": round(float(np.median(manhattan)), 2) if manhattan else None,
            "mean": round(float(np.mean(manhattan)), 2) if manhattan else None,
            "p90": round(float(np.percentile(manhattan, 90)), 2) if manhattan else None,
            "fraction_over_20deg": (round(float(np.mean(np.array(manhattan) > 20.0)), 3)
                                    if manhattan else None)},
        "wall_plane_residual_median": (round(float(np.median(residuals)), 5)
                                       if residuals else None),
        "scene_scale": {
            "min": round(min(scales), 3) if scales else None,
            "max": round(max(scales), 3) if scales else None,
            "spread_ratio": round(max(scales) / min(scales), 2) if scales else None,
            "median": round(float(np.median(scales)), 3) if scales else None},
        "point_extent_median_m": ([round(float(v), 3) for v in np.median(extents, axis=0)]
                                  if extents else None),
        "separation_auc": auc(pos_d, neg_d),
        "distance_field_scored": field,
        "positive_distance_median": round(float(np.median(pos_d)), 4) if pos_d else None,
        "negative_distance_median": round(float(np.median(neg_d)), 4) if neg_d else None,
    }

    metrics = {
        "all": summarise(rows),
        "generated": summarise([r for r in rows if r["source_domain"] == "generated"]),
        "historical": summarise([r for r in rows if r["source_domain"] == "historical"]),
        "category_A": summarise([r for r in rows if r["category"] == "A"]),
        "category_B": summarise([r for r in rows if r["category"] == "B"]),
    }
    per_scene = {s: summarise([r for r in rows if r["scene_id"] == s])
                 for s in sorted({r["scene_id"] for r in rows})}

    return {"label": label, "provider": provider.name, "version": provider.version,
            "up_hint": list(up_hint) if up_hint else None,
            "diagnostics": diagnostics, "metrics": metrics, "per_scene": per_scene,
            "per_case": rows,
            "failures": [r for r in rows if r["correct"] is False],
            "unknowns": [r for r in rows if r["predicted_against_wall"] is None]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-control", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    sample = ROOT / cases[0]["image"]

    print(f"cases {len(cases)}  negatives "
          f"{sum(1 for c in cases if not c['truth'])}  positives "
          f"{sum(1 for c in cases if c['truth'])}\n", flush=True)

    # ── Step 1: model benchmark ─────────────────────────────────────────
    print("== Step 1: model cost and output characteristics", flush=True)
    bench_rows = []
    for provider in (MoGe2Provider(), DepthAnythingRelativeProvider()):
        print(f"  {provider.name} ...", flush=True)
        row = benchmark_model(provider, sample)
        bench_rows.append(row)
        if row["status"] == "ok":
            print(f"    load {row['load_s']}s cold {row['cold_inference_s']}s "
                  f"warm {row['warm_median_s']}s peak "
                  f"{row['peak_vram_reserved_mib']} MiB metric={row['metric']} "
                  f"fov={row['fov_deg']} ({row['fov_source']}) "
                  f"determinism={row['determinism_max_abs_diff']}", flush=True)
        else:
            print(f"    {row['status']}: {row.get('blocker')}", flush=True)
    bench_rows.append({"name": "UniDepthV2", "status": "BLOCKED",
                       "blocker": LICENCES[1]["blocked"]})
    OUT_BENCH.write_text(json.dumps(
        {"_about": "Phase 2 Step 1. Models measured one at a time and unloaded "
                   "between runs. BLOCKED entries record the reason, never a guess.",
         "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram(),
                  "image": str(sample.relative_to(ROOT)).replace("\\", "/"),
                  "resolution": f"{WIDTH}x{HEIGHT}"},
         "licences": LICENCES, "models": bench_rows}, indent=2), encoding="utf-8")
    print(f"  wrote {OUT_BENCH}\n", flush=True)

    # ── Steps 4-6: arms ─────────────────────────────────────────────────
    arms = {}
    print("== Arm A: MoGe-2 metric point map (primary)", flush=True)
    arms["A_moge2_metric"] = run_arm(MoGe2Provider(), cases, label="MoGe-2 metric")

    print("\n== Arm B: MoGe-2 + camera up axis as floor orientation (ablation)",
          flush=True)
    arms["B_moge2_up_hint"] = run_arm(MoGe2Provider(), cases, up_hint=(0.0, 1.0, 0.0),
                                      label="MoGe-2 + known up")

    if not args.skip_control:
        print("\n== Control: Phase 1 relative depth, re-run in this harness",
              flush=True)
        arms["control_relative"] = run_arm(DepthAnythingRelativeProvider(), cases,
                                           label="DAv2-Small relative (Phase 1)")

    not_runnable = {
        "C_known_room_dimensions": "NOT RUN. No per-room measured dimensions exist "
                                   "for these 21 images: the Phase 1g scenes are "
                                   "generated from text prompts and the historical "
                                   "moodboards carry only a project brief, not room "
                                   "measurements.",
        "D_floorplan_fusion": "NOT RUN. No floor plan exists anywhere in the "
                              "repository - `find data -iname '*floorplan*'` returns "
                              "nothing. Floor-plan fusion cannot be evaluated until a "
                              "benchmark with plans exists.",
    }

    baselines = {}
    if PHASE_1H.is_file():
        b = json.loads(PHASE_1H.read_text(encoding="utf-8"))["results"]["negatives_all"]
        baselines["phase_1h_vlm_7b"] = {
            "false_wall_rate_pct": b["false_wall_rate"],
            "false_wall_ci95": b["false_wall_ci95"],
            "no_recall_pct": b["no_recall"], "unknown_rate_pct": 0.0}
    if PHASE_1.is_file():
        p1 = json.loads(PHASE_1.read_text(encoding="utf-8"))
        baselines["phase_1_relative_geometry"] = {
            "false_wall_rate_decided_pct":
                p1["metrics"]["all"]["false_wall_rate_decided_pct"],
            "false_wall_rate_all_pct": p1["metrics"]["all"]["false_wall_rate_all_pct"],
            "unknown_rate_negatives_pct":
                p1["metrics"]["all"]["unknown_rate_negatives_pct"],
            "separation_auc": p1["diagnosis"]["separation_auc"],
            "manhattan_note": "20-30 deg residuals dominated the rejections",
            "scene_scale_spread": "8.4x"}

    OUT_RESULTS.write_text(json.dumps(
        {"_about": "Phase 2. Same 48 cases, same labels, same geometry code; the "
                   "geometry MODEL is the controlled variable. Diagnostics are the "
                   "primary reading, accuracy second.",
         "dataset": {"cases": len(cases),
                     "negatives": sum(1 for c in cases if not c["truth"]),
                     "positives": sum(1 for c in cases if c["truth"]),
                     "images": len({c["image"] for c in cases}),
                     "sources": ["research/phase1g/dataset.json (unchanged)",
                                 "tests/fixtures/relationship_benchmark.json "
                                 "historical negatives (unchanged)"]},
         "licences": LICENCES, "arms": arms, "ablations_not_runnable": not_runnable,
         "baselines": baselines}, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    for key, arm in arms.items():
        d, m = arm["diagnostics"], arm["metrics"]["all"]
        print(f"  {key:22} manhattan_med="
              f"{d['manhattan_residual_deg']['median']}deg >20deg="
              f"{d['manhattan_residual_deg']['fraction_over_20deg']} scale_spread="
              f"{d['scene_scale']['spread_ratio']}x usable_walls="
              f"{d['walls_usable_total']} zero={d['images_with_zero_usable_walls']}")
        print(f"  {'':22} AUC={d['separation_auc']} false-wall(dec)="
              f"{m['false_wall_rate_decided_pct']}% {m['false_wall_ci95_decided']} "
              f"all={m['false_wall_rate_all_pct']}% unknown="
              f"{m['unknown_rate_negatives_pct']}% balacc={m['balanced_accuracy_pct']}%")
    for name, b in baselines.items():
        print(f"  baseline {name}: {b}")
    print(f"\n  wrote {OUT_RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

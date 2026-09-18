"""Spatial engine Phase 8: floor reconstruction as a scored hypothesis.

    python -u research/spatial_engine/floor_benchmark.py

Research only. Reads production modules read-only; nothing in `app/` imports this.

WHAT IS SCORED, AND AGAINST WHAT. There is no ground-truth floor plane in this
benchmark, so angular and offset error against truth are NOT TESTED and are said
to be. What can be measured honestly, per image:

    camera height above the chosen floor   plausible in [1.0, 2.0] m
    object contact                          floor-standing objects rest on it
    the two eye-verified countertop floors  s07 and the historical kitchen
    wall perpendicularity                   walls should be ~90 deg to it
    rank of the current fitter's plane      among the scored candidates
    UNKNOWN rate                            and why

AND THEN THE TEST THAT MATTERS. A corrected floor is pushed downstream: walls
are re-fitted against it with the frozen fitter's own wall loop, the Phase 6
gate and the Phase 7 extent method are run unchanged, and wall-contact precision
is read again. If the floor fix does not move Phase 7's floor-attributed
failures, the floor was not the problem.

Baseline (frozen): `fit_room`'s floor - largest horizontal RANSAC plane in the
lower 45% of the image - and Phase 7's primary result on it: 7/25/3/3, 10 UNKNOWN.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.floor_candidates import (                # noqa: E402
    FLOOR_CONFIG, generate_floor_candidates, refit_walls_with_floor, select_floor)
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    auc, gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.object_extent import (                   # noqa: E402
    extent_wall_contact, resolve_asset_metadata)
from research.spatial_engine.object_extent_benchmark import (         # noqa: E402
    PHASE6_PERMISSIVE, row_base)
from research.spatial_engine.rear_extent_benchmark import (           # noqa: E402
    build_geometry, with_f1)
from research.spatial_engine.segmentation_grounding import Sam2Grounder  # noqa: E402
from research.spatial_engine.wall_quality import (                    # noqa: E402
    extract_wall_features, gated_room)

OUT = HERE / "floor_results.json"
PHASE7_PRIMARY = {"tp": 7, "tn": 25, "fp": 3, "fn": 3, "unknown_total": 10}

#: Eye-verified in Phase 6: the fitted floor is the countertop.
COUNTERTOP_FLOORS = ["research/phase1g/scenes/s07_kitchen.png",
                     "data/projects/proj_553cb09794/analysis/moodboard_room_kitchen.png"]
KITCHENS = COUNTERTOP_FLOORS + ["research/phase1g/scenes/s06_kitchen.png",
                                "research/phase1g/scenes/s15_kitchen.png"]
PLAUSIBLE = FLOOR_CONFIG["camera_height_plausible_m"]


def cam_height(plane: P.Plane, up: np.ndarray) -> float:
    s = 1.0 if float(np.dot(plane.normal, up)) > 0 else -1.0
    return float(s * plane.signed_distance(np.zeros((1, 3)))[0])


def angle_deg(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    c = abs(float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    return math.degrees(math.acos(min(1.0, c)))


def contact_fraction(plane: P.Plane, up: np.ndarray, obj_pts: list) -> float:
    if not obj_pts:
        return float("nan")
    s = 1.0 if float(np.dot(plane.normal, up)) > 0 else -1.0
    lo, hi = FLOOR_CONFIG["contact_band_m"]
    hits = sum(int(lo <= float(np.percentile(s * plane.signed_distance(op), 5)) <= hi)
               for op in obj_pts)
    return hits / len(obj_pts)


def run_phase7_primary(cases: list, geometry: dict, rooms: dict, masks: dict,
                       exclude: dict, label: str) -> dict:
    """Phase 7's primary method, unchanged, on the supplied rooms."""
    rows = []
    for c in cases:
        pm = geometry[c["image"]][0]
        room = rooms[c["image"]]
        feats = extract_wall_features(pm, room, exclude[c["image"]]) if room.ok else []
        g, _ = gated_room(room, feats, PHASE6_PERMISSIVE) if room.ok else (room, {})
        q = {f.wall_index: f.enclosure_fraction for f in feats if f.enclosure_fraction is not None}
        mask = masks[c["case_id"]]
        if not mask.any():
            mask = P.mask_from_box(pm.height, pm.width, c["bbox"])
        ex = extent_wall_contact(c["case_id"], pm, g, mask, resolve_asset_metadata(c["object_type"]),
                                 wall_quality=q)
        pred = None if ex.decision is P.Decision.UNKNOWN else ex.decision is P.Decision.YES
        rows.append({**row_base(c), "predicted_against_wall": pred,
                     "decision": ex.decision.value,
                     "correct": (pred == c["truth"]) if pred is not None else None,
                     "wall_distance": ex.distance_m, "wall_index": ex.wall_index,
                     "failure_reason": ex.failure_reason})
    measured = [r for r in rows if r["wall_distance"] is not None]
    pos = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]
    m = with_f1(summarise(rows))
    m["unknown_total"] = sum(1 for r in rows if r["predicted_against_wall"] is None)
    m["accuracy_all_pct"] = round(100.0 * (m["tp"] + m["tn"]) / len(rows), 1)
    return {"label": label, "metrics": m, "separation_auc": auc(pos, neg), "per_case": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}\n", flush=True)

    grounder = Sam2Grounder()
    grounder.load()
    masks = {c["case_id"]: grounder.segment(ROOT / c["image"], c["bbox"]).mask for c in cases}
    grounder.unload()
    geometry, boxes_by_image = build_geometry(cases, masks)

    exclude, obj_by_image = {}, {}
    for key, (pm, _room) in geometry.items():
        ex = np.zeros((pm.height, pm.width), dtype=bool)
        for box in boxes_by_image[key]:
            ex |= P.mask_from_box(pm.height, pm.width, box)
        exclude[key] = ex
        obj_by_image[key] = [masks[c["case_id"]] for c in cases if c["image"] == key]

    per_image, corrected_rooms, conservative_rooms, timings = {}, {}, {}, []
    for key, (pm, room) in geometry.items():
        t = time.perf_counter()
        cands = generate_floor_candidates(pm, exclude[key], obj_by_image[key])
        hyp = select_floor(cands)
        timings.append(time.perf_counter() - t)

        up_b = np.asarray(room.up)
        base_plane = room.floor.plane
        base_h = cam_height(base_plane, up_b)
        obj_pts = [pm.points[m & pm.valid] for m in obj_by_image[key]
                   if int((m & pm.valid).sum()) >= 32]
        base_contact = contact_fraction(base_plane, up_b, obj_pts)

        ranked = sorted(cands, key=lambda c: c.score, reverse=True)
        base_rank, base_cat = None, None
        for pos_, c in enumerate(ranked, start=1):
            if (angle_deg(c.plane.normal, base_plane.normal) < 5.0
                    and abs(c.camera_height_m - base_h) < 0.15):
                base_rank, base_cat = pos_, c.category
                break

        entry = {"image": key, "kitchen": key in KITCHENS,
                 "eye_verified_countertop_floor": key in COUNTERTOP_FLOORS,
                 "baseline": {"camera_height_m": round(base_h, 3),
                              "plausible": PLAUSIBLE[0] <= base_h <= PLAUSIBLE[1],
                              "object_contact": (None if math.isnan(base_contact)
                                                 else round(base_contact, 3)),
                              "floor_inlier_fraction": round(room.floor.inlier_fraction, 3),
                              "rank_among_candidates": base_rank,
                              "candidate_category": base_cat},
                 "candidates": hyp.competing_candidates,
                 "selection": {"decision": hyp.decision, "score": hyp.score,
                               "confidence": hyp.confidence, "category": hyp.category,
                               "camera_height_m": hyp.camera_height_m,
                               "provenance": hyp.provenance, "warnings": hyp.warnings,
                               "same_as_baseline": None}}
        if hyp.decision == "ROOM_FLOOR" and hyp.plane is not None:
            sel = hyp.plane
            sel_up = np.asarray(sel.normal)
            cf = contact_fraction(sel, sel_up, obj_pts)
            same = (angle_deg(sel.normal, base_plane.normal) < 5.0
                    and abs(hyp.camera_height_m - base_h) < 0.15)
            entry["selection"].update({
                "plausible": PLAUSIBLE[0] <= hyp.camera_height_m <= PLAUSIBLE[1],
                "object_contact": None if math.isnan(cf) else round(cf, 3),
                "angle_to_baseline_deg": round(angle_deg(sel.normal, base_plane.normal), 2),
                "offset_to_baseline_m": round(abs(hyp.camera_height_m - base_h), 3),
                "same_as_baseline": same,
                "usable_wall_angle_to_floor_deg": [
                    round(angle_deg(w.plane.normal, sel.normal), 1) for w in room.walls
                    if w.plane is not None and not w.uncertain]})
            if not same:
                corrected_rooms[key] = refit_walls_with_floor(pm, exclude[key], sel)
                # DO-NO-HARM acceptance, declared before its downstream effect was
                # read: replace the fitter's floor only when that floor is itself
                # implausible (camera outside the soft range), or when the new
                # floor strictly wins on object contact. A tie keeps the baseline.
                slo_, shi_ = FLOOR_CONFIG["camera_height_soft_m"]
                base_bad = not (slo_ <= base_h <= shi_)
                new_c = entry["selection"]["object_contact"]
                old_c = entry["baseline"]["object_contact"]
                wins = (new_c is not None and old_c is not None and new_c > old_c)
                entry["selection"]["accepted_conservative"] = bool(base_bad or wins)
                if base_bad or wins:
                    conservative_rooms[key] = corrected_rooms[key]
        per_image[key] = entry

    # -- metrics --------------------------------------------------------
    imgs = list(per_image.values())
    sel_ok = [e for e in imgs if e["selection"]["decision"] == "ROOM_FLOOR"]
    unknown = [e["image"] for e in imgs if e["selection"]["decision"] != "ROOM_FLOOR"]
    countertop = {}
    for key in COUNTERTOP_FLOORS:
        e = per_image[key]
        s = e["selection"]
        rejected = s["decision"] == "UNKNOWN" or s.get("same_as_baseline") is False
        countertop[key] = {
            "baseline_camera_height_m": e["baseline"]["camera_height_m"],
            "decision": s["decision"], "selected_camera_height_m": s["camera_height_m"],
            "countertop_rejected": rejected,
            "fixed": (s["decision"] == "ROOM_FLOOR" and bool(s.get("plausible"))
                      and s.get("same_as_baseline") is False),
            "baseline_plane_category": e["baseline"]["candidate_category"]}
    rank_hist = {}
    for e in imgs:
        k = str(e["baseline"]["rank_among_candidates"])
        rank_hist[k] = rank_hist.get(k, 0) + 1
    wall_angles = [a for e in sel_ok for a in e["selection"]["usable_wall_angle_to_floor_deg"]]
    bc = [e["baseline"]["object_contact"] for e in imgs if e["baseline"]["object_contact"] is not None]
    sc = [e["selection"]["object_contact"] for e in sel_ok if e["selection"]["object_contact"] is not None]
    metrics = {
        "images": len(imgs),
        "floor_unknown": len(unknown), "floor_unknown_images": unknown,
        "baseline_camera_height_plausible": sum(1 for e in imgs if e["baseline"]["plausible"]),
        "selected_camera_height_plausible": sum(1 for e in sel_ok if e["selection"]["plausible"]),
        "selected_differs_from_baseline": sum(1 for e in sel_ok
                                              if e["selection"]["same_as_baseline"] is False),
        "baseline_object_contact_mean": round(float(np.mean(bc)), 3) if bc else None,
        "selected_object_contact_mean": round(float(np.mean(sc)), 3) if sc else None,
        "baseline_rank_histogram": rank_hist,
        "countertop_false_floor": countertop,
        "countertop_false_floor_rate_after": (
            sum(1 for v in countertop.values() if not v["countertop_rejected"]) / len(countertop)),
        "table_false_floor": "NOT TESTED: no table-as-floor case exists in the benchmark",
        "angular_error_vs_truth": "NOT TESTED: no ground-truth floor plane exists",
        "offset_error_vs_truth": "NOT TESTED: no ground-truth floor plane exists",
        "selected_wall_angle_to_floor_deg": {
            "n": len(wall_angles),
            "median": round(float(np.median(wall_angles)), 2) if wall_angles else None,
            "min": round(min(wall_angles), 2) if wall_angles else None,
            "max": round(max(wall_angles), 2) if wall_angles else None},
        "latency_ms_per_image_median": round(1000 * float(np.median(timings)), 1),
        "latency_ms_per_image_p95": round(1000 * float(np.percentile(timings, 95)), 1),
    }

    # -- downstream: Phase 7 primary with corrected floors ---------------
    rooms_base = {k: v[1] for k, v in geometry.items()}
    rooms_corr = {k: corrected_rooms.get(k, v[1]) for k, v in geometry.items()}
    rooms_cons = {k: conservative_rooms.get(k, v[1]) for k, v in geometry.items()}
    ds_base = run_phase7_primary(cases, geometry, rooms_base, masks, exclude,
                                 "Phase 7 primary, baseline floor (control)")
    ds_corr = run_phase7_primary(cases, geometry, rooms_corr, masks, exclude,
                                 "Phase 7 primary, corrected floor where selected")
    ds_cons = run_phase7_primary(cases, geometry, rooms_cons, masks, exclude,
                                 "Phase 7 primary, do-no-harm acceptance")
    mb = ds_base["metrics"]
    reproduced = all(mb[k] == v for k, v in PHASE7_PRIMARY.items())
    print(f"  Phase 7 primary reproduced on baseline floor: {reproduced}", flush=True)
    flips = []
    bb = {r["case_id"]: r for r in ds_base["per_case"]}
    for r in ds_corr["per_case"]:
        b = bb[r["case_id"]]
        if b["decision"] != r["decision"]:
            flips.append({"case_id": r["case_id"], "image": r["image_id"].split("/")[-1],
                          "label": r["ground_truth_against_wall"],
                          "before": f"{b['decision']} {b['wall_distance']}",
                          "after": f"{r['decision']} {r['wall_distance']}",
                          "correct_before": b["correct"], "correct_after": r["correct"]})

    payload = {
        "_about": "Phase 8. Floor as a scored hypothesis with UNKNOWN. No ground-truth "
                  "floor exists; proxies are camera-height plausibility, object contact, "
                  "the two eye-verified countertop floors, and wall perpendicularity. The "
                  "test that matters is downstream: Phase 7 re-run unchanged on the "
                  "corrected floor.",
        "config": {**FLOOR_CONFIG, "wall_gate": PHASE6_PERMISSIVE.__dict__,
                   "production_code_changed": "none"},
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "control_reproduction": {"phase7_primary_stored": PHASE7_PRIMARY,
                                 "measured": {k: mb[k] for k in PHASE7_PRIMARY},
                                 "reproduced": reproduced},
        "per_image": per_image,
        "metrics": metrics,
        "corrected_images": sorted(corrected_rooms),
        "conservative_accepted_images": sorted(conservative_rooms),
        "downstream_phase7": {"baseline_floor": {"metrics": mb,
                                                 "separation_auc": ds_base["separation_auc"]},
                              "corrected_floor": {"metrics": ds_corr["metrics"],
                                                  "separation_auc": ds_corr["separation_auc"]},
                              "conservative_floor": {"metrics": ds_cons["metrics"],
                                                     "separation_auc": ds_cons["separation_auc"]},
                              "decision_flips": flips},
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  floor UNKNOWN {metrics['floor_unknown']}/{metrics['images']}: "
          f"{[u.split('/')[-1] for u in unknown]}")
    print(f"  camera height plausible: baseline {metrics['baseline_camera_height_plausible']}/21 "
          f"-> selected {metrics['selected_camera_height_plausible']}/{len(sel_ok)}")
    print(f"  object contact mean: baseline {metrics['baseline_object_contact_mean']} "
          f"-> selected {metrics['selected_object_contact_mean']}")
    print(f"  selected differs from baseline: {metrics['selected_differs_from_baseline']}  "
          f"baseline rank histogram {rank_hist}")
    for k, v in countertop.items():
        print(f"  countertop {k.split('/')[-1]:34} base {v['baseline_camera_height_m']} m "
              f"-> {v['decision']} {v['selected_camera_height_m']} m  "
              f"rejected={v['countertop_rejected']} fixed={v['fixed']}")
    print(f"  do-no-harm accepted: {[k.split('/')[-1] for k in sorted(conservative_rooms)]}")
    for lab, d in (("baseline floor", ds_base), ("corrected floor", ds_corr),
                   ("do-no-harm floor", ds_cons)):
        m = d["metrics"]
        print(f"  Phase 7 on {lab:16} TP/TN/FP/FN={m['tp']}/{m['tn']}/{m['fp']}/{m['fn']} "
              f"unk={m['unknown_total']} fw={m['false_wall_rate_decided_pct']}% "
              f"posrec={m['positive_recall_decided_pct']}% prec={m['precision_pct']}% "
              f"balacc={m['balanced_accuracy_pct']}% AUC={d['separation_auc']}")
    for f in flips:
        print(f"    flip {f['case_id']:40} {f['image']:30} lab={f['label']!s:5} "
              f"{f['before']} -> {f['after']}  {f['correct_before']}->{f['correct_after']}")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

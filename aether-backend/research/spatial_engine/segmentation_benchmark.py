"""Spatial engine Phase 3: does SEGMENTATION repair the Phase 2 failure?

    python -u research/spatial_engine/segmentation_benchmark.py

Research only. No production module is imported except `app.spatial.planes`,
which is used exactly as Phase 2 used it and is not modified.

THE CONTROLLED VARIABLE IS THE OBJECT FOOTPRINT, AND NOTHING ELSE.

    variant A   footprint = the annotated bounding box      (Phase 2, re-run)
    variant B   footprint = a SAM 2 mask prompted by that box

Everything else is held: the same 48 cases, the same labels, the same MoGe-2
metric point map, the same RANSAC seed and iteration count, the same wall
fitting with the same box-based exclusion, the same 0.12 m threshold, the same
metric definitions. `load_cases`, `summarise` and `auc` are IMPORTED from the
Phase 2 harness rather than copied, so the dataset and the arithmetic are the
same code and cannot quietly drift.

Variant A is re-run rather than quoted. If it does not reproduce Phase 2's
false-wall 24.3% and AUC 0.7174, something else moved and the comparison is void,
so the script checks and says so.

VARIANT C (ground-truth masks) CANNOT RUN. The benchmark has boxes and
wall-contact labels; it has no hand-drawn masks. Inventing them would mean
drawing them myself against the same images whose answers I already know, which
is not ground truth, it is a second opinion with the answer key open. Recorded
as not runnable.

WHY SAM RUNS FIRST AND ALONE. 6 GB of VRAM. SAM segments all 48 cases, the masks
are kept in RAM (48 x 448 x 704 bool, about 15 MB), SAM is unloaded, and only
then does MoGe-2 load. Neither model ever competes with the other for the card.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.metric_geometry import MoGe2Provider     # noqa: E402
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    auc, gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.segmentation_grounding import (          # noqa: E402
    DEFAULT_CHECKPOINT, Sam2Grounder, is_open_structure)

OUT = HERE / "segmentation_benchmark.json"

#: SAM 2, from the primary source. Both the code and the checkpoints are
#: Apache-2.0, so commercial use is permitted, unlike UniDepthV2 which Phase 2
#: had to exclude on exactly this ground.
LICENCE = {
    "model": "SAM 2.1 Hiera base-plus", "checkpoint": DEFAULT_CHECKPOINT,
    "code_licence": "Apache-2.0", "checkpoint_licence": "Apache-2.0",
    "commercial_use": "PERMITTED",
    "implementation": "transformers.Sam2Model (already installed, 4.57.6). The "
                      "Meta sam2 pip package requires WSL and a compiled CUDA "
                      "kernel on Windows; it is NOT used and NOT installed, so "
                      "the torch 2.14.0+cu126 environment is unchanged.",
    "source": "https://github.com/facebookresearch/sam2 - 'The SAM 2 model "
              "checkpoints, SAM 2 demo code (front-end and back-end), and SAM 2 "
              "training code are licensed under Apache 2.0.'",
}

#: The nine Phase 2 false walls, taken from `metric_geometry_results.json` so each
#: can be tracked individually. Used for REPORTING, never for mask selection.
PHASE_2_FALSE_WALLS = [
    "s07.bar_stool.0", "s05.armchair.0", "s16.chair.0", "s02.ottoman.0",
    "s07.bar_stool.1", "s17.chair.0", "s09.chair.0", "s01.armchair.0",
    "s17.chair.2",
]
PHASE_2_HEADLINE = {"false_wall_rate_decided_pct": 24.3, "no_recall_decided_pct": 75.7,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7174}


def segment_all(cases: list, grounder: Sam2Grounder):
    """Step 3 + Step 4: one mask per case, plus the cost of getting them."""
    import torch

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    grounder.load()
    load_s = round(time.perf_counter() - started, 2)

    masks, records, timings = {}, [], []
    for case in cases:
        started = time.perf_counter()
        result = grounder.segment(ROOT / case["image"], case["bbox"])
        timings.append(time.perf_counter() - started)
        masks[case["case_id"]] = result.mask
        records.append({
            "case_id": case["case_id"], "object_type": case["object_type"],
            "open_structure": is_open_structure(case["object_type"]),
            "bbox_area_px": result.bbox_area, "mask_area_px": result.mask_area,
            "mask_over_bbox_area": result.area_ratio,
            "candidate_scores": result.scores,
            "candidate_areas_px": result.candidate_areas,
            "selected_index": result.selected_index,
            "selection_rule": result.selection_rule,
            "failure_reason": result.failure_reason,
        })
        print(f"    {case['case_id']:38} mask/bbox={result.area_ratio:.3f} "
              f"scores={result.scores}", flush=True)

    peak = round(torch.cuda.max_memory_reserved() / 1024**2)
    vram_loaded = gpu_used_mib()
    grounder.unload()
    time.sleep(1.5)

    warm = timings[1:] or timings
    cost = {"load_s": load_s,
            "cold_inference_s": round(timings[0], 3),
            "warm_median_s": round(float(np.median(warm)), 3),
            "warm_p95_s": round(float(np.percentile(warm, 95)), 3),
            "total_s": round(sum(timings), 1),
            "peak_vram_reserved_mib": peak,
            "vram_used_while_loaded_mib": vram_loaded,
            "vram_after_unload_mib": gpu_used_mib(),
            "cases": len(timings),
            "failures": sum(1 for r in records if r["failure_reason"])}
    return masks, {"cost": cost, "per_case": records}


def mask_quality(records: list) -> dict:
    """Step 4, WITHOUT ground-truth masks, so area statistics rather than IoU.

    There are no GT masks in this benchmark. Rather than invent them, this reports
    what can be measured honestly: how much of each box the mask actually fills,
    split by whether the object is open-structure. If the hypothesis is right,
    open-structure objects fill much less of their box than solid ones do.
    """
    def stats(rows: list) -> dict:
        vals = [r["mask_over_bbox_area"] for r in rows if not r["failure_reason"]]
        if not vals:
            return {"n": 0}
        return {"n": len(vals),
                "median": round(float(np.median(vals)), 4),
                "mean": round(float(np.mean(vals)), 4),
                "p25": round(float(np.percentile(vals, 25)), 4),
                "p75": round(float(np.percentile(vals, 75)), 4),
                "min": round(float(min(vals)), 4), "max": round(float(max(vals)), 4)}

    ok = [r for r in records if not r["failure_reason"]]
    return {
        "note": "No ground-truth masks exist in this benchmark, so IoU against GT "
                "cannot be computed and was NOT invented. Reported instead: the "
                "fraction of each annotated box that the mask fills.",
        "all": stats(records),
        "open_structure": stats([r for r in records if r["open_structure"]]),
        "solid": stats([r for r in records if not r["open_structure"]]),
        "degenerate_masks_under_5pct_of_box":
            [r["case_id"] for r in ok if r["mask_over_bbox_area"] < 0.05],
        "near_full_box_masks_over_95pct":
            [r["case_id"] for r in ok if r["mask_over_bbox_area"] > 0.95],
        "candidate_score_spread_median": (round(float(np.median(
            [max(r["candidate_scores"]) - min(r["candidate_scores"])
             for r in ok if r["candidate_scores"]])), 4) if ok else None),
        "selected_index_counts": {str(i): sum(1 for r in ok if r["selected_index"] == i)
                                  for i in (0, 1, 2)},
    }


def run_variant(cases: list, *, masks, label: str) -> dict:
    """Wall contact for one footprint definition. Identical but for the footprint.

    `masks=None` is variant A: the footprint is the box, exactly as Phase 2.
    """
    boxes_by_image: dict = {}
    for case in cases:
        boxes_by_image.setdefault(case["image"], []).append(case["bbox"])

    provider = MoGe2Provider()
    provider.load()
    rooms: dict = {}
    rows = []
    for case in cases:
        key = case["image"]
        if key not in rooms:
            result = provider.predict(ROOT / key)
            pointmap = result.as_pointmap()
            # Wall fitting still excludes the BOXES, in both variants. Changing
            # the exclusion as well would be a second variable.
            exclude = np.zeros((pointmap.height, pointmap.width), dtype=bool)
            for box in boxes_by_image[key]:
                exclude |= P.mask_from_box(pointmap.height, pointmap.width, box)
            rooms[key] = (pointmap, P.fit_room(pointmap, exclude=exclude))
            print(f"    {key.split('/')[-1]:34} walls={len(rooms[key][1].walls)} "
                  f"usable={sum(1 for w in rooms[key][1].walls if not w.uncertain)}",
                  flush=True)
        pointmap, room = rooms[key]

        box_mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
        footprint = box_mask if masks is None else masks[case["case_id"]]
        empty = not bool(footprint.any())
        if empty:                       # a failed mask is recorded, not repaired
            footprint = box_mask

        contact = P.wall_contact(pointmap, room, footprint)
        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)
        rows.append({
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"], "category": case["category"],
            "source_domain": case["source_domain"],
            "open_structure": is_open_structure(case["object_type"]),
            "ground_truth_against_wall": case["truth"],
            "predicted_against_wall": predicted,
            "decision": contact.decision.value,
            "correct": (predicted == case["truth"]) if predicted is not None else None,
            "wall_distance": contact.distance,
            "relative_distance": contact.relative_distance,
            "object_geometry_confidence": contact.object_geometric_confidence,
            "depth_coverage": contact.depth_coverage,
            "footprint_px": int(footprint.sum()),
            "fell_back_to_bbox": empty,
            "failure_reason": contact.failure_reason,
        })
    provider.unload()

    measured = [r for r in rows if r["wall_distance"] is not None]
    pos_d = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg_d = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]

    def dist(vals: list) -> dict:
        if not vals:
            return {"n": 0}
        return {"n": len(vals), "median": round(float(np.median(vals)), 4),
                "p25": round(float(np.percentile(vals, 25)), 4),
                "p75": round(float(np.percentile(vals, 75)), 4),
                "min": round(float(min(vals)), 4), "max": round(float(max(vals)), 4)}

    return {
        "label": label,
        "metrics": {
            "all": summarise(rows),
            "generated": summarise([r for r in rows
                                    if r["source_domain"] == "generated"]),
            "historical": summarise([r for r in rows
                                     if r["source_domain"] == "historical"]),
            "category_A": summarise([r for r in rows if r["category"] == "A"]),
            "category_B": summarise([r for r in rows if r["category"] == "B"]),
            "open_structure": summarise([r for r in rows if r["open_structure"]]),
            "solid": summarise([r for r in rows if not r["open_structure"]]),
        },
        "per_scene": {s: summarise([r for r in rows if r["scene_id"] == s])
                      for s in sorted({r["scene_id"] for r in rows})},
        "separation_auc": auc(pos_d, neg_d),
        "distance_distribution": {"positives": dist(pos_d), "negatives": dist(neg_d)},
        "per_case": rows,
        "failures": [r for r in rows if r["correct"] is False],
        "unknowns": [r for r in rows if r["predicted_against_wall"] is None],
    }


def threshold_sweep(variant: dict) -> list:
    """Step 9, DIAGNOSTIC ONLY. Nothing here is written back to production.

    It answers one question: is the remaining error a thresholding problem or a
    signal problem? If no threshold gives a usable operating point, then tuning
    the shipped 0.12 m would not have helped either.
    """
    rows = [r for r in variant["per_case"] if r["wall_distance"] is not None]
    out = []
    for thr in (0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        tn = fp = tp = fn = 0
        for r in rows:
            near = r["wall_distance"] <= thr
            if r["ground_truth_against_wall"]:
                tp, fn = (tp + 1, fn) if near else (tp, fn + 1)
            else:
                fp, tn = (fp + 1, tn) if near else (fp, tn + 1)
        out.append({
            "threshold_m": thr,
            "false_wall_rate_pct": round(100.0 * fp / (fp + tn), 1) if fp + tn else None,
            "no_recall_pct": round(100.0 * tn / (fp + tn), 1) if fp + tn else None,
            "positive_recall_pct": round(100.0 * tp / (tp + fn), 1) if tp + fn else None,
            "balanced_accuracy_pct": (round(50.0 * (tn / (tn + fp) + tp / (tp + fn)), 1)
                                      if (tn + fp) and (tp + fn) else None)})
    return out


def nine_case_table(variant_a: dict, variant_b: dict, seg: dict) -> dict:
    """Step 7, mandatory. Each Phase 2 false wall, followed individually."""
    a = {r["case_id"]: r for r in variant_a["per_case"]}
    b = {r["case_id"]: r for r in variant_b["per_case"]}
    s = {r["case_id"]: r for r in seg["per_case"]}
    rows = []
    for case_id in PHASE_2_FALSE_WALLS:
        ra, rb, rs = a.get(case_id), b.get(case_id), s.get(case_id)
        if ra is None or rb is None:
            rows.append({"case_id": case_id, "status": "NOT IN THIS RUN"})
            continue
        changed = None
        if ra["wall_distance"] is not None and rb["wall_distance"] is not None:
            changed = round(rb["wall_distance"] - ra["wall_distance"], 4)
        rows.append({
            "case_id": case_id, "object_type": ra["object_type"],
            "category": ra["category"],
            "bbox_distance_m": ra["wall_distance"],
            "mask_distance_m": rb["wall_distance"],
            "distance_change_m": changed,
            "bbox_decision": ra["decision"], "mask_decision": rb["decision"],
            "bbox_correct": ra["correct"], "mask_correct": rb["correct"],
            "repaired": bool(ra["correct"] is False and rb["correct"] is True),
            "mask_over_bbox_area": rs["mask_over_bbox_area"] if rs else None,
            "footprint_px_bbox": ra["footprint_px"],
            "footprint_px_mask": rb["footprint_px"],
        })
    done = [r for r in rows if r.get("status") != "NOT IN THIS RUN"]
    return {"cases": rows,
            "repaired": sum(1 for r in done if r["repaired"]),
            "still_wrong": sum(1 for r in done if r["mask_correct"] is False),
            "became_unknown": sum(1 for r in done if r["mask_decision"] == "unknown")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}  negatives {sum(1 for c in cases if not c['truth'])}  "
          f"positives {sum(1 for c in cases if c['truth'])}\n", flush=True)

    print("== Step 3-4: SAM 2 segmentation (SAM alone on the GPU)", flush=True)
    masks, seg = segment_all(cases, Sam2Grounder())
    seg["quality"] = mask_quality(seg["per_case"])
    print(f"  cost {seg['cost']}\n", flush=True)

    print("== Variant A: bounding-box footprint (Phase 2, re-run)", flush=True)
    variant_a = run_variant(cases, masks=None, label="bbox footprint (Phase 2)")

    print("\n== Variant B: SAM 2 mask footprint", flush=True)
    variant_b = run_variant(cases, masks=masks, label="SAM 2 mask footprint")

    ma, mb = variant_a["metrics"]["all"], variant_b["metrics"]["all"]
    reproduced = bool(ma["false_wall_rate_decided_pct"]
                      == PHASE_2_HEADLINE["false_wall_rate_decided_pct"]
                      and variant_a["separation_auc"]
                      == PHASE_2_HEADLINE["separation_auc"])

    payload = {
        "_about": "Phase 3. The ONLY change between variants is the object "
                  "footprint: annotated bounding box vs SAM 2 mask. Same 48 cases, "
                  "same labels, same MoGe-2 geometry, same thresholds, same metric "
                  "code (imported from the Phase 2 harness, not copied).",
        "licence": LICENCE,
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "dataset": {"cases": len(cases),
                    "negatives": sum(1 for c in cases if not c["truth"]),
                    "positives": sum(1 for c in cases if c["truth"]),
                    "images": len({c["image"] for c in cases})},
        "segmentation": seg,
        "variant_A_bbox": variant_a,
        "variant_B_sam_mask": variant_b,
        "variant_C_ground_truth_masks": {
            "status": "NOT RUNNABLE",
            "reason": "The benchmark carries bounding boxes and wall-contact "
                      "labels; it carries no ground-truth segmentation masks. "
                      "Drawing them now would mean annotating the same images "
                      "whose answers are already known, which is not ground "
                      "truth. Not invented, not estimated."},
        "phase_2_reproduction_check": {
            "phase_2": PHASE_2_HEADLINE,
            "variant_A_measured": {
                "false_wall_rate_decided_pct": ma["false_wall_rate_decided_pct"],
                "no_recall_decided_pct": ma["no_recall_decided_pct"],
                "unknown_rate_negatives_pct": ma["unknown_rate_negatives_pct"],
                "separation_auc": variant_a["separation_auc"]},
            "reproduced_exactly": reproduced,
            "note": "Variant A must reproduce Phase 2. If it does not, the "
                    "controlled comparison is void and the result is not usable."},
        "nine_phase_2_false_walls": nine_case_table(variant_a, variant_b, seg),
        "threshold_sweep_diagnostic": {
            "note": "DIAGNOSTIC ONLY. The production threshold is unchanged at "
                    f"{P.WALL_CONTACT_DISTANCE_M} m. This asks whether any "
                    "threshold would have worked, not which one to ship.",
            "bbox": threshold_sweep(variant_a),
            "sam_mask": threshold_sweep(variant_b)},
        "comparison": {
            "order": "[variant A bbox, variant B SAM mask]",
            "false_wall_rate_decided_pct": [ma["false_wall_rate_decided_pct"],
                                            mb["false_wall_rate_decided_pct"]],
            "false_wall_ci95": [ma["false_wall_ci95_decided"],
                                mb["false_wall_ci95_decided"]],
            "no_recall_decided_pct": [ma["no_recall_decided_pct"],
                                      mb["no_recall_decided_pct"]],
            "positive_recall_decided_pct": [ma["positive_recall_decided_pct"],
                                            mb["positive_recall_decided_pct"]],
            "balanced_accuracy_pct": [ma["balanced_accuracy_pct"],
                                      mb["balanced_accuracy_pct"]],
            "unknown_rate_negatives_pct": [ma["unknown_rate_negatives_pct"],
                                           mb["unknown_rate_negatives_pct"]],
            "separation_auc": [variant_a["separation_auc"],
                               variant_b["separation_auc"]]},
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  Phase 2 reproduced by variant A: {reproduced}")
    for name, m, v in (("A bbox", ma, variant_a), ("B mask", mb, variant_b)):
        print(f"  {name:8} false-wall={m['false_wall_rate_decided_pct']}% "
              f"{m['false_wall_ci95_decided']} NO-recall={m['no_recall_decided_pct']}% "
              f"pos-recall={m['positive_recall_decided_pct']}% "
              f"balacc={m['balanced_accuracy_pct']}% AUC={v['separation_auc']} "
              f"unknown={m['unknown_rate_negatives_pct']}%")
    nine = payload["nine_phase_2_false_walls"]
    print(f"  nine Phase 2 false walls: repaired={nine['repaired']} "
          f"still_wrong={nine['still_wrong']} unknown={nine['became_unknown']}")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

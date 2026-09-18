"""Spatial engine Phase 4: does REAR EXTENT beat NEAREST VISIBLE SURFACE?

    python -u research/spatial_engine/rear_extent_benchmark.py

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

THE CONTROLLED VARIABLE IS THE MEASURED QUANTITY, AND NOTHING ELSE.

    A  bbox      + nearest visible surface     Phase 2 baseline
    B  SAM mask  + nearest visible surface     Phase 3 baseline (the control)
    C  SAM mask  + rear extent                 THE PHASE 4 ARM
    D  bbox      + rear extent                 diagnostic only, never a candidate

A and B together reproduce the two earlier phases. C is the experiment. D exists
so the segmentation effect and the rear-extent effect can be separated rather
than confounded: C vs B isolates the statistic, D vs A isolates it again under
the old grounding, and C vs D isolates segmentation under the new statistic.

WHY ALL FOUR SHARE ONE GEOMETRY PASS. MoGe-2 runs ONCE per image and the room is
fitted ONCE; all four variants then read the same point map and the same wall
planes. Phase 3 ran MoGe separately per variant and relied on the model being
deterministic to keep them comparable. Computing the geometry once removes even
that assumption: the walls are not merely equal across variants, they are the
same objects.

THE PHASE 3 BASELINE IS A GATE, NOT A COURTESY. Variants A and B are compared
against the stored Phase 3 JSON. If they do not reproduce it, the control arm is
broken, the comparison is meaningless, and the run reports that instead of a
result.
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
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    MIN_ORIENTATION_MARGIN_FRACTION, REAR_EXTENT_PERCENTILE,
    rear_extent_wall_contact)
from research.spatial_engine.segmentation_grounding import (          # noqa: E402
    Sam2Grounder, is_open_structure)

OUT = HERE / "rear_extent_benchmark.json"
PHASE_3 = HERE / "segmentation_benchmark.json"

#: The nine Phase 2 false walls. The four errors Phase 3 newly created are
#: recomputed at runtime rather than hard-coded. Used for REPORTING only.
PHASE_2_FALSE_WALLS = [
    "s07.bar_stool.0", "s05.armchair.0", "s16.chair.0", "s02.ottoman.0",
    "s07.bar_stool.1", "s17.chair.0", "s09.chair.0", "s01.armchair.0",
    "s17.chair.2",
]
PHASE_3_HEADLINE = {"false_wall_rate_decided_pct": 21.6, "no_recall_decided_pct": 78.4,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7445}
PHASE_2_HEADLINE = {"false_wall_rate_decided_pct": 24.3, "no_recall_decided_pct": 75.7,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7174}

VARIANTS = [
    ("A_bbox_nearest", "bbox + nearest visible surface (Phase 2)", "bbox", "nearest"),
    ("B_sam_nearest", "SAM mask + nearest visible surface (Phase 3)", "mask", "nearest"),
    ("C_sam_rear", "SAM mask + rear extent (PHASE 4)", "mask", "rear"),
    ("D_bbox_rear", "bbox + rear extent (diagnostic)", "bbox", "rear"),
]


def object_bucket(object_type: str) -> str:
    """Coarse object families for the per-type breakdown."""
    t = (object_type or "").strip().lower()
    if "armchair" in t:
        return "armchair"
    if "stool" in t:
        return "bar stool"
    if "chair" in t:
        return "chair"
    if "ottoman" in t:
        return "ottoman"
    if "sofa" in t or "couch" in t:
        return "sofa"
    if "table" in t or "desk" in t:
        return "table"
    if any(k in t for k in ("counter", "cabinet", "vanity", "unit", "sideboard",
                            "dresser", "wardrobe", "island")):
        return "cabinet"
    return "other"


def with_f1(metrics: dict) -> dict:
    """`summarise` from the Phase 2 harness, plus F1. The harness is untouched."""
    tp, fp, fn = metrics["tp"], metrics["fp"], metrics["fn"]
    metrics = dict(metrics)
    denom = 2 * tp + fp + fn
    metrics["f1_pct"] = round(100.0 * 2 * tp / denom, 1) if denom else None
    return metrics


def distribution(values: list) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": round(float(np.median(values)), 4),
            "p25": round(float(np.percentile(values, 25)), 4),
            "p75": round(float(np.percentile(values, 75)), 4),
            "min": round(float(min(values)), 4), "max": round(float(max(values)), 4)}


def build_geometry(cases: list, masks: dict) -> tuple:
    """One MoGe-2 pass and one room fit per image, shared by every variant."""
    boxes_by_image: dict = {}
    for case in cases:
        boxes_by_image.setdefault(case["image"], []).append(case["bbox"])

    provider = MoGe2Provider()
    provider.load()
    geometry: dict = {}
    for key in dict.fromkeys(c["image"] for c in cases):
        result = provider.predict(ROOT / key)
        pointmap = result.as_pointmap()
        # Wall fitting excludes the annotated BOXES, exactly as Phases 2 and 3
        # did. Changing it to masks would be a second variable.
        exclude = np.zeros((pointmap.height, pointmap.width), dtype=bool)
        for box in boxes_by_image[key]:
            exclude |= P.mask_from_box(pointmap.height, pointmap.width, box)
        room = P.fit_room(pointmap, exclude=exclude)
        geometry[key] = (pointmap, room)
        print(f"    {key.split('/')[-1]:34} walls={len(room.walls)} "
              f"usable={sum(1 for w in room.walls if not w.uncertain)} "
              f"scale={room.scene_scale:.2f}", flush=True)
    provider.unload()
    return geometry, boxes_by_image


def run_variant(cases: list, geometry: dict, masks: dict, *,
                footprint: str, statistic: str, key: str, label: str) -> dict:
    """One (grounding, statistic) pair over all 48 cases."""
    rows = []
    for case in cases:
        pointmap, room = geometry[case["image"]]
        box_mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
        mask = box_mask if footprint == "bbox" else masks[case["case_id"]]
        if not mask.any():                    # recorded, never silently repaired
            mask = box_mask

        row = {
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"],
            "object_bucket": object_bucket(case["object_type"]),
            "category": case["category"], "source_domain": case["source_domain"],
            "open_structure": is_open_structure(case["object_type"]),
            "ground_truth_against_wall": case["truth"],
            "footprint_px": int(mask.sum()),
        }

        if statistic == "nearest":
            contact = P.wall_contact(pointmap, room, mask)
            row.update(wall_distance=contact.distance, wall_index=contact.wall_index,
                       rear_extent=None, nearest_surface=contact.distance,
                       projection_min=None, projection_max=None,
                       orientation_source=None, orientation_margin=None,
                       valid_point_count=None)
        else:
            contact = rear_extent_wall_contact(pointmap, room, mask)
            row.update(wall_distance=contact.distance, wall_index=contact.wall_index,
                       rear_extent=contact.rear_extent,
                       nearest_surface=contact.nearest_surface,
                       projection_min=contact.projection_min,
                       projection_max=contact.projection_max,
                       orientation_source=contact.orientation_source,
                       orientation_margin=contact.orientation_margin,
                       valid_point_count=contact.valid_point_count)

        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)
        row.update(
            predicted_against_wall=predicted, decision=contact.decision.value,
            correct=(predicted == case["truth"]) if predicted is not None else None,
            relative_distance=contact.relative_distance,
            wall_confidence=contact.wall_confidence,
            depth_coverage=contact.depth_coverage,
            threshold_used=contact.threshold_used,
            failure_reason=contact.failure_reason)
        rows.append(row)

    measured = [r for r in rows if r["wall_distance"] is not None]
    pos = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]

    by_bucket = {}
    for bucket in sorted({r["object_bucket"] for r in rows}):
        subset = [r for r in rows if r["object_bucket"] == bucket]
        by_bucket[bucket] = with_f1(summarise(subset))
        by_bucket[bucket]["median_distance"] = distribution(
            [r["wall_distance"] for r in subset if r["wall_distance"] is not None]
        ).get("median")

    return {
        "key": key, "label": label, "footprint": footprint, "statistic": statistic,
        "metrics": {
            "all": with_f1(summarise(rows)),
            "generated": with_f1(summarise([r for r in rows
                                            if r["source_domain"] == "generated"])),
            "historical": with_f1(summarise([r for r in rows
                                             if r["source_domain"] == "historical"])),
            "category_A": with_f1(summarise([r for r in rows
                                             if r["category"] == "A"])),
            "category_B": with_f1(summarise([r for r in rows
                                             if r["category"] == "B"])),
            "open_structure": with_f1(summarise([r for r in rows
                                                 if r["open_structure"]])),
            "solid": with_f1(summarise([r for r in rows if not r["open_structure"]])),
        },
        "by_object_type": by_bucket,
        "separation_auc": auc(pos, neg),
        "distance_distribution": {"positives": distribution(pos),
                                  "negatives": distribution(neg)},
        "per_case": rows,
        "failures": [r for r in rows if r["correct"] is False],
        "unknowns": [r for r in rows if r["predicted_against_wall"] is None],
    }


def threshold_sweep(variant: dict) -> list:
    """The same sweep methodology as Phases 2 and 3. Diagnostic only."""
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


def percentile_sensitivity(cases: list, geometry: dict, masks: dict) -> list:
    """How much does the frozen percentile matter? DIAGNOSTIC ONLY.

    Declared before the run and reported whatever it says. The gate is decided on
    REAR_EXTENT_PERCENTILE = 10; this exists so the next phase knows whether the
    statistic's tail behaviour is a lever or a detail, not to pick a winner.
    """
    out = []
    for pct in (1.0, 2.0, 5.0, 10.0, 25.0):
        rows = []
        for case in cases:
            pointmap, room = geometry[case["image"]]
            mask = masks[case["case_id"]]
            if not mask.any():
                mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
            contact = rear_extent_wall_contact(pointmap, room, mask, percentile=pct)
            predicted = (None if contact.decision is P.Decision.UNKNOWN
                         else contact.decision is P.Decision.YES)
            rows.append({"ground_truth_against_wall": case["truth"],
                         "predicted_against_wall": predicted,
                         "wall_distance": contact.distance})
        m = summarise(rows)
        out.append({"percentile": pct, "frozen": pct == REAR_EXTENT_PERCENTILE,
                    "false_wall_rate_decided_pct": m["false_wall_rate_decided_pct"],
                    "no_recall_decided_pct": m["no_recall_decided_pct"],
                    "positive_recall_decided_pct": m["positive_recall_decided_pct"],
                    "balanced_accuracy_pct": m["balanced_accuracy_pct"],
                    "unknown_rate_negatives_pct": m["unknown_rate_negatives_pct"]})
    return out


def geometry_diagnostics(variant: dict, geometry: dict, cases: list) -> list:
    """Everything needed to debug the result if it disappoints."""
    by_id = {c["case_id"]: c for c in cases}
    rows = []
    for r in variant["per_case"]:
        case = by_id[r["case_id"]]
        pointmap, room = geometry[case["image"]]
        x1, y1, x2, y2 = case["bbox"]
        bbox_area = int(max(0.0, x2 - x1) * max(0.0, y2 - y1))
        wall = (room.walls[r["wall_index"]] if r["wall_index"] is not None
                and r["wall_index"] < len(room.walls) else None)
        rows.append({
            "case_id": r["case_id"], "object_type": r["object_type"],
            "wall_index": r["wall_index"],
            "wall_normal": (list(wall.plane.normal) if wall and wall.plane else None),
            "wall_plane_offset": (round(float(wall.plane.offset), 5)
                                  if wall and wall.plane else None),
            "object_projection_min": r["projection_min"],
            "object_projection_max": r["projection_max"],
            "rear_extent": r["rear_extent"], "nearest_surface": r["nearest_surface"],
            "wall_distance": r["wall_distance"],
            "valid_point_count": r["valid_point_count"],
            "mask_area": r["footprint_px"], "bbox_area": bbox_area,
            "mask_bbox_ratio": (round(r["footprint_px"] / bbox_area, 4)
                                if bbox_area else None),
            "orientation_source": r["orientation_source"],
            "orientation_margin": r["orientation_margin"],
            "depth_coverage": r["depth_coverage"],
        })
    return rows


def compare_runs(first: dict, second: dict, masks_a: dict, masks_b: dict,
                 geom_a: dict, geom_b: dict) -> dict:
    """Is the whole pipeline deterministic, and if not, where does it enter?"""
    mask_disagree = [k for k in masks_a
                     if not np.array_equal(masks_a[k], masks_b[k])]

    wall_diff = 0.0
    for key in geom_a:
        walls_a, walls_b = geom_a[key][1].walls, geom_b[key][1].walls
        if len(walls_a) != len(walls_b):
            wall_diff = float("inf")
            break
        for wa, wb in zip(walls_a, walls_b):
            if wa.plane is None or wb.plane is None:
                continue
            wall_diff = max(wall_diff,
                            float(np.abs(np.array(wa.plane.normal)
                                         - np.array(wb.plane.normal)).max()),
                            abs(float(wa.plane.offset) - float(wb.plane.offset)))

    rows_a = {r["case_id"]: r for r in first["per_case"]}
    rows_b = {r["case_id"]: r for r in second["per_case"]}
    rear_diff = 0.0
    decision_disagree = []
    for case_id, ra in rows_a.items():
        rb = rows_b[case_id]
        if ra["rear_extent"] is not None and rb["rear_extent"] is not None:
            rear_diff = max(rear_diff, abs(ra["rear_extent"] - rb["rear_extent"]))
        if ra["decision"] != rb["decision"]:
            decision_disagree.append(case_id)

    return {
        "mask_pixel_disagreements": len(mask_disagree),
        "mask_disagreement_cases": mask_disagree,
        "wall_plane_max_abs_diff": wall_diff,
        "rear_extent_max_abs_diff": rear_diff,
        "decision_disagreements": len(decision_disagree),
        "decision_disagreement_cases": decision_disagree,
        "deterministic": bool(not mask_disagree and wall_diff == 0.0
                              and rear_diff == 0.0 and not decision_disagree),
    }


def one_pass(cases: list, *, quiet: bool = False) -> tuple:
    """SAM, then geometry, then all four variants. Returns everything."""
    grounder = Sam2Grounder()
    grounder.load()
    masks, mask_meta = {}, {}
    started = time.perf_counter()
    for case in cases:
        result = grounder.segment(ROOT / case["image"], case["bbox"])
        masks[case["case_id"]] = result.mask
        mask_meta[case["case_id"]] = {
            "mask_area_px": result.mask_area, "bbox_area_px": result.bbox_area,
            "mask_over_bbox_area": result.area_ratio,
            "selected_index": result.selected_index, "scores": result.scores,
            "failure_reason": result.failure_reason}
    sam_s = round(time.perf_counter() - started, 1)
    grounder.unload()
    if not quiet:
        print(f"  SAM: {len(masks)} masks in {sam_s}s "
              f"({sum(1 for m in mask_meta.values() if m['failure_reason'])} failures)",
              flush=True)

    geometry, _ = build_geometry(cases, masks)

    variants = {}
    for key, label, footprint, statistic in VARIANTS:
        variants[key] = run_variant(cases, geometry, masks, footprint=footprint,
                                    statistic=statistic, key=key, label=label)
        m = variants[key]["metrics"]["all"]
        if not quiet:
            print(f"  {key:16} false-wall={m['false_wall_rate_decided_pct']}% "
                  f"pos-recall={m['positive_recall_decided_pct']}% "
                  f"balacc={m['balanced_accuracy_pct']}% "
                  f"AUC={variants[key]['separation_auc']} "
                  f"unknown={m['unknown_rate_negatives_pct']}%", flush=True)
    return masks, mask_meta, geometry, variants


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-repeat", action="store_true",
                        help="skip the stability pass")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}  negatives {sum(1 for c in cases if not c['truth'])}  "
          f"positives {sum(1 for c in cases if c['truth'])}\n", flush=True)

    print("== Pass 1", flush=True)
    masks, mask_meta, geometry, variants = one_pass(cases)

    # -- the Phase 2/3 baselines are the control arm ----------------------
    stored = json.loads(PHASE_3.read_text(encoding="utf-8")) if PHASE_3.is_file() else {}
    a, b = variants["A_bbox_nearest"], variants["B_sam_nearest"]
    reproduction = {
        "phase_2_stored": PHASE_2_HEADLINE,
        "phase_3_stored": PHASE_3_HEADLINE,
        "variant_A_measured": {
            "false_wall_rate_decided_pct":
                a["metrics"]["all"]["false_wall_rate_decided_pct"],
            "no_recall_decided_pct": a["metrics"]["all"]["no_recall_decided_pct"],
            "unknown_rate_negatives_pct":
                a["metrics"]["all"]["unknown_rate_negatives_pct"],
            "separation_auc": a["separation_auc"]},
        "variant_B_measured": {
            "false_wall_rate_decided_pct":
                b["metrics"]["all"]["false_wall_rate_decided_pct"],
            "no_recall_decided_pct": b["metrics"]["all"]["no_recall_decided_pct"],
            "unknown_rate_negatives_pct":
                b["metrics"]["all"]["unknown_rate_negatives_pct"],
            "separation_auc": b["separation_auc"]},
    }
    reproduction["phase_2_reproduced"] = (
        reproduction["variant_A_measured"] == PHASE_2_HEADLINE)
    reproduction["phase_3_reproduced"] = (
        reproduction["variant_B_measured"] == PHASE_3_HEADLINE)
    if stored:
        prev = {r["case_id"]: r for r in stored["variant_B_sam_mask"]["per_case"]}
        reproduction["per_case_decision_drift_vs_stored_phase_3"] = [
            r["case_id"] for r in b["per_case"]
            if r["case_id"] in prev and r["decision"] != prev[r["case_id"]]["decision"]]
    print(f"\n  Phase 2 reproduced: {reproduction['phase_2_reproduced']}   "
          f"Phase 3 reproduced: {reproduction['phase_3_reproduced']}", flush=True)

    if not (reproduction["phase_2_reproduced"] and reproduction["phase_3_reproduced"]):
        OUT.write_text(json.dumps(
            {"_about": "Phase 4 ABORTED: the frozen baselines did not reproduce, so "
                       "the control arm is broken and no Phase 4 result is reportable.",
             "phase_3_reproduction": reproduction}, indent=2, default=str),
            encoding="utf-8")
        print("\n  STOP: baseline did not reproduce. No Phase 4 result reported.")
        return 1

    # -- stability --------------------------------------------------------
    stability = {"status": "not run (--no-repeat)"}
    if not args.no_repeat:
        print("\n== Pass 2 (stability)", flush=True)
        masks2, _meta2, geometry2, variants2 = one_pass(cases, quiet=True)
        stability = compare_runs(variants["C_sam_rear"], variants2["C_sam_rear"],
                                 masks, masks2, geometry, geometry2)
        print(f"  deterministic={stability['deterministic']} "
              f"mask_disagreements={stability['mask_pixel_disagreements']} "
              f"wall_diff={stability['wall_plane_max_abs_diff']} "
              f"rear_diff={stability['rear_extent_max_abs_diff']} "
              f"decision_disagreements={stability['decision_disagreements']}",
              flush=True)

    # -- the tracked cases ------------------------------------------------
    per_variant = {k: {r["case_id"]: r for r in v["per_case"]}
                   for k, v in variants.items()}

    def track(case_ids: list) -> list:
        out = []
        for case_id in case_ids:
            ra = per_variant["A_bbox_nearest"].get(case_id)
            rb = per_variant["B_sam_nearest"].get(case_id)
            rc = per_variant["C_sam_rear"].get(case_id)
            if ra is None:
                out.append({"case_id": case_id, "status": "NOT IN THIS RUN"})
                continue
            if rc["correct"] is True and rb["correct"] is False:
                verdict = "repaired"
            elif rc["correct"] is False and rb["correct"] is False:
                verdict = "persistent"
            elif rc["correct"] is False and rb["correct"] is True:
                verdict = "newly broken"
            else:
                verdict = "unchanged correct"
            out.append({
                "case_id": case_id, "object_type": ra["object_type"],
                "category": ra["category"], "open_structure": ra["open_structure"],
                "label": ra["ground_truth_against_wall"],
                "p2_bbox_nearest_m": ra["wall_distance"],
                "p3_sam_nearest_m": rb["wall_distance"],
                "p4_sam_rear_m": rc["wall_distance"],
                "p4_rear_extent_raw": rc["rear_extent"],
                "p4_projection_min": rc["projection_min"],
                "p4_projection_max": rc["projection_max"],
                "p2_decision": ra["decision"], "p3_decision": rb["decision"],
                "p4_decision": rc["decision"],
                "p2_correct": ra["correct"], "p3_correct": rb["correct"],
                "p4_correct": rc["correct"], "verdict": verdict})
        return out

    new_errors = sorted(
        r["case_id"] for r in variants["B_sam_nearest"]["per_case"]
        if r["correct"] is False
        and per_variant["A_bbox_nearest"][r["case_id"]]["correct"] is True)

    nine = track(PHASE_2_FALSE_WALLS)
    four = track(new_errors)

    payload = {
        "_about": "Phase 4. The ONLY change under test is the measured quantity: "
                  "nearest visible surface vs rear extent along the wall normal. "
                  "Same 48 cases, same labels, same MoGe-2 geometry, same SAM 2 "
                  "masks, same wall planes, same 0.12 m threshold. All four "
                  "variants share ONE geometry pass, so the walls are not merely "
                  "equal across variants, they are the same objects.",
        "frozen": {
            "rear_extent_percentile": REAR_EXTENT_PERCENTILE,
            "rear_extent_percentile_rationale":
                "Reused from Phase 3's percentile(|signed|, 10) with the "
                "projection reversed, rather than introducing a new "
                "hyperparameter. Frozen before the run.",
            "min_orientation_margin_fraction": MIN_ORIENTATION_MARGIN_FRACTION,
            "wall_contact_distance_m": P.WALL_CONTACT_DISTANCE_M,
            "orientation_rule": "the side of the plane the room's median surface "
                                "point lies on; the camera is not used",
            "production_code_changed": "none",
        },
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "dataset": {"cases": len(cases),
                    "negatives": sum(1 for c in cases if not c["truth"]),
                    "positives": sum(1 for c in cases if c["truth"]),
                    "images": len({c["image"] for c in cases})},
        "phase_3_reproduction": reproduction,
        "segmentation": {"per_case": mask_meta},
        "variants": variants,
        "comparison": {
            "order": "[A bbox+nearest, B SAM+nearest, C SAM+rear, D bbox+rear]",
            **{metric: [variants[k]["metrics"]["all"].get(metric)
                        for k, _, _, _ in VARIANTS]
               for metric in ("false_wall_rate_decided_pct", "no_recall_decided_pct",
                              "positive_recall_decided_pct", "precision_pct",
                              "f1_pct", "balanced_accuracy_pct",
                              "accuracy_decided_pct", "unknown_rate_negatives_pct",
                              "tp", "tn", "fp", "fn")},
            "false_wall_ci95": [variants[k]["metrics"]["all"]["false_wall_ci95_decided"]
                                for k, _, _, _ in VARIANTS],
            "separation_auc": [variants[k]["separation_auc"] for k, _, _, _ in VARIANTS],
        },
        "nine_phase_2_false_walls": {
            "cases": nine,
            "repaired": sum(1 for r in nine if r.get("verdict") == "repaired"),
            "persistent": sum(1 for r in nine if r.get("verdict") == "persistent"),
            "newly_broken": sum(1 for r in nine if r.get("verdict") == "newly broken"),
            "unchanged_correct": sum(1 for r in nine
                                     if r.get("verdict") == "unchanged correct")},
        "four_phase_3_new_errors": {
            "identified_at_runtime": new_errors,
            "cases": four,
            "restored_by_rear_extent": sum(1 for r in four
                                           if r.get("p4_correct") is True)},
        "distance_distributions": {
            k: variants[k]["distance_distribution"] for k, _, _, _ in VARIANTS},
        "object_type_analysis": {
            k: variants[k]["by_object_type"] for k, _, _, _ in VARIANTS},
        "open_structure_analysis": {
            k: {"open_structure": variants[k]["metrics"]["open_structure"],
                "solid": variants[k]["metrics"]["solid"],
                "open_structure_distance": distribution(
                    [r["wall_distance"] for r in variants[k]["per_case"]
                     if r["open_structure"] and r["wall_distance"] is not None]),
                "solid_distance": distribution(
                    [r["wall_distance"] for r in variants[k]["per_case"]
                     if not r["open_structure"] and r["wall_distance"] is not None])}
            for k, _, _, _ in VARIANTS},
        "threshold_sweep_diagnostic": {
            "note": f"DIAGNOSTIC ONLY. The threshold stays at "
                    f"{P.WALL_CONTACT_DISTANCE_M} m for the gate.",
            **{k: threshold_sweep(variants[k]) for k, _, _, _ in VARIANTS}},
        "percentile_sensitivity_diagnostic": {
            "note": "DIAGNOSTIC ONLY, declared before the run. The gate uses the "
                    f"frozen percentile {REAR_EXTENT_PERCENTILE}.",
            "rows": percentile_sensitivity(cases, geometry, masks)},
        "stability": stability,
        "geometry_diagnostics": geometry_diagnostics(
            variants["C_sam_rear"], geometry, cases),
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    for key, label, _f, _s in VARIANTS:
        m = variants[key]["metrics"]["all"]
        print(f"  {key:16} fw={m['false_wall_rate_decided_pct']}% "
              f"{m['false_wall_ci95_decided']} NO-rec={m['no_recall_decided_pct']}% "
              f"pos-rec={m['positive_recall_decided_pct']}% F1={m['f1_pct']}% "
              f"balacc={m['balanced_accuracy_pct']}% "
              f"AUC={variants[key]['separation_auc']} "
              f"unk={m['unknown_rate_negatives_pct']}%")
    n = payload["nine_phase_2_false_walls"]
    print(f"  nine P2 false walls: repaired={n['repaired']} "
          f"persistent={n['persistent']} newly_broken={n['newly_broken']} "
          f"unchanged_correct={n['unchanged_correct']}")
    print(f"  four P3 new errors {new_errors}: restored="
          f"{payload['four_phase_3_new_errors']['restored_by_rear_extent']}")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

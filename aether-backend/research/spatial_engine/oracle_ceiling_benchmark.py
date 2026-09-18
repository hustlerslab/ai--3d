"""Spatial engine Phase 5: the manual amodal geometry CEILING test.

    python -u research/spatial_engine/oracle_ceiling_benchmark.py

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

THE QUESTION. Phases 2, 3 and 4 each improved an input and left the wall decision
near chance. Phase 4 showed why the last one failed: the object's rear extent is
occluded and absent from the point cloud. So before anyone builds an amodal
perception model, one thing must be established -

    if the geometry engine is HANDED the object's full physical extent,
    can it get wall contact right on this benchmark at all?

A high ceiling means the missing piece is amodal perception. A low ceiling means
the benchmark or the wall planes are the problem and no perception model will
rescue it. The point of the experiment is that we do not know which, and guessing
would cost a model-building phase.

WHAT IS COMPARED. Five arms over the SAME cases, the same MoGe-2 geometry, the
same wall planes, the same 0.12 m threshold:

    A  bbox      + nearest visible surface     Phase 2
    B  SAM mask  + nearest visible surface     Phase 3
    C  SAM mask  + rear extent                 Phase 4
    A' oracle box + full extent                PHASE 5, existing wall selection
    B' oracle box + full extent                PHASE 5, plus a far-side wall gate

A, B and C are computed by importing the Phase 4 harness, so they are the same
code rather than a reimplementation, and they double as the control check.

THE ORACLE COVERS 26 OF THE 48 CASES, so every comparison is reported twice: over
the full 48 where that is meaningful (the control reproduction) and over the
26-case oracle subset, which is the only fair comparison for the oracle arms.
Reporting a 26-case oracle against a 48-case baseline would be a category error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    auc, gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.oracle_geometry import (                 # noqa: E402
    load_measurements, oracle_wall_contact, place)
from research.spatial_engine.rear_extent_benchmark import (           # noqa: E402
    VARIANTS, build_geometry, distribution, object_bucket, run_variant,
    threshold_sweep, with_f1)
from research.spatial_engine.segmentation_grounding import (          # noqa: E402
    Sam2Grounder, is_open_structure)

OUT = HERE / "oracle_ceiling_results.json"
PHASE_4 = HERE / "rear_extent_benchmark.json"

PHASE_3_HEADLINE = {"false_wall_rate_decided_pct": 21.6, "no_recall_decided_pct": 78.4,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7445}
PHASE_2_HEADLINE = {"false_wall_rate_decided_pct": 24.3, "no_recall_decided_pct": 75.7,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7174}

NINE_FALSE_WALLS = [
    "s07.bar_stool.0", "s05.armchair.0", "s16.chair.0", "s02.ottoman.0",
    "s07.bar_stool.1", "s17.chair.0", "s09.chair.0", "s01.armchair.0",
    "s17.chair.2",
]
FIVE_MISSED_POSITIVES = [
    "preserved.living_room_a.sofa.1", "preserved.living_room_b.tv_unit.0",
    "preserved.master_bedroom.bed.0", "preserved.master_bedroom.bedside_table.0",
    "preserved.master_bedroom.bedside_table.1",
]

#: The perturbation protocol, fixed and documented before the run. Each object is
#: perturbed by its OWN recorded uncertainty rather than a single global figure,
#: because a bedside table measured to +-0.05 m and a bed measured to +-0.15 m do
#: not deserve the same benefit of the doubt. Six perturbations plus the nominal.
PERTURBATIONS = [
    ("nominal", 0.0, 0.0, 0.0),
    ("depth -u", -1.0, 0.0, 0.0),
    ("depth +u", +1.0, 0.0, 0.0),
    ("width -u", 0.0, -1.0, 0.0),
    ("width +u", 0.0, +1.0, 0.0),
    ("shift toward camera", 0.0, 0.0, -1.0),
    ("shift away from camera", 0.0, 0.0, +1.0),
]


def run_oracle(cases: list, geometry: dict, masks: dict, measurements: dict, *,
               sanity_gate: bool, label: str) -> dict:
    """One oracle arm over every case that has a hand measurement."""
    rows = []
    for case in cases:
        if case["case_id"] not in measurements:
            continue
        pointmap, room = geometry[case["image"]]
        mask = masks[case["case_id"]] & pointmap.valid
        points = pointmap.points[mask]

        oracle = load_measurements()[case["case_id"]]
        place(oracle, points, room)
        contact = oracle_wall_contact(oracle, pointmap, room,
                                      sanity_gate=sanity_gate)
        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)
        rows.append({
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"],
            "object_bucket": object_bucket(case["object_type"]),
            "category": case["category"], "source_domain": case["source_domain"],
            "open_structure": is_open_structure(case["object_type"]),
            "ground_truth_against_wall": case["truth"],
            "predicted_against_wall": predicted,
            "decision": contact.decision.value,
            "correct": (predicted == case["truth"]) if predicted is not None else None,
            "wall_distance": contact.distance, "wall_index": contact.wall_index,
            "margin": contact.margin, "borderline": contact.borderline,
            "walls_considered": contact.walls_considered,
            "walls_rejected_far_side": contact.walls_rejected_far_side,
            "oracle_width_m": oracle.width_m, "oracle_depth_m": oracle.depth_m,
            "oracle_height_m": oracle.height_m,
            "oracle_uncertainty_m": oracle.uncertainty_m,
            "visible_points": oracle.visible_points,
            "visible_depth_extent": oracle.visible_depth_extent,
            "depth_underestimated": oracle.depth_underestimated,
            "failure_reason": contact.failure_reason,
            "per_wall": contact.per_wall,
        })

    measured = [r for r in rows if r["wall_distance"] is not None]
    pos = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]
    by_bucket = {}
    for bucket in sorted({r["object_bucket"] for r in rows}):
        subset = [r for r in rows if r["object_bucket"] == bucket]
        by_bucket[bucket] = with_f1(summarise(subset))
        by_bucket[bucket]["median_distance"] = distribution(
            [r["wall_distance"] for r in subset
             if r["wall_distance"] is not None]).get("median")

    return {
        "label": label, "sanity_gate": sanity_gate,
        "metrics": {
            "all": with_f1(summarise(rows)),
            "generated": with_f1(summarise([r for r in rows
                                            if r["source_domain"] == "generated"])),
            "historical": with_f1(summarise([r for r in rows
                                             if r["source_domain"] == "historical"])),
            "category_A": with_f1(summarise([r for r in rows if r["category"] == "A"])),
            "category_B": with_f1(summarise([r for r in rows if r["category"] == "B"])),
            "open_structure": with_f1(summarise([r for r in rows
                                                 if r["open_structure"]])),
            "solid": with_f1(summarise([r for r in rows if not r["open_structure"]])),
        },
        "by_object_type": by_bucket,
        "separation_auc": auc(pos, neg),
        "distance_distribution": {"positives": distribution(pos),
                                  "negatives": distribution(neg)},
        "borderline_cases": [r["case_id"] for r in rows if r["borderline"]],
        "depth_underestimated_cases": [r["case_id"] for r in rows
                                       if r["depth_underestimated"]],
        "per_case": rows,
        "failures": [r for r in rows if r["correct"] is False],
        "unknowns": [r for r in rows if r["predicted_against_wall"] is None],
    }


def uncertainty_analysis(cases: list, geometry: dict, masks: dict,
                         measurements: dict, *, sanity_gate: bool) -> dict:
    """Does the decision survive the measurement error we actually admit to?"""
    rows = []
    for case in cases:
        if case["case_id"] not in measurements:
            continue
        pointmap, room = geometry[case["image"]]
        mask = masks[case["case_id"]] & pointmap.valid
        points = pointmap.points[mask]
        base = load_measurements()[case["case_id"]]
        u = base.uncertainty_m

        outcomes = {}
        for name, dd, dw, ds in PERTURBATIONS:
            oracle = load_measurements()[case["case_id"]]
            d_scale = (oracle.depth_m + dd * u) / oracle.depth_m
            w_scale = (oracle.width_m + dw * u) / oracle.width_m
            place(oracle, points, room, d_scale=d_scale, w_scale=w_scale,
                  shift_m=ds * u)
            contact = oracle_wall_contact(oracle, pointmap, room,
                                          sanity_gate=sanity_gate)
            outcomes[name] = {"decision": contact.decision.value,
                              "gap": contact.distance}

        decisions = {o["decision"] for o in outcomes.values()}
        gaps = [o["gap"] for o in outcomes.values() if o["gap"] is not None]
        rows.append({
            "case_id": case["case_id"], "object_type": case["object_type"],
            "uncertainty_m": u,
            "ground_truth_against_wall": case["truth"],
            "nominal_decision": outcomes["nominal"]["decision"],
            "nominal_gap": outcomes["nominal"]["gap"],
            "stable": len(decisions) == 1,
            "decisions_seen": sorted(decisions),
            "gap_range": [round(min(gaps), 5), round(max(gaps), 5)] if gaps else None,
            "outcomes": outcomes,
        })

    stable = sum(1 for r in rows if r["stable"])
    return {
        "protocol": "Each object perturbed by its OWN recorded uncertainty: depth "
                    "-u/+u, width -u/+u, and the box slid along the depth axis "
                    "-u/+u. Six perturbations plus the nominal, fixed before the "
                    "run and applied to every case. No perturbation was chosen "
                    "after seeing a result.",
        "perturbations": [p[0] for p in PERTURBATIONS],
        "cases": len(rows), "stable": stable, "unstable": len(rows) - stable,
        "stable_pct": round(100.0 * stable / len(rows), 1) if rows else None,
        "unstable_cases": [r["case_id"] for r in rows if not r["stable"]],
        "per_case": rows,
    }


def interpret(balanced_accuracy) -> dict:
    """The brief's decision tree, applied to whatever number comes out."""
    if balanced_accuracy is None:
        return {"band": "UNDEFINED", "meaning": "no balanced accuracy computable"}
    if balanced_accuracy > 90.0:
        return {"band": "HIGH CEILING",
                "meaning": "The benchmark is geometrically solvable. The missing "
                           "information is amodal object geometry, and estimating "
                           "it is the right next problem."}
    if balanced_accuracy >= 70.0:
        return {"band": "MEDIUM CEILING",
                "meaning": "Amodal geometry helps but is not sufficient. Wall-plane "
                           "quality, candidate-wall selection, the contact "
                           "definition and benchmark ambiguity must be investigated "
                           "before another perception model is chosen."}
    return {"band": "LOW CEILING",
            "meaning": "Even with hand-supplied object geometry the formulation is "
                       "not reliably solvable. Stop the perception-model search and "
                       "investigate the benchmark and the wall geometry."}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    measurements = load_measurements()
    subset_ids = [c["case_id"] for c in cases if c["case_id"] in measurements]
    print(f"cases {len(cases)}   oracle subset {len(subset_ids)}   "
          f"measurements on file {len(measurements)}\n", flush=True)

    missing = sorted(set(measurements) - set(subset_ids))
    if missing:
        print(f"  WARNING: measurements with no matching case: {missing}", flush=True)

    # -- SAM masks and geometry, shared by every arm ----------------------
    grounder = Sam2Grounder()
    grounder.load()
    masks = {c["case_id"]: grounder.segment(ROOT / c["image"], c["bbox"]).mask
             for c in cases}
    grounder.unload()
    print(f"  SAM: {len(masks)} masks", flush=True)
    geometry, _ = build_geometry(cases, masks)

    # -- control arms, imported from the Phase 4 harness -------------------
    variants = {}
    for key, label, footprint, statistic in VARIANTS:
        if key == "D_bbox_rear":
            continue
        variants[key] = run_variant(cases, geometry, masks, footprint=footprint,
                                    statistic=statistic, key=key, label=label)

    a, b = variants["A_bbox_nearest"], variants["B_sam_nearest"]
    control = {
        "phase_2_stored": PHASE_2_HEADLINE, "phase_3_stored": PHASE_3_HEADLINE,
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
    control["phase_2_reproduced"] = control["variant_A_measured"] == PHASE_2_HEADLINE
    control["phase_3_reproduced"] = control["variant_B_measured"] == PHASE_3_HEADLINE
    if PHASE_4.is_file():
        stored = json.loads(PHASE_4.read_text(encoding="utf-8"))
        prev = {r["case_id"]: r
                for r in stored["variants"]["C_sam_rear"]["per_case"]}
        control["phase_4_decision_drift"] = [
            r["case_id"] for r in variants["C_sam_rear"]["per_case"]
            if r["case_id"] in prev and r["decision"] != prev[r["case_id"]]["decision"]]
        control["phase_4_reproduced"] = not control["phase_4_decision_drift"]
    print(f"\n  control: P2={control['phase_2_reproduced']} "
          f"P3={control['phase_3_reproduced']} "
          f"P4={control.get('phase_4_reproduced')}", flush=True)

    if not (control["phase_2_reproduced"] and control["phase_3_reproduced"]):
        OUT.write_text(json.dumps(
            {"_about": "Phase 5 ABORTED: the control arm drifted, so no ceiling "
                       "measurement is reportable.", "control_reproduction": control},
            indent=2, default=str), encoding="utf-8")
        print("\n  STOP: control drifted. No ceiling result reported.")
        return 1

    # -- the oracle arms ---------------------------------------------------
    oracle_a = run_oracle(cases, geometry, masks, measurements, sanity_gate=False,
                          label="oracle box, existing wall selection")
    oracle_b = run_oracle(cases, geometry, masks, measurements, sanity_gate=True,
                          label="oracle box + far-side wall gate")

    # Restrict the control arms to the oracle subset so the comparison is fair.
    ids = set(subset_ids)
    subset_metrics = {}
    for key, variant in variants.items():
        rows = [r for r in variant["per_case"] if r["case_id"] in ids]
        m = with_f1(summarise(rows))
        pos = [r["wall_distance"] for r in rows
               if r["ground_truth_against_wall"] and r["wall_distance"] is not None]
        neg = [r["wall_distance"] for r in rows
               if not r["ground_truth_against_wall"] and r["wall_distance"] is not None]
        subset_metrics[key] = {"metrics": m, "separation_auc": auc(pos, neg),
                               "distance_distribution": {
                                   "positives": distribution(pos),
                                   "negatives": distribution(neg)},
                               "per_case": rows}

    uncertainty = uncertainty_analysis(cases, geometry, masks, measurements,
                                       sanity_gate=True)

    # -- critical case tracking -------------------------------------------
    by_arm = {k: {r["case_id"]: r for r in v["per_case"]}
              for k, v in subset_metrics.items()}
    by_arm["oracle_A"] = {r["case_id"]: r for r in oracle_a["per_case"]}
    by_arm["oracle_B"] = {r["case_id"]: r for r in oracle_b["per_case"]}

    def track(case_ids: list) -> list:
        out = []
        for case_id in case_ids:
            if case_id not in by_arm["oracle_B"]:
                out.append({"case_id": case_id, "status": "NOT IN ORACLE SUBSET"})
                continue
            ra = by_arm["A_bbox_nearest"][case_id]
            rb = by_arm["B_sam_nearest"][case_id]
            rc = by_arm["C_sam_rear"][case_id]
            oa = by_arm["oracle_A"][case_id]
            ob = by_arm["oracle_B"][case_id]
            if ob["correct"] is True and rc["correct"] is not True:
                verdict = "correctly solved"
            elif ob["correct"] is True:
                verdict = "unchanged correct"
            elif ob["correct"] is False and rc["correct"] is False:
                verdict = "still wrong"
            elif ob["correct"] is False:
                verdict = "newly wrong"
            else:
                verdict = "ambiguous"
            out.append({
                "case_id": case_id, "object_type": ra["object_type"],
                "label": ra["ground_truth_against_wall"],
                "p2_m": ra["wall_distance"], "p3_m": rb["wall_distance"],
                "p4_m": rc["wall_distance"],
                "oracle_A_m": oa["wall_distance"], "oracle_B_m": ob["wall_distance"],
                "p2": ra["decision"], "p3": rb["decision"], "p4": rc["decision"],
                "oracle_A": oa["decision"], "oracle_B": ob["decision"],
                "oracle_B_correct": ob["correct"],
                "oracle_B_margin": ob["margin"],
                "oracle_B_borderline": ob["borderline"],
                "walls_rejected_far_side": ob["walls_rejected_far_side"],
                "verdict": verdict})
        return out

    wrong_side = sorted(r["case_id"] for r in oracle_a["per_case"]
                        if any(w.get("entirely_far_side") for w in r["per_wall"]))

    mb = oracle_b["metrics"]["all"]
    ceiling = interpret(mb["balanced_accuracy_pct"])

    payload = {
        "_about": "Phase 5. A manual amodal geometry ORACLE supplies each object's "
                  "full physical extent; the existing geometry computes the wall "
                  "decision. This measures the CEILING, not a method. The oracle "
                  "covers 26 of the 48 cases, so control arms are reported both on "
                  "the full 48 (reproduction) and restricted to the 26 (comparison).",
        "protocol": {
            "oracle_supplies": "width, depth, height only",
            "oracle_does_not_supply": "position, orientation, wall distance, label",
            "position_rule": "box near face at the nearest visible surface, "
                             "extending away from the camera by the measured depth",
            "orientation_rule": "width axis = dominant horizontal direction of the "
                                "object's own visible points",
            "threshold_m": P.WALL_CONTACT_DISTANCE_M,
            "production_code_changed": "none",
            "caveat": "This is a MANUAL AMODAL GEOMETRY ORACLE, an empirical "
                      "ceiling estimate. It is not measured 3D ground truth and "
                      "must not be described as perfect.",
        },
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "control_reproduction": control,
        "subset": {
            "case_ids": subset_ids, "cases": len(subset_ids),
            "negatives": sum(1 for c in cases
                             if c["case_id"] in ids and not c["truth"]),
            "positives": sum(1 for c in cases if c["case_id"] in ids and c["truth"]),
            "images": len({c["image"] for c in cases if c["case_id"] in ids}),
            "covers_nine_false_walls": [c for c in NINE_FALSE_WALLS if c in ids],
            "covers_five_missed_positives": [c for c in FIVE_MISSED_POSITIVES
                                             if c in ids],
        },
        "full_48_control": {k: {"metrics": v["metrics"]["all"],
                                "separation_auc": v["separation_auc"]}
                            for k, v in variants.items()},
        "subset_control": {k: {"metrics": v["metrics"],
                               "separation_auc": v["separation_auc"],
                               "distance_distribution": v["distance_distribution"]}
                           for k, v in subset_metrics.items()},
        "oracle_A": {k: v for k, v in oracle_a.items() if k != "per_case"},
        "oracle_B": {k: v for k, v in oracle_b.items() if k != "per_case"},
        "oracle_A_per_case": oracle_a["per_case"],
        "oracle_B_per_case": oracle_b["per_case"],
        "comparison_on_subset": {
            "order": "[A bbox+nearest, B SAM+nearest, C SAM+rear, oracle A, oracle B]",
            **{metric: [subset_metrics["A_bbox_nearest"]["metrics"].get(metric),
                        subset_metrics["B_sam_nearest"]["metrics"].get(metric),
                        subset_metrics["C_sam_rear"]["metrics"].get(metric),
                        oracle_a["metrics"]["all"].get(metric),
                        oracle_b["metrics"]["all"].get(metric)]
               for metric in ("tp", "tn", "fp", "fn",
                              "false_wall_rate_decided_pct", "no_recall_decided_pct",
                              "positive_recall_decided_pct", "precision_pct",
                              "f1_pct", "balanced_accuracy_pct",
                              "accuracy_decided_pct", "unknown_rate_negatives_pct")},
            "separation_auc": [subset_metrics["A_bbox_nearest"]["separation_auc"],
                               subset_metrics["B_sam_nearest"]["separation_auc"],
                               subset_metrics["C_sam_rear"]["separation_auc"],
                               oracle_a["separation_auc"], oracle_b["separation_auc"]],
        },
        "critical_cases": track(subset_ids),
        "five_missed_positives": track(FIVE_MISSED_POSITIVES),
        "nine_false_walls": track(NINE_FALSE_WALLS),
        "wrong_side_wall_cases": {
            "cases_with_a_far_side_candidate_wall": wrong_side,
            "count": len(wrong_side),
            "oracle_A_errors_among_them": sorted(
                r["case_id"] for r in oracle_a["per_case"]
                if r["case_id"] in set(wrong_side) and r["correct"] is False),
            "oracle_B_errors_among_them": sorted(
                r["case_id"] for r in oracle_b["per_case"]
                if r["case_id"] in set(wrong_side) and r["correct"] is False),
        },
        "uncertainty_analysis": uncertainty,
        "threshold_sweep_diagnostic": {
            "note": f"DIAGNOSTIC ONLY. The gate used the frozen "
                    f"{P.WALL_CONTACT_DISTANCE_M} m.",
            "oracle_A": threshold_sweep(oracle_a),
            "oracle_B": threshold_sweep(oracle_b)},
        "ceiling_interpretation": {
            "oracle_B_balanced_accuracy_pct": mb["balanced_accuracy_pct"],
            **ceiling},
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    names = [("A bbox+near", subset_metrics["A_bbox_nearest"]["metrics"],
              subset_metrics["A_bbox_nearest"]["separation_auc"]),
             ("B SAM+near", subset_metrics["B_sam_nearest"]["metrics"],
              subset_metrics["B_sam_nearest"]["separation_auc"]),
             ("C SAM+rear", subset_metrics["C_sam_rear"]["metrics"],
              subset_metrics["C_sam_rear"]["separation_auc"]),
             ("oracle A", oracle_a["metrics"]["all"], oracle_a["separation_auc"]),
             ("oracle B", oracle_b["metrics"]["all"], oracle_b["separation_auc"])]
    print(f"  on the {len(subset_ids)}-case oracle subset:")
    for name, m, au in names:
        print(f"  {name:12} fw={m['false_wall_rate_decided_pct']}% "
              f"NO-rec={m['no_recall_decided_pct']}% "
              f"pos-rec={m['positive_recall_decided_pct']}% F1={m['f1_pct']}% "
              f"balacc={m['balanced_accuracy_pct']}% AUC={au} "
              f"TP/TN/FP/FN={m['tp']}/{m['tn']}/{m['fp']}/{m['fn']}")
    print(f"\n  CEILING: {ceiling['band']} "
          f"(oracle B balanced accuracy {mb['balanced_accuracy_pct']}%)")
    print(f"  uncertainty: {uncertainty['stable']}/{uncertainty['cases']} "
          f"decisions stable ({uncertainty['stable_pct']}%)")
    print(f"  borderline (|gap-0.12| < 0.05): {len(oracle_b['borderline_cases'])}")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

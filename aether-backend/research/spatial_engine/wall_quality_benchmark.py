"""Spatial engine Phase 6: wall quality + abstention.

    python -u research/spatial_engine/wall_quality_benchmark.py --features
    python -u research/spatial_engine/wall_quality_benchmark.py

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

THE QUESTION. Can deterministic geometric evidence tell a room-bounding wall from
a contaminant vertical plane well enough to make wall-contact decisions useful,
while honestly abstaining when it cannot?

TWO PASSES, BY DESIGN. The brief forbids inventing a weighted score before the
feature distributions have been looked at, and forbids tuning against labels.
So `--features` runs first: it reproduces the controls, measures every candidate
plane in every image, splits the planes by whether the decision they produced
was right or wrong, and renders each plane's pixel support over its image so
the planes can be classified BY EYE into wall / partition / furniture. Only
after that are the operating points written into OPERATING_POINTS below, and
the second pass evaluates them - together with the exact 0.40 inlier-fraction
diagnostic Phase 5 left behind, which is labelled as the pre-existing candidate
it is.

THE OBJECT SIDE IS FROZEN. Every decision uses the SAM mask and the production
`wall_contact` statistic exactly as Phase 3 did. The gate never touches the
object; it only decides which fitted planes count as walls, by handing the
production function a room whose failed planes are marked uncertain. UNKNOWN is
what that function already returns when no plane survives, so abstention is not
new behaviour - it is behaviour the code has had since Phase 1 and never used.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    auc, gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.oracle_ceiling_benchmark import (        # noqa: E402
    run_oracle)
from research.spatial_engine.oracle_geometry import (                 # noqa: E402
    load_measurements, oracle_wall_contact, place)
from research.spatial_engine.rear_extent_benchmark import (           # noqa: E402
    VARIANTS, build_geometry, distribution, object_bucket, run_variant, with_f1)
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)
from research.spatial_engine.segmentation_grounding import (          # noqa: E402
    Sam2Grounder, is_open_structure)
from research.spatial_engine.wall_quality import (                    # noqa: E402
    WallQualityGate, assign_pixels, extract_wall_features, gated_room)

OUT = HERE / "wall_quality_results.json"
FEATURES_OUT = HERE / "wall_quality_features.json"
CLASSES = HERE / "wall_plane_classes.json"
PHASE_4 = HERE / "rear_extent_benchmark.json"
PHASE_5 = HERE / "oracle_ceiling_results.json"
OVERLAYS = Path(r"C:\Users\user\AppData\Local\Temp\claude"
                r"\g--ALLURE-INTERIOR-ISHANA-Interior-design"
                r"\9c0578df-4a5c-4af1-93e9-bcb7da7d1588\scratchpad\wall_overlays")

PHASE_2_HEADLINE = {"false_wall_rate_decided_pct": 24.3, "no_recall_decided_pct": 75.7,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7174}
PHASE_3_HEADLINE = {"false_wall_rate_decided_pct": 21.6, "no_recall_decided_pct": 78.4,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.7445}
PHASE_4_HEADLINE = {"false_wall_rate_decided_pct": 37.8, "no_recall_decided_pct": 62.2,
                    "unknown_rate_negatives_pct": 0.0, "separation_auc": 0.6118}
PHASE_5_ORACLE_B = {"balanced_accuracy_pct": 51.3, "false_wall_rate_decided_pct": 52.9,
                    "separation_auc": 0.5294}

FEATURE_NAMES = [
    "inlier_fraction", "extent_fraction", "inlier_pixel_fraction",
    "horizontal_extent_frac", "vertical_extent_frac", "connected_components",
    "largest_component_fraction", "width_m", "height_m", "area_m2",
    "min_height_above_floor_m", "max_height_above_floor_m", "floor_band_fraction",
    "upper_band_fraction", "centroid_distance_m", "camera_distance_m",
    "enclosure_fraction", "manhattan_residual_deg", "residual_median",
]

#: The pre-existing Phase 5 diagnostic, re-run unaltered on the full 48. It is a
#: CANDIDATE HYPOTHESIS inherited from a 26-case post-hoc sweep, not a threshold
#: this phase discovered or validated.
PHASE5_DIAGNOSTIC_040 = WallQualityGate(name="phase5_diagnostic_inlier_0.40",
                                        min_inlier_fraction=0.40)

#: Declared AFTER the `--features` pass had been read and BEFORE any of them was
#: evaluated. Each is a small set of named floors chosen from where the correct
#: and wrong distributions sat, not from what scored best. See the report, S6-7.
#: DECLARED 2026-09-15 after the feature pass, before evaluation. Two features
#: carry the gate, chosen because they are the two that separated the planes
#: behind wrong decisions from the planes behind right ones in that pass AND
#: match what the eye pass saw:
#:
#:   enclosure_fraction   - a room-bounding wall has (nearly) the whole scene on
#:                          its room side. The glazed partition scored ~0.60,
#:                          island edges 0.69-0.88, the bookshelf front 0.74,
#:                          genuine walls 0.91-1.00. TN median 0.904.
#:   floor_band_fraction  - a wall's support in a furnished room sits ABOVE the
#:                          furniture; a plinth or island front is all at floor
#:                          level. FP median 0.81, TN p75 0.004, max 0.07.
#:
#: NOT used: height / upper-band. They separate in aggregate but for the wrong
#: reason - the wall behind a sofa is only VISIBLE above the sofa, so its
#: measured height is occlusion, not architecture. A height floor would reject
#: the true wall behind every positive. NOT used: inlier_fraction - it does not
#: separate FP from TN on the full 48 (0.249 vs 0.241); the conservative point
#: carries a low floor on it only to refuse the thinnest fits.
OPERATING_POINTS: list = [
    WallQualityGate(name="permissive", min_enclosure_fraction=0.80,
                    max_floor_band_fraction=0.75),
    WallQualityGate(name="moderate", min_enclosure_fraction=0.90,
                    max_floor_band_fraction=0.50),
    WallQualityGate(name="conservative", min_enclosure_fraction=0.95,
                    max_floor_band_fraction=0.25, min_inlier_fraction=0.15),
]

#: Diagnostic sweep over one feature at a time. Reported as a curve, never as a
#: choice. Declared alongside the operating points.
SWEEP_FEATURES: dict = {
    "min_inlier_fraction": [0.06, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60],
    "min_height_m": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
    "min_enclosure_fraction": [0.0, 0.80, 0.90, 0.95, 0.97, 0.99],
    "min_upper_band_fraction": [0.0, 0.05, 0.10, 0.20, 0.30, 0.40],
    "max_floor_band_fraction": [1.0, 0.75, 0.50, 0.25, 0.10, 0.02],
}


def stats(values: list) -> dict:
    vals = [float(v) for v in values
            if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "median": round(statistics.median(vals), 4),
            "p25": round(float(np.percentile(vals, 25)), 4),
            "p75": round(float(np.percentile(vals, 75)), 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def render_overlay(image_key: str, pointmap, room, exclude, features: list) -> Path:
    """Each plane's pixel support painted over the image, labelled."""
    from PIL import Image, ImageDraw

    OVERLAYS.mkdir(parents=True, exist_ok=True)
    img = Image.open(ROOT / image_key).convert("RGB").resize(
        (pointmap.width, pointmap.height))
    base = np.asarray(img).astype(np.float64)
    assigned, _valid = assign_pixels(pointmap, room, exclude)
    colours = [(255, 40, 40), (40, 220, 40), (40, 120, 255), (255, 210, 0),
               (255, 0, 255), (0, 255, 255)]
    for k in range(len(room.walls)):
        pix = assigned == k
        if not pix.any():
            continue
        c = np.array(colours[k % len(colours)], dtype=np.float64)
        base[pix] = 0.45 * base[pix] + 0.55 * c
    out = Image.fromarray(base.astype(np.uint8))
    draw = ImageDraw.Draw(out)
    by_index = {f.wall_index: f for f in features}
    for k in range(len(room.walls)):
        pix = assigned == k
        f = by_index.get(k)
        if not pix.any() or f is None:
            continue
        rows, cols = np.nonzero(pix)
        cx, cy = int(np.median(cols)), int(np.median(rows))
        text = (f"w{k} if={f.inlier_fraction:.2f} enc={f.enclosure_fraction} "
                f"h={f.height_m:.1f}m w={f.width_m:.1f}m"
                + (" UNC" if f.fitter_uncertain else ""))
        draw.rectangle([cx - 2, cy - 2, cx + 6 * len(text) + 2, cy + 12], fill=(0, 0, 0))
        draw.text((cx, cy), text, fill=colours[k % len(colours)])
    safe = image_key.replace("/", "__").replace("\\", "__")
    path = OVERLAYS / f"{safe}.png"
    out.save(path)
    return path


def decide_with_gate(cases: list, geometry: dict, masks: dict, features: dict,
                     gate: WallQualityGate, *, label: str) -> dict:
    """SAM mask + production wall_contact, on a room the gate has filtered."""
    rows = []
    rejections = {}
    for case in cases:
        pointmap, room = geometry[case["image"]]
        gated, rejected = gated_room(room, features[case["image"]], gate)
        rejections[case["image"]] = rejected
        mask = masks[case["case_id"]]
        if not mask.any():
            mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
        contact = P.wall_contact(pointmap, gated, mask)
        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)

        # Wrong-side survivors: candidate planes that passed the gate but sit
        # entirely on the far side of the object from the room interior.
        pts = pointmap.points[mask & pointmap.valid]
        centre = room_centroid(pointmap)
        scale = room.scene_scale or pointmap.scene_scale()
        far_side_survivors = []
        for k, fit in enumerate(gated.walls):
            if fit.uncertain or fit.plane is None or pts.shape[0] < 8:
                continue
            sign, _s, _m = orient_to_room(fit.plane, centre, scale)
            if sign and float((sign * fit.plane.signed_distance(pts)).max()) < 0:
                far_side_survivors.append(k)

        rows.append({
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"],
            "object_bucket": object_bucket(case["object_type"]),
            "category": case["category"], "source_domain": case["source_domain"],
            "open_structure": is_open_structure(case["object_type"]),
            "ground_truth_against_wall": case["truth"],
            "predicted_against_wall": predicted, "decision": contact.decision.value,
            "correct": (predicted == case["truth"]) if predicted is not None else None,
            "wall_distance": contact.distance, "wall_index": contact.wall_index,
            "wall_confidence": contact.wall_confidence,
            "walls_available": sum(1 for w in gated.walls if not w.uncertain),
            "walls_rejected_by_gate": sorted(rejected),
            "far_side_survivors": far_side_survivors,
            "failure_reason": contact.failure_reason,
        })

    measured = [r for r in rows if r["wall_distance"] is not None]
    pos = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]
    all_m = with_f1(summarise(rows))
    n = len(rows)
    all_m["accuracy_all_pct"] = round(100.0 * (all_m["tp"] + all_m["tn"]) / n, 1)
    all_m["unknown_total"] = len([r for r in rows if r["predicted_against_wall"] is None])
    all_m["unknown_rate_all_pct"] = round(100.0 * all_m["unknown_total"] / n, 1)

    def sub(pred):
        return with_f1(summarise([r for r in rows if pred(r)]))

    return {
        "label": label, "gate": gate.__dict__,
        "metrics": {
            "all": all_m,
            "generated": sub(lambda r: r["source_domain"] == "generated"),
            "historical": sub(lambda r: r["source_domain"] == "historical"),
            "category_A": sub(lambda r: r["category"] == "A"),
            "category_B": sub(lambda r: r["category"] == "B"),
            "open_structure": sub(lambda r: r["open_structure"]),
            "solid": sub(lambda r: not r["open_structure"]),
        },
        "separation_auc": auc(pos, neg),
        "distance_distribution": {"positives": distribution(pos),
                                  "negatives": distribution(neg)},
        "unknown_cases": [r["case_id"] for r in rows if r["predicted_against_wall"] is None],
        "far_side_survivor_cases": [r["case_id"] for r in rows if r["far_side_survivors"]],
        "planes_rejected_per_image": {k: sorted(v) for k, v in rejections.items()},
        "per_case": rows,
        "failures": [r for r in rows if r["correct"] is False],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", action="store_true",
                        help="first pass: features, distributions, overlays; no gate")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}\n", flush=True)

    grounder = Sam2Grounder()
    grounder.load()
    masks = {c["case_id"]: grounder.segment(ROOT / c["image"], c["bbox"]).mask
             for c in cases}
    grounder.unload()
    geometry, boxes_by_image = build_geometry(cases, masks)
    exclude_by_image = {}
    for key, (pm, _room) in geometry.items():
        ex = np.zeros((pm.height, pm.width), dtype=bool)
        for box in boxes_by_image[key]:
            ex |= P.mask_from_box(pm.height, pm.width, box)
        exclude_by_image[key] = ex

    # -- controls ---------------------------------------------------------
    variants = {}
    for key, label, footprint, statistic in VARIANTS:
        if key == "D_bbox_rear":
            continue
        variants[key] = run_variant(cases, geometry, masks, footprint=footprint,
                                    statistic=statistic, key=key, label=label)

    def headline(v):
        m = v["metrics"]["all"]
        return {"false_wall_rate_decided_pct": m["false_wall_rate_decided_pct"],
                "no_recall_decided_pct": m["no_recall_decided_pct"],
                "unknown_rate_negatives_pct": m["unknown_rate_negatives_pct"],
                "separation_auc": v["separation_auc"]}

    measurements = load_measurements()
    oracle_b = run_oracle(cases, geometry, masks, measurements, sanity_gate=True,
                          label="Phase 5 oracle B, reproduced")
    ob = oracle_b["metrics"]["all"]
    control = {
        "phase_2": {"stored": PHASE_2_HEADLINE,
                    "measured": headline(variants["A_bbox_nearest"])},
        "phase_3": {"stored": PHASE_3_HEADLINE,
                    "measured": headline(variants["B_sam_nearest"])},
        "phase_4": {"stored": PHASE_4_HEADLINE,
                    "measured": headline(variants["C_sam_rear"])},
        "phase_5_oracle_B": {"stored": PHASE_5_ORACLE_B,
                             "measured": {"balanced_accuracy_pct": ob["balanced_accuracy_pct"],
                                          "false_wall_rate_decided_pct":
                                              ob["false_wall_rate_decided_pct"],
                                          "separation_auc": oracle_b["separation_auc"]}},
    }
    for k in control:
        control[k]["reproduced"] = control[k]["stored"] == control[k]["measured"]
    if PHASE_4.is_file():
        prev = {r["case_id"]: r for r in json.loads(PHASE_4.read_text(encoding="utf-8"))
                ["variants"]["C_sam_rear"]["per_case"]}
        control["phase_4"]["per_case_drift"] = [
            r["case_id"] for r in variants["C_sam_rear"]["per_case"]
            if r["case_id"] in prev and r["decision"] != prev[r["case_id"]]["decision"]]
    if PHASE_5.is_file():
        prev = {r["case_id"]: r for r in json.loads(PHASE_5.read_text(encoding="utf-8"))
                ["oracle_B_per_case"]}
        control["phase_5_oracle_B"]["per_case_drift"] = [
            r["case_id"] for r in oracle_b["per_case"]
            if r["case_id"] in prev and r["decision"] != prev[r["case_id"]]["decision"]]
    all_ok = all(control[k]["reproduced"] for k in control)
    print("  controls:", {k: control[k]["reproduced"] for k in control}, flush=True)
    if not all_ok:
        OUT.write_text(json.dumps({"_about": "Phase 6 ABORTED: control drift.",
                                   "control_reproduction": control},
                                  indent=2, default=str), encoding="utf-8")
        print("  STOP: control drift.")
        return 1

    # -- features for every candidate plane --------------------------------
    features = {key: extract_wall_features(pm, room, exclude_by_image[key])
                for key, (pm, room) in geometry.items()}
    features_json = {key: [f.as_dict() for f in fs] for key, fs in features.items()}
    total_planes = sum(len(v) for v in features.values())
    usable_planes = sum(1 for v in features.values() for f in v if not f.fitter_uncertain)

    # The plane each Phase 3 decision actually used, with its features.
    case_img = {c["case_id"]: c["image"] for c in cases}
    selected = []
    for r in variants["B_sam_nearest"]["per_case"]:
        fs = {f.wall_index: f for f in features[case_img[r["case_id"]]]}
        f = fs.get(r["wall_index"]) if r["wall_index"] is not None else None
        selected.append({"case_id": r["case_id"], "correct": r["correct"],
                         "label": r["ground_truth_against_wall"],
                         "decision": r["decision"], "wall_index": r["wall_index"],
                         "features": f.as_dict() if f else None})
    dist = {}
    for name in FEATURE_NAMES:
        dist[name] = {
            "selected_correct": stats([s["features"][name] for s in selected
                                       if s["correct"] is True and s["features"]]),
            "selected_wrong": stats([s["features"][name] for s in selected
                                     if s["correct"] is False and s["features"]]),
            "all_usable_planes": stats([f.as_dict()[name] for v in features.values()
                                        for f in v if not f.fitter_uncertain]),
        }

    # -- manual classes, if the eye pass has been done ---------------------
    classes = (json.loads(CLASSES.read_text(encoding="utf-8")) if CLASSES.is_file()
               else {})
    by_class = {}
    if classes:
        for key, fs in features.items():
            for f in fs:
                c = classes.get(f"{key}:{f.wall_index}", "UNCLASSIFIED")
                by_class.setdefault(c, []).append(f.as_dict())
    class_dist = {c: {name: stats([f[name] for f in fs]) for name in FEATURE_NAMES}
                  for c, fs in by_class.items()}

    if args.features:
        paths = [str(render_overlay(key, pm, room, exclude_by_image[key], features[key]))
                 for key, (pm, room) in geometry.items()]
        FEATURES_OUT.write_text(json.dumps({
            "_about": "Phase 6 first pass. Features for every candidate plane, the "
                      "plane each Phase 3 decision selected, and distributions split "
                      "by whether that decision was right. No gate evaluated.",
            "control_reproduction": control,
            "planes": {"total": total_planes, "usable": usable_planes},
            "features_per_image": features_json,
            "selected_plane_features": selected,
            "feature_distributions": dist,
            "overlays": paths}, indent=2, default=str), encoding="utf-8")
        print(f"\n  planes {total_planes} (usable {usable_planes}); overlays -> {OVERLAYS}")
        print(f"  wrote {FEATURES_OUT}")
        for name in FEATURE_NAMES:
            c, w = dist[name]["selected_correct"], dist[name]["selected_wrong"]
            print(f"  {name:28} correct med={c.get('median')} [{c.get('p25')},{c.get('p75')}]"
                  f"   wrong med={w.get('median')} [{w.get('p25')},{w.get('p75')}]")
        return 0

    if not OPERATING_POINTS:
        print("\n  STOP: OPERATING_POINTS not declared. Run --features first, read the "
              "distributions, declare the points, then run again.")
        return 2

    # -- evaluation ---------------------------------------------------------
    results = {}
    for gate in OPERATING_POINTS:
        results[gate.name] = decide_with_gate(cases, geometry, masks, features, gate,
                                              label=gate.name)
    p5 = decide_with_gate(cases, geometry, masks, features, PHASE5_DIAGNOSTIC_040,
                          label="Phase 5 diagnostic 0.40 wall-quality gate")

    # Oracle + gate on the 26-case subset: the object-geometry ceiling with a
    # cleaned wall set, which is the real ceiling Phase 5 could only hint at.
    oracle_gated = {}
    for gate in OPERATING_POINTS + [PHASE5_DIAGNOSTIC_040]:
        rows = []
        for case in cases:
            if case["case_id"] not in measurements:
                continue
            pm, room = geometry[case["image"]]
            g, _rej = gated_room(room, features[case["image"]], gate)
            pts = pm.points[masks[case["case_id"]] & pm.valid]
            o = load_measurements()[case["case_id"]]
            place(o, pts, room)
            c = oracle_wall_contact(o, pm, g, sanity_gate=False)
            pred = None if c.decision is P.Decision.UNKNOWN else c.decision is P.Decision.YES
            rows.append({"ground_truth_against_wall": case["truth"],
                         "predicted_against_wall": pred, "wall_distance": c.distance})
        m = with_f1(summarise(rows))
        pos = [r["wall_distance"] for r in rows
               if r["ground_truth_against_wall"] and r["wall_distance"] is not None]
        neg = [r["wall_distance"] for r in rows
               if not r["ground_truth_against_wall"] and r["wall_distance"] is not None]
        oracle_gated[gate.name] = {"metrics": m, "separation_auc": auc(pos, neg)}

    # -- contaminant analysis ---------------------------------------------
    base_rows = {r["case_id"]: r for r in variants["B_sam_nearest"]["per_case"]}
    contaminants = []
    for cid, r in base_rows.items():
        if not (r["correct"] is False and not r["ground_truth_against_wall"]):
            continue
        img = case_img[cid]
        old_f = {f.wall_index: f for f in features[img]}.get(r["wall_index"])
        entry = {"case_id": cid, "object_type": r["object_type"],
                 "old_selected_plane": r["wall_index"],
                 "old_inlier_fraction": old_f.inlier_fraction if old_f else None,
                 "old_gap_m": r["wall_distance"],
                 "manual_class": classes.get(f"{img}:{r['wall_index']}", "UNCLASSIFIED"),
                 "old_plane_features": old_f.as_dict() if old_f else None,
                 "under_gate": {}}
        for name, res in list(results.items()) + [(p5["label"], p5)]:
            nr = {x["case_id"]: x for x in res["per_case"]}[cid]
            entry["under_gate"][name] = {
                "decision": nr["decision"], "correct": nr["correct"],
                "old_plane_rejected": r["wall_index"] in nr["walls_rejected_by_gate"],
                "new_selected_plane": nr["wall_index"], "new_gap_m": nr["wall_distance"],
                "new_plane_inlier_fraction": nr["wall_confidence"]}
        contaminants.append(entry)

    # -- selection analysis --------------------------------------------------
    def selection_summary(res):
        out = {"correct": [], "wrong": []}
        chg = 0
        for r in res["per_case"]:
            if r["wall_confidence"] is not None:
                out["correct" if r["correct"] else "wrong"].append(r["wall_confidence"])
            if r["wall_index"] != base_rows[r["case_id"]]["wall_index"]:
                chg += 1
        return {"selected_inlier_fraction_correct": stats(out["correct"]),
                "selected_inlier_fraction_wrong": stats(out["wrong"]),
                "unknown": len(res["unknown_cases"]),
                "selected_plane_changed_vs_phase3": chg}

    # -- diagnostic sweep, one feature at a time -----------------------------
    sweep = {}
    for feat, values in SWEEP_FEATURES.items():
        curve = []
        for v in values:
            g = WallQualityGate(name=f"sweep_{feat}_{v}", **{feat: v})
            res = decide_with_gate(cases, geometry, masks, features, g, label=g.name)
            m = res["metrics"]["all"]
            curve.append({"value": v, "coverage_pct": m["coverage_pct"],
                          "unknown_total": m["unknown_total"],
                          "false_wall_rate_decided_pct": m["false_wall_rate_decided_pct"],
                          "false_wall_rate_all_pct": m["false_wall_rate_all_pct"],
                          "positive_recall_decided_pct": m["positive_recall_decided_pct"],
                          "balanced_accuracy_pct": m["balanced_accuracy_pct"],
                          "accuracy_all_pct": m["accuracy_all_pct"],
                          "auc": res["separation_auc"]})
        sweep[feat] = curve

    payload = {
        "_about": "Phase 6. The object side is frozen at Phase 3 (SAM mask + production "
                  "wall_contact). The ONLY change is which fitted planes count as "
                  "walls, decided by declared geometric floors; when none survive the "
                  "production function returns UNKNOWN, as it always could.",
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "control_reproduction": control,
        "planes": {"total": total_planes, "usable_before_gate": usable_planes},
        "features_per_image": features_json,
        "selected_plane_features_phase3": selected,
        "feature_distributions": dist,
        "manual_classes": {"source": CLASSES.name if classes else "none",
                           "assignments": classes,
                           "counts": {c: len(v) for c, v in by_class.items()},
                           "distributions": class_dist},
        "operating_points": [g.__dict__ for g in OPERATING_POINTS],
        "results": results,
        "phase5_diagnostic_040": p5,
        "selection_analysis": {**{k: selection_summary(v) for k, v in results.items()},
                               p5["label"]: selection_summary(p5)},
        "contaminant_analysis": contaminants,
        "wrong_side": {k: {"cases_with_surviving_far_side_plane": v["far_side_survivor_cases"],
                           "count": len(v["far_side_survivor_cases"])}
                       for k, v in list(results.items()) + [(p5["label"], p5)]},
        "oracle_subset_with_gate": oracle_gated,
        "threshold_sweep_diagnostic": {
            "note": "DIAGNOSTIC ONLY. One feature at a time; reported as a curve, "
                    "never selected from.", **sweep},
        "phase3_baseline_full48": {"metrics": variants["B_sam_nearest"]["metrics"]["all"],
                                   "separation_auc": variants["B_sam_nearest"]["separation_auc"]},
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    b = variants["B_sam_nearest"]["metrics"]["all"]
    print(f"  Phase 3 base    fw={b['false_wall_rate_decided_pct']}% pos-rec="
          f"{b['positive_recall_decided_pct']}% balacc={b['balanced_accuracy_pct']}% "
          f"unk=0 cov=100")
    for name, res in list(results.items()) + [(p5["label"], p5)]:
        m = res["metrics"]["all"]
        print(f"  {name:36} fw={m['false_wall_rate_decided_pct']}% "
              f"(all {m['false_wall_rate_all_pct']}%) pos-rec="
              f"{m['positive_recall_decided_pct']}% balacc={m['balanced_accuracy_pct']}% "
              f"AUC={res['separation_auc']} unk={m['unknown_total']}/48 "
              f"cov={m['coverage_pct']}% acc_all={m['accuracy_all_pct']}%")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

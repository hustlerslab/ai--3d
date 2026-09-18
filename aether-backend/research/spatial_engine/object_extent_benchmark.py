"""Spatial engine Phase 7: object -> wall distance from catalogue-grounded extent.

    python -u research/spatial_engine/object_extent_benchmark.py

Research only. Reads production modules read-only; nothing in `app/` imports this.

THE WALL SIDE IS FROZEN. Every method here runs against the Phase 6 permissive
gate (enclosure >= 0.80, floor_band <= 0.75) and the 0.12 m threshold. The
frozen baseline is that gate with the Phase 3 visible-surface statistic:
1/31/2/10, 4 UNKNOWN. It is re-run first and the script aborts if it drifts.

THE OBJECT SIDE IS THE VARIABLE. Four ways of turning a SAM mask into a wall
distance, on the same 48 cases:

    visible               nearest visible surface        Phase 3/6 baseline
    catalogue_wallnormal  catalogue dims, orientation hypotheses along the
                          selected wall's normal           PRIMARY
    catalogue_pca         catalogue dims, orientation from the visible points'
                          principal axis (Phase 5's construction, catalogue
                          dims instead of hand ones)      SECONDARY
    family_default        the same as PRIMARY but with generic family sizes
                          instead of the specific asset   DIAGNOSTIC

If family_default matches the primary, the specific dimensions are not what
matters; if it is worse, they are.

NO GROUND-TRUTH EXTENT EXISTS. Rear-extent error and footprint IoU are reported
against the Phase 5 MANUAL ORACLE on its 26 cases, and labelled as agreement
with a manual estimate, never as accuracy against truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence import vocab as V                               # noqa: E402
from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    auc, gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.object_extent import (                   # noqa: E402
    AssetSpatialMetadata, SOURCE_CONFIDENCE, extent_wall_contact,
    resolve_asset_metadata)
from research.spatial_engine.oracle_geometry import (                 # noqa: E402
    OracleObjectGeometry, load_measurements, oracle_wall_contact, place)
from research.spatial_engine.rear_extent_benchmark import (           # noqa: E402
    build_geometry, distribution, object_bucket, threshold_sweep, with_f1)
from research.spatial_engine.segmentation_grounding import (          # noqa: E402
    Sam2Grounder, is_open_structure)
from research.spatial_engine.wall_quality import (                    # noqa: E402
    WallQualityGate, extract_wall_features, gated_room)

OUT = HERE / "object_extent_results.json"
PHASE_6 = HERE / "wall_quality_results.json"

#: FROZEN. The Phase 6 permissive operating point, verbatim.
PHASE6_PERMISSIVE = WallQualityGate(name="phase6_permissive",
                                    min_enclosure_fraction=0.80,
                                    max_floor_band_fraction=0.75)
PHASE6_BASELINE = {"tp": 1, "tn": 31, "fp": 2, "fn": 10, "unknown_total": 4}

NINE_FALSE_WALLS = ["s07.bar_stool.0", "s05.armchair.0", "s16.chair.0", "s02.ottoman.0",
                    "s07.bar_stool.1", "s17.chair.0", "s09.chair.0", "s01.armchair.0",
                    "s17.chair.2"]
FIVE_MISSED_POSITIVES = ["preserved.living_room_a.sofa.1", "preserved.living_room_b.tv_unit.0",
                         "preserved.master_bedroom.bed.0",
                         "preserved.master_bedroom.bedside_table.0",
                         "preserved.master_bedroom.bedside_table.1"]

TAXONOMY = ["PERCEPTION_FAILURE", "ROOM_GEOMETRY_FAILURE", "FLOOR_FAILURE", "WALL_FAILURE",
            "OBJECT_EXTENT_FAILURE", "ASSET_FAILURE", "GROUNDING_FAILURE",
            "RELATION_FAILURE", "CONSTRAINT_FAILURE", "COLLISION_FAILURE",
            "BLENDER_EXECUTION_FAILURE", "VALIDATION_FAILURE", "AMBIGUITY", "UNKNOWN"]


def row_base(case: dict) -> dict:
    return {"case_id": case["case_id"], "scene_id": case["scene_id"],
            "image_id": case["image"], "source": case["source_domain"],
            "object_id": case["object_id"], "object_type": case["object_type"],
            "object_bucket": object_bucket(case["object_type"]),
            "category": case["category"],
            "open_structure": is_open_structure(case["object_type"]),
            "ground_truth_against_wall": case["truth"]}


def finish(rows: list, label: str) -> dict:
    measured = [r for r in rows if r["wall_distance"] is not None]
    pos = [r["wall_distance"] for r in measured if r["ground_truth_against_wall"]]
    neg = [r["wall_distance"] for r in measured if not r["ground_truth_against_wall"]]
    m = with_f1(summarise(rows))
    m["unknown_total"] = sum(1 for r in rows if r["predicted_against_wall"] is None)
    m["unknown_rate_all_pct"] = round(100.0 * m["unknown_total"] / len(rows), 1)
    m["accuracy_all_pct"] = round(100.0 * (m["tp"] + m["tn"]) / len(rows), 1)

    def sub(pred):
        return with_f1(summarise([r for r in rows if pred(r)]))

    by_type = {}
    for b in sorted({r["object_bucket"] for r in rows}):
        by_type[b] = with_f1(summarise([r for r in rows if r["object_bucket"] == b]))
    return {"label": label,
            "metrics": {"all": m,
                        "generated": sub(lambda r: r["source"] == "generated"),
                        "historical": sub(lambda r: r["source"] == "historical"),
                        "category_A": sub(lambda r: r["category"] == "A"),
                        "category_B": sub(lambda r: r["category"] == "B"),
                        "open_structure": sub(lambda r: r["open_structure"]),
                        "solid": sub(lambda r: not r["open_structure"])},
            "by_object_type": by_type,
            "separation_auc": auc(pos, neg),
            "distance_distribution": {"positives": distribution(pos),
                                      "negatives": distribution(neg)},
            "unknown_cases": [r["case_id"] for r in rows if r["predicted_against_wall"] is None],
            "per_case": rows,
            "failures": [r["case_id"] for r in rows if r["correct"] is False]}


def classify_failure(r: dict, meta: AssetSpatialMetadata, floor_suspect: bool) -> str:
    """The brief's taxonomy, applied to one wrong or abstained decision."""
    if r["correct"] is True:
        return "NONE"
    if r["predicted_against_wall"] is None:
        reason = r.get("failure_reason") or ""
        if "no wall survived" in reason:
            return "WALL_FAILURE"
        if "no asset metadata" in reason:
            return "ASSET_FAILURE"
        if "exceeds every catalogue" in reason:
            # a span more than double any dimension is a bleeding mask, not an
            # extent estimate that missed
            m_ = re.search(r"visible span ([\d.]+) m", reason)
            span = float(m_.group(1)) if m_ else 0.0
            return ("PERCEPTION_FAILURE"
                    if span > 2.0 * max(meta.depth_m, meta.width_m, 0.01)
                    else "OBJECT_EXTENT_FAILURE")
        if "object points" in reason:
            return "PERCEPTION_FAILURE"
        return "UNKNOWN"
    if floor_suspect:
        return "FLOOR_FAILURE"
    if meta.source == "family_default":
        return "ASSET_FAILURE"
    if r.get("borderline"):
        return "AMBIGUITY"
    if r.get("orientation") == "visible_only":
        return "OBJECT_EXTENT_FAILURE"
    return "OBJECT_EXTENT_FAILURE" if r["ground_truth_against_wall"] else "GROUNDING_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}\n", flush=True)

    t0 = time.perf_counter()
    grounder = Sam2Grounder()
    grounder.load()
    masks = {c["case_id"]: grounder.segment(ROOT / c["image"], c["bbox"]).mask for c in cases}
    grounder.unload()
    geometry, boxes_by_image = build_geometry(cases, masks)
    perception_s = round(time.perf_counter() - t0, 1)

    exclude, features, gated, quality, floor_suspect = {}, {}, {}, {}, {}
    for key, (pm, room) in geometry.items():
        ex = np.zeros((pm.height, pm.width), dtype=bool)
        for box in boxes_by_image[key]:
            ex |= P.mask_from_box(pm.height, pm.width, box)
        exclude[key] = ex
        features[key] = extract_wall_features(pm, room, ex)
        gated[key], _rej = gated_room(room, features[key], PHASE6_PERMISSIVE)
        quality[key] = {f.wall_index: f.enclosure_fraction for f in features[key]
                        if f.enclosure_fraction is not None}
        # Phase 6 found kitchens whose "floor" is the countertop: the camera sits
        # under 0.9 m above it. Recorded per image, never used to decide.
        if room.ok:
            up = np.asarray(room.up)
            fl = room.floor.plane
            s = 1.0 if float(np.dot(fl.normal, up)) > 0 else -1.0
            cam_h = float(s * fl.signed_distance(np.zeros((1, 3)))[0])
        else:
            cam_h = float("nan")
        floor_suspect[key] = bool(cam_h < 0.9)

    # -- metadata coverage ------------------------------------------------
    t1 = time.perf_counter()
    meta = {c["case_id"]: resolve_asset_metadata(c["object_type"]) for c in cases}
    meta_ms = round(1000.0 * (time.perf_counter() - t1) / len(cases), 3)
    coverage = {"by_source": {}, "per_type": {}}
    for c in cases:
        m = meta[c["case_id"]]
        coverage["by_source"][m.source] = coverage["by_source"].get(m.source, 0) + 1
        coverage["per_type"].setdefault(c["object_type"], {
            "canonical": m.canonical_type, "source": m.source,
            "dims_wxhxd_m": [m.width_m, m.height_m, m.depth_m],
            "placement_class": m.placement_class, "confidence": m.confidence,
            "n_records": m.n_records, "depth_spread_m": m.dims_spread_m,
            "notes": m.notes})

    # -- baseline: Phase 6 permissive with the visible statistic -----------
    def run_visible() -> list:
        rows = []
        for c in cases:
            pm, _ = geometry[c["image"]]
            mask = masks[c["case_id"]]
            if not mask.any():
                mask = P.mask_from_box(pm.height, pm.width, c["bbox"])
            ct = P.wall_contact(pm, gated[c["image"]], mask)
            pred = None if ct.decision is P.Decision.UNKNOWN else ct.decision is P.Decision.YES
            rows.append({**row_base(c), "predicted_against_wall": pred,
                         "decision": ct.decision.value,
                         "correct": (pred == c["truth"]) if pred is not None else None,
                         "wall_distance": ct.distance, "wall_index": ct.wall_index,
                         "decision_confidence": None, "orientation": None,
                         "failure_reason": ct.failure_reason})
        return rows

    visible = finish(run_visible(), "visible surface + Phase 6 permissive (FROZEN baseline)")
    vm = visible["metrics"]["all"]
    reproduced = all(vm[k] == v for k, v in PHASE6_BASELINE.items())
    control = {"phase6_permissive_stored": PHASE6_BASELINE,
               "measured": {k: vm[k] for k in PHASE6_BASELINE}, "reproduced": reproduced}
    if PHASE_6.is_file():
        prev = {r["case_id"]: r for r in json.loads(PHASE_6.read_text(encoding="utf-8"))
                ["results"]["permissive"]["per_case"]}
        control["per_case_drift"] = [r["case_id"] for r in visible["per_case"]
                                     if r["case_id"] in prev
                                     and r["decision"] != prev[r["case_id"]]["decision"]]
    print(f"  Phase 6 permissive reproduced: {reproduced}", flush=True)
    if not reproduced:
        OUT.write_text(json.dumps({"_about": "Phase 7 ABORTED: frozen baseline drifted",
                                   "control_reproduction": control}, indent=2,
                                  default=str), encoding="utf-8")
        return 1

    # -- catalogue methods ------------------------------------------------
    def run_extent(method: str, force_family: bool = False,
                   orientation_rule: str = "closest") -> tuple:
        rows, extents, timings = [], {}, []
        for c in cases:
            pm, _ = geometry[c["image"]]
            mask = masks[c["case_id"]]
            if not mask.any():
                mask = P.mask_from_box(pm.height, pm.width, c["bbox"])
            m = meta[c["case_id"]]
            if force_family:
                fam = V.FAMILY_DEFAULTS.get(V.family_for(m.canonical_type, m.canonical_type))
                if fam:
                    (w, h, d), mount, _ = fam
                    m = AssetSpatialMetadata(m.semantic_type, m.canonical_type, w, h, d, mount,
                                             m.placement_class, "family_default",
                                             SOURCE_CONFIDENCE["family_default"])
            t = time.perf_counter()
            rear = None
            if method == "catalogue_pca":
                o = OracleObjectGeometry(case_id=c["case_id"], object_type=c["object_type"],
                                         width_m=m.width_m, depth_m=m.depth_m,
                                         height_m=m.height_m, uncertainty_m=0.05,
                                         notes="catalogue", source=m.source)
                pts = pm.points[mask & pm.valid]
                place(o, pts, geometry[c["image"]][1])
                oc = oracle_wall_contact(o, pm, gated[c["image"]], sanity_gate=False)
                dec, dist, wi = oc.decision, oc.distance, oc.wall_index
                conf, orient, reason, border = None, "pca", oc.failure_reason, oc.borderline
                if not m.known:
                    dec, dist, wi, reason = P.Decision.UNKNOWN, None, None, "no asset metadata"
            else:
                ex = extent_wall_contact(c["case_id"], pm, gated[c["image"]], mask, m,
                                         wall_quality=quality[c["image"]], method=method,
                                         orientation_rule=orientation_rule)
                extents[c["case_id"]] = ex
                dec, dist, wi = ex.decision, ex.distance_m, ex.wall_index
                conf, orient, reason = ex.decision_confidence, ex.orientation, ex.failure_reason
                rear = ex.physical_rear_m
                border = (dist is not None and abs(dist - P.WALL_CONTACT_DISTANCE_M)
                          < ex.uncertainty_m)
            timings.append(time.perf_counter() - t)
            pred = None if dec is P.Decision.UNKNOWN else dec is P.Decision.YES
            row = {**row_base(c), "asset_source": m.source, "asset_canonical": m.canonical_type,
                   "asset_dims_wxhxd_m": [m.width_m, m.height_m, m.depth_m],
                   "asset_confidence": m.confidence,
                   "predicted_against_wall": pred, "decision": dec.value,
                   "correct": (pred == c["truth"]) if pred is not None else None,
                   "wall_distance": dist, "wall_index": wi, "physical_rear_m": rear,
                   "decision_confidence": conf, "orientation": orient,
                   "borderline": border, "failure_reason": reason,
                   "evidence": (extents[c["case_id"]].evidence
                                if c["case_id"] in extents else [])}
            row["failure_category"] = classify_failure(row, m, floor_suspect[c["image"]])
            rows.append(row)
        lat = {"per_case_ms_median": round(1000 * float(np.median(timings)), 3),
               "per_case_ms_p95": round(1000 * float(np.percentile(timings, 95)), 3),
               "total_s": round(sum(timings), 3)}
        return rows, lat

    methods, latency = {}, {}
    for name, ff, rule in (("catalogue_wallnormal", False, "closest"),
                           ("catalogue_depthfirst", False, "depth_first"),
                           ("catalogue_pca", False, "closest"),
                           ("family_default", True, "closest")):
        rows, lat = run_extent(name, ff, rule)
        methods[name] = finish(rows, name)
        latency[name] = lat
        m = methods[name]["metrics"]["all"]
        print(f"  {name:22} TP/TN/FP/FN={m['tp']}/{m['tn']}/{m['fp']}/{m['fn']} "
              f"unk={m['unknown_total']} fw={m['false_wall_rate_decided_pct']}% "
              f"posrec={m['positive_recall_decided_pct']}% balacc={m['balanced_accuracy_pct']}% "
              f"AUC={methods[name]['separation_auc']} cov={m['coverage_pct']}%", flush=True)
    methods["visible"] = visible

    # -- tracked cases ----------------------------------------------------
    per = {k: {r["case_id"]: r for r in v["per_case"]} for k, v in methods.items()}

    def track(ids: list) -> list:
        out = []
        for cid in ids:
            v, w = per["visible"][cid], per["catalogue_wallnormal"][cid]
            df = per["catalogue_depthfirst"][cid]
            if w["correct"] is True and v["correct"] is not True:
                verdict = "repaired"
            elif w["correct"] is True:
                verdict = "unchanged correct"
            elif w["predicted_against_wall"] is None:
                verdict = "became UNKNOWN"
            elif w["correct"] is False and v["correct"] is False:
                verdict = "persistent"
            else:
                verdict = "newly wrong"
            out.append({"case_id": cid, "object_type": v["object_type"],
                        "label": v["ground_truth_against_wall"],
                        "visible_m": v["wall_distance"], "visible": v["decision"],
                        "catalogue_m": w["wall_distance"], "catalogue": w["decision"],
                        "physical_rear_m": w["physical_rear_m"],
                        "orientation": w["orientation"], "asset_source": w["asset_source"],
                        "asset_depth_m": w["asset_dims_wxhxd_m"][2],
                        "confidence": w["decision_confidence"], "verdict": verdict,
                        "depthfirst_m": df["wall_distance"], "depthfirst": df["decision"],
                        "depthfirst_correct": df["correct"]})
        return out

    # -- agreement with the Phase 5 manual oracle (a proxy, not truth) ------
    oracle = load_measurements()
    agree = []
    for c in cases:
        if c["case_id"] not in oracle:
            continue
        w = per["catalogue_wallnormal"][c["case_id"]]
        o = oracle[c["case_id"]]
        cat_d = w["asset_dims_wxhxd_m"][2]
        agree.append({"case_id": c["case_id"], "manual_depth_m": o.depth_m,
                      "catalogue_depth_m": cat_d,
                      "depth_diff_m": round(cat_d - o.depth_m, 3),
                      "manual_uncertainty_m": o.uncertainty_m,
                      "within_manual_uncertainty": abs(cat_d - o.depth_m) <= o.uncertainty_m})
    diffs = [a["depth_diff_m"] for a in agree]
    oracle_agreement = {
        "note": "Agreement between catalogue depth and the Phase 5 MANUAL estimate on its "
                "26 cases. The manual estimate is not ground truth; this measures whether "
                "two independent sources of the same quantity agree.",
        "n": len(agree),
        "depth_diff_m": distribution(diffs),
        "abs_depth_diff_median_m": round(float(np.median(np.abs(diffs))), 3) if diffs else None,
        "within_manual_uncertainty": sum(1 for a in agree if a["within_manual_uncertainty"]),
        "per_case": agree}

    prim = methods["catalogue_wallnormal"]
    tax = {t: [r["case_id"] for r in prim["per_case"] if r["failure_category"] == t]
           for t in TAXONOMY}
    tax = {k: v for k, v in tax.items() if v}
    tax_df = {t: [r["case_id"] for r in methods["catalogue_depthfirst"]["per_case"]
                  if r["failure_category"] == t] for t in TAXONOMY}
    tax_df = {k: v for k, v in tax_df.items() if v}

    payload = {
        "_about": "Phase 7. Wall side FROZEN at the Phase 6 permissive gate and 0.12 m. "
                  "The variable is the object side: nearest visible surface (baseline) "
                  "vs catalogue-grounded physical extent. No labels consulted anywhere; "
                  "dimensions come from the asset registry, the built-in catalogue, or a "
                  "family default, in that order, each with its own confidence.",
        "config": {"wall_gate": PHASE6_PERMISSIVE.__dict__,
                   "wall_contact_distance_m": P.WALL_CONTACT_DISTANCE_M,
                   "span_percentiles": [5, 95], "span_tolerance_m": 0.10,
                   "span_unknown_m": 0.50, "source_confidence": SOURCE_CONFIDENCE,
                   "production_code_changed": "none"},
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "control_reproduction": control,
        "metadata_coverage": coverage,
        "floor_suspect_images": [k for k, v in floor_suspect.items() if v],
        "methods": methods,
        "comparison": {
            "order": ["visible", "catalogue_wallnormal", "catalogue_depthfirst",
                      "catalogue_pca", "family_default"],
            "note": "catalogue_wallnormal uses the PRE-DECLARED orientation rule and is "
                    "the primary result; catalogue_depthfirst is a POST-HOC physical prior "
                    "and must be confirmed on new data before it is preferred.",
            **{metric: [methods[k]["metrics"]["all"].get(metric)
                        for k in ("visible", "catalogue_wallnormal", "catalogue_depthfirst",
                                  "catalogue_pca", "family_default")]
               for metric in ("tp", "tn", "fp", "fn", "unknown_total", "coverage_pct",
                              "false_wall_rate_decided_pct", "false_wall_rate_all_pct",
                              "no_recall_decided_pct", "positive_recall_decided_pct",
                              "precision_pct", "f1_pct", "balanced_accuracy_pct",
                              "accuracy_all_pct")},
            "separation_auc": [methods[k]["separation_auc"] for k in
                               ("visible", "catalogue_wallnormal", "catalogue_depthfirst",
                                "catalogue_pca", "family_default")]},
        "nine_false_walls": track(NINE_FALSE_WALLS),
        "five_missed_positives": track(FIVE_MISSED_POSITIVES),
        "all_cases_tracked": track([c["case_id"] for c in cases]),
        "oracle_agreement": oracle_agreement,
        "failure_taxonomy_primary": tax,
        "failure_taxonomy_depthfirst_posthoc": tax_df,
        "latency": {"perception_sam_moge_total_s": perception_s,
                    "metadata_resolution_ms_per_case": meta_ms, **latency,
                    "note": "extent computation is CPU-only numpy; no model, no VRAM"},
        "threshold_sweep_diagnostic": {
            "note": "DIAGNOSTIC ONLY; the gate used 0.12 m.",
            "catalogue_wallnormal": threshold_sweep(prim),
            "visible": threshold_sweep(visible)},
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    for k in ("visible", "catalogue_wallnormal", "catalogue_depthfirst", "catalogue_pca",
              "family_default"):
        m = methods[k]["metrics"]["all"]
        print(f"  {k:22} TP/TN/FP/FN={m['tp']}/{m['tn']}/{m['fp']}/{m['fn']} "
              f"unk={m['unknown_total']} fw={m['false_wall_rate_decided_pct']}% "
              f"NOrec={m['no_recall_decided_pct']}% posrec={m['positive_recall_decided_pct']}% "
              f"F1={m['f1_pct']}% balacc={m['balanced_accuracy_pct']}% "
              f"AUC={methods[k]['separation_auc']} acc_all={m['accuracy_all_pct']}%")
    print(f"  failure taxonomy (primary): { {k: len(v) for k, v in tax.items()} }")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

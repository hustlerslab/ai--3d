"""Spatial engine Phase 1: can geometry answer the wall question better than a VLM?

    python -u research/spatial_engine/geometric_wall_contact.py

Research only. Imports `app.spatial.planes` (which nothing in production imports)
and writes only into research/spatial_engine/. The live pipeline is untouched.

THE THESIS UNDER TEST. Phases 1c-1h asked qwen2.5vl whether a piece was against a
wall, six ways, and the best result was 14.1% false-wall on 32 objects. This runs
the same question through geometry instead: depth -> point map -> RANSAC floor ->
RANSAC walls -> distance from the object's rear surface to the nearest wall plane.
No model is asked anything. The pipeline may answer UNKNOWN and frequently should.

THE DATASET, AND ONE ADDITION I AM FLAGGING. The brief says use the Phase 1g/1h
dataset, and it is used exactly as annotated - no label changed, no case dropped,
no image cherry-picked. But that dataset's 32 negatives are ALL generated imagery
and its 11 positives are ALL historical, so on its own it cannot answer the
"historical vs generated" question the brief also asks: there are no historical
negatives in it.

So the 5 historical negatives from `tests/fixtures/relationship_benchmark.json`
are included as well. They are not new labels - they are the same hand-verified
negatives Phases 1c-1f scored against, and adding them restores exactly the
16-case historical set Phase 1e/1f/1h measured. That makes the comparison
like-for-like on both halves. Every row records its `source_domain`, and no
aggregate mixes them silently.

UNKNOWN IS NOT A FAILURE AND IS NEVER FOLDED INTO NO. Two false-wall rates are
reported throughout: one over the cases that got a decision, one over all
negatives with UNKNOWN counted against us. A method that abstains on half the
set and is perfect on the rest has not solved the problem, and the second number
is what stops that looking like success.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402

DATASET = ROOT / "research" / "phase1g" / "dataset.json"
FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
PHASE_1H = ROOT / "research" / "phase1h" / "results.json"
OUT_JSON = HERE / "geometric_wall_contact_results.json"

WIDTH, HEIGHT = 704, 448
DEPTH_REPO = "depth-anything/Depth-Anything-V2-Small-hf"


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
    """The Phase 1g cases plus the 5 historical negatives, each tagged by domain."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = []
    for c in data["cases"]:
        cases.append({
            "case_id": c["case_id"], "scene_id": c["scene_id"],
            "image": c["image_path"], "object_id": c["object_id"],
            "object_type": c["object_type"], "bbox": c["bbox"],
            "category": c["category"],
            "truth": c["ground_truth_against_wall"],
            "source_domain": ("generated" if c["origin"] == "phase1g"
                              else "historical"),
            "origin": c["origin"],
        })

    # The historical negatives, unchanged, from the fixture Phases 1c-1f used.
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for room in fixture["rooms"]:
        by_id = {o["id"]: o for o in room["objects"]}
        for truth in room.get("binary_relations", []):
            if (truth["chain"] == "against" and truth["verdict"] == "TRUE"
                    and truth.get("wall") is False):
                obj = by_id[truth["source"]]
                cases.append({
                    "case_id": f"hist_neg.{obj['id']}",
                    "scene_id": f"hist_{room['room_key']}",
                    "image": room["image"], "object_id": obj["id"],
                    "object_type": obj["type"], "bbox": obj["bbox"],
                    # Category as annotated in Phase 1f's audit trail.
                    "category": ("A" if obj["type"] in ("ottoman", "coffee_table")
                                 else "B"),
                    "truth": False, "source_domain": "historical",
                    "origin": "phase1c_fixture",
                })
    return cases


def build_depth():
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    processor = AutoImageProcessor.from_pretrained(DEPTH_REPO)
    model = AutoModelForDepthEstimation.from_pretrained(DEPTH_REPO).to("cuda").eval()
    return model, processor


def disparity_for(model, processor, image_path: Path) -> np.ndarray:
    """Depth Anything's relative inverse depth, resampled back to the image grid.

    The processor resizes internally (a 704x448 input comes back 518x812), so the
    prediction is interpolated back before anything geometric touches it - a box
    in image pixels must index the same pixels in the depth map.
    """
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB").resize((WIDTH, HEIGHT))
    inputs = processor(images=image, return_tensors="pt").to("cuda")
    with torch.no_grad():
        predicted = model(**inputs).predicted_depth
    resized = torch.nn.functional.interpolate(
        predicted.unsqueeze(1), size=(HEIGHT, WIDTH),
        mode="bicubic", align_corners=False).squeeze()
    return resized.detach().float().cpu().numpy()


def summarise(subset: list[dict]) -> dict:
    negatives = [r for r in subset if r["ground_truth_against_wall"] is False]
    positives = [r for r in subset if r["ground_truth_against_wall"] is True]
    decided_neg = [r for r in negatives if r["predicted_against_wall"] is not None]
    decided_pos = [r for r in positives if r["predicted_against_wall"] is not None]

    tn = sum(1 for r in decided_neg if r["predicted_against_wall"] is False)
    fp = sum(1 for r in decided_neg if r["predicted_against_wall"] is True)
    tp = sum(1 for r in decided_pos if r["predicted_against_wall"] is True)
    fn = sum(1 for r in decided_pos if r["predicted_against_wall"] is False)
    unknown_neg = len(negatives) - len(decided_neg)
    unknown_pos = len(positives) - len(decided_pos)
    decided = len(decided_neg) + len(decided_pos)

    def pct(a, b):
        return None if not b else round(100.0 * a / b, 1)

    return {
        "cases": len(subset), "negatives": len(negatives),
        "positives": len(positives),
        "tn": tn, "fp": fp, "tp": tp, "fn": fn,
        "unknown_negatives": unknown_neg, "unknown_positives": unknown_pos,
        "unknown_rate_pct": pct(unknown_neg + unknown_pos, len(subset)),
        "unknown_rate_negatives_pct": pct(unknown_neg, len(negatives)),
        # Of the negatives that got an answer.
        "false_wall_rate_decided_pct": pct(fp, len(decided_neg)),
        "false_wall_ci95_decided": wilson(fp, len(decided_neg)),
        # Of ALL negatives, counting UNKNOWN against us. The honest one.
        "false_wall_rate_all_pct": pct(fp, len(negatives)),
        "no_recall_decided_pct": pct(tn, len(decided_neg)),
        "no_recall_ci95_decided": wilson(tn, len(decided_neg)),
        "no_recall_all_pct": pct(tn, len(negatives)),
        "positive_recall_decided_pct": pct(tp, len(decided_pos)),
        "precision_pct": pct(tp, tp + fp),
        "accuracy_decided_pct": pct(tn + tp, decided) if decided else None,
        "coverage_pct": pct(decided, len(subset)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fov", type=float, default=P.DEFAULT_FOV_DEG)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]

    config = {
        "depth_model": DEPTH_REPO,
        "depth_licence": "Apache-2.0 (Small is the only Apache-2.0 size)",
        "resolution": f"{WIDTH}x{HEIGHT}",
        "fov_deg": args.fov,
        "object_representation": "annotated bounding box (no segmentation; the "
                                 "brief says not to make SAM a prerequisite)",
        "thresholds": {
            "WALL_CONTACT_DISTANCE_M": P.WALL_CONTACT_DISTANCE_M,
            "WALL_CONTACT_RELATIVE_TOLERANCE": P.WALL_CONTACT_RELATIVE_TOLERANCE,
            "MIN_WALL_INLIER_FRACTION": P.MIN_WALL_INLIER_FRACTION,
            "MIN_OBJECT_GEOMETRIC_CONFIDENCE": P.MIN_OBJECT_GEOMETRIC_CONFIDENCE,
            "MIN_WALL_EXTENT_FRACTION": P.MIN_WALL_EXTENT_FRACTION,
            "WALL_VERTICALITY_TOLERANCE_DEG": P.WALL_VERTICALITY_TOLERANCE_DEG,
            "MANHATTAN_SNAP_TOLERANCE_DEG": P.MANHATTAN_SNAP_TOLERANCE_DEG,
            "RANSAC_ITERATIONS": P.RANSAC_ITERATIONS,
            "RANSAC_SEED": P.RANSAC_SEED,
        },
    }
    print(f"cases: {len(cases)}  "
          f"(negatives {sum(1 for c in cases if not c['truth'])}, "
          f"positives {sum(1 for c in cases if c['truth'])})")
    print(f"domains: {dict(Counter(c['source_domain'] for c in cases))}")
    print(f"depth: {DEPTH_REPO}   fov {args.fov} deg\n", flush=True)

    model, processor = build_depth()

    # One room fit per IMAGE, reused across every object in it: the room does not
    # change between objects, and refitting would be both slower and a source of
    # spurious per-object variation.
    rooms: dict[str, tuple] = {}
    rows, timings = [], []

    # Every annotated box in each image, so furniture pixels can be kept out of
    # the wall fit. Without this the first run of this experiment fitted "walls"
    # straight through sofas and counters - a sofa back is a large planar surface
    # and RANSAC has no idea it is furniture - and every object then reported a
    # wall at distance zero. In production these boxes come from the detector;
    # here they are the dataset's own annotations, used only to mask, never to
    # decide.
    boxes_by_image: dict[str, list] = {}
    for case in cases:
        boxes_by_image.setdefault(case["image"], []).append(case["bbox"])

    for case in cases:
        image_key = case["image"]
        if image_key not in rooms:
            started = time.perf_counter()
            disparity = disparity_for(model, processor, ROOT / image_key)
            pointmap = P.unproject(disparity, fov_deg=args.fov)
            exclude = np.zeros((pointmap.height, pointmap.width), dtype=bool)
            for box in boxes_by_image[image_key]:
                exclude |= P.mask_from_box(pointmap.height, pointmap.width, box)
            room = P.fit_room(pointmap, exclude=exclude)
            rooms[image_key] = (pointmap, room, round(time.perf_counter() - started, 2))
            usable = [w for w in room.walls if not w.uncertain]
            print(f"  room {image_key.split('/')[-1]:34} floor_ok="
                  f"{bool(room.floor and room.floor.ok)} walls={len(room.walls)} "
                  f"usable={len(usable)} scale={room.scene_scale:.3f} "
                  f"{rooms[image_key][2]}s", flush=True)
        pointmap, room, _seconds = rooms[image_key]

        started = time.perf_counter()
        mask = P.mask_from_box(pointmap.height, pointmap.width, case["bbox"])
        contact = P.wall_contact(pointmap, room, mask)
        elapsed = round(time.perf_counter() - started, 4)
        timings.append(elapsed)

        predicted = (None if contact.decision is P.Decision.UNKNOWN
                     else contact.decision is P.Decision.YES)
        correct = (predicted is not None and predicted == case["truth"])
        row = {
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_id": case["object_id"], "object_type": case["object_type"],
            "category": case["category"], "source_domain": case["source_domain"],
            "ground_truth_against_wall": case["truth"],
            "predicted_against_wall": predicted,
            "decision": contact.decision.value,
            "correct": correct if predicted is not None else None,
            "wall_distance": contact.distance,
            "relative_distance": contact.relative_distance,
            "wall_index": contact.wall_index,
            "wall_plane_confidence": contact.wall_confidence,
            "object_geometry_confidence": contact.object_geometric_confidence,
            "depth_coverage": contact.depth_coverage,
            "threshold_used": contact.threshold_used,
            "metric_source": contact.metric_source.value,
            "failure_reason": contact.failure_reason,
            "evidence": (contact.evidence.__dict__ if contact.evidence else None),
            "seconds": elapsed,
        }
        rows.append(row)
        mark = "ok " if correct else ("  ?" if predicted is None else "  x")
        print(f"  {mark} [{case['source_domain'][:4]}/{case['category'] or 'P'}] "
              f"{case['case_id']:34} -> {contact.decision.value:7} "
              f"(truth {case['truth']}) rel={contact.relative_distance} "
              f"{contact.failure_reason or ''}", flush=True)

    metrics = {
        "all": summarise(rows),
        "generated": summarise([r for r in rows if r["source_domain"] == "generated"]),
        "historical": summarise([r for r in rows if r["source_domain"] == "historical"]),
        "category_A": summarise([r for r in rows if r["category"] == "A"]),
        "category_B": summarise([r for r in rows if r["category"] == "B"]),
    }

    per_scene = {scene: summarise([r for r in rows if r["scene_id"] == scene])
                 for scene in sorted({r["scene_id"] for r in rows})}

    failures = [r for r in rows if r["correct"] is False]
    unknowns = [r for r in rows if r["predicted_against_wall"] is None]

    # ── diagnosis, not tuning ───────────────────────────────────────────
    # The frozen threshold above IS the result. This sweep exists to answer a
    # different question the brief asks explicitly: when it fails, is the failure
    # a mis-calibrated cut or an absent signal? Separation tells us that
    # independently of where any threshold sits. If positives and negatives
    # overlap completely, no threshold can help and the problem is upstream
    # (depth, or plane fitting); if they separate but the cut is in the wrong
    # place, the method works and the constant is wrong.
    measured = [r for r in rows if r["relative_distance"] is not None]
    pos_d = [r["relative_distance"] for r in measured
             if r["ground_truth_against_wall"]]
    neg_d = [r["relative_distance"] for r in measured
             if not r["ground_truth_against_wall"]]

    def auc(positive: list[float], negative: list[float]):
        """P(a true wall-contact scores closer than a free-standing piece).
        0.5 is no signal; 1.0 is perfect separation. Threshold-free."""
        if not positive or not negative:
            return None
        wins = sum(1 for p in positive for n in negative
                   if p < n) + 0.5 * sum(1 for p in positive for n in negative
                                         if p == n)
        return round(wins / (len(positive) * len(negative)), 4)

    sweep = []
    for threshold in (0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30):
        tn = sum(1 for d in neg_d if d > threshold)
        fp = len(neg_d) - tn
        tp = sum(1 for d in pos_d if d <= threshold)
        fn = len(pos_d) - tp
        sweep.append({
            "relative_threshold": threshold,
            "false_wall_pct": round(100.0 * fp / len(neg_d), 1) if neg_d else None,
            "no_recall_pct": round(100.0 * tn / len(neg_d), 1) if neg_d else None,
            "positive_recall_pct": round(100.0 * tp / len(pos_d), 1) if pos_d else None,
            "balanced_accuracy_pct": (
                round(50.0 * (tn / len(neg_d) + tp / len(pos_d)), 1)
                if neg_d and pos_d else None),
            "tn": tn, "fp": fp, "tp": tp, "fn": fn,
        })

    diagnosis = {
        "_about": "Diagnostic only. The frozen-threshold result above is THE "
                  "result; this says WHY it came out that way.",
        "separation_auc": auc(pos_d, neg_d),
        "positive_relative_distance": {
            "n": len(pos_d),
            "median": round(statistics.median(pos_d), 4) if pos_d else None,
            "p90": round(float(np.percentile(pos_d, 90)), 4) if pos_d else None},
        "negative_relative_distance": {
            "n": len(neg_d),
            "median": round(statistics.median(neg_d), 4) if neg_d else None,
            "p10": round(float(np.percentile(neg_d, 10)), 4) if neg_d else None},
        "scene_scale_spread": {
            "min": round(min(r.scene_scale for _, r, _ in rooms.values()), 3),
            "max": round(max(r.scene_scale for _, r, _ in rooms.values()), 3),
            "note": "a wide spread means the unprojection is unstable between "
                    "scenes, which is the affine-ambiguity distortion the module "
                    "docstring predicts and makes one relative threshold mean "
                    "different things in different rooms",
        },
        "threshold_sweep": sweep,
    }

    room_summary = {
        key: {"floor_ok": bool(room.floor and room.floor.ok),
              "floor_inlier_fraction": (round(room.floor.inlier_fraction, 4)
                                        if room.floor else None),
              "walls": len(room.walls),
              "usable_walls": sum(1 for w in room.walls if not w.uncertain),
              "scene_scale": round(room.scene_scale, 4),
              "warnings": room.warnings,
              "wall_detail": [
                  {"inlier_fraction": round(w.inlier_fraction, 4),
                   "extent_fraction": round(w.extent_fraction, 5),
                   "manhattan_residual_deg": (round(w.manhattan_residual_deg, 2)
                                              if w.manhattan_residual_deg is not None
                                              else None),
                   "residual_median": round(w.residual_median, 5),
                   "uncertain": w.uncertain, "failure_reason": w.failure_reason}
                  for w in room.walls],
              "seconds": seconds}
        for key, (pointmap, room, seconds) in rooms.items()
    }

    baseline = {}
    if PHASE_1H.is_file():
        blob = json.loads(PHASE_1H.read_text(encoding="utf-8"))["results"]
        baseline = {
            "phase_1h_7b_negatives_all": {
                "false_wall_rate_pct": blob["negatives_all"]["false_wall_rate"],
                "false_wall_ci95": blob["negatives_all"]["false_wall_ci95"],
                "no_recall_pct": blob["negatives_all"]["no_recall"],
                "unknown_rate_pct": 0.0,
                "note": "the VLM always answered; it had no UNKNOWN",
            },
            "phase_1h_category_A_false_wall": blob["category_A"]["false_wall_rate"],
            "phase_1h_category_B_false_wall": blob["category_B"]["false_wall_rate"],
        }

    report = {
        "_about": "Spatial engine Phase 1: deterministic geometric wall contact. "
                  "No model was asked for a relation. UNKNOWN is reported "
                  "separately and never folded into NO.",
        "config": config,
        "dataset": {
            "cases": len(rows),
            "negatives": sum(1 for r in rows if not r["ground_truth_against_wall"]),
            "positives": sum(1 for r in rows if r["ground_truth_against_wall"]),
            "generated": sum(1 for r in rows if r["source_domain"] == "generated"),
            "historical": sum(1 for r in rows if r["source_domain"] == "historical"),
            "scenes": len({r["scene_id"] for r in rows}),
            "images": len(rooms),
            "sources": ["research/phase1g/dataset.json (unchanged)",
                        "tests/fixtures/relationship_benchmark.json historical "
                        "negatives (unchanged)"],
        },
        "metrics": metrics,
        "per_scene": per_scene,
        "rooms": room_summary,
        "failures": failures,
        "unknowns": unknowns,
        "baseline": baseline,
        "diagnosis": diagnosis,
        "latency": {"wall_contact_median_s": round(statistics.median(timings), 5),
                    "room_fit_median_s": round(statistics.median(
                        [s for _, _, s in rooms.values()]), 2)},
        "per_case": rows,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 74)
    for name in ("all", "generated", "historical", "category_A", "category_B"):
        m = metrics[name]
        print(f"  {name:12} n={m['cases']:3} neg={m['negatives']:3} "
              f"TN{m['tn']:3} FP{m['fp']:3} UNK{m['unknown_negatives']:3}  "
              f"false-wall(decided)={m['false_wall_rate_decided_pct']}% "
              f"{m['false_wall_ci95_decided']}  "
              f"false-wall(all)={m['false_wall_rate_all_pct']}%  "
              f"unknown={m['unknown_rate_negatives_pct']}%")
    if baseline:
        b = baseline["phase_1h_7b_negatives_all"]
        print(f"\n  Phase 1h VLM baseline: false-wall {b['false_wall_rate_pct']}% "
              f"{b['false_wall_ci95']}, NO-recall {b['no_recall_pct']}%, "
              f"unknown {b['unknown_rate_pct']}%")
    print(f"\n  failures {len(failures)}   unknowns {len(unknowns)}")
    print(f"  wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Spatial engine Phase 9: object grounding benchmark.

    python -u research/spatial_engine/object_grounding_benchmark.py

Research only. Reads production modules read-only; nothing in `app/` imports this.

THE PIPELINE UNDER TEST is the composition of everything frozen so far:

    SAM 2 mask + MoGe-2 points
      -> floor hypothesis (Phase 8, do-no-harm acceptance)
      -> walls re-fitted on the accepted floor, else the fitter's walls
      -> Phase 6 permissive gate
      -> Phase 7 catalogue extent
      -> ObjectGrounding (footprint, position, depth, orientation, confidence)

NO GROUND-TRUTH POSITION EXISTS. Position error, rotation error and footprint
IoU against truth are NOT TESTED. What is measured instead, and honestly named:

    grounded rate              a candidate was produced, not UNKNOWN
    support consistency        lowest visible points within the contact band
    footprint inside room      every corner on the room side of every gated wall
    visible within footprint   the visible floor-projected points the rectangle
                               actually covers (a footprint that misses its own
                               evidence is wrong regardless of truth)
    wall-contact agreement     identical to the Phase 8 do-no-harm arm, by
                               construction; checked, not assumed
    determinism                two runs, identical positions
    latency                    CPU, per object
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
from research.spatial_engine.floor_benchmark import cam_height, contact_fraction  # noqa: E402
from research.spatial_engine.floor_candidates import (                # noqa: E402
    FLOOR_CONFIG, generate_floor_candidates, refit_walls_with_floor, select_floor)
from research.spatial_engine.metric_geometry_benchmark import (       # noqa: E402
    gpu_used_mib, load_cases, summarise, system_ram)
from research.spatial_engine.object_extent import resolve_asset_metadata  # noqa: E402
from research.spatial_engine.object_extent_benchmark import (         # noqa: E402
    PHASE6_PERMISSIVE, row_base)
from research.spatial_engine.object_grounding import (                # noqa: E402
    GROUNDING_CONFIG, ground_object)
from research.spatial_engine.rear_extent_benchmark import (           # noqa: E402
    build_geometry, distribution, with_f1)
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)
from research.spatial_engine.segmentation_grounding import Sam2Grounder  # noqa: E402
from research.spatial_engine.wall_quality import (                    # noqa: E402
    extract_wall_features, gated_room)

OUT = HERE / "object_grounding_results.json"
PHASE8_DONOHARM = {"tp": 7, "tn": 24, "fp": 2, "fn": 3, "unknown_total": 12}


def inside_room(corners: list, gated: P.RoomGeometry, pointmap: P.PointMap, tol: float) -> bool:
    centre = room_centroid(pointmap)
    scale = gated.scene_scale or pointmap.scene_scale()
    pts = np.array(corners, dtype=np.float64)
    for w in gated.walls:
        if w.uncertain or w.plane is None:
            continue
        sign, _s, _m = orient_to_room(w.plane, centre, scale)
        if sign == 0.0:
            continue
        if float((sign * w.plane.signed_distance(pts)).min()) < -tol:
            return False
    return True


def visible_coverage(g, pointmap: P.PointMap, mask: np.ndarray) -> float:
    """Fraction of the object's visible points whose projection lies inside the
    footprint rectangle, in the footprint's own 2D frame (5 cm slack)."""
    pts = pointmap.points[mask & pointmap.valid]
    if pts.shape[0] == 0 or g.footprint is None:
        return float("nan")
    along = np.asarray(g.footprint_axes["along"])
    normal = np.asarray(g.footprint_axes["normal"])
    c = np.array(g.footprint)
    a_lo, a_hi = float((c @ along).min()), float((c @ along).max())
    n_lo, n_hi = float((c @ normal).min()), float((c @ normal).max())
    a, n = pts @ along, pts @ normal
    return float(((a >= a_lo - 0.05) & (a <= a_hi + 0.05)
                  & (n >= n_lo - 0.05) & (n <= n_hi + 0.05)).mean())


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

    # -- floor (Phase 8, do-no-harm) and walls, per image -----------------
    floors, rooms, gated, quality, floor_conf, floor_log = {}, {}, {}, {}, {}, {}
    slo, shi = FLOOR_CONFIG["camera_height_soft_m"]
    for key, (pm, room) in geometry.items():
        ex = np.zeros((pm.height, pm.width), dtype=bool)
        for box in boxes_by_image[key]:
            ex |= P.mask_from_box(pm.height, pm.width, box)
        obj_masks = [masks[c["case_id"]] for c in cases if c["image"] == key]
        obj_pts = [pm.points[m & pm.valid] for m in obj_masks if int((m & pm.valid).sum()) >= 32]
        hyp = select_floor(generate_floor_candidates(pm, ex, obj_masks))
        up_b = np.asarray(room.up)
        base_h = cam_height(room.floor.plane, up_b)
        base_bad = not (slo <= base_h <= shi)
        old_c = contact_fraction(room.floor.plane, up_b, obj_pts)
        accepted = False
        if hyp.decision == "ROOM_FLOOR" and hyp.plane is not None:
            new_c = contact_fraction(hyp.plane, np.asarray(hyp.plane.normal), obj_pts)
            same = abs(hyp.camera_height_m - base_h) < 0.15
            wins = (not np.isnan(new_c) and not np.isnan(old_c) and new_c > old_c)
            accepted = (not same) and (base_bad or wins)
        if accepted:
            floors[key], rooms[key], floor_conf[key] = hyp.plane, refit_walls_with_floor(pm, ex, hyp.plane), hyp.confidence
            status = "accepted scored floor"
        elif base_bad:
            floors[key], rooms[key], floor_conf[key] = None, room, 0.0
            status = "fitter floor implausible and no accepted replacement: UNKNOWN"
        else:
            floors[key], rooms[key] = room.floor.plane, room
            floor_conf[key] = 1.0 if hyp.decision == "ROOM_FLOOR" else 0.7
            status = "fitter floor kept"
        floor_log[key] = {"status": status, "fitter_camera_height_m": round(base_h, 3),
                          "scored_decision": hyp.decision,
                          "scored_camera_height_m": hyp.camera_height_m}
        r = rooms[key]
        feats = extract_wall_features(pm, r, ex) if r.ok else []
        gated[key], _ = gated_room(r, feats, PHASE6_PERMISSIVE) if r.ok else (r, {})
        quality[key] = {f.wall_index: f.enclosure_fraction for f in feats
                        if f.enclosure_fraction is not None}

    # -- ground every case, twice for determinism ---------------------------
    rows, timings, pos_a, pos_b = [], [], {}, {}
    lo, hi = GROUNDING_CONFIG["contact_band_m"]
    for c in cases:
        pm = geometry[c["image"]][0]
        mask = masks[c["case_id"]]
        if not mask.any():
            mask = P.mask_from_box(pm.height, pm.width, c["bbox"])
        meta = resolve_asset_metadata(c["object_type"])
        kw = dict(floor_confidence=floor_conf[c["image"]])
        t = time.perf_counter()
        g = ground_object(c["case_id"], c["object_id"], pm, floors[c["image"]], gated[c["image"]],
                          quality[c["image"]], mask, meta, **kw)
        timings.append(time.perf_counter() - t)
        g2 = ground_object(c["case_id"], c["object_id"], pm, floors[c["image"]], gated[c["image"]],
                           quality[c["image"]], mask, meta, **kw)
        pos_a[c["case_id"]], pos_b[c["case_id"]] = g.room_position, g2.room_position

        wc = g.wall_contact.get("decision")
        pred = None if wc in (None, "UNKNOWN") else wc == "YES"
        grounded = g.footprint is not None
        rows.append({**row_base(c),
                     "placement_class": g.placement_class, "support": g.support,
                     "grounded": grounded, "failure_reason": g.failure_reason,
                     "failure_category": g.failure_category,
                     "room_position": g.room_position, "depth_m": g.depth_m,
                     "footprint": g.footprint, "extent_wdh_m": list(g.extent_wdh_m),
                     "floor_contact_m": g.floor_contact_m, "base_occluded": g.base_occluded,
                     "support_consistent": (g.floor_contact_m is not None
                                            and lo <= g.floor_contact_m <= hi),
                     "inside_room": (inside_room(g.footprint, gated[c["image"]], pm,
                                                 GROUNDING_CONFIG["inside_room_tolerance_m"])
                                     if grounded else None),
                     "visible_coverage": (round(visible_coverage(g, pm, mask), 3)
                                          if grounded else None),
                     "orientation_candidates": g.orientation_candidates,
                     "orientation_known": bool(g.orientation_candidates
                                               and g.orientation_candidates[0].get("wall_index")
                                               is not None),
                     "wall_contact": g.wall_contact,
                     "predicted_against_wall": pred, "decision": wc or "UNKNOWN",
                     "correct": (pred == c["truth"]) if pred is not None else None,
                     "wall_distance": g.wall_contact.get("distance_m"),
                     "confidence": g.confidence, "evidence": g.evidence})

    grounded_rows = [r for r in rows if r["grounded"]]
    wc = with_f1(summarise(rows))
    wc["unknown_total"] = sum(1 for r in rows if r["predicted_against_wall"] is None)
    reproduced = all(wc[k] == v for k, v in PHASE8_DONOHARM.items())
    tax = {}
    for r in rows:
        if r["failure_category"] != "NONE":
            tax.setdefault(r["failure_category"], []).append(r["case_id"])
    determinism = {"identical_positions": sum(1 for k in pos_a if pos_a[k] == pos_b[k]),
                   "cases": len(pos_a)}
    cov = [r["visible_coverage"] for r in grounded_rows
           if r["visible_coverage"] is not None and not np.isnan(r["visible_coverage"])]
    n_g = max(1, len(grounded_rows))
    metrics = {
        "cases": len(rows),
        "grounded": len(grounded_rows),
        "grounded_rate_pct": round(100.0 * len(grounded_rows) / len(rows), 1),
        "unknown": len(rows) - len(grounded_rows),
        "placement_classes": {k: sum(1 for r in rows if r["placement_class"] == k)
                              for k in sorted({r["placement_class"] for r in rows})},
        "support_consistent_of_grounded": sum(1 for r in grounded_rows if r["support_consistent"]),
        "support_consistent_pct": round(100.0 * sum(1 for r in grounded_rows
                                                    if r["support_consistent"]) / n_g, 1),
        "base_occluded_of_grounded": sum(1 for r in grounded_rows if r["base_occluded"]),
        "footprint_inside_room_of_grounded": sum(1 for r in grounded_rows if r["inside_room"]),
        "footprint_inside_room_pct": round(100.0 * sum(1 for r in grounded_rows
                                                       if r["inside_room"]) / n_g, 1),
        "visible_within_footprint": distribution(cov),
        "orientation_known_of_grounded": sum(1 for r in grounded_rows if r["orientation_known"]),
        "wall_contact": wc, "wall_contact_matches_phase8_do_no_harm": reproduced,
        "depth_m": distribution([r["depth_m"] for r in grounded_rows if r["depth_m"] is not None]),
        "confidence": distribution([r["confidence"] for r in grounded_rows]),
        "determinism": determinism,
        "latency_ms_per_object_median": round(1000 * float(np.median(timings)), 2),
        "latency_ms_per_object_p95": round(1000 * float(np.percentile(timings, 95)), 2),
        "position_error_vs_truth": "NOT TESTED: no ground-truth 3D positions exist",
        "rotation_error_vs_truth": "NOT TESTED: no ground-truth orientation exists",
        "footprint_iou_vs_truth": "NOT TESTED: no ground-truth footprints exist",
        "floor_decisions": floor_log,
    }
    payload = {
        "_about": "Phase 9. Candidate 3D grounding composed from the frozen floor (Phase 8 "
                  "do-no-harm), wall gate (Phase 6), extent (Phase 7) and catalogue "
                  "metadata. Candidate, not final placement. No ground-truth positions "
                  "exist; the metrics are internal-consistency checks and say so.",
        "config": {**GROUNDING_CONFIG, "wall_gate": PHASE6_PERMISSIVE.__dict__,
                   "floor_config": FLOOR_CONFIG, "production_code_changed": "none"},
        "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
        "metrics": metrics, "failure_taxonomy": tax, "per_case": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  grounded {metrics['grounded']}/{metrics['cases']} ({metrics['grounded_rate_pct']}%)  "
          f"classes {metrics['placement_classes']}")
    print(f"  support consistent {metrics['support_consistent_of_grounded']}/{metrics['grounded']} "
          f"({metrics['support_consistent_pct']}%)  base occluded {metrics['base_occluded_of_grounded']}")
    print(f"  footprint inside room {metrics['footprint_inside_room_of_grounded']}/{metrics['grounded']} "
          f"({metrics['footprint_inside_room_pct']}%)  visible-within-footprint "
          f"{metrics['visible_within_footprint']}")
    print(f"  orientation known {metrics['orientation_known_of_grounded']}/{metrics['grounded']}")
    print(f"  wall contact TP/TN/FP/FN={wc['tp']}/{wc['tn']}/{wc['fp']}/{wc['fn']} unk={wc['unknown_total']} "
          f"matches Phase 8 do-no-harm: {reproduced}")
    print(f"  determinism {determinism}  latency {metrics['latency_ms_per_object_median']} ms median")
    print(f"  taxonomy { {k: len(v) for k, v in tax.items()} }")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The first true end-to-end test: photo -> GroundingHypothesis -> Scene ->
production validate_scene -> production Blender build -> read-back.

    python -u research/spatial_architecture/integration_benchmark.py

Research only for the bridge (research/spatial_architecture/*.py); everything
downstream of `Scene` is PRODUCTION CODE, called unmodified:
`app.spatial.validation.validate_scene`, `app.blender.manifest.build_manifest`,
`app.blender.runner.BlenderRunner`, `blender/scripts/build_scene.py`.

CONTROL. The frozen Phase 9 wall-contact result (7/24/2/3, 12 UNKNOWN) is
reproduced first; the run aborts rather than reporting an integration result
if it drifts. The grounding computation (SAM 2 + MoGe-2 + Phase 6/7/8/9,
unchanged) is the SAME code Phase 9 benchmarked, not a re-implementation.

COLLISION RESOLUTION (P1, docs/spatial_architecture/collision.md). Every
built scene is passed through `collision_solver.resolve_collisions` BEFORE
the final `validate_scene` call: a deterministic DFS-family sequential
placement pass (order by confidence, commit one at a time, nudge along a
fixed candidate lattice on conflict) matching the mechanism
`app/planning/compiler.py:place_objects` already uses in the brief path at
0/547 measured collisions. This supersedes the earlier single "nudge the
lower-confidence object once" heuristic used in the previous session's run.

CLEARANCE REPORTING (P2, docs/spatial_architecture/clearance.md). After
collision resolution, `pairwise_clearance_violations` and
`functional_clearance_violations` are run and reported (both always
`severity="soft"` per the P2.2 taxonomy, so they do not change
`scene_success`). `circulation_violations` and `door_swing_violations` are
NOT run here: both need evidence this photo bridge never produces - an
entrance point and door `Opening`s - and `docs/spatial_architecture/
scene_from_photo.py` never emits either (no door detector exists on the
photo path). Fabricating an entrance point to exercise them would violate
the standing "never invent evidence" rule; they are instead benchmarked on
purpose-built synthetic scenes in `clearance_benchmark.py` (P2.8), where the
entrance and doors ARE the deliberately-constructed ground truth.

P4 REPAIR (docs/spatial_architecture/repair.md). After collision resolution,
every scene is passed through `repair_engine.repair_scene` (relations from
the bridge, no entrance point - matching CLEARANCE REPORTING's own reasoning
above) before the final `validate_scene` call, so a duplicate-identity
residual (P1's own measured tv_unit case) is correctly classified
UPSTREAM_REQUIRED rather than incorrectly "fixed" by moving either object.

A REAL DETERMINISM BUG WAS FOUND AND FIXED HERE (repair.md P4.13): running
this benchmark repeatedly produced a DIFFERENT `collision resolver: moved N`
count each time (12, 13, 14) before the fix. Root cause: `grounding_to_scene`
(scene_from_photo.py) built every `SceneObject` without an explicit
`object_id`, defaulting to a fresh random UUID every process run;
`resolve_collisions`'s tie-break on `object_id` (for objects that land on
the exact same `overall_confidence`) then depended on that random UUID's
ordering. Fixed by giving `grounding_to_scene` a deterministic
`object_id=f"obj_{case_id}"` - `case_id` is already unique and, unlike a
freshly-generated UUID, stable across runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(r"C:\Users\user\AppData\Local\Temp\claude"
                r"\g--ALLURE-INTERIOR-ISHANA-Interior-design"
                r"\9c0578df-4a5c-4af1-93e9-bcb7da7d1588\scratchpad\photo_e2e")
_SCRATCH.mkdir(parents=True, exist_ok=True)
# Deliberately NOT overriding AETHER_DATA_DIR. This benchmark reads the REAL
# asset registry (`resolve_asset_metadata`, `catalog.search`) to select real
# assets by dimension fit - an empty scratch registry silently changed object
# dimensions for exactly the two cases whose wall distance sat closest to the
# threshold (s13, s15), and was caught only by diffing against Phase 9's own
# per-case decisions before trusting this script at all. Blender's OWN outputs
# (manifest, .blend, log) still go to the scratch directory below, via the
# explicit `project_root` argument to `build_manifest` - independent of
# AETHER_DATA_DIR, so isolating writes does not require isolating reads.

from app.blender.manifest import build_manifest, write_manifest        # noqa: E402
from app.blender.runner import BlenderRunner                           # noqa: E402
from app.spatial import planes as P                                    # noqa: E402
from app.spatial.validation import validate_scene                      # noqa: E402
from research.spatial_engine.floor_benchmark import cam_height, contact_fraction  # noqa: E402
from research.spatial_engine.floor_candidates import (                 # noqa: E402
    FLOOR_CONFIG, generate_floor_candidates, refit_walls_with_floor, select_floor)
from research.spatial_engine.metric_geometry_benchmark import (        # noqa: E402
    gpu_used_mib, load_cases, system_ram)
from research.spatial_engine.object_extent import resolve_asset_metadata  # noqa: E402
from research.spatial_engine.object_extent_benchmark import PHASE6_PERMISSIVE  # noqa: E402
from research.spatial_engine.object_grounding import ground_object      # noqa: E402
from research.spatial_engine.rear_extent_benchmark import build_geometry  # noqa: E402
from research.spatial_engine.rear_extent_wall_contact import (          # noqa: E402
    orient_to_room, room_centroid)
from research.spatial_engine.segmentation_grounding import Sam2Grounder  # noqa: E402
from research.spatial_engine.wall_quality import extract_wall_features, gated_room  # noqa: E402
from research.spatial_architecture.clearance_engine import (          # noqa: E402
    functional_clearance_violations, pairwise_clearance_violations)
from research.spatial_architecture.collision_solver import resolve_collisions  # noqa: E402
from research.spatial_architecture.grounding_contract import GroundingHypothesis  # noqa: E402
from research.spatial_architecture.repair_engine import repair_scene  # noqa: E402
from research.spatial_architecture.scene_from_photo import (           # noqa: E402
    WallEvidence, grounding_to_scene)

OUT = HERE / "integration_results.json"
PHASE9_CONTROL = {"tp": 7, "tn": 24, "fp": 2, "fn": 3}

ROOM_TYPE_KEYWORDS = [("kitchen", "kitchen"), ("bedroom", "bedroom"),
                     ("bathroom", "bathroom"), ("dining", "dining_room"),
                     ("office", "home_office"), ("lounge", "living_room"),
                     ("living", "living_room")]


def guess_room_type(image_key: str) -> str:
    """Heuristic from the filename only - never used for geometry, only for
    the Room.type label and material defaults."""
    name = Path(image_key).stem.lower()
    for kw, rt in ROOM_TYPE_KEYWORDS:
        if kw in name:
            return rt
    return "living_room"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-blender", action="store_true",
                        help="build and validate scenes but skip the Blender pass")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]
    print(f"cases {len(cases)}\n", flush=True)

    # -- perception, once, exactly as Phase 9 benchmarked it -----------------
    grounder = Sam2Grounder()
    grounder.load()
    masks = {c["case_id"]: grounder.segment(ROOT / c["image"], c["bbox"]).mask for c in cases}
    grounder.unload()
    geometry, boxes_by_image = build_geometry(cases, masks)

    slo, shi = FLOOR_CONFIG["camera_height_soft_m"]
    per_image = {}
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
            floor_plane, used_room = hyp.plane, refit_walls_with_floor(pm, ex, hyp.plane)
        elif base_bad:
            floor_plane, used_room = None, room
        else:
            floor_plane, used_room = room.floor.plane, room

        feats = extract_wall_features(pm, used_room, ex) if used_room.ok else []
        gated, _rej = (gated_room(used_room, feats, PHASE6_PERMISSIVE) if used_room.ok
                       else (used_room, {}))
        quality = {f.wall_index: f.enclosure_fraction for f in feats
                  if f.enclosure_fraction is not None}
        width_by_index = {f.wall_index: f.width_m for f in feats}
        centre = room_centroid(pm)
        scale = gated.scene_scale or pm.scene_scale()
        walls_ev = []
        for i, w in enumerate(gated.walls):
            if w.uncertain or w.plane is None:
                continue
            sign, _src, _margin = orient_to_room(w.plane, centre, scale)
            walls_ev.append(WallEvidence(index=i, normal=w.plane.normal, offset=w.plane.offset,
                                         width_m=width_by_index.get(i, 3.0),
                                         enclosure_fraction=quality.get(i),
                                         into_room_sign=sign if sign != 0.0 else 1.0))

        floor_pts_xz = [(0.0, 0.0)]
        if floor_plane is not None:
            threshold = (gated.scene_scale or 1.0) * 0.012
            d = floor_plane.distance(pm.valid_points())
            near_floor = pm.valid_points()[d < threshold * 4.0]
            if near_floor.shape[0] > 0:
                floor_pts_xz = [(float(p[0]), float(p[2])) for p in near_floor]

        per_image[key] = {"pointmap": pm, "gated": gated, "floor_plane": floor_plane,
                          "walls_ev": walls_ev, "quality": quality,
                          "floor_pts_xz": floor_pts_xz}

    # -- grounding, then wrap each into a GroundingHypothesis ---------------
    hyps_by_image: dict = {}
    for c in cases:
        info = per_image[c["image"]]
        pm, gated, quality = info["pointmap"], info["gated"], info["quality"]
        mask = masks[c["case_id"]]
        if not mask.any():
            mask = P.mask_from_box(pm.height, pm.width, c["bbox"])
        meta = resolve_asset_metadata(c["object_type"])
        g = ground_object(c["case_id"], c["object_id"], pm, info["floor_plane"], gated,
                          quality, mask, meta,
                          floor_confidence=(1.0 if info["floor_plane"] is not None else 0.0))
        usable = mask & pm.valid
        perception_conf = float(usable.sum()) / max(1, int(mask.sum()))
        cat = g.failure_category if g.footprint is None else "NONE"
        h = GroundingHypothesis.from_object_grounding(
            g, room_image=c["image"], canonical_type=meta.canonical_type,
            perception_confidence=perception_conf, extent_confidence=meta.confidence,
            failure_category=cat)
        hyps_by_image.setdefault(c["image"], []).append(h)

    grounded_total = sum(1 for hs in hyps_by_image.values() for h in hs if h.grounded)
    print(f"  grounded {grounded_total}/{len(cases)} objects across "
          f"{len(hyps_by_image)} images", flush=True)

    # -- control: reproduce Phase 9's wall-contact confusion matrix ----------
    tp = tn = fp = fn = 0
    truth_by_case = {c["case_id"]: c["truth"] for c in cases}
    for hs in hyps_by_image.values():
        for h in hs:
            if h.wall_decision == "UNKNOWN":
                continue
            pred = h.wall_decision == "YES"
            truth = truth_by_case[h.case_id]
            if truth:
                tp, fn = (tp + 1, fn) if pred else (tp, fn + 1)
            else:
                fp, tn = (fp + 1, tn) if pred else (fp, tn + 1)
    measured = {"tp": tp, "tn": tn, "fp": fp, "fn": fn}
    # The stored confusion matrix is over the FULL 48 cases; a --limit run sees
    # a different, smaller slice by construction, so the control only applies
    # unsliced. A limited run still prints what it measured, honestly, but does
    # not compare it to a number that was never going to match.
    reproduced = (measured == PHASE9_CONTROL) if not args.limit else True
    print(f"  Phase 9 control reproduced: {reproduced} (measured {measured}"
          f"{', --limit set: not compared' if args.limit else ''})", flush=True)
    if not reproduced:
        debug = {c["case_id"]: {"decision": h.wall_decision, "truth": c["truth"],
                                "wall_index": h.wall_index, "distance_m": h.wall_distance_m}
                for hs in hyps_by_image.values() for h in hs
                for c in cases if c["case_id"] == h.case_id}
        OUT.write_text(json.dumps({"_about": "Phase (architecture) integration ABORTED: "
                                   "Phase 9 control drifted.",
                                   "control": {"stored": PHASE9_CONTROL, "measured": measured},
                                   "per_case_debug": debug}, indent=2, default=str),
                       encoding="utf-8")
        print("  STOP: control drifted.")
        return 1

    # -- build a Scene per image, validate, repair once, build in Blender ---
    runner = BlenderRunner() if not args.no_blender else None
    blender_ok = runner.configured if runner else False
    if runner and not blender_ok:
        print("  BLENDER_PATH not configured: scenes will be validated but not built.")

    scenes_out = []
    for image_key, hs in hyps_by_image.items():
        info = per_image[image_key]
        result = grounding_to_scene(
            image_key=image_key, project_id=f"photo_{Path(image_key).stem}",
            room_type=guess_room_type(image_key), floor_points_xz=info["floor_pts_xz"],
            walls=info["walls_ev"], hypotheses=hs)
        scene, resolutions = resolve_collisions(result.scene, result.relations)
        p4 = repair_scene(scene, relations=result.relations, entrance_xz=None)
        scene = p4.scene
        violations = validate_scene(scene)
        hard = [v for v in violations if v.severity == "hard"]
        repair_log = [{"object_id": r.object_id, "status": r.status,
                       "distance_moved_m": r.distance_moved_m,
                       "candidates_tried": r.candidates_tried}
                      for r in resolutions if r.status != "kept"]
        p4_log = {"terminal_state": p4.terminal_state, "hard_before": p4.hard_before,
                 "hard_after": p4.hard_after, "escalation_level_reached": p4.escalation_level_reached,
                 "records": [{"level": rec.level, "type": rec.repair_type, "subject": rec.subject_id,
                             "target": rec.target_id, "cause": rec.cause, "outcome": rec.outcome,
                             "evidence": rec.evidence} for rec in p4.records]}
        clearance = pairwise_clearance_violations(scene) + functional_clearance_violations(scene)
        clearance_log = [{"subject_id": c.subject_id, "target_id": c.target_id,
                          "category": c.category, "constraint": c.constraint,
                          "required_m": c.required_m, "actual_m": c.actual_m,
                          "deficit_m": c.deficit_m, "severity": c.severity}
                         for c in clearance]

        entry = {"image": image_key, "room_type": scene.rooms[0].type,
                 "grounded": sum(1 for h in hs if h.grounded),
                 "objects_placed": result.objects_placed,
                 "objects_skipped": result.objects_skipped,
                 "skipped_reasons": result.skipped_reasons,
                 "relations_emitted": len(result.relations),
                 "relations": result.relations,
                 "room_boundary_source": result.room_boundary_source,
                 "room_confidence": result.room_confidence.value,
                 "footprint_reconstruction_error_m": result.footprint_reconstruction_error_m,
                 "bridge_warnings": result.warnings,
                 "hard_violations": [{"code": v.code, "object_id": v.object_id,
                                      "related_id": v.related_id} for v in hard],
                 "hard_by_code": {c: sum(1 for v in hard if v.code == c) for c in {v.code for v in hard}},
                 "valid": not hard, "repair": repair_log, "clearance_violations": clearance_log,
                 "repair_p4": p4_log}

        if runner and blender_ok and scene.objects:
            proj = _SCRATCH / f"proj_{Path(image_key).stem}"
            proj.mkdir(parents=True, exist_ok=True)
            manifest = build_manifest(scene, project_id=scene.project_id, project_root=proj,
                                      preview=False)
            mpath = write_manifest(manifest, proj / "blender" / "build_manifest.json")
            t = time.perf_counter()
            try:
                res = runner.run("build_scene.py", ["--manifest", str(mpath), "--no-preview"],
                                 log_path=proj / "blender.log", timeout=900)
                report_path = Path(manifest["output"]["report"])
                report = (json.loads(report_path.read_text(encoding="utf-8"))
                          if report_path.exists() else {})
                entry["blender"] = {"ok": bool(report.get("ok")),
                                    "errors": report.get("errors", []),
                                    "warnings": report.get("warnings", []),
                                    "seconds": round(time.perf_counter() - t, 1),
                                    "objects_built": report.get("counts", {}).get("objects")}
            except Exception as exc:                                     # noqa: BLE001
                entry["blender"] = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"[:300]],
                                    "seconds": round(time.perf_counter() - t, 1)}
        else:
            entry["blender"] = {"ok": None, "note": "skipped (no objects or Blender unavailable)"}

        entry["scene_success"] = bool(
            entry["valid"] and entry["objects_placed"] == entry["grounded"]
            and entry["blender"].get("ok") is not False)
        scenes_out.append(entry)
        print(f"  {Path(image_key).stem:34} grounded={entry['grounded']:2} "
              f"placed={entry['objects_placed']:2} skipped={entry['objects_skipped']:2} "
              f"hard={len(hard)} relations={entry['relations_emitted']} "
              f"blender_ok={entry['blender'].get('ok')} success={entry['scene_success']}",
              flush=True)

    valid_n = sum(1 for e in scenes_out if e["valid"])
    success_n = sum(1 for e in scenes_out if e["scene_success"])
    total_grounded = sum(e["grounded"] for e in scenes_out)
    total_placed = sum(e["objects_placed"] for e in scenes_out)
    all_residuals = [v for e in scenes_out for v in e["footprint_reconstruction_error_m"].values()]
    hard_by_code: dict = {}
    for e in scenes_out:
        for k, v in e["hard_by_code"].items():
            hard_by_code[k] = hard_by_code.get(k, 0) + v
    blender_ok_n = sum(1 for e in scenes_out if e["blender"].get("ok") is True)
    blender_attempted = sum(1 for e in scenes_out if e["blender"].get("ok") is not None)

    summary = {
        "images": len(scenes_out), "grounded_objects": total_grounded,
        "objects_placed_in_scene": total_placed,
        "placed_rate_pct": round(100.0 * total_placed / max(1, total_grounded), 1),
        "scenes_valid": valid_n, "scenes_valid_pct": round(100.0 * valid_n / len(scenes_out), 1),
        "scene_success": success_n,
        "scene_success_pct": round(100.0 * success_n / len(scenes_out), 1),
        "scene_success_definition": "zero hard validate_scene violations AND every grounded "
                                    "FLOOR_STANDING object placed AND (Blender build ok OR "
                                    "not attempted)",
        "hard_violations_by_code": hard_by_code,
        "footprint_reconstruction_error_m": {
            "n": len(all_residuals),
            "median": round(float(np.median(all_residuals)), 4) if all_residuals else None,
            "p95": round(float(np.percentile(all_residuals, 95)), 4) if all_residuals else None,
            "max": round(max(all_residuals), 4) if all_residuals else None},
        "relations_emitted_total": sum(e["relations_emitted"] for e in scenes_out),
        "relations_emitted_predicates": sorted({r["predicate"] for e in scenes_out
                                                for r in e["relations"]}),
        "blender_attempted": blender_attempted, "blender_ok": blender_ok_n,
        "collision_resolver_moved": sum(1 for e in scenes_out for r in e["repair"]
                                        if r["status"] == "moved"),
        "collision_resolver_unresolved": sum(1 for e in scenes_out for r in e["repair"]
                                             if r["status"] == "unresolved"),
        "clearance_violations_total": sum(len(e["clearance_violations"]) for e in scenes_out),
        "clearance_violations_by_category": {
            cat: sum(1 for e in scenes_out for c in e["clearance_violations"] if c["category"] == cat)
            for cat in {c["category"] for e in scenes_out for c in e["clearance_violations"]}},
        "p4_hard_before_total": sum(e["repair_p4"]["hard_before"] for e in scenes_out),
        "p4_hard_after_total": sum(e["repair_p4"]["hard_after"] for e in scenes_out),
        "p4_terminal_states": {
            state: sum(1 for e in scenes_out if e["repair_p4"]["terminal_state"] == state)
            for state in {e["repair_p4"]["terminal_state"] for e in scenes_out}},
    }
    payload = {"_about": "Integration benchmark: real GroundingHypothesis output, through the "
                         "research bridge, into UNMODIFIED production validate_scene and "
                         "Blender build+read-back. See architecture_decision.md.",
              "host": {"gpu_used_mib_at_start": gpu_used_mib(), "ram": system_ram()},
              "control": {"stored": PHASE9_CONTROL, "measured": measured, "reproduced": reproduced},
              "summary": summary, "scenes": scenes_out}
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  images {summary['images']}  grounded {summary['grounded_objects']}  "
          f"placed {summary['objects_placed_in_scene']} ({summary['placed_rate_pct']}%)")
    print(f"  scenes valid {summary['scenes_valid']}/{summary['images']} "
          f"({summary['scenes_valid_pct']}%)  scene success {summary['scene_success']}/"
          f"{summary['images']} ({summary['scene_success_pct']}%)")
    print(f"  hard violations by code: {hard_by_code}")
    print(f"  footprint reconstruction error: {summary['footprint_reconstruction_error_m']}")
    print(f"  relations emitted: {summary['relations_emitted_total']} "
          f"({summary['relations_emitted_predicates']})")
    print(f"  Blender: {blender_ok_n}/{blender_attempted} ok")
    print(f"  collision resolver: moved {summary['collision_resolver_moved']}, "
          f"unresolved {summary['collision_resolver_unresolved']}")
    print(f"  clearance violations: {summary['clearance_violations_total']} "
          f"({summary['clearance_violations_by_category']})")
    print(f"  P4 repair: hard {summary['p4_hard_before_total']} -> {summary['p4_hard_after_total']}, "
          f"terminal states {summary['p4_terminal_states']}")
    print(f"\n  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

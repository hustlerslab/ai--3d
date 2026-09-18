"""Phase 13: Blender as an execution backend, with the geometry read back.

    python -u research/spatial_engine/blender_e2e_benchmark.py

Research only. Drives production code (`compile_scene`, `place_objects`,
`build_manifest`, `BlenderRunner`, `blender/scripts/build_scene.py`) on a scratch
project directory. No production file is modified.

WHAT IS MEASURED. For each compiled scene, Blender builds it headless from the
manifest and its own `validate_scene.py` writes a report that includes every
placed object's WORLD-SPACE bounding box, read back through `matrix_world`
after the transform was applied. That is the read-back the brief demands:
Blender is never assumed to have executed the transform. From it:

    position     bbox centre (x, y) vs the manifest location         error, m
    floor        bbox min z                                          contact, m
    dimensions   bbox size vs manifest expected size                 within 25%
    room bounds  Blender's own pivot-inside-room check               errors
    execution    ok / errors / warnings / seconds / counts

Conversions are the production ones (`to_blender_xyz`: (x, y, z) -> (x, -z, y);
up axis Z). They are exercised by the read-back, not restated here.
"""
from __future__ import annotations

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
                r"\9c0578df-4a5c-4af1-93e9-bcb7da7d1588\scratchpad\blender_e2e")
_SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["AETHER_DATA_DIR"] = str(_SCRATCH / "data")
for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MESHY_API_KEY"):
    os.environ[k] = ""
os.environ["INTELLIGENCE_PROVIDER"] = "auto"
os.environ["SCENE_IMAGE_ENABLED"] = "false"

from app.core import config                                            # noqa: E402
config.get_settings.cache_clear()

from app.blender.manifest import build_manifest, write_manifest        # noqa: E402
from app.blender.runner import BlenderRunner                           # noqa: E402
from app.intelligence import InputBundle                               # noqa: E402
from app.intelligence.mock_provider import MockProvider                # noqa: E402
from app.intelligence.vocab import Vertical                            # noqa: E402
from app.planning import compile_scene, place_objects, resolve_plan     # noqa: E402
from app.spatial.validation import validate_scene                      # noqa: E402

OUT = HERE / "blender_e2e_results.json"
DIM_TOL = 0.25

from research.spatial_engine.scene_validity_benchmark import BRIEFS  # noqa: E402  the same frozen 12


def compile_brief(brief_id: str, vertical: str, text: str):
    bundle = InputBundle(project_id=f"e2e_{brief_id}", description=text, vertical=Vertical(vertical))
    mock = MockProvider()
    analysis = mock.analyze_input(bundle)
    style = mock.create_style_spec(analysis, bundle)
    scene, _w = compile_scene(f"e2e_{brief_id}", analysis, style, name=brief_id)
    plan = mock.plan_objects(analysis, style, bundle)
    ops, _pw = place_objects(scene, plan, resolve_plan(plan, style))
    scene.objects = [op.object for op in ops]
    hard = [v for v in validate_scene(scene) if v.severity == "hard"]
    return scene, len(hard)


def main() -> int:
    runner = BlenderRunner()
    if not runner.configured:
        OUT.write_text(json.dumps({"_about": "Phase 13 BLOCKED: BLENDER_PATH not configured"},
                                  indent=2), encoding="utf-8")
        print("BLOCKED: Blender not configured")
        return 1
    version = runner.version()
    print(f"blender: {version}", flush=True)

    scenes_out = []
    for brief_id, vertical, text in BRIEFS:
        scene, hard = compile_brief(brief_id, vertical, text)
        proj = _SCRATCH / f"proj_{brief_id}"
        proj.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest(scene, project_id=f"e2e_{brief_id}", project_root=proj, preview=False)
        mpath = write_manifest(manifest, proj / "blender" / "build_manifest.json")
        expected = {o["id"]: o for o in manifest["objects"]}

        t = time.perf_counter()
        entry = {"id": brief_id, "vertical": vertical, "objects": len(manifest["objects"]),
                 "rooms": len(manifest["rooms"]), "walls": len(manifest["walls"]),
                 "pre_blender_hard_violations": hard}
        try:
            res = runner.run("build_scene.py", ["--manifest", str(mpath), "--no-preview"],
                             log_path=proj / "blender.log", timeout=900)
            result = res.result or {}
            report_path = Path(manifest["output"]["report"])
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            entry.update(ok=bool(report.get("ok")), errors=report.get("errors", []),
                         warnings=report.get("warnings", []), counts=report.get("counts", {}),
                         seconds=round(time.perf_counter() - t, 1),
                         stages=result.get("stages", {}), blender=report.get("blender"))
        except Exception as exc:                                        # noqa: BLE001
            entry.update(ok=False, errors=[f"{type(exc).__name__}: {exc}"[:300]], warnings=[],
                         counts={}, seconds=round(time.perf_counter() - t, 1), readback=[])
            scenes_out.append(entry)
            print(f"  {brief_id:16} FAILED {entry['errors'][0]}", flush=True)
            continue

        # -- read-back --------------------------------------------------
        rb = []
        for p in report.get("objects", []):
            exp = expected.get(p["id"])
            if exp is None or p.get("parts", 0) == 0:
                continue
            lo, hi = np.array(p["bbox_min"]), np.array(p["bbox_max"])
            centre = (lo + hi) / 2.0
            mx, my, _mz = exp["location"]
            size = (hi - lo).tolist()
            edims = exp["dimensions"]                       # blender order (x, y, z)
            dims_ok = all(
                (edims[i] <= 0) or abs(size[i] / edims[i] - 1) <= DIM_TOL
                or (i < 2 and abs(size[1 - i] / edims[i] - 1) <= DIM_TOL)
                for i in range(3))
            rb.append({"id": p["id"], "type": p["semantic_type"], "kind": p["kind"],
                       "manifest_xy": [round(mx, 3), round(my, 3)],
                       "readback_centre_xy": [round(float(centre[0]), 3), round(float(centre[1]), 3)],
                       "xy_error_m": round(float(np.hypot(centre[0] - mx, centre[1] - my)), 3),
                       "bbox_min_z_m": round(float(lo[2]), 3),
                       "readback_size": [round(v, 3) for v in size],
                       "expected_size": [round(v, 3) for v in edims], "dims_ok": dims_ok})
        errs = [r["xy_error_m"] for r in rb]
        zs = [r["bbox_min_z_m"] for r in rb]
        entry["readback"] = rb
        entry["readback_summary"] = {
            "objects_read_back": len(rb),
            "xy_error_m": {"median": round(float(np.median(errs)), 3) if errs else None,
                           "p95": round(float(np.percentile(errs, 95)), 3) if errs else None,
                           "max": round(max(errs), 3) if errs else None},
            "floor_contact_bbox_min_z_m": {"median": round(float(np.median(zs)), 3) if zs else None,
                                           "min": round(min(zs), 3) if zs else None,
                                           "max": round(max(zs), 3) if zs else None},
            "dims_within_25pct": sum(1 for r in rb if r["dims_ok"]),
            "dims_within_25pct_pct": round(100.0 * sum(1 for r in rb if r["dims_ok"]) / max(1, len(rb)), 1),
            "inside_room_errors": sum(1 for e in entry["errors"] if "outside room" in e)}
        scenes_out.append(entry)
        s = entry["readback_summary"]
        print(f"  {brief_id:16} ok={entry['ok']} objects={entry['objects']} errors={len(entry['errors'])} "
              f"warnings={len(entry['warnings'])} {entry['seconds']}s  xy_err med={s['xy_error_m']['median']} "
              f"max={s['xy_error_m']['max']}  floor z med={s['floor_contact_bbox_min_z_m']['median']} "
              f"dims ok {s['dims_within_25pct']}/{s['objects_read_back']}", flush=True)

    built = [e for e in scenes_out if e.get("ok")]
    all_err = [r["xy_error_m"] for e in scenes_out for r in e.get("readback", [])]
    all_z = [r["bbox_min_z_m"] for e in scenes_out for r in e.get("readback", [])]
    n_rb = sum(len(e.get("readback", [])) for e in scenes_out)
    secs = sorted(e["seconds"] for e in scenes_out)
    summary = {"blender": version, "scenes": len(scenes_out), "built_ok": len(built),
               "errors_total": sum(len(e.get("errors", [])) for e in scenes_out),
               "warnings_total": sum(len(e.get("warnings", [])) for e in scenes_out),
               "seconds_median": secs[len(secs) // 2] if secs else None,
               "objects_read_back": n_rb,
               "xy_error_m": {"median": round(float(np.median(all_err)), 3) if all_err else None,
                              "p95": round(float(np.percentile(all_err, 95)), 3) if all_err else None,
                              "max": round(max(all_err), 3) if all_err else None},
               "floor_contact_bbox_min_z_m": {"median": round(float(np.median(all_z)), 3) if all_z else None,
                                              "min": round(min(all_z), 3) if all_z else None,
                                              "max": round(max(all_z), 3) if all_z else None},
               "dims_within_25pct_pct": round(100.0 * sum(1 for e in scenes_out for r in e.get("readback", [])
                                                          if r["dims_ok"]) / max(1, n_rb), 1),
               "not_read_back": ["wall contact (no wall-relative check inside Blender yet)",
                                 "collision (checked pre-Blender by validate_scene, not re-checked "
                                 "on the built meshes)", "rotation (only via size-axis swap)"]}
    OUT.write_text(json.dumps({"_about": "Phase 13. Production compile -> manifest -> headless Blender "
                                         "build -> in-Blender validation with world-space bbox read-back.",
                               "summary": summary, "scenes": scenes_out}, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n  built {summary['built_ok']}/{summary['scenes']}  errors {summary['errors_total']}  "
          f"warnings {summary['warnings_total']}  read back {n_rb} objects  "
          f"xy err med {summary['xy_error_m']['median']} p95 {summary['xy_error_m']['p95']}  "
          f"floor z med {summary['floor_contact_bbox_min_z_m']['median']}  "
          f"dims ok {summary['dims_within_25pct_pct']}%")
    print(f"  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

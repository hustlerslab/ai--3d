"""P16: one real reference through the real product, end to end.

Live Gemini, the real HTTP routes, the real job runner, the real spatial solver,
the real manifest, the real Blender binary. Nothing is mocked and nothing is
short-circuited: every step is the same call the frontend makes.

Isolation, not simulation: AETHER_DATA_DIR points at a scratch directory whose
`assets` and `materials` are junctions to the real library, so the run sees the
real 58-asset registry without writing into the user's project data.

    AETHER_DATA_DIR=<scratch> BLENDER_PATH=<blender.exe> \
        python -u research/p16_live_production_run.py

The reference is ref_07, the sage sofa on a dark wood frame - the case P15
showed the model reads correctly and P14 showed the resolver renders as light
oak. That known, unfixed discrepancy is the point: this records what the
product actually does today.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REFERENCE = (ROOT / "data" / "projects" / "proj_553cb09794" / "input" / "references"
             / "ref_07.jpeg")
OUT = ROOT.parent / "docs" / "benchmarks" / "p16_production_wiring.json"
BRIEF = ("A calm living room for a young family, built around this sofa. "
         "Warm neutral tones, natural materials, a coffee table and a rug.")


def _require_isolated_data_dir() -> Path:
    """Refuse to run against the real data directory. A live run creates a
    project, and that must never land in someone's working set by accident."""
    raw = os.environ.get("AETHER_DATA_DIR", "")
    if not raw:
        raise SystemExit("set AETHER_DATA_DIR to a scratch directory first")
    data = Path(raw).resolve()
    if data == (ROOT / "data").resolve():
        raise SystemExit("refusing to run against the real data dir")
    return data


def main() -> int:
    data_dir = _require_isolated_data_dir()
    if not REFERENCE.exists():
        raise SystemExit(f"reference image not found: {REFERENCE}")

    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.jobs import get_runner
    from app.main import app
    from app.projects.layout import project_dir

    settings = get_settings()
    print(f"data dir : {data_dir}")
    print(f"gemini   : configured={settings.gemini_configured} model={settings.gemini_model}")
    print(f"blender  : configured={settings.blender_configured}")
    if not settings.gemini_configured:
        raise SystemExit("live Gemini is required; GEMINI_API_KEY is not configured")

    report: dict = {
        "_about": "One real reference image through the real production API with live "
                  "Gemini and real Blender. Isolated data dir, real asset registry.",
        "stack": {"vision": "gemini", "asset_generation": "meshy",
                  "spatial": "allure", "executor": "blender"},
        "model": settings.gemini_model,
        "reference": REFERENCE.name,
        "stages": [],
    }

    with TestClient(app) as client:
        health = client.get("/api/health").json()
        report["provider_mode"] = health["providers"]["intelligence"]["mode"]
        print(f"provider mode: {report['provider_mode']}")
        if report["provider_mode"] != "live":
            raise SystemExit("provider is not live; this run would prove nothing")

        # ── 1. create + upload, exactly as the Studio does ───────────────
        t0 = time.perf_counter()
        pid = client.post("/api/projects", json={"name": "P16 live run"}
                          ).json()["project"]["project_id"]
        up = client.post(
            f"/api/projects/{pid}/inputs",
            data={"description": BRIEF},
            files=[("references", (REFERENCE.name, REFERENCE.read_bytes(), "image/jpeg"))],
        )
        if up.status_code != 200:
            raise SystemExit(f"upload failed: {up.text}")
        upload_s = time.perf_counter() - t0
        report["project_id"] = pid
        report["stages"].append({"stage": "upload", "status": "OK",
                                 "seconds": round(upload_s, 2),
                                 "rejected": up.json()["rejected"]})
        print(f"project {pid} | upload {upload_s:.2f}s | rejected {up.json()['rejected']}")

        inputs = client.get(f"/api/projects/{pid}/inputs").json()["data"]
        input_ids = [i["input_id"] for i in inputs if i["kind"] == "reference"]
        report["reference_input_ids"] = input_ids
        print(f"reference input ids: {input_ids}")

        # ── 2. every job the Studio fires, in order ──────────────────────
        def run(path: str, body: dict, timeout: int) -> dict:
            started = time.perf_counter()
            r = client.post(path, json=body)
            if r.status_code != 200:
                raise SystemExit(f"{path} refused: {r.status_code} {r.text}")
            job_id = r.json()["job"]["job_id"]
            if not get_runner().wait_idle(timeout):
                raise SystemExit(f"{path} did not finish within {timeout}s")
            job = client.get(f"/api/jobs/{job_id}").json()["data"]["job"]
            elapsed = time.perf_counter() - started
            report["stages"].append({"stage": job["type"], "job_id": job_id,
                                     "status": job["status"],
                                     "seconds": round(elapsed, 2),
                                     "error": job.get("error") or ""})
            print(f"  {job['type']:14s} {job['status']:10s} {elapsed:7.2f}s "
                  f"{job.get('error') or ''}")
            if job["status"] != "SUCCEEDED":
                raise SystemExit(f"{job['type']} failed: {job.get('error')}")
            return job

        run(f"/api/projects/{pid}/analyze", {}, 900)
        plan = run(f"/api/projects/{pid}/scene-plan", {}, 900)
        scene_id = plan["result"]["scene_id"]
        report["scene_id"] = scene_id
        report["plan_result"] = {k: plan["result"].get(k) for k in
                                 ("scene_id", "scene_version", "objects", "rooms",
                                  "hard_violations", "unresolved_intents")}
        print(f"scene {scene_id}")

        # ── 3. what the reference actually produced ──────────────────────
        intent_set = json.loads((project_dir(pid) / "planning" / "design_intent.json")
                                .read_text(encoding="utf-8"))
        intents = intent_set["intents"]
        report["design_intent"] = {
            "reference_ids": intent_set["reference_ids"],
            "unread": intent_set["unread"],
            "intents": [{"intent_id": i["intent_id"],
                         "reference_class": i["reference_class"],
                         "object_category": i["object_category"],
                         "from_input": i["provenance"]["input_id"],
                         "attributes": {k: v for k, v in i["attributes"].items() if v}}
                        for i in intents],
        }
        for i in report["design_intent"]["intents"]:
            print(f"  intent {i['intent_id']} {i['reference_class']} "
                  f"{i['object_category']} {i['attributes']}")

        scene = client.get(f"/api/scenes/{scene_id}").json()["data"]["scene"]
        traced = [o for o in scene["objects"] if o.get("visual", {}).get("source_intent_ids")]
        report["scene"] = {
            "objects": len(scene["objects"]),
            "rooms": len(scene["rooms"]),
            "objects_traceable_to_a_reference": len(traced),
            "traced": [{"object_id": o["object_id"], "semantic_type": o["semantic_type"],
                        "asset_id": o.get("asset_id"), "color": o.get("color"),
                        "material_overrides": o.get("material_overrides"),
                        "visual": o["visual"]} for o in traced],
        }
        print(f"scene objects {len(scene['objects'])} | traceable {len(traced)}")

        # ── 4. build through Blender, and read the manifest back ─────────
        if not settings.blender_configured:
            report["blender"] = {"ran": False, "why": "BLENDER_PATH not configured"}
            print("blender not configured; stopping before build")
        else:
            run(f"/api/projects/{pid}/build", {"preview": True, "force": True}, 1800)
            manifest = json.loads((project_dir(pid) / "blender" / "build_manifest.json")
                                  .read_text(encoding="utf-8"))
            states: dict[str, int] = {}
            rows = []
            for row in manifest["objects"]:
                finish = row.get("finish")
                if not finish:
                    continue
                states[finish["state"]] = states.get(finish["state"], 0) + 1
                rows.append({"id": row["id"], "semantic_type": row["semantic_type"],
                             "asset": (row.get("asset") or {}).get("kind"),
                             "color": row.get("color"),
                             "material_overrides": row.get("material_overrides"),
                             "finish": finish})
            build = client.get(f"/api/projects/{pid}/build").json()["data"]
            blend = project_dir(pid) / "blender" / "scene.blend"
            report["manifest"] = {
                "scene_id": manifest["scene_id"],
                "objects": len(manifest["objects"]),
                "objects_with_finish": len(rows),
                "finish_states": states,
                "described": rows,
            }
            report["blender"] = {
                "ran": True,
                "blend_bytes": blend.stat().st_size if blend.exists() else 0,
                "files": build.get("files", {}),
                "report_keys": sorted((build.get("report") or {}).keys()),
            }
            print(f"manifest objects {len(manifest['objects'])} | with finish {len(rows)} "
                  f"| states {states}")
            print(f"scene.blend {report['blender']['blend_bytes']} bytes")

            # every advertised file must actually be retrievable
            retrievable = {}
            for key, url in (build.get("files") or {}).items():
                if not url:
                    continue
                retrievable[key] = client.get(url).status_code
            report["blender"]["file_status"] = retrievable
            print(f"file retrieval {retrievable}")

    report["total_seconds"] = round(sum(s["seconds"] for s in report["stages"]), 2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\ntotal {report['total_seconds']}s")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

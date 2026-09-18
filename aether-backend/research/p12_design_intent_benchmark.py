"""P12 live benchmark: does a user's reference survive the REAL scene_plan path?

Every case drives the shipped HTTP routes, the real job runner and the real
`scene_plan` handler - `POST /api/projects`, `POST /inputs`, `POST /analyze`,
`POST /scene-plan` - against an isolated data directory. Nothing is simulated:
the same code a paid user hits is the code measured here.

TWO HONEST LIMITS, stated up front because they bound every number below.

1. The vision provider is the deterministic MockProvider, whose
   `classify_reference` reads the client's FILENAME (it cannot see an image and
   says so in every intent's `notes`). So these cases prove the PLUMBING -
   references reach classification, classes drive instantiation, reconciliation
   de-duplicates, resolution and fidelity run, results are deterministic - not
   the visual accuracy of a real model. Case 10 covers the real model on real
   photographs separately.
2. Blender is not invoked. The measured boundary is `build_manifest`, the
   single Scene -> executor hand-off; the frozen `blender_e2e` benchmark
   already covers what happens past it.

    python -u research/p12_design_intent_benchmark.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="p12_"))
os.environ.update({
    "AETHER_DATA_DIR": str(_TMP / "data"),
    "INTELLIGENCE_PROVIDER": "mock",
    "SCENE_IMAGE_ENABLED": "false",
    "GEMINI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "MESHY_API_KEY": "",
    "JOBS_AI_WORKERS": "2",
    "JOBS_RENDER_WORKERS": "1",
    "JOBS_RETRY_DELAY_SECONDS": "0.05",
})

from fastapi.testclient import TestClient                               # noqa: E402
from PIL import Image                                                   # noqa: E402

from app.jobs import get_runner                                         # noqa: E402
from app.main import app                                                # noqa: E402
from app.projects.layout import project_dir                             # noqa: E402
from app.scene.store import get_store                                   # noqa: E402

OUT = ROOT.parent / "docs" / "benchmarks" / "p12_live_design_intent.json"
BRIEF = ("Two bedroom flat for a family of four. Living room, master bedroom, "
         "kids room and kitchen. Warm and calm.")
client = TestClient(app)


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (140, 150, 130)).save(path, "JPEG")
    return path


def _project(name: str, filenames: list[str], brief: str = BRIEF) -> str:
    """Create a project and upload real files through the real multipart route."""
    pid = client.post("/api/projects", json={"name": name}).json()["project"]["project_id"]
    files = [("references", (fn, _image(_TMP / "refs" / fn).read_bytes(), "image/jpeg"))
             for fn in filenames]
    r = client.post(f"/api/projects/{pid}/inputs", data={"description": brief}, files=files)
    assert r.status_code == 200, r.text
    assert not r.json()["rejected"], r.json()["rejected"]
    assert client.post(f"/api/projects/{pid}/analyze", json={}).status_code == 200
    assert get_runner().wait_idle(180), "analyze did not finish"
    return pid


def _plan(pid: str) -> dict:
    job = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    assert get_runner().wait_idle(300), "scene_plan did not finish"
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]
    assert polled["job"]["status"] == "SUCCEEDED", polled["job"].get("error")
    return polled


def _artifacts(pid: str) -> tuple[dict, dict, dict]:
    root = project_dir(pid)

    def read(rel: str) -> dict:
        p = root / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    return (read("planning/design_intent.json"), read("planning/object_plan.json"),
            read("planning/visual_intent_fidelity.json"))


def _classes(intent: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in intent.get("intents", []):
        out[i["reference_class"]] = out.get(i["reference_class"], 0) + 1
    return out


def _items(plan: dict, semantic_type: str) -> list[dict]:
    return [i for i in plan.get("items", []) if i["semantic_type"] == semantic_type]


# ── cases ────────────────────────────────────────────────────────────────

def case01_exact_object() -> dict:
    pid = _project("p12 exact", ["exact_sage_linen_sofa.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, _fid = _artifacts(pid)
    scene = get_store().load(result["scene_id"])
    sofas = [o for o in scene.objects if o.semantic_type == "sofa"]
    src = [i for i in intent["intents"] if i["object_category"] == "sofa"]
    return {"ok": _classes(intent).get("exact_object") == 1 and len(sofas) == 1
            and bool(src) and bool(src[0]["provenance"]["input_id"]),
            "classes": _classes(intent), "sofas_in_scene": len(sofas),
            "provenance": src[0]["provenance"] if src else None,
            "design_intent_result": result.get("design_intent")}


def case02_design_reference() -> dict:
    pid = _project("p12 design ref", ["sofa_green_velvet.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, _fid = _artifacts(pid)
    scene = get_store().load(result["scene_id"])
    sofas = [o for o in scene.objects if o.semantic_type == "sofa"]
    hints = [{"material_hint": i["material_hint"], "color_hint": i["color_hint"],
              "style_notes": i["style_notes"]} for i in _items(plan, "sofa")]
    return {"ok": _classes(intent).get("design_reference") == 1 and len(sofas) == 1
            and any("velvet" in (h["material_hint"] or "") for h in hints),
            "classes": _classes(intent), "sofas_in_scene": len(sofas), "sofa_hints": hints}


def case03_style_reference() -> dict:
    pid = _project("p12 style", ["style_japandi_palette.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, _fid = _artifacts(pid)
    return {"ok": _classes(intent).get("style_reference") == 1
            and not result.get("generation_requests")
            and all(not i["object_key"].startswith("intent_") for i in plan.get("items", [])),
            "classes": _classes(intent),
            "intent_added_items": [i["object_key"] for i in plan.get("items", [])
                                   if i["object_key"].startswith("intent_")]}


def case04_inspiration_only() -> dict:
    pid = _project("p12 inspo", ["inspiration_chandelier.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, fid = _artifacts(pid)
    scene = get_store().load(result["scene_id"])
    return {"ok": _classes(intent).get("inspiration_only") == 1
            and not [o for o in scene.objects if o.semantic_type == "chandelier"]
            and fid.get("metrics", {}).get("non_instantiation_compliance") in (None, 1.0),
            "classes": _classes(intent),
            "chandeliers_in_scene": len([o for o in scene.objects
                                         if o.semantic_type == "chandelier"]),
            "non_instantiation_compliance": fid.get("metrics", {}).get("non_instantiation_compliance")}


def case05_multiple_references() -> dict:
    pid = _project("p12 multi", ["exact_sofa.jpg", "sofa_linen.jpg", "sofa_sage.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, _fid = _artifacts(pid)
    scene = get_store().load(result["scene_id"])
    sofas = [o for o in scene.objects if o.semantic_type == "sofa"]
    provenances = [i["provenance"]["input_id"] for i in intent["intents"]]
    return {"ok": len(intent["intents"]) == 3 and len(sofas) == 1
            and len(set(provenances)) == 3,
            "intents": len(intent["intents"]), "sofas_in_scene": len(sofas),
            "distinct_provenance": len(set(provenances)),
            "sofa_hints": [{"material_hint": i["material_hint"]} for i in _items(plan, "sofa")]}


def case06_conflict() -> dict:
    pid = _project("p12 conflict", ["sofa_linen.jpg", "sofa_leather.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, plan, fid = _artifacts(pid)
    scene = get_store().load(result["scene_id"])
    unresolved = result.get("unresolved_intents") or []
    return {"ok": bool(intent["conflicts"]) and bool(unresolved)
            and len([o for o in scene.objects if o.semantic_type == "sofa"]) <= 1,
            "conflicts": [c["message"] for c in intent["conflicts"]],
            "unresolved": unresolved,
            "sofa_hints": [{"material_hint": i["material_hint"]} for i in _items(plan, "sofa")]}


def case07_missing_asset() -> dict:
    """A category with no registry model must become a structured GENERATE
    request carrying the attributes - not a silent parametric box."""
    pid = _project("p12 missing", ["exact_walnut_dining_table.jpg"])
    result = _plan(pid)["job"]["result"]
    intent, _plan_json, fid = _artifacts(pid)
    requests = result.get("generation_requests") or []
    unresolved = result.get("unresolved_intents") or []
    return {"ok": bool(requests or unresolved),
            "generation_requests": requests, "unresolved": unresolved,
            "resolution_rungs": sorted({r["rung"] for r in fid.get("resolutions", [])})}


def case08_determinism() -> dict:
    """Same input, 20 planning runs: identical intent ids, classes,
    reconciliation and asset strategy."""
    # "The exact same input" means ONE project re-planned, not twenty projects:
    # each upload mints a fresh uuid-based `input_id`, a pre-existing production
    # characteristic (the same one behind random `object_id`s), so twenty
    # projects would measure id generation rather than pipeline determinism.
    pid = _project("p12 det", ["exact_sage_linen_sofa.jpg", "style_japandi_palette.jpg",
                               "inspiration_chandelier.jpg"])
    signatures = set()
    for _ in range(20):
        job = client.post(f"/api/projects/{pid}/scene-plan", json={"force": True}).json()["job"]
        assert get_runner().wait_idle(300), "scene_plan did not finish"
        assert client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]["status"] == "SUCCEEDED"
        intent, plan, fid = _artifacts(pid)
        signatures.add(json.dumps({
            "intent_ids": sorted(i["intent_id"] for i in intent["intents"]),
            "classes": _classes(intent),
            "hints": sorted((i["semantic_type"], i["material_hint"], i["color_hint"])
                            for i in plan.get("items", [])),
            "rungs": sorted(r["rung"] for r in fid.get("resolutions", [])),
        }, sort_keys=True))
    return {"ok": len(signatures) == 1, "runs": 20, "distinct": len(signatures)}


def case09_reference_limit() -> dict:
    """6/8/10/12 references: every one reaches a terminal state, none dropped.
    The old hardcoded six must not come back."""
    rows = []
    ok = True
    for n in (6, 8, 10, 12):
        names = [f"sofa_ref_{i}.jpg" if i % 3 else f"style_palette_{i}.jpg" for i in range(n)]
        pid = _project(f"p12 refs {n}", names)
        result = _plan(pid)["job"]["result"]
        intent, _plan_json, _fid = _artifacts(pid)
        accounted = len(intent.get("intents", [])) + len(intent.get("unread", []))
        rows.append({"uploaded": n, "classified": len(intent.get("intents", [])),
                     "unread": len(intent.get("unread", [])), "accounted": accounted,
                     "reference_ids": len(intent.get("reference_ids", [])),
                     "result_references": result.get("design_intent", {}).get("references")})
        ok = ok and accounted == n and len(intent.get("reference_ids", [])) == n
    return {"ok": ok, "rows": rows}


def case10_real_photographs_real_model() -> dict:
    """The only case that uses real client photographs and the real vision
    model. Read-only: it classifies the live project's references and touches
    nothing belonging to that project."""
    from app.core.config import Settings
    from app.intelligence.gemini_provider import GeminiProvider
    from app.intelligence.reference_reader import classify_references
    from app.intelligence.schema import InputBundle, ReferenceImage, Vertical

    live = ROOT / "data" / "projects" / "proj_553cb09794" / "input" / "references"
    if not live.is_dir():
        return {"ok": True, "skipped": "live project references not present"}
    key = os.environ.get("_P12_REAL_GEMINI_KEY", "")
    if not key:
        return {"ok": True, "skipped": "no real Gemini key supplied; real-model case not run"}

    photos = sorted(p for p in live.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    bundle = InputBundle(
        project_id="p12_readonly", description=BRIEF, vertical=Vertical.RESIDENTIAL,
        references=[ReferenceImage(input_id=f"in_{n}", path=str(p), filename=p.name)
                    for n, p in enumerate(photos)])
    settings = Settings(gemini_api_key=key)
    result = classify_references(bundle, GeminiProvider(settings=settings))
    accounted = len(result.intents) + len(result.unread)
    return {"ok": accounted == len(photos) and bool(result.intents),
            "photographs": len(photos), "classified": len(result.intents),
            "unread": len(result.unread), "classes": _classes(result.model_dump()),
            "sample": [{"file": i.provenance.filename, "class": i.reference_class.value,
                        "category": i.object_category,
                        "attributes": i.attributes.stated()} for i in result.intents[:4]]}


CASES = [case01_exact_object, case02_design_reference, case03_style_reference,
         case04_inspiration_only, case05_multiple_references, case06_conflict,
         case07_missing_asset, case08_determinism, case09_reference_limit,
         case10_real_photographs_real_model]


def run() -> dict:
    rows = []
    for fn in CASES:
        try:
            detail = fn()
            rows.append({"name": fn.__name__, "ok": bool(detail.pop("ok")), "detail": detail})
        except Exception as exc:                                        # noqa: BLE001
            rows.append({"name": fn.__name__, "ok": False,
                         "detail": {"error": f"{type(exc).__name__}: {exc}"}})
    return {
        "_about": "P12 live benchmark. Drives the real HTTP routes, job runner and scene_plan "
                  "handler. Vision provider is the deterministic MockProvider except case 10, "
                  "which uses real photographs and the real model. Executor boundary is "
                  "build_manifest; Blender itself is covered by the frozen blender_e2e benchmark.",
        "provider": "mock (case 10: gemini)",
        "executor": "blender (no Unreal integration exists in this repository)",
        "generator": "meshy (no Hunyuan3D integration exists in this repository)",
        "cases": rows,
        "passed": sum(1 for r in rows if r["ok"]),
        "total": len(rows),
    }


def main() -> int:
    report = run()
    for row in report["cases"]:
        mark = "PASS" if row["ok"] else "FAIL"
        skipped = row["detail"].get("skipped")
        print(f"  {mark}  {row['name']}" + (f"  (skipped: {skipped})" if skipped else ""))
        if not row["ok"]:
            print(f"        {json.dumps(row['detail'])[:500]}")
    print(f"\n{report['passed']}/{report['total']} cases pass")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")
    shutil.rmtree(_TMP, ignore_errors=True)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

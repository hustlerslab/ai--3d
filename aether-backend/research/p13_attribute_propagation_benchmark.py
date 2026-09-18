"""P13 live benchmark: do the client's words reach the executor boundary?

P12 proved reference -> DesignIntent -> plan on the real path and measured
6 of 10 attribute classes reaching the scene: colour words, pattern, frame
finish and descriptors stopped at the plan because `SceneObject` had nowhere to
put them. This measures the same real path again, now through
`SceneObject.visual` and the manifest row.

Same harness as P12 - real HTTP routes, real job runner, real `scene_plan` -
imported rather than re-implemented. The vision provider is the deterministic
MockProvider (filename-driven, and it says so in every intent's `notes`).

PRESERVED is not RENDERED. A case passes when an attribute SURVIVES to the
scene and the manifest. Whether Blender paints it is a separate, honest axis
reported from `VISUAL_ATTRIBUTE_CONTRACT`: today three attributes are rendered
and four are metadata only, and this benchmark never conflates the two.

    python -u research/p13_attribute_propagation_benchmark.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing P12 first installs the isolated data dir + mock provider env.
from research.p12_design_intent_benchmark import (_artifacts, _plan, _project,  # noqa: E402
                                                  client)

from app.blender.manifest import build_manifest                       # noqa: E402
from app.jobs import get_runner                                       # noqa: E402
from app.planning.intent_fidelity import VISUAL_ATTRIBUTE_CONTRACT    # noqa: E402
from app.projects.layout import project_dir                           # noqa: E402
from app.scene.patches import Patch, UpdateObjectOp, commit_patch     # noqa: E402
from app.scene.store import get_store                                 # noqa: E402

OUT = ROOT.parent / "docs" / "benchmarks" / "p13_visual_attribute_propagation.json"


def _scene_id(pid: str) -> str:
    return client.get(f"/api/projects/{pid}/scene-spec").json()["data"]["scene"]["scene_id"]


def _scene_and_manifest(pid: str):
    result = _plan(pid)["job"]["result"]
    scene = get_store().load(result["scene_id"])
    manifest = build_manifest(scene, project_id=pid, project_root=project_dir(pid), preview=False)
    return result, scene, manifest


def _sofa(scene):
    return next((o for o in scene.objects if o.semantic_type == "sofa"), None)


def _manifest_row(manifest: dict, object_id: str) -> dict:
    return next((o for o in manifest["objects"] if o["id"] == object_id), {})


def _visual_pair(filenames: list[str], semantic_type: str = "sofa"):
    """Plan a project and return (project id, scene object, manifest row, result)."""
    pid = _project(f"p13 {filenames[0][:24]}", filenames)
    result, scene, manifest = _scene_and_manifest(pid)
    obj = next((o for o in scene.objects if o.semantic_type == semantic_type), None)
    row = _manifest_row(manifest, obj.object_id) if obj else {}
    return pid, obj, row, result


# ── cases ────────────────────────────────────────────────────────────────

def case01_colour_word() -> dict:
    _pid, obj, row, _r = _visual_pair(["exact_sage_linen_sofa.jpg"])
    words = obj.visual.color_words if obj else []
    return {"ok": bool(obj) and "sage" in words and row.get("visual", {}).get("color_words") == words
            and bool(row.get("color")),
            "scene_color_words": words, "manifest_color_words": row.get("visual", {}).get("color_words"),
            "rendered_color_hex": row.get("color"),
            "executor": VISUAL_ATTRIBUTE_CONTRACT["color_words"].executor.value}


def case02_pattern() -> dict:
    _pid, obj, row, _r = _visual_pair(["exact_quilted_linen_sofa.jpg"])
    return {"ok": bool(obj) and obj.visual.pattern == "quilted"
            and row.get("visual", {}).get("pattern") == "quilted",
            "scene_pattern": obj.visual.pattern if obj else None,
            "manifest_pattern": row.get("visual", {}).get("pattern"),
            "executor": VISUAL_ATTRIBUTE_CONTRACT["pattern"].executor.value,
            "honest_note": "preserved and traceable; Blender has no pattern synthesis"}


def case03_frame_finish() -> dict:
    _pid, obj, row, _r = _visual_pair(["exact_sofa_dark_walnut_frame.jpg"])
    finish = obj.visual.frame_finish if obj else ""
    return {"ok": bool(obj) and "walnut" in finish
            and row.get("visual", {}).get("frame_finish") == finish,
            "scene_frame_finish": finish,
            "manifest_frame_finish": row.get("visual", {}).get("frame_finish"),
            "executor": VISUAL_ATTRIBUTE_CONTRACT["frame_finish"].executor.value,
            "honest_note": "one material slot per object; a distinct frame material cannot render"}


def case04_descriptors() -> dict:
    _pid, obj, row, _r = _visual_pair(["exact_contemporary_minimal_sofa.jpg"])
    descriptors = obj.visual.descriptors if obj else []
    return {"ok": bool(obj) and bool(descriptors)
            and row.get("visual", {}).get("descriptors") == descriptors,
            "scene_descriptors": descriptors,
            "manifest_descriptors": row.get("visual", {}).get("descriptors"),
            "executor": VISUAL_ATTRIBUTE_CONTRACT["descriptors"].executor.value}


def case05_combined() -> dict:
    """Every attribute must survive INDEPENDENTLY - one present is not proof."""
    _pid, obj, row, _r = _visual_pair(
        ["exact_sage_linen_quilted_contemporary_sofa_dark_walnut_frame.jpg"])
    v = obj.visual if obj else None
    got = {
        "color_words": bool(v and v.color_words),
        "material": bool(v and v.material),
        "pattern": bool(v and v.pattern),
        "frame_finish": bool(v and v.frame_finish),
        "descriptors": bool(v and v.descriptors),
    }
    manifest_visual = row.get("visual", {})
    mirrored = bool(v) and manifest_visual == v.model_dump()
    return {"ok": all(got.values()) and mirrored,
            "survived": got, "manifest_mirrors_scene": mirrored,
            "scene_visual": v.model_dump() if v else None}


def case06_explicit_beats_inferred() -> dict:
    pid, obj, _row, _r = _visual_pair(["exact_linen_sofa.jpg"])
    _intent, plan, _fid = _artifacts(pid)
    sofas = [i for i in plan["items"] if i["semantic_type"] == "sofa"]
    job = client.get(f"/api/projects/{pid}/jobs").json()["data"][0]
    events = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["events"]
    audit = [e["message"] for e in events if e["stage"] == "plan.intent" and "was " in e["message"]]
    return {"ok": bool(obj) and obj.visual.material == "linen"
            and len(sofas) == 1 and all(i["material_hint"] == "linen" for i in sofas),
            "scene_material": obj.visual.material if obj else None,
            "plan_material_hint": [i["material_hint"] for i in sofas],
            "sofa_count": len(sofas), "audit_trail": audit[:3]}


def case07_conflict_stays_explicit() -> dict:
    pid = _project("p13 conflict", ["sofa_linen.jpg", "sofa_leather.jpg"])
    result, scene, _manifest = _scene_and_manifest(pid)
    intent, _plan, _fid = _artifacts(pid)
    obj = _sofa(scene)
    return {"ok": bool(intent["conflicts"]) and bool(result.get("unresolved_intents"))
            and (obj is None or obj.visual.material == ""),
            "conflicts": [c["message"] for c in intent["conflicts"]],
            "unresolved": result.get("unresolved_intents"),
            "scene_material": obj.visual.material if obj else None}


def case08_save_reload() -> dict:
    pid, obj, _row, _r = _visual_pair(["exact_sage_linen_quilted_sofa_dark_walnut_frame.jpg"])
    before = obj.visual.model_dump() if obj else {}
    reloaded = get_store().load(_scene_id(pid))
    after_obj = next((o for o in reloaded.objects if o.object_id == obj.object_id), None)
    after = after_obj.visual.model_dump() if after_obj else {}
    return {"ok": bool(before) and before == after, "before": before, "after": after}


def case09_patch_preserves() -> dict:
    """Editing another field must not wipe what the client said it looks like."""
    pid, obj, _row, _r = _visual_pair(["exact_sage_linen_quilted_sofa.jpg"])
    before = obj.visual.model_dump()
    store = get_store()
    scene_id = _scene_id(pid)
    scene = store.load(scene_id)
    # The real op patches NAMED fields, so `visual` is structurally out of its
    # reach - which is the property worth asserting, not a copy of the object.
    patch = Patch(scene_id=scene_id, base_version=scene.version,
                  operations=[UpdateObjectOp(object_id=obj.object_id, color="#123456")],
                  source="user")
    after_scene = commit_patch(store, patch)
    after_obj = next(o for o in after_scene.objects if o.object_id == obj.object_id)
    return {"ok": after_obj.visual.model_dump() == before and after_obj.color == "#123456",
            "before": before, "after": after_obj.visual.model_dump(),
            "patched_color": after_obj.color}


def case10_retry_checkpoint_deterministic() -> dict:
    """Re-plan the same project 20 times: attributes intact, no duplicates,
    one signature."""
    pid = _project("p13 retry", ["exact_sage_linen_quilted_sofa_dark_walnut_frame.jpg"])
    signatures = set()
    counts = set()
    for _ in range(20):
        job = client.post(f"/api/projects/{pid}/scene-plan", json={"force": True}).json()["job"]
        assert get_runner().wait_idle(300)
        assert client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]["status"] == "SUCCEEDED"
        scene = get_store().load(_scene_id(pid))
        sofas = [o for o in scene.objects if o.semantic_type == "sofa"]
        counts.add(len(sofas))
        signatures.add(json.dumps([o.visual.model_dump() for o in sofas], sort_keys=True))
    return {"ok": len(signatures) == 1 and counts == {1},
            "runs": 20, "distinct_visual": len(signatures), "sofa_counts": sorted(counts)}


CASES = [case01_colour_word, case02_pattern, case03_frame_finish, case04_descriptors,
         case05_combined, case06_explicit_beats_inferred, case07_conflict_stays_explicit,
         case08_save_reload, case09_patch_preserves, case10_retry_checkpoint_deterministic]


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
        "_about": "P13 attribute propagation on the real scene_plan path. PRESERVED is measured "
                  "at the scene and the manifest; RENDERED is a separate axis taken from "
                  "VISUAL_ATTRIBUTE_CONTRACT and never conflated with preservation.",
        "executor_contract": {k: {"scene_field": v.scene_field, "executor": v.executor.value,
                                  "how": v.how} for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()},
        "cases": rows,
        "passed": sum(1 for r in rows if r["ok"]),
        "total": len(rows),
    }


def main() -> int:
    report = run()
    for row in report["cases"]:
        print(f"  {'PASS' if row['ok'] else 'FAIL'}  {row['name']}")
        if not row["ok"]:
            print(f"        {json.dumps(row['detail'], default=str)[:400]}")
    print(f"\n{report['passed']}/{report['total']} cases pass")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

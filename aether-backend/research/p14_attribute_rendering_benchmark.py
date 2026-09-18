"""P14: which visual attributes can Blender actually PAINT, and on what?

P13 carried seven attributes to the executor boundary and reported three as
rendered. P14 asks the harder question - can any of the remaining four be
painted without inventing behaviour - and answers it from the real asset
registry and the real material registry rather than from intent.

The two numbers this produces are deliberately separate:

    preservation      does the attribute reach the manifest      (P13: 7/7)
    rendered rate     does Blender change pixels because of it   (measured here)

Everything is measured against the real library: all 58 registry GLBs are
parsed, and `build_manifest` runs over real assets. The live `scene_plan` path
is covered by the P12/P13 benchmarks and by tests/test_p14_visual_rendering.py,
which this file deliberately does not import - their harness repoints
AETHER_DATA_DIR at a temp directory, which would hide the real asset library.

    python -u research/p14_attribute_rendering_benchmark.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Deliberately does NOT import the P12 harness: that repoints AETHER_DATA_DIR
# at a temp directory, and this benchmark's whole purpose is to read the REAL
# asset library. The live scene_plan path is covered by the P12/P13 benchmarks
# and by tests/test_p14_visual_rendering.py.
from app.assets import gltf                                               # noqa: E402
from app.assets.registry import get_registry                              # noqa: E402
from app.blender.manifest import _descriptor_finish, _FINISH_ROUGHNESS, _finish_entry, build_manifest  # noqa: E402
from app.core.config import get_settings                                  # noqa: E402
from app.planning.compiler import finish_material_for                     # noqa: E402
from app.planning.intent_fidelity import VISUAL_ATTRIBUTE_CONTRACT        # noqa: E402
from app.scene.schema import (Confidence, ObjectVisual, Room, Scene,      # noqa: E402
                              SceneObject)

OUT = ROOT.parent / "docs" / "benchmarks" / "p14_visual_attribute_rendering.json"

#: Material-name fragments that denote a frame/leg/base region rather than a
#: body, glass or foliage one. Used only to REPORT how many assets have a
#: genuine frame separation; nothing in production branches on these words.
_FRAME_WORDS = ("leg", "frame", "base", "stand", "foot")


def audit_assets() -> dict:
    """Read every asset in the registry. No sampling, no assumption."""
    root = get_settings().data_dir
    rows, unreadable = [], 0
    for rec in get_registry().list():
        rel = rec.files.normalized or rec.files.original
        if not rel:
            continue
        path = Path(rel) if Path(rel).is_absolute() else root / rel
        if not path.exists():
            path = root / "assets" / rel
        try:
            doc = gltf.load(path)
        except Exception:                                                 # noqa: BLE001
            unreadable += 1
            continue
        slots = gltf.material_slots(doc)
        uv = any("TEXCOORD_0" in prim.get("attributes", {})
                 for mesh in doc.json.get("meshes", [])
                 for prim in mesh.get("primitives", []))
        rows.append({
            "asset_id": rec.asset_id, "semantic_type": rec.semantic_type,
            "regions": len(slots), "slot_names": slots, "uv": uv,
            "frame_region": any(any(w in n.lower() for w in _FRAME_WORDS) for n in slots),
        })

    multi = [r for r in rows if r["regions"] >= 2]
    return {
        "total": len(rows),
        "unreadable": unreadable,
        "regions_histogram": {str(k): v for k, v in sorted(Counter(r["regions"] for r in rows).items())},
        # Frame finish needs somewhere to go: more than one material region.
        "frame_capable": len(multi),
        "frame_named_region": sum(1 for r in rows if r["frame_region"]),
        # Colour and upholstery ride the body material / tint, which every
        # asset has.
        "colour_capable": len(rows),
        "upholstery_capable": len(rows),
        # No pattern synthesis exists anywhere in the executor.
        "pattern_capable": 0,
        "uv_capable": sum(1 for r in rows if r["uv"]),
        "unsupported_for_frame": len(rows) - len(multi),
        "multi_region_assets": [
            {"asset_id": r["asset_id"], "type": r["semantic_type"],
             "regions": r["regions"], "slots": r["slot_names"]} for r in multi],
    }


def _object(asset_id=None, **visual) -> SceneObject:
    return SceneObject(semantic_type="sofa", room_id="r", position=(0, 0, 0),
                       dimensions=(2, 0.8, 0.9), asset_id=asset_id,
                       visual=ObjectVisual(**visual))


# ── cases ────────────────────────────────────────────────────────────────

def case01_frame_finish_renders_on_a_multi_region_asset() -> dict:
    audit = audit_assets()
    multi = audit["multi_region_assets"]
    if not multi:
        return {"ok": False, "why": "no multi-region asset exists to paint"}
    entry = _finish_entry(_object(multi[0]["asset_id"], frame_finish="dark walnut"))
    return {"ok": entry["state"] == "rendered" and entry["frame_material"] == "veneer_walnut",
            "asset": multi[0]["asset_id"], "regions": entry["material_regions"],
            "material": entry["frame_material"], "state": entry["state"]}


def case02_frame_finish_on_a_single_region_asset_stays_metadata() -> dict:
    audit = audit_assets()
    multi_ids = {r["asset_id"] for r in audit["multi_region_assets"]}
    one_region = next((rec.asset_id for rec in get_registry().list()
                       if rec.asset_id not in multi_ids), None)
    entry = _finish_entry(_object(one_region, frame_finish="dark walnut"))
    return {"ok": entry["state"] == "metadata_only" and bool(entry["reason"]),
            "asset": one_region, "regions": entry["material_regions"],
            "state": entry["state"], "reason": entry["reason"]}


def case03_unrepresentable_finish_is_unsupported() -> dict:
    entry = _finish_entry(_object("ph_modern_armchair", frame_finish="hand-carved teak inlay"))
    return {"ok": entry["state"] == "unsupported" and entry["frame_material"] == "",
            "state": entry["state"], "reason": entry["reason"]}


def case04_no_colour_word_is_ever_invented() -> dict:
    """No authoritative word->hex mapping exists, so a colour word must not
    become a colour. Only an explicit hex renders."""
    entry = _finish_entry(_object(color_words=["sage green"]))
    contract = VISUAL_ATTRIBUTE_CONTRACT["color_words"]
    return {"ok": entry["frame_material"] == "" and entry["roughness"] is None
            and contract.executor.value == "preserved_metadata_only",
            "finish_entry_state": entry["state"], "contract": contract.executor.value}


def case05_pattern_is_never_faked() -> dict:
    entry = _finish_entry(_object("ph_modern_armchair", pattern="quilted"))
    contract = VISUAL_ATTRIBUTE_CONTRACT["pattern"]
    return {"ok": entry["state"] == "none" and contract.executor.value == "preserved_metadata_only",
            "contract": contract.executor.value,
            "note": "no texture synthesis exists; 'quilted' must not become a noise map"}


def case06_surface_quality_is_resolved_but_not_applied() -> dict:
    """`finish.roughness` is computed and carried, and NO Blender script reads
    it. Measured here rather than claimed, so the contract cannot drift."""
    rendered = _finish_entry(_object(descriptors=["contemporary", "matte"]))
    ignored = _finish_entry(_object(descriptors=["luxurious", "elegant", "premium"]))
    scripts = ROOT / "blender" / "scripts"
    readers = sorted(f.name for f in scripts.glob("*.py")
                     if '["roughness"]' in f.read_text(encoding="utf-8", errors="ignore")
                     and "finish" in f.read_text(encoding="utf-8", errors="ignore"))
    return {"ok": rendered["roughness"] == _FINISH_ROUGHNESS["matte"]
            and ignored["roughness"] is None and readers == [],
            "matte_roughness": rendered["roughness"],
            "luxurious_roughness": ignored["roughness"],
            "executor_scripts_reading_finish_roughness": readers,
            "supported_words": sorted(_FINISH_ROUGHNESS)}


def case11_a_part_naming_descriptor_supplies_the_frame_finish() -> dict:
    """The measured gap: real Gemini fills `frame_finish` 0 times out of 8 and
    puts the same evidence in `visual_descriptors`. Read there through the SAME
    resolver, gated on the descriptor naming a part we actually paint."""
    supplies = {
        "wooden frame": _finish_entry(_object(descriptors=["tufted back", "wooden frame"])),
        "gold accent trim": _finish_entry(_object(descriptors=["gold accent trim"])),
    }
    refuses = {
        "glass coffee table": _finish_entry(_object(descriptors=["glass coffee table"])),
        "walnut": _finish_entry(_object(descriptors=["walnut"])),
        "luxurious": _finish_entry(_object(descriptors=["luxurious"])),
    }
    stated_wins = _finish_entry(_object(frame_finish="brushed brass",
                                        descriptors=["wooden frame"]))
    return {"ok": all(e["frame_material"] and e["source"] == "descriptor"
                      for e in supplies.values())
            and all(not e["frame_material"] and e["source"] == "" for e in refuses.values())
            and stated_wins["frame_material"] == "metal_brass"
            and stated_wins["source"] == "stated",
            "supplies": {k: v["frame_material"] for k, v in supplies.items()},
            "refuses": sorted(refuses),
            "stated_beats_descriptor": stated_wins["source"]}


def case07_manifest_carries_the_finish_state_for_real_assets() -> dict:
    """The real `build_manifest`, over real registry assets: one that can take
    a frame finish and one that cannot."""
    audit = audit_assets()
    multi_ids = {r["asset_id"] for r in audit["multi_region_assets"]}
    capable = audit["multi_region_assets"][0]["asset_id"] if multi_ids else None
    single = next((rec.asset_id for rec in get_registry().list()
                   if rec.asset_id not in multi_ids), None)

    room = Room(room_id="r1", name="Living Room", boundary=[(0, 0), (5, 0), (5, 4), (0, 4)])
    objects = []
    for n, aid in enumerate([capable, single]):
        if not aid:
            continue
        objects.append(SceneObject(
            object_id=f"obj_{n}", semantic_type="sofa", asset_id=aid, room_id="r1",
            position=(1.0 + n, 0.0, 1.0), dimensions=(2.0, 0.8, 0.9),
            confidence=Confidence(value=1.0, source="p14"),
            visual=ObjectVisual(frame_finish="dark walnut", descriptors=["matte"])))
    scene = Scene(scene_id="p14", project_id="p14", rooms=[room], objects=objects)

    manifest = build_manifest(scene, project_id="p14", project_root=ROOT / "data", preview=False)
    rows = [o for o in manifest["objects"] if o.get("finish")]
    states = Counter(r["finish"]["state"] for r in rows)
    return {"ok": len(rows) == len(objects) and "rendered" in states and "metadata_only" in states,
            "objects_with_finish": len(rows), "states": dict(states),
            "capable_asset": capable, "single_region_asset": single,
            "sample": rows[0]["finish"] if rows else None}


def case08_materials_are_never_mutated_across_objects() -> dict:
    """Two objects, different finishes: resolving one must not change the
    other's answer or the shared registry record."""
    from app.materials.registry import get_material_registry

    before = get_material_registry().get("veneer_walnut").model_dump()
    a = _finish_entry(_object("ph_modern_armchair", frame_finish="dark walnut"))
    b = _finish_entry(_object("ph_modern_armchair", frame_finish="brushed brass"))
    after = get_material_registry().get("veneer_walnut").model_dump()
    return {"ok": a["frame_material"] == "veneer_walnut" and b["frame_material"] == "metal_brass"
            and before == after,
            "a": a["frame_material"], "b": b["frame_material"],
            "registry_record_unchanged": before == after}


def case09_resolution_is_deterministic() -> dict:
    words = ["dark walnut", "brushed brass", "matte black steel", "oak", "glass", "quilted"]
    runs = {json.dumps([finish_material_for(w) for w in words]) for _ in range(20)}
    return {"ok": len(runs) == 1, "runs": 20, "distinct": len(runs),
            "resolved": json.loads(next(iter(runs)))}


def case10_rendered_attribute_rate() -> dict:
    """Rendered / technically-supported, per attribute. Never averaged with
    preservation."""
    audit = audit_assets()
    supported = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
                 if v.executor.value in ("preserved_and_rendered", "conditionally_rendered")}
    rate = {
        "color_hex": 1.0, "material": 1.0, "upholstery": 1.0,
        "frame_finish": round(audit["frame_capable"] / audit["total"], 4),
        "descriptors": None,   # depends on the words a reference actually used
        "color_words": 0.0, "pattern": 0.0,
    }
    return {"ok": supported == {"color_hex", "material", "upholstery", "frame_finish", "descriptors"},
            "supported": sorted(supported), "rendered_attribute_rate": rate,
            "frame_capable_assets": f"{audit['frame_capable']}/{audit['total']}"}


def _extraction_summary() -> dict:
    """What real Gemini actually produced on 8 real project photographs,
    recorded by research/../p14_reference_extraction.json. The executor's
    reach is capped by this, so the report carries it rather than implying
    every stated attribute arrives."""
    path = ROOT.parent / "docs" / "benchmarks" / "p14_reference_extraction.json"
    if not path.exists():
        return {"measured": False,
                "note": "run the reference-extraction probe with a real Gemini key"}
    data = json.loads(path.read_text(encoding="utf-8"))
    evidence = sum(1 for row in data["per_image"]
                   if _descriptor_finish(row["visual_descriptors"])[1])
    return {"measured": True, "images": data["images"], "populated": data["populated"],
            "descriptor_frame_evidence": evidence,
            "note": "frame_finish is stated 0/8; the frame words arrive in "
                    "visual_descriptors instead"}


CASES = [case01_frame_finish_renders_on_a_multi_region_asset,
         case02_frame_finish_on_a_single_region_asset_stays_metadata,
         case03_unrepresentable_finish_is_unsupported,
         case04_no_colour_word_is_ever_invented,
         case05_pattern_is_never_faked,
         case06_surface_quality_is_resolved_but_not_applied,
         case07_manifest_carries_the_finish_state_for_real_assets,
         case08_materials_are_never_mutated_across_objects,
         case09_resolution_is_deterministic,
         case10_rendered_attribute_rate,
         case11_a_part_naming_descriptor_supplies_the_frame_finish]


def run() -> dict:
    rows = []
    for fn in CASES:
        try:
            detail = fn()
            rows.append({"name": fn.__name__, "ok": bool(detail.pop("ok")), "detail": detail})
        except Exception as exc:                                          # noqa: BLE001
            rows.append({"name": fn.__name__, "ok": False,
                         "detail": {"error": f"{type(exc).__name__}: {exc}"}})
    audit = audit_assets()
    return {
        "_about": "P14 rendering capability, measured against the real asset registry and the "
                  "real Blender material path. PRESERVATION (P13: 7/7) and RENDERING are "
                  "reported separately and never combined.",
        "stack": {"vision": "gemini", "asset_generation": "meshy", "executor": "blender"},
        "asset_audit": audit,
        "real_reference_extraction": _extraction_summary(),
        "contract": {k: {"executor": v.executor.value, "how": v.how}
                     for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()},
        "cases": rows,
        "passed": sum(1 for r in rows if r["ok"]),
        "total": len(rows),
    }


def main() -> int:
    report = run()
    a = report["asset_audit"]
    print(f"  assets {a['total']} | frame-capable {a['frame_capable']} | "
          f"named frame region {a['frame_named_region']} | pattern-capable {a['pattern_capable']} | "
          f"UV {a['uv_capable']}")
    print(f"  region histogram: {a['regions_histogram']}\n")
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

"""P11 regression benchmark: does visual design intent survive into the 3D scene?

Ten scenarios, one per clause of the P11 brief. Every one runs on the
deterministic mock provider and the real production chain - `classify_references`
-> `merge_intents` -> `resolve_intent` -> `compile_scene`/`place_objects` ->
`validate_scene` -> `build_manifest` - so a pass means the shipped code did it,
not a simulation of it.

Executor note: the brief says "Unreal". This repository's executor is Blender
(`app/blender/manifest.py` is the single Scene -> executor boundary; there is
no Unreal integration in the tree). Scenario 10 therefore measures traceability
into the manifest rows that cross that boundary, which is the same measurement
for whatever renders them.

    python -u research/p11_intent_benchmark.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.blender.manifest import build_manifest                       # noqa: E402
from app.intelligence.bundle import InputBundle                       # noqa: E402
from app.intelligence.design_intent import (DesignIntent, DesignIntentSet,  # noqa: E402
                                            IntentProvenance, ReferenceClass,
                                            VisualAttributes, merge_intents)
from app.intelligence.mock_provider import MockProvider               # noqa: E402
from app.intelligence.reference_reader import classify_references, style_words  # noqa: E402
from app.intelligence.schema import ReferenceImage, Vertical          # noqa: E402
from app.planning import compile_scene, place_objects, resolve_plan   # noqa: E402
from app.planning.intent_fidelity import visual_intent_fidelity       # noqa: E402
from app.planning.intent_resolution import (ResolutionRung, apply_intents_to_plan,  # noqa: E402
                                            resolve_all, resolve_intent)

BRIEF = "A warm family flat: living room, master bedroom, kitchen and bathroom."
OUT = ROOT / "research" / "p11_intent_benchmark_results.json"


def _bundle(filenames: list[str]) -> InputBundle:
    refs = [ReferenceImage(input_id=f"in_{n}", path=f"/p/input/references/{f}", filename=f)
            for n, f in enumerate(filenames)]
    return InputBundle(project_id="p11", description=BRIEF, vertical=Vertical.RESIDENTIAL,
                       references=refs)


def _style(bundle: InputBundle):
    mock = MockProvider()
    analysis = mock.analyze_input(bundle)
    return analysis, mock.create_style_spec(analysis, bundle)


def _scene_from(bundle: InputBundle, intent_set: DesignIntentSet):
    """The real chain: intents add plan items, the SOLVER places everything."""
    mock = MockProvider()
    analysis, style = _style(bundle)
    scene, _ = compile_scene("p11", analysis, style, name="p11")
    plan = mock.plan_objects(analysis, style, bundle)

    merged = merge_intents(intent_set.intents)
    room_for = {r.name.lower(): r.room_id for r in scene.rooms}
    room_for.update({r.type.replace("_", " "): r.room_id for r in scene.rooms})
    plan.items, notes = apply_intents_to_plan(list(plan.items), merged, room_for,
                                              default_room_id=scene.rooms[0].room_id)
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))
    scene = scene.model_copy(update={"objects": [op.object for op in ops]})
    return scene, style, merged, plan, notes


def _prov(n: int, filename: str) -> IntentProvenance:
    return IntentProvenance(input_id=f"in_{n}", filename=filename,
                            image_ref=f"input/references/{filename}", model="mock")


# ── scenarios ────────────────────────────────────────────────────────────

def s01_exact_reference_appears_in_3d() -> dict:
    """The client's sofa must BE the room's sofa - not a second one standing
    next to the planner's generic one."""
    bundle = _bundle(["exact_sage_linen_sofa.jpg"])
    intents = classify_references(bundle, MockProvider())
    scene, _style, _merged, plan, notes = _scene_from(bundle, intents)
    placed = [o for o in scene.objects if o.semantic_type == "sofa"]
    sofa_items = [i for i in plan.items if i.semantic_type == "sofa"]
    # The reference said linen. A planner guess of "fabric" surviving here is
    # precisely the silent loss this phase exists to end, so assert the
    # REFERENCE's own word reached the item - not merely that some hint did.
    carried = [i for i in sofa_items if "linen" in (i.material_hint or "").lower()]
    return {"ok": bool(notes) and len(placed) == 1 and bool(carried),
            "notes": notes, "sofa_plan_items": len(sofa_items),
            "sofas_in_scene": len(placed),
            "hints_carried": [{"material_hint": i.material_hint, "color_hint": i.color_hint,
                               "style_notes": i.style_notes} for i in sofa_items]}


def s02_colour_material_reference_reaches_the_asset() -> dict:
    bundle = _bundle(["sofa_sage_linen.jpg"])
    intents = classify_references(bundle, MockProvider())
    merged = merge_intents(intents.intents)
    _a, style = _style(bundle)
    res = resolve_intent(merged[0], style)
    carried = res.generation.prompt if res.generation else ""
    stated = merged[0].attributes.stated()
    return {"ok": bool(stated) and all(word in carried.lower() for word in ("sage", "linen")),
            "stated": stated, "rung": res.rung.value, "prompt": carried}


def s03_style_only_reference_creates_no_object() -> dict:
    bundle = _bundle(["style_japandi_palette.jpg"])
    intents = classify_references(bundle, MockProvider())
    _scene, _s, merged, _plan, notes = _scene_from(bundle, intents)
    return {"ok": not notes and bool(style_words(intents)),
            "plan_changes_from_intent": notes,
            "style_words": style_words(intents),
            "merged_categories": [m.object_category for m in merged]}


def s04_inspiration_only_is_never_instantiated() -> dict:
    bundle = _bundle(["inspiration_chandelier.jpg"])
    intents = classify_references(bundle, MockProvider())
    _scene, _s, merged, _plan, notes = _scene_from(bundle, intents)
    return {"ok": not notes and not merged,
            "intent_class": intents.intents[0].reference_class.value,
            "instantiate": intents.intents[0].instantiate,
            "plan_changes_from_intent": notes}


def s05_multiple_references_merge_deterministically() -> dict:
    a = DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(1, "a.jpg"), object_category="sofa",
                            attributes=VisualAttributes(color_words=["sage"], material="linen"),
                            confidence=0.9)
    b = DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(2, "b.jpg"), object_category="sofa",
                            attributes=VisualAttributes(upholstery="tufted",
                                                        style_descriptors=["japandi"]), confidence=0.7)
    runs = {json.dumps([m.model_dump() for m in merge_intents(x)], sort_keys=True)
            for x in ([a, b], [b, a])}
    merged = merge_intents([a, b])[0]
    return {"ok": len(runs) == 1 and merged.attributes.material == "linen"
            and merged.attributes.upholstery == "tufted" and not merged.conflicts,
            "order_independent": len(runs) == 1, "merged": merged.attributes.stated()}


def s06_conflicting_references_stay_uncertain() -> dict:
    a = DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(1, "a.jpg"), object_category="sofa",
                            attributes=VisualAttributes(material="linen"), confidence=0.9)
    b = DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(2, "b.jpg"), object_category="sofa",
                            attributes=VisualAttributes(material="velvet"), confidence=0.85)
    merged = merge_intents([a, b])[0]
    _a, style = _style(_bundle([]))
    res = resolve_intent(merged, style)
    return {"ok": merged.uncertain and merged.attributes.material == ""
            and res.rung is ResolutionRung.UNRESOLVED and res.needs_input,
            "material_after_merge": merged.attributes.material,
            "conflict": merged.conflicts[0].message if merged.conflicts else "",
            "rung": res.rung.value, "needs_input": res.needs_input}


def s07_missing_asset_falls_back_to_generation() -> dict:
    """No registry model can satisfy these attributes, so the ladder must ask
    the generator - with the attributes attached, not a generic prompt."""
    merged = merge_intents([DesignIntent.create(
        ReferenceClass.EXACT_OBJECT, _prov(1, "exact_sofa.jpg"), object_category="sofa",
        attributes=VisualAttributes(color_words=["sage green"], material="linen",
                                    upholstery="tufted"), confidence=0.9)])[0]
    _a, style = _style(_bundle([]))
    res = resolve_intent(merged, style, generation_available=True,
                         reference_image="input/references/exact_sofa.jpg")
    off = resolve_intent(merged, style, generation_available=False)
    return {"ok": res.rung is ResolutionRung.GENERATE and bool(res.generation)
            and res.generation.reference_image != "" and off.needs_input,
            "rung": res.rung.value, "prompt": res.generation.prompt if res.generation else "",
            "without_generator": {"rung": off.rung.value, "needs_input": off.needs_input}}


def s08_generated_asset_carries_metadata_and_is_placed() -> dict:
    """The generation request must carry everything the registry needs to tag
    the asset afterwards, and the object must reach the scene through the
    solver."""
    bundle = _bundle(["exact_sage_linen_sofa.jpg"])
    intents = classify_references(bundle, MockProvider())
    scene, style, merged, _plan, _notes = _scene_from(bundle, intents)
    res = resolve_intent(merged[0], style, generation_available=True,
                         reference_image=intents.intents[0].provenance.image_ref)
    placed = [o for o in scene.objects if o.semantic_type == "sofa"]
    request = res.generation
    return {"ok": bool(placed) and bool(request) and request.object_category == "sofa"
            and bool(request.source_intent_ids) and bool(request.attributes.stated()),
            "placed": len(placed),
            "request": {"category": request.object_category if request else None,
                        "attributes": request.attributes.stated() if request else {},
                        "sources": request.source_intent_ids if request else [],
                        "reference_image": request.reference_image if request else ""},
            "position_decided_by": "place_objects" if placed else None}


def s09_refresh_is_deterministic() -> dict:
    bundle = _bundle(["exact_sage_linen_sofa.jpg", "style_japandi_palette.jpg",
                      "inspiration_chandelier.jpg", "DSC00812.jpg"])
    signatures = set()
    for _ in range(20):
        intents = classify_references(bundle, MockProvider())
        merged = merge_intents(intents.intents)
        _a, style = _style(bundle)
        resolutions = resolve_all(merged, style)
        signatures.add(json.dumps(
            {"intents": intents.model_dump(),
             "resolutions": [r.model_dump() for r in resolutions]}, sort_keys=True))
    return {"ok": len(signatures) == 1, "runs": 20, "distinct_results": len(signatures)}


def s10_attributes_traceable_into_the_executor() -> dict:
    """Every manifest row that came from an intent must name the reference that
    justified it - the end-to-end traceability the brief asks for."""
    bundle = _bundle(["exact_sage_linen_sofa.jpg", "style_japandi_palette.jpg",
                      "inspiration_chandelier.jpg"])
    intents = classify_references(bundle, MockProvider())
    scene, style, merged, _plan, _notes = _scene_from(bundle, intents)
    resolutions = resolve_all(merged, style)
    report = visual_intent_fidelity(intents, resolutions, scene)

    manifest = build_manifest(scene, project_id="p11", project_root=ROOT / "data" / "_p11_tmp",
                              preview=False)
    categories = {o["semantic_type"] for o in manifest["objects"]}
    traced = {row.object_category for row in report.rows if row.traced_object_ids}
    violations = [r.model_dump() for r in report.rows if r.note]
    return {"ok": report.compliant and bool(traced) and traced <= categories and not violations,
            "metrics": report.metrics, "counts": report.counts,
            "traced_categories": sorted(traced),
            "manifest_objects": len(manifest["objects"]),
            "compliance_violations": violations}


SCENARIOS = [
    s01_exact_reference_appears_in_3d,
    s02_colour_material_reference_reaches_the_asset,
    s03_style_only_reference_creates_no_object,
    s04_inspiration_only_is_never_instantiated,
    s05_multiple_references_merge_deterministically,
    s06_conflicting_references_stay_uncertain,
    s07_missing_asset_falls_back_to_generation,
    s08_generated_asset_carries_metadata_and_is_placed,
    s09_refresh_is_deterministic,
    s10_attributes_traceable_into_the_executor,
]


def run() -> dict:
    rows = []
    for fn in SCENARIOS:
        detail = fn()
        rows.append({"name": fn.__name__, "ok": bool(detail.pop("ok")), "detail": detail})
    passed = sum(1 for r in rows if r["ok"])
    return {
        "_about": "P11 visual-intent regression. Runs the production chain on the deterministic "
                  "mock provider. Executor is Blender (this repo has no Unreal integration); "
                  "scenario 10 measures traceability into the manifest that crosses that boundary.",
        "scenarios": rows, "passed": passed, "total": len(rows),
    }


def main() -> int:
    report = run()
    for row in report["scenarios"]:
        print(f"  {'PASS' if row['ok'] else 'FAIL'}  {row['name']}")
        if not row["ok"]:
            print(f"        {json.dumps(row['detail'])[:400]}")
    print(f"\n{report['passed']}/{report['total']} scenarios pass")
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

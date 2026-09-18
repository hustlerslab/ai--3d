"""Can the CURRENT pipeline represent an element inventory at all?

The element-first proposal rests on one claim: that today the system does not
know how many of each thing a room should contain. That claim is testable
without opinion, by running the real production functions and reading what
comes out.

This is the CURRENT column of the comparison. The ELEMENT-FIRST column is
qwen_capability.py, which measured the same 8 inventories straight from the
brief. Nothing here is asserted - every row is produced by calling shipped code.

    python -u research/element-first/inventory_benchmark.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "aether-backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.intelligence.design_intent import (DesignIntent, IntentProvenance,     # noqa: E402
                                            ReferenceClass, VisualAttributes,
                                            merge_intents)
from app.intelligence.schema import (ObjectPlan, SceneElement,                   # noqa: E402
                                     SceneReading)
from app.intelligence.scene_reading import merge_reading_into_plan              # noqa: E402
from app.planning.intent_resolution import intent_to_plan_item                  # noqa: E402

OUT = Path(__file__).resolve().parent / "benchmark-results.json"
QWEN = Path(__file__).resolve().parent / "qwen-capability.json"

#: The same inventories qwen_capability.py measured, so the two columns compare.
SCENARIOS = [
    {"id": "s1_two_chairs", "expect": {"sofa": 1, "armchair": 2, "coffee_table": 1}},
    {"id": "s2_four_pillows", "expect": {"sofa": 1, "pillow": 4, "rug": 1}},
    {"id": "s3_symmetric_bedroom", "expect": {"bed": 1, "nightstand": 2}},
    {"id": "s4_three_stools", "expect": {"kitchen_island": 1, "bar_stool": 3}},
    {"id": "s5_two_different_chairs", "expect": {"desk": 1, "desk_chair": 1, "armchair": 1}},
    {"id": "s6_lamps_pair", "expect": {"sofa": 1, "coffee_table": 1, "floor_lamp": 2}},
    {"id": "s7_singletons", "expect": {"console_table": 1, "mirror": 1, "bench": 1}},
    {"id": "s8_attributes", "expect": {"sofa": 1, "side_table": 2}},
]

ROOM = "living_room"


def _intent(category: str, n: int) -> DesignIntent:
    """One reference photo of this piece. n distinguishes the photos."""
    return DesignIntent.create(
        ReferenceClass.EXACT_OBJECT,
        IntentProvenance(input_id=f"in_{category}_{n}", filename=f"{category}_{n}.jpg"),
        object_category=category, room_hint=ROOM,
        attributes=VisualAttributes(material="linen"), confidence=0.9)


def current_via_design_intent(expect: dict[str, int]) -> dict:
    """Route A: the client photographs every piece they own.

    Two photographs of two armchairs is the clearest possible statement that
    there are two armchairs. Run the real merge and see what survives.
    """
    intents = [_intent(cat, i) for cat, n in expect.items() for i in range(n)]
    merged = merge_intents(intents)

    produced: dict[str, int] = {}
    for m in merged:
        item = intent_to_plan_item(m, object_key=f"{ROOM}.{m.object_category}.0", room_id=ROOM)
        if item is not None:
            produced[m.object_category] = produced.get(m.object_category, 0) + item.count
    return {"references_in": len(intents), "merged_intents": len(merged), "produced": produced}


def current_via_moodboard_reading(expect: dict[str, int]) -> dict:
    """Route B: the moodboard is read back and its elements become the plan.

    The reader emits one element per visible piece, so two armchairs are two
    rows. Run the real merge and see whether the multiplicity reaches the plan.
    """
    elements = []
    for cat, n in expect.items():
        for i in range(n):
            elements.append(SceneElement(
                element_id=f"el_{cat}_{i}", room_id=ROOM, name=f"{cat} {i}",
                semantic_type=cat, bbox=(0.1 + 0.2 * i, 0.4, 0.2 + 0.2 * i, 0.6),
                check="ok", approved=True))
    reading = SceneReading(elements=elements)
    plan = ObjectPlan(rooms=[ROOM], items=[])
    merged, _notes = merge_reading_into_plan(plan, reading)

    produced: dict[str, int] = {}
    for item in merged.items:
        produced[item.semantic_type] = produced.get(item.semantic_type, 0) + item.count
    return {"elements_in": len(elements), "plan_items": len(merged.items),
            "produced": produced,
            "counts_all_one": all(i.count == 1 for i in merged.items)}


def main() -> int:
    rows = []
    for sc in SCENARIOS:
        expect = sc["expect"]
        a = current_via_design_intent(expect)
        b = current_via_moodboard_reading(expect)
        rows.append({
            "scenario": sc["id"], "expected": expect,
            "route_a_design_intent": a, "route_b_moodboard_reading": b,
            "a_correct": a["produced"] == expect,
            "b_correct": b["produced"] == expect,
        })
        print(f"{sc['id']:24s} expected {expect}")
        print(f"{'':24s} A intent    {a['references_in']:2d} refs -> {a['produced']}"
              f"  {'ok' if rows[-1]['a_correct'] else 'WRONG'}")
        print(f"{'':24s} B moodboard {b['elements_in']:2d} els  -> {b['produced']}"
              f"  {'ok' if rows[-1]['b_correct'] else 'WRONG'}")

    multi = [r for r in rows if any(v > 1 for v in r["expected"].values())]
    summary = {
        "scenarios": len(rows),
        "scenarios_with_a_repeated_element": len(multi),
        "route_a_design_intent_correct": sum(1 for r in rows if r["a_correct"]),
        "route_b_moodboard_reading_correct": sum(1 for r in rows if r["b_correct"]),
        "route_a_correct_on_repeated": sum(1 for r in multi if r["a_correct"]),
        "route_b_correct_on_repeated": sum(1 for r in multi if r["b_correct"]),
    }

    if QWEN.exists():
        q = json.loads(QWEN.read_text(encoding="utf-8"))["summary"]
        summary["element_first_count_accuracy"] = q["count_accuracy"]
        summary["element_first_fully_correct_generations"] = (
            f"{q['generations_fully_correct']}/{q['total_generations']}")
        summary["element_first_model"] = q["model"]
    else:
        summary["element_first_count_accuracy"] = "NOT MEASURED - run qwen_capability.py"

    print("\n-- summary --")
    for k, v in summary.items():
        print(f"  {k:40s} {v}")

    OUT.write_text(json.dumps({
        "_about": "CURRENT inventory representation, measured by calling the shipped "
                  "merge_intents / intent_to_plan_item / merge_reading_into_plan on "
                  "inventories whose ground truth is known. Element-first column comes "
                  "from qwen-capability.json.",
        "summary": summary, "scenarios": rows}, indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Can qwen2.5vl:3b produce the scene specification element-first depends on?

This is implementation gate question 8, and it is the one that decides the
architecture. Element-first moves the object inventory UPSTREAM of the
moodboard: the model must name every element, say how many instances of each
exist, and relate them to one another, from the brief alone, before any image
exists.

If the 3B model cannot do that reliably, element-first does not remove the
inventory problem - it relocates it from "detect objects in a picture" to
"trust a small model's counting", which is not obviously better.

Measured, not assumed:
  structured validity   did valid JSON matching the schema come back
  count accuracy        per-element instance counts vs a stated ground truth
  missing / extra       elements the brief demanded, or invented
  repeatability         same brief run N times - same inventory?
  relationships         did it produce usable spatial relations

Ground truth is deliberately restricted to briefs that state their inventory
in words, so "correct" is a fact about the brief and not my opinion about
interior design.

    python -u research/element-first/qwen_capability.py [runs]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "aether-backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings                                  # noqa: E402
from app.intelligence.ollama_provider import OllamaProvider               # noqa: E402

OUT = Path(__file__).resolve().parent / "qwen-capability.json"

#: The schema element-first would need. Counts and instances are the point;
#: everything else is what P13 already carries.
SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "semantic_type": {"type": "string"},
                    "instance_count": {"type": "integer"},
                    "material": {"type": "string"},
                    "color_words": {"type": "array", "items": {"type": "string"}},
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "relation": {"type": "string"},
                                "target": {"type": "string"},
                            },
                            "required": ["relation", "target"],
                        },
                    },
                },
                "required": ["semantic_type", "instance_count"],
            },
        },
    },
    "required": ["elements"],
}

RELATIONS = {"left_of", "right_of", "front_of", "behind", "beside", "facing",
             "centered_on", "aligned_with", "above", "below", "near",
             "against_wall", "attached_to", "inside"}


def prompt_for(brief: str) -> str:
    return "\n".join([
        "You are specifying the furniture inventory for ONE room, from the brief below.",
        "Return JSON only.",
        "",
        f"BRIEF: {brief}",
        "",
        "For every distinct piece of furniture the brief calls for, return one entry:",
        "  semantic_type   - a single lowercase noun, e.g. sofa, armchair, coffee_table,",
        "                    floor_lamp, pillow, rug, side_table, bed, nightstand",
        "  instance_count  - HOW MANY of that piece exist. An integer, at least 1.",
        "                    Two armchairs is ONE entry with instance_count 2, never two entries.",
        "  material        - only if the brief says so, else empty",
        "  color_words     - only if the brief says so, else empty list",
        "  relations       - where this piece sits relative to ANOTHER semantic_type,",
        f"                    using only: {', '.join(sorted(RELATIONS))}",
        "",
        "Count exactly what the brief asks for. Do not add pieces it did not mention.",
        "Do not split one piece into its parts. A sofa is one element, not a frame",
        "plus cushions plus legs.",
    ])


#: Scenarios whose inventory the brief states outright, so ground truth is a
#: reading of the brief rather than a design judgement.
SCENARIOS = [
    {
        "id": "s1_two_chairs",
        "brief": "A living room with one sofa, two matching armchairs, and one coffee table.",
        "expect": {"sofa": 1, "armchair": 2, "coffee_table": 1},
    },
    {
        # KEPT DELIBERATELY as an adversarial case, not a fair one. The prompt
        # tells the model not to split a piece into its parts, and cushions on a
        # sofa sit exactly on that line. The model drops them most runs. That is
        # the real finding: the part-versus-element boundary is ambiguous, and
        # element-first inherits the ambiguity rather than solving it.
        "id": "s2_four_pillows",
        "brief": "A living room containing a single three-seat sofa with four cushions on it, "
                 "and one rug underneath.",
        "expect": {"sofa": 1, "pillow": 4, "rug": 1},
        "aliases": {"pillow": {"pillow", "cushion", "throw_pillow", "pillows", "cushions"}},
        "adversarial": "part-vs-element boundary",
    },
    {
        "id": "s3_symmetric_bedroom",
        "brief": "A bedroom with one double bed and two nightstands, one on each side of the bed.",
        "expect": {"bed": 1, "nightstand": 2},
        "aliases": {"nightstand": {"nightstand", "bedside_table", "night_stand", "nightstands"}},
    },
    {
        "id": "s4_three_stools",
        "brief": "A kitchen with one island and three bar stools along it.",
        "expect": {"kitchen_island": 1, "bar_stool": 3},
        "aliases": {"kitchen_island": {"kitchen_island", "island", "counter", "kitchen_counter"},
                    "bar_stool": {"bar_stool", "stool", "barstool", "bar_stools"}},
    },
    {
        "id": "s5_two_different_chairs",
        "brief": "A study with one desk, one desk chair, and one separate reading armchair.",
        "expect": {"desk": 1, "desk_chair": 1, "armchair": 1},
        # `reading_armchair` is what the model actually returns, and it is the
        # correct reading of "one separate reading armchair". Its absence here
        # was a scoring bug of mine, not a model error - recorded because the
        # first run of this experiment misattributed 3 failures to Qwen.
        "aliases": {"desk_chair": {"desk_chair", "office_chair", "chair", "task_chair"},
                    "armchair": {"armchair", "reading_chair", "reading_armchair",
                                 "accent_chair", "lounge_chair"}},
    },
    {
        "id": "s6_lamps_pair",
        "brief": "A living room with one sofa, one coffee table, and a pair of floor lamps.",
        "expect": {"sofa": 1, "coffee_table": 1, "floor_lamp": 2},
        "aliases": {"floor_lamp": {"floor_lamp", "lamp", "standing_lamp", "floor_lamps"}},
    },
    {
        "id": "s7_singletons",
        "brief": "A small entry with one console table, one mirror and one bench.",
        "expect": {"console_table": 1, "mirror": 1, "bench": 1},
        "aliases": {"console_table": {"console_table", "console", "side_table", "entry_table"}},
    },
    {
        "id": "s8_attributes",
        "brief": "A living room with one sage green linen sofa and two walnut side tables.",
        "expect": {"sofa": 1, "side_table": 2},
    },
]


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "_").replace("-", "_")


def _match(expected_type: str, produced: str, aliases: dict) -> bool:
    allowed = aliases.get(expected_type, {expected_type})
    p = _norm(produced)
    if p in {_norm(a) for a in allowed}:
        return True
    return p.rstrip("s") == expected_type.rstrip("s")


def score(scenario: dict, payload: dict) -> dict:
    expect = scenario["expect"]
    aliases = scenario.get("aliases", {})
    elements = payload.get("elements") or []

    got: dict[str, int] = {}
    unmatched = []
    for el in elements:
        stype = el.get("semantic_type", "")
        count = el.get("instance_count")
        hit = next((k for k in expect if _match(k, stype, aliases)), None)
        if hit is None:
            unmatched.append(_norm(stype))
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = -1
        # a repeated entry for the same element is itself a defect: sum it so
        # the count comes out wrong rather than silently overwriting
        got[hit] = got.get(hit, 0) + max(n, 0) if hit in got else n

    correct_counts = sum(1 for k, v in expect.items() if got.get(k) == v)
    found = sum(1 for k in expect if k in got)

    relations = [r for el in elements for r in (el.get("relations") or [])]
    bad_relations = [r for r in relations if _norm(r.get("relation")) not in RELATIONS]

    return {
        "expected": expect,
        "produced": got,
        "extra_elements": unmatched,
        "elements_found": found,
        "elements_expected": len(expect),
        "counts_correct": correct_counts,
        "missing": [k for k in expect if k not in got],
        "count_errors": {k: {"expected": v, "got": got.get(k)}
                         for k, v in expect.items() if k in got and got[k] != v},
        "relations": len(relations),
        "invalid_relations": len(bad_relations),
    }


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    settings = get_settings()
    provider = OllamaProvider(settings)
    print(f"model: {settings.ollama_model} | scenarios: {len(SCENARIOS)} | runs each: {runs}\n")

    results = []
    for scenario in SCENARIOS:
        per_run = []
        inventories = []
        for r in range(runs):
            t0 = time.perf_counter()
            status = "OK"
            try:
                payload = provider._generate(prompt_for(scenario["brief"]), SPEC_SCHEMA,
                                             f"qwen_cap.{scenario['id']}")
            except Exception as exc:                                       # noqa: BLE001
                payload, status = {}, f"{type(exc).__name__}: {exc}"
            elapsed = time.perf_counter() - t0
            row = score(scenario, payload)
            row.update({"run": r + 1, "seconds": round(elapsed, 1), "status": status,
                        "valid": status == "OK" and bool(payload.get("elements"))})
            per_run.append(row)
            inventories.append(json.dumps(row["produced"], sort_keys=True))
            flag = "ok  " if row["counts_correct"] == row["elements_expected"] else "MISS"
            print(f"  {scenario['id']:24s} run{r+1} {flag} "
                  f"found {row['elements_found']}/{row['elements_expected']} "
                  f"counts {row['counts_correct']}/{row['elements_expected']} "
                  f"extra {len(row['extra_elements'])} {elapsed:6.1f}s")

        distinct = len(set(inventories))
        results.append({"scenario": scenario["id"], "brief": scenario["brief"],
                        "runs": per_run, "distinct_inventories": distinct,
                        "repeatable": distinct == 1})
        print(f"  {scenario['id']:24s} -> {distinct} distinct inventor(y/ies) over {runs} runs\n")

    flat = [r for s in results for r in s["runs"]]
    total_expected = sum(r["elements_expected"] for r in flat)
    summary = {
        "model": settings.ollama_model,
        "runs_per_scenario": runs,
        "total_generations": len(flat),
        "valid_json_rate": round(sum(1 for r in flat if r["valid"]) / len(flat), 4),
        "element_recall": round(sum(r["elements_found"] for r in flat) / total_expected, 4),
        "count_accuracy": round(sum(r["counts_correct"] for r in flat) / total_expected, 4),
        "generations_fully_correct": sum(
            1 for r in flat if r["counts_correct"] == r["elements_expected"]
                             and not r["extra_elements"]),
        "hallucinated_elements": sum(len(r["extra_elements"]) for r in flat),
        "missing_elements": sum(len(r["missing"]) for r in flat),
        "repeatable_scenarios": sum(1 for s in results if s["repeatable"]),
        "scenarios": len(SCENARIOS),
        "relations_produced": sum(r["relations"] for r in flat),
        "invalid_relations": sum(r["invalid_relations"] for r in flat),
        "median_seconds": round(statistics.median(r["seconds"] for r in flat), 1),
        "common_hallucinations": Counter(
            x for r in flat for x in r["extra_elements"]).most_common(10),
    }

    print("-- summary --")
    for k, v in summary.items():
        print(f"  {k:28s} {v}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"_about": "Gate Q8: can qwen2.5vl:3b specify the element "
                                         "inventory element-first requires, from the brief alone?",
                               "summary": summary, "results": results},
                              indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

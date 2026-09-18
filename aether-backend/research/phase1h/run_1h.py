"""Phase 1h: the frozen 7B wall gate against the Phase 1g dataset.

    python -u research/phase1h/run_1h.py [--runs 2]

Research only. Reads the Phase 1g dataset and the 1e/1f raw files; writes only
into research/phase1h/. Nothing in app/ is modified and no earlier artefact is
rewritten.

FROZEN, and imported rather than restated: `_wall_a`, `BINARY_SCHEMA`, `_images`
and `MODE` all come from the Phase 1d/1e modules, so the prompt text, the schema,
the image handling and the temperature are the same objects Phase 1e and 1f ran.
The only thing that changed is the dataset.

ONE CONSTRUCTION WAS UNAVOIDABLE, and it is the thing to check first. The frozen
prompt renders `{desc} (a {type})`, and the Phase 1g cases carry no `desc` - they
were annotated with ids, boxes and categories. So a description has to be
supplied, and where it comes from matters enormously:

* `annotations.json` DOES hold prose for every case - "stands on the rug in open
  floor", "the bed behind it is against the wall". Using it would put the ground
  truth INTO THE PROMPT. It is not used here, anywhere, for any purpose.
* Instead each Phase 1g case gets a description computed from its bounding box
  alone: where it sits in the frame, and an ordinal when a scene holds more than
  one piece of the same type. Position only; nothing about walls, floors,
  adjacency or spacing.
* The 11 preserved positives keep their ORIGINAL fixture descriptions, so they
  remain the same strings Phase 1e and 1f sent.

That asymmetry - terse computed descriptions for the negatives, the historical
prose for the positives - is a second confound stacked on the source-domain one,
and it is reported rather than smoothed over. The exact string sent for every
case is recorded in raw.json so it can be audited.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence.ollama_provider import OllamaProvider              # noqa: E402
from research.phase1d_binary_relations import _stats, confusion          # noqa: E402
from research.phase1e_qwen7b_wall import (                               # noqa: E402
    MODELS, ask_wall, gpu, load_model, system_ram)

DATASET = ROOT / "research" / "phase1g" / "dataset.json"
ANNOTATIONS = ROOT / "research" / "phase1g" / "annotations.json"
FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
BENCH = ROOT.parent / "docs" / "benchmarks"
RAW = HERE / "raw.json"
RESULTS = HERE / "results.json"


def wilson(successes: int, total: int):
    """95% Wilson interval in percent. Wilson because the normal approximation
    runs outside 0-100 at these counts."""
    if not total:
        return None
    z = 1.959963985
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return [round(100 * max(0.0, centre - half), 1),
            round(100 * min(1.0, centre + half), 1)]


def build_descriptions(cases: list[dict]) -> dict[str, str]:
    """A `desc` for every case, from the box and nothing else.

    Position in frame, plus an ordinal when a scene holds several pieces of the
    same type (four bar stools at one counter would otherwise all read "centre
    of frame" and the question would be ambiguous). Deliberately says nothing
    about walls, floor, spacing or neighbours.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    original = {o["id"]: o["desc"] for room in fixture["rooms"] for o in room["objects"]}

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for case in cases:
        if case["origin"] == "phase1g":
            groups[(case["scene_id"], case["object_type"])].append(case)

    out: dict[str, str] = {}
    for case in cases:
        if case["origin"] != "phase1g":
            # Preserved positives keep the exact string Phase 1e/1f sent.
            out[case["case_id"]] = original[case["object_id"]]
            continue
        x1, y1, x2, y2 = case["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        horiz = "left" if cx < 704 / 3 else ("right" if cx > 2 * 704 / 3 else "centre")
        depth = ("in the foreground" if cy > 0.62 * 448
                 else ("towards the back" if cy < 0.42 * 448 else ""))
        siblings = groups[(case["scene_id"], case["object_type"])]
        if len(siblings) > 1:
            order = sorted(siblings, key=lambda c: c["bbox"][0])
            nth = ["first", "second", "third", "fourth", "fifth", "sixth"][
                order.index(case)]
            desc = f"{nth} from the left"
        else:
            desc = f"{horiz} of the frame"
        if depth:
            desc = f"{desc}, {depth}"
        out[case["case_id"]] = desc
    return out


def metrics(pairs) -> dict:
    """pairs of (truth_against_wall, answer)."""
    out = confusion(pairs)
    negatives = out["no_truth"]
    out["false_wall_rate"] = (None if not negatives
                              else round(100.0 * out["fp"] / negatives, 1))
    out["false_wall_ci95"] = wilson(out["fp"], negatives) if negatives else None
    out["no_recall_ci95"] = wilson(out["tn"], negatives) if negatives else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()

    data = json.loads(DATASET.read_text(encoding="utf-8"))
    ann = {a["case_id"]: a
           for a in json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["cases"]}
    # Deterministic ordering, identical between runs: dataset order as written.
    cases = list(data["cases"])
    descs = build_descriptions(cases)

    provider = OllamaProvider()
    environment = {"gpu_before": gpu(), "ram_before": system_ram(),
                   "temperature": 0.2,
                   "num_ctx": provider._settings.ollama_num_ctx,
                   "num_predict": provider._settings.ollama_num_predict,
                   "image_max_px": provider._settings.ollama_scene_image_max_px,
                   "prompt": "phase1d _wall_a, imported unmodified",
                   "quantisation": "Q4_K_M",
                   "desc_source": {
                       "phase1g_negatives": "computed from bbox: position in frame "
                                            "plus an ordinal within same-type "
                                            "siblings. Never from annotations.json.",
                       "preserved_positives": "original fixture desc, identical to "
                                              "Phase 1e/1f"}}

    negatives = [c for c in cases if not c["ground_truth_against_wall"]]
    positives = [c for c in cases if c["ground_truth_against_wall"]]
    print(f"dataset: {len(cases)} cases  ({len(positives)} positive, "
          f"{len(negatives)} negative: "
          f"A={sum(1 for c in negatives if c['category'] == 'A')}, "
          f"B={sum(1 for c in negatives if c['category'] == 'B')})\n", flush=True)

    model = MODELS["7b"]
    info = load_model(provider, model)
    res = info.get("residency", {})
    print(f"== {model}  load {info.get('load_s')}s  VRAM {res.get('vram_gb')} GB  "
          f"CPU {res.get('cpu_gb')} GB  on-GPU {res.get('on_gpu_pct')}%\n", flush=True)

    runs = []
    for run_no in range(1, args.runs + 1):
        rows = []
        for case in cases:
            room = {"room_type": case["room_type"], "image": case["image_path"],
                    "room_key": case["scene_id"]}
            obj = {"id": case["object_id"], "type": case["object_type"],
                   "desc": descs[case["case_id"]], "bbox": case["bbox"]}
            row = ask_wall(provider, room, obj)
            row.update(case_id=case["case_id"], scene_id=case["scene_id"],
                       category=case["category"], origin=case["origin"],
                       truth=case["ground_truth_against_wall"],
                       prompt_desc=obj["desc"])
            rows.append(row)
            mark = "ok " if row["answer"] == case["ground_truth_against_wall"] else "  x"
            print(f"  {mark} run{run_no} [{case['category'] or 'P'}] "
                  f"{case['case_id']:34} -> {str(row['answer']):5} "
                  f"(truth {case['ground_truth_against_wall']}) {row['elapsed_s']}s",
                  flush=True)
        neg_pairs = [(r["truth"], r["answer"]) for r in rows if r["truth"] is False]
        summary = metrics(neg_pairs)
        summary.update(run=run_no, rows=rows,
                       latency=_stats([r["elapsed_s"] for r in rows]),
                       first_query_s=rows[0]["elapsed_s"],
                       failed=sum(1 for r in rows if r["answer"] is None))
        runs.append(summary)
        print(f"  -- run{run_no} negatives: TN{summary['tn']} FP{summary['fp']}  "
              f"NO-recall {summary['no_recall']}%  false-wall "
              f"{summary['false_wall_rate']}%\n", flush=True)

    # ── pooled over this phase's runs only ──────────────────────────────
    def pooled(keep) -> dict:
        pairs = []
        for run in runs:
            for row in run["rows"]:
                if keep(row):
                    pairs.append((row["truth"], row["answer"]))
        return metrics(pairs)

    results = {
        "negatives_all": pooled(lambda r: r["truth"] is False),
        "category_A": pooled(lambda r: r["truth"] is False and r["category"] == "A"),
        "category_B": pooled(lambda r: r["truth"] is False and r["category"] == "B"),
        "positives_descriptive_only": pooled(lambda r: r["truth"] is True),
        "all_cases_descriptive_only": pooled(lambda r: True),
    }

    # ── stability, per case and per category ────────────────────────────
    per_case = []
    for index, case in enumerate(cases):
        answers = [run["rows"][index]["answer"] for run in runs]
        per_case.append({
            "case_id": case["case_id"], "scene_id": case["scene_id"],
            "object_type": case["object_type"], "category": case["category"],
            "origin": case["origin"], "truth": case["ground_truth_against_wall"],
            "run1": answers[0], "run2": answers[1] if len(answers) > 1 else None,
            "answers": answers, "stable": len(set(answers)) == 1,
        })

    def agreement(rows) -> dict:
        if not rows:
            return {"cases": 0, "stable": 0, "flipped": 0, "agreement_pct": None}
        stable = sum(1 for r in rows if r["stable"])
        return {"cases": len(rows), "stable": stable,
                "flipped": len(rows) - stable,
                "agreement_pct": round(100.0 * stable / len(rows), 1)}

    neg_rows = [r for r in per_case if r["truth"] is False]
    stability = {
        "negatives_all": agreement(neg_rows),
        "category_A": agreement([r for r in neg_rows if r["category"] == "A"]),
        "category_B": agreement([r for r in neg_rows if r["category"] == "B"]),
        "positives": agreement([r for r in per_case if r["truth"] is True]),
        "all_cases": agreement(per_case),
    }

    # ── every false wall, with its annotation evidence ──────────────────
    false_walls = []
    for row in per_case:
        if row["truth"] is not False:
            continue
        if not any(a is True for a in row["answers"]):
            continue
        a = ann.get(row["case_id"], {})
        false_walls.append({
            "case_id": row["case_id"], "scene_id": row["scene_id"],
            "object_type": row["object_type"], "category": row["category"],
            "run1": row["run1"], "run2": row["run2"],
            "wall_visible": a.get("wall_visible"),
            "wall_backed_mass": a.get("wall_backed_mass_present"),
            "occlusion": a.get("visual_occlusion"),
            "annotation_notes": a.get("annotation_notes"),
        })

    # ── Phase 1e / 1f reference, read only, kept separate ───────────────
    history = {}
    for tag, path in (("1e", BENCH / "phase_1e_raw.json"),
                      ("1f", BENCH / "phase_1f_raw.json")):
        if not path.is_file():
            continue
        blob = json.loads(path.read_text(encoding="utf-8"))
        combined = (blob["models"]["7b"]["combined"] if tag == "1e"
                    else blob["subsets_pooled"]["negatives_only"])
        history[tag] = {"negative_objects": 5,
                        "false_wall_rate": combined.get("false_wall_rate"),
                        "no_recall": combined.get("no_recall"),
                        "tn": combined.get("tn"), "fp": combined.get("fp")}

    every = [r for run in runs for r in run["rows"]]
    report = {
        "environment": environment, "model_load": info,
        "ram_after": system_ram(), "gpu_after": gpu(),
        "dataset": {"cases": len(cases), "positives": len(positives),
                    "negatives": len(negatives),
                    "category_A": sum(1 for c in negatives if c["category"] == "A"),
                    "category_B": sum(1 for c in negatives if c["category"] == "B"),
                    "scenes": len({c["scene_id"] for c in negatives}),
                    "source": "research/phase1g/dataset.json, unmodified"},
        "prompt_inputs": [{"case_id": c["case_id"], "desc": descs[c["case_id"]],
                           "type": c["object_type"], "room_type": c["room_type"]}
                          for c in cases],
        "runs": runs,
    }
    HERE.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(report, indent=2), encoding="utf-8")

    RESULTS.write_text(json.dumps({
        "results": results, "stability": stability, "per_case": per_case,
        "false_walls": false_walls, "history_reference": history,
        "reliability": {
            "queries": len(every),
            "valid_json": sum(1 for r in every if r["answer"] is not None),
            "failed": sum(1 for r in every if r["answer"] is None),
            "status": dict(Counter(r["status"] for r in every))},
        "latency": {"all": _stats([r["elapsed_s"] for r in every]),
                    "cold_first_query_s": runs[0]["first_query_s"]},
        "caveats": [
            "The 32 negatives are generated SD 1.5 images from the project's own "
            "provider; the 11 positives are historical images. Positive-vs-negative "
            "metrics are source-domain confounded and are descriptive only.",
            "Negatives were described to the model by frame position computed from "
            "their bounding box; positives kept their original prose descriptions. "
            "That is a second, independent confound on any cross-class comparison.",
        ],
    }, indent=2), encoding="utf-8")

    print("=" * 74)
    for name in ("negatives_all", "category_A", "category_B"):
        s = results[name]
        print(f"  {name:16} n={s['n']:3} TN{s['tn']:3} FP{s['fp']:3}  NO-recall="
              f"{s['no_recall']}% {s['no_recall_ci95']}  false-wall="
              f"{s['false_wall_rate']}% {s['false_wall_ci95']}")
    print()
    for name, st in stability.items():
        print(f"  stability {name:16} {st['agreement_pct']}%  "
              f"({st['flipped']} of {st['cases']} flipped)")
    print(f"\n  false walls: {len(false_walls)} distinct cases  "
          f"(A={sum(1 for f in false_walls if f['category'] == 'A')}, "
          f"B={sum(1 for f in false_walls if f['category'] == 'B')})")
    print(f"  wrote {RAW}\n  wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

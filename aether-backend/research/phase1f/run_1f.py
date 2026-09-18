"""Phase 1f: is the 7B wall failure general, or is it wall-backed context?

    python -u research/phase1f/run_1f.py [--runs 2]

Research only. Imports production code, writes nothing into it. Phase 1e raw
data is read for pooling and never rewritten.

THE BRIEF'S METHOD IS PARTLY BLOCKED, and that is the first finding rather than
a footnote. Phase 1f was to expand the negative set to >=25 so the false-wall
rate could be measured with a usable confidence interval. All 11 moodboard
renders and all 8 reference photos were examined; they support **5** negatives.
Interiors are photographed with the furniture against the walls, and the
reference photos are product shots of sofas and mattresses, two of them on a
white background with no wall in frame. The accounting, case by case, is in the
report and in `case_categories.json`. Nothing was invented to reach a count.

So the two objectives separate:

* **Objective A - what is the false-wall rate really?** BLOCKED. With 5 distinct
  objects the sampling error lives in *which objects were chosen*, and repeating
  the run does not touch that. More runs shrink measurement noise, not the
  interval that matters.
* **Objective B - general inability, or wall-backed context confusion?**
  ANSWERABLE, and it is the phase's primary diagnostic question. It needs the
  per-object answer to be *reliable*, which repetition does address.

So: 2 fresh runs as the protocol specifies, pooled with Phase 1e's 2 runs for the
per-object reliability table - same 16 cases, same prompt, same model, same
settings, so the pooling is legitimate and is stated wherever it is used.

Everything is frozen from Phase 1e: model, quantisation, temperature, prompt
function, schema, image handling. The prompt is imported, not copied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence.ollama_provider import OllamaProvider              # noqa: E402
from research.phase1d_binary_relations import _stats, confusion          # noqa: E402
from research.phase1e_qwen7b_wall import (                               # noqa: E402
    MODELS, OUT_DIR, ask_wall, gpu, load_model, system_ram, wall_cases)

FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
CATEGORIES = HERE / "case_categories.json"
PHASE_1E = OUT_DIR / "phase_1e_raw.json"
TARGET_NEGATIVES = 25


def wilson(successes: int, total: int):
    """95% Wilson interval, in percent.

    Reported because the whole point of the phase was to narrow this, and a
    point estimate from five objects would imply a precision the data does not
    have. Wilson rather than normal-approximation: at n this small the normal
    interval runs past 0 and 100.
    """
    if not total:
        return None
    z = 1.959963985
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return [round(100 * max(0.0, centre - half), 1),
            round(100 * min(1.0, centre + half), 1)]


def subset_metrics(pairs) -> dict:
    """pairs of (truth_wall, answer). Adds the false-wall rate and its interval."""
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

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cats = json.loads(CATEGORIES.read_text(encoding="utf-8"))
    by_cat = {n["id"]: n for n in cats["negatives"]}
    cases = wall_cases(fixture)
    positives = sum(1 for _r, t, _o in cases if t["wall"] is True)
    negatives = sum(1 for _r, t, _o in cases if t["wall"] is False)

    def cat_of(obj) -> str:
        return by_cat.get(obj["id"], {}).get("category", "-")

    provider = OllamaProvider()
    environment = {"gpu_before": gpu(), "ram_before": system_ram(),
                   "temperature": 0.2,
                   "num_ctx": provider._settings.ollama_num_ctx,
                   "num_predict": provider._settings.ollama_num_predict,
                   "image_max_px": provider._settings.ollama_scene_image_max_px,
                   "prompt": "phase1d _wall_a, imported unmodified via phase1e",
                   "quantisation": "Q4_K_M"}

    print(f"dataset: {len(cases)} cases ({positives} positive, {negatives} negative)")
    print(f"BLOCKER: brief asked for >={TARGET_NEGATIVES} negatives; imagery "
          f"supports {negatives}. See report.\n", flush=True)

    model = MODELS["7b"]
    info = load_model(provider, model)
    res = info.get("residency", {})
    print(f"== {model}  load {info.get('load_s')}s  VRAM {res.get('vram_gb')} GB  "
          f"CPU {res.get('cpu_gb')} GB  on-GPU {res.get('on_gpu_pct')}%\n", flush=True)

    runs = []
    for run_no in range(1, args.runs + 1):
        rows = []
        for room, truth, obj in cases:
            row = ask_wall(provider, room, obj)
            rows.append(row)
            mark = "ok " if row["answer"] == truth["wall"] else "  x"
            print(f"  {mark} run{run_no} [{cat_of(obj)}] {obj['id']:34} -> "
                  f"{str(row['answer']):5} (truth {truth['wall']}) "
                  f"{row['elapsed_s']}s", flush=True)
        pairs = [(t["wall"], r["answer"]) for r, (_rm, t, _o) in zip(rows, cases)]
        summary = subset_metrics(pairs)
        summary.update(run=run_no, rows=rows,
                       latency=_stats([r["elapsed_s"] for r in rows]),
                       first_query_s=rows[0]["elapsed_s"],
                       valid_json=sum(1 for r in rows if r["answer"] is not None),
                       failed=sum(1 for r in rows if r["answer"] is None))
        runs.append(summary)
        print(f"  -- run{run_no}: acc {summary['accuracy']}%  NO-recall "
              f"{summary['no_recall']}%  false-wall {summary['false_wall_rate']}%\n",
              flush=True)

    # ── pool this phase's runs with Phase 1e's, same 16 cases and settings ──
    pooled_rows = [r["rows"] for r in runs]
    pooled_source = [f"1f_run{r['run']}" for r in runs]
    phase1e = {}
    if PHASE_1E.is_file():
        e = json.loads(PHASE_1E.read_text(encoding="utf-8"))
        for r in e["models"]["7b"]["runs"]:
            pooled_rows.append(r["rows"])
            pooled_source.append(f"1e_run{r['run']}")
        phase1e = {"combined": e["models"]["7b"]["combined"],
                   "load": e["models"]["7b"]["load"]}

    def pairs_for(keep):
        out = []
        for rows in pooled_rows:
            for row, (_rm, truth, obj) in zip(rows, cases):
                if keep(truth, obj):
                    out.append((truth["wall"], row["answer"]))
        return out

    subsets = {
        "all_cases": subset_metrics(pairs_for(lambda t, o: True)),
        "negatives_only": subset_metrics(pairs_for(lambda t, o: t["wall"] is False)),
        "category_A": subset_metrics(
            pairs_for(lambda t, o: t["wall"] is False and cat_of(o) == "A")),
        "category_B": subset_metrics(
            pairs_for(lambda t, o: t["wall"] is False and cat_of(o) == "B")),
    }

    # ── per-case confusion analysis (section 7) ─────────────────────────
    per_case = []
    for index, (_room, truth, obj) in enumerate(cases):
        answers = {src: rows[index]["answer"]
                   for src, rows in zip(pooled_source, pooled_rows)}
        ann = by_cat.get(obj["id"], {})
        per_case.append({
            "object": obj["id"], "type": obj["type"],
            "category": ann.get("category", "-"),
            "ground_truth_wall": truth["wall"],
            "answers": answers,
            "stable_across_runs": len(set(answers.values())) == 1,
            "wall_behind_object": ann.get("wall_behind_object"),
            "wall_backed_object_immediately_behind":
                ann.get("wall_backed_object_immediately_behind"),
            "visually_touching_wall": ann.get("visually_touching_wall"),
            "visually_separated_from_wall": ann.get("visually_separated_from_wall"),
            "occlusion": ann.get("occlusion"),
        })

    report = {
        "blocker": {
            "required_negatives": TARGET_NEGATIVES,
            "available_negatives": negatives,
            "objective_A_false_wall_rate": "BLOCKED - 5 distinct objects cannot "
                                           "resolve a 20% gate; repetition does not "
                                           "reduce sampling error over objects",
            "objective_B_category_confusion": "ANSWERABLE - reported below",
            "sources_examined": "11 moodboard renders + 8 reference photos",
            "rejected_candidates": cats["rejected_candidates"],
        },
        "environment": environment,
        "model_load": info,
        "ram_after": system_ram(),
        "gpu_after": gpu(),
        "dataset": {"cases": len(cases), "positives": positives,
                    "negatives": negatives,
                    "category_A": sum(1 for _r, t, o in cases
                                      if t["wall"] is False and cat_of(o) == "A"),
                    "category_B": sum(1 for _r, t, o in cases
                                      if t["wall"] is False and cat_of(o) == "B"),
                    "unchanged_from_phase_1d_1e": True},
        "runs_this_phase": runs,
        "pooled_sources": pooled_source,
        "subsets_pooled": subsets,
        "per_case": per_case,
        "phase_1e_reference": phase1e,
        "latency": {"this_phase": _stats([r["elapsed_s"] for run in runs
                                          for r in run["rows"]])},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "phase_1f_raw.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 72)
    for name, s in subsets.items():
        print(f"  {name:16} n={s['n']:3} acc={s['accuracy']}%  NO-recall="
              f"{s['no_recall']}% {s['no_recall_ci95']}  false-wall="
              f"{s['false_wall_rate']}% {s['false_wall_ci95']}")
    print(f"\n  pooled over {len(pooled_rows)} runs: {pooled_source}")
    unstable = [c["object"] for c in per_case if not c["stable_across_runs"]]
    print(f"  cases unstable across runs: {unstable or 'none'}")
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

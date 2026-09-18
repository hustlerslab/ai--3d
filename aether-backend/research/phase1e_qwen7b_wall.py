"""Phase 1e: is the wall gate a capacity problem? 3B vs 7B, one question only.

    python -u research/phase1e_qwen7b_wall.py [--runs 2] [--skip-3b]

Research only. Imports production code, writes nothing into it.

Phase 1d asked `qwen2.5vl:3b` whether each of sixteen pieces was against a wall
and got `true` sixteen times - eleven right by luck of the distribution, five
wrong, and not one of the five open-floor pieces identified. Every reformulation
available had already been spent on it: binary output, frozen prompt, no
competing candidate list, schema-constrained, 100% valid JSON.

So the remaining untested variable is the model. This changes exactly one thing -
`provider.model` - and holds everything else fixed: same sixteen examples, same
frozen prompt A, same `{"answer": bool}` schema, same temperature, same image
handling. The prompt is IMPORTED from the Phase 1d module rather than copied, so
it cannot drift between the two arms.

Run twice per model, because Phase 1d showed the answer is not deterministic on a
five-example negative set and one run cannot tell a real change from noise. Both
runs are reported; neither is averaged away.

The 3B arm is re-run here rather than quoted, so both models are measured the
same number of times in the same session on the same machine. The Phase 1d
figures are loaded alongside for continuity, not substituted for it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence.ollama_provider import OllamaError, OllamaProvider   # noqa: E402
# The prompt, schema and image handling are IMPORTED, never restated: a copy
# could drift, and then this would be a prompt experiment wearing a model
# experiment's name.
from research.phase1d_binary_relations import (                           # noqa: E402
    BINARY_SCHEMA, MODE, _images, _stats, _wall_a, confusion)

FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
OUT_DIR = ROOT.parent / "docs" / "benchmarks"
PHASE_1D = OUT_DIR / "phase_1d_raw.json"

MODELS = {"7b": "qwen2.5vl:7b", "3b": "qwen2.5vl:3b"}
OLLAMA = "http://127.0.0.1:11434"


def wall_cases(fixture: dict) -> list[tuple[dict, dict, dict]]:
    """Exactly the Phase 1d wall examples - same rows, same order, no additions
    and no removals. Selected by the same predicate Phase 1d scored on."""
    out = []
    for room in fixture["rooms"]:
        by_id = {o["id"]: o for o in room["objects"]}
        for truth in room.get("binary_relations", []):
            if (truth["chain"] == "against" and truth["verdict"] == "TRUE"
                    and truth.get("wall") is not None):
                out.append((room, truth, by_id[truth["source"]]))
    return out


def unload(model: str) -> None:
    try:
        httpx.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0},
                   timeout=60)
    except httpx.HTTPError:
        pass


def residency(model: str) -> dict:
    """What Ollama actually did with the weights.

    A 5.97 GB model on a 6 GB card does not fit, and Ollama silently puts the
    remainder on the CPU. Reporting "we ran the 7B model" without this number
    would hide the reason it is slow.
    """
    try:
        data = httpx.get(f"{OLLAMA}/api/ps", timeout=10).json()
    except httpx.HTTPError:
        return {}
    for entry in data.get("models", []):
        if model in entry.get("name", ""):
            total, vram = entry.get("size", 0), entry.get("size_vram", 0)
            return {"total_gb": round(total / 1e9, 2),
                    "vram_gb": round(vram / 1e9, 2),
                    "cpu_gb": round((total - vram) / 1e9, 2),
                    "on_gpu_pct": round(100.0 * vram / total, 1) if total else None}
    return {}


def gpu() -> dict:
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"], capture_output=True, text=True,
            timeout=20)
        name, total, used, free = [p.strip() for p in out.stdout.strip().split(",")]
        return {"name": name, "vram_total_mib": int(total),
                "vram_used_mib": int(used), "vram_free_mib": int(free)}
    except Exception:                                             # noqa: BLE001
        return {}


def system_ram() -> dict:
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        stat = MS()
        stat.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return {"total_gb": round(stat.ullTotalPhys / 1e9, 1),
                "available_gb": round(stat.ullAvailPhys / 1e9, 1),
                "load_pct": stat.dwMemoryLoad}
    except Exception:                                             # noqa: BLE001
        return {}


def load_model(provider: OllamaProvider, model: str) -> dict:
    """Swap the model in and time it, with the other one evicted first."""
    for other in MODELS.values():
        if other != model:
            unload(other)
    unload(model)
    provider.model = model
    started = time.perf_counter()
    try:
        httpx.post(f"{OLLAMA}/api/generate",
                   json={"model": model, "prompt": "hi", "stream": False,
                         "options": {"num_predict": 1}}, timeout=900)
    except httpx.HTTPError as exc:
        return {"error": str(exc)[:200]}
    elapsed = round(time.perf_counter() - started, 1)
    return {"load_s": elapsed, "residency": residency(model), "gpu_after": gpu()}


def ask_wall(provider: OllamaProvider, room: dict, obj: dict) -> dict:
    """One wall question. Prompt, schema and images are Phase 1d's, unmodified."""
    prompt = _wall_a(room, obj)
    images = _images(provider, MODE["against"], room, obj, ROOT / room["image"])
    row = {"source": obj["id"], "room": room["room_key"]}
    started = time.perf_counter()
    try:
        payload, status = provider._generate_traced(
            prompt, BINARY_SCHEMA, "binary:wall", images=images, array_key=None)
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        answer = (payload or {}).get("answer")
        row["answer"] = answer if isinstance(answer, bool) else None
        row["status"] = status.value
    except OllamaError as exc:
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["answer"] = None
        row["status"] = getattr(exc, "code", "MODEL_FAILURE")
        row["error"] = str(exc)[:160]
    return row


def score(rows: list[dict], cases) -> dict:
    pairs = [(truth["wall"], row["answer"])
             for row, (_room, truth, _obj) in zip(rows, cases)]
    out = confusion(pairs)
    # The headline number: among pieces that are NOT against a wall, how often did
    # the model say they were. The 3B baseline is 5/5.
    out["false_wall_rate"] = (None if not out["no_truth"]
                              else round(100.0 * out["fp"] / out["no_truth"], 1))
    out["latency"] = _stats([r["elapsed_s"] for r in rows])
    out["first_query_s"] = rows[0]["elapsed_s"] if rows else None
    out["valid_json"] = sum(1 for r in rows if r["answer"] is not None)
    out["answer_distribution"] = {
        "true": sum(1 for r in rows if r["answer"] is True),
        "false": sum(1 for r in rows if r["answer"] is False),
        "failed": sum(1 for r in rows if r["answer"] is None)}
    return out


def combine(runs: list[dict], cases) -> dict:
    """Both runs pooled. Reported ALONGSIDE the individual runs, never instead of
    them - Phase 1d's lesson was that a five-example negative set disagrees with
    itself, and averaging hides exactly that."""
    pairs = []
    for run in runs:
        pairs += [(truth["wall"], row["answer"])
                  for row, (_r, truth, _o) in zip(run["rows"], cases)]
    out = confusion(pairs)
    out["false_wall_rate"] = (None if not out["no_truth"]
                              else round(100.0 * out["fp"] / out["no_truth"], 1))
    out["latency"] = _stats([r["elapsed_s"] for run in runs for r in run["rows"]])
    out["agreement_pct"] = None
    if len(runs) == 2:
        same = sum(1 for a, b in zip(runs[0]["rows"], runs[1]["rows"])
                   if a["answer"] == b["answer"])
        out["agreement_pct"] = round(100.0 * same / max(1, len(cases)), 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--skip-3b", action="store_true")
    args = parser.parse_args()

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = wall_cases(fixture)
    positives = sum(1 for _r, t, _o in cases if t["wall"] is True)
    negatives = sum(1 for _r, t, _o in cases if t["wall"] is False)

    provider = OllamaProvider()
    environment = {"gpu": gpu(), "system_ram_before": system_ram(),
                   "temperature": 0.2,
                   "num_ctx": provider._settings.ollama_num_ctx,
                   "num_predict": provider._settings.ollama_num_predict,
                   "image_max_px": provider._settings.ollama_scene_image_max_px,
                   "prompt": "phase1d _wall_a, imported unmodified",
                   "schema": BINARY_SCHEMA}

    print(f"dataset: {len(cases)} wall cases  ({positives} against a wall, "
          f"{negatives} not)\n", flush=True)
    print(f"GPU: {environment['gpu'].get('name')}  "
          f"{environment['gpu'].get('vram_total_mib')} MiB\n", flush=True)

    order = ["7b"] if args.skip_3b else ["7b", "3b"]
    results: dict = {}
    for key in order:
        model = MODELS[key]
        print(f"== {model} " + "=" * 50, flush=True)
        info = load_model(provider, model)
        res = info.get("residency", {})
        print(f"  load {info.get('load_s')}s  VRAM {res.get('vram_gb')} GB  "
              f"CPU {res.get('cpu_gb')} GB  on-GPU {res.get('on_gpu_pct')}%",
              flush=True)
        runs = []
        for run_no in range(1, args.runs + 1):
            rows = []
            for room, truth, obj in cases:
                row = ask_wall(provider, room, obj)
                rows.append(row)
                mark = "ok " if row["answer"] == truth["wall"] else "  x"
                print(f"  {mark} run{run_no} {obj['id']:34} -> "
                      f"{str(row['answer']):5}  (truth {truth['wall']})  "
                      f"{row['elapsed_s']}s", flush=True)
            summary = score(rows, cases)
            summary["rows"] = rows
            summary["run"] = run_no
            runs.append(summary)
            print(f"  -- run{run_no}: acc {summary['accuracy']}%  "
                  f"NO-recall {summary['no_recall']}%  false-wall "
                  f"{summary['false_wall_rate']}%  answers "
                  f"{summary['answer_distribution']}\n", flush=True)
        results[key] = {"model": model, "load": info, "runs": runs,
                        "combined": combine(runs, cases),
                        "ram_after": system_ram()}

    phase1d = {}
    if PHASE_1D.is_file():
        phase1d = json.loads(PHASE_1D.read_text(encoding="utf-8"))["stages"]["wall"]

    report = {
        "environment": environment,
        "dataset": {"cases": len(cases), "positives": positives,
                    "negatives": negatives,
                    "source": "tests/fixtures/relationship_benchmark.json "
                              "binary_relations, identical to Phase 1d"},
        "models": results,
        "phase_1d_3b_reference": phase1d,
        "cases": [{"source": o["id"], "room": r["room_key"], "truth_wall": t["wall"],
                   "note": t.get("note", "")} for r, t, o in cases],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "phase_1e_raw.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 72)
    for key in order:
        c = results[key]["combined"]
        res = results[key]["load"].get("residency", {})
        print(f"  {MODELS[key]:14} pooled acc {c['accuracy']}%  NO-recall "
              f"{c['no_recall']}%  false-wall {c['false_wall_rate']}%  "
              f"TP{c['tp']} TN{c['tn']} FP{c['fp']} FN{c['fn']}  "
              f"median {c['latency']['median']}s  on-GPU {res.get('on_gpu_pct')}%  "
              f"run-agreement {c['agreement_pct']}%")
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

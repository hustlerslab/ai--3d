"""P1-MM-002: choose Supervisor role models on evidence, not preference.

Scores each candidate model against a labelled set of known-good AND
known-bad states for all three Supervisor roles' model calls - Watcher
narration, Orchestrator decide-on-UNKNOWN, Validator appearance (renders vs
design intent) - then computes a pairwise error-correlation matrix per role
and asks the one question that matters: do different models catch different
mistakes, or do they all fail the same cases?

Every case runs through the real agent code (`Watcher.narrate`,
`Orchestrator._ask_model`, `Validator._appearance`) with a real
`RoleProvider` at temperature 0, so the agents' own guards apply exactly as in
production - a low-confidence PASS becomes REVIEW_REQUIRED, an uncited FAIL
is refused.

Requires a running Ollama with the candidate models pulled. Appearance cases
run only on models Ollama reports as vision-capable. Never touches the
pipeline's own provider, never runs inside pytest (a benchmark is not a
pass/fail test):

    python scripts/benchmark_model_diversity.py --models qwen2.5:0.5b,llama3.2:1b,gemma2:2b,qwen2.5vl:3b
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "benchmarks"))
import httpx  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.db.sqlite import get_db  # noqa: E402
from app.supervisor.memory import OrchestratorMemoryStore, ValidatorMemoryStore, WatcherMemoryStore  # noqa: E402
from app.supervisor.orchestrator import Orchestrator, QueueHandle  # noqa: E402
from app.supervisor.providers import RoleConfig, RoleProvider, RoleProviderError  # noqa: E402
from app.supervisor.review import ReviewHandle  # noqa: E402
from app.supervisor.validator import Validator, ValidatorInputs  # noqa: E402
from app.supervisor.watcher import Watcher, residual_events  # noqa: E402
from mm002_fixtures import APPEARANCE_CASES, DECIDE_CASES, NARRATION_CASES, RENDER_ROOT_REL  # noqa: E402

REPEAT_RUNS = 3          # for the temperature-0 consistency measurement
RENDER_ROOT = REPO.joinpath(*RENDER_ROOT_REL)
ROLES = ("watcher", "orchestrator", "validator")


def _provider(model: str, base_url: str, role: str) -> RoleProvider:
    # Timeouts sized for a 4 GB laptop GPU: a vision call reads a 1024 px image.
    cfg = RoleConfig(role=role, provider="ollama", model=model, temperature=0.0, max_tokens=600,
                     timeout_seconds=300 if role == "validator" else 120, max_attempts=1,
                     allow_fallback=False, output_schema="bench", memory_scope="bench")
    return RoleProvider(cfg, Settings(_env_file=None, ollama_base_url=base_url))  # type: ignore[call-arg]


def can_see(model: str, base_url: str) -> bool:
    """Ask Ollama, don't guess from the name."""
    r = httpx.post(f"{base_url.rstrip('/')}/api/show", json={"model": model}, timeout=30)
    r.raise_for_status()
    return "vision" in (r.json().get("capabilities") or [])


def _pid(case_id: str) -> str:
    # Fresh per call: memory.append() is idempotent by (kind, key), and run 2
    # of a case must ask the model again, never read back run 1's answer.
    return f"bench_{case_id}_{uuid.uuid4().hex[:8]}"


# ── the three roles, each through its real agent code ─────────────────────

def run_narration(provider: RoleProvider, case) -> tuple[bool, str]:
    # `narrate()` re-derives the residue itself (real call shape); a case may
    # carry a filler row residual_events() screens out - what must hold is
    # that the PATTERN reaches the model.
    residue = residual_events(case.residue, [])
    if case.label == "pattern":
        assert case.pattern_event_ids <= {e.event_id for e in residue}, \
            f"{case.case_id}: the pattern's own events were filtered out before reaching the model"
    memory = WatcherMemoryStore(_pid(case.case_id))
    try:
        found = Watcher(memory, provider=provider).narrate(case.residue, [])
    except RoleProviderError as exc:
        return False, f"PROVIDER_ERROR: {exc}"
    finally:
        memory.close()
    if case.label == "no_pattern":
        return (len(found) == 0), f"anomalies={len(found)}"
    cited = {i for o in found for i in o.observed.get("event_ids", [])}
    return bool(cited & case.pattern_event_ids), f"anomalies={len(found)} cited={sorted(cited)}"


def run_decide(provider: RoleProvider, case) -> tuple[bool, str]:
    memory = OrchestratorMemoryStore(_pid(case.case_id))
    try:
        orch = Orchestrator(memory, QueueHandle(lambda *a, **kw: None), ReviewHandle(), provider=provider)
        decision, by, confidence, _ = orch._ask_model(case.worst, case.observations, "ESCALATE",
                                                      "no policy row")
    finally:
        memory.close()
    # `by == "policy"` means the model's answer was unusable or under 0.6
    # confidence and the default stood - the model did not choose it.
    return (decision == case.label and by == "model"), f"decision={decision} by={by} conf={confidence:.2f}"


def run_appearance(provider: RoleProvider, case) -> tuple[bool, str]:
    pid = _pid(case.case_id)
    memory = ValidatorMemoryStore(pid)
    try:
        v = Validator(memory, provider=provider, project_root=RENDER_ROOT)
        r = v._appearance(ValidatorInputs(project_id=pid, renders=[case.render],
                                          design_intents=[{"intent": case.intent}]))
    finally:
        memory.close()
    ok = (r.status == "PASS") if case.label == "PASS" else (r.status in ("FAIL", "WARNING"))
    return ok, f"status={r.status} conf={r.confidence:.2f}"


CASES: dict[str, tuple[list, Callable]] = {
    "watcher": (NARRATION_CASES, run_narration),
    "orchestrator": (DECIDE_CASES, run_decide),
    "validator": (APPEARANCE_CASES, run_appearance),
}
#: Checks run beside the roles that are NOT production behaviour. Empty since
#: the production prompt defines every option (the "options defined" check
#: that motivated that fix is kept in the before-fix report).
DIAGNOSTICS: dict[str, tuple[list, Callable]] = {}
#: The best accuracy a model can reach by giving ONE fixed answer to every
#: case (each label is balanced). A model at or under this has shown no skill.
CONSTANT_BASELINE = {"watcher": 0.5, "orchestrator": 0.25, "validator": 0.5}


def _answer(note: str) -> str:
    """The part of a note that is the model's ANSWER, for spotting a model
    that says the same thing whatever the case."""
    head = note.split()[0] if note else ""
    return "anomalies>0" if head.startswith("anomalies=") and head != "anomalies=0" else head


# ── driver ──────────────────────────────────────────────────────────────────

def score_model(model: str, base_url: str, roles: list[str], log: Callable[[str], None]) -> dict[str, Any]:
    runs: dict[str, list[bool]] = {}
    notes: dict[str, list[str]] = {}
    latency: dict[str, list[float]] = {r: [] for r in roles}
    errors = 0
    false_pass = 0
    for role in roles:
        cases, run = {**CASES, **DIAGNOSTICS}[role]
        provider = _provider(model, base_url, "orchestrator" if role in DIAGNOSTICS else role)
        for case in cases:
            key = f"{role}/{case.case_id}"
            runs[key], notes[key] = [], []
            for _ in range(REPEAT_RUNS):
                t0 = time.monotonic()
                try:
                    ok, note = run(provider, case)
                except AssertionError:
                    raise                                  # a broken fixture is a bug, not a model result
                except Exception as exc:                   # noqa: BLE001 - a bad answer is a result, not a crash
                    ok, note, errors = False, f"EXC {type(exc).__name__}: {exc}"[:200], errors + 1
                latency[role].append(time.monotonic() - t0)
                runs[key].append(ok)
                notes[key].append(note)
                if role == "validator" and case.label == "FAIL" and note.startswith("status=PASS"):
                    false_pass += 1
            log(f"    {key}: {['ok' if x else '--' for x in runs[key]]}  {notes[key][0]}")

    majority = {k: sum(v) > REPEAT_RUNS / 2 for k, v in runs.items()}
    per_role = {}
    for role in roles:
        keys = [k for k in runs if k.startswith(role + "/")]
        accuracy = sum(majority[k] for k in keys) / len(keys)
        answers = Counter(_answer(n) for k in keys for n in notes[k])
        per_role[role] = {
            "accuracy": accuracy,
            "correct": sum(majority[k] for k in keys), "cases": len(keys),
            "constant_answer_baseline": CONSTANT_BASELINE[role],
            # Positive only if the model beats saying one thing to every case.
            "skill_over_baseline": round(accuracy - CONSTANT_BASELINE[role], 4),
            "answer_distribution": dict(answers),
            "gives_one_answer_to_everything": len(answers) == 1,
            "repeat_run_consistency": sum(len(set(runs[k])) == 1 for k in keys) / len(keys),
            "mean_latency_s": round(statistics.mean(latency[role]), 2),
        }
    if "validator" in roles:
        per_role["validator"]["false_pass_runs"] = false_pass
    return {"model": model, "roles": per_role, "provider_errors": errors,
            "per_case_majority_correct": majority, "per_case_runs": runs, "per_case_notes": notes}


def error_correlation(a: dict[str, bool], b: dict[str, bool]) -> float | None:
    """Phi coefficient over the shared cases' errors. +1: the two models are
    wrong on exactly the same cases (redundant). -1: one is wrong exactly
    where the other is right (maximally diverse). 0: unrelated. None: not
    defined - one model made no error or erred on every case, so there is no
    variance to correlate (reported as such, never as 0)."""
    keys = sorted(set(a) & set(b))
    xs = [0 if a[k] else 1 for k in keys]                  # 1 = error
    ys = [0 if b[k] else 1 for k in keys]
    if not keys or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    n = len(keys)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    return cov / (sx * sy)


def joint_errors(a: dict[str, bool], b: dict[str, bool]) -> dict[str, int]:
    """What diversity is FOR: cases where a second model would catch the
    first one's mistake. `both_wrong` is what no pairing can fix."""
    keys = set(a) & set(b)
    return {"both_wrong": sum(not a[k] and not b[k] for k in keys),
            "only_first_wrong": sum(not a[k] and b[k] for k in keys),
            "only_second_wrong": sum(a[k] and not b[k] for k in keys),
            "shared_cases": len(keys)}


def precision_recall(majority: dict[str, bool]) -> dict[str, dict]:
    """task.md asks for per-role precision/recall. For each label in a role:
    precision = of the cases the model answered with this label, how many had
    it; recall = of the cases with this label, how many the model got.
    Reconstructed from correctness alone, so only for labels where a wrong
    answer is attributable: a binary role (watcher, validator), where wrong on
    one label means the model said the other. The orchestrator is 4-way, so
    its per-class recall is reported and precision is left to the answer
    distribution in the report."""
    out: dict[str, dict] = {}
    for role, (cases, _) in CASES.items():
        keys = {f"{role}/{c.case_id}": c.label for c in cases}
        if not any(k in majority for k in keys):
            continue
        labels = sorted({c.label for c in cases})
        per: dict[str, Any] = {}
        for lab in labels:
            with_lab = [k for k, l in keys.items() if l == lab and k in majority]
            got = sum(majority[k] for k in with_lab)
            entry: dict[str, Any] = {"recall": round(got / len(with_lab), 4), "support": len(with_lab)}
            if len(labels) == 2:
                other = [k for k, l in keys.items() if l != lab and k in majority]
                said_lab = got + sum(not majority[k] for k in other)
                entry["precision"] = round(got / said_lab, 4) if said_lab else None
            per[lab] = entry
        out[role] = per
    return out


def role_finding(pairs: dict[str, dict], takers: list[str], skilled: list[str]) -> str:
    """Correlation is evidence about diversity only between models that can do
    the task. Two models that each give one fixed answer "disagree" on half
    the cases by construction; pairing an always-yes with an always-no model
    catches nothing, whatever phi says."""
    if len(takers) < 2:
        return "NOT MEASURED: fewer than two models took this role's cases"
    if len(skilled) < 2:
        return (f"NOT MEASURABLE: {len(skilled)} of {len(takers)} model(s) beat the constant-answer baseline "
                f"({', '.join(skilled) or 'none'}); correlated error between models with no skill says nothing "
                "about diversity")
    defined = [p["error_correlation"] for name, p in pairs.items()
               if p["error_correlation"] is not None and all(m in skilled for m in name.split(" vs "))]
    if not defined:
        return "NOT MEASURABLE: no pair of skilled models has error variance to correlate"
    m = statistics.mean(defined)
    if m > 0.5:
        return f"NO measurable diversity benefit: mean pairwise error correlation {m:.2f} (models fail the same cases)"
    if m < 0.2:
        return f"diversity HELPS: mean pairwise error correlation {m:.2f} (models mostly fail different cases)"
    return f"weak diversity benefit: mean pairwise error correlation {m:.2f}"


def _scratch_db() -> None:
    """A scratch data dir, never the real one: the agents write real sqlite
    rows (their memory) and must not touch a live project's database. Done in
    main(), not at import, so importing this module (the harness test) has no
    side effects."""
    os.environ["AETHER_DATA_DIR"] = os.environ.get("MM002_DATA_DIR") or str(REPO / ".tools" / "mm002-scratch-data")
    get_settings.cache_clear()
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    get_db()                                               # runs the schema migrations once, at this data dir


def main() -> None:
    _scratch_db()
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=os.environ.get("OLLAMA_MODELS_TO_BENCH", ""))
    ap.add_argument("--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--out", default=str(REPO / "docs" / "benchmarks" / "p1_mm002_model_diversity.json"))
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        sys.exit("--models is required, e.g. qwen2.5:0.5b,llama3.2:1b,gemma2:2b,qwen2.5vl:3b")

    vision = {m: can_see(m, args.base_url) for m in models}
    print(f"{len(models)} model(s); vision-capable: {[m for m, v in vision.items() if v] or 'none'}")
    print(f"cases: watcher {len(NARRATION_CASES)}, orchestrator {len(DECIDE_CASES)}, "
          f"validator {len(APPEARANCE_CASES)} - each run {REPEAT_RUNS}x at temperature 0\n", flush=True)

    results = {}
    for m in models:
        roles = [r for r in ROLES if r != "validator" or vision[m]] + list(DIAGNOSTICS)
        print(f"  {m}  roles={roles}", flush=True)
        t0 = time.monotonic()
        results[m] = score_model(m, args.base_url, roles, lambda s: print(s, flush=True))
        for role, r in results[m]["roles"].items():
            print(f"    {role}: accuracy {r['accuracy']:.2f} ({r['correct']}/{r['cases']}, baseline "
                  f"{r['constant_answer_baseline']}), consistency {r['repeat_run_consistency']:.2f}, "
                  f"{r['mean_latency_s']}s/call, answers {r['answer_distribution']}"
                  + (f", false PASS runs {r['false_pass_runs']}" if "false_pass_runs" in r else ""))
        print(f"    ({time.monotonic() - t0:.0f}s)\n", flush=True)

    correlation: dict[str, Any] = {}
    for role in (*ROLES, *DIAGNOSTICS):
        takers = [m for m in models if role in results[m]["roles"]]
        skilled = [m for m in takers if results[m]["roles"][role]["skill_over_baseline"] > 0]
        pairs = {}
        for x, y in itertools.combinations(takers, 2):
            a = {k: v for k, v in results[x]["per_case_majority_correct"].items() if k.startswith(role + "/")}
            b = {k: v for k, v in results[y]["per_case_majority_correct"].items() if k.startswith(role + "/")}
            phi = error_correlation(a, b)
            pairs[f"{x} vs {y}"] = {"error_correlation": None if phi is None else round(phi, 4),
                                    **joint_errors(a, b)}
        correlation[role] = {"models": takers, "beat_baseline": skilled, "pairs": pairs,
                             "finding": role_finding(pairs, takers, skilled)}

    report = {
        "task": "P1-MM-002", "date": datetime.now(timezone.utc).isoformat(), "repeat_runs": REPEAT_RUNS,
        "temperature": 0.0, "provider": "ollama (local)", "hardware": "NVIDIA RTX 3050 Laptop, 4 GB",
        "n_cases": {"watcher": len(NARRATION_CASES), "orchestrator": len(DECIDE_CASES),
                    "validator": len(APPEARANCE_CASES)},
        "vision_capable": vision,
        "scoring": {
            "watcher": "no_pattern: no anomaly reported; pattern: an anomaly citing at least one pattern event",
            "orchestrator": "the model's own decision (by=model, confidence >= 0.6) equals the label",
            "validator": "PASS label: status PASS; FAIL label: status FAIL or WARNING. REVIEW_REQUIRED is "
                         "never correct, but never a false PASS either",
            "majority": f"a case counts correct when at least {REPEAT_RUNS // 2 + 1} of {REPEAT_RUNS} runs are",
            "skill": "accuracy minus the best one-fixed-answer accuracy; only models with skill > 0 count as "
                     "evidence about diversity",
        },
        "models": {m: {"roles": r["roles"], "provider_errors": r["provider_errors"],
                       "precision_recall": precision_recall(r["per_case_majority_correct"])}
                   for m, r in results.items()},
        "error_correlation_by_role": correlation,
        "per_case_runs": {m: r["per_case_runs"] for m, r in results.items()},
        "per_case_first_note": {m: {k: v[0] for k, v in r["per_case_notes"].items()} for m, r in results.items()},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for role, c in correlation.items():
        print(f"{role}: {c['finding']}")
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()

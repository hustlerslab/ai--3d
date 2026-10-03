"""P1-MM-002: the model-diversity benchmark measures what it claims to.

No model is called. Every case runs through the real agent code (Watcher,
Orchestrator, Validator) and real agent memory, with stand-in providers
whose answers are known, so each number the benchmark reports can be
checked: an oracle scores 100%, a one-answer model scores exactly its
baseline, the agents' own guards still apply, and correlation is never
claimed between models that have no skill.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bmd(env):
    from app.db.sqlite import get_db

    get_db()                                               # schema at the env fixture's data dir
    spec = importlib.util.spec_from_file_location("bmd", ROOT / "scripts" / "benchmark_model_diversity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _config(bmd):
    return bmd._provider("stub", "http://127.0.0.1:1", "validator").config


def _oracle(bmd, case):
    class Oracle:
        config = _config(bmd)

        def complete_json(self, prompt, schema, stage, images=None):
            if stage == "watcher.narrate":
                if case.label == "pattern":
                    return {"anomalies": [{"event_ids": sorted(case.pattern_event_ids), "summary": "s",
                                           "severity": "warning", "recommended_check": "Check the pattern"}]}
                return {"anomalies": []}
            if stage == "orchestrator.decide":
                return {"decision": case.label, "rationale": "r", "confidence": 0.9}
            assert images and all(Path(p).is_file() for p in images), "the render must reach the model"
            if case.label == "PASS":
                return {"status": "PASS", "confidence": 0.9, "rationale": "r", "issues": []}
            return {"status": "FAIL", "confidence": 0.9, "rationale": "r", "issues": [
                {"issue_type": "intent", "expected": "e", "observed": "o", "evidence_refs": [case.render]}]}
    return Oracle()


def _constant(bmd, answer):
    class Constant:
        config = _config(bmd)

        def complete_json(self, prompt, schema, stage, images=None):
            return answer
    return Constant()


def test_the_labelled_set_is_balanced_and_has_known_bad_states(bmd):
    """task.md: known-good AND known-bad, not only good."""
    from mm002_fixtures import APPEARANCE_CASES, DECIDE_CASES, NARRATION_CASES

    assert sorted(c.label for c in NARRATION_CASES) == ["no_pattern"] * 4 + ["pattern"] * 4
    assert sorted(c.label for c in APPEARANCE_CASES) == ["FAIL"] * 4 + ["PASS"] * 4
    assert {c.label for c in DECIDE_CASES} == {"RETRY", "RE_SOLVE", "RE_READ", "ESCALATE"}
    assert all(sum(c.label == d for c in DECIDE_CASES) == 4 for d in ("RETRY", "RE_SOLVE", "RE_READ", "ESCALATE"))
    for c in APPEARANCE_CASES:
        assert (bmd.RENDER_ROOT / c.render).is_file(), c.render


def test_an_oracle_scores_every_case_correct(bmd):
    for role, (cases, run) in bmd.CASES.items():
        wrong = [(c.case_id, run(_oracle(bmd, c), c)[1]) for c in cases if not run(_oracle(bmd, c), c)[0]]
        assert not wrong, (role, wrong)


def test_a_one_answer_model_scores_exactly_the_baseline(bmd):
    from mm002_fixtures import APPEARANCE_CASES, DECIDE_CASES, NARRATION_CASES

    empty = _constant(bmd, {"anomalies": []})
    assert {c.case_id: bmd.run_narration(empty, c)[0] for c in NARRATION_CASES} == \
        {c.case_id: c.label == "no_pattern" for c in NARRATION_CASES}
    retry = _constant(bmd, {"decision": "RETRY", "rationale": "r", "confidence": 0.9})
    assert {c.case_id: bmd.run_decide(retry, c)[0] for c in DECIDE_CASES} == \
        {c.case_id: c.label == "RETRY" for c in DECIDE_CASES}
    passes = _constant(bmd, {"status": "PASS", "confidence": 0.9, "rationale": "r", "issues": []})
    assert {c.case_id: bmd.run_appearance(passes, c)[0] for c in APPEARANCE_CASES} == \
        {c.case_id: c.label == "PASS" for c in APPEARANCE_CASES}


def test_the_agents_guards_still_apply_inside_the_benchmark(bmd):
    from mm002_fixtures import APPEARANCE_CASES, DECIDE_CASES

    # Under 0.6 confidence the Orchestrator keeps its policy default, ESCALATE.
    # On an ESCALATE-labelled case that default is "right" - and must still
    # not be credited to the model, which chose nothing.
    unsure = _constant(bmd, {"decision": "ESCALATE", "rationale": "r", "confidence": 0.3})
    escalate_case = next(c for c in DECIDE_CASES if c.label == "ESCALATE")
    ok, note = bmd.run_decide(unsure, escalate_case)
    assert ok is False and "by=policy" in note, note
    uncited = _constant(bmd, {"status": "FAIL", "confidence": 0.9, "rationale": "r", "issues": [
        {"issue_type": "x", "expected": "e", "observed": "o", "evidence_refs": []}]})
    ok, note = bmd.run_appearance(uncited, next(c for c in APPEARANCE_CASES if c.label == "FAIL"))
    assert not ok and "REVIEW_REQUIRED" in note


def test_the_benchmark_sends_the_production_prompt(bmd):
    from app.supervisor.orchestrator import option_definitions
    from mm002_fixtures import DECIDE_CASES

    seen = []

    class Capture:
        config = _config(bmd)

        def complete_json(self, prompt, schema, stage, images=None):
            seen.append(prompt)
            return {"decision": "RETRY", "rationale": "r", "confidence": 0.9}

    bmd.run_decide(Capture(), next(c for c in DECIDE_CASES if c.label == "RETRY"))
    assert option_definitions() in seen[0]


def test_error_correlation_and_the_skill_gate(bmd):
    a = {"x1": True, "x2": False, "x3": True, "x4": False}
    assert bmd.error_correlation(a, dict(a)) == pytest.approx(1.0)
    assert bmd.error_correlation(a, {k: not v for k, v in a.items()}) == pytest.approx(-1.0)
    assert bmd.error_correlation(a, {k: True for k in a}) is None, "no error variance is undefined, never 0"
    assert bmd.joint_errors(a, {k: not v for k, v in a.items()}) == \
        {"both_wrong": 0, "only_first_wrong": 2, "only_second_wrong": 2, "shared_cases": 4}
    # An always-yes and an always-no model "disagree" perfectly and catch nothing.
    no_skill = bmd.role_finding({"a vs b": {"error_correlation": -1.0}}, ["a", "b"], [])
    assert no_skill.startswith("NOT MEASURABLE: 0 of 2 model(s) beat the constant-answer baseline"), no_skill
    one_skilled = bmd.role_finding({"a vs b": {"error_correlation": 0.0}}, ["a", "b"], ["a"])
    assert one_skilled.startswith("NOT MEASURABLE: 1 of 2"), one_skilled
    assert bmd.role_finding({"a vs b": {"error_correlation": 0.9}}, ["a", "b"], ["a", "b"]).startswith("NO measurable")
    assert bmd.role_finding({"a vs b": {"error_correlation": 0.0}}, ["a", "b"], ["a", "b"]).startswith("diversity HELPS")


def test_precision_and_recall_per_role(bmd):
    """task.md asks for per-role precision/recall, not only accuracy."""
    from mm002_fixtures import APPEARANCE_CASES, DECIDE_CASES

    perfect = {f"{role}/{c.case_id}": True for role, (cases, _) in bmd.CASES.items() for c in cases}
    pr = bmd.precision_recall(perfect)
    assert all(e["recall"] == 1.0 and e.get("precision", 1.0) == 1.0 for per in pr.values() for e in per.values())
    # A validator that passes everything: FAIL recall 0 and PASS precision 0.5.
    passes = {f"validator/{c.case_id}": c.label == "PASS" for c in APPEARANCE_CASES}
    v = bmd.precision_recall(passes)["validator"]
    assert v["FAIL"]["recall"] == 0.0 and v["PASS"]["recall"] == 1.0 and v["PASS"]["precision"] == 0.5
    # An orchestrator that always says RE_SOLVE: recall 1 for RE_SOLVE, 0 for every other option.
    resolve = {f"orchestrator/{c.case_id}": c.label == "RE_SOLVE" for c in DECIDE_CASES}
    o = bmd.precision_recall(resolve)["orchestrator"]
    assert {k: e["recall"] for k, e in o.items()} == {"ESCALATE": 0.0, "RETRY": 0.0, "RE_READ": 0.0, "RE_SOLVE": 1.0}


def test_importing_the_harness_touches_no_database(env, monkeypatch):
    """The scratch data dir is set up in main(), never at import."""
    import os

    before = os.environ.get("AETHER_DATA_DIR")
    spec = importlib.util.spec_from_file_location("bmd2", ROOT / "scripts" / "benchmark_model_diversity.py")
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert os.environ.get("AETHER_DATA_DIR") == before

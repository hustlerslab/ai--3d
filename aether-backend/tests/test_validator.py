"""P1-VALIDATOR-002 — the Validator agent.

The one property that matters most: a Validator that cannot run, or is not
convinced, says REVIEW_REQUIRED. PASS must be unreachable on every such path.
"""
from __future__ import annotations

import json
import random

import httpx
import pytest
from pydantic import ValidationError

from app.core import config
from app.spatial.failures import FailureCategory as FC
from app.supervisor.contracts import ValidationResult
from app.supervisor.memory import (
    MemoryIsolationError, OrchestratorMemoryStore, ValidatorMemoryStore, WatcherMemoryStore,
)
from app.supervisor.providers import RoleProvider, get_role_provider, role_config
from app.supervisor.validator import APPEARANCE_SCHEMA, Validator, ValidatorInputs

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c"
                    "6360f8cfc0f01f0005000201e1c5a3a10000000049454e44ae426082")


def _set(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    config.get_settings.cache_clear()


class Scripted(RoleProvider):
    """A real RoleProvider (config and all) whose transport answers from a script."""

    def __init__(self, answer, *, temperature=0.0, fallback=False, raises=None):
        cfg = role_config("validator").model_copy(update={"provider": "mock", "model": "scripted",
                                                          "temperature": temperature,
                                                          "allow_fallback": fallback})
        super().__init__(cfg)
        self.answer, self.raises, self.seen = answer, raises, []

    def complete_json(self, prompt, schema, stage, images=None):
        self.seen.append({"prompt": prompt, "schema": schema, "images": list(images or [])})
        if self.raises:
            raise self.raises
        return self.answer


@pytest.fixture
def project(env, tmp_path):
    from app.projects import get_project_store

    pid = get_project_store().create(name="validated").project_id
    root = tmp_path / "proj"
    (root / "previews").mkdir(parents=True)
    (root / "previews" / "build_preview.png").write_bytes(PNG)
    return pid, root


def _clean_inputs(pid, **kw):
    base = dict(project_id=pid, scene_id="scene_1", scene_version=1,
                spatial_check={"repair": {"terminal_state": "ALREADY_VALID", "hard_after": 0},
                               "intent": {"satisfied": 3, "violated": 0}},
                build_report={"ok": True, "errors": [], "warnings": []},
                renders=["previews/build_preview.png"], design_intents=[{"text": "warm oak, linen sofa"}])
    return ValidatorInputs(**{**base, **kw})


def _run(pid, root, provider, inputs=None):
    store = ValidatorMemoryStore(pid)
    try:
        return Validator(store, provider=provider, project_root=root).validate(inputs or _clean_inputs(pid))
    finally:
        store.close()


def _appearance(results):
    return next(r for r in results if r.issue_type.startswith("appearance"))


# ── REVIEW_REQUIRED, never PASS, whenever the model cannot vouch ───────────

GOOD_PASS = {"status": "PASS", "confidence": 0.92, "rationale": "matches the brief", "issues": []}


@pytest.mark.parametrize("why, provider", [
    ("no model configured", None),
    ("model raised", Scripted(GOOD_PASS, raises=__import__("app.supervisor.providers", fromlist=["x"]).RoleProviderError("503"))),
    ("fallback marker", Scripted({"_fallback": True})),
    ("not a dict", Scripted(["PASS"])),
    ("unknown status", Scripted({"status": "LOOKS_GREAT", "confidence": 1.0, "rationale": "", "issues": []})),
    ("unconvinced PASS", Scripted({"status": "PASS", "confidence": 0.4, "rationale": "", "issues": []})),
    ("PASS that lists issues", Scripted({"status": "PASS", "confidence": 0.95, "rationale": "",
                                         "issues": [{"issue_type": "x", "expected": "", "observed": "",
                                                     "evidence_refs": []}]})),
    ("FAIL citing nothing it was shown", Scripted({"status": "FAIL", "confidence": 0.9, "rationale": "",
                                                    "issues": [{"issue_type": "colour", "expected": "oak",
                                                                "observed": "walnut",
                                                                "evidence_refs": ["renders/imagined.png"]}]})),
    ("confidence not a number", Scripted({"status": "PASS", "confidence": "very", "rationale": "", "issues": []})),
])
def test_every_path_without_a_convinced_supported_model_is_review_required(project, why, provider):
    pid, root = project
    a = _appearance(_run(pid, root, provider))
    assert a.status == "REVIEW_REQUIRED", why
    assert a.recommended_action == "human_review" and a.confidence == 0.0


def test_a_dead_model_endpoint_ends_in_review_required(project, monkeypatch):
    pid, root = project
    _set(monkeypatch, VALIDATOR_PROVIDER="ollama")
    p = get_role_provider("validator", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="x")))
    assert _appearance(_run(pid, root, p)).status == "REVIEW_REQUIRED"


def test_pass_is_unreachable_except_from_a_convinced_issue_free_model(project):
    """200 scripted answers across the whole answer space: PASS appears only
    for status PASS, confidence >= 0.7 and no issues - nothing else."""
    pid, root = project
    rng = random.Random(7)
    for _ in range(200):
        status = rng.choice(["PASS", "FAIL", "WARNING", "", None, "pass", "OK"])
        conf = rng.choice([0.0, 0.3, 0.69, 0.7, 0.95, 1.5, -1, "x"])
        issues = rng.choice([[], [{"issue_type": "t", "expected": "e", "observed": "o",
                                   "evidence_refs": rng.choice([[], ["previews/build_preview.png"], ["nope.png"]])}]])
        a = _appearance(_run(pid, root, Scripted({"status": status, "confidence": conf,
                                                  "rationale": "r", "issues": issues})))
        if a.status == "PASS":
            assert status == "PASS" and issues == [] and isinstance(conf, float) and conf >= 0.7


def test_a_convinced_model_with_a_render_passes_and_was_shown_the_render(project):
    pid, root = project
    p = Scripted(GOOD_PASS)
    a = _appearance(_run(pid, root, p))
    assert a.status == "PASS" and a.determinism == "model_assisted" and a.recommended_action == "continue"
    assert a.evidence == ["previews/build_preview.png"]
    assert p.seen[0]["schema"] is APPEARANCE_SCHEMA
    assert [str(i).replace("\\", "/").endswith("previews/build_preview.png") for i in p.seen[0]["images"]] == [True]
    assert "UNTRUSTED_DATA" in p.seen[0]["prompt"]


def test_no_render_no_verdict(project):
    pid, root = project
    a = _appearance(_run(pid, root, Scripted(GOOD_PASS), _clean_inputs(pid, renders=[])))
    assert a.status == "REVIEW_REQUIRED"


def test_a_supported_model_fail_is_a_fail_with_evidence_and_category(project):
    pid, root = project
    a = _appearance(_run(pid, root, Scripted({"status": "FAIL", "confidence": 0.8, "rationale": "sofa is leather",
                                              "issues": [{"issue_type": "material", "expected": "linen",
                                                          "observed": "black leather",
                                                          "evidence_refs": ["previews/build_preview.png"]}]})))
    assert a.status == "FAIL" and a.evidence == ["previews/build_preview.png"]
    assert isinstance(a.failure_category, FC) and a.recommended_action == "human_review"


# ── construction ───────────────────────────────────────────────────────────


def test_the_validator_refuses_a_fallback_or_warm_provider(project):
    pid, root = project
    store = ValidatorMemoryStore(pid)
    try:
        with pytest.raises(ValueError):
            Validator(store, provider=Scripted(GOOD_PASS, fallback=True))
        with pytest.raises(ValueError):
            Validator(store, provider=Scripted(GOOD_PASS, temperature=1.0))
    finally:
        store.close()


def test_the_validator_role_defaults_to_temperature_zero_and_no_fallback(env):
    c = role_config("validator")
    assert c.temperature == 0.0 and c.allow_fallback is False


def test_the_validator_is_built_with_its_own_memory_only(project):
    pid, root = project
    for wrong in (WatcherMemoryStore(pid), OrchestratorMemoryStore(pid)):
        try:
            with pytest.raises(MemoryIsolationError):
                Validator(wrong)
        finally:
            wrong.close()


def test_the_validator_cannot_read_watcher_or_orchestrator_memory(project):
    pid, root = project
    w, o = WatcherMemoryStore(pid), OrchestratorMemoryStore(pid)
    try:
        w.append("observation", {"secret": "WATCHER_SECRET"}, key="k")
        o.append("directive", {"secret": "ORCH_SECRET"})
    finally:
        w.close()
        o.close()
    p = Scripted(GOOD_PASS)
    _run(pid, root, p)
    assert "SECRET" not in p.seen[0]["prompt"]
    v = ValidatorMemoryStore(pid)
    try:
        for table in ("watcher_memory", "orchestrator_memory"):
            with pytest.raises(MemoryIsolationError):
                v._db.query(f"SELECT content FROM {table}")
    finally:
        v.close()


# ── the contract ───────────────────────────────────────────────────────────


def _vr(**kw):
    base = dict(validation_id="v", project_id="p", status="FAIL", severity="error", issue_type="x",
                failure_category=FC.SOLVER_FAILURE, evidence=["planning/spatial_check.json"], confidence=1.0,
                recommended_action="re_solve", determinism="deterministic", rationale="r", validator_version="t")
    return ValidationResult(**{**base, **kw})


def test_a_fail_without_evidence_is_schema_invalid():
    _vr()
    with pytest.raises(ValidationError):
        _vr(evidence=[])
    with pytest.raises(ValidationError):
        _vr(failure_category=None)
    with pytest.raises(ValidationError):
        _vr(evidence=['{"inlined": "render"}'])
    with pytest.raises(ValidationError):
        _vr(status="PASS", recommended_action="retry", failure_category=None)
    with pytest.raises(ValidationError):
        _vr(failure_category="made_up_category")


def test_it_receives_results_never_geometry(project):
    from app.scene.schema import Scene

    pid, root = project
    with pytest.raises(ValidationError):
        ValidatorInputs(project_id=pid, scene={"objects": []})
    with pytest.raises(ValidationError):
        ValidatorInputs(project_id=pid, objects=[{"position": [0, 0, 0]}])
    store = ValidatorMemoryStore(pid)
    try:
        with pytest.raises(TypeError):
            Validator(store).validate(Scene(project_id=pid))
    finally:
        store.close()


# ── deterministic results are consumed, not recomputed ─────────────────────


def test_hard_violations_reported_by_layers_1_to_7_are_a_cited_fail(project):
    pid, root = project
    inputs = _clean_inputs(pid, spatial_check={"repair": {"terminal_state": "ESCALATE", "hard_after": 2},
                                               "intent": {"violated": 1, "satisfied": 2}})
    results = _run(pid, root, None, inputs)
    fail = next(r for r in results if r.issue_type == "spatial_hard_violations")
    assert fail.status == "FAIL" and fail.failure_category is FC.REPAIR_FAILURE
    assert fail.evidence == ["planning/spatial_check.json"] and fail.determinism == "deterministic"
    assert any(r.issue_type == "placement_intent_violated" and r.status == "WARNING" for r in results)


def test_a_missing_build_report_is_a_validation_failure_not_a_pass(project):
    pid, root = project
    results = _run(pid, root, None, _clean_inputs(pid, build_report={"ok": False, "errors": ["no report"]}))
    r = next(r for r in results if r.issue_type == "build_report_missing")
    assert r.status == "FAIL" and r.failure_category is FC.VALIDATION_FAILURE


def test_no_spatial_report_means_nothing_is_vouched_for(project):
    pid, root = project
    results = _run(pid, root, None, _clean_inputs(pid, spatial_check=None))
    assert any(r.issue_type == "spatial_report_missing" and r.status == "REVIEW_REQUIRED" for r in results)


def test_verdicts_are_recorded_in_validator_memory_only(project):
    pid, root = project
    _run(pid, root, Scripted(GOOD_PASS))
    v = ValidatorMemoryStore(pid)
    try:
        assert {r["content"]["status"] for r in v.recent("verdict")} == {"PASS"}
    finally:
        v.close()


# ── end to end: the runner validates after a real plan ─────────────────────


def test_the_runner_validates_after_scene_plan_and_default_config_never_passes_appearance(env):
    from fastapi.testclient import TestClient

    from app.jobs import get_runner
    from app.main import app
    from tests.conftest import sign_in_admin
    from tests.test_golden_project import _seed_project

    with TestClient(app) as c:
        c = sign_in_admin(c)
        pid = _seed_project(c)
        c.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(60)
        c.post(f"/api/projects/{pid}/scene-plan", json={})
        assert get_runner().wait_idle(120)
    v = ValidatorMemoryStore(pid)
    try:
        verdicts = [r["content"] for r in v.recent("verdict", 100)]
    finally:
        v.close()
    appearance = [x for x in verdicts if x["issue_type"].startswith("appearance")]
    assert appearance and all(x["status"] == "REVIEW_REQUIRED" for x in appearance), \
        "with no Validator model configured, appearance is never vouched for"
    assert not any(x["status"] == "PASS" for x in verdicts)


def test_sample_validation_result_is_written_for_evidence(project):
    from pathlib import Path

    pid, root = project
    results = _run(pid, root, Scripted({"status": "FAIL", "confidence": 0.8, "rationale": "sofa is leather",
                                        "issues": [{"issue_type": "material", "expected": "linen",
                                                    "observed": "black leather",
                                                    "evidence_refs": ["previews/build_preview.png"]}]}),
                   _clean_inputs(pid, spatial_check={"repair": {"terminal_state": "ESCALATE", "hard_after": 1},
                                                     "intent": {"violated": 0}}))
    out = Path(__file__).resolve().parents[2] / "version 4" / "evidence" / "P1-VALIDATOR-002"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample_validation_results.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=2), "utf-8")


# ── layer 7: the render verifier's evidence (QA-003 rows 5 and 12) ─────────


def _evidence(*, drifted=(), wrong_size=(), unseen=()):
    per = []
    for oid in {*wrong_size, *unseen, "obj_fine"}:
        per.append({"scene_object_id": oid, "visibility": "occluded" if oid in unseen else "visible",
                    "checks": {"scale": "fail" if oid in wrong_size else "pass",
                               "major_objects_visible": "fail" if oid in unseen else "pass"}})
    return {"scene_checks": {"render_matches_committed_scene": "fail" if drifted else "pass"},
            "summary": {"drifted_object_ids": list(drifted)}, "per_object": per}


def _layer7(results):
    return {r.issue_type: r for r in results if r.issue_type in ("render_mismatch", "asset_dimensions")}


def test_a_render_that_no_longer_shows_the_committed_scene_goes_to_a_person(project):
    pid, root = project
    found = _layer7(_run(pid, root, None, _clean_inputs(pid, render_verification=_evidence(drifted=["obj_gone"]))))
    v = found["render_mismatch"]
    assert v.status == "FAIL" and v.failure_category == FC.VALIDATION_FAILURE
    assert v.recommended_action == "human_review" and v.determinism == "deterministic"
    assert [e.id for e in v.affected_entities] == ["obj_gone"]
    assert v.evidence == ["planning/render_verification.json"]


def test_a_piece_built_beyond_tolerance_is_an_asset_failure_to_regenerate(project):
    pid, root = project
    found = _layer7(_run(pid, root, None, _clean_inputs(pid, render_verification=_evidence(wrong_size=["obj_big"]))))
    v = found["asset_dimensions"]
    assert v.status == "FAIL" and v.failure_category == FC.ASSET_FAILURE
    assert v.recommended_action == "regenerate_asset"
    assert [e.id for e in v.affected_entities] == ["obj_big"]


def test_a_piece_the_corner_cameras_did_not_see_is_not_escalated(project):
    """Four corner cameras do not see every piece of a correct room: not
    seen is evidence for a person reading the report, not a failure."""
    pid, root = project
    assert _layer7(_run(pid, root, None, _clean_inputs(pid, render_verification=_evidence(unseen=["obj_hidden"])))) == {}


def test_no_render_verification_yet_adds_no_verdict(project):
    pid, root = project
    assert _layer7(_run(pid, root, None, _clean_inputs(pid))) == {}

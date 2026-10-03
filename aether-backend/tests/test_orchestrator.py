"""P1-ORCHESTRATOR-001/002, P1-REPAIR-001, P1-HUMAN-001 — decide, bound,
record, escalate.

The end-to-end cases inject a real collision into a real committed golden
scene and let the pipeline find it (check_scene -> Validator), decide
(Orchestrator), repair (repair_scene -> Repair Engine), re-validate and
record - with nothing mocked but the absence of a model.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.jobs import get_job_store, get_runner
from app.projects import ProjectStage, get_project_store
from app.spatial.failures import FailureCategory as FC
from app.supervisor.contracts import (
    AffectedEntity, Directive, DirectiveBasis, DirectiveTarget, ValidationResult,
)
from app.supervisor.memory import OrchestratorMemoryStore, ValidatorMemoryStore
from app.supervisor.orchestrator import AuditTrail, Orchestrator, QueueHandle
from app.supervisor.policy import POLICY
from app.supervisor.review import ReviewHandle, ReviewQueue, audience_for

SUPERVISOR = Path(__file__).resolve().parents[1] / "app" / "supervisor"


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import sign_in_admin

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _planned(client) -> str:
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)
    return pid


def _inject_collision(pid: str) -> tuple[str, str]:
    """Corrupt the COMMITTED scene: put one floor piece on top of another,
    bypassing the commit gate the way an external edit or a bug would."""
    from app.scene.store import get_store

    store = get_store()
    scene = store.load(get_project_store().get(pid).scene_ids[-1])
    floor = [o for o in scene.objects if o.mount == "floor" and not o.parent_id and o.dimensions[0] < 1.2]
    a, b = floor[0], next(o for o in floor[1:] if o.room_id == floor[0].room_id)
    moved = scene.model_copy(deep=True)
    obj = next(o for o in moved.objects if o.object_id == b.object_id)
    obj.position = (a.position[0] + 0.05, a.position[1], a.position[2] + 0.05)
    store.commit(moved, base_version=scene.version)
    return a.object_id, b.object_id


def _run(pid, job_type, params=None):
    job = get_runner().enqueue(pid, job_type, params or {})
    assert get_runner().wait_idle(120)
    return job


def _v(pid, status="FAIL", category=FC.SOLVER_FAILURE, **kw) -> ValidationResult:
    base = dict(validation_id=f"val_{status}_{category}", project_id=pid, scene_id="s", scene_version=1,
                status=status, severity="error" if status == "FAIL" else "warning", issue_type="x",
                failure_category=category if status == "FAIL" else None,
                affected_entities=[AffectedEntity(kind="scene_object", id="obj_1")],
                evidence=["planning/spatial_check.json"] if status == "FAIL" else [],
                confidence=1.0, recommended_action="re_solve" if status == "FAIL" else "human_review",
                determinism="deterministic", rationale="r", validator_version="t")
    return ValidationResult(**{**base, **kw})


class RecordingQueue(QueueHandle):
    def __init__(self, answer="job_x"):
        self.calls = []
        super().__init__(lambda *a, **k: (self.calls.append((a, k)) or type("J", (), {"job_id": answer})()))


def _orch(pid, queue=None, provider=None):
    return Orchestrator(OrchestratorMemoryStore(pid), queue or RecordingQueue(), ReviewHandle(), provider=provider)


# ── P1-ORCHESTRATOR-001 ────────────────────────────────────────────────────


EXPECTED = {
    FC.PERCEPTION_FAILURE: ("RE_READ", "scene_plan"), FC.ASSET_FAILURE: ("REGENERATE", "generate_elements"),
    FC.GEOMETRY_FAILURE: ("RE_SOLVE", "repair_scene"), FC.SOLVER_FAILURE: ("RE_SOLVE", "repair_scene"),
    FC.CANDIDATE_VOCABULARY_FAILURE: ("HUMAN_REVIEW", ""), FC.CONSTRAINT_FAILURE: ("HUMAN_REVIEW", ""),
    FC.REPRESENTATION_FAILURE: ("HUMAN_REVIEW", ""), FC.REPAIR_FAILURE: ("ESCALATE", ""),
    FC.VALIDATION_FAILURE: ("HUMAN_REVIEW", ""), FC.BLENDER_EXECUTION_FAILURE: ("RETRY", "build"),
    FC.HARDWARE_FAILURE: ("RETRY", "build"), FC.UNKNOWN: ("ESCALATE", ""),
}


@pytest.mark.parametrize("category", list(FC))
def test_all_twelve_categories_map_as_designed(env, category):
    pid = get_project_store().create(name="map").project_id
    o = _orch(pid)
    try:
        d = o.decide([_v(pid, category=category)], [], repair_round=0, failed_job_type="build")
    finally:
        o.memory.close()
    assert (d.decision, d.target.job_type) == EXPECTED[category]
    assert d.decided_by == "policy" and d.based_on.validation_ids == [f"val_FAIL_{category}"]
    assert set(POLICY) == set(FC)


def test_blender_is_retried_once_then_escalated(env):
    pid = get_project_store().create(name="blender").project_id
    o = _orch(pid)
    try:
        assert o.decide([_v(pid, category=FC.BLENDER_EXECUTION_FAILURE)], [], repair_round=0).decision == "RETRY"
        assert o.decide([_v(pid, category=FC.BLENDER_EXECUTION_FAILURE)], [], repair_round=1).decision == "ESCALATE"
    finally:
        o.memory.close()


def test_upstream_required_routes_to_re_read_not_another_repair(env):
    from app.supervisor.validator import Validator, ValidatorInputs

    pid = get_project_store().create(name="upstream").project_id
    v = ValidatorMemoryStore(pid)
    try:
        verdicts = Validator(v).validate(ValidatorInputs(
            project_id=pid, spatial_check={"repair": {"terminal_state": "UPSTREAM_REQUIRED", "hard_after": 1}}))
    finally:
        v.close()
    o = _orch(pid)
    try:
        d = o.decide(verdicts, [], repair_round=0)
    finally:
        o.memory.close()
    assert d.decision == "RE_READ" and d.target.job_type == "scene_plan" and d.failure_category is FC.PERCEPTION_FAILURE
    assert d.target.params.get("force_read") is True, "a re-read must actually read the moodboard again"


def test_a_model_is_consulted_only_where_the_table_abstains(env):
    pid = get_project_store().create(name="model").project_id

    class Model:
        calls = 0

        def complete_json(self, prompt, schema, stage, images=None):
            Model.calls += 1
            return {"decision": "RE_SOLVE", "rationale": "looks geometric", "confidence": 0.9}

    o = _orch(pid, provider=Model())
    try:
        d = o.decide([_v(pid, category=FC.SOLVER_FAILURE)], [], repair_round=0)
        assert d.decided_by == "policy" and Model.calls == 0, "the table decided; no model was asked"
        d = o.decide([_v(pid, category=FC.UNKNOWN)], [], repair_round=0)
        assert d.decided_by == "model" and d.decision == "RE_SOLVE" and d.target.job_type == "repair_scene"
        assert Model.calls == 1, "consulted once, where the table abstained - and RE_SOLVE still means the Repair Engine"
    finally:
        o.memory.close()



def test_the_model_is_told_what_every_option_means(env):
    """P1-MM-002: the prompt used to define only RE_SOLVE, and every local
    model benchmarked answered RE_SOLVE to all 16 labelled cases. Every
    option is now defined in the prompt, in words written for the model."""
    from app.supervisor.orchestrator import MODEL_OPTION_MEANINGS, MODEL_OPTIONS, MODEL_SCHEMA, option_definitions

    pid = get_project_store().create(name="prompt").project_id
    seen: list[str] = []

    class Model:
        def complete_json(self, prompt, schema, stage, images=None):
            seen.append(prompt)
            return {"decision": "ESCALATE", "rationale": "r", "confidence": 0.9}

    o = _orch(pid, provider=Model())
    try:
        o.decide([_v(pid, category=FC.UNKNOWN)], [], repair_round=0)
    finally:
        o.memory.close()
    (prompt,) = seen
    assert option_definitions() in prompt
    assert set(MODEL_OPTION_MEANINGS) == set(MODEL_OPTIONS), "an option with no meaning, or a meaning with no option"
    for option in MODEL_OPTIONS:
        assert f"- {option}: {MODEL_OPTION_MEANINGS[option]}" in prompt.splitlines(), f"{option} is not defined"
    # The definitions sit BEFORE the untrusted evidence, never inside it.
    assert prompt.index("- ESCALATE: ") < prompt.index("UNTRUSTED_DATA")
    assert MODEL_SCHEMA["properties"]["decision"]["enum"] == list(MODEL_OPTIONS)


def test_every_option_the_model_may_choose_has_a_policy_definition():
    """An option the model may choose must also be a decision the policy
    table itself makes - so its meaning has a row to follow."""
    from app.supervisor.orchestrator import MODEL_OPTIONS

    decisions = {r.decision for r in POLICY.values() if r.note}
    assert set(MODEL_OPTIONS) <= decisions, set(MODEL_OPTIONS) - decisions


def test_every_directive_cites_what_it_rests_on():
    with pytest.raises(ValidationError):
        Directive(directive_id="d", project_id="p", decision="RE_SOLVE", rationale="r", decided_by="policy",
                  confidence=1.0, orchestrator_version="t", target=DirectiveTarget(job_type="repair_scene"))
    with pytest.raises(ValidationError):
        Directive(directive_id="d", project_id="p", decision="RE_SOLVE", rationale="r", decided_by="policy",
                  confidence=1.0, orchestrator_version="t", based_on=DirectiveBasis(validation_ids=["v"]))
    Directive(directive_id="d", project_id="p", decision="CONTINUE", rationale="r", decided_by="policy",
              confidence=1.0, orchestrator_version="t")


def test_capability_audit_no_scene_store_is_reachable(env):
    """The Orchestrator holds a queue handle and a review handle and no path
    to SceneStore - checked on the live object graph (bound methods and
    closures included) and on the source's imports."""
    from app.scene.store import SceneStore

    pid = get_project_store().create(name="audit").project_id
    o = Orchestrator(OrchestratorMemoryStore(pid), QueueHandle(get_runner().request_repair), ReviewHandle())
    seen, stack, reached = set(), [o], []
    try:
        while stack:
            obj = stack.pop()
            if id(obj) in seen or isinstance(obj, (str, bytes, int, float, bool, type(None))):
                continue
            seen.add(id(obj))
            if isinstance(obj, SceneStore):
                reached.append(type(obj).__name__)
            children = list(getattr(obj, "__dict__", {}).values())
            children += [getattr(obj, "__self__", None), getattr(obj, "__func__", None)]
            children += [c.cell_contents for c in (getattr(obj, "__closure__", None) or ())]
            if isinstance(obj, (list, tuple, set)):
                children += list(obj)
            if isinstance(obj, dict):
                children += list(obj.values())
            stack.extend(c for c in children if c is not None and not isinstance(c, type))
    finally:
        o.memory.close()
    assert reached == [], f"a SceneStore is reachable from the Orchestrator: {reached}"

    forbidden = {"app.scene.store", "app.scene.patches", "..scene.store", "..scene.patches"}
    for name in ("orchestrator.py", "policy.py", "review.py"):
        tree = ast.parse((SUPERVISOR / name).read_text("utf-8"))
        imported = {("." * n.level + (n.module or "")) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imported & forbidden, f"{name} imports {imported & forbidden}"
        assert "commit_patch" not in (SUPERVISOR / name).read_text("utf-8")


def test_the_queue_handle_dispatches_only_the_allowed_services():
    q = RecordingQueue()
    with pytest.raises(PermissionError):
        q.dispatch("p", "film", {})
    assert q.dispatch("p", "repair_scene", {}) == "job_x"


# ── P1-REPAIR-001: the bound belongs to the runner ─────────────────────────


def test_a_misbehaving_orchestrator_asking_forever_still_halts_at_round_2(client):
    pid = _planned(client)
    runner = get_runner()
    q = QueueHandle(runner.request_repair)
    dispatched = []
    for _ in range(25):                                    # a component that will not stop asking
        dispatched.append(q.dispatch(pid, "repair_scene", {"repair_round": 0, "max_rounds": 99}))
        runner.wait_idle(60)
    made = [j for j in dispatched if j]
    assert len(made) == 2, dispatched
    rounds = [get_job_store().get(j).repair_round for j in made]
    assert rounds == [1, 2], "numbered by the runner; the forged params were ignored"
    refusals = [e for e in get_job_store().list_events(pid, limit=5000) if e.event_type == "repair.limit_reached"]
    assert len(refusals) == 23
    queued = [e for e in get_job_store().list_events(pid, limit=5000)
              if e.event_type == "job.queued" and e.payload.get("repair_round")]
    assert [e.message for e in queued] == ["repair round 1 of 2", "repair round 2 of 2"]


def test_a_user_action_starts_a_fresh_budget(client):
    pid = _planned(client)
    runner = get_runner()
    for _ in range(3):
        runner.request_repair(pid, "repair_scene", {})
        runner.wait_idle(60)
    assert runner.repair_rounds_used(pid) == 2
    _run(pid, "check_scene")                               # an ordinary, user-initiated job
    assert runner.repair_rounds_used(pid) == 0


def test_the_inner_engine_bound_is_unchanged():
    from app.spatial import repair_engine

    assert repair_engine.MAX_ITERATIONS == 20


def test_a_zero_cap_disables_automatic_repair_but_not_escalation(client, monkeypatch):
    monkeypatch.setenv("REPAIR_MAX_ROUNDS", "0")
    from app.core import config

    config.get_settings.cache_clear()
    pid = _planned(client)
    _inject_collision(pid)
    _run(pid, "check_scene")
    assert [j for j in get_job_store().list_for_project(pid) if j.repair_round > 0] == [], "no automatic repair"
    items = ReviewQueue().items(pid, role="admin")
    assert len(items) == 1, "escalation still works"
    rounds = AuditTrail(pid).rounds()
    assert rounds[-1]["outcome"] == "escalated" and "limit reached" in rounds[-1]["rationale"]
    assert rounds[-1]["decision"] == "ESCALATE"


# ── end to end: find, decide, repair, re-validate, record ──────────────────


def test_an_injected_collision_is_found_repaired_revalidated_and_recorded(client):
    pid = _planned(client)
    a, b = _inject_collision(pid)
    _run(pid, "check_scene")
    assert get_runner().wait_idle(120)

    jobs = get_job_store().list_for_project(pid)
    repairs = [j for j in jobs if j.type == "repair_scene"]
    assert len(repairs) == 1 and repairs[0].repair_round == 1 and repairs[0].status.value == "SUCCEEDED"
    assert repairs[0].result["repaired"] is True and repairs[0].result["hard_after"] == 0

    rounds = client.get(f"/api/projects/{pid}/repairs").json()["data"]["rounds"]
    assert len(rounds) == 1
    r = rounds[0]
    assert r["failure_category"] == FC.SOLVER_FAILURE.value and r["validator_status"] == "FAIL"
    assert r["decision"] == "RE_SOLVE" and r["decided_by"] == "policy" and r["rationale"]
    assert r["action_job_type"] == "repair_scene" and r["action_job_id"] == repairs[0].job_id
    assert r["failure_evidence"] == ["planning/spatial_check.json"]
    assert r["scene_version_before"] == 2, "the corrupted version was the one checked"
    assert r["scene_version_after"] > r["scene_version_before"]
    assert "spatial_hard_violations" not in r["second_validation"]
    assert r["outcome"] == "resolved"
    assert get_project_store().get(pid).stage != ProjectStage.REPAIRING

    from app.scene.store import get_store
    from app.spatial.validation import validate_scene

    scene = get_store().load(get_project_store().get(pid).scene_ids[-1])
    assert [v for v in validate_scene(scene) if v.severity == "hard"] == []


def test_an_unrepairable_scene_ends_in_a_review_item_not_a_loop(client):
    """Stack four floor pieces into one another in a corner the engine cannot
    untangle: every path must end in a person, within the bound."""
    pid = _planned(client)
    from app.scene.store import get_store

    store = get_store()
    scene = store.load(get_project_store().get(pid).scene_ids[-1])
    room = scene.rooms[0]
    xs = [p[0] for p in room.boundary]
    zs = [p[1] for p in room.boundary]
    bad = scene.model_copy(deep=True)
    in_room = [o for o in bad.objects if o.room_id == room.room_id and o.mount == "floor" and not o.parent_id]
    for o in in_room:
        o.position = ((min(xs) + max(xs)) / 2, 0.0, (min(zs) + max(zs)) / 2)
        o.dimensions = (max(xs) - min(xs) + 1.0, o.dimensions[1], max(zs) - min(zs) + 1.0)
    store.commit(bad, base_version=scene.version)
    _run(pid, "check_scene")
    assert get_runner().wait_idle(120)

    assert get_runner().repair_rounds_used(pid) <= 2
    items = ReviewQueue().items(pid, role="admin", status="open")
    assert len(items) == 1
    assert get_project_store().get(pid).stage == ProjectStage.HUMAN_REVIEW
    rounds = AuditTrail(pid).rounds()
    assert rounds and rounds[-1]["outcome"] == "escalated"


# ── P1-HUMAN-001 ───────────────────────────────────────────────────────────


def test_new_stages_are_added_and_existing_strings_unchanged():
    assert [s.value for s in ProjectStage][:13] == [
        "CREATED", "INPUT_RECEIVED", "ANALYZING", "DESIGN_SPEC_READY", "ASSET_PLANNING", "ASSETS_READY",
        "SCENE_BUILDING", "SCENE_VALIDATING", "CAMERA_PLANNING", "PREVIEW_RENDERING", "FINAL_RENDERING",
        "COMPLETED", "FAILED"]
    assert {"REPAIRING", "HUMAN_REVIEW", "VERIFIED", "CANCELLED"} <= {s.value for s in ProjectStage}


@pytest.mark.parametrize("category, issue_type, audience", [
    (FC.BLENDER_EXECUTION_FAILURE, "build_errors", "operations"),
    (FC.HARDWARE_FAILURE, "", "operations"),
    (FC.VALIDATION_FAILURE, "build_report_missing", "operations"),
    (FC.REPRESENTATION_FAILURE, "", "operations"),
    (FC.PERCEPTION_FAILURE, "", "designer"),
    (FC.ASSET_FAILURE, "appearance", "homeowner"),
    (None, "appearance", "homeowner"),
])
def test_escalations_route_to_the_right_audience(category, issue_type, audience):
    assert audience_for(category, issue_type) == audience


def _open_item(pid, category=FC.BLENDER_EXECUTION_FAILURE, recommendation="accept_as_is"):
    return ReviewHandle().open(project_id=pid, issue="the build reported errors", category=category,
                               issue_type="build_errors", entity_ids=[], evidence_refs=["blender/validation_report.json"],
                               expected={"ok": True}, observed={"errors": ["x"]}, recommendation=recommendation,
                               actions=["accept_as_is", "retry_repair", "replan", "cancel"])


def test_a_rendering_defect_is_never_shown_to_the_homeowner(client):
    pid = _planned(client)
    item = _open_item(pid)
    assert item["audience"] == "operations"
    assert ReviewQueue().items(pid, role="homeowner") == []
    assert [i["item_id"] for i in ReviewQueue().items(pid, role="admin")] == [item["item_id"]]
    assert [i["item_id"] for i in client.get(f"/api/projects/{pid}/reviews").json()["data"]["items"]] == \
        [item["item_id"]], "the admin sees it through the API"


def test_a_review_item_carries_the_six_fields_with_human_names(client):
    pid = _planned(client)
    a, b = _inject_collision(pid)
    _run(pid, "check_scene")
    # the round has resolved; open a case about the same two objects
    item = ReviewHandle().open(project_id=pid, issue="two pieces overlap", category=FC.SOLVER_FAILURE,
                               entity_ids=[a, b], evidence_refs=["planning/spatial_check.json"],
                               expected={"hard_after": 0}, observed={"hard_after": 1},
                               recommendation="retry_repair", actions=["accept_as_is", "retry_repair", "cancel"])
    got = ReviewQueue().get(pid, item["item_id"])
    assert got["issue"] and got["evidence_refs"] and got["expected"] and got["observed"]
    assert got["recommendation"] == "retry_repair" and got["actions"] and got["action_labels"]["retry_repair"]
    assert all(x["name"] != x["id"] and "unnamed" not in x["name"] for x in got["affected"]), got["affected"]
    assert got["attempts"] and got["attempts"][0]["decision"] == "RE_SOLVE", "what was attempted, per round"


def test_an_override_requires_a_reason_and_names_the_person(client):
    pid = _planned(client)
    item = _open_item(pid, recommendation="retry_repair")
    r = client.post(f"/api/projects/{pid}/reviews/{item['item_id']}/decision", json={"action": "accept_as_is"})
    assert r.status_code == 422, r.text
    assert ReviewQueue().get(pid, item["item_id"])["status"] == "open", "a refused decision changed nothing"
    r = client.post(f"/api/projects/{pid}/reviews/{item['item_id']}/decision",
                    json={"action": "accept_as_is", "reason": "The overlap is a rug under a table; it is correct."})
    assert r.status_code == 200, r.text
    d = r.json()["data"]["decision"]
    assert d["is_override"] and d["user_id"] and d["user_email"] and d["reason"].startswith("The overlap")
    assert d["result"] == {"stage": "VERIFIED"}
    got = ReviewQueue().get(pid, item["item_id"])
    assert got["status"] == "resolved" and got["decisions"][0]["decision_id"] == d["decision_id"]


def test_following_the_recommendation_needs_no_reason_and_keeps_project_state(client):
    pid = _planned(client)
    before = get_project_store().get(pid)
    item = _open_item(pid, recommendation="retry_repair")
    r = client.post(f"/api/projects/{pid}/reviews/{item['item_id']}/decision", json={"action": "retry_repair"})
    assert r.status_code == 200, r.text
    result = r.json()["data"]["decision"]["result"]
    assert result["job_type"] == "repair_scene"
    assert get_runner().wait_idle(120)
    job = get_job_store().get(result["job_id"])
    assert job.repair_round == 0, "a person's action is an ordinary job, not an automatic round"
    after = get_project_store().get(pid)
    assert after.scene_ids[:len(before.scene_ids)] == before.scene_ids, "nothing the project had was lost"
    assert client.get(f"/api/projects/{pid}/scene-spec").status_code == 200


def test_a_decision_cannot_be_rewritten(client):
    import sqlite3

    from app.db import get_db

    pid = _planned(client)
    item = _open_item(pid)
    client.post(f"/api/projects/{pid}/reviews/{item['item_id']}/decision", json={"action": "accept_as_is"})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        get_db().execute("UPDATE review_decisions SET reason = 'edited'")
    r = client.post(f"/api/projects/{pid}/reviews/{item['item_id']}/decision", json={"action": "cancel",
                                                                                      "reason": "changed my mind entirely"})
    assert r.status_code == 409, "a resolved item is not re-decided in place"

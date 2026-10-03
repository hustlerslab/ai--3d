"""P1-FRONTEND-002: the review screen's words, from the backend.

Every string the review endpoint returns is scanned for what must never reach
a person: internal ids, check names, category names, status codes.
"""
from __future__ import annotations

import json
import re

import pytest

from app.jobs import get_runner
from app.projects import get_project_store
from app.projects.layout import project_dir
from app.spatial.failures import FailureCategory as FC
from app.supervisor.review import ReviewHandle
from tests.test_asset_rebind import client  # noqa: F401

#: What a person must never read.
FORBIDDEN = [
    re.compile(r"\b(obj|scene|proj|ver|rev|usr|job|cel|inst|verify|spec|val|dir)_[0-9a-z]{4,}\b"),
    re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b"),                   # HUMAN_REVIEW, VALIDATION_FAILURE, RE_SOLVE
    re.compile(r"\b[a-z]+(?:_[a-z]+)+\b"),                      # render_matches_committed_scene, accept_as_is
    re.compile(r"\b(FAIL|PASS|REVIEW_REQUIRED|failure_category)\b"),
]


#: Machine fields the screen styles from and never prints: the render's
#: <img src>, and the two enums (the frontend's DOM test proves they are
#: mapped to words and icons, never rendered raw).
NOT_TEXT = {".render.url", ".status", ".checks.outcome"}


def _strings(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if path + "." + k in NOT_TEXT:
                continue
            yield from _strings(v, path + "." + k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, path)
    elif isinstance(value, str):
        yield path, value


def assert_plain(view: dict) -> None:
    for where, text in _strings(view):
        for rx in FORBIDDEN:
            assert not rx.search(text), f"{where}: {text!r} contains {rx.pattern}"


def _golden(client):  # noqa: F811
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)
    return pid


def _review(client, pid):  # noqa: F811
    r = client.get(f"/api/projects/{pid}/review")
    assert r.status_code == 200, r.text
    view = r.json()["data"]
    assert_plain(view)
    return view


def test_a_project_with_no_design_says_so(client):  # noqa: F811
    pid = client.post("/api/projects", json={"name": "Empty"}).json()["project"]["project_id"]
    view = _review(client, pid)
    assert view["status"] == "not_ready" and view["can_decide"] is False


def test_a_planned_but_unverified_design_says_it_has_not_been_checked(client):  # noqa: F811
    view = _review(client, _golden(client))
    assert view["status"] == "not_verified"
    assert "hasn't been checked" in view["status_text"]
    assert view["can_decide"] is True


def _evidence(pid, *, scene_checks, per_object):
    path = project_dir(pid) / "planning" / "render_verification.json"
    path.write_text(json.dumps({"scene_checks": scene_checks, "per_object": per_object,
                                "summary": {"drifted_object_ids": []}}), encoding="utf-8")


def test_verification_is_told_as_plain_checks(client):  # noqa: F811
    pid = _golden(client)
    _evidence(pid, scene_checks={"expected_objects_exist": "pass", "severe_intersections": "pass",
                                 "circulation": "unknown", "render_matches_committed_scene": "pass"},
              per_object=[{"checks": {"scale": "pass", "floating_objects": "pass", "orientation": "unknown",
                                      "approximate_location": "unknown"}}])
    view = _review(client, pid)
    outcome = {c["label"]: c["outcome"] for c in view["checks"]}
    assert outcome["Every piece was built"] == "passed"
    assert outcome["There is a clear way through the room"] == "not_checked", "unknown is never shown as passed"
    assert outcome["Pieces face the way the picture showed"] == "not_checked"
    assert outcome["Materials and colours match the design"] == "not_checked"
    assert view["status"] == "verified"


def test_a_failed_check_and_an_open_issue_need_attention_and_say_what_to_do(client):  # noqa: F811
    pid = _golden(client)
    _evidence(pid, scene_checks={"render_matches_committed_scene": "fail"}, per_object=[])
    ReviewHandle().open(project_id=pid, issue="1 piece(s) changed after the render was taken",
                        category=FC.VALIDATION_FAILURE, issue_type="render_mismatch", entity_ids=["obj_123456"],
                        evidence_refs=[], expected={}, observed={}, recommendation="accept_as_is",
                        actions=["accept_as_is", "replan", "cancel"])
    view = _review(client, pid)
    assert view["status"] == "needs_attention"
    assert {"label": "The picture shows the current design", "outcome": "failed"} in view["checks"]
    issue = next(i for i in view["issues"] if "changed after the render" in i["text"])
    assert issue["text"] == "1 pieces changed after the render was taken."
    assert issue["next"] == "You can accept it as it is."


def test_a_failed_check_alone_needs_attention(client):  # noqa: F811
    """No open issue at all - a failed check must still stop "verified"."""
    pid = _golden(client)
    _evidence(pid, scene_checks={"severe_intersections": "fail"}, per_object=[])
    view = _review(client, pid)
    assert view["issues"] == []
    assert view["status"] == "needs_attention"
    assert view["status_text"] == "1 thing to look at before you approve."


def test_a_repair_is_shown_as_attempts_out_of_two(client):  # noqa: F811
    """A real repair: a collision injected into the committed scene, checked,
    repaired by the Repair Engine through the Orchestrator."""
    from tests.test_orchestrator import _inject_collision

    pid = _golden(client)
    _inject_collision(pid)
    get_runner().enqueue(pid, "check_scene", {})
    assert get_runner().wait_idle(120)
    view = _review(client, pid)
    assert view["repair"] is not None
    assert view["repair"]["of"] == 2 and 1 <= view["repair"]["attempt"] <= 2
    assert "of 2" in view["repair"]["text"]


def test_the_scan_itself_catches_what_it_is_for():
    """The guard is only worth something if it fires."""
    for bad in ({"status_text": "VALIDATION_FAILURE"}, {"issues": [{"text": "obj_4f2a9c1e is missing", "next": ""}]},
                {"checks": [{"label": "render_matches_committed_scene", "outcome": "failed"}]}):
        with pytest.raises(AssertionError):
            assert_plain(bad)
    assert_plain({"render": {"url": "/files/projects/proj_abc123/previews/x.png"}})


@pytest.mark.blender
def test_the_review_after_a_real_build_and_verification(client, blender_path, monkeypatch):  # noqa: F811
    from app.core import config

    monkeypatch.setenv("BLENDER_PATH", blender_path)
    config.get_settings.cache_clear()
    pid = _golden(client)
    assert client.post(f"/api/projects/{pid}/build", json={"preview": True}).status_code == 200
    assert get_runner().wait_idle(600)
    get_runner().enqueue(pid, "verify", {})
    assert get_runner().wait_idle(300)
    view = _review(client, pid)
    assert view["render"] and view["render"]["url"].endswith("build_preview.png")
    labels = {c["label"] for c in view["checks"]}
    assert "Every piece was built" in labels and "The picture shows the current design" in labels
    assert view["status"] in ("verified", "needs_attention")
    assert get_project_store().get(pid).scene_ids

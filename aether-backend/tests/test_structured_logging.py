"""P0-OBSERVABILITY-001 - a support engineer can reconstruct one customer's
project from the logs alone.

Three claims:

  1. Every line parses as JSON and carries correlation_id, project_id, job_id,
     stage.
  2. Filtering by correlation id returns the complete run.
  3. Logs carry ids ONLY - never a brief, an image path, a prompt or a key.

(3) is the one with teeth. A log aggregator is a second copy of everything it
ingests, usually with different access rules and longer retention than the
database, so a brief logged "temporarily for debugging" outlives the project it
describes.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import (
    JsonFormatter,
    bind,
    current_context,
    install_record_factory,
    new_correlation_id,
)

CID = "cid_a1b2c3d4e5f6"
PID = "proj_a1b2c3d4e5"
JID = "job_0011223344"

BRIEF = ("A warm, modern two-bedroom flat in Bandra for a family of five, "
         "keeping the existing oak flooring and the TV unit.")
FAKE_KEY = "sk-ant-not-a-real-key-0000"


@pytest.fixture(autouse=True)
def _factory():
    install_record_factory()


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _record(message="hello", logger="aether.test", level=logging.INFO, **extra):
    rec = logging.getLogger(logger).makeRecord(
        logger, level, "f.py", 1, message, (), None
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def _line(**kwargs) -> dict:
    return json.loads(JsonFormatter().format(_record(**kwargs)))


# ── 1. every line is JSON with the four fields ───────────────────────────

def test_a_line_is_json_with_the_four_correlation_fields():
    line = _line(message="job.start")
    for field in ("ts", "level", "logger", "message",
                  "correlation_id", "project_id", "job_id", "stage"):
        assert field in line, f"{field} missing"
    assert line["message"] == "job.start"


def test_the_fields_are_empty_strings_not_null_when_unbound():
    """A formatter must never have to decide what a missing id looks like, and
    a consumer must never have to handle both null and ""."""
    line = _line()
    for field in ("correlation_id", "project_id", "job_id", "stage"):
        assert line[field] == ""


def test_bound_ids_appear_on_the_line():
    with bind(correlation_id=CID, project_id=PID, job_id=JID, stage="analyze"):
        line = _line(message="job.start")
    assert line["correlation_id"] == CID
    assert line["project_id"] == PID
    assert line["job_id"] == JID
    assert line["stage"] == "analyze"


def test_the_timestamp_is_utc_with_a_z():
    """A log read in a different timezone than it was written in misleads."""
    from datetime import datetime, timezone

    ts = _line()["ts"]
    assert ts.endswith("Z"), ts
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 120


def test_ids_are_captured_when_the_record_is_MADE_not_when_it_is_written():
    """The property that makes this correct under a buffered or queued handler.

    Reading contextvars at format time looks equivalent and is not: a handler
    that writes later, on another thread, would stamp whatever context happens
    to be current then - and a line that still has ids, naming the wrong
    customer, is worse than one with none.
    """
    with bind(correlation_id=CID, project_id=PID):
        record = _record(message="job.start")

    # Formatted OUTSIDE the bind, exactly as a queued handler would.
    line = json.loads(JsonFormatter().format(record))
    assert line["correlation_id"] == CID
    assert line["project_id"] == PID


def test_context_is_restored_after_a_block():
    """A failed job must not leave its ids attached to whatever this worker
    thread picks up next."""
    with bind(project_id=PID):
        assert current_context()["project_id"] == PID
    assert current_context()["project_id"] == ""


def test_a_nested_block_restores_the_outer_value():
    with bind(project_id="proj_outer"):
        with bind(project_id="proj_inner"):
            assert current_context()["project_id"] == "proj_inner"
        assert current_context()["project_id"] == "proj_outer"


def test_an_unknown_context_field_is_refused():
    """A typo'd field would silently never appear on any line."""
    with pytest.raises(ValueError, match="unknown log context field"):
        bind(projcet_id="typo")


def test_an_exception_is_carried_as_fields_not_swallowed():
    import sys

    try:
        raise RuntimeError("upstream returned 503")
    except RuntimeError:
        rec = logging.getLogger("aether.test").makeRecord(
            "aether.test", logging.ERROR, "f.py", 1, "job.failed", (), sys.exc_info()
        )
    line = json.loads(JsonFormatter().format(rec))
    assert line["exc_type"] == "RuntimeError"
    assert "503" in line["exc"]


# ── 2. filtering by correlation id returns the complete run ──────────────

def test_filtering_by_correlation_id_returns_the_whole_run_and_nothing_else():
    mine, theirs = new_correlation_id(), new_correlation_id()
    stream = []

    with bind(correlation_id=mine, project_id=PID):
        stream.append(_line(message="project.created"))
        with bind(job_id="job_1", stage="analyze"):
            stream.append(_line(message="job.start"))
            stream.append(_line(message="job.succeeded"))
        with bind(job_id="job_2", stage="scene_plan"):
            stream.append(_line(message="job.start"))
    with bind(correlation_id=theirs, project_id="proj_somebody_else"):
        stream.append(_line(message="job.start"))

    run = [x for x in stream if x["correlation_id"] == mine]
    assert len(run) == 4, "the run is not complete"
    assert {x["message"] for x in run} == {
        "project.created", "job.start", "job.succeeded"}
    assert {x["job_id"] for x in run} == {"", "job_1", "job_2"}
    assert all(x["project_id"] == PID for x in run), "another project leaked in"


def test_two_projects_never_share_a_correlation_id(client):
    from app.projects import get_project_store

    token = client.post("/api/auth/register",
                        json={"email": "alice@example.com",
                              "password": "alice-password-123"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.cookies.clear()

    ids = set()
    for name in ("one", "two", "three"):
        pid = client.post("/api/projects", json={"name": name},
                          headers=headers).json()["project"]["project_id"]
        cid = get_project_store().get(pid).correlation_id
        assert cid.startswith("cid_"), f"project {name} has no correlation id: {cid!r}"
        ids.add(cid)
    assert len(ids) == 3, "two projects share a correlation id"


def test_a_job_inherits_its_projects_correlation_id(client):
    """Copied onto the job row at enqueue, so a job can be traced back to its
    run even when the project lookup is what failed."""
    from app.jobs import get_job_store
    from app.projects import get_project_store

    token = client.post("/api/auth/register",
                        json={"email": "alice@example.com",
                              "password": "alice-password-123"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.cookies.clear()

    pid = client.post("/api/projects", json={"name": "p"},
                      headers=headers).json()["project"]["project_id"]
    job = client.post(f"/api/projects/{pid}/jobs", json={"type": "noop", "params": {}},
                      headers=headers).json()["job"]

    stored = get_job_store().get(job["job_id"])
    assert stored.correlation_id == get_project_store().get(pid).correlation_id
    assert stored.correlation_id.startswith("cid_")


def test_a_request_gets_a_correlation_id_back(client):
    """So a user can quote it in a support request and somebody can find the
    run without asking them what they clicked."""
    r = client.get("/api/health")
    assert r.headers.get("X-Correlation-Id", "").startswith("cid_")


def test_an_inbound_correlation_id_is_honoured(client):
    """A frontend retry, or a call that fans out into jobs, must stay one
    thread in the logs."""
    r = client.get("/api/health", headers={"X-Correlation-Id": CID})
    assert r.headers.get("X-Correlation-Id") == CID


# ── 3. ids only - the log scan ───────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "api_key", "meshy_api_key", "auth_token", "session_token",
    "password", "authorization", "client_secret", "credential",
])
def test_a_field_that_looks_like_a_secret_is_redacted(field):
    """A seatbelt, not a licence. The rule is that these are not passed at all;
    this is what happens when somebody does it anyway."""
    line = _line(**{field: FAKE_KEY})
    assert line[field] == "[redacted]"
    assert FAKE_KEY not in json.dumps(line)


def test_an_ordinary_field_is_carried_through():
    """Redaction must not eat the fields that make a line useful."""
    line = _line(message="job.start", type="scene_plan", duration_ms=1234)
    assert line["type"] == "scene_plan"
    assert line["duration_ms"] == 1234


def test_a_real_run_never_logs_the_brief(client, caplog):
    """The scan the task asks for, over a real request and job cycle."""
    caplog.set_level(logging.DEBUG)

    token = client.post("/api/auth/register",
                        json={"email": "alice@example.com",
                              "password": "alice-password-123"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.cookies.clear()

    pid = client.post("/api/projects", json={"name": "Sharma Residence",
                                             "description": BRIEF},
                      headers=headers).json()["project"]["project_id"]
    client.post(f"/api/projects/{pid}/jobs", json={"type": "noop", "params": {}},
                headers=headers)

    formatter = JsonFormatter()
    rendered = "\n".join(formatter.format(r) for r in caplog.records)

    for fragment in (BRIEF[:40], BRIEF[-40:], "Bandra", "oak flooring"):
        assert fragment not in rendered, f"the brief leaked into the logs: {fragment!r}"
    assert "alice-password-123" not in rendered, "a password reached the logs"
    assert "alice@example.com" not in rendered, "an email address reached the logs"


def test_no_provider_key_can_reach_a_log_line(client, caplog, monkeypatch):
    """Even with a key configured, nothing may print one."""
    from app.core import config

    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("INTELLIGENCE_PROVIDER", "gemini")
    config.get_settings.cache_clear()

    from app.intelligence import get_provider, reset_provider

    reset_provider()
    get_provider()                       # logs the resolved provider and model

    rendered = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    assert FAKE_KEY not in rendered, "a provider key reached the logs"
    # ...but the line naming the model must still be there, or the
    # provider-drift warning from P0-AI-001 would have been silenced.
    assert "gemini" in rendered

    config.get_settings.cache_clear()
    reset_provider()

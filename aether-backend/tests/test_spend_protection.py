"""P0-SEC-003 - nobody can drain the Meshy credits, and a restart cannot reset
a spend limit.

The task names three acceptance criteria and a fault injection. The third is
the one that needs proving rather than asserting:

    "Restarting the process does not reset accumulated spend."

A cap held in memory satisfies every other test in this file and fails that
one. So the restart is actually performed - every singleton is dropped and the
database reopened from disk, which is what a process restart does to this
backend - and the ledger is read again on the other side.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.spend import check_budget, project_spend, record_spend, user_spend

ALICE = ("alice@example.com", "alice-password-123")
BOB = ("bob@example.com", "bob-password-123")

PROJECT = "proj_test"
USER = "usr_test"
PER_PIECE = 30


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _register(client, creds):
    email, password = creds
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


# ── the ledger ────────────────────────────────────────────────────────────

def test_a_charge_is_remembered(env):
    record_spend(PROJECT, 30, user_id=USER, item_key="living_room.sofa.0")
    assert project_spend(PROJECT).total == 30
    assert user_spend(USER).total == 30


def test_measured_and_estimated_are_never_mixed(env):
    """An estimated total that reads as measured is how a budget becomes
    fiction. They are summed separately and both stay visible."""
    record_spend(PROJECT, 30, user_id=USER)
    record_spend(PROJECT, 30, user_id=USER, is_estimate=True)

    spend = project_spend(PROJECT)
    assert spend.measured == 30
    assert spend.estimated == 30
    assert spend.total == 60, "an estimate still counts against the cap"
    assert spend.is_exact is False, "the total must not claim to be measured"


def test_spend_is_attributed_to_both_the_project_and_the_user(env):
    record_spend("proj_one", 30, user_id=USER)
    record_spend("proj_two", 30, user_id=USER)
    assert project_spend("proj_one").total == 30
    assert user_spend(USER).total == 60, "a user's spend crosses their projects"


# ── the caps ──────────────────────────────────────────────────────────────

def _budget(pieces, project_cap=600, user_cap=3000, user_id=USER):
    return check_budget(PROJECT, user_id, pieces, PER_PIECE, project_cap, user_cap)


def test_an_untouched_project_may_spend(env):
    d = _budget(5)
    assert d.allowed == 5 and not d.blocked and d.reason == ""


def test_the_project_cap_allows_exactly_what_is_left(env):
    """600 credits, 540 spent, 60 left -> two pieces at 30 each."""
    for _ in range(18):
        record_spend(PROJECT, 30, user_id=USER)
    d = _budget(5, project_cap=600)
    assert d.allowed == 2
    assert d.blocked and not d.halted
    assert "this project" in d.reason and "540" in d.reason


def test_a_reached_project_cap_halts_generation(env):
    for _ in range(20):
        record_spend(PROJECT, 30, user_id=USER)
    d = _budget(5, project_cap=600)
    assert d.allowed == 0 and d.halted


def test_the_user_cap_binds_even_when_the_project_has_room(env):
    """A new project does not reset what a person has already spent."""
    for _ in range(10):
        record_spend("some_other_project", 30, user_id=USER)
    d = _budget(5, project_cap=600, user_cap=300)
    assert d.allowed == 0 and d.halted
    assert "your account" in d.reason


def test_the_tighter_of_the_two_caps_wins(env):
    for _ in range(15):
        record_spend(PROJECT, 30, user_id=USER)   # 450 against this project and user
    tight_project = _budget(10, project_cap=480, user_cap=3000)
    tight_user = _budget(10, project_cap=3000, user_cap=510)
    assert tight_project.allowed == 1
    assert tight_user.allowed == 2


def test_a_cap_of_zero_means_no_limit_and_must_be_deliberate(env):
    """For a deployment that runs uncapped on purpose. The defaults in
    config.py are 600 and 3000, never 0."""
    from app.core.config import get_settings

    for _ in range(100):
        record_spend(PROJECT, 30, user_id=USER)
    assert _budget(5, project_cap=0, user_cap=0).allowed == 5

    settings = get_settings()
    assert settings.meshy_max_credits_per_project > 0
    assert settings.meshy_max_credits_per_user > 0


def test_an_anonymous_batch_is_still_capped_by_the_project(env):
    """No user id - the per-user cap cannot apply, so the project cap must."""
    for _ in range(20):
        record_spend(PROJECT, 30, user_id=None)
    d = check_budget(PROJECT, None, 5, PER_PIECE, 600, 3000)
    assert d.halted, "without a user id the project cap is the only thing standing there"


# ── fault injection: the criterion a memory counter cannot meet ───────────

def test_accumulated_spend_survives_a_process_restart(env):
    """Kill the process mid-project; the cap must still be there afterwards.

    `_reset_singletons()` is exactly what a restart does to this backend: every
    cached store, the runner and the database handle are dropped and rebuilt
    from disk. A counter in memory passes every other test in this file and
    fails this one.
    """
    from tests.conftest import _reset_singletons

    for _ in range(12):                                   # 360 credits
        record_spend(PROJECT, 30, user_id=USER)
    before = project_spend(PROJECT).total
    assert before == 360

    _reset_singletons()                                   # <- the restart

    after = project_spend(PROJECT).total
    assert after == before, "spend was forgotten across a restart"
    d = _budget(10, project_cap=600)
    assert d.allowed == 8, "the cap must be computed from the surviving ledger"


def test_a_half_finished_batch_keeps_the_credits_it_already_spent(env):
    """Charges are written as each piece confirms, not at the end of the batch.
    A crash halfway must not refund what was really spent."""
    from tests.conftest import _reset_singletons

    for i in range(3):
        record_spend(PROJECT, 30, user_id=USER, item_key=f"piece_{i}")
    # ... the process dies here, before the remaining seven pieces ...
    _reset_singletons()

    assert project_spend(PROJECT).total == 90, "three confirmed charges must survive"


# ── the route: 401 means zero spend ──────────────────────────────────────

def test_an_unauthenticated_generation_request_spends_nothing(client):
    alice = _register(client, ALICE)
    pid = client.post("/api/projects", json={"name": "spend"}, headers=alice) \
                .json()["project"]["project_id"]

    assert client.post(f"/api/projects/{pid}/elements/generate").status_code == 401
    assert client.post(f"/api/projects/{pid}/jobs",
                       json={"type": "generate_elements", "params": {}}).status_code == 401
    assert project_spend(pid).total == 0, "a refused request must leave no charge"


def test_another_user_cannot_spend_on_your_project(client):
    alice = _register(client, ALICE)
    pid = client.post("/api/projects", json={"name": "spend"}, headers=alice) \
                .json()["project"]["project_id"]
    bob = _register(client, BOB)

    assert client.post(f"/api/projects/{pid}/elements/generate", headers=bob).status_code == 403
    assert client.post(f"/api/projects/{pid}/jobs",
                       json={"type": "generate_elements", "params": {}},
                       headers=bob).status_code == 403
    assert project_spend(pid).total == 0


def test_a_job_records_who_asked_for_it(client):
    """Without this the per-user cap has nothing to attribute a charge to."""
    from app.auth.service import get_user_by_email
    from app.jobs import get_job_store

    alice = _register(client, ALICE)
    pid = client.post("/api/projects", json={"name": "spend"}, headers=alice) \
                .json()["project"]["project_id"]
    job = client.post(f"/api/projects/{pid}/jobs",
                      json={"type": "noop", "params": {}}, headers=alice).json()["job"]

    stored = get_job_store().get(job["job_id"])
    assert stored.created_by == get_user_by_email(ALICE[0])["user_id"]


def test_the_caller_cannot_forge_who_asked(client):
    """`params` is caller-controlled. `created_by` is a column set from the
    authenticated request, and must ignore anything in the body."""
    from app.auth.service import get_user_by_email
    from app.jobs import get_job_store

    alice = _register(client, ALICE)
    pid = client.post("/api/projects", json={"name": "spend"}, headers=alice) \
                .json()["project"]["project_id"]
    job = client.post(
        f"/api/projects/{pid}/jobs",
        json={"type": "noop", "params": {"created_by": "usr_somebody_else"}},
        headers=alice,
    ).json()["job"]

    stored = get_job_store().get(job["job_id"])
    assert stored.created_by == get_user_by_email(ALICE[0])["user_id"]
    assert stored.created_by != "usr_somebody_else"

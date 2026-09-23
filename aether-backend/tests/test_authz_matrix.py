"""P0-SEC-002 - authorization at one choke point, deny by default.

The matrix this file enforces:

| Caller            | Own project | Someone else's | Unowned (legacy) |
|-------------------|-------------|----------------|------------------|
| anonymous         | 401         | 401            | 401              |
| signed-in owner   | 200         | **403**        | 403              |
| signed-in member  | 200         | -              | -                |
| admin             | 200         | 200            | 200              |

Plus the thing that must NOT change:
  * `/health` stays anonymous - a liveness probe that needs credentials
    reports the wrong thing during an outage.

The tour route used to be listed here too. P0-SEC-004 replaced its anonymous
allow-list entry with a capability token, so the assertion about it is now
inverted; see test_the_tour_needs_a_share_token_now.

The route-coverage test at the bottom is the important one. Hand-written cases
cover the routes somebody thought of; it walks every registered route and fails
on any that is neither gated nor on the justified allow-list.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ALICE = ("alice@example.com", "alice-password-123")
BOB = ("bob@example.com", "bob-password-123")


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _register(client, creds):
    """Register and return a bearer-header dict.

    The cookie jar is cleared each time: TestClient keeps the Set-Cookie from
    registration, which would silently authenticate the "anonymous" cases and
    make this entire file pass for the wrong reason.
    """
    email, password = creds
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _make_project(client, headers, name="A flat in Bandra"):
    r = client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["project"]["project_id"]


# ── the core matrix ───────────────────────────────────────────────────────

def test_anonymous_is_401_not_403(client):
    """401 and 403 are different instructions. Collapsing them leaves a
    signed-out user retrying a password they never entered."""
    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    assert client.get(f"/api/projects/{pid}").status_code == 401


def test_the_owner_gets_their_own_project(client):
    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    assert client.get(f"/api/projects/{pid}", headers=alice).status_code == 200


def test_another_user_is_403(client):
    """The whole point of the task: a person's home photographs are visible
    only to them."""
    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    bob = _register(client, BOB)
    r = client.get(f"/api/projects/{pid}", headers=bob)
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_a_project_that_does_not_exist_answers_like_one_that_is_not_yours(client):
    """Otherwise the 403/404 split is a free oracle for which ids are real."""
    alice = _register(client, ALICE)
    _make_project(client, alice)
    bob = _register(client, BOB)
    assert client.get("/api/projects/proj_does_not_exist", headers=bob).status_code == 403


def test_an_assigned_member_gets_in(client):
    from app.auth.authz import add_member
    from app.auth.service import get_user_by_email

    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    bob = _register(client, BOB)
    assert client.get(f"/api/projects/{pid}", headers=bob).status_code == 403

    add_member(pid, get_user_by_email(BOB[0])["user_id"])
    assert client.get(f"/api/projects/{pid}", headers=bob).status_code == 200


def test_the_first_account_becomes_admin_and_sees_everything(client):
    """Bootstrap. Alice registers first, so she is the administrator."""
    alice = _register(client, ALICE)
    bob = _register(client, BOB)
    bobs_project = _make_project(client, bob, name="Bob's flat")
    assert client.get(f"/api/projects/{bobs_project}", headers=alice).status_code == 200


def test_the_second_account_is_not_an_admin(client):
    """If bootstrap fired twice, every user would be an administrator."""
    _register(client, ALICE)
    bob = _register(client, BOB)
    assert client.get("/api/auth/me", headers=bob).json()["data"]["user"]["role"] == "homeowner"


# ── mutating routes, not just reads ───────────────────────────────────────

@pytest.mark.parametrize("method,suffix,body", [
    ("POST", "/analyze", {}),
    ("POST", "/scene-plan", {}),
    ("POST", "/elements/generate", {}),
    ("POST", "/jobs", {"type": "noop", "params": {}}),
    ("GET", "/jobs", None),
    ("GET", "/events", None),
    ("GET", "/outputs", None),
])
def test_another_user_cannot_touch_a_project_through_any_of_these(client, method, suffix, body):
    """Reading someone's project is bad. Spending their Meshy credits is worse,
    and `POST /jobs` reaches every job type including both generators."""
    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    bob = _register(client, BOB)
    url = f"/api/projects/{pid}{suffix}"
    assert client.request(method, url, json=body, headers=bob).status_code == 403
    assert client.request(method, url, json=body).status_code == 401


# ── what must NOT have broken ─────────────────────────────────────────────

def test_the_tour_needs_a_share_token_now(client):
    """SUPERSEDED BY P0-SEC-004, and inverted on purpose.

    This used to assert that `GET /projects/{id}/tour` was anonymous, which was
    correct while the allow-list said so - P0-SEC-002 deliberately kept the
    share link working and left the capability-token work to P0-SEC-004.

    That task is now done: the project id no longer authorises anything, so
    holding it alone is a 401. The full share-link behaviour - minting, scope,
    revocation, expiry - lives in tests/test_share_links.py. What is kept here
    is the one claim this file owns: the gate refuses, and refuses with 401.
    """
    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    assert client.get(f"/api/projects/{pid}/tour").status_code == 401

    # The owner, signed in, still reaches the handler - 404 because this
    # project has no rendered tour, which proves the gate let the request past.
    r = client.get(f"/api/projects/{pid}/tour", headers=alice)
    assert r.status_code == 404 and r.json()["error"]["code"] == "TOUR_NOT_READY"


def test_health_is_still_anonymous(client):
    assert client.get("/api/health").status_code == 200


def test_the_auth_routes_are_still_reachable_without_a_session(client):
    """You cannot authenticate in order to authenticate."""
    assert client.get("/api/auth/session").status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": "nobody@example.com", "password": "x" * 12}).status_code == 401


def test_listing_projects_shows_only_your_own(client):
    """The gate answers "may you touch project X"; a list has no X. Without a
    filter a signed-in stranger could read every project's name and id, which
    is most of what a client brief reveals."""
    alice = _register(client, ALICE)            # admin by bootstrap
    bob = _register(client, BOB)
    bob_pid = _make_project(client, bob, name="Bob's private brief")

    bob_list = client.get("/api/projects", headers=bob).json()["data"]
    assert [p["project_id"] for p in bob_list] == [bob_pid]

    alice_list = client.get("/api/projects", headers=alice).json()["data"]
    assert bob_pid in [p["project_id"] for p in alice_list], "admin sees all"

    assert client.get("/api/projects").status_code == 401


def test_a_new_project_has_an_owner_immediately(client):
    """A project that exists unowned for even one request is a project only an
    admin can reach - including the person who just made it."""
    from app.auth.authz import project_owner
    from app.auth.service import get_user_by_email

    alice = _register(client, ALICE)
    pid = _make_project(client, alice)
    assert project_owner(pid) == get_user_by_email(ALICE[0])["user_id"]


def test_an_unowned_legacy_project_is_not_public(client):
    """NULL owner means unclaimed, not world-readable."""
    from app.db.sqlite import get_db

    alice = _register(client, ALICE)            # admin
    pid = _make_project(client, alice)
    get_db().execute("UPDATE projects SET owner_id = NULL WHERE project_id = ?", (pid,))

    bob = _register(client, BOB)
    assert client.get(f"/api/projects/{pid}", headers=bob).status_code == 403
    assert client.get(f"/api/projects/{pid}").status_code == 401
    assert client.get(f"/api/projects/{pid}", headers=alice).status_code == 200, "admin may"


# ── coverage: the test that catches the route nobody thought of ───────────

def test_every_registered_route_is_either_gated_or_deliberately_anonymous(client):
    """Walk the real route table. Any route that answers a request from nobody
    must be on the justified allow-list in authz.py - not merely overlooked.

    This is what makes "deny by default" a property of the system rather than a
    property of the cases someone remembered to write.
    """
    from app.api.projects_routes import router as projects_router
    from app.api.routes import router as scenes_router
    from app.auth.authz import is_anonymous

    unguarded = []
    for router in (scenes_router, projects_router):
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = set(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"}
            if not path or not methods:
                continue
            for method in sorted(methods):
                # Substitute a syntactically valid id so routing succeeds; the
                # request must then be refused by the gate, not by a 404.
                concrete = path
                for name in ("project_id", "scene_id", "job_id", "asset_id",
                             "material_id", "proposal_id", "input_id", "room_id"):
                    concrete = concrete.replace("{%s}" % name, "zz_probe")
                if "{" in concrete:
                    continue  # a param this test does not know how to fill
                r = client.request(method, concrete, json={})
                anonymous_ok = is_anonymous(method, concrete)
                if r.status_code == 401:
                    assert not anonymous_ok, f"{method} {concrete} is allow-listed yet returned 401"
                elif not anonymous_ok:
                    unguarded.append(f"{method} {concrete} -> {r.status_code}")

    assert not unguarded, (
        "these routes answered an unauthenticated request without being on the "
        "anonymous allow-list:\n  " + "\n  ".join(unguarded)
    )

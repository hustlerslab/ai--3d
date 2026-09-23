"""P0-SEC-001 - identity: register, sign in, be recognised, be forgotten.

This file owns IDENTITY. Authorization - who may touch which project - is
tested in tests/test_authz_matrix.py.

A note on history, because two tests here read oddly without it. P0-SEC-001
shipped identity under an explicit contract: "capability, not enforcement". So
this file originally asserted that all 63 existing routes were STILL OPEN,
guarding against the likelier mistake of gating the whole API in the commit
that introduced logins. P0-SEC-002 is the task that deliberately closes them,
so those assertions were inverted rather than deleted, and say so in place.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

EMAIL = "owner@example.com"
PASSWORD = "correct-horse-battery"   # >= MIN_PASSWORD_LEN, synthetic


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _register(client, email=EMAIL, password=PASSWORD, **extra):
    return client.post("/api/auth/register", json={"email": email, "password": password, **extra})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── registration ──────────────────────────────────────────────────────────

def test_a_person_can_register_and_is_signed_in_immediately(client):
    r = _register(client)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["user"]["email"] == EMAIL
    assert data["user"]["user_id"].startswith("usr_")
    # The FIRST account on an instance is promoted to administrator and adopts
    # any unowned projects - P0-SEC-002 bootstrap. Before that task this
    # asserted "homeowner", which was correct then and is wrong now.
    assert data["user"]["role"] == "admin"
    assert data["bootstrapped"] is True

    second = client.post("/api/auth/register",
                         json={"email": "second@example.com", "password": PASSWORD})
    assert second.json()["data"]["user"]["role"] == "homeowner", (
        "only the first account is promoted; if bootstrap replayed, everyone "
        "on the instance would be an administrator"
    )

    assert data["token"]
    # Registering signs you in, so the token works without a second round trip.
    assert client.get("/api/auth/me", headers=_auth(data["token"])).status_code == 200


def test_the_response_never_carries_the_password_or_its_hash(client):
    """Whatever is in this body is what leaks if a proxy logs it."""
    body = _register(client).text
    assert PASSWORD not in body
    assert "scrypt" not in body
    assert "password_hash" not in body


def test_the_same_email_cannot_register_twice(client):
    assert _register(client).status_code == 200
    r = _register(client)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_a_short_password_is_refused(client):
    r = _register(client, password="short")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"


def test_a_malformed_email_is_refused(client):
    r = _register(client, email="not-an-email")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_EMAIL"


def test_nobody_can_make_themselves_an_admin_by_asking(client):
    """The single most valuable test in this file. `role` is caller-controlled
    input; if self-registration honoured it, the authorization work in
    P0-SEC-002 would be decorative from the day it shipped."""
    r = _register(client, role="admin")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_NOT_SELF_ASSIGNABLE"

    from app.db.sqlite import get_db
    assert get_db().one("SELECT user_id FROM users WHERE email = ?", (EMAIL,)) is None, \
        "a rejected role must not leave a homeowner account behind"


def test_email_case_and_padding_do_not_create_a_second_account(client):
    assert _register(client).status_code == 200
    assert _register(client, email="  OWNER@Example.COM  ").status_code == 409


# ── signing in ────────────────────────────────────────────────────────────

def test_sign_in_with_the_right_password(client):
    _register(client)
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["data"]["user"]["email"] == EMAIL


def test_a_wrong_password_and_an_unknown_account_are_indistinguishable(client):
    """Different messages here would be a free account-enumeration oracle."""
    _register(client)
    wrong = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password-x"})
    missing = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["error"] == missing.json()["error"]


def test_each_sign_in_issues_a_distinct_session(client):
    _register(client)
    a = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["data"]["token"]
    b = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["data"]["token"]
    assert a != b
    # Signing in on a phone must not sign you out on a laptop.
    assert client.get("/api/auth/me", headers=_auth(a)).status_code == 200
    assert client.get("/api/auth/me", headers=_auth(b)).status_code == 200


# ── the dependency ────────────────────────────────────────────────────────

def test_no_token_is_401(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize("header", [
    {"Authorization": "Bearer not-a-real-token"},
    {"Authorization": "Basic abc123"},
    {"Authorization": "Bearer"},
    {"Authorization": ""},
])
def test_a_token_that_is_not_a_live_session_is_401(client, header):
    assert client.get("/api/auth/me", headers=header).status_code == 401


def test_an_expired_session_is_401(client):
    """Forced rather than waited for - the TTL is fourteen days."""
    from app.auth.service import expire_session_now

    token = _register(client).json()["data"]["token"]
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200
    expire_session_now(token)
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_a_revoked_session_stops_working_at_once(client):
    token = _register(client).json()["data"]["token"]
    assert client.post("/api/auth/logout", headers=_auth(token)).json()["data"]["ended"] is True
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_logging_out_twice_is_not_an_error(client):
    """A sign-out that can fail teaches people to close the tab instead, which
    leaves the session alive."""
    token = _register(client).json()["data"]["token"]
    client.post("/api/auth/logout", headers=_auth(token))
    second = client.post("/api/auth/logout", headers=_auth(token))
    assert second.status_code == 200 and second.json()["data"]["ended"] is False


def test_logout_everywhere_kills_every_session(client):
    """The laptop-left-on-a-train control. A JWT scheme could not offer it."""
    _register(client)
    tokens = [
        client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
              .json()["data"]["token"]
        for _ in range(3)
    ]
    r = client.post("/api/auth/logout-everywhere", headers=_auth(tokens[0]))
    assert r.status_code == 200 and r.json()["data"]["revoked"] >= 3
    for t in tokens:
        assert client.get("/api/auth/me", headers=_auth(t)).status_code == 401


def test_a_disabled_account_loses_its_live_sessions_immediately(client):
    """Not "when the session expires". Disabling has to mean now."""
    from app.db.sqlite import get_db

    token = _register(client).json()["data"]["token"]
    get_db().execute(
        "UPDATE users SET disabled_at = '2026-09-21T00:00:00Z' WHERE email = ?", (EMAIL,)
    )
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_the_session_route_is_anonymous_safe(client):
    """A frontend deciding whether to show a sign-in button should not have to
    treat the normal signed-out state as an error."""
    anon = client.get("/api/auth/session")
    assert anon.status_code == 200 and anon.json()["data"]["authenticated"] is False

    token = _register(client).json()["data"]["token"]
    signed_in = client.get("/api/auth/session", headers=_auth(token))
    assert signed_in.json()["data"]["authenticated"] is True


def test_the_cookie_is_httponly_so_script_cannot_read_it(client):
    cookie = _register(client).headers.get("set-cookie", "")
    assert "allure_session=" in cookie
    assert "HttpOnly" in cookie
    assert "lax" in cookie.lower()


def test_a_cookie_alone_authenticates(client):
    """TestClient keeps the cookie from register; /me must accept it with no
    Authorization header, because that is how the browser will call it."""
    _register(client)
    assert client.get("/api/auth/me").status_code == 200


# ── the half that is easy to forget ───────────────────────────────────────

def test_the_api_is_now_closed_to_anonymous_callers(client):
    """RETIRED AND REPLACED by P0-SEC-002.

    This used to assert the opposite - that the whole API was still open -
    because P0-SEC-001's contract was "capability, not enforcement" and the
    likeliest mistake was gating all 63 routes in the commit that introduced
    logins. P0-SEC-002 is the task that deliberately closes them, so the old
    assertion is not weakened here, it is inverted on purpose.

    The full role matrix lives in tests/test_authz_matrix.py. What is kept here
    is the narrow claim this file owns: an anonymous caller is refused with 401,
    not 403, and not a silent empty result.
    """
    for method, path in (
        ("GET", "/api/projects"),
        ("GET", "/api/catalog"),
        ("GET", "/api/jobs/types"),
        ("GET", "/api/credits"),
    ):
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} is reachable without signing in"

    created = client.post("/api/projects", json={"name": "Anonymous project"})
    assert created.status_code == 401, "anyone could create projects on your instance"


def test_password_hashes_are_never_stored_in_plaintext(client):
    from app.db.sqlite import get_db

    _register(client)
    row = get_db().one("SELECT password_hash FROM users WHERE email = ?", (EMAIL,))
    assert PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith("scrypt$")


def test_the_session_token_itself_is_never_stored(client):
    """A database leak must not hand over live sessions."""
    from app.db.sqlite import get_db

    token = _register(client).json()["data"]["token"]
    stored = [r["token_hash"] for r in get_db().query("SELECT token_hash FROM sessions")]
    assert stored and token not in stored
    assert all(len(h) == 64 for h in stored), "expected sha256 hex"

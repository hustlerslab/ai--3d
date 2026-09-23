"""P0-SEC-006 - a single client cannot exhaust the service or the job queue.

Three acceptance criteria, and the third is the one usually skipped:

  1. Exceeding a limit returns 429.
  2. Limits are configurable.
  3. **Normal use is unaffected.**

(3) matters because a limiter that fires during ordinary studio use is worse
than none: it teaches people to reload harder, and it teaches whoever is on
call to raise every limit until the thing is decorative.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import ratelimit

ALICE = ("alice@example.com", "alice-password-123")
BOB = ("bob@example.com", "bob-password-123")


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


def _settings(**over):
    from app.core.config import get_settings

    s = get_settings()

    class _S:
        rate_limit_enabled = over.get("enabled", True)
        rate_limit_window_seconds = over.get("window", 60)
        rate_limit_auth_per_window = over.get("auth", s.rate_limit_auth_per_window)
        rate_limit_spend_per_window = over.get("spend", s.rate_limit_spend_per_window)
        rate_limit_write_per_window = over.get("write", s.rate_limit_write_per_window)
        rate_limit_read_per_window = over.get("read", s.rate_limit_read_per_window)

    return _S


# ── which bucket a route lands in ────────────────────────────────────────

@pytest.mark.parametrize("method,path,expected", [
    ("POST", "/api/auth/login", "auth"),
    ("POST", "/api/auth/register", "auth"),
    ("GET", "/api/auth/session", "auth"),
    ("POST", "/api/projects/p1/elements/generate", "spend"),
    ("POST", "/api/projects/p1/assets/resolve", "spend"),
    ("POST", "/api/projects/p1/jobs", "spend"),
    ("POST", "/api/projects", "write"),
    ("PATCH", "/api/projects/p1", "write"),
    ("DELETE", "/api/projects/p1", "write"),
    ("GET", "/api/projects", "read"),
    ("GET", "/api/health", "read"),
])
def test_routes_land_in_the_right_bucket(method, path, expected):
    """`POST /jobs` is priced as spending even though most job types are free:
    it is the wildcard dispatcher and reaches both Meshy handlers."""
    assert ratelimit.bucket_for(method, path) == expected


# ── 1. exceeding a limit returns 429 ─────────────────────────────────────

def test_the_window_lets_exactly_the_limit_through():
    ratelimit.reset()
    s = _settings(write=3)
    got = [ratelimit.check("POST", "/api/projects", principal_id="usr_a",
                           client="1.2.3.4", settings=s).allowed for _ in range(5)]
    assert got == [True, True, True, False, False]


def test_a_refusal_says_how_long_to_wait():
    """A 429 with no retry hint is an invitation to hammer."""
    ratelimit.reset()
    s = _settings(write=1, window=60)
    ratelimit.check("POST", "/api/projects", principal_id="usr_a", client="1.2.3.4", settings=s)
    d = ratelimit.check("POST", "/api/projects", principal_id="usr_a", client="1.2.3.4", settings=s)
    assert d.allowed is False
    assert 1 <= d.retry_after <= 61


def test_one_principal_cannot_exhaust_another():
    ratelimit.reset()
    s = _settings(write=2)
    for _ in range(3):
        ratelimit.check("POST", "/api/projects", principal_id="usr_a", client="1.2.3.4", settings=s)
    # usr_a is out; usr_b is untouched, from the very same address.
    assert ratelimit.check("POST", "/api/projects", principal_id="usr_a",
                           client="1.2.3.4", settings=s).allowed is False
    assert ratelimit.check("POST", "/api/projects", principal_id="usr_b",
                           client="1.2.3.4", settings=s).allowed is True


def test_the_auth_bucket_keys_on_the_address_not_the_principal():
    """A login attempt has no principal, and one that did would let an attacker
    reset their own limit by signing out."""
    ratelimit.reset()
    s = _settings(auth=2)
    for _ in range(2):
        ratelimit.check("POST", "/api/auth/login", principal_id="usr_a",
                        client="1.2.3.4", settings=s)
    # Same address, different "principal" - still refused.
    assert ratelimit.check("POST", "/api/auth/login", principal_id="usr_b",
                           client="1.2.3.4", settings=s).allowed is False
    # A different address is a different attacker.
    assert ratelimit.check("POST", "/api/auth/login", principal_id=None,
                           client="5.6.7.8", settings=s).allowed is True


def test_the_buckets_do_not_share_an_allowance():
    """A number loose enough for reads is useless for spending."""
    ratelimit.reset()
    s = _settings(spend=1, write=10, read=10)
    assert ratelimit.check("POST", "/api/projects/p1/elements/generate",
                           principal_id="usr_a", client="1.2.3.4", settings=s).allowed is True
    assert ratelimit.check("POST", "/api/projects/p1/elements/generate",
                           principal_id="usr_a", client="1.2.3.4", settings=s).allowed is False
    # Spending is exhausted; reading and writing are not.
    assert ratelimit.check("GET", "/api/projects", principal_id="usr_a",
                           client="1.2.3.4", settings=s).allowed is True
    assert ratelimit.check("POST", "/api/projects", principal_id="usr_a",
                           client="1.2.3.4", settings=s).allowed is True


# ── the load test: driving a real route past its limit ───────────────────

def test_driving_a_real_route_past_its_limit_returns_429(client, monkeypatch):
    """End to end through the middleware, not the function in isolation."""
    from app.core import config

    alice = _register(client, ALICE)
    monkeypatch.setenv("RATE_LIMIT_WRITE_PER_WINDOW", "5")
    config.get_settings.cache_clear()
    ratelimit.reset()

    codes = [client.post("/api/projects", json={"name": f"p{i}"},
                         headers=alice).status_code for i in range(9)]
    assert codes[:5] == [200] * 5, codes
    assert codes[5:] == [429] * 4, codes

    last = client.post("/api/projects", json={"name": "over"}, headers=alice)
    assert last.status_code == 429
    assert last.headers["Retry-After"].isdigit()
    body = last.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True, "waiting IS the fix; say so"
    config.get_settings.cache_clear()


def test_a_refused_request_never_reaches_the_handler(client, monkeypatch):
    """A 429 that still did the work is not a limit."""
    from app.core import config
    from app.projects import get_project_store

    alice = _register(client, ALICE)
    monkeypatch.setenv("RATE_LIMIT_WRITE_PER_WINDOW", "2")
    config.get_settings.cache_clear()
    ratelimit.reset()

    for i in range(6):
        client.post("/api/projects", json={"name": f"p{i}"}, headers=alice)
    # Count only what this test asked for: the app seeds `proj_seed` at
    # startup, and counting the whole store would make the assertion about
    # ensure_seed rather than about the limiter.
    mine = [p for p in get_project_store().list() if p.name.startswith("p")]
    assert len(mine) == 2, f"requests past the limit still created projects: {[p.name for p in mine]}"
    config.get_settings.cache_clear()


def test_brute_forcing_a_password_is_cut_off(client, monkeypatch):
    """The reason the auth bucket exists."""
    from app.core import config

    _register(client, ALICE)
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_WINDOW", "4")
    config.get_settings.cache_clear()
    ratelimit.reset()

    codes = [client.post("/api/auth/login",
                         json={"email": ALICE[0], "password": f"guess-{i}-wrong"}).status_code
             for i in range(8)]
    assert codes.count(401) == 4, codes
    assert codes.count(429) == 4, codes
    config.get_settings.cache_clear()


# ── 2. limits are configurable ───────────────────────────────────────────

def test_a_bucket_set_to_zero_is_unlimited():
    """The documented rollback: "raise limits to effectively unlimited via
    configuration". It must work from the outside, not by editing code."""
    ratelimit.reset()
    s = _settings(write=0)
    assert all(ratelimit.check("POST", "/api/projects", principal_id="usr_a",
                               client="1.2.3.4", settings=s).allowed for _ in range(50))


def test_the_whole_limiter_can_be_switched_off():
    ratelimit.reset()
    s = _settings(enabled=False, write=1)
    assert all(ratelimit.check("POST", "/api/projects", principal_id="usr_a",
                               client="1.2.3.4", settings=s).allowed for _ in range(20))


def test_the_shipped_defaults_are_not_zero():
    """A default of 0 would ship the feature switched off while reading as
    switched on."""
    from app.core.config import get_settings

    s = get_settings()
    assert s.rate_limit_enabled is True
    for value in (s.rate_limit_auth_per_window, s.rate_limit_spend_per_window,
                  s.rate_limit_write_per_window, s.rate_limit_read_per_window):
        assert value > 0


# ── 3. normal use is unaffected ──────────────────────────────────────────

def test_a_realistic_studio_session_is_never_limited(client):
    """What opening the studio and making a project actually costs.

    If this ever fails, the limits are too tight - and the right response is to
    look at this test rather than to raise every number until it passes.
    """
    ratelimit.reset()
    alice = _register(client, ALICE)

    codes = []
    for _ in range(3):                                  # three page loads
        codes.append(client.get("/api/auth/session", headers=alice).status_code)
        codes.append(client.get("/api/projects", headers=alice).status_code)
        codes.append(client.get("/api/credits", headers=alice).status_code)
        codes.append(client.get("/api/catalog", headers=alice).status_code)
    pid = client.post("/api/projects", json={"name": "Sharma Residence"},
                      headers=alice).json()["project"]["project_id"]
    for _ in range(10):                                 # polling a job
        codes.append(client.get(f"/api/projects/{pid}/jobs", headers=alice).status_code)
        codes.append(client.get(f"/api/projects/{pid}/events", headers=alice).status_code)

    assert 429 not in codes, "normal use hit a rate limit"


def test_the_share_page_is_not_limited_out_of_existence(client):
    """A tour is one JSON read plus a burst of panorama and mesh fetches. The
    read bucket has to survive that or a shared link looks broken."""
    from app.projects.layout import ensure_layout, project_dir

    ratelimit.reset()
    alice = _register(client, ALICE)
    pid = client.post("/api/projects", json={"name": "s"}, headers=alice) \
                .json()["project"]["project_id"]
    ensure_layout(pid)
    web = project_dir(pid) / "outputs" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "tour.json").write_text('{"tour": {"nodes": []}}', encoding="utf-8")
    (web / "pano.jpg").write_bytes(b"x")
    token = client.post(f"/api/projects/{pid}/share", json={},
                        headers=alice).json()["data"]["token"]

    client.cookies.clear()
    codes = [client.get(f"/api/projects/{pid}/tour", params={"k": token}).status_code]
    codes += [client.get(f"/files/projects/{pid}/outputs/web/pano.jpg",
                         params={"k": token}).status_code for _ in range(40)]
    assert 429 not in codes, "a share link hit a rate limit while loading one tour"

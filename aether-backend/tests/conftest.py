from __future__ import annotations

import os

import pytest


def _reset_singletons() -> None:
    from app.core import config
    from app.assets import registry as areg
    from app.db import sqlite
    from app.jobs import runner as jrunner
    from app.jobs import store as jstore
    from app.materials import registry as mreg
    from app.projects import store as pstore
    from app.scene import store as sstore

    config.get_settings.cache_clear()
    jrunner.reset_runner()
    jstore.reset_job_store()
    pstore.reset_project_store()
    sqlite.reset_db()
    areg._registry = None
    mreg._registry = None
    sstore._store = None


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh data dir + reset every singleton. Blender stays unconfigured
    unless the test opts in via BLENDER_PATH from the environment."""
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path / "data"))
    # Keys are blanked for EVERY test by _no_real_keys below, not here. They
    # used to be blanked only in this fixture, which 547 of 728 test functions
    # never request - see the note on _no_real_keys.
    monkeypatch.setenv("INTELLIGENCE_PROVIDER", "auto")
    # No GPU work in the test suite. Left on, the analyze job loads Stable
    # Diffusion and renders for ~40 s per call — the run went from 25 s to
    # 339 s and blew wait_idle(30). Tests that want it opt in explicitly.
    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "false")
    monkeypatch.setenv("JOBS_RETRY_DELAY_SECONDS", "0.05")
    monkeypatch.setenv("JOBS_AI_WORKERS", "2")
    monkeypatch.setenv("JOBS_RENDER_WORKERS", "1")
    _reset_singletons()
    yield tmp_path
    _reset_singletons()


@pytest.fixture
def blender_path() -> str:
    path = os.environ.get("BLENDER_PATH", "")
    if not path or not os.path.exists(path):
        pytest.skip("BLENDER_PATH not set; skipping Blender test")
    return path


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with an empty rate-limit window.

    P0-SEC-006 keys the `auth` bucket on the client address, and every test
    that signs in shares one address ("testclient"). Ten registrations into a
    suite of a thousand, the eleventh would 429 - and the failure would look
    like an auth bug in whichever test happened to be eleventh.

    This does NOT weaken the limiter: it is exercised deliberately in
    tests/test_rate_limiting.py, which drives past each bucket on purpose.
    """
    from app.core import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """No test may reach a real provider by accident. Every test, not some.

    Settings read `.env`, so a developer's real GEMINI_API_KEY is visible to
    the suite unless something blanks it. That blanking used to live in the
    `env` fixture - which 547 of the 728 test functions never request. The
    suite was therefore only accidentally offline: nothing structural stopped a
    test from constructing a live GeminiProvider and spending real credits.

    A test that genuinely wants a key sets it in its own body, which runs after
    this fixture and so still wins. That makes reaching a real provider a
    deliberate, visible act - which is the whole point of the MOCK /
    REAL-PROVIDER test split.
    """
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MESHY_API_KEY"):
        monkeypatch.setenv(key, "")
    from app.core import config

    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_intelligence():
    from app.intelligence import reset_provider

    reset_provider()
    yield
    reset_provider()


#: The account every product-behaviour suite runs as.
ADMIN_EMAIL = "test-admin@example.com"
ADMIN_PASSWORD = "test-admin-password"


def sign_in_admin(c):
    """Give a TestClient a signed-in administrator, and return it.

    P0-SEC-002 made the API deny-by-default, so a client that never signs in is
    no longer a valid caller. These suites test the PRODUCT, not the gate, so
    they authenticate once and keep every assertion they already had.

    Administrator specifically, because its visibility matches the pre-auth
    behaviour these suites were written against - a homeowner would change what
    `GET /api/projects` returns and quietly alter tests that are not about
    authorization at all.

    The gate itself is tested in tests/test_authz_matrix.py, whose client is
    deliberately anonymous, and in tests/test_auth_identity.py.
    """
    r = c.post("/api/auth/register", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code == 409:  # already registered in this database
        r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"test admin sign-in failed: {r.text}"
    c.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]
    return c

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
def _reset_intelligence():
    from app.intelligence import reset_provider

    reset_provider()
    yield
    reset_provider()

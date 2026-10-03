"""P1-BLENDER-002: the `viewpoints` job renders N cameras from the ALREADY
BUILT scene.blend, without rebuilding it, on the render lane.

Real Blender (marker `blender`). Skipped unless BLENDER_PATH is set.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.jobs.registry import get_spec
from app.jobs.schema import JobLane
from app.projects.layout import project_dir
from tests.conftest import sign_in_admin
from tests.test_blender_build import BRIEF


def test_viewpoints_is_registered_on_the_render_lane():
    spec = get_spec("viewpoints")
    assert spec.lane == JobLane.render


@pytest.mark.blender
def test_viewpoints_renders_without_rebuilding(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app

    with TestClient(app) as client:
        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "Viewpoints test"}).json()["project"]["project_id"]
        img = tmp_path / "ref.png"
        Image.new("RGB", (32, 32), (180, 150, 120)).save(img)
        client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF},
                    files=[("references", ("ref.png", img.read_bytes(), "image/png"))])
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(30)
        client.post(f"/api/projects/{pid}/scene-plan", json={})
        assert get_runner().wait_idle(60)
        r = client.post(f"/api/projects/{pid}/build", json={"preview": False})
        assert r.status_code == 200, r.text
        assert get_runner().wait_idle(600)

        root = project_dir(pid)
        blend = root / "blender" / "scene.blend"
        assert blend.exists()
        blend_mtime_before = blend.stat().st_mtime

        views = [
            {"name": "corner_0", "position": [3.0, 1.55, -3.0], "look_at": [0.0, 1.1, 0.0]},
            {"name": "corner_1", "position": [-3.0, 1.55, -3.0], "look_at": [0.0, 1.1, 0.0]},
        ]
        job = get_runner().enqueue(pid, "viewpoints", {"views": views, "profile": "preview"})
        assert get_runner().wait_idle(300)
        polled = client.get(f"/api/jobs/{job.job_id}").json()["data"]["job"]
        assert polled["status"] == "SUCCEEDED", polled["error"]

        # NOT rebuilt: same .blend file, untouched.
        assert blend.stat().st_mtime == blend_mtime_before

        result = polled["result"]
        assert result["count"] == 2
        assert result["device"]
        for r_ in result["rendered"]:
            assert r_["url"].startswith("/files/projects/")

        manifest_path = root / "renders" / "viewpoints" / "default" / "manifest.json"
        assert manifest_path.exists()
        for view in views:
            png = root / "renders" / "viewpoints" / "default" / f"{view['name']}.png"
            assert png.exists() and png.stat().st_size > 1000

        detail = client.get(f"/api/projects/{pid}").json()["data"]
        kinds = {o["kind"] for o in detail["outputs"]}
        assert "viewpoints" in kinds


@pytest.mark.blender
def test_viewpoints_requires_a_build_first(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app

    with TestClient(app) as client:
        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "No build"}).json()["project"]["project_id"]
        job = get_runner().enqueue(pid, "viewpoints", {"views": [{"name": "a", "position": [0, 1.5, 0], "look_at": [1, 1, 1]}]})
        assert get_runner().wait_idle(30)
        polled = client.get(f"/api/jobs/{job.job_id}").json()["data"]["job"]
        assert polled["status"] == "FAILED"
        assert "build" in polled["error"].lower()


@pytest.mark.blender
def test_viewpoints_requires_views(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app

    with TestClient(app) as client:
        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "No views"}).json()["project"]["project_id"]
        job = get_runner().enqueue(pid, "viewpoints", {"views": []})
        assert get_runner().wait_idle(30)
        polled = client.get(f"/api/jobs/{job.job_id}").json()["data"]["job"]
        assert polled["status"] == "FAILED"
        assert "viewpoint" in polled["error"].lower()

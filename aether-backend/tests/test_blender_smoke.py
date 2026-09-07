"""Real Blender run. Skipped unless BLENDER_PATH points at an executable."""
from __future__ import annotations

import pytest

from app.blender import BlenderRunner


@pytest.mark.blender
def test_headless_smoke_render(env, blender_path, tmp_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    runner = BlenderRunner()
    assert runner.configured
    out = tmp_path / "smoke.png"
    res = runner.smoke(out, engine="BLENDER_EEVEE", samples=4, size=(320, 180), log_path=tmp_path / "smoke.log")
    assert out.exists() and out.stat().st_size > 1000
    assert res.result["ok"] is True
    assert res.result["engine"] == "BLENDER_EEVEE"
    assert "ALLURE_RESULT" in (tmp_path / "smoke.log").read_text(encoding="utf-8")


@pytest.mark.blender
def test_smoke_job_through_runner(env, blender_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import JobRunner, JobStatus, get_job_store
    from app.projects import get_project_store
    from app.projects.layout import project_dir

    project = get_project_store().create(name="Smoke")
    runner = JobRunner()
    job = runner.enqueue(project.project_id, "blender_smoke", {"engine": "BLENDER_EEVEE", "samples": 4})
    assert runner.wait_idle(120)
    done = get_job_store().get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED, done.error
    assert (project_dir(project.project_id) / "previews" / "smoke_blender_eevee.png").exists()
    assert done.result["image"].startswith("/files/projects/")
    assert get_project_store().list_outputs(project.project_id)[0]["kind"] == "smoke_render"
    runner.shutdown()

"""Project + inputs + jobs routes through the FastAPI app."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from app.projects.layout import project_dir


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _png_bytes() -> bytes:
    # 1x1 PNG
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da6364f8cfc00000030101"
        "00a24ba33f0000000049454e44ae426082"
    )


def test_create_project_and_layout(client):
    r = client.post("/api/projects", json={"name": "Sea view flat", "description": "Warm modern"})
    assert r.status_code == 200, r.text
    project = r.json()["project"]
    assert project["stage"] == "CREATED"
    root = project_dir(project["project_id"])
    for sub in ["input/references", "analysis", "planning", "blender", "previews", "renders", "outputs/web", "logs"]:
        assert (root / sub).is_dir(), sub
    assert (root / "input" / "description.txt").read_text(encoding="utf-8").strip() == "Warm modern"

    listed = client.get("/api/projects").json()["data"]
    assert any(p["project_id"] == project["project_id"] for p in listed)
    # seed project migrated/created too
    assert any(p["project_id"] == "proj_seed" for p in listed)


def test_upload_inputs_moves_stage(client):
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    dims = json.dumps([{"name": "Living", "type": "living_room", "width_m": 5.2, "length_m": 4.8, "estimated": False}])
    files = [
        ("references", ("living.png", io.BytesIO(_png_bytes()), "image/png")),
        ("references", ("notes.txt", io.BytesIO(b"hello"), "text/plain")),
    ]
    r = client.post(
        f"/api/projects/{pid}/inputs",
        data={"description": "Two bedroom, warm minimal, lots of wood", "dimensions": dims},
        files=files,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["stage"] == "INPUT_RECEIVED"
    kinds = sorted(i["kind"] for i in body["inputs"])
    assert kinds == ["description", "dimensions", "reference"]
    assert body["rejected"][0]["filename"] == "notes.txt"
    assert body["project"]["room_hints"][0]["width_m"] == 5.2

    root = project_dir(pid)
    assert (root / "input" / "references" / "ref_01.png").exists()
    assert (root / "input" / "dimensions.json").exists()

    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["checkpoints"]["inputs"] is True
    assert detail["checkpoints"]["analysis"] is False
    assert len(detail["inputs"]) == 3

    # file served through the static mount
    served = client.get(f"/files/projects/{pid}/input/references/ref_01.png")
    assert served.status_code == 200


def test_enqueue_job_and_poll(client):
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    r = client.post(f"/api/projects/{pid}/jobs", json={"type": "noop", "params": {"steps": 1, "sleep": 0}})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["status"] in ("QUEUED", "RUNNING", "SUCCEEDED")

    from app.jobs import get_runner

    assert get_runner().wait_idle(10)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]
    assert polled["job"]["status"] == "SUCCEEDED"
    assert any(e["status"] == "succeeded" for e in polled["events"])

    feed = client.get(f"/api/projects/{pid}/events").json()["data"]
    assert feed["last_id"] > 0
    again = client.get(f"/api/projects/{pid}/events", params={"after": feed["last_id"]}).json()["data"]
    assert again["events"] == []

    types = client.get("/api/jobs/types").json()["data"]
    assert {t["type"] for t in types} >= {"noop", "blender_smoke"}


def test_errors_use_envelope(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    r = client.post(f"/api/projects/{pid}/jobs", json={"type": "does_not_exist"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_JOB_TYPE"
    r = client.get("/api/jobs/job_missing")
    assert r.status_code == 404


def test_scene_create_attaches_to_sqlite_project(client):
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    r = client.post("/api/scenes", json={"project_id": pid, "name": "Draft"})
    assert r.status_code == 200, r.text
    scene_id = r.json()["scene"]["scene_id"]
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert scene_id in detail["project"]["scene_ids"]


def test_blender_smoke_without_blender_fails_cleanly(client, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", "")
    from app.core import config

    config.get_settings.cache_clear()
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    job = client.post(f"/api/projects/{pid}/jobs", json={"type": "blender_smoke"}).json()["job"]
    from app.jobs import get_runner

    assert get_runner().wait_idle(15)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
    assert polled["status"] == "FAILED"
    assert "BLENDER_PATH" in polled["error"]

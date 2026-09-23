"""Project + inputs + jobs routes through the FastAPI app."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin

from app.projects.layout import project_dir


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


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


# ── vertical + scope guard ──────────────────────────────────────────────


def test_vertical_defaults_to_residential_and_round_trips(client):
    default = client.post("/api/projects", json={"name": "Flat"}).json()["project"]
    assert default["vertical"] == "residential"

    r = client.post("/api/projects", json={"name": "Boutique hotel", "vertical": "hospitality"})
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["project_id"]
    assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["vertical"] == "hospitality"
    listed = {p["project_id"]: p["vertical"] for p in client.get("/api/projects").json()["data"]}
    assert listed[pid] == "hospitality"


def test_unknown_vertical_is_rejected(client):
    for bad in ("factory", "manufacturing", "nonsense"):
        r = client.post("/api/projects", json={"name": "Nope", "vertical": bad})
        assert r.status_code == 422, f"{bad} -> {r.status_code}"


def test_vertical_editable_only_while_created(client):
    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    r = client.patch(f"/api/projects/{pid}", json={"vertical": "industrial"})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["vertical"] == "industrial"

    # a name-only patch must still work once the project has moved on
    from app.projects import ProjectStage, get_project_store

    get_project_store().set_stage(pid, ProjectStage.INPUT_RECEIVED)
    assert client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}).status_code == 200
    # re-sending the unchanged vertical is a no-op, not a conflict
    assert client.patch(f"/api/projects/{pid}", json={"vertical": "industrial"}).status_code == 200

    r = client.patch(f"/api/projects/{pid}", json={"vertical": "residential"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "VERTICAL_LOCKED"
    assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["vertical"] == "industrial"


OUT_OF_SCOPE_BRIEFS = [
    "Design the layout of our manufacturing plant in Pune",
    "We need the factory floor re-planned around the new line",
    "Check the load bearing capacity of the mezzanine",
    "Is this a load-bearing wall we can remove?",
    "Specify machine guarding for the press area",
    "Make sure the exits meet the fire code",
    "Compliance with the Factories Act, 1948 is required",
    "Needs to satisfy the OSH Code",
    "Calculate the structural load of the new partition",
]

IN_SCOPE_BRIEFS = [
    "Industrial loft with exposed brick and black steel",
    "A warehouse aesthetic for the living room, lots of wood",
    "Industrial-style cafe, concrete floors, pendant lighting",
    "Warm minimal two-bedroom flat",
]


def test_scope_guard_refuses_facility_briefs(client):
    for brief in OUT_OF_SCOPE_BRIEFS:
        r = client.post("/api/projects", json={"name": "Plant", "description": brief})
        assert r.status_code == 422, f"{brief!r} -> {r.status_code}"
        assert r.json()["error"]["code"] == "OUT_OF_SCOPE"
    # nothing was created for any of them
    assert [p for p in client.get("/api/projects").json()["data"] if p["name"] == "Plant"] == []

    pid = client.post("/api/projects", json={"name": "Flat"}).json()["project"]["project_id"]
    for brief in OUT_OF_SCOPE_BRIEFS:
        assert client.patch(f"/api/projects/{pid}", json={"description": brief}).status_code == 422
        r = client.post(f"/api/projects/{pid}/inputs", data={"description": brief})
        assert r.status_code == 422, f"{brief!r} -> {r.status_code}"
        assert r.json()["error"]["code"] == "OUT_OF_SCOPE"
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["inputs"] == [] and detail["project"]["description"] == ""


def test_scope_guard_passes_aesthetic_briefs(client):
    for brief in IN_SCOPE_BRIEFS:
        r = client.post("/api/projects", json={"name": "Flat", "description": brief})
        assert r.status_code == 200, f"{brief!r} -> {r.text}"
        pid = r.json()["project"]["project_id"]
        assert client.patch(f"/api/projects/{pid}", json={"description": brief}).status_code == 200
        inputs = client.post(f"/api/projects/{pid}/inputs", data={"description": brief})
        assert inputs.status_code == 200, f"{brief!r} -> {inputs.text}"
        assert project_dir(pid).joinpath("input", "description.txt").read_text(
            encoding="utf-8"
        ).strip() == brief


# ── schema migration ────────────────────────────────────────────────────

# The v1 projects DDL, i.e. an existing allure.db that predates `vertical`.
V1_PROJECTS_DDL = """
    CREATE TABLE projects (
        project_id  TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        stage       TEXT NOT NULL DEFAULT 'CREATED',
        scene_ids   TEXT NOT NULL DEFAULT '[]',
        room_hints  TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )"""


def test_migration_adds_vertical_to_an_existing_db(tmp_path):
    import sqlite3

    from app.db.sqlite import SCHEMA_VERSION, Database

    path = tmp_path / "allure.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    legacy.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    legacy.execute(V1_PROJECTS_DDL)
    legacy.execute(
        "INSERT INTO projects(project_id, name, created_at, updated_at) VALUES (?,?,?,?)",
        ("proj_old", "Pre-migration flat", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    for _ in range(2):  # running it twice must be a no-op the second time
        db = Database(path)
        assert db.scalar("SELECT vertical FROM projects WHERE project_id = 'proj_old'") == "residential"
        assert db.scalar("SELECT value FROM meta WHERE key = 'schema_version'") == str(SCHEMA_VERSION)
        assert [r["name"] for r in db.query("PRAGMA table_info(projects)")].count("vertical") == 1
        db.close()


def test_fresh_db_has_vertical_and_reads_back(tmp_path):
    from app.db.sqlite import Database
    from app.projects.store import _row_to_project

    db = Database(tmp_path / "fresh.db")
    db.execute(
        """INSERT INTO projects(project_id, name, created_at, updated_at)
           VALUES ('proj_new', 'Fresh', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"""
    )
    row = db.one("SELECT * FROM projects WHERE project_id = 'proj_new'")
    assert _row_to_project(row).vertical.value == "residential"
    db.close()

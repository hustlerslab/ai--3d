"""Deleting a project keeps the expensive half."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.main import app
from app.projects.layout import project_dir


def _project_with_work(client: TestClient) -> tuple[str, Path]:
    pid = client.post("/api/projects", json={"name": "Doomed", "description": "2BHK"}) \
        .json()["project"]["project_id"]
    root = project_dir(pid)
    (root / "analysis").mkdir(parents=True, exist_ok=True)
    for name in ("living_room", "kitchen"):
        Image.new("RGB", (64, 48)).save(root / "analysis" / f"moodboard_room_{name}.png")
    Image.new("RGB", (96, 72)).save(root / "analysis" / "moodboard_scene.png")
    crops = root / "planning" / "scene_crops" / "living_room"
    crops.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32)).save(crops / "00_sofa.png")
    refs = root / "input" / "references"
    refs.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 96)).save(refs / "ref_01.jpeg")
    return pid, root


def test_delete_removes_the_project_but_archives_what_it_produced(env):
    """The moodboard is the brief the client approved and the meshes cost 30
    credits each. Losing those with the project would make deleting a tidy-up
    that quietly throws away an afternoon of generation."""
    client = TestClient(app)
    pid, root = _project_with_work(client)
    assert root.is_dir()

    body = client.delete(f"/api/projects/{pid}").json()["data"]
    assert body["deleted"] == pid
    assert body["kept"]["moodboard_rooms"] == 3     # two rooms + the whole scene
    assert body["kept"]["scene_crops"] == 1
    assert body["kept"]["references"] == 1

    assert not root.exists(), "the project folder should be gone"
    archive = get_settings().data_dir / "archive" / pid
    assert (archive / "manifest.json").is_file()
    assert sorted(p.name for p in (archive / "moodboard").glob("*.png")) == [
        "moodboard_room_kitchen.png", "moodboard_room_living_room.png",
        "moodboard_scene.png"]
    assert (archive / "scene_crops" / "living_room" / "00_sofa.png").is_file()
    # The uploads are the user's own photographs: nothing can regenerate them,
    # so a delete that fails to keep them destroys something unrecoverable.
    assert (archive / "references" / "ref_01.jpeg").is_file()


def test_deleting_it_twice_is_a_404_not_a_second_success(env):
    client = TestClient(app)
    pid, _ = _project_with_work(client)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.delete(f"/api/projects/{pid}").status_code == 404


def test_a_deleted_project_is_gone_from_the_list_and_its_rows(env):
    client = TestClient(app)
    pid, _ = _project_with_work(client)
    client.delete(f"/api/projects/{pid}")
    assert pid not in client.get("/api/projects").text
    assert client.get(f"/api/projects/{pid}").status_code == 404

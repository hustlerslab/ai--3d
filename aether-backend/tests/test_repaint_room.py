"""One room redrawn, on a new seed, without disturbing the rest of the board.

Seed variance is the reason this exists, not a prompt defect: the same bathroom
prompt — already naming vanity, basin, mirror, toilet and walk-in shower —
gives a complete room on two of six seeds and a bathtub in an alcove on others.
ADR-002 §1 names the human review step as the backstop for exactly this, and
this is that backstop made real.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin
from PIL import Image

from app.intelligence.schema import MoodboardSpec
from app.projects.layout import project_dir
from app.providers import local_image


@pytest.fixture
def studio(env, monkeypatch):
    """A project with a finished moodboard, and a stubbed GPU."""
    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "true")
    monkeypatch.setenv("INTELLIGENCE_PROVIDER", "mock")
    from app.core import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(local_image, "available", lambda: True)
    monkeypatch.setattr(local_image, "unload", lambda: None)
    seeds: list[int] = []

    def fake_generate(prompt, **kw):
        seeds.append(kw.get("seed"))
        return local_image.GeneratedImage(
            data=b"\x89PNG\r\n\x1a\n" + bytes([len(seeds) % 251]) * 64,
            mime_type="image/png", model="sd15")

    monkeypatch.setattr(local_image, "generate", fake_generate)

    from app.jobs import get_runner
    from app.main import app

    with TestClient(app) as client:

        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "repaint"}).json()["project"]["project_id"]
        img = project_dir(pid) / "ref.png"
        Image.new("RGB", (32, 32), (90, 120, 160)).save(img)
        client.post(f"/api/projects/{pid}/inputs",
                    data={"description": "A calm 2BHK: living room, bedroom, kitchen and bathroom."},
                    files=[("references", ("ref.png", img.read_bytes(), "image/png"))])
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(60)
        yield client, pid, seeds


def _board(pid: str) -> MoodboardSpec:
    return MoodboardSpec.model_validate(
        json.loads((project_dir(pid) / "analysis/moodboard_spec.json").read_text(encoding="utf-8")))


def test_every_room_records_the_seed_it_was_drawn_from(studio):
    _, pid, _ = studio
    board = _board(pid)
    assert board.room_scenes
    for scene in board.room_scenes:
        assert scene.seed > 0, f"{scene.room_id} has no recorded seed"


def test_repaint_redraws_one_room_on_a_new_seed_and_leaves_the_others(studio):
    client, pid, _ = studio
    from app.jobs import get_runner

    before = _board(pid)
    target = before.room_scenes[0]
    others = {s.room_id: s.seed for s in before.room_scenes[1:]}

    r = client.post(f"/api/projects/{pid}/moodboard/rooms/{target.room_id}/repaint")
    assert r.status_code == 200, r.text
    assert get_runner().wait_idle(60)

    after = _board(pid)
    redrawn = next(s for s in after.room_scenes if s.room_id == target.room_id)
    assert redrawn.seed != target.seed, "a repaint must be a different draw, not the same one again"
    assert redrawn.seed > 0
    # the rest of the board is untouched
    assert {s.room_id: s.seed for s in after.room_scenes if s.room_id != target.room_id} == others
    assert len(after.room_scenes) == len(before.room_scenes)


def test_repaint_runs_on_the_render_lane(studio):
    """It drives the local GPU, so it belongs behind the single-worker mutex
    whatever the intelligence provider is."""
    client, pid, _ = studio
    room = _board(pid).room_scenes[0].room_id
    job = client.post(f"/api/projects/{pid}/moodboard/rooms/{room}/repaint").json()["job"]
    assert job["lane"] == "render"


def test_an_unknown_room_is_refused_with_the_rooms_that_do_exist(studio):
    client, pid, _ = studio
    r = client.post(f"/api/projects/{pid}/moodboard/rooms/conservatory/repaint")
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "ROOM_NOT_FOUND"
    assert "Rooms:" in body["message"], body["message"]


def test_repaint_before_any_analysis_is_refused(env):
    from app.main import app

    with TestClient(app) as client:

        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "empty"}).json()["project"]["project_id"]
        r = client.post(f"/api/projects/{pid}/moodboard/rooms/living_room/repaint")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ANALYSIS_NOT_READY"

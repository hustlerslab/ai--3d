"""M6: panorama node planning and the preview tour job (Blender marker)."""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.walkthrough.tour_nodes import plan_nodes, yaw_from
from tests.test_blender_build import BRIEF, _compiled_scene


def test_yaw_from_matches_scene_convention():
    # forward −Z → yaw 0; forward −X → yaw +π/2 (same as the spatial planner)
    assert yaw_from((0, 1.6, 0), (0, 1.6, -3)) == pytest.approx(0.0)
    assert yaw_from((0, 1.6, 0), (-3, 1.6, 0)) == pytest.approx(math.pi / 2)


def test_nodes_one_per_room_with_links(env):
    scene = _compiled_scene()
    nodes, route = plan_nodes(scene)
    rooms = {n.room_id for n in nodes}
    assert rooms == {r.room_id for r in scene.rooms}
    assert route == [n.id for n in nodes]
    assert len(nodes) >= len(scene.rooms)          # large living room gets a second vantage
    living = [n for n in nodes if n.room_id == "living_room"]
    assert len(living) == 2
    for n in nodes:
        assert n.links, n.id
        assert all(l != n.id and any(m.id == l for m in nodes) for l in n.links)
        assert n.position[1] == pytest.approx(1.6)


@pytest.mark.blender
def test_preview_job_renders_panoramas_and_tour(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app
    from app.projects.layout import project_dir

    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Tour test"}).json()["project"]["project_id"]
        img = tmp_path / "ref.png"
        Image.new("RGB", (32, 32), (180, 150, 120)).save(img)
        client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF},
                    files=[("references", ("ref.png", img.read_bytes(), "image/png"))])
        r = client.post(f"/api/projects/{pid}/preview", json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SCENE_REQUIRED"
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(30)
        client.post(f"/api/projects/{pid}/scene-plan", json={})
        assert get_runner().wait_idle(60)
        r = client.post(f"/api/projects/{pid}/preview", json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "BUILD_REQUIRED"
        client.post(f"/api/projects/{pid}/build", json={"preview": False})
        assert get_runner().wait_idle(600)

        r = client.post(f"/api/projects/{pid}/preview", json={"profile": "pano_test"})
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        assert get_runner().wait_idle(900)
        polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
        assert polled["status"] == "SUCCEEDED", polled["error"]
        assert polled["result"]["nodes"] >= 4

        tour = client.get(f"/api/projects/{pid}/tour").json()["data"]
        assert tour["quality"] == "preview" and tour["tour"]["route"]
        node = tour["tour"]["nodes"][0]
        assert node["pano_url"].startswith("/files/projects/")
        served = client.get(node["pano_url"])
        assert served.status_code == 200 and served.headers["content-type"].startswith("image/jpeg")
        root = project_dir(pid)
        with Image.open(root / "outputs" / "web" / "panos" / "preview" / f"{node['id']}.jpg") as im:
            assert im.size == (256, 128)
        assert (root / "blender" / "camera_path.json").exists()
        assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["stage"] == "PREVIEW_RENDERING"

        # second run skips everything
        job2 = client.post(f"/api/projects/{pid}/preview", json={"profile": "pano_test"}).json()["job"]
        assert get_runner().wait_idle(120)
        events = client.get(f"/api/jobs/{job2['job_id']}").json()["data"]["events"]
        assert sum("skipped" in e["message"] for e in events) == 2


@pytest.mark.blender
def test_film_job_renders_mp4(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app
    from app.projects.layout import project_dir

    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Film test"}).json()["project"]["project_id"]
        client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF})
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(30)
        client.post(f"/api/projects/{pid}/scene-plan", json={})
        assert get_runner().wait_idle(60)
        client.post(f"/api/projects/{pid}/build", json={"preview": False})
        assert get_runner().wait_idle(600)
        r = client.post(f"/api/projects/{pid}/film", json={"profile": "test"})
        assert r.status_code == 200, r.text
        assert get_runner().wait_idle(900)
        job = client.get(f"/api/jobs/{r.json()['job']['job_id']}").json()["data"]["job"]
        assert job["status"] == "SUCCEEDED", job["error"]
        mp4 = project_dir(pid) / "renders" / "walkthrough_test.mp4"
        assert mp4.exists() and mp4.stat().st_size > 5_000
        assert job["result"]["frames"] > 20
        assert client.get(job["result"]["film"]).status_code == 200

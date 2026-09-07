"""M4: manifest conversion (no Blender) and the real Blender build (marker)."""
from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.blender.manifest import (
    blender_forward,
    build_manifest,
    scene_forward,
    to_blender_xyz,
    yaw_to_blender_rz,
)
from app.intelligence import InputBundle
from app.intelligence.mock_provider import MockProvider
from app.planning import compile_scene, place_objects, resolve_plan
from app.projects.layout import project_dir

BRIEF = "2BHK in Pune. Warm modern minimal with oak floors, a big sofa, a dining table for six and plants."


def _compiled_scene(project_id="proj_x"):
    bundle = InputBundle(project_id=project_id, description=BRIEF)
    mock = MockProvider()
    analysis = mock.analyze_input(bundle)
    style = mock.create_style_spec(analysis, bundle)
    scene, _ = compile_scene(project_id, analysis, style, name="test")
    plan = mock.plan_objects(analysis, style, bundle)
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))
    scene.objects = [op.object for op in ops]
    return scene


def test_axis_conversion_and_yaw_round_trip():
    assert to_blender_xyz((1.0, 2.0, 3.0)) == [1.0, -3.0, 2.0]
    for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 3, 2.1):
        fx, fz = scene_forward(yaw)
        bx, by = blender_forward(yaw_to_blender_rz(yaw))
        # scene (x, z) forward must equal blender (x, -y) forward
        assert abs(fx - bx) < 1e-5 and abs(fz - (-by)) < 1e-5, yaw


def test_manifest_shape(env, tmp_path):
    scene = _compiled_scene()
    manifest = build_manifest(scene, project_id="proj_x", project_root=tmp_path, preview=True)
    assert manifest["up_axis"] == "Z" and manifest["units"] == "meters"
    assert len(manifest["rooms"]) == len(scene.rooms)
    assert len(manifest["walls"]) == len(scene.walls)
    assert len(manifest["objects"]) == len(scene.objects)
    obj = manifest["objects"][0]
    src = scene.objects[0]
    assert obj["location"] == to_blender_xyz(src.position)
    assert obj["dimensions"] == [src.dimensions[0], src.dimensions[2], src.dimensions[1]]
    assert obj["asset"]["kind"] in ("glb", "procedural")
    assert all(k in manifest["materials"] for k in {r.floor_material for r in scene.rooms})
    assert 1.2 < manifest["camera"]["preview_shot"]["position"][2] < 1.8
    assert manifest["camera"]["keyframes"]
    assert manifest["output"]["blend"].endswith("scene.blend")
    openings = sum(len(w["openings"]) for w in manifest["walls"])
    assert openings == len(scene.openings)
    json.dumps(manifest)  # serialisable


@pytest.mark.blender
def test_build_job_end_to_end(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app

    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Build test"}).json()["project"]["project_id"]
        img = tmp_path / "ref.png"
        Image.new("RGB", (32, 32), (180, 150, 120)).save(img)
        client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF},
                    files=[("references", ("ref.png", img.read_bytes(), "image/png"))])
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(30)
        client.post(f"/api/projects/{pid}/scene-plan", json={})
        assert get_runner().wait_idle(60)

        r = client.post(f"/api/projects/{pid}/build", json={"preview": True})
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        assert get_runner().wait_idle(600)
        polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
        assert polled["status"] == "SUCCEEDED", polled["error"]
        result = polled["result"]
        assert result["validation_ok"], result["errors"]
        assert result["counts"]["objects"] >= 12
        assert result["counts"]["rooms"] == 4

        root = project_dir(pid)
        assert (root / "blender" / "scene.blend").stat().st_size > 100_000
        assert (root / "blender" / "validation_report.json").exists()
        preview = root / "previews" / "build_preview.png"
        assert preview.exists() and preview.stat().st_size > 10_000
        with Image.open(preview) as im:
            assert im.size == (960, 540)

        detail = client.get(f"/api/projects/{pid}").json()["data"]
        assert detail["project"]["stage"] == "SCENE_VALIDATING"
        kinds = {o["kind"] for o in detail["outputs"]}
        assert {"scene_blend", "validation_report", "build_preview"} <= kinds
        build = client.get(f"/api/projects/{pid}/build").json()["data"]
        assert build["report"]["ok"] and build["files"]["preview"].startswith("/files/projects/")
        served = client.get(build["files"]["preview"])
        assert served.status_code == 200

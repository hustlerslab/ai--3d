"""P1-VALIDATOR-001: `app/verification/render_verifier.py` and the `verify`
job it backs.

`test_verify_scene_pure_function` exercises `verify_scene()` directly (fast,
MOCK class) against a small hand-built Scene, so the check logic itself is
tested without paying for Blender. `test_verify_job_end_to_end` is the real
promotion proof: analyze -> scene-plan -> build -> verify against a real
built scene with real Blender renders and real ray-cast visibility.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.scene.schema import Room, Scene, SceneObject
from app.verification.render_verifier import CHECK_NAMES, DETERMINISTIC_CHECKS, MODEL_CHECKS, verify_scene
from tests.conftest import sign_in_admin
from tests.test_blender_build import BRIEF


def _tiny_scene() -> Scene:
    room = Room(name="living_room", type="living_room", boundary=[(0, 0), (4, 0), (4, 4), (0, 4)])
    obj = SceneObject(
        semantic_type="sofa", asset_id="asset_1", room_id=room.room_id,
        position=(2.0, 0.0, 2.0), rotation_y=0.0, scale=(1, 1, 1), dimensions=(2.0, 0.8, 0.9),
        mount="floor",
    )
    return Scene(project_id="proj_x", rooms=[room], objects=[obj])


def test_check_names_match_design_doc_split():
    assert len(CHECK_NAMES) == 13
    assert len(DETERMINISTIC_CHECKS) == 11
    assert MODEL_CHECKS == ("major_materials_match", "major_colours_match")


def test_model_checks_are_always_unknown_never_a_pass():
    scene = _tiny_scene()
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[])
    for obj in evidence.per_object:
        assert obj.checks["major_materials_match"] == "unknown"
        assert obj.checks["major_colours_match"] == "unknown"


def test_a_check_that_could_not_run_is_unknown_not_a_pass():
    """No build report, no visibility data, no object plan: nothing to grade
    most checks against. `unknown`, never invented as `pass`."""
    scene = _tiny_scene()
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[])
    obj = evidence.per_object[0]
    assert obj.checks["major_objects_visible"] == "unknown"
    assert obj.checks["approximate_location"] == "unknown"
    assert obj.checks["orientation"] == "unknown"
    assert obj.checks["circulation"] == "unknown"
    assert evidence.ok  # no FAIL anywhere - only unknowns - is not a failure


def test_missing_geometry_fails_expected_objects_exist():
    scene = _tiny_scene()
    build_report = {"ok": False, "errors": [f"{scene.objects[0].object_id} (sofa): no geometry"], "warnings": []}
    evidence = verify_scene(scene, build_report=build_report, visibility_detail=[], render_ids=[])
    assert evidence.scene_checks["expected_objects_exist"] == "fail"
    assert not evidence.ok


def test_visible_object_passes_visibility_check():
    scene = _tiny_scene()
    oid = scene.objects[0].object_id
    detail = [{"name": oid, "in_frame": 2, "visible": 1, "views": ["corner_0"]}]
    evidence = verify_scene(scene, build_report={}, visibility_detail=detail, render_ids=["corner_0"])
    assert evidence.per_object[0].visibility == "visible"
    assert evidence.per_object[0].checks["major_objects_visible"] == "pass"
    assert evidence.summary["coverage"] == 1.0


def test_never_in_frame_object_fails_visibility_check():
    scene = _tiny_scene()
    oid = scene.objects[0].object_id
    detail = [{"name": oid, "in_frame": 0, "visible": 0, "views": []}]
    evidence = verify_scene(scene, build_report={}, visibility_detail=detail, render_ids=["corner_0"])
    assert evidence.per_object[0].visibility == "never_in_frame"
    assert evidence.per_object[0].checks["major_objects_visible"] == "fail"
    assert not evidence.ok


def test_floating_object_fails_floating_check():
    scene = _tiny_scene()
    scene.objects[0].position = (2.0, 0.5, 2.0)  # floor-mounted but hovering 0.5m up
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[])
    assert evidence.per_object[0].checks["floating_objects"] == "fail"
    assert not evidence.ok


# ─── real pipeline, real Blender ───────────────────────────────────────────


@pytest.mark.blender
def test_verify_job_end_to_end(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner
    from app.main import app
    from app.projects.layout import project_dir

    with TestClient(app) as client:
        sign_in_admin(client)
        pid = client.post("/api/projects", json={"name": "Verify test"}).json()["project"]["project_id"]
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

        job = get_runner().enqueue(pid, "verify", {})
        assert get_runner().wait_idle(300)
        polled = client.get(f"/api/jobs/{job.job_id}").json()["data"]["job"]
        assert polled["status"] == "SUCCEEDED", polled["error"]

        result = polled["result"]
        assert result["summary"]["object_count"] >= 12
        # Real ray-cast visibility on a real built scene, same method
        # research/placement_loop.py measured coverage 100% with.
        assert result["summary"]["coverage"] is not None
        assert result["summary"]["coverage"] > 0.5

        root = project_dir(pid)
        evidence_path = root / "planning" / "render_verification.json"
        assert evidence_path.exists()
        import json

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert len(evidence["per_object"]) >= 12
        assert evidence["render_ids"]
        for obj in evidence["per_object"]:
            assert set(obj["checks"]) == set(CHECK_NAMES)
            assert obj["checks"]["major_materials_match"] == "unknown"
            assert obj["checks"]["major_colours_match"] == "unknown"
            assert obj["visibility"] in ("visible", "occluded", "never_in_frame", "unknown")

        detail = client.get(f"/api/projects/{pid}").json()["data"]
        kinds = {o["kind"] for o in detail["outputs"]}
        assert "render_verification" in kinds

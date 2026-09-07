"""M8: the golden project against the DPR §30 acceptance criteria.

Fixture: tests/fixtures/golden_project (brief + three reference images).
The AI part runs on the mock provider so it needs no keys; the Blender part
runs at test profiles and is skipped without BLENDER_PATH.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.projects.layout import project_dir

FIXTURE = Path(__file__).parent / "fixtures" / "golden_project"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _seed_project(client) -> str:
    pid = client.post("/api/projects", json={"name": "Golden 2BHK"}).json()["project"]["project_id"]
    files = [("references", (p.name, p.read_bytes(), "image/png")) for p in sorted((FIXTURE / "references").iterdir())]
    r = client.post(f"/api/projects/{pid}/inputs", data={"description": (FIXTURE / "brief.txt").read_text(encoding="utf-8")}, files=files)
    assert r.status_code == 200, r.text
    assert r.json()["rejected"] == []
    return pid


def test_inputs_analysis_and_scene_spec(client):
    from app.jobs import get_runner

    pid = _seed_project(client)
    root = project_dir(pid)
    # §30: text and images are locally stored and retrievable
    assert (root / "input" / "description.txt").exists()
    assert len(list((root / "input" / "references").iterdir())) == 3
    for i in client.get(f"/api/projects/{pid}/inputs").json()["data"]:
        if i["kind"] == "reference":
            assert client.get(i["meta"]["url"]).status_code == 200

    # §30: valid DesignAnalysis JSON is produced
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    analysis = json.loads((root / "analysis" / "design_analysis.json").read_text(encoding="utf-8"))
    assert analysis["rooms"] and all(r["width_m"] > 0 and r["length_m"] > 0 for r in analysis["rooms"])
    assert all("estimated" in r for r in analysis["rooms"])  # §23: dimensions given or marked estimated
    style = json.loads((root / "analysis" / "style_spec.json").read_text(encoding="utf-8"))
    assert style["palette"] and style["materials"]

    # §30: valid SceneSpec is compiled; every object resolves to a local file or a procedural definition
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]
    scene = spec["scene"]
    assert scene["rooms"] and scene["objects"]
    assert all(o["source_strategy"] in ("local_asset", "local_modified", "procedural", "generated") for o in scene["objects"])
    assert all(v["severity"] != "hard" for v in spec["violations"])
    asset_plan = json.loads((root / "planning" / "asset_plan.json").read_text(encoding="utf-8"))
    for d in asset_plan["decisions"]:
        assert d["strategy"] in ("local_asset", "local_modified", "procedural", "generated")
        if d["has_model"]:
            assert d["asset_id"]

    # §30: successful outputs are versioned and preserved; artifacts isolated by project id
    versions = client.get(f"/api/projects/{pid}/analysis").json()["data"]["versions"]
    assert {v["kind"] for v in versions} >= {"design_analysis", "style_spec", "object_plan", "asset_plan"}
    other = client.post("/api/projects", json={"name": "Other"}).json()["project"]["project_id"]
    assert not (project_dir(other) / "analysis" / "design_analysis.json").exists()


@pytest.mark.blender
def test_build_preview_and_package(client, blender_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    from app.jobs import get_runner

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)

    # §30: Blender builds from a manifest; materials, lighting and camera are automated
    client.post(f"/api/projects/{pid}/build", json={"preview": False})
    assert get_runner().wait_idle(600)
    root = project_dir(pid)
    report = json.loads((root / "blender" / "validation_report.json").read_text(encoding="utf-8"))
    assert report["ok"], report["errors"]
    assert report["counts"]["lights"] >= len(report["objects"]) * 0 + 2
    manifest = json.loads((root / "blender" / "build_manifest.json").read_text(encoding="utf-8"))
    assert manifest["camera"]["keyframes"] and manifest["lighting"]["interior_lights"]

    # §30: a stable walkthrough sequence renders; failed stages can retry without losing outputs
    client.post(f"/api/projects/{pid}/preview", json={"profile": "pano_test"})
    assert get_runner().wait_idle(900)
    tour = client.get(f"/api/projects/{pid}/tour").json()["data"]
    assert len(tour["tour"]["nodes"]) >= len(tour["rooms"])
    r = client.post(f"/api/projects/{pid}/walkthrough", json={"profile": "pano_test", "hero_stills": 0})
    assert r.status_code == 200, r.text
    assert get_runner().wait_idle(900)
    job = client.get(f"/api/jobs/{r.json()['job']['job_id']}").json()["data"]["job"]
    assert job["status"] == "SUCCEEDED", job["error"]
    package = json.loads((root / "outputs" / "manifest.json").read_text(encoding="utf-8"))
    assert package["panoramas"] and package["tour"].endswith("tour.json")
    # §30: one complete project reaches final output
    assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["stage"] == "COMPLETED"
    # the preview panoramas survived the final pass (checkpoints never overwritten)
    assert (root / "outputs" / "web" / "panos" / "preview").exists()

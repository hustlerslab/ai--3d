"""P12: design intent is live in the real scene_plan path.

These assert the WIRING, against the real routes and the real handler: that a
reference uploaded through the API reaches classification, that its class
governs what may be created, and that the API hands the result to the frontend.
The heavyweight ten-case live benchmark lives in
`research/p12_design_intent_benchmark.py` and is run separately - it creates
~30 projects and plans each, which is too slow for every suite run.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin
from PIL import Image

from app.jobs import get_runner
from app.projects.layout import project_dir

BRIEF = "Two bedroom flat: living room, master bedroom, kids room, kitchen. Warm and calm."


# Same local fixture every other API test file defines (test_scene_plan.py:182):
# the app is imported after `env` has pointed AETHER_DATA_DIR at a temp dir.
@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (150, 160, 140)).save(buf, "JPEG")
    return buf.getvalue()


def _planned_project(client, filenames: list[str]) -> str:
    pid = client.post("/api/projects", json={"name": "p12"}).json()["project"]["project_id"]
    files = [("references", (fn, _jpeg(), "image/jpeg")) for fn in filenames]
    r = client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF}, files=files)
    assert r.status_code == 200, r.text
    assert client.post(f"/api/projects/{pid}/analyze", json={}).status_code == 200
    assert get_runner().wait_idle(180)
    job = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    assert get_runner().wait_idle(300)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
    assert polled["status"] == "SUCCEEDED", polled.get("error")
    return pid


def _artifact(pid: str, name: str) -> dict:
    path = project_dir(pid) / "planning" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_an_uploaded_reference_reaches_design_intent_with_provenance(client):
    """The P11 blocker, closed: a real upload is classified by the live job."""
    pid = _planned_project(client, ["exact_sage_linen_sofa.jpg"])
    intent = _artifact(pid, "design_intent.json")

    assert len(intent["reference_ids"]) == 1
    assert len(intent["intents"]) == 1, intent.get("warnings")
    only = intent["intents"][0]
    assert only["reference_class"] == "exact_object"
    assert only["object_category"] == "sofa"
    # Provenance points back at the upload, not at a render.
    assert only["provenance"]["input_id"] == intent["reference_ids"][0]
    assert only["provenance"]["stage"] == "reference_classification"
    assert only["provenance"]["filename"] == "exact_sage_linen_sofa.jpg"


def test_an_exact_object_does_not_duplicate_the_planners_own_piece(client):
    from app.scene.store import get_store

    pid = _planned_project(client, ["exact_sage_linen_sofa.jpg"])
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]
    scene = get_store().load(spec["scene"]["scene_id"])
    assert len([o for o in scene.objects if o.semantic_type == "sofa"]) == 1


def test_a_design_reference_shapes_the_piece_without_creating_one(client):
    """DESIGN_REFERENCE influences appearance and instantiates nothing."""
    pid = _planned_project(client, ["sofa_green_velvet.jpg"])
    intent = _artifact(pid, "design_intent.json")
    plan = _artifact(pid, "object_plan.json")

    assert intent["intents"][0]["reference_class"] == "design_reference"
    sofas = [i for i in plan["items"] if i["semantic_type"] == "sofa"]
    assert len(sofas) == 1
    assert "velvet" in (sofas[0]["material_hint"] or "")
    assert not [i for i in plan["items"] if i["object_key"].startswith("intent_")]


def test_inspiration_only_never_becomes_furniture(client):
    from app.scene.store import get_store

    pid = _planned_project(client, ["inspiration_chandelier.jpg"])
    intent = _artifact(pid, "design_intent.json")
    fidelity = _artifact(pid, "visual_intent_fidelity.json")
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]
    scene = get_store().load(spec["scene"]["scene_id"])

    assert intent["intents"][0]["reference_class"] == "inspiration_only"
    assert not [o for o in scene.objects if o.semantic_type == "chandelier"]
    assert fidelity["metrics"]["non_instantiation_compliance"] in (None, 1.0)


def test_conflicting_references_surface_as_unresolved_not_a_silent_pick(client):
    pid = _planned_project(client, ["sofa_linen.jpg", "sofa_leather.jpg"])
    intent = _artifact(pid, "design_intent.json")
    job = client.get(f"/api/projects/{pid}/jobs").json()["data"][0]

    assert intent["conflicts"], "a clash must be recorded"
    assert job["result"]["unresolved_intents"], "and must surface as needs-input"
    assert job["result"]["design_intent"]["conflicts"] >= 1


def test_every_reference_reaches_a_terminal_state(client):
    """The hardcoded six-reference cap must never come back."""
    names = [f"sofa_ref_{i}.jpg" for i in range(8)]
    pid = _planned_project(client, names)
    intent = _artifact(pid, "design_intent.json")
    assert len(intent["reference_ids"]) == 8
    assert len(intent["intents"]) + len(intent["unread"]) == 8


def test_the_api_hands_intent_and_fidelity_to_the_frontend(client):
    pid = _planned_project(client, ["exact_sage_linen_sofa.jpg"])
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]

    assert spec["design_intent"]["intents"], "the frontend must be able to show what was read"
    metrics = spec["visual_intent_fidelity"]["metrics"]
    assert set(metrics) >= {"instantiation_fidelity", "appearance_fidelity",
                            "non_instantiation_compliance", "traceability"}
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["checkpoints"]["design_intent"] is True
    assert detail["checkpoints"]["visual_intent_fidelity"] is True


def test_the_job_reports_the_real_terminal_state_not_a_generic_message(client):
    pid = _planned_project(client, ["exact_sage_linen_sofa.jpg", "inspiration_chandelier.jpg"])
    job = client.get(f"/api/projects/{pid}/jobs").json()["data"][0]
    events = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["events"]
    intent_events = [e["message"] for e in events if e["stage"] == "plan.intent"]

    assert intent_events, "the feed must say what the references did"
    assert any("classified" in m for m in intent_events)
    assert job["result"]["design_intent"]["references"] == 2

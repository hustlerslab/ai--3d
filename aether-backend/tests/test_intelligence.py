"""Intelligence layer: mock provider, Gemini provider (mocked HTTP), resilient
fallback, the analyze job and the analysis routes."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.intelligence import (
    DesignAnalysis,
    InputBundle,
    ReferenceImage,
    ResilientProvider,
    StyleSpec,
    build_input_bundle,
    get_provider,
    reset_provider,
)
from app.intelligence.gemini_provider import GeminiError, GeminiProvider
from app.intelligence.images import palette_from_images
from app.intelligence.mock_provider import MockProvider
from app.projects import ProjectStage, RoomHint, get_project_store
from app.projects.layout import project_dir

BRIEF = (
    "2BHK in Pune for a young couple. Warm modern minimal with oak floors, a big sofa, "
    "a dining table for six and lots of plants. Budget is tight so avoid marble. "
    "Keep the master bedroom calm and moody."
)


def _solid(path, rgb, size=(64, 64)):
    Image.new("RGB", size, rgb).save(path)
    return path


# ── mock provider ────────────────────────────────────────────────────────


def test_mock_analysis_is_deterministic_and_structured(env):
    bundle = InputBundle(project_id="p", description=BRIEF)
    a1 = MockProvider().analyze_input(bundle)
    a2 = MockProvider().analyze_input(bundle)
    assert a1.model_dump(exclude={"created_at"}) == a2.model_dump(exclude={"created_at"})

    ids = [r.room_id for r in a1.rooms]
    assert ids == ["living_room", "kitchen", "master_bedroom", "bedroom"]
    assert all(r.estimated for r in a1.rooms)
    sems = {o.semantic_type for o in a1.spotted_objects}
    assert {"sofa", "dining_table", "plant"} <= sems
    sofa = next(o for o in a1.spotted_objects if o.semantic_type == "sofa")
    assert sofa.room_id == "living_room"
    assert any("marble" in c for c in a1.constraints)
    assert {"warm", "modern", "minimal", "natural", "moody"} <= set(a1.keywords)
    assert a1.intent.startswith("2BHK in Pune")


def test_mock_rooms_from_hints_respect_given_dimensions(env):
    hints = [
        RoomHint(name="Living", type="living_room", width_m=5.2, length_m=4.8, estimated=False),
        RoomHint(name="Bedroom", type="bedroom"),
    ]
    a = MockProvider().analyze_input(InputBundle(project_id="p", description="", room_hints=hints))
    living, bed = a.rooms
    assert living.room_id == "living" and living.width_m == 5.2 and living.estimated is False
    assert bed.estimated is True and bed.width_m == 4.0


def test_mock_style_palette_from_images(env, tmp_path):
    red = _solid(tmp_path / "red.png", (200, 30, 30))
    blue = _solid(tmp_path / "blue.png", (30, 30, 200), size=(32, 32))
    palette = palette_from_images([red, blue])
    assert palette[0].startswith("#C") and palette[0][3:5] in ("18", "28")  # reddish
    bundle = InputBundle(
        project_id="p",
        description=BRIEF,
        references=[ReferenceImage(path=str(red)), ReferenceImage(path=str(blue))],
    )
    analysis = MockProvider().analyze_input(bundle)
    style = MockProvider().create_style_spec(analysis, bundle)
    assert style.palette == palette
    assert style.name == "warm_modern_minimal"
    assert style.lighting_mood == "evening"  # "moody" in the brief
    assert len(style.materials) >= 3          # built-in materials exist without disk records
    assert style.warnings == []


# ── gemini provider with a fake transport ────────────────────────────────


def _gemini_payload(obj) -> dict:
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(obj)}]}}]}


ANALYSIS_OK = {
    "intent": "Warm 2BHK for a couple",
    "rooms": [
        {"name": "Living Room", "type": "living_room", "width_m": 5.2, "length_m": 4.8, "estimated": False},
        {"name": "Master Bedroom", "type": "master_bedroom", "width_m": 4.4, "length_m": 4.0, "estimated": True},
    ],
    "constraints": ["avoid marble"],
    "spotted_objects": [
        {"semantic_type": "sofa", "room_name": "Living Room", "confidence": 0.9, "notes": "grey fabric"},
        {"semantic_type": "unicorn", "confidence": 0.9},
    ],
    "keywords": ["warm", "modern", "not_a_tag"],
    "confidence": 0.82,
}


def _provider(handler, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.core import config

    config.get_settings.cache_clear()
    return GeminiProvider(transport=httpx.MockTransport(handler))


def test_gemini_analysis_is_validated_and_coerced(env, monkeypatch, tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["parts"] = body["contents"][0]["parts"]
        seen["schema"] = body["generationConfig"]["responseSchema"]
        return httpx.Response(200, json=_gemini_payload(ANALYSIS_OK))

    img = _solid(tmp_path / "ref.png", (120, 100, 80))
    bundle = InputBundle(project_id="p", description=BRIEF, references=[ReferenceImage(path=str(img))])
    analysis = _provider(handler, monkeypatch).analyze_input(bundle)

    assert analysis.provider == "gemini"
    assert [r.room_id for r in analysis.rooms] == ["living_room", "master_bedroom"]
    assert analysis.rooms[0].estimated is False
    assert [o.semantic_type for o in analysis.spotted_objects] == ["sofa"]
    assert analysis.spotted_objects[0].room_id == "living_room"
    assert analysis.keywords == ["warm", "modern"]
    assert any("unicorn" in w for w in analysis.warnings)
    # the photo went inline and the schema was sent
    assert any("inline_data" in p for p in seen["parts"])
    assert seen["schema"]["type"] == "OBJECT"


def test_gemini_repairs_invalid_json_once(env, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{not json"}]}}]})
        return httpx.Response(200, json=_gemini_payload(ANALYSIS_OK))

    analysis = _provider(handler, monkeypatch).analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert len(calls) == 2
    assert calls[1]["contents"][-1]["parts"][0]["text"].startswith("That was not valid JSON")
    assert analysis.intent == "Warm 2BHK for a couple"


def test_gemini_http_error_raises(env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(GeminiError) as exc:
        _provider(handler, monkeypatch).analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert "429" in str(exc.value)


def test_resilient_provider_falls_back_with_warning(env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    primary = _provider(handler, monkeypatch)
    resilient = ResilientProvider(primary, MockProvider(), allow_fallback=True)
    analysis = resilient.analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert analysis.provider == "mock(fallback)"
    assert analysis.warnings[0].startswith("gemini failed during analyze_input")
    assert [r.room_id for r in analysis.rooms][0] == "living_room"

    strict = ResilientProvider(primary, MockProvider(), allow_fallback=False)
    with pytest.raises(GeminiError):
        strict.analyze_input(InputBundle(project_id="p", description=BRIEF))


def test_get_provider_is_mock_without_key(env):
    reset_provider()
    provider = get_provider()
    assert provider.mode == "mock" and provider.primary is None


# ── analyze job + routes ─────────────────────────────────────────────────


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _project_with_inputs(client, tmp_path) -> str:
    pid = client.post("/api/projects", json={"name": "Pune 2BHK"}).json()["project"]["project_id"]
    img = _solid(tmp_path / "ref.png", (180, 150, 120))
    r = client.post(
        f"/api/projects/{pid}/inputs",
        data={"description": BRIEF},
        files=[("references", ("ref.png", img.read_bytes(), "image/png"))],
    )
    assert r.status_code == 200, r.text
    return pid


def test_analyze_job_writes_checkpoints_and_moves_stage(client, tmp_path):
    from app.jobs import get_runner

    pid = _project_with_inputs(client, tmp_path)
    r = client.post(f"/api/projects/{pid}/analyze", json={})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert get_runner().wait_idle(30)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
    assert polled["status"] == "SUCCEEDED", polled["error"]
    assert polled["result"]["style"] == "warm_modern_minimal"
    assert polled["result"]["provider"] == "mock"

    root = project_dir(pid)
    for name in ("design_analysis.json", "style_spec.json", "moodboard_spec.json", "agent_analyze_input.json"):
        assert (root / "analysis" / name).exists(), name
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["project"]["stage"] == "DESIGN_SPEC_READY"
    assert detail["checkpoints"]["analysis"] is True and detail["checkpoints"]["moodboard"] is True

    body = client.get(f"/api/projects/{pid}/analysis").json()["data"]
    assert body["analysis"]["version"] == 1
    assert body["style"]["palette"] and body["moodboard"]["reference_urls"][0].startswith("/files/projects/")
    kinds = {v["kind"] for v in body["versions"]}
    assert kinds == {"design_analysis", "style_spec", "moodboard_spec"}
    assert body["provider"]["mode"] == "mock"

    # re-running without force skips the checkpoints
    job2 = client.post(f"/api/projects/{pid}/analyze", json={}).json()["job"]
    assert get_runner().wait_idle(30)
    events = client.get(f"/api/jobs/{job2['job_id']}").json()["data"]["events"]
    assert sum("skipped" in e["message"] for e in events) == 2


def test_analyze_requires_inputs(client):
    pid = client.post("/api/projects", json={"name": "Empty"}).json()["project"]["project_id"]
    r = client.post(f"/api/projects/{pid}/analyze", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_INPUTS"
    r = client.get(f"/api/projects/{pid}/analysis")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYSIS_NOT_READY"


def test_patch_analysis_creates_new_version_and_syncs_hints(client, tmp_path):
    from app.jobs import get_runner

    pid = _project_with_inputs(client, tmp_path)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(30)

    r = client.patch(
        f"/api/projects/{pid}/analysis",
        json={
            "rooms": [
                {"room_id": "living_room", "width_m": 6.0, "length_m": 4.5},
                {"room_id": "study", "type": "study", "name": "Study"},
            ],
            "remove_rooms": ["bedroom"],
            "style": {"lighting_mood": "warm_daylight", "palette": ["#112233", "445566"]},
        },
    )
    assert r.status_code == 200, r.text
    analysis = r.json()["analysis"]
    ids = [x["room_id"] for x in analysis["rooms"]]
    assert "bedroom" not in ids and "master_bedroom" in ids and "study" in ids
    living = next(x for x in analysis["rooms"] if x["room_id"] == "living_room")
    assert living["width_m"] == 6.0 and living["estimated"] is False
    assert analysis["version"] == 2 and analysis["provider"] == "user"
    style = r.json()["style"]
    assert style["palette"] == ["#112233", "#445566"] and style["lighting_mood"] == "warm_daylight"

    project = get_project_store().get(pid)
    assert any(h.name == "Study" for h in project.room_hints)
    assert project.stage == ProjectStage.DESIGN_SPEC_READY
    versions = client.get(f"/api/projects/{pid}/analysis").json()["data"]["versions"]
    assert max(v["version"] for v in versions if v["kind"] == "design_analysis") == 2

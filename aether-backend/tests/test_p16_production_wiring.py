"""P16: the product actually uses P11-P15, through the real HTTP API.

Every earlier phase proved a capability. This proves the PRODUCT reaches it:
the same endpoints the frontend calls, the same job handlers, the same files on
disk, the same manifest Blender reads. Nothing here constructs a pipeline of its
own - if a route stopped calling `scene_plan`, or `scene_plan` stopped calling
the P11 classifier, these fail.

The intelligence provider is the mock, because CI must be deterministic and must
not spend money. Everything else is real: real routes, real job runner, real
solver, real compiler, real manifest, and real Blender where BLENDER_PATH is
set. The live-Gemini equivalent of the extraction step is measured in
research/p15_extraction_experiment.py.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.jobs import get_runner
from app.projects.layout import project_dir
from app.scene.store import get_store

BRIEF = ("Two bedroom flat: living room, master bedroom, kids room, kitchen. "
         "Warm and calm, natural materials.")
RICH = "exact_sage_linen_quilted_contemporary_sofa_dark_walnut_frame.jpg"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _jpeg(color=(150, 160, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "JPEG")
    return buf.getvalue()


def _project(client, name="P16 wiring") -> str:
    r = client.post("/api/projects", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["project"]["project_id"]


def _upload(client, pid: str, filenames=(RICH,)) -> dict:
    files = [("references", (fn, _jpeg(), "image/jpeg")) for fn in filenames]
    r = client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, path: str, body: dict | None = None, timeout: int = 300) -> dict:
    """POST a job route the frontend uses, wait, and return the polled job."""
    r = client.post(path, json=body or {})
    assert r.status_code == 200, r.text
    job_id = r.json()["job"]["job_id"]
    assert get_runner().wait_idle(timeout)
    return client.get(f"/api/jobs/{job_id}").json()["data"]["job"]


def _planned(client, filenames=(RICH,)) -> tuple[str, str]:
    """The real production sequence the Studio drives: create, upload,
    analyze, scene-plan."""
    pid = _project(client)
    _upload(client, pid, filenames)
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    job = _run(client, f"/api/projects/{pid}/scene-plan")
    assert job["status"] == "SUCCEEDED", job.get("error")
    return pid, job["result"]["scene_id"]


# ════════════════════════════════════════════════════════════════════════
# 1. the production entrypoints carry the ids the frontend needs
# ════════════════════════════════════════════════════════════════════════

def test_the_upload_route_returns_stable_reference_ids(client):
    """The frontend keeps only `project_id` in sessionStorage and refetches
    everything else, so reference identity must live on the server."""
    pid = _project(client)
    body = _upload(client, pid, (RICH, "style_japandi_palette.jpg"))

    assert body["rejected"] == []
    listed = client.get(f"/api/projects/{pid}/inputs").json()["data"]
    refs = [i for i in listed if i["kind"] == "reference"]
    assert len(refs) == 2
    assert all(r["input_id"] for r in refs)
    again = client.get(f"/api/projects/{pid}/inputs").json()["data"]
    assert [i["input_id"] for i in again] == [i["input_id"] for i in listed]


def test_the_scene_plan_route_returns_a_retrievable_scene_id(client):
    pid, scene_id = _planned(client)

    assert scene_id
    assert client.get(f"/api/scenes/{scene_id}").status_code == 200
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]
    assert spec["scene"]["scene_id"] == scene_id


def test_a_project_reload_returns_the_same_scene(client):
    """Browser refresh: the Studio re-opens a project from `scene_ids[-1]`."""
    pid, scene_id = _planned(client)
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["project"]["scene_ids"][-1] == scene_id


def test_two_projects_never_share_a_scene(client):
    """Guards the 'old scene shown as the new one' failure at the data layer."""
    _pid_a, scene_a = _planned(client)
    _pid_b, scene_b = _planned(client)

    assert scene_a != scene_b
    assert get_store().load(scene_a).project_id != get_store().load(scene_b).project_id


# ════════════════════════════════════════════════════════════════════════
# 2. the production route really invokes P11-P15
# ════════════════════════════════════════════════════════════════════════

def test_the_production_scene_plan_runs_the_p11_p15_reference_path(client):
    """`design_intent.json` exists only if the route reached
    `classify_references`. No benchmark harness is involved."""
    pid, _scene_id = _planned(client)
    path = project_dir(pid) / "planning" / "design_intent.json"
    assert path.exists(), "the production route did not classify references"

    intent_set = json.loads(path.read_text(encoding="utf-8"))
    assert intent_set["reference_ids"], "no reference reached the classifier"
    assert intent_set["intents"], "no typed intent was produced"
    assert intent_set["unread"] == [], intent_set.get("warnings")


def test_the_production_scene_plan_writes_the_fidelity_report(client):
    """`visual_intent_fidelity.json` exists only if the route reached
    `resolve_all` and `visual_intent_fidelity`."""
    pid, _scene_id = _planned(client)
    report = json.loads((project_dir(pid) / "planning" / "visual_intent_fidelity.json")
                        .read_text(encoding="utf-8"))

    assert "survival" in report
    by_attribute = {row["attribute"]: row for row in report["survival"]}
    assert "frame_finish" in by_attribute
    # P14's honesty rule survives the API boundary: preservation is not rendering.
    assert by_attribute["pattern"]["executor"] == "preserved_metadata_only"


def test_the_scene_spec_route_exposes_intent_and_fidelity_to_the_frontend(client):
    pid, _scene_id = _planned(client)
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]

    assert spec.get("design_intent"), "the frontend cannot see the design intent"
    assert spec.get("visual_intent_fidelity"), "the frontend cannot see fidelity"


def test_visual_attributes_survive_the_api_boundary(client):
    """P13 put them on SceneObject; this asserts they are still there after a
    round trip through HTTP, not only inside a Python object."""
    _pid, scene_id = _planned(client)
    scene = client.get(f"/api/scenes/{scene_id}").json()["data"]["scene"]
    sofas = [o for o in scene["objects"] if o["semantic_type"] == "sofa"]
    assert sofas, "the client's sofa never reached the scene"

    visual = sofas[0]["visual"]
    assert visual["color_words"], "colour words lost at the API boundary"
    assert visual["frame_finish"], "frame finish lost at the API boundary"
    assert visual["source_intent_ids"], "traceability lost at the API boundary"


def test_the_full_traceability_chain_survives_the_real_api(client):
    """input_id -> intent_id -> scene object, end to end over HTTP. One
    provenance system, the P11 one; nothing invented for P16."""
    pid, scene_id = _planned(client)

    inputs = client.get(f"/api/projects/{pid}/inputs").json()["data"]
    input_ids = {i["input_id"] for i in inputs if i["kind"] == "reference"}

    intent_set = json.loads((project_dir(pid) / "planning" / "design_intent.json")
                            .read_text(encoding="utf-8"))
    intent_by_id = {i["intent_id"]: i for i in intent_set["intents"]}
    assert intent_by_id

    for intent in intent_set["intents"]:
        assert intent["provenance"]["input_id"] in input_ids

    scene = client.get(f"/api/scenes/{scene_id}").json()["data"]["scene"]
    traced = [o for o in scene["objects"] if o["visual"]["source_intent_ids"]]
    assert traced, "no scene object is traceable to a reference"
    for obj in traced:
        for intent_id in obj["visual"]["source_intent_ids"]:
            assert intent_id in intent_by_id, f"{intent_id} belongs to no intent"


# ════════════════════════════════════════════════════════════════════════
# 3. failures reach the client, and never look like success
# ════════════════════════════════════════════════════════════════════════

def test_scene_plan_before_analysis_is_refused_with_a_typed_error(client):
    pid = _project(client)
    _upload(client, pid)
    r = client.post(f"/api/projects/{pid}/scene-plan", json={})

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ANALYSIS_REQUIRED"


def test_analyze_with_no_inputs_is_refused(client):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/analyze", json={})

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "NO_INPUTS"


def test_a_failed_job_reports_failed_and_carries_its_reason(client):
    """The frontend decides 'failed' from job.status; it must never have to
    infer failure from a missing field."""
    pid = _project(client)
    _upload(client, pid)
    job = _run(client, f"/api/projects/{pid}/jobs", {"type": "scene_plan", "params": {}})

    assert job["status"] == "FAILED"
    assert job["error"], "a failed job must say why"
    assert not job.get("result"), "a failed job must not carry a result"


def test_a_failed_generation_leaves_no_scene_to_mistake_for_success(client):
    pid = _project(client)
    _upload(client, pid)
    _run(client, f"/api/projects/{pid}/jobs", {"type": "scene_plan", "params": {}})

    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["project"]["scene_ids"] == [], "a failed plan must publish no scene"


# ════════════════════════════════════════════════════════════════════════
# 4. idempotency
# ════════════════════════════════════════════════════════════════════════

def test_double_clicking_generate_does_not_queue_the_work_twice(client):
    """Two `scene_plan` jobs on the two-worker ai lane write the same planning
    files concurrently. The second request joins the first."""
    pid = _project(client)
    _upload(client, pid)
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"

    first = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    second = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    assert second["job_id"] == first["job_id"], "a double click queued two plans"

    assert get_runner().wait_idle(300)
    jobs = client.get(f"/api/projects/{pid}/jobs").json()["data"]
    assert len([j for j in jobs if j["type"] == "scene_plan"]) == 1


def test_a_finished_job_never_blocks_a_genuine_re_run(client):
    """The guard is in-flight only, so `force` and retries still work."""
    pid, _scene_id = _planned(client)
    again = _run(client, f"/api/projects/{pid}/scene-plan", {"force": True})

    assert again["status"] == "SUCCEEDED"
    jobs = client.get(f"/api/projects/{pid}/jobs").json()["data"]
    assert len([j for j in jobs if j["type"] == "scene_plan"]) == 2


# ════════════════════════════════════════════════════════════════════════
# 5. the manifest is the record of what was compiled
# ════════════════════════════════════════════════════════════════════════

def test_the_build_route_is_refused_cleanly_when_blender_is_absent(client, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", "")
    from app.core import config
    config.get_settings.cache_clear()

    pid, _scene_id = _planned(client)
    r = client.post(f"/api/projects/{pid}/build", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "BLENDER_NOT_CONFIGURED"


def test_the_manifest_carries_p13_visual_and_p14_finish(client, blender_path, monkeypatch):
    """The real build route, the real manifest, real Blender. The end of the
    chain: what the executor was actually told to paint."""
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config
    config.get_settings.cache_clear()

    pid, scene_id = _planned(client)
    job = _run(client, f"/api/projects/{pid}/build", {"preview": False}, timeout=900)
    assert job["status"] == "SUCCEEDED", job.get("error")

    manifest = json.loads((project_dir(pid) / "blender" / "build_manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["objects"], "the manifest compiled no objects"
    assert manifest["scene_id"] == scene_id

    described = [o for o in manifest["objects"] if "visual" in o]
    assert described, "no reference-derived object reached the executor"
    for row in described:
        assert "finish" in row, "P14's finish block is missing from the manifest"
        assert row["finish"]["state"] in {"rendered", "metadata_only", "unsupported", "none"}
        assert row["finish"]["source"] in {"stated", "descriptor", ""}


def test_blender_persists_the_scene_and_the_api_can_retrieve_it(client, blender_path, monkeypatch):
    """A successful response must not point at a file that vanishes."""
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config
    config.get_settings.cache_clear()

    pid, _scene_id = _planned(client)
    assert _run(client, f"/api/projects/{pid}/build", {"preview": True},
                timeout=900)["status"] == "SUCCEEDED"

    build = client.get(f"/api/projects/{pid}/build").json()["data"]
    assert build["report"], "no validation report"
    for key in ("blend", "manifest"):
        url = build["files"].get(key)
        assert url, f"{key} missing from the build response"
        assert client.get(url).status_code == 200, f"{key} url 404s: {url}"

    blend = project_dir(pid) / "blender" / "scene.blend"
    assert blend.exists() and blend.stat().st_size > 0


# ════════════════════════════════════════════════════════════════════════
# 6. no demo path is reachable in production
# ════════════════════════════════════════════════════════════════════════

def test_the_seed_scene_is_never_one_of_a_real_projects_scenes(client):
    """The Studio used to fall back to the seed apartment when a project had no
    scene of its own. Whatever the UI does, the seed scene must never appear in
    a real project's scene list."""
    pid, scene_id = _planned(client)
    detail = client.get(f"/api/projects/{pid}").json()["data"]

    assert "scene_seed_apartment" not in detail["project"]["scene_ids"]
    assert scene_id != "scene_seed_apartment"


# ════════════════════════════════════════════════════════════════════════
# 7. a cached analysis must not outlive the references it was built from
# ════════════════════════════════════════════════════════════════════════

def test_the_analysis_records_which_references_produced_it(client):
    pid = _project(client)
    _upload(client, pid, (RICH,))
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"

    inputs = client.get(f"/api/projects/{pid}/inputs").json()["data"]
    refs = [i["input_id"] for i in inputs if i["kind"] == "reference"]
    analysis = json.loads((project_dir(pid) / "analysis" / "design_analysis.json")
                          .read_text(encoding="utf-8"))

    assert analysis["reference_ids"] == refs


def test_uploading_another_reference_invalidates_the_cached_analysis(client):
    """The bug this guards: a project analysed under an older, smaller Gemini
    cap kept reporting 'only the first 6 of 8 references were sent' forever,
    because the analyze job reused its checkpoint without ever checking that
    the reference set had changed."""
    pid = _project(client)
    _upload(client, pid, (RICH,))
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    first = json.loads((project_dir(pid) / "analysis" / "design_analysis.json")
                       .read_text(encoding="utf-8"))

    _upload(client, pid, ("style_japandi_palette.jpg",))
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    second = json.loads((project_dir(pid) / "analysis" / "design_analysis.json")
                        .read_text(encoding="utf-8"))

    assert len(second["reference_ids"]) == 2
    assert second["reference_ids"] != first["reference_ids"]
    assert second["version"] > first["version"], "the analysis was not re-run"


def test_an_unchanged_reference_set_still_reuses_the_checkpoint(client):
    """The guard must not turn every analyze into a re-spend."""
    pid = _project(client)
    _upload(client, pid, (RICH,))
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    first = json.loads((project_dir(pid) / "analysis" / "design_analysis.json")
                       .read_text(encoding="utf-8"))

    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    second = json.loads((project_dir(pid) / "analysis" / "design_analysis.json")
                        .read_text(encoding="utf-8"))

    assert second["version"] == first["version"], "an unchanged project re-analysed"


def test_an_analysis_written_before_this_field_existed_is_treated_as_stale(client):
    """Backward compatibility: the old artifact still loads, and because it
    cannot prove which references it used, it must not be trusted."""
    from app.intelligence.schema import DesignAnalysis

    legacy = DesignAnalysis.model_validate({
        "intent": "warm and calm", "rooms": [],
        "warnings": ["only the first 6 of 8 references were sent to Gemini"],
    })
    assert legacy.reference_ids == []
    assert legacy.reference_ids != ["in_ab12cd"], "empty must never match a real set"


def test_a_stale_reference_warning_does_not_survive_a_re_analysis(client):
    """The user-visible symptom: the banner must disappear once the analysis
    is recomputed for the current references."""
    pid = _project(client)
    _upload(client, pid, (RICH,))
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"

    path = project_dir(pid) / "analysis" / "design_analysis.json"
    analysis = json.loads(path.read_text(encoding="utf-8"))
    analysis["warnings"] = ["only the first 6 of 8 references were sent to Gemini"]
    analysis["reference_ids"] = ["in_stale_one", "in_stale_two"]
    path.write_text(json.dumps(analysis), encoding="utf-8")

    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    after = json.loads(path.read_text(encoding="utf-8"))

    assert "only the first 6 of 8 references were sent to Gemini" not in after["warnings"]

    style = json.loads((project_dir(pid) / "analysis" / "style_spec.json")
                       .read_text(encoding="utf-8"))
    assert "only the first 6 of 8 references were sent to Gemini" not in style.get("warnings", []), \
        "the style spec kept its own copy of the stale warning"


# ════════════════════════════════════════════════════════════════════════
# 8. observability without leaking secrets
# ════════════════════════════════════════════════════════════════════════

def test_the_gemini_key_never_travels_in_the_url(monkeypatch):
    """httpx logs whole URLs at INFO. As a query parameter the live key was
    written in clear text into the job and server logs on every call."""
    import httpx

    from app.core import config
    from app.intelligence.gemini_provider import GeminiProvider

    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-value")
    config.get_settings.cache_clear()
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    provider = GeminiProvider(config.get_settings(), transport=httpx.MockTransport(capture))
    provider._generate([{"text": "hi"}], {"type": "object", "properties": {}}, "p16.test")

    assert seen, "no request was made"
    request = seen[0]
    assert "test-secret-value" not in str(request.url), "the key is in the URL"
    assert request.headers.get("x-goog-api-key") == "test-secret-value"
    config.get_settings.cache_clear()


def test_each_job_logs_the_ids_needed_to_trace_one_generation(client, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="aether.jobs")
    pid, scene_id = _planned(client)

    lines = [r.getMessage() for r in caplog.records if r.name == "aether.jobs"]
    started = [m for m in lines if m.startswith("job.start")]
    done = [m for m in lines if m.startswith("job.succeeded")]

    assert any("type=scene_plan" in m and f"project={pid}" in m for m in started)
    assert any(f"scene_id={scene_id}" in m for m in done), "the scene id is not traceable in logs"
    # ids only: no brief text, no prompt, no key
    for message in lines:
        assert BRIEF[:40] not in message


def test_the_provider_mode_is_reported_honestly(client):
    """The viewer labels a mock run 'deterministic mock'. That label is only
    truthful if health reports the real mode."""
    health = client.get("/api/health").json()
    intelligence = health["providers"]["intelligence"]

    assert intelligence["mode"] in {"live", "mock"}
    assert intelligence["mode"] == "mock", "this suite must not spend on a live provider"

"""Meshy adapter and the generate_assets job.

Every test here runs against a mocked httpx transport. Nothing in this file
touches the live API or spends a credit — the response shapes are transcribed
from a real verified call (11 Sep 2026), recorded in app/providers/meshy.py.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin

from app.providers import meshy

TASK = "01a09084-c443-7771-be68-6329f8e25814"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
    )


def _succeeded(textured: bool = False) -> dict:
    return {
        "id": TASK,
        "status": "SUCCEEDED",
        "progress": 100,
        "model_urls": {"glb": "https://assets.example/model.glb", "obj": "https://assets.example/model.obj"},
        "thumbnail_url": "https://assets.example/thumb.png",
        "texture_urls": [{"base_color": "https://assets.example/c.png"}] if textured else [],
        "consumed_credits": 5,
        "task_error": {"message": ""},
    }


# ── submit ───────────────────────────────────────────────────────────────


def test_submit_sends_the_prompt_and_returns_the_task_id():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(202, json={"result": TASK})

    async def go():
        async with _client(handler) as c:
            return await meshy.submit_text_to_3d(c, "a warm ceramic vase", mode="preview")

    assert asyncio.run(go()) == TASK
    assert seen["url"].endswith("/openapi/v2/text-to-3d")
    assert seen["body"]["prompt"] == "a warm ceramic vase"
    assert seen["body"]["mode"] == "preview"
    assert seen["auth"] == "Bearer test"


def test_an_empty_prompt_is_refused_before_the_request_is_made():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent for an empty prompt")

    async def go():
        async with _client(handler) as c:
            await meshy.submit_text_to_3d(c, "   ")

    with pytest.raises(meshy.MeshyError, match="prompt is required"):
        asyncio.run(go())


def test_a_400_carries_the_api_message():
    """The live API answers a missing prompt with exactly this shape."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Invalid values: Prompt is a required field"})

    async def go():
        async with _client(handler) as c:
            await meshy.submit_text_to_3d(c, "vase")

    with pytest.raises(meshy.MeshyError, match="Prompt is a required field"):
        asyncio.run(go())


def test_402_is_a_distinct_out_of_credits_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"message": "no credits"})

    async def go():
        async with _client(handler) as c:
            await meshy.submit_text_to_3d(c, "vase")

    with pytest.raises(meshy.MeshyOutOfCredits):
        asyncio.run(go())


def test_a_missing_task_id_is_an_error_not_a_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={})

    async def go():
        async with _client(handler) as c:
            await meshy.submit_text_to_3d(c, "vase")

    with pytest.raises(meshy.MeshyError, match="no task id"):
        asyncio.run(go())


# ── polling ──────────────────────────────────────────────────────────────


def test_wait_for_polls_until_it_succeeds_and_reports_progress():
    states = [
        {"status": "IN_PROGRESS", "progress": 25},
        {"status": "IN_PROGRESS", "progress": 99},
        _succeeded(),
    ]
    seen: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=states.pop(0))

    async def go():
        async with _client(handler) as c:
            return await meshy.wait_for(
                c, TASK, timeout_seconds=30, poll_seconds=0,
                on_progress=lambda s, p: seen.append((s, p)),
            )

    model = asyncio.run(go())
    assert model.glb_url == "https://assets.example/model.glb"
    assert model.credits == 5
    assert model.textured is False          # preview mode returns no textures
    assert seen == [("IN_PROGRESS", 25), ("IN_PROGRESS", 99), ("SUCCEEDED", 100)]


def test_a_failed_task_raises_with_the_vendor_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "FAILED", "progress": 0,
            "task_error": {"message": "prompt violates policy"},
        })

    async def go():
        async with _client(handler) as c:
            await meshy.wait_for(c, TASK, timeout_seconds=30, poll_seconds=0)

    with pytest.raises(meshy.MeshyError, match="prompt violates policy"):
        asyncio.run(go())


def test_a_task_that_never_finishes_times_out_rather_than_hanging():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "IN_PROGRESS", "progress": 10})

    async def go():
        async with _client(handler) as c:
            await meshy.wait_for(c, TASK, timeout_seconds=0, poll_seconds=0)

    with pytest.raises(meshy.MeshyError, match="still IN_PROGRESS"):
        asyncio.run(go())


def test_success_without_a_glb_is_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "SUCCEEDED", "progress": 100, "model_urls": {"obj": "x"}})

    async def go():
        async with _client(handler) as c:
            await meshy.wait_for(c, TASK, timeout_seconds=30, poll_seconds=0)

    with pytest.raises(meshy.MeshyError, match="without a glb"):
        asyncio.run(go())


# ── download ─────────────────────────────────────────────────────────────


def test_download_writes_the_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"glTF-bytes")

    dest = tmp_path / "nested" / "model.glb"

    async def go():
        async with _client(handler) as c:
            return await meshy.download_glb(c, "https://assets.example/model.glb", dest)

    assert asyncio.run(go()) == dest
    assert dest.read_bytes() == b"glTF-bytes"


def test_an_empty_download_is_rejected_and_leaves_no_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    dest = tmp_path / "model.glb"

    async def go():
        async with _client(handler) as c:
            await meshy.download_glb(c, "https://assets.example/model.glb", dest)

    with pytest.raises(meshy.MeshyError, match="empty file"):
        asyncio.run(go())
    assert not dest.exists()


def test_balance_reads_the_account():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/openapi/v1/balance")
        return httpx.Response(200, json={"balance": 4100})

    async def go():
        async with _client(handler) as c:
            return await meshy.balance(c)

    assert asyncio.run(go()) == 4100


def test_make_client_refuses_an_empty_key():
    with pytest.raises(meshy.MeshyError, match="MESHY_API_KEY"):
        meshy.make_client("")


# ── the job ──────────────────────────────────────────────────────────────


def test_the_job_is_registered_on_the_ai_lane():
    """Generation is network-bound: it must not occupy the single render
    thread that owns the GPU."""
    from app.jobs.registry import get_spec

    spec = get_spec("generate_assets")
    assert spec.lane.value == "ai"
    assert spec.max_attempts == 2


def test_the_checkpoint_name_is_stable_and_filesystem_safe():
    from app.jobs.handlers.generate import _asset_id, _glb_rel

    assert _glb_rel("obj_12ab") == "assets/generated/obj_12ab.glb"
    assert _glb_rel("living/sofa #1") == "assets/generated/living_sofa__1.glb"
    assert "/" not in _asset_id("proj_abcdef1234", "living/sofa #1")
    assert _asset_id("proj_abcdef1234", "o") == _asset_id("proj_abcdef1234", "o")


def test_generate_assets_needs_meshy_configured(env, client):
    """Without a key the job is a caller error, not a silent no-op — the
    conftest env fixture clears MESHY_API_KEY for every test."""
    from app.jobs.context import JobContext
    from app.jobs.handlers.generate import MeshyNotConfigured, generate_assets
    from app.jobs.store import get_job_store
    from app.projects.store import get_project_store

    project_id = client.post("/api/projects", json={"name": "p"}).json()["project"]["project_id"]
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=project_id, type="generate_assets", lane="ai")
    ctx = JobContext(job, projects.get(project_id), jobs, projects)
    try:
        with pytest.raises(MeshyNotConfigured):
            generate_assets(ctx)
    finally:
        ctx.close()


def test_a_model_that_fails_ingest_validation_is_not_reported_as_generated(env, monkeypatch, tmp_path):
    """Regression: a hard validation failure registers the record but writes no
    normalized glb (assets/pipeline.py), so the asset id resolves to nothing.
    The handler used to treat any returned id as success and would have swapped
    a working procedural stand-in for an asset the viewer cannot load.

    This is what an un-remeshed Meshy model does in practice: the first live run
    produced 1,926,510 triangles, past MAX_TRIANGLES_HARD.
    """
    import json

    from app.assets.schema import AssetRecord, ValidationIssue
    from app.jobs.context import JobContext
    from app.jobs.handlers import generate as gen
    from app.jobs.store import get_job_store
    from app.projects.layout import ensure_layout
    from app.projects.store import get_project_store

    monkeypatch.setenv("MESHY_API_KEY", "test-key")
    from app.core import config
    config.get_settings.cache_clear()

    projects, jobs = get_project_store(), get_job_store()
    project = projects.create(name="failed ingest")
    root = ensure_layout(project.project_id)
    (root / "planning").mkdir(parents=True, exist_ok=True)
    (root / "planning" / "asset_plan.json").write_text(json.dumps({
        "decisions": [{
            "object_key": "obj_vase", "semantic_type": "vase", "strategy": "generated",
            "asset_name": "vase", "has_model": False, "dimensions": [0.2, 0.4, 0.2],
            "color": "#b08968", "mount": "surface",
            "generation_prompt": "a sculptural vase", "reason": "sculptural",
        }],
        "counts": {}, "warnings": [],
    }), encoding="utf-8")

    # No network: the vendor "succeeds" and the file "downloads".
    async def fake_submit(*a, **k):
        return TASK

    async def fake_wait(*a, **k):
        return meshy.GeneratedModel(TASK, "https://assets.example/model.glb", "", 20, False)

    async def fake_download(client, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"glTF")
        return dest

    async def fake_balance(*a, **k):
        return 4100

    monkeypatch.setattr(meshy, "submit_text_to_3d", fake_submit)
    monkeypatch.setattr(meshy, "wait_for", fake_wait)
    monkeypatch.setattr(meshy, "download_glb", fake_download)
    monkeypatch.setattr(meshy, "balance", fake_balance)

    # …but the ingester rejects it, exactly as it does for a 1.9M-triangle mesh.
    def failed_ingest(path, meta):
        return AssetRecord(
            asset_id="gen_bad", name=meta.name, semantic_type=meta.semantic_type,
            status="failed",
            validation=[ValidationIssue(code="POLYCOUNT_EXTREME", severity="hard",
                                        message="1,926,510 triangles exceeds the hard limit.")],
        )

    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", failed_ingest)

    job = jobs.create(project_id=project.project_id, type="generate_assets", lane="ai")
    ctx = JobContext(job, projects.get(project.project_id), jobs, projects)
    try:
        result = gen.generate_assets(ctx)
    finally:
        ctx.close()

    assert result["generated"] == {}, "a failed ingest must not count as generated"
    assert result["replaced"] == 0, "nothing may be swapped in for a broken asset"
    assert any("failed ingest validation" in w for w in result["warnings"]), result["warnings"]
    assert any("1,926,510" in w for w in result["warnings"]), "the vendor reason must survive"

    # The stand-in survives: the plan must not claim a model it cannot load.
    plan = json.loads((root / "planning" / "asset_plan.json").read_text(encoding="utf-8"))
    assert plan["decisions"][0]["has_model"] is False
    assert plan["decisions"][0]["asset_id"] is None

    # And the checkpoint is NOT marked, so a later run can retry the piece.
    assert not ctx.has_checkpoint("assets/generated/obj_vase.glb")

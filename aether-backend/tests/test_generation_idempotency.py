"""P1-ASSET-002 - a crash or a retry can never cost the customer a second mesh.

The adapter had four download attempts and a per-project cap, but no
idempotency key: a job killed after Meshy accepted the task re-submitted the
same crop on retry and paid again. Now every submission is a row in
`generation_tasks`, written before anything waits on it, and a retry polls the
task it finds there.

The fault is injected at the adapter boundary: the vendor accepts the task,
then the wait "dies" (a dropped connection, exactly what a killed process
looks like from the ledger's side). The process is then restarted for real -
every singleton dropped, the database reopened from disk - and the job run
again. Submissions are counted throughout.
"""
from __future__ import annotations

from tests.conftest import _reset_singletons
from tests.test_asset_rebind import Reader, _approve_all, _fake_vendor, _project_with_render, client  # noqa: F401

from app.intelligence.schema import SceneReading
from app.jobs import get_job_store
from app.jobs.context import JobContext
from app.jobs.handlers import generate_elements as gen
from app.jobs.handlers import scene_plan
from app.projects import get_project_store
from app.providers import meshy
from app.spend import project_spend, request_key, resumable_task
from app.spend.tasks import get_task, project_tasks

READING = "planning/scene_reading.json"


# -- the key --------------------------------------------------------------------

def test_the_key_is_deterministic_for_identical_inputs_and_only_those(tmp_path):
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"png-bytes-1")
    params = {"should_remesh": True, "target_polycount": 30000, "enable_pbr": True, "symmetry_mode": "auto"}
    a, sha_a = request_key("living_room|bar_stool||metal|111111", crop, params)
    b, _ = request_key("living_room|bar_stool||metal|111111", crop, dict(reversed(list(params.items()))))
    assert a == b, "same inputs, any dict order: same request"
    assert a.startswith("gr_") and len(sha_a) == 64

    crop.write_bytes(b"png-bytes-2")
    c, _ = request_key("living_room|bar_stool||metal|111111", crop, params)
    assert c != a, "a different picture is a different request"
    crop.write_bytes(b"png-bytes-1")
    d, _ = request_key("living_room|bar_stool||metal|111111", crop, {**params, "target_polycount": 10000})
    assert d != a, "different parameters are a different generation"
    e, _ = request_key("living_room|sofa||fabric|2a4d8f", crop, params)
    assert e != a


# -- the fault: killed mid-generation, restarted, run again ----------------------

def _prepared(client):
    """A project whose reading has three approved crops and nothing bound."""
    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    _approve_all(ctx)
    return pid, ctx


def _restart(pid) -> JobContext:
    """What a process restart does to this backend: every cached store, the
    runner and the database handle are dropped and rebuilt from disk."""
    _reset_singletons()
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type="generate_elements", lane="ai")
    return JobContext(job, projects.get(pid), jobs, projects)


def test_killing_and_restarting_a_generation_job_submits_nothing_more(client, monkeypatch):
    pid, ctx = _prepared(client)
    calls = _fake_vendor(monkeypatch)
    polled: list[str] = []

    async def dies_waiting(client_, task_id, **kw):
        polled.append(task_id)
        raise meshy.MeshyError("All connection attempts failed")      # the process is gone

    monkeypatch.setattr(meshy, "wait_for", dies_waiting)
    try:
        first = gen.generate_elements(ctx)
    finally:
        ctx.close()
    assert calls["submit"] == 3, "three pieces, three submissions - the tasks are live at the vendor"
    assert first["made"] == {} and first["credits"] == 0
    rows = project_tasks(pid)
    assert len(rows) == 3 and all(r["status"] == "SUBMITTED" and r["task_id"] for r in rows), \
        "every receipt was written before the wait, and a dropped connection does not clear it"
    submitted = {r["task_id"] for r in rows}

    ctx2 = _restart(pid)
    assert {r["task_id"] for r in project_tasks(pid)} == submitted, "the ledger survived the restart"

    async def now_finishes(client_, task_id, **kw):
        polled.append(task_id)
        return meshy.GeneratedModel(task_id, "https://assets.example/model.glb", "", 30, False)

    monkeypatch.setattr(meshy, "wait_for", now_finishes)
    try:
        second = gen.generate_elements(ctx2)
    finally:
        ctx2.close()
    assert calls["submit"] == 3, "ZERO additional submissions across the kill/restart cycle"
    assert set(polled[3:]) == submitted, "the retry polled exactly the tasks the first run submitted"
    assert len(second["made"]) == 3 and second["credits"] == 90
    rows = {r["task_id"]: r for r in project_tasks(pid)}
    assert all(r["status"] == "SUCCEEDED" and r["asset_id"] and r["credits"] == 30 for r in rows.values())
    reading = SceneReading.model_validate(ctx2.read_json(READING))
    assert all(e.asset_id for e in reading.elements), "every piece bound, paid for once"
    assert project_spend(pid).total == 90, "and the spend ledger agrees: three pieces, not six"


def test_a_task_the_vendor_ended_is_resubmitted_and_a_timeout_is_not(client, monkeypatch):
    """Only the vendor closing the task clears the receipt. A timeout says
    nothing about the task and must not become a second purchase."""
    pid, ctx = _prepared(client)
    calls = _fake_vendor(monkeypatch)

    async def vendor_failed(client_, task_id, **kw):
        raise meshy.MeshyTaskFailed(f"task {task_id} ended as FAILED: mesh generation failed")

    monkeypatch.setattr(meshy, "wait_for", vendor_failed)
    try:
        gen.generate_elements(ctx)
    finally:
        ctx.close()
    assert calls["submit"] == 3
    assert {r["status"] for r in project_tasks(pid)} == {"FAILED"}
    assert all(resumable_task(r["request_id"]) is None for r in project_tasks(pid))

    async def timed_out(client_, task_id, **kw):
        raise meshy.MeshyError(f"task {task_id} still IN_PROGRESS at 40% after 600s")

    ctx2 = _restart(pid)
    monkeypatch.setattr(meshy, "wait_for", timed_out)
    try:
        gen.generate_elements(ctx2)
    finally:
        ctx2.close()
    assert calls["submit"] == 6, "vendor-failed tasks are genuinely gone: re-submitted, once each"
    assert {r["status"] for r in project_tasks(pid)} == {"SUBMITTED"}, "a timeout leaves the receipt"

    ctx3 = _restart(pid)
    try:
        gen.generate_elements(ctx3)
    finally:
        ctx3.close()
    assert calls["submit"] == 6, "and the next run polls; it does not submit"


def test_a_mesh_the_ingester_rejects_is_recorded_and_not_resumed(client, monkeypatch):
    from app.assets.schema import AssetRecord, ValidationIssue

    pid, ctx = _prepared(client)
    calls = _fake_vendor(monkeypatch)

    def rejects(path, meta):
        return AssetRecord(asset_id=meta.asset_id, name=meta.name, semantic_type=meta.semantic_type,
                           status="failed",
                           validation=[ValidationIssue(code="POLYCOUNT_EXTREME", severity="hard",
                                                       message="1,926,510 triangles exceeds the hard limit.")])

    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", rejects)
    try:
        result = gen.generate_elements(ctx)
    finally:
        ctx.close()
    assert calls["submit"] == 3 and result["made"] == {}
    rows = project_tasks(pid)
    assert {r["status"] for r in rows} == {"INGEST_FAILED"}
    assert all(r["credits"] == 30 and "1,926,510" in r["error"] for r in rows), "paid for, and it says so"
    assert all(resumable_task(r["request_id"]) is None for r in rows)
    assert get_task(rows[0]["request_id"])["asset_id"] == ""

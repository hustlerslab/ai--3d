"""Phase 3 — the typed, append-only event bus (P1-EVENT-001, 002, 003).

001: the envelope is additive; the migration is safe twice and old rows read.
002: one hook in `runner._execute` types every job transition; the handlers
     that know entity ids emit the canonical stage events; a broken writer
     never fails a job; a run shares one correlation id.
003: the database refuses UPDATE and DELETE; corrections are new rows;
     consumers are idempotent by event_id.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import _reset_singletons
from tests.test_asset_rebind import Reader, _approve_all, _fake_vendor, _project_with_render, client  # noqa: F401

from app.db import get_db
from app.db.sqlite import SCHEMA_VERSION, Database
from app.jobs import JobContext, JobLane, JobRunner, JobStatus, get_job_store, register
from app.jobs.registry import unregister
from app.jobs.store import EVENT_SCHEMA_VERSION, EventContractError
from app.projects import get_project_store

APP = Path(__file__).resolve().parents[1] / "app"


def _project(name: str = "Event flat"):
    return get_project_store().create(name=name)


def _typed(events, event_type):
    return [e for e in events if e.event_type == event_type]


# ── P1-EVENT-001: the envelope ─────────────────────────────────────────────


def _v9_database(path: Path) -> None:
    """A database exactly as schema v9 left it: the old 8-column events table
    with rows in it, and the marker saying 9."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
            job_id TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL, status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '', duration_ms INTEGER NOT NULL DEFAULT 0, ts TEXT NOT NULL);
        INSERT INTO events(project_id, job_id, stage, status, message, duration_ms, ts)
            VALUES ('proj_old', 'job_old', 'analyze', 'succeeded', 'from before the envelope', 12,
                    '2026-09-01T00:00:00+00:00');
        INSERT INTO meta(key, value) VALUES ('schema_version', '9');
    """)
    conn.commit()
    conn.close()


def test_the_migration_is_additive_and_safe_to_run_twice(tmp_path):
    from app.jobs.store import JobStore

    path = tmp_path / "old.db"
    _v9_database(path)

    db = Database(path)
    cols = {r["name"] for r in db.query("PRAGMA table_info(events)")}
    assert {"schema_version", "event_type", "severity", "confidence", "correlation_id", "parent_event_id",
            "producer", "entity_ids", "evidence_refs", "payload"} <= cols
    assert db.scalar("SELECT value FROM meta WHERE key='schema_version'") == str(SCHEMA_VERSION)
    assert SCHEMA_VERSION >= 10

    # Twice: forget the marker, which replays every step from 0.
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', 'garbage')")
    db.close()
    db = Database(path)

    old = JobStore(db).list_events("proj_old")
    assert len(old) == 1
    e = old[0]
    assert (e.stage, e.status, e.message, e.duration_ms) == ("analyze", "succeeded", "from before the envelope", 12)
    assert e.schema_version == "" and e.event_type == "" and e.entity_ids == [] and e.payload == {}
    db.close()


def test_every_existing_emit_call_shape_still_works_unchanged(env):
    """`ctx.emit(stage, message, status)` - the call every handler already
    makes - records exactly what it did before, and gains the envelope
    stamp without the caller saying anything."""
    project = _project()
    jobs = get_job_store()
    job = jobs.create(project_id=project.project_id, type="noop", lane="ai",
                      correlation_id=project.correlation_id)
    ctx = JobContext(job, project, jobs, get_project_store())
    try:
        ctx.emit("stage.a")
        ctx.emit("stage.b", "a message")
        ctx.emit("stage.c", "warned", status="warning")
    finally:
        ctx.close()
    rows = jobs.list_job_events(job.job_id)
    assert [(e.stage, e.message, e.status) for e in rows] == [
        ("stage.a", "", "progress"), ("stage.b", "a message", "progress"), ("stage.c", "warned", "warning")]
    for e in rows:
        assert e.schema_version == EVENT_SCHEMA_VERSION
        assert e.producer == "job.noop"
        assert e.correlation_id == project.correlation_id
        assert e.event_type == "" and e.severity == "", "nothing is invented for an emitter that said nothing"


def test_the_envelope_round_trips_and_a_sample_row_is_what_design_md_shows(env):
    project = _project()
    jobs = get_job_store()
    parent = jobs.add_event(project.project_id, "plan.scene", "progress", event_type="spatial.solve.started",
                            severity="info")
    e = jobs.add_event(
        project.project_id, "plan.repair", "failed", "2 hard violations remain", job_id="job_x",
        event_type="validation.failed", severity="error", confidence=0.9, parent_event_id=parent.event_id,
        producer="spatial_engine@4.0", entity_ids=["cel_ab12cd34ef", "cel_ab12cd34ef#1"],
        evidence_refs=["planning/validation_report.json", "renders/view_ne.png"],
        payload={"failure_category": "geometry_failure", "violation_count": 2})
    back = jobs.get_event(e.event_id)
    assert back == e
    assert back.correlation_id == project.correlation_id, "filled from the project when the emitter omits it"
    row = dict(get_db().one("SELECT * FROM events WHERE event_id = ?", (e.event_id,)))
    assert json.loads(row["evidence_refs"]) == ["planning/validation_report.json", "renders/view_ne.png"]
    assert row["severity"] == "error" and row["parent_event_id"] == parent.event_id


@pytest.mark.parametrize("ref", [
    '{"answer": "the sofa is blue"}', "line one\nline two", "data:image/png;base64,iVBORw0KGgo",
    "x" * 600, "", "<svg/>",
])
def test_evidence_refs_are_paths_never_content(env, ref):
    project = _project()
    with pytest.raises(EventContractError):
        get_job_store().add_event(project.project_id, "s", "progress", evidence_refs=[ref])
    assert get_job_store().list_events(project.project_id) == [], "refused BEFORE anything is written"


def test_severity_is_the_emitters_and_must_be_a_real_level(env):
    project = _project()
    with pytest.raises(EventContractError):
        get_job_store().add_event(project.project_id, "s", "progress", severity="bad")
    # and nothing downstream infers it: a status of "failed" does not make
    # an untyped event an error
    e = get_job_store().add_event(project.project_id, "s", "failed")
    assert e.severity == ""


# ── P1-EVENT-002: the choke point ──────────────────────────────────────────


def test_every_job_transition_produces_exactly_one_typed_event(env):
    project = _project()
    runner = JobRunner()
    job = runner.enqueue(project.project_id, "noop", {"steps": 2, "sleep": 0})
    assert runner.wait_idle(10)
    runner.shutdown()

    events = get_job_store().list_job_events(job.job_id)
    transitions = [e for e in events if e.producer == "jobs.runner"]
    assert [e.event_type for e in transitions] == ["job.queued", "job.started", "job.succeeded"]
    assert all(e.severity == "info" for e in transitions)
    assert transitions[-1].payload["attempt"] == 1
    assert {e.correlation_id for e in events} == {project.correlation_id}, "one run, one correlation id"


def test_retry_and_failure_are_typed_with_the_emitters_severity(env):
    calls = {"n": 0}

    @register("always_fails_evt", lane=JobLane.ai, max_attempts=2)
    def always_fails(ctx):
        calls["n"] += 1
        raise RuntimeError("boom")

    try:
        project = _project()
        runner = JobRunner(retry_delay=0.01)
        job = runner.enqueue(project.project_id, "always_fails_evt")
        assert runner.wait_idle(10)
        runner.shutdown()
    finally:
        unregister("always_fails_evt")

    types = [(e.event_type, e.severity) for e in get_job_store().list_job_events(job.job_id)
             if e.producer == "jobs.runner"]
    assert types == [("job.queued", "info"), ("job.started", "info"), ("job.retrying", "warning"),
                     ("job.started", "info"), ("job.failed", "error")]
    failed = _typed(get_job_store().list_job_events(job.job_id), "job.failed")[0]
    assert failed.payload["error"] == "RuntimeError: boom"


def test_a_broken_event_writer_never_fails_the_producing_job(env, monkeypatch, caplog):
    """The fault test: every event write raises. The work must still happen,
    succeed, and say so in the log."""
    from app.core.logging import install_record_factory
    from app.jobs import store as store_mod

    # Production's record factory binds `stage` on every LogRecord. Without it
    # installed this test passed while the drop path still crashed the job in
    # production: its warning passed `extra={"stage": ...}` and logging raised.
    install_record_factory()

    def broken(self, *a, **kw):
        raise sqlite3.OperationalError("disk I/O error")

    project = _project()
    monkeypatch.setattr(store_mod.JobStore, "add_event", broken)
    runner = JobRunner()
    with caplog.at_level("WARNING"):
        job = runner.enqueue(project.project_id, "noop", {"steps": 2, "sleep": 0})
        assert runner.wait_idle(10)
    runner.shutdown()
    monkeypatch.undo()

    done = get_job_store().get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED and done.result["steps"] == 2
    assert any("event.dropped" in r.getMessage() or "event not recorded" in r.getMessage()
               for r in caplog.records), "a dropped event is logged, never silent"


def test_a_contract_violation_is_not_swallowed(env):
    """Swallowing is for the WRITER failing. An emitter passing content as
    evidence is a bug, and a silently dropped event would hide it."""
    project = _project()
    jobs = get_job_store()
    job = jobs.create(project_id=project.project_id, type="noop", lane="ai")
    ctx = JobContext(job, project, jobs, get_project_store())
    try:
        with pytest.raises(EventContractError):
            ctx.emit("s", evidence_refs=['{"inlined": true}'])
    finally:
        ctx.close()


def test_scene_plan_emits_identity_solve_and_commit_with_entity_ids(client):  # noqa: F811
    """analyze + scene_plan on the golden fixture (mock provider)."""
    from app.jobs import get_runner
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)

    events = get_job_store().list_events(pid, limit=1000)
    started = _typed(events, "spatial.solve.started")
    completed = _typed(events, "spatial.solve.completed")
    committed = _typed(events, "scene.committed")
    assert len(started) == len(completed) == len(committed) == 1
    assert completed[0].parent_event_id == started[0].event_id
    assert committed[0].parent_event_id == completed[0].event_id, "the causal chain is explicit"
    assert committed[0].evidence_refs == ["planning/scene_spec.json"]
    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]["scene"]
    object_ids = {o["object_id"] for o in spec["objects"]}
    assert object_ids <= set(committed[0].entity_ids), "every placed object is named on the commit"
    assert committed[0].payload["objects"] == len(spec["objects"])

    project = get_project_store().get(pid)
    assert {e.correlation_id for e in events} == {project.correlation_id}, \
        "API-raised events and job events of one project share one correlation id"


def test_the_moodboard_reading_emits_element_identity_resolved(client):  # noqa: F811
    from app.intelligence.schema import SceneReading
    from app.jobs.handlers import scene_plan

    class CheckingReader(Reader):
        """Its second look at each crop agrees with its first reading, so the
        rows are trusted through the ordinary check, not by a test override."""

        def check_element_crop(self, crop, room_type, vertical) -> dict:
            for slug, sem in (("sofa", "sofa"), ("bar_stool", "bar_stool"), ("side_table", "side_table")):
                if slug in crop.name:
                    return {"sees": sem.replace("_", " "), "semantic_type": sem,
                            "certain": True, "fills_frame": True}
            return {}

    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    try:
        scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
        first = _typed(get_job_store().list_events(pid), "element.identity.resolved")
        # nothing is trusted until checked or approved: zero is the true answer
        assert len(first) == 1 and first[0].payload["definitions"] == 0 and first[0].entity_ids == []
        scene_plan._read_scene(ctx, analysis, style, CheckingReader(), force=True)
    finally:
        ctx.close()
    ev = _typed(get_job_store().list_events(pid), "element.identity.resolved")
    assert len(ev) == 2
    reading = SceneReading.model_validate(ctx.read_json("planning/scene_reading.json"))
    assert len(reading.definitions) == 3, "three checked pieces, three identities"
    assert ev[-1].entity_ids == [d.element_id for d in reading.definitions]
    assert ev[-1].payload["instances"] == len(reading.instances)
    assert ev[-1].evidence_refs == ["planning/scene_reading.json"]


def test_generation_emits_requested_generated_failed_and_reused(client, monkeypatch):  # noqa: F811
    from app.jobs.handlers import generate_elements as gen
    from app.jobs.handlers import scene_plan
    from app.providers import meshy

    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    _approve_all(ctx)
    calls = _fake_vendor(monkeypatch)
    real_wait = meshy.wait_for
    seen: list[str] = []

    async def first_fails(client_, task_id, **kw):
        seen.append(task_id)
        if len(seen) == 1:
            raise meshy.MeshyTaskFailed(f"task {task_id} ended as FAILED")
        return await real_wait(client_, task_id, **kw)

    monkeypatch.setattr(meshy, "wait_for", first_fails)
    try:
        first = gen.generate_elements(ctx)
    finally:
        ctx.close()
    events = get_job_store().list_events(pid, limit=1000)
    requested = _typed(events, "asset.requested")
    assert len(requested) == calls["submit"] == 3
    assert all(e.payload["resumed"] is False and e.evidence_refs for e in requested)
    assert len(_typed(events, "asset.failed")) == 1 and _typed(events, "asset.failed")[0].severity == "warning"
    generated = _typed(events, "asset.generated")
    assert len(generated) == len(first["made"]) == 2
    assert all(e.payload["asset_id"] in e.entity_ids for e in generated)

    # a second run reuses the two bought meshes and asks again only for the failed one
    _reset_singletons()
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type="generate_elements", lane="ai")
    ctx2 = JobContext(job, projects.get(pid), jobs, projects)
    monkeypatch.setattr(meshy, "wait_for", real_wait)
    try:
        gen.generate_elements(ctx2)
    finally:
        ctx2.close()
    run2 = get_job_store().list_job_events(job.job_id)
    assert len(_typed(run2, "asset.reused")) == 2
    assert all(e.payload["credits"] == 0 for e in _typed(run2, "asset.reused"))
    assert len(_typed(run2, "asset.requested")) == 1


def test_a_build_emits_render_generated_with_its_evidence(client, monkeypatch):  # noqa: F811
    """Blender is faked at the handler's boundary: the fake writes the three
    files a real build writes, so this is the handler's own code path."""
    from app.jobs import get_runner
    from app.jobs.handlers import build as build_mod
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)

    class FakeBlender:
        blender_path = "fake-blender"

        def run(self, script, args, log_path, timeout):
            root = Path(args[1]).parent.parent
            (root / "blender" / "scene.blend").write_bytes(b"BLENDER")
            (root / "blender" / "validation_report.json").write_text(
                json.dumps({"ok": True, "errors": [], "warnings": [], "counts": {}}), "utf-8")
            (root / "previews").mkdir(exist_ok=True)
            (root / "previews" / "build_preview.png").write_bytes(b"\x89PNG")
            return SimpleNamespace(result={"objects": 1, "stages": {}}, duration_s=0.1)

    monkeypatch.setattr(build_mod, "BlenderRunner", FakeBlender)
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type="build", lane="render")
    ctx = JobContext(job, projects.get(pid), jobs, projects)
    try:
        build_mod.build(ctx)
    finally:
        ctx.close()
    ev = _typed(jobs.list_job_events(job.job_id), "render.generated")
    assert len(ev) == 1
    assert ev[0].evidence_refs == [build_mod.PREVIEW, build_mod.REPORT, build_mod.MANIFEST]
    manifest = json.loads(ctx.path(build_mod.MANIFEST).read_text("utf-8"))
    assert {o["id"] for o in manifest["objects"]} <= set(ev[0].entity_ids)
    assert ev[0].severity == "info" and ev[0].payload["validation_ok"] is True


# ── P1-EVENT-003: immutability and idempotent consumption ─────────────────


def test_the_database_refuses_update_and_delete_on_events(env):
    project = _project()
    e = get_job_store().add_event(project.project_id, "s", "progress", "original")
    db = get_db()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE events SET message = 'rewritten' WHERE event_id = ?", (e.event_id,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM events WHERE event_id = ?", (e.event_id,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM events")
    assert get_job_store().get_event(e.event_id).message == "original"


def test_no_code_path_updates_or_deletes_events():
    """The contract test: nothing in the application even tries."""
    offenders = []
    pattern = re.compile(r"(UPDATE\s+events\b|DELETE\s+FROM\s+events\b|DELETE\s+FROM\s+\{table\})", re.I)
    for path in APP.rglob("*.py"):
        text = path.read_text("utf-8")
        for m in pattern.finditer(text):
            if "{table}" in m.group(0):
                # the one generic delete: prove its table list excludes events
                block = text[max(0, m.start() - 600):m.start()]
                tables = re.findall(r"for table in \(([^)]*)\)", block, re.S)
                if tables and '"events"' in tables[-1]:
                    offenders.append(f"{path.name}: events in the generic delete list")
            else:
                offenders.append(f"{path.name}: {m.group(0)}")
    assert offenders == []


def test_a_correction_is_two_rows_not_one_edited_row(env):
    project = _project()
    jobs = get_job_store()
    wrong = jobs.add_event(project.project_id, "plan.repair", "progress", "0 violations",
                           event_type="validation.passed", severity="info", entity_ids=["obj_1"])
    fixed = jobs.correct_event(wrong, "2 violations were missed: re-validated", severity="warning",
                               payload={"violation_count": 2})
    rows = jobs.list_events(project.project_id)
    assert [r.event_id for r in rows] == [wrong.event_id, fixed.event_id]
    assert rows[0].message == "0 violations", "the original is untouched"
    assert fixed.parent_event_id == wrong.event_id
    assert fixed.event_type == "validation.passed.corrected" and fixed.entity_ids == ["obj_1"]


def test_replaying_a_batch_produces_no_duplicated_side_effects(env):
    project = _project()
    jobs = get_job_store()
    for i in range(5):
        jobs.add_event(project.project_id, "s", "progress", f"e{i}", event_type="asset.generated")
    batch = jobs.list_events(project.project_id)
    effects: list[int] = []

    assert jobs.consume("watcher", batch, lambda e: effects.append(e.event_id)) == 5
    assert jobs.consume("watcher", batch, lambda e: effects.append(e.event_id)) == 0
    _reset_singletons()                                   # and across a restart
    assert get_job_store().consume("watcher", batch, lambda e: effects.append(e.event_id)) == 0
    assert effects == [e.event_id for e in batch], "each event acted on exactly once"

    # a separate consumer is a separate obligation
    other: list[int] = []
    assert get_job_store().consume("validator", batch, lambda e: other.append(e.event_id)) == 5


def test_a_consumer_that_raises_is_retried_not_marked_done(env):
    project = _project()
    jobs = get_job_store()
    e = jobs.add_event(project.project_id, "s", "progress")
    with pytest.raises(RuntimeError):
        jobs.consume("flaky", [e], lambda _: (_ for _ in ()).throw(RuntimeError("down")))
    done: list[int] = []
    assert jobs.consume("flaky", [e], lambda ev: done.append(ev.event_id)) == 1 and done == [e.event_id]


def test_deleting_a_project_keeps_its_events(client):  # noqa: F811
    pid = client.post("/api/projects", json={"name": "to delete"}).json()["project"]["project_id"]
    before = get_job_store().list_events(pid)
    assert before, "project.created was recorded"
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200, r.text
    assert [e.event_id for e in get_job_store().list_events(pid)] == [e.event_id for e in before]


def test_the_run_stream_is_queryable_by_correlation_id(env):
    a, b = _project("A"), _project("B")
    jobs = get_job_store()
    jobs.add_event(a.project_id, "s", "progress")
    jobs.add_event(b.project_id, "s", "progress")
    jobs.add_event(a.project_id, "t", "progress")
    run = jobs.list_run_events(a.correlation_id)
    assert [e.stage for e in run] == ["s", "t"] and {e.project_id for e in run} == {a.project_id}

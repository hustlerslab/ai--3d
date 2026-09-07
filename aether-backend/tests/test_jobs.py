"""Job runner: lanes, events, retry from checkpoint, restart recovery."""
from __future__ import annotations

import json
import threading

from app.jobs import (
    JobContext,
    JobLane,
    JobRunner,
    JobStatus,
    get_job_store,
    register,
)
from app.jobs.registry import unregister
from app.projects import ProjectStage, get_project_store
from app.projects.layout import project_dir


def _project():
    return get_project_store().create(name="Test flat")


def test_noop_job_runs_and_emits_events(env):
    project = _project()
    runner = JobRunner()
    job = runner.enqueue(project.project_id, "noop", {"steps": 2, "sleep": 0})
    assert runner.wait_idle(10)

    store = get_job_store()
    done = store.get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED
    assert done.attempt == 1
    assert done.result["steps"] == 2
    assert done.log_path.endswith(f"{job.job_id}.log")

    statuses = [e.status for e in store.list_events(project.project_id)]
    assert statuses[0] == "queued"
    assert "started" in statuses and "succeeded" in statuses
    assert statuses[-1] == "succeeded"

    # checkpoint files landed in the project layout
    root = project_dir(project.project_id)
    assert (root / "logs" / "noop_step_1.json").exists()
    assert (root / "logs" / "noop_step_2.json").exists()
    runner.shutdown()


def test_events_feed_is_incremental(env):
    project = _project()
    runner = JobRunner()
    runner.enqueue(project.project_id, "noop", {"steps": 1, "sleep": 0})
    assert runner.wait_idle(10)
    store = get_job_store()
    first = store.list_events(project.project_id)
    assert len(first) >= 3
    later = store.list_events(project.project_id, after=first[-1].event_id)
    assert later == []
    runner.shutdown()


def test_retry_resumes_from_checkpoint(env):
    """Attempt 1 completes step 1, fails on step 2. Attempt 2 must skip
    step 1 (checkpoint present) and finish."""
    project = _project()
    runner = JobRunner(retry_delay=0.01)
    job = runner.enqueue(project.project_id, "noop", {"steps": 2, "sleep": 0, "fail_until": 2})
    assert runner.wait_idle(10)

    store = get_job_store()
    done = store.get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED
    assert done.attempt == 2
    events = store.list_job_events(job.job_id)
    statuses = [e.status for e in events]
    assert "retrying" in statuses
    skipped = [e for e in events if "skipped" in e.message]
    assert len(skipped) == 1 and skipped[0].stage == "noop.step1"
    # step 1 was written exactly once, by attempt 1
    step1 = json.loads((project_dir(project.project_id) / "logs" / "noop_step_1.json").read_text())
    assert step1["attempt"] == 1
    runner.shutdown()


def test_job_fails_after_max_attempts(env):
    project = _project()
    runner = JobRunner(retry_delay=0.01)
    job = runner.enqueue(project.project_id, "noop", {"steps": 1, "sleep": 0, "fail_until": 99})
    assert runner.wait_idle(10)
    done = get_job_store().get(job.job_id)
    assert done.status == JobStatus.FAILED
    assert done.attempt == 3
    assert "simulated failure" in done.error
    assert get_project_store().get(project.project_id).stage == ProjectStage.FAILED
    runner.shutdown()


def test_restart_resumes_inflight_jobs(env):
    """Simulate a crash: a job row left RUNNING with a checkpoint on disk.
    A fresh runner must pick it up, log 'resumed', and finish it."""
    project = _project()
    store = get_job_store()
    job = store.create(project.project_id, "noop", JobLane.ai, {"steps": 2, "sleep": 0}, max_attempts=3)
    store.update(job.job_id, status=JobStatus.RUNNING, attempt=1, checkpoint="logs/noop_step_1.json")
    root = project_dir(project.project_id, create=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "noop_step_1.json").write_text('{"step": 1, "attempt": 1}')

    runner = JobRunner()
    assert runner.start() == 1
    assert runner.wait_idle(10)
    done = store.get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED
    assert done.attempt == 2
    statuses = [e.status for e in store.list_job_events(job.job_id)]
    assert statuses[0] == "resumed"
    runner.shutdown()


def test_lanes_and_stage_transitions(env):
    """A render-lane handler runs on the render thread and moves the
    project through stage_running → stage_done."""
    seen: dict[str, str] = {}

    @register(
        "test_render",
        lane=JobLane.render,
        stage_running=ProjectStage.SCENE_BUILDING,
        stage_done=ProjectStage.SCENE_VALIDATING,
    )
    def _handler(ctx: JobContext) -> dict:
        seen["thread"] = threading.current_thread().name
        seen["stage_during"] = get_project_store().get(ctx.project_id).stage.value
        return {"ok": True}

    try:
        project = _project()
        runner = JobRunner()
        runner.enqueue(project.project_id, "test_render")
        assert runner.wait_idle(10)
        assert seen["thread"].startswith("aether-render")
        assert seen["stage_during"] == "SCENE_BUILDING"
        assert get_project_store().get(project.project_id).stage == ProjectStage.SCENE_VALIDATING
        runner.shutdown()
    finally:
        unregister("test_render")

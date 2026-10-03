"""P1-VALIDATOR-003 — every failure named in the one existing taxonomy.

The acceptance bar is "all 12 categories reachable from at least one REAL
failure", so every case below is produced by running the real layer that
reports it - the validator, the repair engine, the compiler, the constraint
set, the build handler, the Blender runner, the job runner - and classifying
what it actually said. Nothing is classified from a hand-written string that
the product does not itself produce.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.scene.schema import Confidence, Opening, Room, Scene, SceneObject, Wall
from app.spatial.failures import FailureCategory as FC
from app.spatial.repair_engine import repair_scene
from app.spatial.validation import validate_scene
from app.supervisor import classify
from app.supervisor.classify import Classification, ClassificationError

ROOM = Room(name="Room", type="living_room", boundary=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])


def _obj(oid, st, x, z, w=1.0, d=1.0, conf=0.7, room=ROOM):
    return SceneObject(object_id=oid, semantic_type=st, room_id=room.room_id, position=(x, 0.0, z),
                       dimensions=(w, 0.5, d), confidence=Confidence(value=conf, source="test"))


REACHED: dict[str, str] = {}


def _reach(c: Classification, how: str) -> Classification:
    REACHED.setdefault(c.category.value, how)
    return c


# ── spatial validation ─────────────────────────────────────────────────────


def test_solver_failure_from_a_real_collision():
    scene = Scene(project_id="p", rooms=[ROOM], objects=[_obj("a", "sofa", 0, 0), _obj("b", "chair", 0.2, 0)])
    hits = [v for v in validate_scene(scene) if v.code == "COLLIDES_OBJECT"]
    assert hits and hits[0].failure_category == FC.SOLVER_FAILURE.value
    c = _reach(classify.from_violation(hits[0]), "validate_scene: COLLIDES_OBJECT")
    assert c.origin == "architecture" and set(c.entity_ids) == {"a", "b"}


def test_representation_failure_from_a_real_dangling_room_reference():
    stray = _obj("x", "chair", 0, 0).model_copy(update={"room_id": "room_missing"})
    scene = Scene(project_id="p", rooms=[ROOM], objects=[stray])
    v = next(v for v in validate_scene(scene) if v.code == "ROOM_NOT_FOUND")
    assert _reach(classify.from_violation(v), "validate_scene: ROOM_NOT_FOUND").category is FC.REPRESENTATION_FAILURE


def test_geometry_failure_from_a_real_degenerate_room():
    flat = Room(name="Flat", type="living_room", boundary=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)])
    v = next(v for v in validate_scene(Scene(project_id="p", rooms=[flat])) if v.code == "INVALID_ROOM_POLYGON")
    assert _reach(classify.from_violation(v), "validate_scene: INVALID_ROOM_POLYGON").category is FC.GEOMETRY_FAILURE


# ── repair engine ──────────────────────────────────────────────────────────


def _terminal_scenes():
    tiny = Room(name="Tiny", type="other", boundary=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)])
    return {
        "impossible": Scene(project_id="p", rooms=[tiny], objects=[
            _obj("a", "sofa", 0, 0, conf=0.9, room=tiny), _obj("b", "coffee_table", 0, 0, conf=0.3, room=tiny)]),
        "duplicate": Scene(project_id="p", rooms=[ROOM], objects=[
            _obj("a", "tv_unit", 0, 0, w=1.0, d=0.5), _obj("b", "tv_unit", 0.02, 0, w=1.0, d=0.5, conf=0.65)]),
    }


def test_repair_terminal_states_are_classified_from_real_runs():
    got = {}
    for name, scene in _terminal_scenes().items():
        r = repair_scene(scene)
        got[name] = (r.terminal_state, r.failure_category)
        c = classify.from_repair(r.terminal_state, hard_after=r.hard_after)
        _reach(c, f"repair_scene({name}) -> {r.terminal_state}")
    assert got["duplicate"] == ("UPSTREAM_REQUIRED", FC.PERCEPTION_FAILURE.value), \
        "a duplicate the READING produced is a perception failure - repair must not be asked again"
    assert got["impossible"][1] in (FC.CANDIDATE_VOCABULARY_FAILURE.value, FC.REPAIR_FAILURE.value)

    assert got["impossible"][0] == "UNREPAIRABLE"


def test_repair_that_moves_something_and_still_fails_escalates_as_a_repair_failure():
    """A repairable collision beside a duplicate pair the reading produced:
    repair moves the table (MOVED) and must leave the duplicates alone, so it
    ends having acted and still invalid -> ESCALATE."""
    scene = Scene(project_id="p", rooms=[ROOM], objects=[
        _obj("a", "sofa", 0, 0, conf=0.9), _obj("b", "coffee_table", 0.1, 0, w=0.5, d=0.5, conf=0.4),
        _obj("t1", "tv_unit", 3, 3, w=1.0, d=0.5), _obj("t2", "tv_unit", 3.02, 3, w=1.0, d=0.5, conf=0.65)])
    r = repair_scene(scene)
    assert r.terminal_state == "ESCALATE" and any(x.outcome == "MOVED" for x in r.records)
    assert r.failure_category == FC.REPAIR_FAILURE.value
    _reach(classify.from_repair(r.terminal_state, hard_after=r.hard_after), "repair_scene(collision + duplicate) -> ESCALATE")


def test_a_repair_that_runs_out_of_budget_is_hardware_never_a_model_failure():
    scene = Scene(project_id="p", rooms=[ROOM], objects=[_obj("a", "sofa", 0, 0, conf=0.9),
                                                        _obj("b", "chair", 0.1, 0, conf=0.3),
                                                        _obj("c", "chair", -0.1, 0.1, conf=0.3)])
    r = repair_scene(scene, max_iterations=1)
    assert r.terminal_state == "TIMEOUT"
    c = _reach(classify.from_repair(r.terminal_state), "repair_scene(max_iterations=1) -> TIMEOUT")
    assert c.category is FC.HARDWARE_FAILURE and c.origin == "hardware"


def test_a_successful_repair_is_not_a_failure():
    assert classify.from_repair("REPAIRED") is None and classify.from_repair("ALREADY_VALID") is None


# ── compiler ───────────────────────────────────────────────────────────────


def test_compiler_warnings_from_real_place_objects(env):
    from app.intelligence.mock_provider import MockProvider
    from app.intelligence.schema import InputBundle, ObjectPlanItem
    from app.planning import compile_scene, place_objects, resolve_plan
    from tests.test_scene_plan import BRIEF, _analysis, _style

    analysis = _analysis()
    style = _style(analysis)
    scene, _ = compile_scene("proj_x", analysis, style, name="classify")
    plan = MockProvider().plan_objects(analysis, style, InputBundle(project_id="p", description=BRIEF))
    room_id = scene.rooms[0].room_id
    plan.items += [
        ObjectPlanItem(object_key="ghost.chair.0", semantic_type="chair", room_id="room_that_is_not_here",
                       priority=3, count=1),
        ObjectPlanItem(object_key="crowd.bed.0", semantic_type="bed", room_id=room_id, priority=3, count=12),
        ObjectPlanItem(object_key="stools.0", semantic_type="bar_stool", room_id=room_id, priority=3, count=4,
                       element_id="cel_stool"),
    ]
    assets = resolve_plan(plan, style)
    assets.decisions = [d for d in assets.decisions if d.object_key != plan.items[0].object_key]
    reading = SimpleNamespace(elements=[SimpleNamespace(element_id="cel_stool")] * 2)
    _, warnings = place_objects(scene, plan, assets, reading=reading)

    by_cat = {}
    for w in warnings:
        c = classify.from_compiler_warning(w)
        by_cat.setdefault(c.category, []).append(w)
        _reach(c, f"place_objects: {w[:70]}")
    assert FC.REPRESENTATION_FAILURE in by_cat, warnings          # room not in scene
    assert FC.CANDIDATE_VOCABULARY_FAILURE in by_cat, warnings    # 12 beds do not fit
    assert FC.PERCEPTION_FAILURE in by_cat, warnings              # plan 4 vs read 2
    assert FC.ASSET_FAILURE in by_cat, warnings                   # no asset decision
    assert FC.UNKNOWN not in by_cat, f"a compiler warning format is unmapped: {by_cat.get(FC.UNKNOWN)}"


def test_constraint_failure_from_a_real_mis_compiled_constraint():
    from app.planning.constraint_model import Constraint, ConstraintSet, ConstraintType

    cs = ConstraintSet(constraints=(
        Constraint(constraint_id="c1", constraint_type=ConstraintType.CONTACT, subject_id="sofa.0",
                   target_id="wall_north"),
        Constraint(constraint_id="c2", constraint_type=ConstraintType.ORIENTATION, subject_id="armchair.9",
                   target_id="sofa.0"),
    ))
    found = classify.from_constraints(cs, plan_keys={"sofa.0", "wall_north"})
    assert [c.code for c in found] == ["c2"]
    assert _reach(found[0], "constraint names a subject the plan lacks").category is FC.CONSTRAINT_FAILURE


# ── build, Blender and the job runner ──────────────────────────────────────


def test_a_build_with_no_validation_report_is_a_validation_failure(client, monkeypatch):  # noqa: F811
    from app.jobs import JobContext, get_job_store, get_runner
    from app.jobs.handlers import build as build_mod
    from app.projects import get_project_store
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)

    class BlenderWithoutReport:
        blender_path = "fake"

        def run(self, script, args, log_path, timeout):
            (Path(args[1]).parent / "scene.blend").write_bytes(b"B")
            return SimpleNamespace(result={"stages": {}}, duration_s=0.1)

    monkeypatch.setattr(build_mod, "BlenderRunner", BlenderWithoutReport)
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type="build", lane="render")
    ctx = JobContext(job, projects.get(pid), jobs, projects)
    try:
        build_mod.build(ctx)
    finally:
        ctx.close()
    ev = [e for e in jobs.list_job_events(job.job_id) if e.event_type == "validation.failed"]
    assert len(ev) == 1 and ev[0].payload["failure_category"] == FC.VALIDATION_FAILURE.value
    REACHED.setdefault(FC.VALIDATION_FAILURE.value, "build: no validation report")


def test_blender_not_configured_is_an_execution_failure(env):
    from app.blender import BlenderRunner
    from app.blender.runner import BlenderError

    with pytest.raises(BlenderError) as info:
        BlenderRunner().run("build_scene.py", [])
    c = _reach(classify.from_exception(info.value, job_type="build"), f"BlenderRunner: {type(info.value).__name__}")
    assert c.category is FC.BLENDER_EXECUTION_FAILURE


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import sign_in_admin

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _failing_job(exc_factory, type_name):
    from app.jobs import JobLane, JobRunner, get_job_store, register
    from app.jobs.registry import unregister
    from app.projects import get_project_store

    @register(type_name, lane=JobLane.ai, max_attempts=1)
    def boom(ctx):
        raise exc_factory()

    try:
        pid = get_project_store().create(name=type_name).project_id
        runner = JobRunner()
        job = runner.enqueue(pid, type_name)
        assert runner.wait_idle(10)
        runner.shutdown()
    finally:
        unregister(type_name)
    return next(e for e in get_job_store().list_job_events(job.job_id) if e.event_type == "job.failed")


def test_a_real_model_output_error_fails_a_job_as_perception(env, monkeypatch):
    import httpx

    from app.intelligence.gemini_provider import GeminiError, GeminiProvider

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.core import config

    config.get_settings.cache_clear()

    def garbage(request):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json {"}]}}]})

    provider = GeminiProvider(transport=httpx.MockTransport(garbage))
    with pytest.raises(GeminiError) as info:
        provider._generate([{"text": "x"}], {"type": "object"}, "analyze_input")
    real = info.value
    ev = _failing_job(lambda: real, "fails_perception")
    assert ev.payload["failure_category"] == FC.PERCEPTION_FAILURE.value and ev.payload["failure_origin"] == "model"
    REACHED.setdefault(FC.PERCEPTION_FAILURE.value, "job.failed: GeminiError (invalid JSON after repair)")


def test_a_model_call_that_times_out_is_hardware_not_perception(env, monkeypatch):
    """P10: a hardware (latency) limitation is never relabelled a model failure."""
    import httpx

    from app.intelligence.gemini_provider import GeminiError, GeminiProvider

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.core import config

    config.get_settings.cache_clear()

    def slow(request):
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(GeminiError) as info:
        GeminiProvider(transport=httpx.MockTransport(slow))._generate([{"text": "x"}], {"type": "object"}, "s")
    c = classify.from_exception(info.value)
    assert c.category is FC.HARDWARE_FAILURE, (c, str(info.value))


def test_a_vendor_ended_mesh_is_an_asset_failure(env):
    from app.providers import meshy

    ev = _failing_job(lambda: meshy.MeshyTaskFailed("task t1 ended as FAILED: mesh generation failed"),
                      "fails_asset")
    assert ev.payload["failure_category"] == FC.ASSET_FAILURE.value
    REACHED.setdefault(FC.ASSET_FAILURE.value, "job.failed: MeshyTaskFailed")


def test_an_unrecognised_failure_abstains_and_is_still_a_failure(env):
    ev = _failing_job(lambda: KeyError("scene_id"), "fails_unknown")
    assert ev.payload["failure_category"] == FC.UNKNOWN.value
    assert ev.event_type == "job.failed" and ev.severity == "error", \
        "UNKNOWN is a correct abstention, never 'no problem': the job still failed, loudly"
    c = classify.from_exception(KeyError("x"))
    assert c.abstained and not c.is_code_defect
    REACHED.setdefault(FC.UNKNOWN.value, "job.failed: KeyError")


# ── the three P10 rules, structurally ──────────────────────────────────────


@pytest.mark.parametrize("category, origin", [
    (FC.GEOMETRY_FAILURE, "model"),            # a model error relabelled an architecture error
    (FC.SOLVER_FAILURE, "model"),
    (FC.PERCEPTION_FAILURE, "architecture"),   # an architecture error relabelled a model error
    (FC.PERCEPTION_FAILURE, "hardware"),       # a hardware limitation relabelled a model failure
    (FC.HARDWARE_FAILURE, "model"),
])
def test_a_p10_violation_cannot_be_constructed(category, origin):
    with pytest.raises(ClassificationError):
        Classification(category, origin, "x", "x", "x")


def test_the_enum_is_unchanged():
    assert [c.value for c in FC] == [
        "perception_failure", "geometry_failure", "representation_failure", "constraint_failure",
        "candidate_vocabulary_failure", "solver_failure", "repair_failure", "validation_failure",
        "asset_failure", "blender_execution_failure", "hardware_failure", "unknown"]


def test_zz_all_twelve_categories_are_reachable_from_real_failures():
    """Runs last (zz): the coverage report of what the tests above reached."""
    out = Path(__file__).resolve().parents[2] / "version 4" / "evidence" / "P1-VALIDATOR-003"
    out.mkdir(parents=True, exist_ok=True)
    report = {c.value: REACHED.get(c.value, "NOT REACHED") for c in FC}
    (out / "category_coverage.json").write_text(json.dumps(report, indent=2), "utf-8")
    missing = [k for k, v in report.items() if v == "NOT REACHED"]
    assert missing == [], f"unreached categories: {missing}"

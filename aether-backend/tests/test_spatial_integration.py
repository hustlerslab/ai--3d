"""Phase 11 — Spatial Engine integration (P1-SPATIAL-001 · 002)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_asset_rebind import _project_with_render, client  # noqa: F401
from tests.test_element_first import _fresh_ctx, _plan_with

from app.jobs import get_job_store, get_runner
from app.projects import get_project_store
from app.projects.layout import project_dir
from app.scene.store import get_store
from app.spatial.validation import validate_scene

EVIDENCE = Path(__file__).resolve().parents[2] / "version 4" / "evidence" / "P1-SPATIAL"


def _scene(pid):
    return get_store().load(get_project_store().get(pid).scene_ids[-1])


def _golden(client):  # noqa: F811
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)
    return pid


# ── P1-SPATIAL-001 ─────────────────────────────────────────────────────────


def test_every_committed_object_has_explicit_identity_and_valid_geometry(client):  # noqa: F811
    pid = _golden(client)
    scene = _scene(pid)
    assert [v for v in validate_scene(scene) if v.severity == "hard"] == []
    report = []
    for o in scene.objects:
        assert o.identity_source in ("element", "planner")
        assert (o.identity_source == "element") == bool(o.element_id), o
        report.append({"object_id": o.object_id, "name": o.name or o.semantic_type, "room_id": o.room_id,
                       "identity_source": o.identity_source, "element_id": o.element_id,
                       "instance_id": o.instance_id, "asset_id": o.asset_id,
                       "hard_violations": [v.code for v in validate_scene(scene)
                                           if v.object_id == o.object_id and v.severity == "hard"]})
    assert all(r["hard_violations"] == [] for r in report)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "golden_identity_validity_report.json").write_text(json.dumps({
        "project_id": pid, "scene_version": scene.version, "objects": len(report),
        "identity_source": {s: sum(1 for r in report if r["identity_source"] == s) for s in ("element", "planner")},
        "hard_violations": 0, "rows": report}, indent=2), "utf-8")


def test_moodboard_driven_objects_carry_their_element_id(client, monkeypatch):  # noqa: F811
    pid, ctx = _project_with_render(client)
    _plan_with(ctx, monkeypatch, force=False)
    scene = _scene(pid)
    from_reading = [o for o in scene.objects if o.identity_source == "element"]
    assert from_reading and all(o.element_id and o.instance_id for o in from_reading)
    assert [v for v in validate_scene(scene) if v.severity == "hard"] == []


def test_legacy_objects_load_with_an_explicit_identity_source():
    from app.scene.schema import SceneObject

    o = SceneObject.model_validate({"object_id": "o", "semantic_type": "sofa", "room_id": "r",
                                    "position": [0, 0, 0], "dimensions": [1, 1, 1]})
    assert o.identity_source == "planner"
    o = SceneObject.model_validate({"object_id": "o", "semantic_type": "sofa", "room_id": "r", "element_id": "el_x",
                                    "position": [0, 0, 0], "dimensions": [1, 1, 1]})
    assert o.identity_source == "element"
    with pytest.raises(ValueError):
        SceneObject(object_id="o", semantic_type="sofa", room_id="r", position=(0, 0, 0), dimensions=(1, 1, 1),
                    identity_source="element")


def test_repair_preserves_identity_dimensions_and_asset_binding(client):  # noqa: F811
    from tests.test_orchestrator import _inject_collision, _run

    pid = _golden(client)
    before = {o.object_id: o for o in _scene(pid).objects}
    _inject_collision(pid)
    _run(pid, "check_scene")
    assert get_runner().wait_idle(120)
    after = _scene(pid)
    assert after.version > 2, "the repair committed"
    for o in after.objects:
        b = before[o.object_id]
        # identity, binding and SIZE - dimensions and scale both: a rescale
        # changes a piece's real size as surely as new dimensions would
        assert (o.element_id, o.instance_id, o.asset_id, tuple(o.dimensions), tuple(o.scale),
                o.identity_source, o.semantic_type) == \
            (b.element_id, b.instance_id, b.asset_id, tuple(b.dimensions), tuple(b.scale),
             b.identity_source, b.semantic_type), o.object_id
    assert [v for v in validate_scene(after) if v.severity == "hard"] == []


def _crowded(client):  # noqa: F811
    """A real plan asked to fit twelve beds into one room."""
    from app.intelligence.mock_provider import MockProvider
    from app.intelligence.schema import ObjectPlanItem
    from app.jobs.handlers import scene_plan

    pid = _golden(client)
    root = project_dir(pid)
    plan = json.loads((root / "planning" / "object_plan.json").read_text("utf-8"))
    room_id = plan["items"][0]["room_id"]
    plan["items"].append(ObjectPlanItem(object_key=f"{room_id}.bed.9", semantic_type="bed", room_id=room_id,
                                        name="walnut bed", priority=3, count=12).model_dump(mode="json"))
    (root / "planning" / "object_plan.json").write_text(json.dumps(plan), "utf-8")
    for rel in ("planning/asset_plan.json", "planning/scene_spec.json"):
        (root / rel).unlink(missing_ok=True)
    job = get_runner().enqueue(pid, "scene_plan", {})
    assert get_runner().wait_idle(120)
    assert MockProvider and scene_plan
    return pid, get_job_store().get(job.job_id)


def test_an_unplaceable_item_is_named_with_room_and_priority_never_dropped_silently(client):  # noqa: F811
    pid, job = _crowded(client)
    named = [w for w in job.result["warnings"] if "no valid position" in w]
    assert named and all("for walnut bed in " in w and "(priority 3)" in w for w in named), named
    events = get_job_store().list_job_events(job.job_id)
    failed = [e for e in events if e.event_type == "validation.failed" and "walnut bed" in e.message]
    assert failed and failed[0].payload["failure_category"] == "candidate_vocabulary_failure"
    solved = next(e for e in events if e.event_type == "spatial.solve.completed")
    assert solved.payload["unplaced"] >= 1 and solved.payload["placed"] > 0
    assert any(k.endswith(".bed.9") for k in solved.payload["unplaced_keys"]) and solved.entity_ids


def test_the_measured_constants_are_unchanged():
    from app.spatial import clearance_engine, repair_engine, validation

    assert clearance_engine.PRIMARY_WALKWAY_MIN_M == 0.90
    assert validation.DOOR_CLEARANCE_DEPTH == 0.75
    assert validation.BOUNDARY_TOLERANCE == 0.09
    assert repair_engine.MAX_ITERATIONS == 20


# ── P1-SPATIAL-002 ─────────────────────────────────────────────────────────


def test_a_trade_off_is_a_plain_statement_with_at_least_two_options(client):  # noqa: F811
    from app.planning.tradeoffs import FORBIDDEN

    pid, _ = _crowded(client)
    data = client.get(f"/api/projects/{pid}/tradeoffs").json()["data"]["tradeoffs"]
    assert data, "the over-constrained room produced a trade-off"
    t = data[0]
    assert "walnut bed" in t["statement"] and t["room"] in t["statement"].title() or t["room"].lower() in t["statement"]
    assert len(t["options"]) >= 2
    for text in [t["statement"]] + [o["label"] for o in t["options"]]:
        assert not FORBIDDEN.search(text), f"an internal code leaked into: {text!r}"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "tradeoffs_over_constrained_room.json").write_text(json.dumps(data, indent=2), "utf-8")


@pytest.mark.parametrize("warning, piece, kind", [
    ("living_room.sofa.1: no valid position for grey sofa in Living Room (priority 2)", "grey sofa", "doesnt_fit"),
    ("living_room.sofa.1: no valid position in Living Room (priority 2)", "sofa", "doesnt_fit"),  # pre-rename text
    ("bedroom.table_lamp.0: no surface in Bedroom to rest brass lamp on; skipped", "brass lamp", "nothing_to_rest_on"),
])
def test_warnings_translate_without_leaking_identifiers(warning, piece, kind):
    from app.planning.tradeoffs import FORBIDDEN, explain

    [t] = explain([warning])
    assert t.kind == kind and t.pieces == [piece] and len(t.options) >= 2
    for text in [t.statement] + [o.label for o in t.options]:
        assert not FORBIDDEN.search(text), text


def test_two_pieces_that_do_not_both_fit_are_named_together():
    from app.planning.tradeoffs import explain

    [t] = explain(["lr.sofa.0: no valid position for grey sofa in Living Room (priority 1)",
                   "lr.armchair.0: no valid position for velvet armchair in Living Room (priority 2)",
                   "some unrelated warning"])
    assert t.statement.startswith("The grey sofa and the velvet armchair don't fit in the living room")
    assert t.pieces == ["grey sofa", "velvet armchair"]

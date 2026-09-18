"""The glue between `place_objects` and the migrated spatial engine
(app/planning/spatial_pipeline.py), exercised on the deterministic mock brief
path - no LLM, no GPU, no Blender.
"""
from __future__ import annotations

import json

from app.intelligence.bundle import InputBundle
from app.intelligence.mock_provider import MockProvider
from app.intelligence.schema import Vertical
from app.planning import compile_scene, place_objects, resolve_plan
from app.planning.spatial_pipeline import (RELATION_TO_PREDICATE, UNSUPPORTED_REASONS, derive_intents,
                                           repair_placement, spatial_check)
from app.scene.patches import AddObjectOp
from app.spatial.validation import validate_scene

BRIEF = "A two bedroom flat: living room with sofa facing the TV, dining table, master bedroom, kids room."


def _solve():
    bundle = InputBundle(project_id="t_pipeline", description=BRIEF, vertical=Vertical.RESIDENTIAL)
    mock = MockProvider()
    analysis = mock.analyze_input(bundle)
    style = mock.create_style_spec(analysis, bundle)
    scene, _ = compile_scene("t_pipeline", analysis, style, name="t")
    plan = mock.plan_objects(analysis, style, bundle)
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))
    return scene, plan, ops


def test_repair_is_a_no_op_on_valid_solver_output_and_keeps_op_identity():
    scene, _plan, ops = _solve()
    out, summary = repair_placement(scene, ops)
    assert summary["terminal_state"] == "ALREADY_VALID"
    assert summary["hard_before"] == 0 and summary["hard_after"] == 0 and summary["moved"] == []
    assert all(a is b for a, b in zip(out, ops))


def test_repair_moves_only_the_colliding_object():
    scene, _plan, ops = _solve()
    floor = [op for op in ops if op.object.mount == "floor"]
    a = floor[0]
    # A different type, offset by a third of a metre: a real overlap, not the
    # same-type-same-centre pair P4 classifies as an upstream duplicate.
    b = next(op for op in floor[1:] if op.object.semantic_type != a.object.semantic_type)
    x, y, z = a.object.position
    clone = b.object.model_copy(update={"object_id": "obj_dup", "position": (x + 0.3, y, z + 0.2),
                                        "rotation_y": a.object.rotation_y})
    ops2 = ops + [AddObjectOp(object=clone)]
    tentative = scene.model_copy(update={"objects": [op.object for op in ops2]})
    assert any(v.code == "COLLIDES_OBJECT" for v in validate_scene(tentative))
    out, summary = repair_placement(scene, ops2)
    assert summary["hard_before"] >= 1
    assert summary["terminal_state"] in ("REPAIRED", "UNREPAIRABLE", "ESCALATE")
    untouched = [op for op in out if op.object.object_id not in summary["moved"]]
    assert len(untouched) >= len(ops2) - 2
    if summary["terminal_state"] == "REPAIRED":
        assert summary["hard_after"] == 0
        assert not [v for v in validate_scene(scene.model_copy(update={"objects": [op.object for op in out]}))
                    if v.severity == "hard"]


def test_intents_come_only_from_facing_and_targets_resolve_by_plan_key():
    scene, plan, ops = _solve()
    final = scene.model_copy(update={"objects": [op.object for op in ops]})
    intents, unsupported = derive_intents(final, plan)
    assert RELATION_TO_PREDICATE == {"facing": "FACES"}
    assert all(i.predicate == "FACES" for i in intents)
    ids = {o.object_id for o in final.objects}
    assert all(i.subject_id in ids for i in intents)
    assert all(i.target_id == "" or i.target_id in ids for i in intents)
    assert set(unsupported) <= set(UNSUPPORTED_REASONS)
    assert "against_wall" in unsupported  # the mock plan always emits some


def test_spatial_check_is_serializable_deterministic_and_reports_unsupported_reasons():
    scene, plan, ops = _solve()
    final = scene.model_copy(update={"objects": [op.object for op in ops]})
    _out, repair = repair_placement(scene, ops)
    a, canon_a = spatial_check(final, plan, repair)
    b, canon_b = spatial_check(final, plan, repair)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert json.dumps(canon_a, sort_keys=True) == json.dumps(canon_b, sort_keys=True)
    it = a["intent"]
    assert it["satisfied"] + it["violated"] + it["unknown"] + it["partial"] == len(it["results"])
    assert it["unsupported_reasons"]["against_wall"].startswith("P8 CONTACT verifier")
    assert a["consistency"] == []
    assert canon_a["schema_version"] == "p7.1"
    supported = [r for r in canon_a["relations"] if r["predicate"] == "SUPPORTED_BY"]
    assert len(supported) == sum(1 for o in final.objects if o.parent_id)

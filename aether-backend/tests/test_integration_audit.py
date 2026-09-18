"""Deterministic checks for integration_audit.py: the pipeline-stage
contract table and the 10 traced evidence -> decision chains. No GPU, no
models.
"""
from __future__ import annotations

from research.spatial_architecture.integration_audit import (
    PIPELINE_STAGES, get_stage, trace_ten_decisions)


def test_all_sixteen_stages_present():
    expected = {"PERCEPTION", "EVIDENCE", "ROOM_GEOMETRY", "OBJECT_GROUNDING", "RELATIONS",
               "USER_MODEL_INTENT", "CONSTRAINTS", "CANDIDATE_GENERATION", "CANDIDATE_FILTERING",
               "CANDIDATE_RANKING", "SOLVER", "VALIDATION", "REPAIR_RE_SOLVE",
               "INDEPENDENT_INTENT_EVALUATION", "SCENE", "BLENDER"}
    assert {s.stage for s in PIPELINE_STAGES} == expected


def test_get_stage_returns_none_for_unknown():
    assert get_stage("NOT_A_REAL_STAGE") is None


def test_only_solver_and_repair_may_decide_geometry():
    """The architectural invariant this table encodes: geometry is decided
    only at SOLVER and REPAIR_RE_SOLVE (and, structurally, ROOM_GEOMETRY/
    OBJECT_GROUNDING for the room/object's OWN measured shape, not another
    object's placement) - never at CANDIDATE_*, VALIDATION, or evaluation
    stages, which only propose/check."""
    deciders = {s.stage for s in PIPELINE_STAGES if s.may_decide_geometry}
    assert "SOLVER" in deciders and "REPAIR_RE_SOLVE" in deciders
    assert "CANDIDATE_FILTERING" not in deciders
    assert "CANDIDATE_RANKING" not in deciders
    assert "VALIDATION" not in deciders
    assert "INDEPENDENT_INTENT_EVALUATION" not in deciders


def test_validation_and_evaluation_never_mutate_state():
    for stage_name in ("VALIDATION", "INDEPENDENT_INTENT_EVALUATION", "CANDIDATE_FILTERING",
                      "CANDIDATE_RANKING"):
        stage = get_stage(stage_name)
        assert stage.may_mutate_state is False, stage_name


def test_trace_ten_decisions_returns_at_least_ten():
    traces = trace_ten_decisions()
    assert len(traces) >= 10


def test_every_trace_is_explainable_without_an_llm():
    for t in trace_ten_decisions():
        assert t.explainable_without_llm is True
        assert t.validation_result   # every trace ends in a real, non-empty verdict


def test_trace_names_are_unique():
    traces = trace_ten_decisions()
    names = [t.name for t in traces]
    assert len(names) == len(set(names))


def test_traces_are_deterministic_across_repeated_calls():
    """Compares CONTENT, not the `p9_brief_*` trace names - those embed a
    constraint_id derived from `place_objects`'s own pre-existing random
    `object_id` assignment (documented, out-of-scope production behaviour -
    see `candidate_benchmark.determinism_check`'s docstring for the same,
    already-established finding from P9). Every VALIDATION RESULT, which is
    this module's own responsibility, is still identical run to run."""
    a = sorted(t.validation_result for t in trace_ten_decisions())
    b = sorted(t.validation_result for t in trace_ten_decisions())
    assert a == b

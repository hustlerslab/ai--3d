"""P1-IDENTITY-006 - the golden composition's identity arithmetic, pinned.

research/p1_identity_benchmark.py produces the numbers; this file makes the
acceptance criteria fail the build if the shipped resolver drifts. It runs the
same harness functions, so the test and the benchmark cannot disagree.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "research" / "p1_identity_benchmark.py"


def _harness():
    spec = importlib.util.spec_from_file_location("p1_identity_benchmark", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                     # type: ignore[union-attr]
    return mod


def test_golden_living_room_definitions_instances_and_no_errors():
    h = _harness()
    els, truth = h.golden_living_room()
    s = h.score(els, truth)
    assert s["n_elements"] == 17 and s["n_trustworthy"] == 17
    assert s["instances"] == 17
    # 10 element kinds; the side-table row is two designs, so 11 definitions
    # (correction C10 - see the harness docstring and TRACK_RECORD.md).
    assert s["definitions"] == 11 and s["truth_groups"] == 11
    assert s["false_merges"] == 0 and s["false_splits"] == 0
    assert s["instance_count"]["accuracy"] == 1.0
    assert s["definition_sizes"] == [4, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1]


def test_three_stools_and_two_chairs_are_one_generation_each_and_the_tv_unit_none():
    h = _harness()
    els, _ = h.golden_living_room()
    from app.intelligence.scene_reading import distinct_shapes

    groups = distinct_shapes(els)
    sizes = {m[0].semantic_type: len(m) for m in groups.values()}
    assert sizes["bar_stool"] == 3 and sizes["lounge_chair"] == 2 and sizes["cushion"] == 4
    assert sum(1 for m in groups.values() if m[0].semantic_type == "side_table") == 2

    spend = h.generations(els)
    assert spend["ready_rows"] == 17 and spend["held_rows"] == 0
    assert spend["groups"] == 11
    assert spend["reused_groups"] == 1 and spend["owned_rows"] == ["tv_unit"]
    assert spend["generations"] == 10
    assert spend["instances_bound"] == 17
    assert spend["asset_reuse_rate"] == round(1 - 10 / 17, 4)


def test_two_dark_one_light_stool_is_two_definitions():
    h = _harness()
    s = h.score(*h.two_dark_one_light_stool())
    assert s["definitions"] == 2 and s["instances"] == 3
    assert s["false_merges"] == 0 and s["false_splits"] == 0


def test_television_never_merges_with_tv_unit():
    h = _harness()
    s = h.score(*h.television_is_not_tv_unit())
    assert s["definitions"] == 2 and s["false_merges"] == 0


def test_the_whole_labelled_set_has_zero_false_merges():
    """The rule the key was chosen by: never a false merge. Splits are the
    safe failure and are reported, not asserted at zero, because the real
    project's labels include pieces the resolver cannot know are the same."""
    h = _harness()
    report = h.run()
    assert report["totals"]["false_merges"] == 0
    assert report["totals"]["n_trustworthy"] >= 35, "the synthetic set alone is not small"
    real = report["cases"].get("ablation_real_project")
    if real is None:                       # CI has no data dir; the report says so
        assert report["absent_cases"] == ["ablation_real_project"]
    else:
        assert real["n_elements"] == 26 and real["n_trustworthy"] == 15 and real["n_excluded"] == 11


def test_a_rejected_row_is_excluded_not_counted_as_a_third_stool():
    h = _harness()
    s = h.score(*h.one_rejected_stool())
    assert s["n_elements"] == 3 and s["n_trustworthy"] == 2 and s["n_excluded"] == 1
    assert s["definitions"] == 1 and s["instances"] == 2
    assert s["instance_count"]["accuracy"] == 1.0

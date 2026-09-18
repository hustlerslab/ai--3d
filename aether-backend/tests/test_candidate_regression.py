"""§42: P9 must not regress anything P0-P8 built. In-process guard that P9's
imports/constants have not silently drifted anything earlier phases (or P9
itself) depend on. The frozen benchmark scripts (P0-P8) are re-run
separately as their own processes - see docs/spatial_architecture/
decisions.md's P9 entry for those results.
"""
from __future__ import annotations

from research.spatial_architecture.constraint_benchmark import brief_end_to_end_demo


def test_p8_control_brief_demo_still_zero_hard_violations_when_regenerate_is_false():
    """`regenerate=False` (the default) must still reach 0 hard violations
    and place all 5 objects - the FACES fix lives in
    `apply_constraints_to_plan`'s wiring (always active), but the P9
    candidate-regeneration step for DISTANCE/POSITION must never run
    unless explicitly requested."""
    r = brief_end_to_end_demo(regenerate=False)
    assert r["hard_violations"] == 0
    assert r["objects_placed"] == 5
    assert r["regenerated_notes"] == []


def test_p9_regenerate_improves_on_p8_without_reducing_hard_validity():
    r8 = brief_end_to_end_demo(regenerate=False)
    r9 = brief_end_to_end_demo(regenerate=True)
    assert r9["hard_violations"] == 0
    assert r8["hard_violations"] == 0
    n_satisfied_8 = sum(1 for v in r8["constraint_verdicts"].values() if v == "satisfied")
    n_satisfied_9 = sum(1 for v in r9["constraint_verdicts"].values() if v == "satisfied")
    assert n_satisfied_9 > n_satisfied_8


def test_orientation_faces_fix_does_not_depend_on_regenerate_flag():
    """The FACES fix (§8 - routing through the existing 'facing'
    RelationType) is a compile-time wiring change, not a runtime flag - it
    must fix FACES whether or not `regenerate` is requested."""
    r8 = brief_end_to_end_demo(regenerate=False)
    faces_messages = [m for m in r8["constraint_messages"].values() if "angular error" in m]
    assert faces_messages and "angular error 0.0 deg" in faces_messages[0]


def test_p0_p8_modules_still_import_cleanly_alongside_p9():
    import app.planning.constraint_compiler   # noqa: F401
    import app.planning.constraint_evaluator   # noqa: F401
    import app.planning.constraint_model       # noqa: F401
    import app.planning.intent_model           # noqa: F401
    import app.spatial.repair_engine          # noqa: F401
    import app.spatial.scene_consistency      # noqa: F401
    import app.spatial.scene_graph            # noqa: F401
    assert True

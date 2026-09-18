"""§14/§25: P10 must not regress anything P0-P9 built. In-process guard
that P10's own new modules import cleanly alongside every prior phase's
research code. The frozen benchmark scripts (P0-P9) are re-run separately
as their own processes - see docs/spatial_architecture/decisions.md's P10
entry for those results.
"""
from __future__ import annotations


def test_p0_p9_modules_still_import_cleanly_alongside_p10():
    import app.planning.candidate_filters       # noqa: F401
    import app.planning.candidate_generators    # noqa: F401
    import app.planning.candidate_model         # noqa: F401
    import app.planning.candidate_ranker        # noqa: F401
    import app.planning.constraint_compiler     # noqa: F401
    import app.planning.constraint_evaluator    # noqa: F401
    import app.planning.intent_model            # noqa: F401
    import app.spatial.repair_engine           # noqa: F401
    import app.spatial.scene_consistency       # noqa: F401
    import app.spatial.scene_graph             # noqa: F401
    import app.spatial.wall_geometry            # noqa: F401
    assert True


def test_p10_modules_import_cleanly():
    import research.spatial_architecture.authority_audit          # noqa: F401
    import research.spatial_architecture.failure_taxonomy         # noqa: F401
    import research.spatial_architecture.integration_audit        # noqa: F401
    import research.spatial_architecture.p10_integration_benchmark  # noqa: F401
    import research.spatial_architecture.production_boundary      # noqa: F401
    assert True


def test_p9_brief_demo_still_reaches_zero_hard_violations():
    """One concrete, executable regression check (not merely an import
    smoke test): P9's own headline result must still hold exactly."""
    from research.spatial_architecture.constraint_benchmark import brief_end_to_end_demo
    r = brief_end_to_end_demo(regenerate=True)
    assert r["hard_violations"] == 0
    assert r["objects_placed"] == 5


def test_p7_demonstration_scene_still_has_zero_consistency_findings():
    from app.spatial.scene_consistency import check_consistency
    from app.spatial.scene_graph import (
        build_demonstration_scene, recompute_relations)
    recomputed, _changes = recompute_relations(build_demonstration_scene())
    assert check_consistency(recomputed) == []

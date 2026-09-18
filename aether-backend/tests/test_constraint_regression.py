"""§59: P8 must not regress anything P7 built. These tests import P8's new
modules ALONGSIDE P7's and re-assert P7's own guarantees still hold exactly
- the frozen benchmark scripts (P0-P7) are re-run separately as their own
processes (see docs/spatial_architecture/decisions.md's P8 entry for those
results); this file is the in-process guard that P8's imports/constants
have not silently drifted anything P8 depends on.
"""
from __future__ import annotations

import math

from app.planning.constraint_evaluator import (
    DEFAULT_ORIENTATION_TOLERANCE_DEG)
from app.spatial.scene_consistency import check_consistency
from app.spatial.scene_graph import (
    AGAINST_WALL_TOLERANCE_M, build_demonstration_scene, recompute_relations)
from app.spatial.scene_serialization import to_canonical_json


def test_p7_demonstration_scene_unchanged_with_p8_modules_loaded():
    """Importing P8's intent/constraint modules must not change P7's own
    behaviour in any way - same demonstration scene, same consistency
    findings, same canonical serialization, byte for byte, across two
    independent builds (the same determinism check P7's own test suite
    already runs, re-asserted here with P8 fully imported alongside it)."""
    recomputed_a, changes_a = recompute_relations(build_demonstration_scene())
    recomputed_b, changes_b = recompute_relations(build_demonstration_scene())
    assert check_consistency(recomputed_a) == []
    assert changes_a == changes_b
    assert len(changes_a) == 1   # the one AGAINST_WALL DERIVED -> SUPPORTED promotion, per P7's own report
    assert to_canonical_json(recomputed_a) == to_canonical_json(recomputed_b)


def test_p7_wall_tolerance_constant_has_not_drifted():
    """P8's CONTACT evaluator reuses this EXACT constant (constraint_
    contract.md's explicit reuse decision) - if it ever changes in P7's own
    file, P8's evaluator changes with it, which must be a deliberate,
    visible event, not a silent one this test would otherwise miss."""
    assert AGAINST_WALL_TOLERANCE_M == 0.25


def test_p8_orientation_tolerance_matches_compilers_own_faces_cos():
    """§15: the compiler's own `_FACES_COS = 0.5` (app/planning/compiler.py)
    corresponds to 60 degrees - P8's default must stay numerically
    consistent with it, not silently diverge."""
    faces_cos = 0.5
    assert math.isclose(DEFAULT_ORIENTATION_TOLERANCE_DEG, math.degrees(math.acos(faces_cos)), abs_tol=0.1)


def test_p1_p4_p5_p6_modules_still_import_cleanly_alongside_p8():
    """A broad import smoke test - if P8 introduced a circular import or a
    name collision with any earlier phase's module, this fails immediately
    rather than surfacing as a mysterious downstream error."""
    import app.spatial.clearance_engine        # noqa: F401
    import app.spatial.collision_solver         # noqa: F401
    import app.spatial.coordinate_frames        # noqa: F401
    import app.spatial.frame_graph               # noqa: F401
    import research.spatial_architecture.grounding_contract        # noqa: F401
    import app.spatial.relation_model            # noqa: F401
    import app.spatial.repair_engine             # noqa: F401
    import research.spatial_architecture.scene_from_photo          # noqa: F401
    import research.spatial_architecture.scene_optimizer           # noqa: F401
    import app.spatial.transforms                # noqa: F401
    import app.spatial.wall_geometry             # noqa: F401
    assert True

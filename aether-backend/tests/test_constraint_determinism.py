"""§48: 20-repeat determinism for intent ids, constraint ids, ordering,
compilation, and evaluation. No GPU, no models.
"""
from __future__ import annotations

from research.spatial_architecture.constraint_benchmark import (
    _obj, _run, _spatial, determinism_check)
from app.planning.intent_model import Intent, IntentSource


def test_determinism_check_passes():
    assert determinism_check(runs=20) is True


def test_repeated_compilation_and_evaluation_is_byte_identical():
    signatures = set()
    for _ in range(20):
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i1 = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, results = _run(spatial, [i1, i2])
        sig = (i1.intent_id, i2.intent_id, tuple(c.constraint_id for c in cs.constraints),
              tuple((r.constraint_id, r.verdict.value, r.error) for r in results))
        signatures.add(sig)
    assert len(signatures) == 1


def test_intent_ids_are_stable_across_runs():
    ids = {Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x").intent_id
          for _ in range(20)}
    assert len(ids) == 1

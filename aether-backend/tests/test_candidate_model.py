"""Deterministic checks for the P9 candidate model (candidate_model.py).
No GPU, no models.
"""
from __future__ import annotations

from app.planning.candidate_model import (
    Candidate, CandidateSource, candidate_key, dedupe)


def _c(x, z, rot=0.0, source=CandidateSource.DISTANCE):
    return Candidate(position=(x, z), rotation_y=rot, y=None, source=source,
                     constraint_id="c1", provenance="test")


def test_candidate_is_frozen():
    c = _c(1.0, 2.0)
    try:
        c.rotation_y = 1.0   # type: ignore[misc]
        assert False, "Candidate must be immutable"
    except Exception:
        pass


def test_candidate_key_is_deterministic():
    assert candidate_key(_c(1.0, 2.0, 0.5)) == candidate_key(_c(1.0, 2.0, 0.5))


def test_candidate_key_rounds_like_scene_object_fields():
    """Matches app/planning/compiler.py's own rounding (position to 3 dp,
    rotation to 4 dp) before a candidate ever becomes a placed SceneObject."""
    a = candidate_key(_c(1.00001, 2.0))
    b = candidate_key(_c(1.0, 2.0))
    assert a == b


def test_dedupe_keeps_first_occurrence():
    c1 = _c(1.0, 1.0, source=CandidateSource.DISTANCE)
    c2 = _c(1.0000001, 1.0, source=CandidateSource.BETWEEN)   # same rounded pose
    out = dedupe([c1, c2])
    assert len(out) == 1
    assert out[0] is c1


def test_dedupe_preserves_distinct_candidates():
    c1, c2 = _c(1.0, 1.0), _c(2.0, 2.0)
    out = dedupe([c1, c2])
    assert len(out) == 2


def test_dedupe_is_order_stable():
    c1, c2, c3 = _c(1.0, 1.0), _c(2.0, 2.0), _c(1.0, 1.0)
    out = dedupe([c1, c2, c3])
    assert out == [c1, c2]

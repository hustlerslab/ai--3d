"""Deterministic checks for candidate_ranker.py: soft preference only, no
random tie-breaking. No GPU, no models.
"""
from __future__ import annotations

from app.planning.candidate_model import Candidate, CandidateSource
from app.planning.candidate_ranker import rank_between, rank_by_ideal_distance


def _c(x, z):
    return Candidate(position=(x, z), rotation_y=0.0, y=None, source=CandidateSource.DISTANCE,
                     constraint_id="c", provenance="t")


def test_rank_by_ideal_distance_orders_best_first():
    near, far = _c(0.0, 1.0), _c(0.0, 3.0)
    ranked = rank_by_ideal_distance([far, near], 1.0, (0.0, 0.0))
    assert ranked == [near, far]


def test_rank_by_ideal_distance_tie_break_is_deterministic():
    a, b = _c(1.0, 0.0), _c(-1.0, 0.0)   # both exactly 1.0 from origin - a genuine tie
    ranked1 = rank_by_ideal_distance([a, b], 1.0, (0.0, 0.0))
    ranked2 = rank_by_ideal_distance([b, a], 1.0, (0.0, 0.0))
    assert ranked1 == ranked2   # same order regardless of input order - not insertion-order dependent


def test_rank_between_orders_by_lateral_offset():
    on_axis = _c(0.0, 0.0)
    off_axis = _c(2.0, 0.0)
    ranked = rank_between([off_axis, on_axis], (0.0, -2.0), (0.0, 2.0))
    assert ranked == [on_axis, off_axis]


def test_rank_between_handles_degenerate_segment():
    a = _c(0.0, 0.0)
    b = _c(5.0, 5.0)
    ranked = rank_between([b, a], (1.0, 1.0), (1.0, 1.0))   # anchor_a == anchor_b
    assert ranked[0] is a   # closer to the single point wins

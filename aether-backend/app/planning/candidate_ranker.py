"""P9 candidate ranking: soft preference ONLY - every candidate reaching
this module already passed `candidate_filters.filter_feasible` (§17's
filter/rank separation). No score here can ever resurrect a hard-infeasible
candidate, because none reach it.

§26: two SEPARATE, named numbers per candidate (never one opaque blend of
collision + distance + orientation + style): the PRIMARY key is the
constraint's own real geometric error (distance-to-ideal, or lateral
offset from a segment); the tie-break is `candidate_key` (§24), which is
purely a function of the candidate's own content - never insertion order,
never a random number, so ranking is deterministic even when two
candidates score identically.
"""
from __future__ import annotations

import math

from app.planning.candidate_model import Candidate, candidate_key


def rank_by_ideal_distance(candidates: list[Candidate], ideal_distance_m: float,
                           target_xz: tuple[float, float]) -> list[Candidate]:
    """§19/§26: best (smallest \\|actual - ideal\\|) first, deterministic
    tie-break by `candidate_key`."""
    def score(c: Candidate) -> tuple:
        actual = math.hypot(c.position[0] - target_xz[0], c.position[1] - target_xz[1])
        return (abs(actual - ideal_distance_m), candidate_key(c))
    return sorted(candidates, key=score)


def rank_between(candidates: list[Candidate], anchor_a: tuple[float, float],
                 anchor_b: tuple[float, float]) -> list[Candidate]:
    """§14/§19: best (smallest lateral offset from the anchor_a-anchor_b
    segment) first, deterministic tie-break by `candidate_key`."""
    dx, dz = anchor_b[0] - anchor_a[0], anchor_b[1] - anchor_a[1]
    length_sq = dx * dx + dz * dz

    def lateral_offset(c: Candidate) -> float:
        if length_sq < 1e-9:
            return math.hypot(c.position[0] - anchor_a[0], c.position[1] - anchor_a[1])
        t = ((c.position[0] - anchor_a[0]) * dx + (c.position[1] - anchor_a[1]) * dz) / length_sq
        proj = (anchor_a[0] + t * dx, anchor_a[1] + t * dz)
        return math.hypot(c.position[0] - proj[0], c.position[1] - proj[1])

    return sorted(candidates, key=lambda c: (lateral_offset(c), candidate_key(c)))


__all__ = ["rank_by_ideal_distance", "rank_between"]

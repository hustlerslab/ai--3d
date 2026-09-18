"""The 30+ named P10 end-to-end adversarial scenarios, as pytest cases.

Reuses (does not duplicate) `p10_integration_benchmark._scenarios()`.
"""
from __future__ import annotations

import pytest

from research.spatial_architecture.p10_integration_benchmark import (
    _scenarios, multi_constraint_composite)

_CASES = _scenarios()
_IDS = [name for name, _builder in _CASES]


@pytest.mark.parametrize("name,builder", _CASES, ids=_IDS)
def test_adversarial_scenario(name, builder):
    actual, expected = builder()
    assert actual == expected, f"{name}: expected {expected}, got {actual}"


def test_at_least_thirty_named_scenarios_exist():
    assert len(_CASES) >= 30
    assert len(set(_IDS)) == len(_IDS)


def test_multi_constraint_composite_generates_and_filters_candidates():
    """§7: the architecture must generate MORE THAN ZERO candidates and be
    able to filter/rank them - even when it cannot satisfy every constraint
    at once (a genuine, honestly-reported finding, not a test failure)."""
    result = multi_constraint_composite()
    assert result["candidate_count_before_filter"] > 0
    assert result["hard_violations"] == 0
    assert result["selected_candidate"] is not None

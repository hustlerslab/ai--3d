"""The >=40 named adversarial candidate scenarios, as pytest cases.

Reuses (does not duplicate) `candidate_benchmark._scenarios()`.
"""
from __future__ import annotations

import pytest

from research.spatial_architecture.candidate_benchmark import _scenarios

_CASES = _scenarios()
_IDS = [name for name, _builder in _CASES]


@pytest.mark.parametrize("name,builder", _CASES, ids=_IDS)
def test_adversarial_scenario(name, builder):
    actual, expected = builder()
    assert actual == expected, f"{name}: expected {expected}, got {actual}"


def test_at_least_forty_named_scenarios_exist():
    assert len(_CASES) >= 40
    assert len(set(_IDS)) == len(_IDS)

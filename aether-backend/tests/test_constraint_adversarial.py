"""The >=30 named adversarial constraint scenarios, as pytest cases.

Reuses (does not duplicate) `constraint_benchmark._scenarios()` - the same
builders `python research/spatial_architecture/constraint_benchmark.py`
reports on are asserted here individually, by name.
"""
from __future__ import annotations

import pytest

from research.spatial_architecture.constraint_benchmark import _scenarios

_CASES = _scenarios()
_IDS = [name for name, _builder in _CASES]


@pytest.mark.parametrize("name,builder", _CASES, ids=_IDS)
def test_adversarial_scenario(name, builder):
    actual, expected = builder()
    assert actual == expected, f"{name}: expected {expected}, got {actual}"


def test_at_least_thirty_named_scenarios_exist():
    assert len(_CASES) >= 30
    assert len(set(_IDS)) == len(_IDS)

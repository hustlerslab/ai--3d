"""The >=20 named adversarial scene-graph scenarios, as pytest cases.

Reuses (does not duplicate) `scene_benchmark._scenarios()` - the same
scenario builders `python research/spatial_architecture/scene_benchmark.py`
reports on are asserted here individually, by name, so a regression in any
one scenario fails pytest with that scenario's own name rather than only
showing up in a benchmark JSON diff.
"""
from __future__ import annotations

import pytest

from research.spatial_architecture.scene_benchmark import _scenarios
from app.spatial.scene_consistency import check_consistency
from app.spatial.scene_graph import recompute_relations
from app.spatial.scene_serialization import (
    from_canonical_json, to_canonical_json)

_CASES = _scenarios()
_IDS = [name for name, *_ in _CASES]


@pytest.mark.parametrize("name,builder,do_recompute,expected", _CASES, ids=_IDS)
def test_adversarial_scenario(name, builder, do_recompute, expected):
    spatial = builder()
    if do_recompute:
        spatial, _changes = recompute_relations(spatial)
    findings = check_consistency(spatial)
    codes = {f.code for f in findings}
    assert codes == expected, f"{name}: expected {expected}, found {codes}"

    text = to_canonical_json(spatial)
    assert to_canonical_json(from_canonical_json(text)) == text, f"{name}: not lossless"


def test_at_least_twenty_named_scenarios_exist():
    assert len(_CASES) >= 20
    assert len(set(_IDS)) == len(_IDS)   # every name unique

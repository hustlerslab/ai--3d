"""§20: 20-repeat determinism for the P10 end-to-end integration benchmark.
No GPU, no models.
"""
from __future__ import annotations

from research.spatial_architecture.p10_integration_benchmark import (
    determinism_check, multi_constraint_composite)


def test_determinism_check_passes():
    assert determinism_check(runs=20) is True


def test_multi_constraint_composite_is_byte_identical_across_20_runs():
    runs = {str(multi_constraint_composite()) for _ in range(20)}
    assert len(runs) == 1

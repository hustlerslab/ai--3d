"""Deterministic checks for failure_taxonomy.py. No GPU, no models."""
from __future__ import annotations

from research.spatial_architecture.failure_taxonomy import (
    HISTORICAL_FAILURES, FailureCategory, by_category, classify, summary_counts)


def test_every_historical_failure_has_a_valid_category():
    for f in HISTORICAL_FAILURES:
        assert isinstance(f.category, FailureCategory)


def test_every_historical_failure_cites_a_source():
    for f in HISTORICAL_FAILURES:
        assert f.source.strip(), f.name


def test_classify_unknown_name_returns_unknown():
    assert classify("not_a_real_failure") == FailureCategory.UNKNOWN


def test_classify_known_name_returns_its_category():
    assert classify("p8_faces_wiring_bug") == FailureCategory.REPRESENTATION_FAILURE


def test_by_category_only_returns_matching_entries():
    perception = by_category(FailureCategory.PERCEPTION_FAILURE)
    assert all(f.category == FailureCategory.PERCEPTION_FAILURE for f in perception)
    assert len(perception) > 0


def test_summary_counts_sum_to_total_failures():
    counts = summary_counts()
    assert sum(counts.values()) == len(HISTORICAL_FAILURES)


def test_no_perception_failure_relabelled_as_solver_failure():
    """§8's own explicit rule: never call a model error an architecture
    error. The FACES wiring bug (a genuine representation/architecture
    defect) must NOT be classified as PERCEPTION_FAILURE, and the wall-
    contact precision ceiling (a genuine model/evidence limitation) must
    NOT be classified as SOLVER_FAILURE."""
    assert classify("p8_faces_wiring_bug") != FailureCategory.PERCEPTION_FAILURE
    assert classify("wall_contact_precision_77_8_pct") != FailureCategory.SOLVER_FAILURE

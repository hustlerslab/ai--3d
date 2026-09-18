"""Deterministic checks for production_boundary.py. No GPU, no models."""
from __future__ import annotations

from research.spatial_architecture.production_boundary import (
    PRODUCTION_BOUNDARY, Readiness, by_path, readiness_counts)


def test_at_least_four_distinct_paths_assessed():
    """§15's own explicit requirement: design-from-brief, photo-to-scene,
    floorplan-to-scene, mixed-input - never one vague overall label."""
    assert len(PRODUCTION_BOUNDARY) >= 4


def test_every_assessment_has_evidence_and_limitation():
    for p in PRODUCTION_BOUNDARY:
        assert p.evidence.strip()
        assert p.limitation.strip()


def test_readiness_is_never_a_single_collapsed_value():
    values = {p.readiness for p in PRODUCTION_BOUNDARY}
    assert len(values) > 1   # not everything is labelled the same


def test_floorplan_path_is_honestly_not_yet_solved():
    row = by_path("floorplan")
    assert row is not None
    assert row.readiness == Readiness.NOT_YET_SOLVED


def test_photo_to_scene_is_research_only():
    row = by_path("photo-to-scene")
    assert row is not None
    assert row.readiness in (Readiness.RESEARCH_ONLY, Readiness.MODEL_LIMITED)


def test_readiness_counts_sum_to_total_paths():
    counts = readiness_counts()
    assert sum(counts.values()) == len(PRODUCTION_BOUNDARY)

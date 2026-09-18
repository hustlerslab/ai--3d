"""Deterministic checks for authority_audit.py: the "who decides what"
matrix and its central invariant. No GPU, no models.
"""
from __future__ import annotations

from research.spatial_architecture.authority_audit import (
    AUTHORITY_MATRIX, check_no_ai_override, find)

REQUIRED_ARTIFACTS = [
    "object identity (object_id)", "object dimensions", "object footprint",
    "object orientation (rotation_y)", "room boundary", "wall geometry", "floor",
    "wall contact (AGAINST_WALL)", "FACES", "NEAR", "BETWEEN",
    "support (SUPPORTED_BY / parent_id)", "clearance", "collision",
    "final XYZ", "final yaw", "final intent satisfaction",
]


def test_all_seventeen_required_artifacts_present():
    names = {row.artifact for row in AUTHORITY_MATRIX}
    for artifact in REQUIRED_ARTIFACTS:
        assert artifact in names, artifact


def test_no_ai_override_of_final_geometry():
    """The central property this audit exists to prove (§3's own explicit
    demand): no artifact's final value may be decided by an LLM/VLM."""
    assert check_no_ai_override() == []


def test_every_row_has_a_non_empty_verifier():
    for row in AUTHORITY_MATRIX:
        assert isinstance(row.verifier, str) and row.verifier.strip(), row.artifact


def test_find_returns_none_for_unknown_artifact():
    assert find("not a real artifact") is None


def test_find_returns_the_matching_row():
    row = find("FACES")
    assert row is not None
    assert row.ai_can_decide_final_value is False

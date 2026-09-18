"""Canonical failure taxonomy (P10 §8): the twelve categories every layer
reports against, so a failure always names the layer responsible.

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md.

Rules (P10 §8): a model error is never relabelled an architecture error;
an architecture error is never relabelled a model error; a hardware
limitation is never relabelled a model failure.
"""
from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    """The twelve categories §8 asks for, verbatim."""

    PERCEPTION_FAILURE = "perception_failure"                   # a model's own output was wrong/absent
    GEOMETRY_FAILURE = "geometry_failure"                       # a geometric computation was wrong
    REPRESENTATION_FAILURE = "representation_failure"           # the DATA MODEL could not express a true fact
    CONSTRAINT_FAILURE = "constraint_failure"                   # a constraint was mis-specified or mis-compiled
    CANDIDATE_VOCABULARY_FAILURE = "candidate_vocabulary_failure"  # no candidate could express a valid solution
    SOLVER_FAILURE = "solver_failure"                           # the solver picked wrong among valid candidates
    REPAIR_FAILURE = "repair_failure"                           # repair could not or wrongly fixed a violation
    VALIDATION_FAILURE = "validation_failure"                   # a check was missing or incorrect
    ASSET_FAILURE = "asset_failure"                             # a catalogue/generated asset was wrong
    BLENDER_EXECUTION_FAILURE = "blender_execution_failure"     # the build/render step itself failed
    HARDWARE_FAILURE = "hardware_failure"                       # VRAM/compute/latency, not correctness
    UNKNOWN = "unknown"                                         # correctly abstained - not a defect at all


__all__ = ["FailureCategory"]

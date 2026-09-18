"""P10 canonical failure taxonomy, and the reclassification of every named
historical failure this program (P0-P9) has actually found.

WHY THIS DID NOT EXIST BEFORE. Every phase invented its own prose category
for what went wrong ("REPRESENTATION loss," "OBJECT_EXTENT_FAILURE,"
"UPSTREAM_PERCEPTION_FAILURE," "GROUNDING_FAILURE") - all real, all
carefully reasoned at the time, but never unified into one enum a future
caller could sort or count by. P10's job is that unification, not
re-investigating any of them: every entry in `HISTORICAL_FAILURES` cites the
phase/doc that already did the finding.

THE THREE RULES THIS MODULE ENFORCES (§8's own three warnings):
  1. A model error is never relabelled an architecture error.
  2. An architecture error is never relabelled a model error.
  3. A hardware limitation is never relabelled a model failure.
"""
from __future__ import annotations

from dataclasses import dataclass


from app.spatial.failures import FailureCategory  # noqa: E402,F401


@dataclass(frozen=True)
class HistoricalFailure:
    name: str
    phase: str
    category: FailureCategory
    description: str
    source: str          # the doc/report that originally found it
    resolved: bool        # was it fixed within P0-P9, or does it remain open?


#: Every named failure this program has actually measured and reported,
#: from the pre-P0 perception research through P9. Reclassified here, not
#: re-investigated - each `source` is the original finding.
HISTORICAL_FAILURES: tuple[HistoricalFailure, ...] = (
    HistoricalFailure(
        name="vlm_wall_contact_refusal",
        phase="pre-P0 (Phase 1c-1h)",
        category=FailureCategory.PERCEPTION_FAILURE,
        description="A VLM asked 'is this object against a wall' in six "
                    "formulations produced 78/78 refusals to abstain and a "
                    "constant-function wall gate - the model could not do a "
                    "geometric task by being asked in language.",
        source="app/spatial/planes.py module docstring; phase_1c-1h reports",
        resolved=True,   # replaced by deterministic plane-fit geometry (app/spatial/planes.py)
    ),
    HistoricalFailure(
        name="wall_contact_precision_77_8_pct",
        phase="pre-P0",
        category=FailureCategory.PERCEPTION_FAILURE,
        description="Deterministic wall-contact geometry (once built) reached "
                    "77.8% precision / 25% UNKNOWN on the frozen 48-case "
                    "benchmark, short of the 90% target - a genuine model/"
                    "evidence-quality ceiling (mask quality, depth noise), "
                    "not an architectural defect: the abstention mechanism "
                    "itself worked correctly (no silent false positives).",
        source="docs/benchmarks/spatial_engine_production_readiness.md §6-7",
        resolved=False,   # open - perception-quality-dependent, not blocking the architecture
    ),
    HistoricalFailure(
        name="tv_unit_duplicate_grounding",
        phase="P1",
        category=FailureCategory.PERCEPTION_FAILURE,
        description="Two independent groundings of one physical TV unit in "
                    "moodboard_room_living_room - re-examined against real "
                    "bounding boxes and found to be genuinely different "
                    "shapes/positions, i.e. an upstream object-extent "
                    "measurement issue, NOT a duplicate-identity bug in the "
                    "collision/repair architecture (an earlier session claim "
                    "that it was a duplicate was corrected in P4).",
        source="docs/spatial_architecture/repair.md (P4's correction of the "
              "original P1-era claim)",
        resolved=False,   # remains the one UNREPAIRABLE case in every 21-image benchmark run since
    ),
    HistoricalFailure(
        name="collision_solver_budget_discard",
        phase="P3",
        category=FailureCategory.SOLVER_FAILURE,
        description="`solve_backtracking`'s budget-exhaustion path discarded "
                    "ALL prior valid commitments, not just the abandoned "
                    "branch, producing impossible 'zero objects placed' "
                    "results at n=20/30.",
        source="docs/spatial_architecture/optimization.md",
        resolved=True,
    ),
    HistoricalFailure(
        name="wall_candidate_offset_bug",
        phase="P3",
        category=FailureCategory.GEOMETRY_FAILURE,
        description="`_wall_candidates` forgot to offset by `wall.thickness/2` "
                    "from the centreline, placing every candidate inside the "
                    "wall's own collision rectangle.",
        source="docs/spatial_architecture/optimization.md",
        resolved=True,
    ),
    HistoricalFailure(
        name="repair_terminal_state_misclassification",
        phase="P4",
        category=FailureCategory.REPAIR_FAILURE,
        description="Terminal-state logic hardcoded UPSTREAM_REQUIRED even "
                    "when a violation was genuinely attempted-and-failed, "
                    "which should report ESCALATE/UNREPAIRABLE instead.",
        source="docs/spatial_architecture/repair.md",
        resolved=True,
    ),
    HistoricalFailure(
        name="random_object_id_nondeterminism",
        phase="P4",
        category=FailureCategory.REPRESENTATION_FAILURE,
        description="`grounding_to_scene` never set an explicit `object_id`, "
                    "defaulting to a fresh random UUID every process run, "
                    "which corrupted `resolve_collisions`'s confidence-based "
                    "tie-break non-deterministically across runs.",
        source="docs/spatial_architecture/repair.md",
        resolved=True,
    ),
    HistoricalFailure(
        name="wall_tilt_representation_loss",
        phase="P5",
        category=FailureCategory.REPRESENTATION_FAILURE,
        description="A flat `Wall`/`Room.boundary` schema could not represent "
                    "a photo-reconstructed wall's real ~11 degree tilt, "
                    "causing false COLLIDES_WALL residuals - the geometry was "
                    "correctly reconstructed; the SCHEMA could not express it.",
        source="docs/spatial_architecture/wall_geometry.md; "
              "spatial_engine_production_readiness.md §15 item 6",
        resolved=True,   # research-layer TiltedWall closes this; production Scene.Wall still 2D-only
    ),
    HistoricalFailure(
        name="wall_frame_non_orthogonality",
        phase="P5",
        category=FailureCategory.GEOMETRY_FAILURE,
        description="`wall_local_frame`'s tangent/up basis vectors were each "
                    "only separately near-perpendicular to the fitted plane "
                    "normal, not to EACH OTHER, breaking the round-trip "
                    "transform for a tilted wall.",
        source="docs/spatial_architecture/wall_geometry.md",
        resolved=True,
    ),
    HistoricalFailure(
        name="p8_faces_wiring_bug",
        phase="P8 (found and fixed in P9)",
        category=FailureCategory.REPRESENTATION_FAILURE,
        description="The FACES constraint was compiled into the free-text "
                    "`ObjectPlanItem.faces` field, which `_ordered()`'s "
                    "dependency graph never reads (only `.relation.target_key` "
                    "is tracked) - the CANDIDATE vocabulary and the SOLVER "
                    "were both already correct; the INTENT could not be "
                    "represented in a form either of them could consume in "
                    "the right order. Not a candidate-vocabulary gap (P9's "
                    "own explicit, measured finding) and not a solver bug.",
        source="docs/spatial_architecture/decisions.md P9 entry, §3-4",
        resolved=True,
    ),
    HistoricalFailure(
        name="p8_near_between_no_metric_vocabulary",
        phase="P8 (found), P9 (fixed)",
        category=FailureCategory.CANDIDATE_VOCABULARY_FAILURE,
        description="No `RelationType`/`ObjectRelation` field could carry a "
                    "user's explicit metric distance or a two-target segment "
                    "region - a genuine, not merely mis-wired, gap in what "
                    "the candidate vocabulary could express.",
        source="docs/spatial_architecture/decisions.md P9 entry, §4",
        resolved=True,   # closed by candidate_generators.py's distance/between generators
    ),
    HistoricalFailure(
        name="asset_forward_axis_unverifiable",
        phase="pre-P0, re-confirmed P6/P7/P8/P9",
        category=FailureCategory.ASSET_FAILURE,
        description="No per-asset forward-axis correction field exists; "
                    "identity remains the measured-correct default for every "
                    "asset benchmarked so far (Phase 10's 58/58 audit, "
                    "re-confirmed unneeded every phase since).",
        source="docs/spatial_architecture/coordinate_frames.md §Asset frame",
        resolved=False,   # open, but explicitly not blocking (no benchmarked case has needed it)
    ),
    HistoricalFailure(
        name="mock_provider_room_studio_misparse",
        phase="pre-P0",
        category=FailureCategory.PERCEPTION_FAILURE,
        description="The `res_studio` brief parsed to a single 'kitchen' room "
                    "in the mock provider, leaving bed/sofa/wardrobe with no "
                    "room to place into - an upstream room-analysis "
                    "limitation, not a solver/candidate defect.",
        source="docs/benchmarks/scene_validity_report.md §2",
        resolved=False,   # open, mock-provider-specific, not on the architecture's critical path
    ),
)


def classify(name: str) -> FailureCategory:
    for f in HISTORICAL_FAILURES:
        if f.name == name:
            return f.category
    return FailureCategory.UNKNOWN


def by_category(category: FailureCategory) -> tuple[HistoricalFailure, ...]:
    return tuple(f for f in HISTORICAL_FAILURES if f.category == category)


def summary_counts() -> dict[str, int]:
    counts = {c.value: 0 for c in FailureCategory}
    for f in HISTORICAL_FAILURES:
        counts[f.category.value] += 1
    return counts


__all__ = ["FailureCategory", "HistoricalFailure", "HISTORICAL_FAILURES",
           "classify", "by_category", "summary_counts"]

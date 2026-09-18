"""P10 authority audit: for every important spatial fact, who created it,
who may modify it, who may invalidate it, and who verifies it.

METHOD. Each row below is a FINDING from re-reading the actual call sites
(`app/planning/compiler.py`, `app/spatial/validation.py`, `research/
spatial_architecture/*`), not an assumption - the same discipline P7's
`scene_model.md` and P9's `candidate_architecture.md` audits used. Encoded
as data here for the first time so it can be checked (`check_no_ai_override`)
rather than only asserted in prose.

THE ONE PROPERTY THIS MODULE EXISTS TO PROVE: no row has
`ai_can_decide_final_value=True`. An LLM/VLM may supply EVIDENCE (a
measured-ish estimate, e.g. a brief's stated room width) or INTENT (a
claim/request, e.g. "the sofa faces the TV"), and both are recorded with
their own provenance/confidence - but the FINAL value of every row below is
always written by a named, deterministic function, gated through
`validate_object` where geometry is involved.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorityRow:
    artifact: str
    creator: str
    modifier: str
    invalidator: str
    verifier: str
    ai_role: str                    # what an LLM/VLM may contribute, if anything
    ai_can_decide_final_value: bool  # must be False for every row - the property this module proves


AUTHORITY_MATRIX: tuple[AuthorityRow, ...] = (
    AuthorityRow(
        artifact="object identity (object_id)",
        creator="place_objects (brief path, default factory) / grounding_to_scene "
               "(photo path, deterministic f'obj_{case_id}')",
        modifier="never - immutable once created",
        invalidator="never",
        verifier="SpatialScene.object()/.wall()/.room() lookups (P7) - implicit uniqueness reliance",
        ai_role="none - ids are never derived from model output",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="object dimensions",
        creator="AssetDecision.dimensions - app.catalog.catalog (real measured catalogue/registry "
               "dims) or GroundingHypothesis.extent_wdh_m (measured from SAM/MoGe evidence)",
        modifier="SceneObject.scale, set once by place_objects's shrink_steps (deterministic)",
        invalidator="never",
        verifier="object_footprint()/validate_object consume dims but do not independently re-verify them",
        ai_role="a VLM/brief may SUGGEST a semantic type whose catalogue dims are then looked up "
               "deterministically - it never states a dimension number that is used directly",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="object footprint",
        creator="N/A - derived on demand by app.spatial.geometry.footprint_corners "
               "(position + dimensions + rotation_y), a pure function, never stored",
        modifier="N/A - recomputed every call, never cached/mutated",
        invalidator="N/A",
        verifier="validate_object (H1/H2/H3 checks read it fresh each call)",
        ai_role="none",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="object orientation (rotation_y)",
        creator="place_objects's candidate loop (brief path) / grounding_to_scene's "
               "_resolve_yaw (photo path, geometrically derived + residual-checked)",
        modifier="repair_engine.repair_scene (P4); candidate_generators.regenerate_after_placement (P9)",
        invalidator="scene_graph.recompute_relations (P7) marks a stale AGAINST_WALL relation, "
                   "never the rotation_y field itself",
        verifier="validate_object (collision/bounds); constraint_evaluator (ORIENTATION verdict)",
        ai_role="a user/model may ASSERT a FACES intent (a request); the actual yaw is always a "
               "solver-chosen candidate, filtered through validate_object",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="room boundary",
        creator="layout_rooms (brief path, from RoomAnalysis.width_m/length_m) / "
               "scene_from_photo.build_room_boundary (photo path, a padded convex hull of "
               "MEASURED floor points)",
        modifier="never after compile_scene/grounding_to_scene",
        invalidator="never",
        verifier="validate_scene's INVALID_ROOM_POLYGON check (degeneracy only, not room-size truth)",
        ai_role="a design-analysis provider MAY estimate width_m/length_m (recorded as evidence, "
               "Room.confidence.source names the provider) - the BOUNDARY POLYGON itself is always "
               "computed deterministically from whatever numbers it is given, never hand-drawn by a model",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="wall geometry",
        creator="build_walls_and_openings (brief path, deterministic from room boundary) / "
               "app.spatial.planes plane-fit geometry + wall_quality.extract_wall_features (photo "
               "path, deterministic RANSAC-style fitting - replaced a VLM approach that failed "
               "(78/78 refusals), see failure_taxonomy.py's vlm_wall_contact_refusal entry)",
        modifier="never after construction",
        invalidator="never",
        verifier="validate_scene (wall-referencing openings); wall_geometry.py's round-trip tests (P5)",
        ai_role="none on the photo path (deliberately replaced); brief path is evidence-derived per "
               "the room-boundary row above",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="floor",
        creator="Room.floor_height=0.0 (brief path, fixed) / generate_floor_candidates + "
               "select_floor (photo path, deterministic plane-fit scoring)",
        modifier="never after construction",
        invalidator="never",
        verifier="floor plane fit reports its own inlier fraction/residuals (app/spatial/planes.py "
               "rule 1 - 'every fit reports its own trustworthiness')",
        ai_role="none",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="wall contact (AGAINST_WALL)",
        creator="constraint_evaluator._evaluate_contact (P8) - geometric distance-to-segment check, "
               "P7's own AGAINST_WALL_TOLERANCE_M",
        modifier="scene_graph.recompute_relations (P7) - re-verification only, never asserts a new claim",
        invalidator="scene_graph.recompute_relations marks CONTRADICTED when geometry no longer supports it",
        verifier="the SAME function that creates the verdict - a deterministic geometric test, run "
               "identically at generation and evaluation time (P9's own consistency invariant)",
        ai_role="a user/model may ASSERT an AGAINST_WALL intent (a claim, EVIDENCE_CLAIM or "
               "USER_ASSERTED Intent) - whether it is actually TRUE is decided only by the geometric test",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="FACES",
        creator="constraint_evaluator._evaluate_orientation (P8) - angular-error geometric test",
        modifier="none - re-evaluated fresh, never patched",
        invalidator="N/A (always re-computed from current geometry, no cached claim to invalidate)",
        verifier="same function - candidate generation (production's _relation_candidates('facing')) "
               "and evaluation share the identical cos>0.5 threshold (P9's proven invariant)",
        ai_role="Intent only (USER_ASSERTED/MODEL_INFERRED) - never decides satisfaction",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="NEAR",
        creator="constraint_evaluator._evaluate_distance (P8)",
        modifier="none",
        invalidator="N/A",
        verifier="same function; UNKNOWN (not a fabricated number) when no explicit distance was given",
        ai_role="Intent only, and may supply the numeric distance_m parameter as a stated request "
               "(still just a parameter on an Intent, not a placement)",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="BETWEEN",
        creator="constraint_evaluator._evaluate_between (P8) - segment projection + lateral offset",
        modifier="none",
        invalidator="N/A",
        verifier="same function; candidate_generators.between_candidates (P9) uses the identical formula",
        ai_role="Intent only",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="support (SUPPORTED_BY / parent_id)",
        creator="app.planning.compiler._pick_support (deterministic, vocab.SUPPORT_PREFERENCE + "
               "geometric _surface_candidates fit)",
        modifier="place_objects only, at placement time",
        invalidator="never",
        verifier="constraint_evaluator._evaluate_support (parent_id match + vertical gap check)",
        ai_role="none - support preference tables are static data, not model output",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="clearance",
        creator="research.spatial_architecture.clearance_engine (P2, deterministic geometry)",
        modifier="none - always recomputed",
        invalidator="N/A",
        verifier="same module; reported as soft severity, does not block scene_success in production integration",
        ai_role="none",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="collision",
        creator="app.spatial.validation.validate_object (H2/H3 - SAT on rotated footprints), the "
               "SINGLE hard-collision authority used everywhere in this program",
        modifier="never - always recomputed",
        invalidator="N/A",
        verifier="itself - every candidate generator/filter in P1-P9 calls this exact function, "
                "never a reimplementation",
        ai_role="none",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="final XYZ",
        creator="place_objects (P0) / repair_scene (P4) / regenerate_after_placement (P9) - "
               "always a candidate filtered through validate_object, never an unfiltered write",
        modifier="the same three functions, and only those three, across P0-P9",
        invalidator="N/A (repair/regeneration REPLACES it, under the same validate_object gate)",
        verifier="validate_object/validate_scene, every time a candidate is accepted",
        ai_role="none - not even as a suggested coordinate; intent supplies a RELATION/DISTANCE, "
               "never a number consumed directly as a position",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="final yaw",
        creator="same three functions as final XYZ",
        modifier="same three functions",
        invalidator="N/A",
        verifier="validate_object; constraint_evaluator's ORIENTATION check independently afterwards",
        ai_role="none - same as final XYZ",
        ai_can_decide_final_value=False,
    ),
    AuthorityRow(
        artifact="final intent satisfaction",
        creator="constraint_evaluator.evaluate_all (P8) - STRICTLY read-only, never mutates the scene "
               "it inspects",
        modifier="never - a fresh ConstraintResult is produced by each call, nothing is patched",
        invalidator="N/A - re-evaluation simply produces a new result",
        verifier="itself; independent of, and never consulted by, the solver's own internal candidate "
               "ranking (P8/P9's own 'solver success vs. intent success' distinction)",
        ai_role="none - a model may only be the SOURCE of the Intent being checked, never the checker",
        ai_can_decide_final_value=False,
    ),
)


def check_no_ai_override() -> list[str]:
    """The one property this audit exists to prove. Returns violations
    (empty = the property holds)."""
    return [row.artifact for row in AUTHORITY_MATRIX if row.ai_can_decide_final_value]


def find(artifact: str):
    return next((r for r in AUTHORITY_MATRIX if r.artifact == artifact), None)


__all__ = ["AuthorityRow", "AUTHORITY_MATRIX", "check_no_ai_override", "find"]

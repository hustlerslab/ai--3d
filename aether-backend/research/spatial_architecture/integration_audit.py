"""P10 integration audit: the canonical pipeline-stage contract table (§2)
and at least 10 traced evidence -> decision provenance chains (§4).

Everything traced here is REUSED, not reimplemented: every trace below
calls into P1/P4/P5/P7/P8/P9's own already-tested functions (`grounding_to_
scene`, `repair_scene`, `wall_geometry`, `scene_graph.build_demonstration_
scene`, `constraint_benchmark.brief_end_to_end_demo`, `constraint_benchmark.
photo_end_to_end_demo`) and reads the provenance fields those functions
already populate - this module adds no new geometry, no new solver
behaviour, and no new evidence source.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── §2: the sixteen-stage pipeline contract table ─────────────────────────

@dataclass(frozen=True)
class StageContract:
    stage: str
    input_contract: str
    output_contract: str
    authority: str
    evidence_provenance: str
    confidence: str
    deterministic: bool
    failure_modes: str
    may_mutate_state: bool
    may_decide_geometry: bool


PIPELINE_STAGES: tuple[StageContract, ...] = (
    StageContract(
        stage="PERCEPTION",
        input_contract="a photo (bytes) or a text brief (str)",
        output_contract="MoGe-2 point map + SAM 2 masks (photo) / DesignAnalysis (brief, may use an LLM provider)",
        authority="the model itself - never corrected by downstream code, only abstained-from",
        evidence_provenance="raw model output, unattributed to any prior stage",
        confidence="per-mask/per-point model confidence (photo); provider-reported (brief)",
        deterministic=False,   # model inference is not guaranteed bit-identical across hardware/versions
        failure_modes="PERCEPTION_FAILURE - wrong/missing detection, hallucinated object, wrong room count",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="EVIDENCE",
        input_contract="raw model output from PERCEPTION",
        output_contract="typed evidence records (PlaneFitResult, WallContact, RoomAnalysis) with "
                        "explicit trust fields (inlier fraction, residuals)",
        authority="app.spatial.planes / app.intelligence.schema - deterministic wrapping, no re-interpretation",
        evidence_provenance="cites the exact model/algorithm that produced it (app/spatial/planes.py rule 1)",
        confidence="explicit per-record (never a single collapsed number)",
        deterministic=True,   # the WRAPPING is deterministic even though the model call above is not
        failure_modes="PERCEPTION_FAILURE (propagated) - low inlier fraction, UNKNOWN decision",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="ROOM_GEOMETRY",
        input_contract="evidence (floor/wall plane fits, or brief RoomAnalysis)",
        output_contract="Room (boundary polygon) + Wall list",
        authority="layout_rooms/build_walls_and_openings (brief) or build_room_boundary/wall_quality (photo)",
        evidence_provenance="padded convex hull of MEASURED floor points (photo) / stated room dims (brief)",
        confidence="Room.confidence (explicit, e.g. 'reconstructed_partial_view')",
        deterministic=True,
        failure_modes="REPRESENTATION_FAILURE - flat Wall schema cannot express real 3D tilt",
        may_mutate_state=False,
        may_decide_geometry=True,   # the ROOM's own geometry, not an object's
    ),
    StageContract(
        stage="OBJECT_GROUNDING",
        input_contract="evidence + room geometry",
        output_contract="GroundingHypothesis (FACT footprint/position/depth, HYPOTHESIS orientation "
                        "candidates, DECISION wall_contact)",
        authority="research.spatial_engine.object_grounding - deterministic geometry over model evidence",
        evidence_provenance="SAM mask coverage x MoGe valid-depth fraction (perception_confidence)",
        confidence="three explicit channels (perception/extent/wall), never averaged into one hidden number",
        deterministic=True,
        failure_modes="PERCEPTION_FAILURE (upstream) / GEOMETRY_FAILURE (own math)",
        may_mutate_state=False,
        may_decide_geometry=True,
    ),
    StageContract(
        stage="RELATIONS",
        input_contract="GroundingHypothesis / SceneReading (moodboard arrangement words)",
        output_contract="GeometricRelation (P7) / SpatialRelation (moodboard stage) - classified, "
                        "provenance-carrying, deterministic id",
        authority="scene_graph.from_bridge_result / app.planning.spatial_graph.build_spatial_graph",
        evidence_provenance="explicit source field (geometry/semantic/placement) per relation",
        confidence="categorical (HIGH/MEDIUM/LOW/UNKNOWN), never fabricated",
        deterministic=True,
        failure_modes="REPRESENTATION_FAILURE if a relation cannot be expressed in the target schema",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="USER_MODEL_INTENT",
        input_contract="a user's stated request or a model's own claim",
        output_contract="Intent (P8) - subject/predicate/target/parameters, source, priority",
        authority="whoever asserted it - USER_ASSERTED/MODEL_INFERRED/OBSERVED/DERIVED, never re-labelled downstream",
        evidence_provenance="Intent.provenance - the original text/reason, verbatim",
        confidence="categorical, carried from the source",
        deterministic=True,   # Intent construction itself; the human/model INPUT it wraps is not
        failure_modes="none architectural - an Intent is a request, never wrong by construction",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="CONSTRAINTS",
        input_contract="Intent + SpatialScene",
        output_contract="Constraint (P8) - typed, SOFT, provenance-chained to its Intent",
        authority="constraint_compiler.compile_intents - pure function, never places anything",
        evidence_provenance="Constraint.provenance embeds source_intent_id + the Intent's own text",
        confidence="carried from the Intent",
        deterministic=True,
        failure_modes="CONSTRAINT_FAILURE - unsupported predicate (recorded in .unsupported, never dropped)",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="CANDIDATE_GENERATION",
        input_contract="Constraint + current Scene geometry",
        output_contract="Candidate[] (P9) or production's own (Vec2, yaw, y) tuples",
        authority="app.planning.compiler._relation_candidates (ORIENTATION/CONTACT/SUPPORT) / "
                 "candidate_generators.distance_candidates/between_candidates (DISTANCE/POSITION)",
        evidence_provenance="Candidate.provenance names the rule and parameters that produced it",
        confidence="N/A - a candidate is a possibility, not a claim",
        deterministic=True,
        failure_modes="CANDIDATE_VOCABULARY_FAILURE - no candidate can express a valid solution",
        may_mutate_state=False,
        may_decide_geometry=False,   # PROPOSES, does not decide
    ),
    StageContract(
        stage="CANDIDATE_FILTERING",
        input_contract="Candidate[] + Scene",
        output_contract="Candidate[] (feasible subset only)",
        authority="candidate_filters.filter_feasible - wraps app.spatial.validation.validate_object, "
                 "the ONE hard-feasibility gate everywhere in this program",
        evidence_provenance="N/A - a deterministic geometric test, not evidence",
        confidence="N/A - boolean feasibility",
        deterministic=True,
        failure_modes="none architectural if validate_object itself is correct (VALIDATION_FAILURE otherwise)",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="CANDIDATE_RANKING",
        input_contract="feasible Candidate[]",
        output_contract="Candidate[] sorted best-first",
        authority="candidate_ranker.rank_by_ideal_distance/rank_between (P9) or production's own "
                 "_prefer_hint/_faces_rank re-ordering",
        evidence_provenance="N/A",
        confidence="N/A",
        deterministic=True,   # tie-break by candidate_key, never random/insertion-order
        failure_modes="none architectural - ranking only reorders already-feasible candidates",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="SOLVER",
        input_contract="ranked/ordered candidates for one object at a time",
        output_contract="SceneObject.position/.rotation_y - the ONE authoritative geometric decision",
        authority="app.planning.compiler.place_objects (P0) - the sole placement authority",
        evidence_provenance="Confidence.source names the solver/provider that placed it",
        confidence="Confidence.value (a scalar, explicit)",
        deterministic=True,   # given a fixed candidate list and fixed ordering
        failure_modes="SOLVER_FAILURE - a feasible, intent-satisfying candidate existed but a worse one was chosen",
        may_mutate_state=True,   # writes the Scene
        may_decide_geometry=True,
    ),
    StageContract(
        stage="VALIDATION",
        input_contract="Scene",
        output_contract="list[Violation] - hard, empty means valid",
        authority="app.spatial.validation.validate_scene - strictly read-only",
        evidence_provenance="N/A - a deterministic geometric re-check",
        confidence="N/A - boolean per violation code",
        deterministic=True,
        failure_modes="VALIDATION_FAILURE - a real violation the checks do not cover (e.g. no 3D OBB)",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="REPAIR_RE_SOLVE",
        input_contract="Scene + hard Violation[]",
        output_contract="Scene (updated) + RepairRecord[] + TerminalState",
        authority="repair_engine.repair_scene (P4) - escalation ladder, bounded, local-first",
        evidence_provenance="RepairRecord names the level/rule/reason for every move",
        confidence="N/A",
        deterministic=True,
        failure_modes="REPAIR_FAILURE - wrong terminal state, or a fix that creates a new violation",
        may_mutate_state=True,
        may_decide_geometry=True,
    ),
    StageContract(
        stage="INDEPENDENT_INTENT_EVALUATION",
        input_contract="Constraint[] + final Scene",
        output_contract="ConstraintResult[] - SATISFIED/VIOLATED/UNKNOWN/PARTIAL, with numeric error",
        authority="constraint_evaluator.evaluate_all (P8) - STRICTLY read-only, independent of the solver's own scoring",
        evidence_provenance="ConstraintResult.message names the exact measured quantity",
        confidence="N/A - a deterministic verdict, not a belief",
        deterministic=True,
        failure_modes="none architectural if the evaluator itself is correct - this IS the check that "
                     "catches every other stage's mistakes (P8/P9's central finding)",
        may_mutate_state=False,
        may_decide_geometry=False,
    ),
    StageContract(
        stage="SCENE",
        input_contract="N/A - the accumulated state itself",
        output_contract="Scene (pydantic, canonical, lossless-serializable)",
        authority="whichever stage last wrote it (SOLVER or REPAIR_RE_SOLVE only)",
        evidence_provenance="per-field, inherited from whichever stage wrote each field",
        confidence="per-object Confidence field",
        deterministic=True,
        failure_modes="REPRESENTATION_FAILURE if the schema cannot express a true fact",
        may_mutate_state=True,   # is the state
        may_decide_geometry=False,
    ),
    StageContract(
        stage="BLENDER",
        input_contract="Scene -> manifest (app.blender.manifest.build_manifest)",
        output_contract="a .blend file + a read-back report (object bboxes, floor contact, dims)",
        authority="app.blender.runner.BlenderRunner + blender/scripts/build_scene.py - execution only",
        evidence_provenance="read-back is MEASURED from the built mesh, never assumed executed",
        confidence="N/A",
        deterministic=True,   # measured XY error p95 0.015 m, effectively deterministic at that tolerance
        failure_modes="BLENDER_EXECUTION_FAILURE - build error, missing texture, geometry mismatch",
        may_mutate_state=False,   # writes a file, not the in-memory Scene
        may_decide_geometry=False,
    ),
)


def get_stage(name: str) -> Optional[StageContract]:
    return next((s for s in PIPELINE_STAGES if s.stage == name), None)


# ── §4: at least 10 traced evidence -> decision provenance chains ────────

@dataclass(frozen=True)
class DecisionTrace:
    name: str
    evidence: str
    interpretation: str
    geometric_hypothesis: str
    relation: str
    intent: str
    constraint: str
    candidate: str
    solver_decision: str
    validation_result: str
    explainable_without_llm: bool = True


def trace_ten_decisions() -> list[DecisionTrace]:
    """Builds 10 traces from REAL, already-tested P1/P4/P5/P7/P8/P9 output -
    never a fabricated example. Each trace's fields are read directly off
    the objects those functions return."""
    from research.spatial_architecture.constraint_benchmark import (
        brief_end_to_end_demo, photo_end_to_end_demo)
    from research.spatial_architecture.repair_benchmark import CASES as REPAIR_CASES
    from research.spatial_architecture.repair_engine import repair_scene
    from research.spatial_architecture.scene_graph import (
        build_demonstration_scene, recompute_relations)
    from research.spatial_architecture.wall_geometry import TiltedWall, up_from_normal

    traces: list[DecisionTrace] = []

    # 1-3: P7's demonstration scene - AGAINST_WALL, FACES(unresolved), ADJACENT_TO
    demo = build_demonstration_scene()
    recomputed, _changes = recompute_relations(demo)
    for rel in recomputed.relations:
        obj = recomputed.scene.object(rel.subject_id)
        traces.append(DecisionTrace(
            name=f"p7_demo_{rel.predicate.lower()}",
            evidence="synthetic demonstration geometry (P7) - stands in for measured MoGe/SAM evidence",
            interpretation=f"GeometricRelation classified as {rel.kind.value}",
            geometric_hypothesis=f"subject {rel.subject_id} at {obj.position if obj else '?'}",
            relation=f"{rel.predicate}({rel.subject_id}, {rel.object_id or '-'})",
            intent="N/A - this relation is geometry-derived, not from a stated request" if rel.source != "semantic"
                  else f"stated hint: {rel.note}",
            constraint="N/A - P7 predates P8's Constraint type; relation status IS the verdict here",
            candidate="N/A - object already placed at demo-construction time",
            solver_decision=f"Confidence.source={obj.confidence.source if obj else '?'}",
            validation_result=f"relation status={rel.status.value}",
        ))

    # 4-7: P9's brief demo - FACES, BETWEEN, NEAR (satisfied), NEAR (infeasible)
    brief = brief_end_to_end_demo(regenerate=True)
    for cid, verdict in brief["constraint_verdicts"].items():
        msg = brief["constraint_messages"][cid]
        traces.append(DecisionTrace(
            name=f"p9_brief_{cid[-8:]}",
            evidence="brief text: 'sofa facing the TV, coffee table between them, two chairs near the sofa'",
            interpretation="USER_ASSERTED Intent, one per named relation",
            geometric_hypothesis="entity resolution against the ObjectPlan (P8 §5)",
            relation="see constraint_compiler.PREDICATE_TO_TYPE mapping",
            intent=f"USER_ASSERTED (constraint_id={cid})",
            constraint="compiled via constraint_compiler.compile_intents",
            candidate="production's own _relation_candidates('facing'/'beside') or "
                     "candidate_generators.distance_candidates/between_candidates (P9)",
            solver_decision="app.planning.compiler.place_objects, then (for DISTANCE/POSITION) "
                           "candidate_generators.regenerate_after_placement",
            validation_result=f"{verdict}: {msg}",
        ))

    # 8: photo path - model hypothesis vs. measured geometry, independently agreeing
    photo = photo_end_to_end_demo()
    traces.append(DecisionTrace(
        name="p9_photo_mirror_wall_contact",
        evidence="synthetic grounding result in the shape scene_from_photo.BridgeResult produces "
                "(P7's own demonstration convention)",
        interpretation=f"P7 relation status={photo['p7_relation_status']}, kind={photo['p7_relation_kind']}",
        geometric_hypothesis="mirror footprint + wall plane (P1/P5/P6 geometry)",
        relation="AGAINST_WALL(mirror, wall) - geometry-sourced",
        intent="MODEL_INFERRED: \"the mirror is against the wall\" (a VLM's own claim, kept separate)",
        constraint="CONTACT constraint compiled from the MODEL_INFERRED intent",
        candidate="N/A - object already grounded/placed by the photo bridge",
        solver_decision="N/A - observed geometry, not solver-placed",
        validation_result=f"independent verdict={photo['p8_constraint_verdict']}, "
                          f"error_m={photo['p8_constraint_error_m']}",
    ))

    # 9: P4 repair - a real collision-driven decision, escalation-ladder provenance
    repair_name, repair_builder = REPAIR_CASES[0]
    scene, entrance_xz, relations, _expected = repair_builder()
    result = repair_scene(scene, relations=relations, entrance_xz=entrance_xz)
    record_summary = ("no records (already valid)" if not result.records else
                      f"{result.records[0].repair_type} at level {result.records[0].level}: "
                      f"{result.records[0].cause}")
    traces.append(DecisionTrace(
        name=f"p4_repair_{repair_name}",
        evidence="synthetic adversarial collision scene (P4's own frozen benchmark fixture)",
        interpretation="collect_hard_failures classifies the violation code",
        geometric_hypothesis="classify_and_get_movers picks the lower-confidence mover",
        relation="wall/object relation dict, if any, read via _wall_by_object",
        intent="N/A - repair responds to a VALIDATION failure, not a stated request",
        constraint="N/A - P4 predates P8's Constraint type; the hard Violation IS the requirement here",
        candidate="_lattice_candidates / find_valid_nudge (P1's own lattice, reused)",
        solver_decision=record_summary,
        validation_result=f"terminal_state={result.terminal_state}, hard {result.hard_before} -> {result.hard_after}",
    ))

    # 10: P5 wall-tilt representation decision
    normal = (0.06009, 0.1888, -0.98018)   # the real measured 11-degree-tilt normal, P5's own benchmark value
    wall = TiltedWall(wall_id="w_tilt", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=up_from_normal(normal))
    traces.append(DecisionTrace(
        name="p5_wall_tilt_representation",
        evidence="a real measured wall-plane normal from the frozen 21-image benchmark "
                "(the ~11 degree tilt that caused false COLLIDES_WALL residuals pre-P5)",
        interpretation="up_from_normal projects world-up onto the wall's own fitted plane",
        geometric_hypothesis="TiltedWall.extrusion_direction - a superset of the flat Wall schema",
        relation="N/A - this is a GEOMETRIC_INVARIANT (the wall's own shape), not a relation between entities",
        intent="N/A",
        constraint="N/A",
        candidate="N/A - this trace is about REPRESENTATION, not placement",
        solver_decision="N/A",
        validation_result=f"extrusion_direction={wall.extrusion_direction} (research-layer only - "
                          f"production Scene.Wall still has no tilt field, see failure_taxonomy.py)",
    ))

    return traces


__all__ = ["StageContract", "PIPELINE_STAGES", "get_stage", "DecisionTrace", "trace_ten_decisions"]

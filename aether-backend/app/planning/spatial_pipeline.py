"""Production glue between `place_objects` and the migrated spatial engine.

Three pure functions, called by the `scene_plan` job after the solver has
decided positions. None of them writes files or changes the authority
hierarchy: `place_objects` still decides geometry, `repair_scene` (P4) only
moves objects that are in hard violation and only to positions
`validate_object` accepts, and the intent evaluator (P8) is strictly read-only.

  repair_placement        SOLVER -> VALIDATION -> REPAIR / RE-SOLVE
  evaluate_plan_intents   INDEPENDENT INTENT EVALUATION
  spatial_scene_artifact  SPATIAL SCENE (P7 relations, consistency, canonical JSON)

Intent derivation is deliberately narrow: only a plan relation type with an
exact, validated predicate inverse AND matching semantics becomes an intent.
Today that is `facing` <-> FACES (P9 §14). `beside` / `in_front_of` / `around`
/ `under` have no validated predicate. `against_wall` HAS a predicate
(AGAINST_WALL -> CONTACT) but the P7/P8 verifier measures the object CENTRE to
the wall with P7's 0.25 m staleness tolerance, while `place_objects` puts wall
objects flush by footprint EDGE: measured on the frozen 12-brief benchmark,
76 of 107 solver-placed wall objects the verifier called VIOLATED sit 0.045 m
from the wall by edge. Evaluating them with the centre metric would report
false failures; changing the metric would redesign a validated evaluator. So
`against_wall` is reported as unsupported with that reason (a stop condition,
recorded as debt), never evaluated with the wrong ruler. A `facing` target
that matches zero or several placed objects is left empty and evaluates to
UNKNOWN (ambiguous target), never to the first match.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from ..intelligence.schema import ObjectPlan
from ..scene.patches import AddObjectOp
from ..scene.schema import Scene, SceneObject
from ..spatial.relation_model import GeometricRelation, RelationStatus, classify, relation_id
from ..spatial.repair_engine import repair_scene
from ..spatial.scene_consistency import check_consistency
from ..spatial.scene_model import SpatialScene
from ..spatial.scene_serialization import SCHEMA_VERSION, to_canonical_dict
from .constraint_compiler import compile_intents
from .constraint_evaluator import evaluate_all
from .intent_model import Intent, IntentSource

SPATIAL_CHECK_VERSION = "spatial_check.1"

#: The only plan relation type with an exact validated predicate AND matching
#: semantics (P9 §14). See the module docstring for why `against_wall` is not here.
RELATION_TO_PREDICATE: dict[str, str] = {"facing": "FACES"}

#: Why each other production `RelationType` is reported, not evaluated.
UNSUPPORTED_REASONS: dict[str, str] = {
    "against_wall": "P8 CONTACT verifier is centre-to-wall (P7 0.25 m tolerance); solver places "
                    "wall objects flush by footprint edge - semantics differ, not evaluated",
    "beside": "no validated predicate (P8 NEAR needs an explicit distance_m)",
    "in_front_of": "no validated predicate",
    "around": "no validated predicate",
    "under": "no validated predicate (P8 SUPPORT is subject-on-surface, not under)",
}


def _tentative(scene: Scene, ops: list[AddObjectOp]) -> Scene:
    return scene.model_copy(update={"objects": list(scene.objects) + [op.object for op in ops]})


def repair_placement(scene: Scene, ops: list[AddObjectOp]) -> tuple[list[AddObjectOp], dict[str, Any]]:
    """P4 repair on the solver's output before it is committed. Objects the
    repair moved are rewritten in their `AddObjectOp`; everything else is
    returned untouched (identity, not a copy). `commit_patch` remains the
    gate: a residual violation is still dropped there, as before."""
    result = repair_scene(_tentative(scene, ops))
    repaired = {o.object_id: o for o in result.scene.objects}
    moved: list[str] = []
    out: list[AddObjectOp] = []
    for op in ops:
        after = repaired.get(op.object.object_id)
        if after is not None and (after.position != op.object.position or after.rotation_y != op.object.rotation_y):
            moved.append(op.object.object_id)
            out.append(op.model_copy(update={"object": after}))
        else:
            out.append(op)
    summary = {
        "terminal_state": result.terminal_state,
        "hard_before": result.hard_before,
        "hard_after": result.hard_after,
        "moved": moved,
        "escalation_level_reached": result.escalation_level_reached,
        "nodes_explored": result.nodes_explored,
        "records": [asdict(r) for r in result.records],
    }
    return out, summary


def derive_intents(scene: Scene, plan: ObjectPlan) -> tuple[list[Intent], dict[str, int]]:
    items = {item.object_key: item for item in plan.items}
    by_key: dict[str, list[SceneObject]] = {}
    for o in scene.objects:
        by_key.setdefault((o.plan_key or "").split("#")[0], []).append(o)
    intents: list[Intent] = []
    unsupported: dict[str, int] = {}
    for o in sorted(scene.objects, key=lambda x: x.object_id):
        item = items.get((o.plan_key or "").split("#")[0])
        if item is None or item.relation is None:
            continue
        rtype = str(item.relation.type)
        predicate = RELATION_TO_PREDICATE.get(rtype)
        if predicate is None:
            unsupported[rtype] = unsupported.get(rtype, 0) + 1
            continue
        targets = by_key.get(item.relation.target_key or "", [])
        target_id = targets[0].object_id if len(targets) == 1 else ""
        note = f"target_key={item.relation.target_key!r} matched {len(targets)} placed object(s)"
        intents.append(Intent.create(
            o.object_id, predicate, target_id, source=IntentSource.MODEL_INFERRED,
            provenance=f"object_plan item {item.object_key} relation {rtype}; {note}",
            confidence="MEDIUM"))
    return intents, unsupported


def evaluate_plan_intents(scene: Scene, plan: ObjectPlan) -> dict[str, Any]:
    """Read-only. Compiles the plan's own relations into P8 constraints and
    evaluates them against the FINAL committed scene. Never moves anything."""
    intents, unsupported = derive_intents(scene, plan)
    spatial = SpatialScene(scene=scene)
    constraint_set = compile_intents(spatial, intents)
    results = evaluate_all(constraint_set.constraints, spatial)
    by_id = {c.constraint_id: c for c in constraint_set.constraints}
    rows = []
    counts = {"satisfied": 0, "violated": 0, "unknown": 0, "partial": 0}
    for r in results:
        c = by_id[r.constraint_id]
        verdict = str(r.verdict.value)
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append({
            "constraint_id": r.constraint_id,
            "subject_id": c.subject_id,
            "target_id": c.target_id,
            "constraint_type": str(c.constraint_type.value),
            "verdict": verdict,
            "error": r.error,
            "error_kind": r.error_kind,
            "message": r.message,
        })
    return {
        **counts,
        "unsupported_relations": unsupported,
        "unsupported_reasons": {k: UNSUPPORTED_REASONS.get(k, "no validated predicate") for k in unsupported},
        "conflicts": [asdict(x) for x in constraint_set.conflicts],
        "results": rows,
    }


def spatial_scene_artifact(scene: Scene) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """P7 SpatialScene over the committed scene. The one relation the brief
    path has real evidence for is SUPPORTED_BY, decided by the solver itself
    (`SceneObject.parent_id`); nothing else is fabricated."""
    relations = []
    for o in sorted(scene.objects, key=lambda x: x.object_id):
        if not o.parent_id:
            continue
        relations.append(GeometricRelation(
            relation_id=relation_id(o.object_id, "SUPPORTED_BY", o.parent_id),
            subject_id=o.object_id, predicate="SUPPORTED_BY", object_id=o.parent_id,
            kind=classify("SUPPORTED_BY", "placement"), status=RelationStatus.DERIVED,
            confidence="HIGH", source="placement",
            provenance="place_objects._pick_support via SceneObject.parent_id",
            verified_at_position=o.position))
    spatial = SpatialScene(scene=scene).with_relations(tuple(relations))
    findings = [asdict(f) for f in check_consistency(spatial)]
    return to_canonical_dict(spatial), findings


def spatial_check(scene: Scene, plan: ObjectPlan, repair: Optional[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The two artifacts `scene_plan` persists: the check summary and the
    canonical P7 scene."""
    canonical, findings = spatial_scene_artifact(scene)
    check = {
        "schema_version": SPATIAL_CHECK_VERSION,
        "spatial_scene_schema": SCHEMA_VERSION,
        "repair": repair,
        "intent": evaluate_plan_intents(scene, plan),
        "consistency": findings,
    }
    return check, canonical


__all__ = ["RELATION_TO_PREDICATE", "UNSUPPORTED_REASONS", "SPATIAL_CHECK_VERSION", "repair_placement", "derive_intents",
           "evaluate_plan_intents", "spatial_scene_artifact", "spatial_check"]

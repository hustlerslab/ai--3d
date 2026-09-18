"""P8 benchmark: performance, 20-repeat determinism, >=30 named adversarial
scenarios, and the two required end-to-end demonstrations (brief path,
photo path) for the intent/constraint layer.

    python -u research/spatial_architecture/constraint_benchmark.py

Mirrors this program's established shape (P7's scene_benchmark.py): measures
this phase's own new code only; the frozen P0-P7 benchmarks are re-run
separately, unmodified, and reported in docs/spatial_architecture/decisions.md.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace as dc_replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.intelligence.schema import (                                         # noqa: E402
    AssetDecision, AssetPlan, ObjectPlan, ObjectPlanItem)
from app.planning.compiler import place_objects                              # noqa: E402
from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall      # noqa: E402
from research.spatial_architecture.constraint_compiler import (              # noqa: E402
    apply_constraints_to_plan, compile_intents)
from research.spatial_architecture.constraint_evaluator import evaluate_all  # noqa: E402
from research.spatial_architecture.intent_model import Intent, IntentSource  # noqa: E402
from research.spatial_architecture.repair_engine import repair_scene         # noqa: E402
from research.spatial_architecture.scene_from_photo import grounding_to_scene  # noqa: E402,F401
from research.spatial_architecture.scene_graph import from_bridge_result     # noqa: E402
from research.spatial_architecture.scene_model import SpatialScene           # noqa: E402

OUT = Path(__file__).resolve().parent / "constraint_benchmark_results.json"


def _move(spatial: SpatialScene, object_id: str, position) -> SpatialScene:
    obj = spatial.scene.object(object_id)
    moved = obj.model_copy(update={"position": position})
    others = [o for o in spatial.scene.objects if o.object_id != object_id]
    new_scene = spatial.scene.model_copy(update={"objects": others + [moved]})
    return dc_replace(spatial, scene=new_scene)


# ── shared fixtures ──────────────────────────────────────────────────────

def _room_and_wall():
    room = Room(room_id="room_a", name="Room", type="living_room",
               boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])
    wall_a = Wall(wall_id="wall_a", start=(-3.0, -3.0), end=(3.0, -3.0))
    wall_b = Wall(wall_id="wall_b", start=(-3.0, -3.0), end=(-3.0, 3.0))
    # a non-axis-aligned ("tilted" in plan view) wall segment, for scenario 6 -
    # Scene.Wall carries no 3D tilt field (see constraint_contract.md's
    # "AGAINST_WALL tilted wall" note); this exercises the CONTACT evaluator
    # against a wall whose segment is not cardinal, which axis-aligned test
    # scenes never do.
    wall_diag = Wall(wall_id="wall_diag", start=(1.0, 3.0), end=(3.0, 1.0))
    return room, wall_a, wall_b, wall_diag


def _obj(oid, pos, semantic_type="chair", rotation_y=0.0, dims=(0.45, 0.9, 0.5),
        asset_id=None, confidence=0.8, parent_id=None, mount="floor") -> SceneObject:
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="room_a",
                      position=pos, rotation_y=rotation_y, dimensions=dims, asset_id=asset_id,
                      parent_id=parent_id, mount=mount, confidence=Confidence(value=confidence))


def _scene(objects, walls=None) -> Scene:
    room, wall_a, wall_b, wall_diag = _room_and_wall()
    return Scene(scene_id="scene_adv", project_id="proj_adv", name="adversarial", rooms=[room],
                walls=list(walls) if walls is not None else [wall_a, wall_b, wall_diag],
                objects=objects)


def _spatial(objects, walls=None) -> SpatialScene:
    return SpatialScene(scene=_scene(objects, walls))


def _run(spatial: SpatialScene, intents: list[Intent]):
    cs = compile_intents(spatial, intents)
    results = evaluate_all(cs.constraints, spatial)
    return cs, results


def _verdicts(results) -> list[str]:
    return [r.verdict.value for r in results]


# ── >=30 named adversarial scenarios ──────────────────────────────────────
#
# Each scenario returns (actual: dict, expected: dict); the harness compares
# key-by-key so heterogeneous checks (verdicts, conflict codes, unsupported
# counts, priority ordering) share one runner.

def _scenarios() -> list[tuple[str, "callable"]]:

    def s01_faces():
        sofa = _obj("sofa", (0, 0, 0), "sofa", rotation_y=3.14159265)  # forward flips to +Z
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="user text")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s02_faces_opposite():
        sofa = _obj("sofa", (0, 0, 0), "sofa", rotation_y=0.0)   # forward -Z
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")                  # target is +Z: opposite
        spatial = _spatial([sofa, tv])
        i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results), "error": round(results[0].error)}, \
               {"verdicts": ["violated"], "error": 180}

    def s03_faces_90deg():
        import math
        sofa = _obj("sofa", (0, 0, 0), "sofa", rotation_y=math.pi / 2)
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results), "error": round(results[0].error)}, \
               {"verdicts": ["violated"], "error": 90}

    def s04_faces_same_position():
        sofa = _obj("sofa", (0, 0, 0), "sofa")
        tv = _obj("tv", (0, 0, 0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["unknown"]}

    def s05_against_wall():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s06_against_wall_diagonal():
        # a point flush against the diagonal wall_diag segment
        obj = _obj("chair", (2.0, 0, 2.0), "chair")
        spatial = _spatial([obj])
        i = Intent.create("chair", "AGAINST_WALL", "wall_diag", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s07_support():
        table = _obj("table", (0, 0, 0), "coffee_table", dims=(1.1, 0.42, 0.6))
        lamp = _obj("lamp", (0, 0.42, 0), "table_lamp", dims=(0.2, 0.3, 0.2), parent_id="table")
        spatial = _spatial([table, lamp])
        i = Intent.create("lamp", "SUPPORTED_BY", "table", source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s08_inside():
        obj = _obj("chair", (0, 0, 0), "chair")
        spatial = _spatial([obj])
        i = Intent.create("chair", "INSIDE", "room_a", source=IntentSource.DERIVED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s09_near_no_distance():
        a, b = _obj("a", (0, 0, 0)), _obj("b", (0.5, 0, 0))
        spatial = _spatial([a, b])
        i = Intent.create("a", "NEAR", "b", source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["unknown"]}

    def s10_explicit_distance():
        a, b = _obj("a", (0, 0, 0)), _obj("b", (1.5, 0, 0))
        spatial = _spatial([a, b])
        i = Intent.create("a", "NEAR", "b", parameters={"distance_m": 1.5},
                          source=IntentSource.USER_ASSERTED, provenance="user said 1.5m")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s11_between():
        sofa = _obj("sofa", (0, 0, -2.0), "sofa")
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        table = _obj("table", (0, 0, 0), "coffee_table")
        spatial = _spatial([sofa, tv, table])
        i = Intent.create("table", "BETWEEN", "", parameters={"between_a_id": "sofa", "between_b_id": "tv"},
                          source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["satisfied"]}

    def s12_centered_on_wall_unsupported():
        obj = _obj("art", (0, 1.5, -2.9), "wall_art", mount="wall")
        spatial = _spatial([obj])
        i = Intent.create("art", "CENTERED_ON_WALL", "wall_a", source=IntentSource.MODEL_INFERRED, provenance="x")
        cs, _results = _run(spatial, [i])
        return {"unsupported": len(cs.unsupported)}, {"unsupported": 1}

    def s13_contradictory_orientation():
        sofa = _obj("sofa", (0, 0, 0), "sofa")
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        window = _obj("window_obj", (2.0, 0, 0), "other")
        spatial = _spatial([sofa, tv, window])
        i1 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("sofa", "FACES", "window_obj", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, _results = _run(spatial, [i1, i2])
        return {"conflict_codes": sorted({c.code for c in cs.conflicts})}, \
               {"conflict_codes": ["CONFLICTING_ORIENTATION"]}

    def s14_hard_soft_conflict_independence():
        """A SOFT constraint violation must never affect HARD validate_scene."""
        from app.spatial.validation import validate_scene
        sofa = _obj("sofa", (0, 0, 0), "sofa", rotation_y=0.0)   # faces away from tv: violates soft FACES
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        _cs, results = _run(spatial, [i])
        hard_violations = validate_scene(spatial.scene)
        return {"soft_verdict": results[0].verdict.value, "hard_violation_count": len(hard_violations)}, \
               {"soft_verdict": "violated", "hard_violation_count": 0}

    def s15_user_vs_model_precedence():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        spatial = _spatial([sofa])
        i_user = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="user")
        i_model = Intent.create("sofa", "AGAINST_WALL", "wall_b", source=IntentSource.MODEL_INFERRED, provenance="model")
        cs, _results = _run(spatial, [i_model, i_user])   # inserted model-first on purpose
        ordered = sorted(cs.constraints, key=lambda c: c.priority)
        return {"highest_precedence_source": ordered[0].provenance.split("(")[-1].rstrip(")"),
               "conflict_detected": any(c.code == "CONFLICTING_WALL_CONTACT" for c in cs.conflicts)}, \
               {"highest_precedence_source": "user", "conflict_detected": True}

    def s16_observation_vs_intent_not_merged():
        tv = _obj("tv", (0, 0, -2.9), "tv_unit")   # observed: against wall_a
        spatial = _spatial([tv])
        i_observed = Intent.create("tv", "AGAINST_WALL", "wall_a", source=IntentSource.OBSERVED,
                                   provenance="photo: TV seen on wall_a")
        i_intent = Intent.create("tv", "AGAINST_WALL", "wall_b", source=IntentSource.USER_ASSERTED,
                                 provenance="user: move the TV to wall_b")
        cs, _results = _run(spatial, [i_observed, i_intent])
        return {"n_constraints": len(cs.constraints), "scene_unchanged_object_count": len(spatial.scene.objects)}, \
               {"n_constraints": 2, "scene_unchanged_object_count": 1}

    def s17_stale_constraint():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, before = _run(spatial, [i])
        moved = _move(spatial, "sofa", (0, 0, 0))
        after = evaluate_all(cs.constraints, moved)
        return {"before": before[0].verdict.value, "after": after[0].verdict.value}, \
               {"before": "satisfied", "after": "violated"}

    def s18_post_repair_reevaluation():
        """A real `repair_scene` call (P4, unmodified) on an ALREADY-VALID
        scene must be a no-op, and re-evaluating afterwards must reproduce
        the same verdict - the well-defined passthrough contract
        (`TerminalState.ALREADY_VALID`), which this checks with a REAL call
        rather than only a simulated move (see s17 for the simulated case).
        Uses a THIN object (0.15 m deep, e.g. a console) rather than s05's
        default 0.5 m depth: with the room's 0.15 m wall thickness and
        AGAINST_WALL_TOLERANCE_M=0.25 m, a 0.5 m-deep object at gap 0.025 m
        (s05's own position) is geometrically INSIDE the wall rectangle even
        though its centre-to-centreline gap is well within tolerance - a
        real, physically consistent fact (a real flush-against-the-wall
        placement has near-zero footprint gap by definition), not a bug;
        this scenario specifically needs a scene `validate_scene` also
        calls genuinely valid, so a thinner object is used to keep both
        checks satisfiable at once."""
        sofa = _obj("sofa", (0, 0, -2.8), "sofa", dims=(0.45, 0.9, 0.15))
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, before = _run(spatial, [i])
        result = repair_scene(spatial.scene, relations=[])
        after_spatial = SpatialScene(scene=result.scene)
        after = evaluate_all(cs.constraints, after_spatial)
        return {"terminal_state": result.terminal_state, "before": before[0].verdict.value,
               "after": after[0].verdict.value}, \
               {"terminal_state": "ALREADY_VALID", "before": "satisfied", "after": "satisfied"}

    def s19_missing_target():
        sofa = _obj("sofa", (0, 0, 0), "sofa")
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "FACES", "ghost", source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["unknown"]}

    def s20_duplicate_object_labels():
        c1 = _obj("c1", (0, 0, -2.9), "chair")
        c2 = _obj("c2", (1.0, 0, -2.9), "chair")
        spatial = _spatial([c1, c2])
        i1 = Intent.create("c1", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("c2", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, results = _run(spatial, [i1, i2])
        return {"n_constraints": len(cs.constraints), "distinct_ids": len({c.constraint_id for c in cs.constraints}),
               "verdicts": sorted(_verdicts(results))}, \
               {"n_constraints": 2, "distinct_ids": 2, "verdicts": ["satisfied", "satisfied"]}

    def s21_camera_frame_predicate_unsupported():
        a, b = _obj("a", (0, 0, 0)), _obj("b", (1, 0, 0))
        spatial = _spatial([a, b])
        i = Intent.create("a", "LEFT_OF", "b", source=IntentSource.MODEL_INFERRED,
                          provenance="camera-frame, never geometric")
        cs, _results = _run(spatial, [i])
        return {"unsupported": len(cs.unsupported)}, {"unsupported": 1}

    def s22_large_unit_mismatch_no_crash():
        a, b = _obj("a", (0, 0, 0)), _obj("b", (1.5, 0, 0))
        spatial = _spatial([a, b])
        i = Intent.create("a", "NEAR", "b", parameters={"distance_m": 150.0},   # e.g. cm mistaken for m
                          source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results), "crashed": False}, {"verdicts": ["violated"], "crashed": False}

    def s23_unsupported_relation():
        a, b = _obj("a", (0, 0, 0)), _obj("b", (1, 0, 0))
        spatial = _spatial([a, b])
        i = Intent.create("a", "GROUPED_WITH", "b", source=IntentSource.MODEL_INFERRED, provenance="x")
        cs, _results = _run(spatial, [i])
        return {"unsupported": len(cs.unsupported)}, {"unsupported": 1}

    def s24_unknown_geometry_missing_room():
        obj = _obj("art", (0, 0, 0))
        spatial = _spatial([obj])
        i = Intent.create("art", "CENTERED_IN_ROOM", "ghost_room", source=IntentSource.MODEL_INFERRED, provenance="x")
        _cs, results = _run(spatial, [i])
        return {"verdicts": _verdicts(results)}, {"verdicts": ["unknown"]}

    def s25_user_asserted_priority():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "AGAINST_WALL", "wall_a", parameters={"distance_m": 1.5},
                          source=IntentSource.USER_ASSERTED, provenance="user text")
        cs, _results = _run(spatial, [i])
        return {"priority": cs.constraints[0].priority}, {"priority": 0}   # USER_EXPLICIT == 0

    def s26_model_inferred_priority():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        spatial = _spatial([sofa])
        i = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.MODEL_INFERRED,
                          provenance="model guess")
        cs, _results = _run(spatial, [i])
        return {"priority": cs.constraints[0].priority}, {"priority": 4}   # MODEL_INFERRED == 4

    def s27_shared_asset_distinct_constraints():
        c1 = _obj("c1", (0, 0, -2.9), "chair", asset_id="cat_chair")
        c2 = _obj("c2", (1.0, 0, -2.9), "chair", asset_id="cat_chair")
        spatial = _spatial([c1, c2])
        i1 = Intent.create("c1", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("c2", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, _results = _run(spatial, [i1, i2])
        return {"distinct_subjects": len({c.subject_id for c in cs.constraints})}, {"distinct_subjects": 2}

    def s28_multiple_constraints_same_object():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa", parent_id=None)
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i1 = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        i3 = Intent.create("sofa", "SUPPORTED_BY", "room_a", source=IntentSource.OBSERVED, provenance="x")
        cs, results = _run(spatial, [i1, i2, i3])
        return {"n_constraints": len(cs.constraints), "n_results": len(results)}, \
               {"n_constraints": 3, "n_results": 3}

    def s29_impossible_wall_capacity():
        sofa = _obj("sofa", (-1.0, 0, -2.9), "sofa", dims=(2.2, 0.85, 0.9))
        bench = _obj("bench", (1.0, 0, -2.9), "bench", dims=(2.2, 0.45, 0.5))
        spatial = _spatial([sofa, bench], walls=[Wall(wall_id="short_wall", start=(-2.0, -3.0), end=(2.0, -3.0))])
        i1 = Intent.create("sofa", "AGAINST_WALL", "short_wall", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("bench", "AGAINST_WALL", "short_wall", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, _results = _run(spatial, [i1, i2])
        return {"conflict_codes": sorted({c.code for c in cs.conflicts})}, \
               {"conflict_codes": ["INFEASIBLE_WALL_CAPACITY"]}

    def s30_deterministic_repeated_compilation():
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        ids_seen = set()
        for _ in range(20):
            spatial = _spatial([sofa, tv])
            i1 = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
            i2 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
            cs, _results = _run(spatial, [i1, i2])
            ids_seen.add(tuple(c.constraint_id for c in cs.constraints))
        return {"distinct_orderings": len(ids_seen)}, {"distinct_orderings": 1}

    return [
        ("faces", s01_faces), ("faces_opposite", s02_faces_opposite),
        ("faces_90deg", s03_faces_90deg), ("faces_same_position", s04_faces_same_position),
        ("against_wall", s05_against_wall), ("against_wall_diagonal_wall", s06_against_wall_diagonal),
        ("support", s07_support), ("inside", s08_inside),
        ("near_no_distance", s09_near_no_distance), ("explicit_distance", s10_explicit_distance),
        ("between", s11_between), ("centered_on_wall_unsupported", s12_centered_on_wall_unsupported),
        ("contradictory_orientation", s13_contradictory_orientation),
        ("hard_soft_conflict_independence", s14_hard_soft_conflict_independence),
        ("user_vs_model_precedence", s15_user_vs_model_precedence),
        ("observation_vs_intent_not_merged", s16_observation_vs_intent_not_merged),
        ("stale_constraint", s17_stale_constraint),
        ("post_repair_reevaluation", s18_post_repair_reevaluation),
        ("missing_target", s19_missing_target), ("duplicate_object_labels", s20_duplicate_object_labels),
        ("camera_frame_predicate_unsupported", s21_camera_frame_predicate_unsupported),
        ("large_unit_mismatch_no_crash", s22_large_unit_mismatch_no_crash),
        ("unsupported_relation", s23_unsupported_relation),
        ("unknown_geometry_missing_room", s24_unknown_geometry_missing_room),
        ("user_asserted_priority", s25_user_asserted_priority),
        ("model_inferred_priority", s26_model_inferred_priority),
        ("shared_asset_distinct_constraints", s27_shared_asset_distinct_constraints),
        ("multiple_constraints_same_object", s28_multiple_constraints_same_object),
        ("impossible_wall_capacity", s29_impossible_wall_capacity),
        ("deterministic_repeated_compilation", s30_deterministic_repeated_compilation),
    ]


def run_adversarial_scenarios() -> list[dict]:
    out = []
    for name, builder in _scenarios():
        try:
            actual, expected = builder()
            passed = actual == expected
        except Exception as exc:  # noqa: BLE001 - a scenario failure IS the finding
            actual, expected, passed = {"exception": str(exc)}, {}, False
        out.append({"name": name, "actual": actual, "expected": expected, "pass": passed})
    return out


# ── determinism ───────────────────────────────────────────────────────────

def determinism_check(runs: int = 20) -> bool:
    signatures = []
    for _ in range(runs):
        sofa = _obj("sofa", (0, 0, -2.9), "sofa")
        tv = _obj("tv", (0, 0, 2.0), "tv_unit")
        spatial = _spatial([sofa, tv])
        i1 = Intent.create("sofa", "AGAINST_WALL", "wall_a", source=IntentSource.USER_ASSERTED, provenance="x")
        i2 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
        cs, results = _run(spatial, [i1, i2])
        sig = (tuple(c.constraint_id for c in cs.constraints), cs.conflicts,
              tuple((r.constraint_id, r.verdict.value, r.error) for r in results))
        signatures.append(sig)
    return all(s == signatures[0] for s in signatures[1:])


# ── performance (§51) ──────────────────────────────────────────────────────

def _synthetic(n_objects: int, n_constraints: int):
    objects = [_obj(f"o{i}", (float(i) * 0.8 - 2.5, 0, -2.9)) for i in range(n_objects)]
    spatial = _spatial(objects)
    intents = []
    for i in range(n_constraints):
        subj = f"o{i % n_objects}"
        if i % 2 == 0:
            intents.append(Intent.create(subj, "AGAINST_WALL", "wall_a",
                                        source=IntentSource.USER_ASSERTED, provenance="perf"))
        else:
            target = f"o{(i + 1) % n_objects}"
            intents.append(Intent.create(subj, "FACES", target, parameters={"n": i},
                                        source=IntentSource.MODEL_INFERRED, provenance="perf"))
    return spatial, intents


def performance_sweep() -> list[dict]:
    results = []
    for n_obj, n_con in ((5, 10), (10, 25), (20, 50), (20, 100)):
        spatial, intents = _synthetic(n_obj, n_con)

        t0 = time.perf_counter()
        cs = compile_intents(spatial, intents)
        compile_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        eval_results = evaluate_all(cs.constraints, spatial)
        eval_ms = (time.perf_counter() - t1) * 1000.0

        results.append({"n_objects": n_obj, "n_constraints_requested": n_con,
                        "n_constraints_compiled": len(cs.constraints),
                        "compile_ms": round(compile_ms, 4), "evaluate_ms": round(eval_ms, 4),
                        "n_results": len(eval_results)})
    return results


# ── §57: end-to-end BRIEF demonstration ────────────────────────────────────

def brief_end_to_end_demo(regenerate: bool = False) -> dict:
    """"Create a living room with a three-seater sofa facing the TV, a
    coffee table between them, and two accent chairs near the sofa."

    USER TEXT -> INTENT -> ENTITY RESOLUTION -> RELATIONS -> CONSTRAINTS ->
    CANDIDATE GENERATION (existing `_relation_candidates`/`_faces_rank`) ->
    EXISTING SOLVER (`place_objects`, unmodified) -> PLACEMENT DECISIONS ->
    VALIDATION (`validate_scene`, unmodified). No raw LLM coordinates at any
    step - every position below is `place_objects`'s own candidate search.

    `regenerate=False` (the default) reproduces this exact P8 control
    result unchanged - kept as the frozen baseline this docstring's own
    numbers describe. `regenerate=True` is the P9 addition
    (`candidate_benchmark.py`): after `place_objects` and the first
    independent evaluation below, any DISTANCE/POSITION constraint that did
    not evaluate SATISFIED is handed to `candidate_generators.
    regenerate_after_placement` - the repair-shaped "remove, generate new
    candidates, validate, re-add" step (§33) - and, if a feasible pose was
    found, the object is moved there before the FINAL (returned) evaluation
    runs. ORIENTATION needs no such step - see `candidate_contract.md`'s
    "critical experiment" for why the P9 fix for FACES lives entirely in
    `apply_constraints_to_plan`'s wiring above, not here.
    """
    room = Room(room_id="living_room", name="Living Room", type="living_room",
               boundary=[(-3.5, -3.0), (3.5, -3.0), (3.5, 3.0), (-3.5, 3.0)])
    wall_tv = Wall(wall_id="wall_tv", start=(-3.5, 3.0), end=(3.5, 3.0))
    scene = Scene(scene_id="scene_brief_demo", project_id="proj_brief_demo", name="brief demo",
                 rooms=[room], walls=[wall_tv])

    # ENTITY RESOLUTION: the brief names four things - a sofa, a TV, a coffee
    # table, two accent chairs. IDs are the entities' own object_key (a real
    # brief-path caller would resolve these against `ObjectPlan`; this demo
    # IS that resolution, made explicit rather than hidden in a prompt).
    items = [
        ObjectPlanItem(object_key="sofa", semantic_type="sofa", room_id="living_room", priority=1),
        ObjectPlanItem(object_key="tv_unit", semantic_type="tv_unit", room_id="living_room", priority=1),
        ObjectPlanItem(object_key="coffee_table", semantic_type="coffee_table", room_id="living_room", priority=2),
        ObjectPlanItem(object_key="chair_1", semantic_type="armchair", room_id="living_room", priority=3),
        ObjectPlanItem(object_key="chair_2", semantic_type="armchair", room_id="living_room", priority=3),
    ]
    plan = ObjectPlan(rooms=["living_room"], items=items, provider="p8_demo")

    decisions = {
        "sofa": (2.1, 0.85, 0.9), "tv_unit": (1.2, 0.5, 0.15),
        "coffee_table": (1.1, 0.42, 0.6), "chair_1": (0.8, 0.8, 0.85), "chair_2": (0.8, 0.8, 0.85),
    }
    asset_plan = AssetPlan(decisions=[
        AssetDecision(object_key=item.object_key, semantic_type=item.semantic_type, strategy="procedural",
                     dimensions=decisions[item.object_key]) for item in items])

    # INTENT: what the user's sentence asks for, named explicitly rather
    # than left as free text a downstream function re-parses.
    intents = [
        Intent.create("sofa", "FACES", "tv_unit", source=IntentSource.USER_ASSERTED,
                     provenance="user brief: 'sofa facing the TV'"),
        Intent.create("coffee_table", "BETWEEN", "",
                     parameters={"between_a_id": "sofa", "between_b_id": "tv_unit"},
                     source=IntentSource.USER_ASSERTED, provenance="user brief: 'coffee table between them'"),
        Intent.create("chair_1", "NEAR", "sofa", parameters={"distance_m": 1.2},
                     source=IntentSource.USER_ASSERTED, provenance="user brief: 'accent chairs near the sofa'"),
        Intent.create("chair_2", "NEAR", "sofa", parameters={"distance_m": 1.2},
                     source=IntentSource.USER_ASSERTED, provenance="user brief: 'accent chairs near the sofa'"),
    ]

    spatial_before = SpatialScene(scene=scene)
    constraint_set = compile_intents(spatial_before, intents)

    # RELATIONS -> CANDIDATE GENERATION: fill the SAME fields the existing
    # solver already reads (§31's bridge - `constraint_compiler.
    # apply_constraints_to_plan`), never a second solver.
    notes = apply_constraints_to_plan(items, constraint_set, spatial_before)

    # EXISTING SOLVER, UNMODIFIED.
    ops, warnings = place_objects(scene, plan, asset_plan)
    final_scene = scene.model_copy(deep=True)
    for op in ops:
        final_scene.objects.append(op.object)

    from app.spatial.validation import validate_scene
    violations = validate_scene(final_scene)

    final_spatial = SpatialScene(scene=final_scene)
    id_map = {(o.plan_key.split("#")[0] if o.plan_key else o.object_id): o.object_id
             for o in final_scene.objects}
    # re-key intents onto the SOLVER'S OWN object_ids (plan_key -> object_id)
    # so the constraints can be re-evaluated against the FINAL placed scene -
    # this is the "constraint re-evaluation after the solver decides" step.
    # `between_a_id`/`between_b_id` live INSIDE `parameters`, not in
    # subject_id/target_id, so they need the same remap or BETWEEN's
    # evaluator would look up plan_keys that no longer exist on the placed
    # SceneObjects.
    def _rekey_params(params: dict) -> dict:
        out = dict(params)
        for key in ("between_a_id", "between_b_id"):
            if key in out:
                out[key] = id_map.get(out[key], out[key])
        return out

    rekeyed_intents = [Intent.create(id_map.get(i.subject_id, i.subject_id), i.predicate,
                                     id_map.get(i.target_id, i.target_id),
                                     parameters=_rekey_params(i.parameters),
                                     source=i.source, provenance=i.provenance, confidence=i.confidence)
                       for i in intents]
    final_constraint_set = compile_intents(final_spatial, rekeyed_intents)
    final_results = evaluate_all(final_constraint_set.constraints, final_spatial)

    regenerated_notes: list[str] = []
    if regenerate:
        from research.spatial_architecture.candidate_generators import regenerate_after_placement
        from research.spatial_architecture.constraint_model import ConstraintType, Verdict

        by_id = {r.constraint_id: r for r in final_results}
        dims_by_key = {item.object_key: decisions[item.object_key] for item in items}
        for c in final_constraint_set.constraints:
            if c.constraint_type not in (ConstraintType.DISTANCE, ConstraintType.POSITION):
                continue
            if by_id[c.constraint_id].verdict == Verdict.SATISFIED:
                continue
            subject = final_spatial.scene.object(c.subject_id)
            plan_key = subject.plan_key.split("#")[0] if subject and subject.plan_key else None
            dims = dims_by_key.get(plan_key, (0.5, 0.5, 0.5))
            pose = regenerate_after_placement(c, final_spatial, dims)
            if pose is None:
                regenerated_notes.append(f"{c.constraint_id}: no feasible regenerated candidate found")
                continue
            x, y, z, yaw = pose
            moved = subject.model_copy(update={"position": (x, y, z), "rotation_y": yaw})
            others = [o for o in final_spatial.scene.objects if o.object_id != c.subject_id]
            new_scene = final_spatial.scene.model_copy(update={"objects": others + [moved]})
            final_spatial = dc_replace(final_spatial, scene=new_scene)
            regenerated_notes.append(f"{c.constraint_id}: regenerated to {(x, y, z)}, yaw={yaw}")

        violations = validate_scene(final_spatial.scene)
        final_results = evaluate_all(final_constraint_set.constraints, final_spatial)

    return {
        "compiler_notes": notes, "solver_warnings": warnings, "regenerated_notes": regenerated_notes,
        "objects_placed": len(ops), "hard_violations": len(violations),
        "constraint_verdicts": {r.constraint_id: r.verdict.value for r in final_results},
        "constraint_messages": {r.constraint_id: r.message for r in final_results},
    }


# ── §58: end-to-end PHOTO demonstration ────────────────────────────────────

def photo_end_to_end_demo() -> dict:
    """IMAGE -> Evidence -> Grounding -> SpatialScene -> model hypothesis ->
    geometric relation -> constraint (only where evidence policy allows) ->
    solver -> validation. Uses a synthetic grounding result (no GPU/model
    call - the photo PIPELINE itself is P1/P6/P7's frozen, already-benchmarked
    code; this demo exercises this phase's NEW intent/constraint layer on its
    output shape, exactly as `scene_graph.build_demonstration_scene` did for
    P7)."""
    room = Room(room_id="room_photo", name="Photo Room", type="living_room",
               boundary=[(-2.5, -2.5), (2.5, -2.5), (2.5, 2.5), (-2.5, 2.5)])
    wall = Wall(wall_id="wall_photo", start=(-2.5, -2.5), end=(2.5, -2.5))
    mirror = SceneObject(object_id="mirror_obs", semantic_type="mirror", room_id="room_photo",
                         position=(0.6, 1.4, -2.3), dimensions=(0.6, 0.9, 0.05), mount="wall",
                         confidence=Confidence(value=0.7, source="geometry"))
    scene = Scene(scene_id="scene_photo_demo", project_id="proj_photo_demo", name="photo demo",
                 rooms=[room], walls=[wall], objects=[mirror])

    raw_relations = [{"subject_id": "mirror_obs", "predicate": "AGAINST_WALL", "object_id": "wall_photo",
                      "confidence": "MEDIUM", "source": "geometry", "note": "measured gap 0.35 m"}]
    spatial = from_bridge_result(scene, raw_relations)

    # MODEL HYPOTHESIS (a VLM's own claim, unverified) - kept as
    # MODEL_INFERRED intent, never silently promoted to a hard fact (§37).
    model_hypothesis = Intent.create("mirror_obs", "AGAINST_WALL", "wall_photo",
                                     source=IntentSource.MODEL_INFERRED,
                                     provenance="VLM: 'the mirror is against the wall'")
    constraint_set = compile_intents(spatial, [model_hypothesis])
    results = evaluate_all(constraint_set.constraints, spatial)

    return {
        "p7_relation_status": spatial.relations[0].status.value,
        "p7_relation_kind": spatial.relations[0].kind.value,
        "p8_constraint_verdict": results[0].verdict.value,
        "p8_constraint_error_m": results[0].error,
        "note": "model hypothesis and P7's own geometry-sourced relation are "
               "evaluated independently and AGREE here by measurement, not "
               "by being merged into one object",
    }


# ── report ────────────────────────────────────────────────────────────────

def main() -> int:
    print("-- performance sweep --", flush=True)
    perf = performance_sweep()
    for e in perf:
        print(f"  objects={e['n_objects']:3} constraints={e['n_constraints_compiled']:4}  "
              f"compile={e['compile_ms']} ms  evaluate={e['evaluate_ms']} ms", flush=True)

    print("\n-- determinism (20 runs) --", flush=True)
    det = determinism_check()
    print(f"  deterministic: {det}", flush=True)

    print("\n-- adversarial scenarios --", flush=True)
    adversarial = run_adversarial_scenarios()
    n_pass = sum(1 for a in adversarial if a["pass"])
    for a in adversarial:
        mark = "OK" if a["pass"] else "FAIL"
        print(f"  [{mark}] {a['name']}: {a['actual']}", flush=True)
    print(f"\n  {n_pass}/{len(adversarial)} adversarial scenarios passed")

    print("\n-- brief end-to-end demo --", flush=True)
    brief = brief_end_to_end_demo()
    print(json.dumps(brief, indent=2), flush=True)

    print("\n-- photo end-to-end demo --", flush=True)
    photo = photo_end_to_end_demo()
    print(json.dumps(photo, indent=2), flush=True)

    payload = {
        "_about": "P8 intent/constraint layer benchmark. P0-P7 benchmarks are "
                 "separate, unmodified scripts.",
        "performance": perf, "deterministic": det,
        "adversarial_pass": n_pass, "adversarial_total": len(adversarial),
        "adversarial": adversarial, "brief_demo": brief, "photo_demo": photo,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    return 0 if (det and n_pass == len(adversarial)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

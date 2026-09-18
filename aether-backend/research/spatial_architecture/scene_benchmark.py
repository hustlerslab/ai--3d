"""P7 benchmark: performance, determinism, and >=20 named adversarial
scene-graph scenarios for the SpatialScene / relation / consistency layer.

    python -u research/spatial_architecture/scene_benchmark.py

Mirrors this program's established benchmark shape (coordinate_benchmark.py,
wall_benchmark.py, repair_benchmark.py): measures this phase's own new code
only, writes a JSON result file, and does not re-run the frozen P1-P6
benchmarks (those remain separate, unmodified scripts - see the P7 final
report for their re-run results).
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

from app.scene.schema import Confidence, Room, Scene, SceneObject, Wall  # noqa: E402
from research.spatial_architecture.relation_model import (               # noqa: E402
    GeometricRelation, RelationStatus, relation_id)
from research.spatial_architecture.scene_consistency import check_consistency  # noqa: E402
from research.spatial_architecture.scene_graph import (                  # noqa: E402
    build_demonstration_scene, from_bridge_result, recompute_relations)
from research.spatial_architecture.scene_model import SpatialScene       # noqa: E402
from research.spatial_architecture.scene_serialization import (          # noqa: E402
    from_canonical_json, to_canonical_json)

OUT = Path(__file__).resolve().parent / "scene_benchmark_results.json"


def _move(spatial: SpatialScene, object_id: str, position) -> SpatialScene:
    """Replace one object's position, pydantic-copy style - the SceneObject
    schema is a pydantic BaseModel, not a dataclass, so `.model_copy` is
    used, never `dataclasses.replace` (which silently does not apply to it)."""
    obj = spatial.scene.object(object_id)
    moved = obj.model_copy(update={"position": position})
    others = [o for o in spatial.scene.objects if o.object_id != object_id]
    new_scene = spatial.scene.model_copy(update={"objects": others + [moved]})
    return dc_replace(spatial, scene=new_scene)


def _remove(spatial: SpatialScene, object_id: str) -> SpatialScene:
    others = [o for o in spatial.scene.objects if o.object_id != object_id]
    new_scene = spatial.scene.model_copy(update={"objects": others})
    return dc_replace(spatial, scene=new_scene)


# ── performance sweep ─────────────────────────────────────────────────────

def _synthetic_scene(n: int) -> SpatialScene:
    """N objects in a row against one wall, deterministic (a simple grid is
    enough to measure lookup/consistency cost, which does not depend on
    layout)."""
    room = Room(room_id="room_perf", name="Perf Room", type="living_room",
               boundary=[(-50.0, -5.0), (50.0, -5.0), (50.0, 5.0), (-50.0, 5.0)])
    wall = Wall(wall_id="wall_perf", start=(-50.0, -5.0), end=(50.0, -5.0))
    objects = [SceneObject(object_id=f"obj_{i}", semantic_type="chair", room_id=room.room_id,
                           position=(float(i) * 0.8, 0.0, -4.9), dimensions=(0.45, 0.9, 0.5),
                           confidence=Confidence(value=0.8))
              for i in range(n)]
    scene = Scene(scene_id=f"scene_perf_{n}", project_id="proj_perf", name="perf",
                 rooms=[room], walls=[wall], objects=objects)
    raw = [{"subject_id": o.object_id, "predicate": "AGAINST_WALL", "object_id": wall.wall_id,
           "confidence": "HIGH", "source": "geometry", "note": "synthetic"} for o in objects]
    return from_bridge_result(scene, raw)


def performance_sweep() -> list[dict]:
    results = []
    for n in (5, 10, 20, 50, 100):
        spatial = _synthetic_scene(n)

        t0 = time.perf_counter()
        recomputed, changes = recompute_relations(spatial)
        recompute_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        findings = check_consistency(recomputed)
        consistency_ms = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        text = to_canonical_json(recomputed)
        serialize_ms = (time.perf_counter() - t2) * 1000.0

        results.append({"n_objects": n, "n_relations": len(spatial.relations),
                        "recompute_ms": round(recompute_ms, 4),
                        "consistency_ms": round(consistency_ms, 4),
                        "serialize_ms": round(serialize_ms, 4),
                        "findings": len(findings), "changes": len(changes),
                        "json_bytes": len(text)})
    return results


# ── determinism ───────────────────────────────────────────────────────────

def determinism_check(runs: int = 20) -> bool:
    signatures = []
    for _ in range(runs):
        spatial = build_demonstration_scene()
        recomputed, _changes = recompute_relations(spatial)
        findings = check_consistency(recomputed)
        sig = (to_canonical_json(recomputed),
              tuple((f.code, f.subject_id, f.object_id) for f in findings))
        signatures.append(sig)
    return all(s == signatures[0] for s in signatures[1:])


# ── >=20 named adversarial scenarios ──────────────────────────────────────

def _room_two_walls() -> tuple[Room, Wall, Wall]:
    room = Room(room_id="room_a", name="Adversarial Room", type="living_room",
               boundary=[(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)])
    wall_a = Wall(wall_id="wall_a", start=(-3.0, -3.0), end=(3.0, -3.0))
    wall_b = Wall(wall_id="wall_b", start=(-3.0, -3.0), end=(-3.0, 3.0))
    return room, wall_a, wall_b


def _obj(oid: str, pos, semantic_type: str = "chair", asset_id=None) -> SceneObject:
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="room_a",
                      position=pos, dimensions=(0.45, 0.9, 0.5), asset_id=asset_id,
                      confidence=Confidence(value=0.8))


def _scene(objects: list[SceneObject], walls=None) -> Scene:
    room, wall_a, wall_b = _room_two_walls()
    return Scene(project_id="proj_adv", name="adversarial", rooms=[room],
                walls=list(walls) if walls is not None else [wall_a, wall_b], objects=objects)


def _rel(subject: str, predicate: str, obj: str = "", **kw) -> dict:
    return {"subject_id": subject, "predicate": predicate, "object_id": obj,
           "confidence": kw.pop("confidence", "MEDIUM"), "source": kw.pop("source", "geometry"),
           "frame": kw.pop("frame", "floor_plan"), "note": kw.pop("note", "")}


#: Each scenario: (name, builder() -> SpatialScene, run_recompute: bool,
#: expected consistency-finding codes as a set - empty means "must be clean").
def _scenarios() -> list[tuple]:

    def s01_against_wall_holds_unmoved():
        o = _obj("o1", (0.0, 0.0, -2.9))
        return from_bridge_result(_scene([o]), [_rel("o1", "AGAINST_WALL", "wall_a")])

    def s02_against_wall_holds_after_jitter():
        spatial = from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                     [_rel("o1", "AGAINST_WALL", "wall_a")])
        return _move(spatial, "o1", (0.01, 0.0, -2.895))

    def s03_against_wall_broken_after_move():
        spatial = from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                     [_rel("o1", "AGAINST_WALL", "wall_a")])
        return _move(spatial, "o1", (0.0, 0.0, 0.0))

    def s04_against_wall_still_true_after_sliding():
        spatial = from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                     [_rel("o1", "AGAINST_WALL", "wall_a")])
        return _move(spatial, "o1", (1.5, 0.0, -2.9))

    def s05_orphan_subject():
        return from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                  [_rel("ghost", "AGAINST_WALL", "wall_a")])

    def s06_orphan_object_wall():
        return from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                  [_rel("o1", "AGAINST_WALL", "wall_missing")])

    def s07_duplicate_relation():
        return from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                  [_rel("o1", "AGAINST_WALL", "wall_a"),
                                   _rel("o1", "AGAINST_WALL", "wall_a")])

    def s08_multiple_wall_claims():
        o = _obj("o1", (-2.9, 0.0, -2.9))   # genuinely near both walls (a corner)
        return from_bridge_result(_scene([o]), [_rel("o1", "AGAINST_WALL", "wall_a"),
                                                _rel("o1", "AGAINST_WALL", "wall_b")])

    def s09_stale_relation_no_rule():
        spatial = from_bridge_result(_scene([_obj("o1", (0.0, 0.0, 0.0), "sofa")]),
                                     [_rel("o1", "SUPPORTED_BY", "room_a", source="placement")])
        return _move(spatial, "o1", (2.0, 0.0, 2.0))

    def s10_unsupported_hypothesis():
        rel = GeometricRelation.from_bridge_dict(
            {"subject_id": "o1", "predicate": "FACES", "object_id": "o2",
             "confidence": "LOW", "source": "semantic", "note": ""}, provenance="")
        return SpatialScene(scene=_scene([_obj("o1", (0, 0, 0)), _obj("o2", (0, 0, -1))]),
                            relations=(rel,))

    def s11_same_category_duplicates_distinct_relations():
        o1, o2 = _obj("c1", (0.0, 0.0, -2.9)), _obj("c2", (2.5, 0.0, -2.9))
        return from_bridge_result(_scene([o1, o2]), [_rel("c1", "AGAINST_WALL", "wall_a"),
                                                     _rel("c2", "AGAINST_WALL", "wall_a")])

    def s12_repair_style_move_breaks_relation():
        # Simulates what resolve_collisions/repair_scene do today: build the
        # relation, then move the object as a collision nudge would, WITHOUT
        # touching the relation - exactly BridgeResult's own shape.
        spatial = from_bridge_result(_scene([_obj("o1", (0.5, 0.0, -2.9))]),
                                     [_rel("o1", "AGAINST_WALL", "wall_a")])
        return _move(spatial, "o1", (0.5, 0.0, -1.2))   # P1-style nudge

    def s13_camera_frame_relation_no_false_positive():
        rel = GeometricRelation.from_bridge_dict(
            {"subject_id": "o1", "predicate": "LEFT_OF", "object_id": "o2",
             "confidence": "MEDIUM", "source": "geometry", "frame": "camera",
             "note": "ordering in the render"}, provenance="app.planning.spatial_graph")
        return SpatialScene(scene=_scene([_obj("o1", (0, 0, 0)), _obj("o2", (1, 0, 0))]),
                            relations=(rel,))

    def s14_object_outside_room_out_of_scope():
        # Room-bounds is validate_scene's job, not this layer's - confirms no
        # false ORPHAN/CONTRADICTED finding is invented for it here.
        o = _obj("o1", (100.0, 0.0, 100.0))
        return from_bridge_result(_scene([o]), [])

    def s15_containment_non_circular():
        rel = GeometricRelation.from_bridge_dict(
            {"subject_id": "cabinet", "predicate": "CONTAINS", "object_id": "book",
             "confidence": "MEDIUM", "source": "geometry", "note": "footprint nesting"},
            provenance="scene_consistency demo")
        return SpatialScene(scene=_scene([_obj("cabinet", (0, 0, 0), "wardrobe"),
                                          _obj("book", (0, 0, 0), "decor")]), relations=(rel,))

    def s16_circular_containment():
        r1 = GeometricRelation.from_bridge_dict(
            {"subject_id": "a", "predicate": "CONTAINS", "object_id": "b",
             "confidence": "LOW", "source": "geometry", "note": "adversarial"}, provenance="x")
        r2 = GeometricRelation.from_bridge_dict(
            {"subject_id": "b", "predicate": "CONTAINS", "object_id": "a",
             "confidence": "LOW", "source": "geometry", "note": "adversarial"}, provenance="x")
        return SpatialScene(scene=_scene([_obj("a", (0, 0, 0)), _obj("b", (0, 0, 0))]),
                            relations=(r1, r2))

    def s17_conflicting_faces():
        r1 = GeometricRelation.from_bridge_dict(
            {"subject_id": "o1", "predicate": "FACES", "object_id": "o2",
             "confidence": "LOW", "source": "semantic", "note": "reader said facing o2"},
            provenance="app.planning.spatial_graph")
        r2 = GeometricRelation.from_bridge_dict(
            {"subject_id": "o1", "predicate": "FACES", "object_id": "o3",
             "confidence": "LOW", "source": "semantic", "note": "reader said facing o3"},
            provenance="app.planning.spatial_graph")
        return SpatialScene(scene=_scene([_obj("o1", (0, 0, 0)), _obj("o2", (1, 0, 0)),
                                          _obj("o3", (-1, 0, 0))]), relations=(r1, r2))

    def s18_stated_hint_vs_measured_geometry_disagree():
        # "user intent" (a stated AGAINST_WALL hint) vs the actual measured
        # position disagreeing - resolved the same way P1/P4 already resolve
        # geometry disputes: recompute against the CURRENT scene wins.
        return from_bridge_result(_scene([_obj("o1", (0.0, 0.0, 0.0))]),
                                  [_rel("o1", "AGAINST_WALL", "wall_a", source="semantic",
                                       confidence="LOW", note="reader said 'against the wall'")])

    def s19_shared_asset_distinct_object_identity():
        o1 = _obj("c1", (0, 0, -2.9), asset_id="cat_chair")
        o2 = _obj("c2", (1.0, 0, -2.9), asset_id="cat_chair")
        return from_bridge_result(_scene([o1, o2]), [_rel("c1", "AGAINST_WALL", "wall_a"),
                                                     _rel("c2", "AGAINST_WALL", "wall_a")])

    def s20_missing_asset_metadata_no_finding():
        o = _obj("o1", (0, 0, 0), semantic_type="rug", asset_id=None)
        return from_bridge_result(_scene([o]), [])

    def s21_deterministic_serialization_round_trip():
        return build_demonstration_scene()

    def s22_orphan_after_object_removed():
        spatial = from_bridge_result(_scene([_obj("o1", (0.0, 0.0, -2.9))]),
                                     [_rel("o1", "AGAINST_WALL", "wall_a")])
        return _remove(spatial, "o1")

    return [
        ("against_wall_holds_unmoved", s01_against_wall_holds_unmoved, True, set()),
        ("against_wall_holds_after_jitter", s02_against_wall_holds_after_jitter, True, set()),
        ("against_wall_broken_after_move", s03_against_wall_broken_after_move, True,
         {"CONTRADICTED_RELATION"}),
        ("against_wall_still_true_after_sliding", s04_against_wall_still_true_after_sliding,
         True, set()),
        ("orphan_subject", s05_orphan_subject, False, {"ORPHAN_REFERENCE"}),
        ("orphan_object_wall", s06_orphan_object_wall, False, {"ORPHAN_REFERENCE"}),
        ("duplicate_relation", s07_duplicate_relation, False, {"DUPLICATE_RELATION"}),
        ("multiple_wall_claims_real_corner", s08_multiple_wall_claims, False,
         {"MULTIPLE_WALL_CLAIMS"}),
        ("stale_relation_no_rule", s09_stale_relation_no_rule, True, {"STALE_RELATION"}),
        ("unsupported_hypothesis", s10_unsupported_hypothesis, False, {"UNSUPPORTED_HYPOTHESIS"}),
        ("same_category_duplicates_distinct_relations",
         s11_same_category_duplicates_distinct_relations, True, set()),
        ("repair_style_move_breaks_relation", s12_repair_style_move_breaks_relation, True,
         {"CONTRADICTED_RELATION"}),
        ("camera_frame_relation_no_false_positive", s13_camera_frame_relation_no_false_positive,
         False, set()),
        ("object_outside_room_out_of_scope", s14_object_outside_room_out_of_scope, True, set()),
        ("containment_non_circular", s15_containment_non_circular, False, set()),
        ("circular_containment", s16_circular_containment, False, {"CIRCULAR_CONTAINMENT"}),
        ("conflicting_faces", s17_conflicting_faces, False, {"CONFLICTING_FACES"}),
        ("stated_hint_vs_measured_geometry_disagree",
         s18_stated_hint_vs_measured_geometry_disagree, True, {"CONTRADICTED_RELATION"}),
        ("shared_asset_distinct_object_identity", s19_shared_asset_distinct_object_identity,
         True, set()),
        ("missing_asset_metadata_no_finding", s20_missing_asset_metadata_no_finding, False, set()),
        ("deterministic_serialization_round_trip", s21_deterministic_serialization_round_trip,
         False, set()),
        ("orphan_after_object_removed", s22_orphan_after_object_removed, False,
         {"ORPHAN_REFERENCE"}),
    ]


def run_adversarial_scenarios() -> list[dict]:
    results = []
    for name, builder, do_recompute, expected in _scenarios():
        spatial = builder()
        if do_recompute:
            spatial, _changes = recompute_relations(spatial)
        findings = check_consistency(spatial)
        codes = {f.code for f in findings}
        # a REAL round trip: serialize, parse back into fresh objects,
        # re-serialize, and require byte-identical text - not merely
        # re-serializing the same in-memory objects twice.
        text = to_canonical_json(spatial)
        round_trip_ok = to_canonical_json(from_canonical_json(text)) == text
        passed = codes == expected and round_trip_ok
        results.append({"name": name, "expected": sorted(expected), "found": sorted(codes),
                        "round_trip_ok": round_trip_ok, "pass": passed})
    return results


# ── report ────────────────────────────────────────────────────────────────

def main() -> int:
    print("-- performance sweep --", flush=True)
    perf = performance_sweep()
    for e in perf:
        print(f"  n={e['n_objects']:4}  recompute={e['recompute_ms']} ms  "
              f"consistency={e['consistency_ms']} ms  serialize={e['serialize_ms']} ms",
              flush=True)

    print("\n-- determinism (20 runs) --", flush=True)
    det = determinism_check()
    print(f"  deterministic: {det}", flush=True)

    print("\n-- adversarial scenarios --", flush=True)
    adversarial = run_adversarial_scenarios()
    n_pass = sum(1 for a in adversarial if a["pass"])
    for a in adversarial:
        mark = "OK" if a["pass"] else "FAIL"
        print(f"  [{mark}] {a['name']}: expected={a['expected']} found={a['found']}", flush=True)
    print(f"\n  {n_pass}/{len(adversarial)} adversarial scenarios passed")

    print("\n-- end-to-end demonstration scene --", flush=True)
    demo = build_demonstration_scene()
    demo_recomputed, demo_changes = recompute_relations(demo)
    demo_findings = check_consistency(demo_recomputed)
    print(f"  objects={len(demo.scene.objects)} walls={len(demo.scene.walls)} "
         f"relations={len(demo.relations)}")
    for r in demo_recomputed.relations:
        print(f"    {r.subject_id} {r.predicate} {r.object_id or '-'}  "
             f"kind={r.kind.value} status={r.status.value} conf={r.confidence}")
    print(f"  consistency findings: {len(demo_findings)}")

    payload = {
        "_about": "P7 SpatialScene/relation/consistency layer benchmark. "
                 "P1-P6 benchmarks are separate, unmodified scripts.",
        "performance": perf, "deterministic": det,
        "adversarial_pass": n_pass, "adversarial_total": len(adversarial),
        "adversarial": adversarial,
        "demonstration_scene": {
            "objects": len(demo.scene.objects), "walls": len(demo.scene.walls),
            "relations": len(demo.relations), "changes_on_recompute": demo_changes,
            "consistency_findings": len(demo_findings)},
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    return 0 if (det and n_pass == len(adversarial)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

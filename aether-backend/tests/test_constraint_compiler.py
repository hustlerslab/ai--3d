"""Deterministic checks for constraint_compiler.py: compilation, conflict
detection, wall-capacity feasibility, and the candidate-generation bridge.
No GPU, no models.
"""
from __future__ import annotations

from app.intelligence.schema import ObjectPlanItem
from app.scene.schema import Room, Scene, SceneObject, Wall
from app.planning.constraint_compiler import (
    PREDICATE_TO_TYPE, apply_constraints_to_plan, compile_intents)
from app.planning.constraint_model import ConstraintType, Hardness
from app.planning.intent_model import Intent, IntentSource
from app.spatial.scene_model import SpatialScene


def _scene(objects, walls=None):
    room = Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-3, -3), (3, -3), (3, 3), (-3, 3)])
    wall = Wall(wall_id="w1", start=(-3, -3), end=(3, -3))
    return Scene(scene_id="s1", project_id="p1", name="t", rooms=[room],
                walls=list(walls) if walls is not None else [wall], objects=objects)


def _obj(oid, pos, semantic_type="chair", dims=(0.45, 0.9, 0.5)):
    return SceneObject(object_id=oid, semantic_type=semantic_type, room_id="r1",
                      position=pos, dimensions=dims)


def test_compile_known_predicate_produces_a_constraint():
    spatial = SpatialScene(scene=_scene([_obj("sofa", (0, 0, -2.9))]))
    i = Intent.create("sofa", "AGAINST_WALL", "w1", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i])
    assert len(cs.constraints) == 1
    assert cs.constraints[0].constraint_type == ConstraintType.CONTACT
    assert cs.unsupported == ()


def test_compile_unknown_predicate_is_recorded_not_dropped():
    spatial = SpatialScene(scene=_scene([_obj("a", (0, 0, 0))]))
    i = Intent.create("a", "GROUPED_WITH", "b", source=IntentSource.MODEL_INFERRED, provenance="x")
    cs = compile_intents(spatial, [i])
    assert cs.constraints == ()
    assert cs.unsupported == (i.intent_id,)


def test_every_compiled_constraint_is_soft():
    spatial = SpatialScene(scene=_scene([_obj("sofa", (0, 0, -2.9))]))
    for predicate in PREDICATE_TO_TYPE:
        i = Intent.create("sofa", predicate, "w1", source=IntentSource.USER_ASSERTED, provenance="x")
        cs = compile_intents(spatial, [i])
        assert cs.constraints[0].hardness == Hardness.SOFT


def test_constraint_carries_intent_provenance_chain():
    spatial = SpatialScene(scene=_scene([_obj("sofa", (0, 0, -2.9))]))
    i = Intent.create("sofa", "AGAINST_WALL", "w1", source=IntentSource.USER_ASSERTED,
                      provenance="user said 'against the wall'")
    cs = compile_intents(spatial, [i])
    c = cs.constraints[0]
    assert i.intent_id in c.provenance
    assert "user said" in c.provenance
    assert c.source_intent_id == i.intent_id


def test_conflicting_orientation_detected():
    spatial = SpatialScene(scene=_scene([_obj("sofa", (0, 0, 0)), _obj("tv", (0, 0, 2)),
                                         _obj("window", (2, 0, 0))]))
    i1 = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
    i2 = Intent.create("sofa", "FACES", "window", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i1, i2])
    assert any(c.code == "CONFLICTING_ORIENTATION" for c in cs.conflicts)


def test_wall_capacity_feasibility_flags_oversubscribed_wall():
    short_wall = Wall(wall_id="short", start=(-1.0, -3.0), end=(1.0, -3.0))
    a = _obj("a", (-0.5, 0, -2.9), dims=(1.5, 0.9, 0.9))
    b = _obj("b", (0.5, 0, -2.9), dims=(1.5, 0.9, 0.9))
    spatial = SpatialScene(scene=_scene([a, b], walls=[short_wall]))
    i1 = Intent.create("a", "AGAINST_WALL", "short", source=IntentSource.USER_ASSERTED, provenance="x")
    i2 = Intent.create("b", "AGAINST_WALL", "short", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i1, i2])
    assert any(c.code == "INFEASIBLE_WALL_CAPACITY" for c in cs.conflicts)


def test_wall_capacity_feasibility_clean_when_wall_has_room():
    wall = Wall(wall_id="w1", start=(-3.0, -3.0), end=(3.0, -3.0))
    a = _obj("a", (0, 0, -2.9), dims=(1.0, 0.9, 0.9))
    spatial = SpatialScene(scene=_scene([a], walls=[wall]))
    i = Intent.create("a", "AGAINST_WALL", "w1", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i])
    assert not any(c.code == "INFEASIBLE_WALL_CAPACITY" for c in cs.conflicts)


def test_compile_intents_never_mutates_the_scene():
    scene = _scene([_obj("sofa", (0, 0, -2.9))])
    spatial = SpatialScene(scene=scene)
    before = list(scene.objects)
    i = Intent.create("sofa", "AGAINST_WALL", "w1", source=IntentSource.USER_ASSERTED, provenance="x")
    compile_intents(spatial, [i])
    assert scene.objects == before


def test_apply_constraints_to_plan_never_overwrites_existing_fields():
    """Matches `apply_spatial_graph`'s own rule one stage upstream: never
    overwrite what the planner already decided."""
    from app.intelligence.schema import ObjectRelation
    already = ObjectRelation(type="beside", target_key="someone_else")
    items = [ObjectPlanItem(object_key="sofa", semantic_type="sofa", room_id="r1", relation=already)]
    spatial = SpatialScene(scene=_scene([]))
    i = Intent.create("sofa", "FACES", "tv_unit", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i])
    apply_constraints_to_plan(items, cs, spatial)
    assert items[0].relation is already


def test_apply_constraints_to_plan_routes_orientation_through_facing_relation():
    """P9 fix (docs/spatial_architecture/decisions.md's P9 entry): ORIENTATION
    routes through `.relation=facing(target)`, not the free-text `.faces`
    field - `.faces` never participated in `_ordered()`'s dependency graph,
    which was the measured root cause of P8's own FACES failure. The bridge
    runs BEFORE placement, so the target is resolved among the PLAN items
    (by object_key), not the (still-empty) scene."""
    items = [ObjectPlanItem(object_key="sofa", semantic_type="sofa", room_id="r1"),
            ObjectPlanItem(object_key="tv_unit", semantic_type="tv_unit", room_id="r1")]
    spatial = SpatialScene(scene=_scene([]))   # deliberately empty - nothing placed yet
    i = Intent.create("sofa", "FACES", "tv_unit", source=IntentSource.USER_ASSERTED, provenance="x")
    cs = compile_intents(spatial, [i])
    notes = apply_constraints_to_plan(items, cs, spatial)
    assert items[0].relation is not None
    assert items[0].relation.type == "facing"
    assert items[0].relation.target_key == "tv_unit"
    assert notes

"""The bridge: spatial graph -> object plan -> the compiler's own machinery.

`merge_reading_into_plan` builds items from the approved render but sets neither
`relation` nor `support_key`, so every moodboard-derived piece reached the
compiler with no relationship - while `_relation_candidates` and `_pick_support`
sat there ready to consume them. These cover the bridge that fills them, and the
guards that stop the wrong things crossing it.

No GPU, no Ollama, no detector, no network, no Blender.
"""
from __future__ import annotations

from app.intelligence.schema import (
    ObjectPlan, ObjectPlanItem, ObjectRelation, SceneElement, SceneReading)
from app.planning.compiler import _ordered, _relation_candidates
from app.planning.spatial_graph import apply_spatial_graph, build_spatial_graph
from app.scene.schema import Room, SceneObject


def el(element_id, semantic_type, room="living_room", bbox=(0.1, 0.1, 0.3, 0.3), **kw):
    return SceneElement(element_id=element_id, room_id=room, semantic_type=semantic_type,
                        name=kw.pop("name", semantic_type), bbox=bbox,
                        check=kw.pop("check", "ok"), crop_ref=f"{element_id}.png", **kw)


def item(object_key, semantic_type, element_id="", room="living_room", **kw):
    return ObjectPlanItem(object_key=object_key, semantic_type=semantic_type,
                          room_id=room, element_id=element_id, **kw)


def plan_of(*items) -> ObjectPlan:
    return ObjectPlan(provider="test", rooms=sorted({i.room_id for i in items}),
                      items=list(items))


def attach(reading: SceneReading, plan: ObjectPlan, **kw):
    graph = build_spatial_graph(reading, detections=kw.pop("detections", None))
    return apply_spatial_graph(plan, graph, **kw)


# -- relations that should cross the bridge ------------------------------

def test_a_faces_hint_becomes_a_facing_relation_on_the_plan():
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.05, 0.30, 0.45, 0.60), faces="the tv unit"),
        el("t1", "tv_unit", bbox=(0.65, 0.20, 0.95, 0.45))])
    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                   item("living_room.tv_unit.0", "tv_unit", "t1"))
    plan, notes = attach(reading, plan)

    sofa = plan.item("living_room.sofa.0")
    assert sofa.relation is not None, "the reader said which way it faces"
    assert sofa.relation.type == "facing"
    assert sofa.relation.target_key == "living_room.tv_unit.0"
    assert any("attached to the object plan" in n for n in notes)


def test_an_against_wall_hint_becomes_an_against_wall_relation():
    reading = SceneReading(elements=[el("b1", "bed", room="bedroom", against="the window wall")])
    plan = plan_of(item("bedroom.bed.0", "bed", "b1", room="bedroom"))
    plan, _ = attach(reading, plan)

    bed = plan.item("bedroom.bed.0")
    assert bed.relation.type == "against_wall"
    assert bed.relation.target_key is None, "which wall is the compiler's decision"


def test_against_a_named_piece_becomes_beside_it():
    """'against the sofa' means beside it, not against a wall."""
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.10, 0.40, 0.40, 0.60)),
        el("t1", "side_table", bbox=(0.42, 0.42, 0.52, 0.58), against="the sofa")])
    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                   item("living_room.side_table.0", "side_table", "t1"))
    plan, _ = attach(reading, plan)

    table = plan.item("living_room.side_table.0")
    assert table.relation.type == "beside"
    assert table.relation.target_key == "living_room.sofa.0"


def test_on_top_of_sets_support_key_not_a_relation():
    """Support and relation are read separately by the compiler and must not
    compete for the one `relation` slot."""
    reading = SceneReading(elements=[
        el("t1", "coffee_table", bbox=(0.30, 0.55, 0.60, 0.80)),
        el("v1", "vase", bbox=(0.40, 0.50, 0.46, 0.58),
           placement="on_surface", against="the coffee table")])
    plan = plan_of(item("living_room.coffee_table.0", "coffee_table", "t1"),
                   item("living_room.vase.0", "vase", "v1", placement="on_surface"))
    plan, _ = attach(reading, plan)

    vase = plan.item("living_room.vase.0")
    assert vase.support_key == "living_room.coffee_table.0"


def test_a_named_target_resolves_to_the_existing_plan_key():
    """No second matching system: the graph keys on element_id, and the plan
    item already carries element_id, so the join is exact rather than fuzzy."""
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.10, 0.40, 0.40, 0.60), name="striped teal sofa"),
        el("t1", "side_table", bbox=(0.42, 0.42, 0.52, 0.58),
           name="small wooden side table", against="the sofa")])
    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                   item("living_room.side_table.0", "side_table", "t1"))
    plan, _ = attach(reading, plan)
    assert plan.item("living_room.side_table.0").relation.target_key == "living_room.sofa.0"


# -- safety: what must NOT cross ----------------------------------------

def test_camera_frame_relations_never_reach_the_plan():
    """LEFT_OF exists in the graph and must stay there. A render's left is not
    the room's left, and a placement built on it puts the sofa on whichever
    wall the camera happened to face."""
    reading = SceneReading(elements=[
        el("a1", "sofa", bbox=(0.05, 0.40, 0.25, 0.60)),
        el("b1", "armchair", bbox=(0.70, 0.40, 0.90, 0.60))])
    graph = build_spatial_graph(reading)
    assert [r for r in graph.relations if r.frame == "camera"], "the graph keeps them"

    plan = plan_of(item("living_room.sofa.0", "sofa", "a1"),
                   item("living_room.armchair.0", "armchair", "b1"))
    plan, notes = apply_spatial_graph(plan, graph)
    assert any("camera-frame" in n for n in notes)
    for i in plan.items:
        if i.relation:
            assert i.relation.type in ("against_wall", "facing", "beside",
                                       "in_front_of", "under", "around")


def test_an_unresolved_conflict_blocks_the_relation():
    """The reader said 'against the sofa'; the picture puts them at opposite
    corners. Neither side is chosen, so neither drives placement."""
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.02, 0.05, 0.20, 0.25)),
        el("l1", "floor_lamp", bbox=(0.85, 0.80, 0.98, 0.97), against="the sofa")])
    graph = build_spatial_graph(reading)
    assert graph.conflicts and graph.conflicts[0].resolution == "unresolved"

    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                   item("living_room.floor_lamp.0", "floor_lamp", "l1"))
    plan, notes = apply_spatial_graph(plan, graph)
    assert plan.item("living_room.floor_lamp.0").relation is None
    assert any("unresolved conflict" in n for n in notes)


def test_a_relation_the_planner_already_set_is_never_overwritten():
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.10, 0.40, 0.40, 0.60)),
        el("t1", "side_table", bbox=(0.42, 0.42, 0.52, 0.58), against="the sofa")])
    existing = ObjectRelation(type="in_front_of", target_key="living_room.sofa.0")
    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                   item("living_room.side_table.0", "side_table", "t1", relation=existing))
    plan, _ = attach(reading, plan)
    assert plan.item("living_room.side_table.0").relation.type == "in_front_of"


def test_the_strongest_relation_wins_when_a_piece_has_several():
    """A bed against a wall AND beside a table takes the wall: it constrains a
    whole edge, where beside only fixes a neighbour."""
    reading = SceneReading(elements=[
        el("b1", "bed", room="bedroom", bbox=(0.10, 0.30, 0.50, 0.70),
           against="the window wall"),
        el("t1", "bedside_table", room="bedroom", bbox=(0.52, 0.40, 0.62, 0.60))])
    plan = plan_of(item("bedroom.bed.0", "bed", "b1", room="bedroom"),
                   item("bedroom.bedside_table.0", "bedside_table", "t1", room="bedroom"))
    plan, _ = attach(reading, plan)
    assert plan.item("bedroom.bed.0").relation.type == "against_wall"


def test_a_project_with_no_spatial_graph_is_untouched():
    """Old projects replan exactly as before."""
    plan = plan_of(item("living_room.sofa.0", "sofa", "s1"))
    before = plan.model_dump(exclude={"created_at"})
    plan, _ = apply_spatial_graph(plan, build_spatial_graph(SceneReading(elements=[])))
    assert plan.model_dump(exclude={"created_at"}) == before


def test_items_without_an_element_id_are_left_alone():
    """Rooms the reading never covered keep the planner's own items."""
    plan = plan_of(item("study.desk.0", "desk", room="study"))
    plan, notes = apply_spatial_graph(plan, build_spatial_graph(SceneReading(elements=[])))
    assert plan.item("study.desk.0").relation is None
    assert any("cannot be attached" in n for n in notes)


# -- it reaches the compiler's own machinery -----------------------------

def test_the_relation_reaches_relation_candidates():
    """The point of the whole bridge: a populated relation produces positions
    from the compiler's existing generator, with no new solver involved."""
    target = SceneObject(semantic_type="sofa", room_id="living_room",
                         position=(2.0, 0.0, 1.0), dimensions=(2.1, 0.8, 0.9))
    room = Room(room_id="living_room", name="Living", type="living_room",
                boundary=[(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)], ceiling_height=2.8)
    assert _relation_candidates(target, (0.5, 0.5, 0.5), "beside", 0, 1, room), \
        "the existing generator turns a relation into positions"


def test_a_support_key_changes_the_placement_order():
    """`_ordered` waits for an item's support before placing it. With
    support_key empty - the state before this bridge - it had nothing to wait
    for."""
    host = item("living_room.coffee_table.0", "coffee_table", "t1")
    guest = item("living_room.vase.0", "vase", "v1", placement="on_surface",
                 support_key="living_room.coffee_table.0")
    order = [i.object_key for i in _ordered(plan_of(guest, host))]
    assert order.index("living_room.coffee_table.0") < order.index("living_room.vase.0")


def test_the_same_graph_gives_the_same_plan():
    reading = SceneReading(elements=[
        el("s1", "sofa", bbox=(0.10, 0.40, 0.40, 0.60), faces="the tv unit"),
        el("t1", "tv_unit", bbox=(0.60, 0.40, 0.90, 0.60)),
        el("x1", "side_table", bbox=(0.42, 0.42, 0.52, 0.58), against="the sofa")])
    graph = build_spatial_graph(reading)

    def run():
        plan = plan_of(item("living_room.sofa.0", "sofa", "s1"),
                       item("living_room.tv_unit.0", "tv_unit", "t1"),
                       item("living_room.side_table.0", "side_table", "x1"))
        return apply_spatial_graph(plan, graph)[0].model_dump(exclude={'created_at'})

    assert run() == run()

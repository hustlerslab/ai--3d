"""P1-IDENTITY-001/002 - a scene object names the element it came from.

Identity used to survive only as a join: `plan_key` -> `ObjectPlanItem.object_key`
-> `.element_id`. Nobody performed it. So three identical bar stools looked like
three unrelated objects, and the link back to the element that justified them -
and to the ONE mesh they share - existed only in principle.

`item.element_id` was in scope at the compiler's `SceneObject(...)` constructor
and simply unused. These tests pin that it no longer is, and that adding it
strands nothing already on disk.

Distinct from tests/test_p18_canonical_identity.py, which covers the element
DEFINITION layer - the canonical key, false merges and splits, one asset per
element. This file covers the SCENE layer: whether a placed object carries that
identity forward.
"""
from __future__ import annotations

from app.intelligence import InputBundle
from app.intelligence.mock_provider import MockProvider
from app.intelligence.schema import ObjectPlan, ObjectPlanItem
from app.planning import place_objects, resolve_plan
from app.scene.schema import SceneObject

ELEMENT = "cel_1a2b3c4d5e"


# ── P1-IDENTITY-001: the schema ──────────────────────────────────────────

def test_a_pre_v4_scene_object_still_loads():
    """THE acceptance criterion. Both fields are Optional with None defaults
    precisely so a scene_spec.json written before V4 opens unchanged - making
    them required would strand every scene already on disk."""
    pre_v4 = {
        "object_id": "obj_a1b2c3",
        "semantic_type": "sofa",
        "room_id": "living_room",
        "position": [1.0, 0.0, 1.0],
        "dimensions": [2.0, 0.8, 0.9],
        "plan_key": "living_room.sofa.0",
    }
    obj = SceneObject.model_validate(pre_v4)
    assert obj.element_id is None
    assert obj.instance_id is None
    assert obj.plan_key == "living_room.sofa.0", "the old join must be retained"


def test_the_flat_accessor_delegates_rather_than_duplicating():
    """One list, two ways to reach it. A second field would be a second place
    to update, and one of them would eventually be wrong."""
    obj = SceneObject.model_validate({
        "semantic_type": "chair", "room_id": "living_room",
        "position": [0, 0, 0], "dimensions": [0.5, 0.9, 0.5],
        "visual": {"source_intent_ids": ["int_a", "int_b"]},
    })
    assert obj.source_intent_ids == ["int_a", "int_b"]
    assert obj.source_intent_ids is obj.visual.source_intent_ids


def test_the_accessor_is_empty_not_missing_when_nothing_shaped_the_object():
    obj = SceneObject.model_validate({
        "semantic_type": "chair", "room_id": "living_room",
        "position": [0, 0, 0], "dimensions": [0.5, 0.9, 0.5],
    })
    assert obj.source_intent_ids == []


def test_identity_round_trips_through_json():
    """It has to survive the file, not just the object."""
    obj = SceneObject.model_validate({
        "semantic_type": "stool", "room_id": "kitchen",
        "position": [0, 0, 0], "dimensions": [0.4, 0.7, 0.4],
        "element_id": ELEMENT, "instance_id": ELEMENT + "#1",
    })
    again = SceneObject.model_validate(obj.model_dump(mode="json"))
    assert again.element_id == ELEMENT and again.instance_id == ELEMENT + "#1"


# ── P1-IDENTITY-002: the compiler ────────────────────────────────────────

def _scene_with_kitchen():
    from app.intelligence.schema import DesignAnalysis, RoomAnalysis
    from app.planning.compiler import compile_scene

    analysis = DesignAnalysis(
        intent="a kitchen",
        rooms=[RoomAnalysis(room_id="kitchen", name="Kitchen", type="kitchen",
                            width_m=5.0, length_m=4.0)],
        provider="test",
    )
    style = MockProvider().create_style_spec(
        analysis, InputBundle(project_id="p", description="a kitchen"))
    scene, _ = compile_scene("p", analysis, style, name="t")
    return scene, style


def _three_stools(element_id: str = ELEMENT, count: int = 3) -> ObjectPlan:
    return ObjectPlan(
        rooms=["kitchen"],
        items=[ObjectPlanItem(
            object_key="kitchen.bar_stool.0", semantic_type="bar_stool",
            room_id="kitchen", name="bar stool", count=count,
            element_id=element_id, material="wood", color="#111111",
        )],
        provider="test",
    )


def _stools(ops):
    return [op.object for op in ops if op.object.semantic_type == "bar_stool"]


def test_three_of_one_element_are_one_identity_and_three_occurrences():
    """The headline claim: 1 element_id, 3 distinct instance_ids."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools()
    ops, warnings = place_objects(scene, plan, resolve_plan(plan, style))

    stools = _stools(ops)
    assert len(stools) == 3, warnings
    assert {s.element_id for s in stools} == {ELEMENT}, "one element"
    assert len({s.instance_id for s in stools}) == 3, "three occurrences"
    assert {s.instance_id for s in stools} == {
        ELEMENT + "#0", ELEMENT + "#1", ELEMENT + "#2"}


def test_the_old_join_still_works_alongside_the_new_field():
    """`plan_key` is kept, not replaced: every pre-V4 consumer still resolves."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools()
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))

    keys = {s.plan_key for s in _stools(ops)}
    assert keys == {"kitchen.bar_stool.0", "kitchen.bar_stool.0#2",
                    "kitchen.bar_stool.0#3"}


def test_instance_ids_are_deterministic_across_two_compiles():
    """Derived from element_id and the loop index - no uuid, no clock. Two
    compiles of one plan must produce identical sets, or provenance changes
    every time somebody re-runs the planner."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools()

    first = {s.instance_id for s in
             _stools(place_objects(scene, plan, resolve_plan(plan, style))[0])}
    second = {s.instance_id for s in
              _stools(place_objects(scene, plan, resolve_plan(plan, style))[0])}
    assert first == second and first


def test_an_item_with_no_element_carries_no_identity_rather_than_a_fake_one():
    """A catalog item the planner added on its own has no element behind it.
    Inventing an id would make it look like it came from the client's approved
    moodboard - a lie the provenance chain would then carry."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools(element_id="", count=1)
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))

    stools = _stools(ops)
    assert stools and all(s.element_id is None for s in stools)
    assert all(s.instance_id is None for s in stools)
    assert all(s.plan_key for s in stools), "the old join must still be there"


# ── the divergence the criterion asks to be surfaced ─────────────────────

class _Reading:
    """Just enough of a SceneReading to carry occurrences."""

    class _El:
        def __init__(self, element_id):
            self.element_id = element_id

    def __init__(self, element_ids):
        self.elements = [self._El(e) for e in element_ids]


def test_planning_more_than_the_reading_saw_is_warned_about():
    """Planning three stools from a picture showing two is a decision somebody
    should see - not something to discover when paying for three meshes."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools(count=3)
    reading = _Reading([ELEMENT, ELEMENT])          # the reading saw two

    _, warnings = place_objects(scene, plan, resolve_plan(plan, style), reading=reading)
    hit = [w for w in warnings if ELEMENT in w]
    assert hit, "the divergence was tolerated silently: %s" % warnings
    assert "plan says 3" in hit[0] and "2 occurrence" in hit[0]


def test_agreement_is_not_warned_about():
    """A warning on every correct plan is a warning nobody reads."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools(count=3)
    reading = _Reading([ELEMENT, ELEMENT, ELEMENT])

    _, warnings = place_objects(scene, plan, resolve_plan(plan, style), reading=reading)
    assert not [w for w in warnings if ELEMENT in w], warnings


def test_an_element_the_reading_never_saw_is_not_warned_about():
    """Silence is not zero occurrences. A reading that has never heard of an
    element says nothing about it, and warning here would fire on every catalog
    item the planner legitimately added."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools(count=3)
    reading = _Reading(["cel_something_else"])

    _, warnings = place_objects(scene, plan, resolve_plan(plan, style), reading=reading)
    assert not [w for w in warnings if ELEMENT in w], warnings


def test_the_reading_argument_is_optional():
    """Nine call sites predate it. None of them had to change."""
    scene, style = _scene_with_kitchen()
    plan = _three_stools()
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))
    assert _stools(ops)

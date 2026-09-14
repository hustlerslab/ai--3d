"""Reference photos must not furnish the room.

Uploads are frequently shop or catalogue photographs. On the sample set the
reading correctly found four *different* mattresses in a showroom, and every one
became a bed, because the planner's contract is "keep every read item". The fix
is a per-item role defaulted here and settled by the client on the review
screen — not an automatic similarity merge, which the measurements ruled out
(CLIP scores two views of one sofa at 0.804 and two different pieces at 0.936,
so no threshold separates them).
"""
from __future__ import annotations

from app.intelligence.coerce import assign_ids, assign_roles, coerce_analysis
from app.intelligence.schema import DesignAnalysis, InputBundle, ReferenceImage, RoomAnalysis, SpottedObject


def _bundle(n_photos: int = 4) -> InputBundle:
    return InputBundle(
        project_id="p", description="A calm bedroom",
        references=[ReferenceImage(input_id=f"in_{i}", path=f"/tmp/{i}.jpg") for i in range(n_photos)],
    )


def _analysis(*spotted: SpottedObject) -> DesignAnalysis:
    a = DesignAnalysis(
        intent="test",
        rooms=[RoomAnalysis(room_id="bedroom", name="Bedroom", type="bedroom", width_m=4.0, length_m=3.6),
               RoomAnalysis(room_id="living_room", name="Living Room", type="living_room", width_m=5.0, length_m=4.0)],
        spotted_objects=list(spotted),
    )
    assign_ids(a)
    return a


def _bed(name: str, confidence: float, index: int) -> SpottedObject:
    return SpottedObject(semantic_type="bed", name=name, family="bed", room_id="bedroom",
                         confidence=confidence, image_ref=f"in_{index}", image_index=index)


def test_the_default_flips_once_a_room_holds_more_than_it_plausibly_can(env):
    """ROOM_SETS says a bedroom holds one bed; the slack allows two. The third
    and fourth mattress are the ones that stop being furniture."""
    a = _analysis(*[_bed(f"mattress {i}", 0.9 - i * 0.1, i) for i in range(4)])
    assign_roles(a)
    roles = [s.role for s in a.spotted_objects]
    assert roles.count("place") == 2, roles
    assert roles.count("reference") == 2, roles
    # the confident readings are the ones kept
    kept = {s.name for s in a.spotted_objects if s.role == "place"}
    assert kept == {"mattress 0", "mattress 1"}, kept


def test_a_plausible_count_is_left_alone(env):
    """Two beds in a bedroom is a real room, not a catalogue. Nothing is
    demoted — the threshold must not punish the honest case."""
    a = _analysis(*[_bed(f"mattress {i}", 0.9, i) for i in range(2)])
    assign_roles(a)
    assert all(s.role == "place" for s in a.spotted_objects)


def test_only_photo_read_items_can_be_demoted(env):
    """Items the planner added are there because the room needs them; they have
    no photo behind them and must never be demoted."""
    a = _analysis(*[
        SpottedObject(semantic_type="bed", name=f"bed {i}", family="bed", room_id="bedroom", confidence=0.9)
        for i in range(4)
    ])
    assign_roles(a)
    assert all(s.role == "place" for s in a.spotted_objects)


def test_reference_items_feed_style_but_never_the_object_list(env):
    """The whole point of 'reference' rather than 'delete': the mattress still
    tells us the client likes blue, it just does not become a bed."""
    from app.intelligence.mock_provider import MockProvider
    from app.intelligence.prompts import objects_prompt

    a = _analysis(
        _bed("blue mattress", 0.95, 0),
        _bed("grey mattress", 0.90, 1),
        _bed("striped mattress", 0.85, 2),
        _bed("green mattress", 0.80, 3),
    )
    for s in a.spotted_objects:
        s.color = "#2C70CB"
    assign_roles(a)
    references = [s for s in a.spotted_objects if s.role == "reference"]
    assert references, "the fixture must actually produce references"

    # 1. the planner is never offered them
    style = MockProvider().create_style_spec(a, _bundle())
    prompt = objects_prompt(a, style, _bundle())
    for s in references:
        assert s.name not in prompt, f"{s.name} was offered to the planner"
    for s in (x for x in a.spotted_objects if x.role == "place"):
        assert s.name in prompt, f"{s.name} was withheld from the planner"

    # 2. but the style stage still reads the whole analysis, so their colour
    #    survives into the palette
    assert style.palette, "reference items should still contribute colour"


def test_the_planner_cannot_restore_a_reference_through_the_back_door(env):
    """coerce_object_plan re-adds items the model forgot. References were never
    offered, so that path must skip them or the fix is undone silently."""
    from app.intelligence.coerce import coerce_object_plan

    a = _analysis(*[_bed(f"mattress {i}", 0.9 - i * 0.1, i) for i in range(4)])
    assign_roles(a)
    plan = coerce_object_plan({"items": []}, a, provider="test")
    beds = [i for i in plan.items if i.semantic_type == "bed"]
    assert len(beds) == 2, [i.name for i in beds]


def test_ids_are_stable_across_a_re_read(env):
    """Content-derived, so a re-analysis of the same photos does not throw away
    the client's place/reference decisions."""
    raw = {
        "intent": "bedroom",
        "rooms": [{"name": "Bedroom", "type": "bedroom", "width_m": 4.0, "length_m": 3.6}],
        "spotted_objects": [
            {"name": "blue mattress", "semantic_type": "bed", "family": "bed", "room_name": "Bedroom",
             "image_index": 0, "bbox": [0.1, 0.1, 0.9, 0.9]},
        ],
    }
    first = coerce_analysis(raw, _bundle(), [], provider="test")
    second = coerce_analysis(raw, _bundle(), [], provider="test")
    assert [s.object_id for s in first.spotted_objects] == [s.object_id for s in second.spotted_objects]
    assert all(s.object_id.startswith("it_") for s in first.spotted_objects)


def test_a_planner_index_pointing_at_a_reference_resolves_to_nothing(env):
    """The filter removes references from the prompt but leaves the indices
    unrenumbered, so the planner sees a gap and sometimes emits it anyway.
    Found live: 'grey pull-out sofa bed' was excluded from the prompt and still
    arrived in the plan, name and crop intact, because index 1 resolved.
    """
    from app.intelligence.coerce import coerce_object_plan

    a = _analysis(*[_bed(f"mattress {i}", 0.9 - i * 0.1, i) for i in range(4)])
    assign_roles(a)
    demoted = [s for s in a.spotted_objects if s.role == "reference"]
    assert demoted, "fixture must produce a reference"
    idx = a.spotted_objects.index(demoted[0])

    raw = {"items": [{
        "object_key": "bedroom.bed.1", "semantic_type": "bed", "room_id": "bedroom",
        "spotted_index": idx, "priority": 1, "count": 1,
    }]}
    plan = coerce_object_plan(raw, a, provider="test")
    for item in plan.items:
        assert item.name != demoted[0].name, f"reference leaked back in as {item.name!r}"
        assert item.spotted_index != idx

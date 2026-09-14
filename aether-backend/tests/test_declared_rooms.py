"""A room the client declared at setup is a fact, not a suggestion.

"Full 2BHK" says what the property IS: two bedrooms, a living room, a kitchen
and a bathroom, whether or not the brief mentions them. The brief then
conditions those rooms — what each is for, what it must hold.

Before this, the room list came only from the model's answer and the declared
rooms were merely offered to it in the prompt. The same project came back with
a bathroom one run and without it the next, with nothing to point at.
"""
from __future__ import annotations

from app.intelligence.coerce import coerce_analysis
from app.intelligence.schema import InputBundle
from app.projects.schema import RoomHint

# what the "Full 2BHK" preset declares
TWO_BHK = [
    RoomHint(name="Living Room", type="living_room"),
    RoomHint(name="Master Bedroom", type="master_bedroom"),
    RoomHint(name="Second Bedroom", type="bedroom"),
    RoomHint(name="Kitchen", type="kitchen"),
    RoomHint(name="Bathroom", type="bathroom"),
]

# a brief that only talks about two of them — the real sample project's shape
BRIEF = "Warm modern family home, a living room around this blue sofa and a primary bedroom around this mattress."


def _bundle(hints=TWO_BHK) -> InputBundle:
    return InputBundle(project_id="p", description=BRIEF, room_hints=list(hints))


def test_a_declared_room_survives_a_reading_that_forgot_it(env):
    """The exact failure: the reading returned four rooms and no bathroom."""
    raw = {
        "intent": BRIEF,
        "rooms": [
            {"name": "Living Room", "type": "living_room", "width_m": 5.8, "length_m": 4.5},
            {"name": "Master Bedroom", "type": "master_bedroom", "width_m": 4.8, "length_m": 4.2},
            {"name": "Second Bedroom", "type": "bedroom", "width_m": 4.0, "length_m": 3.6},
            {"name": "Kitchen", "type": "kitchen", "width_m": 3.8, "length_m": 3.0},
        ],
    }
    analysis = coerce_analysis(raw, _bundle(), [], provider="test")
    types = [r.type for r in analysis.rooms]
    assert "bathroom" in types, types
    assert len(analysis.rooms) == 5, [r.name for r in analysis.rooms]
    added = next(r for r in analysis.rooms if r.type == "bathroom")
    assert added.width_m > 0 and added.length_m > 0, "the added room needs usable dimensions"
    assert added.estimated is True
    assert any("declared" in w for w in analysis.warnings), analysis.warnings


def test_a_reading_that_returns_nothing_still_yields_the_declared_space(env):
    analysis = coerce_analysis({"intent": BRIEF, "rooms": []}, _bundle(), [], provider="test")
    for t in ("living_room", "master_bedroom", "bedroom", "kitchen", "bathroom"):
        assert any(r.type == t for r in analysis.rooms), f"{t} missing from {[r.type for r in analysis.rooms]}"


def test_a_differently_named_room_is_matched_not_duplicated(env):
    """"Master Bedroom" declared and "Primary Bedroom" read are one room. The
    reading renames rooms between runs, and duplicating them would furnish a
    2BHK with three bedrooms."""
    raw = {"intent": BRIEF, "rooms": [
        {"name": "Primary Bedroom", "type": "master_bedroom", "width_m": 4.8, "length_m": 4.2},
        {"name": "Lounge", "type": "living_room", "width_m": 5.8, "length_m": 4.5},
    ]}
    analysis = coerce_analysis(raw, _bundle(), [], provider="test")
    assert sum(1 for r in analysis.rooms if r.type == "master_bedroom") == 1
    assert sum(1 for r in analysis.rooms if r.type == "living_room") == 1
    assert len(analysis.rooms) == 5, [r.name for r in analysis.rooms]
    # the reading's own names win; we only guarantee the room exists
    assert any(r.name == "Primary Bedroom" for r in analysis.rooms)


def test_the_reading_may_still_add_rooms_beyond_the_declared_set(env):
    """Declared rooms are a floor, not a ceiling — a balcony the client
    photographed should not be thrown away."""
    raw = {"intent": BRIEF, "rooms": [
        {"name": "Living Room", "type": "living_room"},
        {"name": "Balcony", "type": "balcony"},
    ]}
    analysis = coerce_analysis(raw, _bundle(), [], provider="test")
    assert any(r.type == "balcony" for r in analysis.rooms)
    assert len(analysis.rooms) == 6, [r.name for r in analysis.rooms]


def test_declared_dimensions_are_used_for_a_room_the_reading_omitted(env):
    hints = [RoomHint(name="Study", type="study", width_m=3.0, length_m=2.5)]
    analysis = coerce_analysis({"intent": "x", "rooms": []}, _bundle(hints), [], provider="test")
    study = next(r for r in analysis.rooms if r.type == "study")
    assert (study.width_m, study.length_m) == (3.0, 2.5)
    assert study.estimated is False, "the client gave real numbers"


def test_no_hints_means_the_reading_is_left_alone(env):
    """Projects created before the space preset declared its rooms must behave
    exactly as they did."""
    raw = {"intent": BRIEF, "rooms": [{"name": "Living Room", "type": "living_room"}]}
    analysis = coerce_analysis(raw, _bundle(hints=[]), [], provider="test")
    assert [r.type for r in analysis.rooms] == ["living_room"]

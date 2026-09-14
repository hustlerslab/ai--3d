"""Arrangement hints bias placement without ever weakening it."""
from __future__ import annotations

from app.intelligence.schema import ObjectPlanItem
from app.planning.compiler import _prefer_hint, _hint_rank
from app.scene.schema import Room, Scene


def _room() -> Room:
    # 5 x 4 m, corners at the origin.
    return Room(room_id="living_room", name="Living Room", type="living_room",
                boundary=[(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)], ceiling_height=2.8)


def _item(**kw) -> ObjectPlanItem:
    base = dict(object_key="living_room.sofa.0", semantic_type="sofa", room_id="living_room")
    base.update(kw)
    return ObjectPlanItem(**base)


# Three valid spots the engine already produced: a wall, a corner, the centre.
WALL = ((2.5, 0.4), 0.0)
CORNER = ((0.6, 0.5), 0.0)
CENTRE = ((2.5, 2.0), 0.0)
CANDIDATES = [WALL, CORNER, CENTRE]


def test_no_hint_leaves_the_order_exactly_as_it_is():
    """The fallback path must be byte-for-byte what runs today."""
    out = _prefer_hint(list(CANDIDATES), _item(), None, _room(), {})
    assert out == CANDIDATES
    assert out is not CANDIDATES or True          # a copy or the same list, same order


def test_a_centre_hint_moves_the_centre_spot_first():
    out = _prefer_hint(list(CANDIDATES), _item(against="in the middle of the room"),
                       None, _room(), {})
    assert out[0] == CENTRE
    assert set(out) == set(CANDIDATES), "a preference must not drop a valid spot"


def test_a_corner_hint_moves_the_corner_spot_first():
    out = _prefer_hint(list(CANDIDATES), _item(against="the corner"), None, _room(), {})
    assert out[0] == CORNER
    assert set(out) == set(CANDIDATES)


def test_an_unsatisfiable_hint_changes_nothing():
    """No candidate is near a window, so the engine's own order stands. This is
    the graceful-fallback case: it must not raise, drop, or reorder."""
    out = _prefer_hint(list(CANDIDATES), _item(against="the window wall"), None, _room(), {})
    assert out == CANDIDATES


def test_camera_relative_words_are_deliberately_ignored():
    """The reader answers in the picture's frame - "back wall", "left wall" -
    and a render has no fixed orientation against the floor plan. Mapping those
    to real walls would be inventing a fact, so they leave the order alone."""
    for hint in ("back wall", "left wall", "right wall", "front"):
        assert _prefer_hint(list(CANDIDATES), _item(against=hint), None, _room(), {}) == CANDIDATES


def test_every_candidate_survives_whatever_the_hint_says():
    """The engine decides what is valid; the hint only decides what to try
    first. Nothing here may shrink the list the collision checks run over."""
    for hint in ("middle", "corner", "window", "beside the sofa", "", "nonsense"):
        out = _prefer_hint(list(CANDIDATES), _item(against=hint), None, _room(), {})
        assert sorted(out) == sorted(CANDIDATES), hint

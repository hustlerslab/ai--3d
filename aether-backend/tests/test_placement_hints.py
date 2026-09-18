"""Arrangement hints bias placement without ever weakening it."""
from __future__ import annotations

import math

from app.intelligence.schema import ObjectPlanItem
from app.planning.compiler import _prefer_hint, _hint_rank, _faces_rank
from app.scene.schema import Room, Scene, SceneObject


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


# ── `faces`: which way round, not where ──────────────────────────────────
#
# Two spots at the SAME position with opposite rotations, so only orientation
# can separate them. AWAY is listed first deliberately: that is the production
# bug, where the engine took whichever rotation the wall normal gave it and the
# reader's "facing the tv" was never consulted.
TV = SceneObject(semantic_type="tv", room_id="living_room",
                 position=(2.5, 0.5, 3.6), dimensions=(1.2, 0.7, 0.1))
TOWARD_TV = ((2.5, 0.4), math.pi)     # forward is +z, up the room at the tv
AWAY_FROM_TV = ((2.5, 0.4), 0.0)      # forward is -z, at the wall behind it
FACING = [AWAY_FROM_TV, TOWARD_TV]
PLACED = {"living_room.tv.0": TV}


def test_faces_turns_the_piece_towards_what_the_render_showed_it_facing():
    """The regression this closes: `faces` was written by the reader, copied
    into the plan, and read by nothing, so rotation came only from the wall."""
    out = _prefer_hint(list(FACING), _item(faces="the tv"), None, _room(), PLACED)
    assert out[0] == TOWARD_TV
    assert set(out) == set(FACING), "a preference must not drop a valid spot"


def test_faces_works_with_no_against_hint_at_all():
    """`_prefer_hint` used to return early whenever `against` was empty, which
    would have swallowed every orientation hint that arrived on its own."""
    assert _item(faces="the tv").against == ""
    assert _prefer_hint(list(FACING), _item(faces="the tv"), None, _room(), PLACED)[0] == TOWARD_TV


def test_an_unsatisfiable_faces_hint_changes_nothing():
    """No tv is placed, so nothing resolves and the engine's order stands."""
    out = _prefer_hint(list(FACING), _item(faces="the tv"), None, _room(), {})
    assert out == FACING


def test_faces_is_byte_for_byte_the_no_hint_path_when_it_cannot_resolve():
    for hint in ("north", "left", "behind it", "nonsense", ""):
        assert _prefer_hint(list(FACING), _item(faces=hint), None, _room(), PLACED) == FACING, hint


def test_a_piece_pointing_away_is_ranked_below_one_pointing_at_the_target():
    item = _item(faces="the tv")
    assert _faces_rank(TOWARD_TV, item, None, _room(), PLACED) == 0
    assert _faces_rank(AWAY_FROM_TV, item, None, _room(), PLACED) == 1


def test_position_leads_and_orientation_breaks_its_ties():
    """`against` is the stronger claim: a piece in the right place facing the
    wrong way beats one facing the right way in the wrong place, because the
    wall it stands against is what the eye reads first."""
    centre_wrong_way = ((2.5, 2.0), 0.0)        # matches `against`, not `faces`
    wall_right_way = ((2.5, 0.4), math.pi)      # matches `faces`, not `against`
    out = _prefer_hint([wall_right_way, centre_wrong_way],
                       _item(against="the middle of the room", faces="the tv"),
                       None, _room(), PLACED)
    assert out[0] == centre_wrong_way

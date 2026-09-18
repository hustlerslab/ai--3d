"""P22: where the picture put each piece, as metres the solver can use.

A moodboard render has no camera pose against the floor plan, so the frame
is fixed by convention instead: the picture is taken from the room's front
wall looking at its back wall, and the plan binds back = north edge, left =
west. Gemini answers in that frame as whole numbers out of 1000; deterministic
code turns them into room-local metres; the solver prefers the valid spot
nearest that anchor and never places AT it. Walls get finish zones the same
way, bound to the wall segment the named edge became.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from app.intelligence.schema import (ObjectPlan, ObjectPlanItem, RoomAnalysis, RoomSurfaces, SceneElement,
                                     SceneReading, WallFinish)
from app.intelligence.scene_reading import (coerce_room_reading, ensure_anchors,
                                            merge_reading_into_plan, render_frame_position)
from app.planning.compiler import _forward, _prefer_hint, anchor_world, bind_wall_finishes
from app.planning.layout import build_walls_and_openings, layout_rooms, wall_segments
from app.scene.schema import Room, Scene, Wall

ROOM = SimpleNamespace(room_id="living_room", width_m=5.0, length_m=4.0, height_m=2.8)


# ── fractions to metres ─────────────────────────────────────────────────

def test_metres_come_from_the_room_not_the_picture():
    # 5 x 4 m room: halfway along, a quarter of the way in, on the floor.
    assert render_frame_position("", 0.5, 0.25, None, "floor", 5.0, 4.0, 2.8) == (2.5, 0.0, 1.0)


def test_a_named_wall_snaps_the_coordinate_it_fixes():
    assert render_frame_position("back", 0.2, 0.9, None, "floor", 5.0, 4.0, 2.8) == (1.0, 0.0, 0.0)
    assert render_frame_position("right", 0.1, 0.5, None, "floor", 5.0, 4.0, 2.8) == (5.0, 0.0, 2.0)


def test_height_only_matters_off_the_floor():
    assert render_frame_position("back", 0.5, 0.0, 0.5, "floor", 5.0, 4.0, 2.8)[1] == 0.0
    assert render_frame_position("back", 0.5, 0.0, 0.5, "wall", 5.0, 4.0, 2.8)[1] == 1.4
    assert render_frame_position("", 0.5, 0.5, None, "ceiling", 5.0, 4.0, 2.8)[1] == 2.8


def test_nothing_read_is_no_anchor_not_a_guess():
    assert render_frame_position("", None, None, None, "floor", 5.0, 4.0, 2.8) is None


def test_the_reading_turns_whole_numbers_out_of_1000_into_metres():
    raw = {
        "elements": [{
            "name": "oak sideboard", "semantic_type": "sideboard", "bbox": [100, 400, 500, 800],
            "placement": "floor", "against": "wall", "faces": "into the room",
            "wall": "back", "along": 300, "depth": 50, "height": 0, "facing": "front",
        }],
        "surfaces": {
            "wall_material": "paint",
            "walls": [
                {"wall": "back", "material": "zellige tiles", "color": "#3a6b5c", "pattern": "",
                 "span": [0, 1000], "band": [0, 400]},
                {"wall": "back", "material": "lime plaster", "span": [0, 1000], "band": [400, 1000]},
                {"wall": "sideways", "material": "x", "span": [0, 1000], "band": [0, 1000]},
            ],
        },
    }
    warnings: list[str] = []
    elements, surfaces = coerce_room_reading(raw, ROOM, "residential", warnings)

    el = elements[0]
    assert el.wall == "back" and el.position_m == (1.5, 0.0, 0.0)
    assert el.facing == "front" and el.facing_dir == (0.0, 1.0)
    # two zones on the back wall: tiles to 40 %, plaster above; the unnamed wall is dropped, not guessed
    assert [w.wall for w in surfaces.walls] == ["back", "back"]
    assert surfaces.walls[0].extent_m == (0.0, 5.0, 0.0, 1.12)
    assert surfaces.walls[1].extent_m == (0.0, 5.0, 1.12, 2.8)
    assert any("sideways" in w for w in warnings)


def test_an_unread_piece_still_gets_an_anchor_from_its_box():
    """Every boxed element has a position. A reader that skipped the frame
    fields is not a reason for the piece to have no anchor at all - the box
    is required and already validated, so it answers instead, and says so."""
    raw = {"elements": [{"name": "rug", "semantic_type": "rug", "bbox": [100, 600, 900, 900],
                         "against": "", "faces": ""}]}
    elements, _ = coerce_room_reading(raw, ROOM, "residential", [])
    el = elements[0]
    # box centre 0.5 across a 5 m room; bottom edge 0.9 down a 4 m room
    assert el.position_m == (2.5, 0.0, 3.6)
    assert el.position_source == "derived"
    assert el.facing_dir is None


def test_a_wall_piece_takes_its_height_from_the_box_bottom():
    raw = {"elements": [{"name": "framed print", "semantic_type": "wall_art",
                         "bbox": [400, 100, 600, 300], "placement": "wall",
                         "against": "", "faces": ""}]}
    elements, _ = coerce_room_reading(raw, ROOM, "residential", [])
    # image y grows downward: a box ending at 0.3 hangs 0.7 of the way up
    assert elements[0].position_m == (2.5, 1.96, 2.0)
    assert elements[0].position_source == "derived"


def test_a_hung_piece_is_never_put_on_the_floor_by_a_missing_height():
    """The live defect this fixes: the reader answered wall/along/depth for a
    framed print and gave `height: 0`, and it was stored at y = 0.0 - on the
    floor. A hung piece cannot sit on the floor, so zero there is the model
    declining to measure, not a measurement; the box says where it hangs."""
    raw = {"elements": [{"name": "framed print", "semantic_type": "wall_art",
                         "bbox": [59, 0, 155, 332], "placement": "wall",
                         "against": "wall", "faces": "into the room",
                         "wall": "left", "along": 100, "depth": 450, "height": 0}]}
    elements, _ = coerce_room_reading(raw, ROOM, "residential", [])
    el = elements[0]
    assert el.position_m[0] == 0.0                 # the left wall, as read
    assert el.position_m[1] == round((1 - 0.332) * 2.8, 2)   # hung, from the box
    # x and z were read but the height was not: the weaker of the two wins.
    assert el.position_source == "derived"


def test_what_the_reader_answered_is_marked_read():
    raw = {"elements": [{"name": "sofa", "semantic_type": "sofa", "bbox": [100, 400, 500, 800],
                         "against": "wall", "faces": "into the room",
                         "wall": "back", "along": 300, "depth": 50, "facing": "front"}]}
    elements, _ = coerce_room_reading(raw, ROOM, "residential", [])
    assert elements[0].position_source == "read"


# ── every project, including the ones read before this existed ──────────

def _stored(**kw) -> SceneElement:
    base = dict(element_id="el_1", room_id="living_room", name="sofa", semantic_type="sofa",
                bbox=(0.1, 0.4, 0.5, 0.8), check="ok")
    base.update(kw)
    return SceneElement(**base)


def test_a_reading_stored_before_the_fields_existed_gains_anchors():
    reading = SceneReading(elements=[_stored()], surfaces=[])
    assert reading.elements[0].position_m is None

    filled = ensure_anchors(reading, {"living_room": ROOM})
    assert filled == 1
    assert reading.elements[0].position_m == (1.5, 0.0, 3.2)
    assert reading.elements[0].position_source == "derived"


def test_filling_anchors_is_idempotent_and_never_overwrites_the_reader():
    read_row = _stored(element_id="el_read", position_m=(1.0, 0.0, 0.0),
                       position_source="read", wall="back")
    reading = SceneReading(elements=[read_row, _stored(element_id="el_blank")], surfaces=[])

    assert ensure_anchors(reading, {"living_room": ROOM}) == 1     # only the blank one
    assert ensure_anchors(reading, {"living_room": ROOM}) == 0     # nothing left to do
    assert reading.elements[0].position_m == (1.0, 0.0, 0.0)
    assert reading.elements[0].position_source == "read"


def test_an_element_without_a_box_or_a_known_room_is_left_alone():
    reading = SceneReading(elements=[_stored(element_id="el_nobox", bbox=None),
                                     _stored(element_id="el_elsewhere", room_id="attic")], surfaces=[])
    assert ensure_anchors(reading, {"living_room": ROOM}) == 0
    assert all(e.position_m is None and e.position_source == "" for e in reading.elements)


def test_the_anchor_rides_into_the_plan():
    el = SceneElement(element_id="el_1", room_id="living_room", name="sofa", semantic_type="sofa",
                      bbox=(0.1, 0.1, 0.5, 0.5), crop_ref="crops/el_1.png", check="ok",
                      wall="back", position_m=(2.5, 0.0, 0.0), facing="front", facing_dir=(0.0, 1.0))
    plan, _ = merge_reading_into_plan(ObjectPlan(rooms=["living_room"], items=[]),
                                      SceneReading(elements=[el], surfaces=[]))
    item = plan.items[0]
    assert item.anchor_m == (2.5, 0.0, 0.0) and item.wall == "back" and item.facing_dir == (0.0, 1.0)


# ── the solver prefers, never obeys ─────────────────────────────────────

def _room() -> Room:
    return Room(room_id="living_room", name="Living Room", type="living_room",
                boundary=[(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)], ceiling_height=2.8)


def _item(**kw) -> ObjectPlanItem:
    base = dict(object_key="living_room.sofa.0", semantic_type="sofa", room_id="living_room")
    base.update(kw)
    return ObjectPlanItem(**base)


WALL = ((2.5, 0.4), 0.0)
CORNER = ((0.6, 0.5), 0.0)
CENTRE = ((2.5, 2.0), 0.0)
CANDIDATES = [WALL, CORNER, CENTRE]


def test_no_anchor_and_no_hint_leaves_the_engine_order_untouched():
    assert _prefer_hint(list(CANDIDATES), _item(), None, _room(), {}) == CANDIDATES


def test_the_anchor_moves_the_nearest_valid_spot_first():
    assert _prefer_hint(list(CANDIDATES), _item(anchor_m=(0.5, 0.0, 0.5)), None, _room(), {})[0] == CORNER
    assert _prefer_hint(list(CANDIDATES), _item(anchor_m=(2.5, 0.0, 2.0)), None, _room(), {})[0] == CENTRE


def test_a_measured_position_outranks_a_vague_phrase():
    """This assertion used to run the other way, and the measurement reversed
    it. The old rule - a stated relation beats a position estimated off a 2D
    render - sounds right and cost accuracy: `against: 'wall'` and `faces:
    'into the room'` are true of nearly every candidate, so they were beating
    an anchor that names one spot. The verification loop turned the knob
    across four settings and only the narrow band reached 100% orientation
    (93% -> 98% accuracy). A phrase that describes half the room does not
    outrank a coordinate."""
    out = _prefer_hint(list(CANDIDATES), _item(against="in the middle of the room", anchor_m=(0.5, 0.0, 0.5)),
                       None, _room(), {})
    assert out[0] == CORNER, "the anchor names one spot; the phrase names many"


def test_a_named_hint_still_decides_when_nothing_was_measured():
    """The phrase is not ignored - it leads whenever there is no anchor to
    beat it, which is every piece the reader did not place."""
    out = _prefer_hint(list(CANDIDATES), _item(against="in the middle of the room"),
                       None, _room(), {})
    assert out[0] == CENTRE


def test_the_anchor_is_room_local_and_becomes_world():
    room = Room(room_id="r", name="r", type="bedroom",
                boundary=[(5.0, 0.0), (9.0, 0.0), (9.0, 3.0), (5.0, 3.0)], ceiling_height=2.8)
    assert anchor_world(_item(anchor_m=(1.0, 0.0, 0.5)), room) == (6.0, 0.0, 0.5)


def test_facing_the_pictured_wall_picks_the_rotation():
    spot = (2.5, 2.0)
    candidates = [(spot, 0.0), (spot, math.pi)]          # yaw 0 faces the back wall (-z)
    out = _prefer_hint(list(candidates), _item(facing_dir=(0.0, 1.0)), None, _room(), {})
    _, fz = _forward(out[0][1])
    assert fz > 0.9                                        # turned towards the front


def test_the_pictured_spot_is_offered_as_a_candidate_not_only_preferred():
    """Reordering alone can only reach spots the generator already produced,
    and those hug the walls - so a piece read in the middle of the room could
    never land there. Measured: a coffee table read 2.25 m in came out at
    4.08 m, against the far wall."""
    from app.planning.compiler import _floor_candidates

    rooms = [RoomAnalysis(room_id="living_room", name="Living", type="living_room",
                          width_m=5.8, length_m=4.5, height_m=3.0)]
    placed = layout_rooms(rooms)
    walls, openings, _ = build_walls_and_openings(placed)
    room = Room(room_id="living_room", name="Living", type="living_room",
                boundary=placed[0].boundary, ceiling_height=3.0)
    scene = Scene(project_id="p", name="n", rooms=[room], walls=walls, openings=openings)

    item = _item(object_key="living_room.coffee_table.0", semantic_type="coffee_table",
                 anchor_m=(4.35, 0.0, 2.25), facing_dir=(0.0, 1.0))
    spots = _floor_candidates(scene, room, item, (1.1, 0.4, 0.6), 8, {})

    assert spots[0][0] == (4.35, 2.25), "the pictured spot is not on offer"
    assert len(spots) > 1, "the generator's own spots must still be there to fall back to"


def test_a_piece_with_no_anchor_gets_the_generator_list_unchanged():
    from app.planning.compiler import _floor_candidates

    rooms = [RoomAnalysis(room_id="living_room", name="Living", type="living_room",
                          width_m=5.8, length_m=4.5, height_m=3.0)]
    placed = layout_rooms(rooms)
    walls, openings, _ = build_walls_and_openings(placed)
    room = Room(room_id="living_room", name="Living", type="living_room",
                boundary=placed[0].boundary, ceiling_height=3.0)
    scene = Scene(project_id="p", name="n", rooms=[room], walls=walls, openings=openings)

    plain = _floor_candidates(scene, room, _item(semantic_type="sideboard"), (1.6, 0.8, 0.45), 8, {})
    assert all(c[0] != (4.35, 2.25) for c in plain)


def test_a_hung_piece_is_ordered_towards_the_wall_it_was_pictured_on():
    """The hung path read no arrangement evidence at all: a television read
    against the back wall was hung on whichever wall came first."""
    from app.planning.compiler import _prefer_anchor

    room = Room(room_id="living_room", name="Living", type="living_room",
                boundary=[(0.0, 0.0), (5.8, 0.0), (5.8, 4.5), (0.0, 4.5)], ceiling_height=3.0)
    right = (((5.6, 2.25), 0.0, 1.4))
    back = (((2.1, 0.1), 0.0, 1.4))
    item = _item(semantic_type="tv_unit", anchor_m=(2.09, 2.1, 0.0))

    assert _prefer_anchor([right, back], item, room)[0] == back
    # nothing read, nothing reordered
    assert _prefer_anchor([right, back], _item(semantic_type="tv_unit"), room) == [right, back]


def test_the_pictured_facing_becomes_the_rotation():
    from app.planning.compiler import _forward, _rotation_facing

    for direction in ((0.0, -1.0), (0.0, 1.0), (1.0, 0.0), (-1.0, 0.0)):
        fx, fz = _forward(_rotation_facing(direction))
        assert round(fx, 3) == direction[0] and round(fz, 3) == direction[1]
    assert _rotation_facing(None) == 0.0


# ── wall finishes bind to the room's named edge ─────────────────────────

def test_finish_zones_bind_to_the_named_edge_of_the_room():
    rooms = [RoomAnalysis(room_id="living_room", name="Living", type="living_room",
                          width_m=5.0, length_m=4.0, height_m=2.8)]
    placed = layout_rooms(rooms)
    walls, _, _ = build_walls_and_openings(placed)
    segs = wall_segments(placed)
    reading = SimpleNamespace(surfaces=[RoomSurfaces(room_id="living_room", walls=[
        WallFinish(wall="back", material="zellige tiles", extent_m=(0.0, 5.0, 0.0, 1.12)),
        WallFinish(wall="right", material="lime plaster", extent_m=(0.0, 4.0, 0.0, 2.8)),
    ])])

    assert bind_wall_finishes(walls, segs, placed, reading) == 2
    back = [w for w in walls if w.finishes and w.finishes[0].wall_name == "back"]
    right = [w for w in walls if w.finishes and w.finishes[0].wall_name == "right"]
    assert len(back) == 1 and back[0].start[1] == 0.0 == back[0].end[1]   # north edge, z = 0
    assert len(right) == 1 and right[0].start[0] == 5.0 == right[0].end[0]  # east edge, x = 5
    zone = back[0].finishes[0]
    assert zone.material and zone.material_text == "zellige tiles" and zone.extent == (0.0, 5.0, 0.0, 1.12)


def test_scenes_stored_before_p22_load_without_finishes():
    w = Wall.model_validate({"wall_id": "w", "start": (0.0, 0.0), "end": (1.0, 0.0)})
    assert w.finishes == []

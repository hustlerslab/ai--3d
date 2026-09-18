"""Spatial reconciliation: semantics from the reader, geometry from a detector.

The layer between knowing WHAT is in a room and deciding WHERE it goes. It must
never produce a coordinate, never let a detector add furniture nobody approved,
and never call something HIGH confidence because one source agreed with itself.

No GPU, no Ollama, no detector download, no network, no Blender - detections are
plain dicts, which is exactly the shape the benchmark detector returns.
"""
from __future__ import annotations

import json

from app.intelligence.schema import (
    CAMERA_FRAME_PREDICATES, SceneElement, SceneReading, SpatialGraph)
from app.planning.spatial_graph import build_spatial_graph


def el(element_id, semantic_type, room="living_room", bbox=(0.1, 0.1, 0.3, 0.3), **kw):
    return SceneElement(element_id=element_id, room_id=room, semantic_type=semantic_type,
                        name=kw.pop("name", semantic_type), bbox=bbox,
                        check=kw.pop("check", "ok"), crop_ref=f"{element_id}.png", **kw)


def det(label, bbox, score=0.9):
    return {"label": label, "bbox": bbox, "score": score}


def rel_between(graph, subject, predicate, obj=""):
    return [r for r in graph.relations
            if r.subject_id == subject and r.predicate == predicate
            and (not obj or r.object_id == obj)]


SOFA = el("sofa1", "sofa", bbox=(0.05, 0.30, 0.45, 0.60))
TABLE = el("tbl1", "coffee_table", bbox=(0.30, 0.55, 0.60, 0.80))
FAR_LAMP = el("lamp1", "floor_lamp", bbox=(0.88, 0.05, 0.98, 0.25))


# -- the responsibility split --------------------------------------------

def test_agreement_between_the_two_sources_is_high_confidence():
    reading = SceneReading(elements=[SOFA, el("tbl1", "coffee_table",
                                              bbox=(0.30, 0.55, 0.60, 0.80),
                                              against="the sofa")])
    graph = build_spatial_graph(reading, detections={"living_room": [
        det("sofa", (0.06, 0.31, 0.44, 0.59)), det("coffee table", (0.31, 0.56, 0.59, 0.79))]})
    matched = rel_between(graph, "tbl1", "AGAINST", "sofa1")
    assert matched and matched[0].confidence == "HIGH"
    assert matched[0].source == "semantic+geometry"


def test_the_readers_own_box_agreeing_with_itself_is_not_high():
    """The bug this catches: with no detector, the 'geometry' corroborating a
    semantic claim IS the reader's own bounding box. One source agreeing with
    itself must not be reported as two sources agreeing."""
    reading = SceneReading(elements=[SOFA, el("tbl1", "coffee_table",
                                              bbox=(0.30, 0.55, 0.60, 0.80),
                                              against="the sofa")])
    graph = build_spatial_graph(reading)
    assert not [r for r in graph.relations if r.confidence == "HIGH"]
    assert any("nothing independent confirms it" in r.note for r in graph.relations)


def test_an_element_without_geometry_confirmation_survives():
    """Step 3 rule 4: no confirmation is not grounds for deletion."""
    reading = SceneReading(elements=[SOFA, FAR_LAMP])
    graph = build_spatial_graph(reading, detections={"living_room": [
        det("sofa", (0.06, 0.31, 0.44, 0.59))]})
    assert {n.node_id for n in graph.nodes} == {"sofa1", "lamp1"}
    lamp = next(n for n in graph.nodes if n.node_id == "lamp1")
    assert lamp.geometry_confirmed is False
    assert lamp.source_confidence == "LOW"


def test_a_detection_the_reader_never_named_is_never_promoted():
    """Step 3 rule 3. Phase 0b measured this detector proposing 20 false
    positives against the reader's 6-8; it does not get to add furniture."""
    reading = SceneReading(elements=[SOFA])
    graph = build_spatial_graph(reading, detections={"living_room": [
        det("sofa", (0.06, 0.31, 0.44, 0.59)), det("bathtub", (0.80, 0.80, 0.95, 0.95), 0.42)]})
    assert {n.semantic_type for n in graph.nodes} == {"sofa"}
    assert [u.label for u in graph.unmatched_detections] == ["bathtub"]
    assert any("never added to the plan" in w for w in graph.warnings)


def test_the_detector_never_overrides_what_a_piece_is():
    """Qwen owns identity. A detection matched to an element changes its box,
    never its semantic_type."""
    reading = SceneReading(elements=[el("x1", "sofa", bbox=(0.1, 0.1, 0.5, 0.5))])
    graph = build_spatial_graph(reading, detections={"living_room": [
        det("sofa", (0.12, 0.12, 0.48, 0.48))]})
    assert graph.nodes[0].semantic_type == "sofa"


# -- image-space relationships -------------------------------------------

def test_left_and_right_are_derived_but_marked_camera_frame():
    """Phase 0a established that a render has no fixed left relative to the
    floor plan. These are ordering between two pieces in one view, and the
    marker is what stops a later phase reading them as room directions."""
    left = el("a", "sofa", bbox=(0.05, 0.40, 0.25, 0.60))
    right = el("b", "armchair", bbox=(0.70, 0.40, 0.90, 0.60))
    graph = build_spatial_graph(SceneReading(elements=[left, right]))
    found = rel_between(graph, "a", "LEFT_OF", "b")
    assert found, "ordering must be recorded"
    assert found[0].frame == "camera"
    assert all(r.frame == "camera" for r in graph.relations
               if r.predicate in CAMERA_FRAME_PREDICATES)
    assert all(r.frame == "floor_plan" for r in graph.relations
               if r.predicate not in CAMERA_FRAME_PREDICATES)


def test_right_of_is_emitted_when_the_first_piece_is_the_right_hand_one():
    """Pairs are walked in sorted element_id order and emit ONE direction each,
    so a pair never yields both LEFT_OF and RIGHT_OF. That is what keeps the
    graph deterministic; it is not symmetry."""
    right = el("a", "armchair", bbox=(0.70, 0.40, 0.90, 0.60))
    left = el("b", "sofa", bbox=(0.05, 0.40, 0.25, 0.60))
    graph = build_spatial_graph(SceneReading(elements=[left, right]))
    assert rel_between(graph, "a", "RIGHT_OF", "b")
    assert rel_between(graph, "b", "LEFT_OF", "a") == [], "one direction per pair"


def test_above_and_below_follow_image_rows():
    top = el("art", "wall_art", bbox=(0.30, 0.05, 0.50, 0.25))
    bottom = el("sofa1", "sofa", bbox=(0.25, 0.50, 0.60, 0.75))
    graph = build_spatial_graph(SceneReading(elements=[top, bottom]))
    found = rel_between(graph, "art", "ABOVE", "sofa1")
    assert found and found[0].frame == "camera"
    assert rel_between(graph, "sofa1", "BELOW", "art") == [], "one direction per pair"


def test_pieces_at_nearly_the_same_centre_get_no_left_right():
    """Without a tolerance, three pixels of difference becomes a confident
    LEFT_OF, and the solver inherits noise as though it were evidence."""
    a = el("a", "sofa", bbox=(0.20, 0.20, 0.60, 0.40))
    b = el("b", "rug", bbox=(0.21, 0.45, 0.59, 0.70))
    graph = build_spatial_graph(SceneReading(elements=[a, b]))
    assert not rel_between(graph, "a", "LEFT_OF")
    assert not rel_between(graph, "a", "RIGHT_OF")


def test_near_is_distance_not_type():
    close = build_spatial_graph(SceneReading(elements=[
        el("a", "sofa", bbox=(0.10, 0.40, 0.30, 0.60)),
        el("b", "side_table", bbox=(0.32, 0.42, 0.44, 0.58))]))
    assert rel_between(close, "a", "NEAR", "b")

    apart = build_spatial_graph(SceneReading(elements=[
        el("a", "sofa", bbox=(0.02, 0.05, 0.18, 0.20)),
        el("b", "side_table", bbox=(0.82, 0.80, 0.96, 0.95))]))
    assert not rel_between(apart, "a", "NEAR", "b")


def test_adjacent_needs_a_shared_row_and_a_small_gap():
    touching = build_spatial_graph(SceneReading(elements=[
        el("a", "sofa", bbox=(0.10, 0.40, 0.40, 0.60)),
        el("b", "side_table", bbox=(0.42, 0.42, 0.52, 0.58))]))
    assert rel_between(touching, "a", "ADJACENT_TO", "b")

    # same gap, but no shared row: one is high on the wall, one on the floor
    offset = build_spatial_graph(SceneReading(elements=[
        el("a", "sofa", bbox=(0.10, 0.70, 0.40, 0.90)),
        el("b", "wall_art", bbox=(0.42, 0.05, 0.52, 0.20))]))
    assert not rel_between(offset, "a", "ADJACENT_TO", "b")


def test_overlap_is_recorded_not_treated_as_placement():
    graph = build_spatial_graph(SceneReading(elements=[
        el("rug1", "rug", bbox=(0.05, 0.50, 0.70, 0.95)),
        el("tbl1", "coffee_table", bbox=(0.30, 0.55, 0.60, 0.80))]))
    overlaps = rel_between(graph, "rug1", "OVERLAPS", "tbl1")
    assert overlaps
    assert "occlusion, grouping or a bad box" in overlaps[0].note


# -- semantic hints, reusing Phase 0a's fields ---------------------------

def test_a_named_faces_hint_becomes_a_relationship():
    graph = build_spatial_graph(SceneReading(elements=[
        el("sofa1", "sofa", bbox=(0.05, 0.30, 0.45, 0.60), faces="the tv unit"),
        el("tv1", "tv_unit", bbox=(0.65, 0.20, 0.95, 0.45))]))
    assert rel_between(graph, "sofa1", "FACES", "tv1")


def test_camera_relative_hints_are_still_refused():
    """`left wall` was never usable and must not sneak in through this layer."""
    graph = build_spatial_graph(SceneReading(elements=[
        el("sofa1", "sofa", faces="front", against="the left wall"),
        el("tv1", "tv_unit", bbox=(0.65, 0.20, 0.95, 0.45))]))
    assert not rel_between(graph, "sofa1", "FACES")
    assert not [r for r in graph.relations
                if r.predicate == "AGAINST" and r.subject_id == "sofa1"]
    walls = rel_between(graph, "sofa1", "AGAINST_WALL")
    assert walls, "'wall' is architecture, so it is kept - but without choosing one"
    assert walls[0].object_id == ""


def test_an_on_surface_piece_records_what_holds_it():
    graph = build_spatial_graph(SceneReading(elements=[
        el("tbl1", "coffee_table", bbox=(0.30, 0.55, 0.60, 0.80)),
        el("vase1", "vase", bbox=(0.40, 0.50, 0.46, 0.58),
           placement="on_surface", against="the coffee table")]))
    assert rel_between(graph, "vase1", "ON_TOP_OF", "tbl1")


# -- grouping ------------------------------------------------------------

def test_a_seating_arrangement_is_grouped():
    graph = build_spatial_graph(SceneReading(elements=[
        el("sofa1", "sofa", bbox=(0.05, 0.30, 0.45, 0.60)),
        el("tbl1", "coffee_table", bbox=(0.30, 0.55, 0.60, 0.80)),
        el("rug1", "rug", bbox=(0.02, 0.55, 0.75, 0.95))]))
    assert len(graph.groups) == 1
    group = graph.groups[0]
    assert group.group_type == "seating"
    assert set(group.members) == {"sofa1", "tbl1", "rug1"}


def test_an_anchor_on_its_own_is_not_a_group():
    graph = build_spatial_graph(SceneReading(elements=[el("bed1", "bed", room="bedroom")]))
    assert graph.groups == []


def test_a_piece_across_the_room_is_not_in_the_arrangement():
    graph = build_spatial_graph(SceneReading(elements=[
        el("bed1", "bed", room="bedroom", bbox=(0.05, 0.30, 0.45, 0.70)),
        el("tbl1", "bedside_table", room="bedroom", bbox=(0.47, 0.40, 0.58, 0.60)),
        el("wr1", "wardrobe", room="bedroom", bbox=(0.90, 0.02, 0.99, 0.30))]))
    members = set(graph.groups[0].members)
    assert "tbl1" in members and "wr1" not in members


# -- conflicts -----------------------------------------------------------

def test_a_named_relationship_the_picture_contradicts_is_a_conflict():
    graph = build_spatial_graph(SceneReading(elements=[
        el("sofa1", "sofa", bbox=(0.02, 0.05, 0.20, 0.25)),
        el("lamp1", "floor_lamp", bbox=(0.85, 0.80, 0.98, 0.97), against="the sofa")]))
    assert len(graph.conflicts) == 1
    conflict = graph.conflicts[0]
    assert conflict.resolution == "unresolved", "neither side is chosen automatically"
    assert conflict.semantic_evidence and conflict.geometry_evidence
    assert rel_between(graph, "lamp1", "AGAINST", "sofa1"), "the claim itself survives"


# -- hygiene -------------------------------------------------------------

def test_flagged_elements_do_not_draw_relationships():
    graph = build_spatial_graph(SceneReading(elements=[
        SOFA, el("bad", "bathtub", bbox=(0.5, 0.5, 0.7, 0.7), check="implausible")]))
    assert {n.node_id for n in graph.nodes} == {"sofa1"}
    assert any("excluded" in w for w in graph.warnings)


def test_no_coordinate_ever_appears_in_the_graph():
    """The architectural rule. Boxes are image fractions and stay inside the
    reconciler; nothing in the output names metres, x, y or z."""
    graph = build_spatial_graph(SceneReading(elements=[SOFA, TABLE]))
    blob = graph.model_dump_json()
    for forbidden in ('"x"', '"y"', '"z"', '"position"', '"rotation"', '"dimensions_m"'):
        assert forbidden not in blob, f"{forbidden} leaked into the spatial graph"


def test_raw_model_output_never_reaches_the_graph():
    reading = SceneReading(elements=[SOFA], warnings=["raw: {'elements': [ ... ]}"])
    blob = build_spatial_graph(reading).model_dump_json()
    assert "raw:" not in blob


def test_the_graph_round_trips_through_json():
    graph = build_spatial_graph(SceneReading(elements=[SOFA, TABLE]))
    again = SpatialGraph.model_validate(json.loads(graph.model_dump_json()))
    assert again.model_dump(exclude={"created_at"}) == graph.model_dump(exclude={"created_at"})


def test_the_same_input_gives_the_same_graph():
    reading = SceneReading(elements=[TABLE, SOFA, FAR_LAMP])
    a = build_spatial_graph(reading).model_dump(exclude={"created_at"})
    b = build_spatial_graph(reading).model_dump(exclude={"created_at"})
    assert a == b


def test_duplicate_elements_are_left_to_the_pass_that_owns_them():
    """`mark_duplicates` already decides this on IoU. A piece it flagged is
    excluded here rather than re-judged with a second, different rule."""
    graph = build_spatial_graph(SceneReading(elements=[
        SOFA, el("dup", "sofa", bbox=(0.06, 0.31, 0.44, 0.59), check="duplicate")]))
    assert {n.node_id for n in graph.nodes} == {"sofa1"}


def test_facing_into_the_room_is_kept_as_orientation():
    """One of the answers the prompt asks for by name, and one `_faces_rank`
    already consumes in the compiler. Dropping it here would lose orientation
    the reader actually supplied. No object: which way inward points depends on
    the room, which this layer does not decide."""
    graph = build_spatial_graph(SceneReading(elements=[
        el("a", "sideboard", against="floor", faces="into the room")]))
    found = rel_between(graph, "a", "FACES_ROOM")
    assert found and found[0].object_id == ""


def test_standing_on_the_floor_is_not_a_relationship():
    """Everything stands on the floor, so `against: floor` carries no
    arrangement information and must not become an AGAINST_WALL."""
    graph = build_spatial_graph(SceneReading(elements=[el("a", "sideboard", against="floor")]))
    assert not rel_between(graph, "a", "AGAINST_WALL")
    assert not rel_between(graph, "a", "AGAINST")

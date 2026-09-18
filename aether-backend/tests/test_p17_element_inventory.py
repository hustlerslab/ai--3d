"""P17: how many of each piece a room was read to hold, written down.

The element-first research concluded that the pipeline's real inventory defect
is not that it cannot count - `merge_reading_into_plan` carries multiplicity
correctly as N plan items, measured 8 of 8. The defect is that the number is
implicit in `len(...)` everywhere, so when a check removes two of three bar
stools, nothing records that three were ever there.

These assert the number is now stated, that it is DERIVED rather than authored
by a model, and that stating it changed no placement.

Evidence: research/element-first/decision-record.md
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.intelligence.schema import ObjectPlan, SceneElement, SceneReading
from app.intelligence.scene_reading import (element_inventory, inventory_notes,
                                            mark_duplicates, merge_reading_into_plan)

#: The documented real failure: three "black bar stool" boxes each running to
#: the right edge of the kitchen, so each contains the next.
EDGE_BOXES = [(0.1, 0.5, 0.9, 0.8), (0.3, 0.5, 0.9, 0.8), (0.5, 0.5, 0.9, 0.8)]
CLEAN_BOXES = [(0.1, 0.5, 0.2, 0.8), (0.3, 0.5, 0.4, 0.8), (0.5, 0.5, 0.6, 0.8)]


def _stools(boxes, approved=None, room="kitchen") -> SceneReading:
    return SceneReading(elements=[
        SceneElement(element_id=f"el_{i}", room_id=room, name="black bar stool",
                     semantic_type="bar_stool", bbox=b, check="ok", approved=approved)
        for i, b in enumerate(boxes)])


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


# ── the number is stated ─────────────────────────────────────────────────

def test_three_stools_read_as_three():
    inventory = element_inventory(_stools(CLEAN_BOXES))
    assert len(inventory) == 1
    assert inventory[0].read == 3
    assert inventory[0].usable == 3
    assert not inventory[0].discrepant


def test_a_silent_loss_is_now_recorded():
    """The whole point. Two of three stools are removed by `mark_duplicates`
    and, before this, left no trace anywhere in the system."""
    reading = _stools(EDGE_BOXES)
    assert mark_duplicates(reading) == 2

    row = element_inventory(reading)[0]
    assert row.read == 3, "three stools were read"
    assert row.usable == 1, "only one survives, which is the existing behaviour"
    assert row.discrepant
    assert row.lost_to == {"duplicate": 2}, "and the reason is named"


def test_the_shortfall_is_reported_in_words():
    reading = _stools(EDGE_BOXES)
    mark_duplicates(reading)
    notes = inventory_notes(element_inventory(reading))

    assert notes == ["kitchen: read 3 bar stool, 1 usable (2 duplicate)"]


def test_nothing_is_reported_when_nothing_was_lost():
    """A note on every room every time would be noise, and would train people
    to ignore the one that matters."""
    assert inventory_notes(element_inventory(_stools(CLEAN_BOXES))) == []


@pytest.mark.parametrize("check,reason", [
    ("duplicate", "duplicate"), ("mismatch", "mismatch"),
    ("crowded", "crowded"), ("unreadable", "unreadable"),
])
def test_every_check_that_removes_a_piece_is_named(check, reason):
    reading = _stools(CLEAN_BOXES)
    reading.elements[0].check = check
    row = element_inventory(reading)[0]

    assert row.usable == 2
    assert row.lost_to == {reason: 1}


def test_an_unreviewed_piece_is_counted_as_unapproved_not_as_a_check():
    """`unchecked` is not a verdict, it means nobody looked yet."""
    reading = _stools(CLEAN_BOXES)
    reading.elements[0].check = "unchecked"
    assert element_inventory(reading)[0].lost_to == {"unapproved": 1}


def test_a_human_approval_overrides_a_duplicate_flag_and_the_count_follows():
    """`trustworthy` prefers an explicit human decision over the check, so the
    inventory must agree with what will actually be planned."""
    reading = _stools(EDGE_BOXES, approved=True)
    mark_duplicates(reading)
    row = element_inventory(reading)[0]

    assert row.read == 3 and row.usable == 3
    assert not row.discrepant


# ── it is derived, never authored ────────────────────────────────────────

def test_the_count_is_computed_from_the_rows_not_taken_from_a_model():
    """The research measured a 3B model producing 2-3 different inventories for
    the same vague brief across 3 runs. Nothing here asks a model anything."""
    reading = _stools(CLEAN_BOXES)
    reading.inventory = element_inventory(reading)
    # a stored count that disagrees with the rows must not win
    reading.inventory[0].read = 99

    assert element_inventory(reading)[0].read == 3


def test_the_inventory_is_deterministic_and_ordered():
    reading = SceneReading(elements=[
        SceneElement(element_id="b", room_id="living_room", semantic_type="sofa",
                     bbox=(0.1, 0.1, 0.2, 0.2), check="ok"),
        SceneElement(element_id="a", room_id="kitchen", semantic_type="bar_stool",
                     bbox=(0.3, 0.3, 0.4, 0.4), check="ok"),
    ])
    runs = [[(r.room_id, r.semantic_type) for r in element_inventory(reading)]
            for _ in range(10)]

    assert all(r == runs[0] for r in runs)
    assert runs[0] == [("kitchen", "bar_stool"), ("living_room", "sofa")]


def test_a_reading_written_before_this_field_existed_still_loads_and_counts():
    """Backward compatibility: no `inventory` key at all must not raise, and
    must not be read as 'zero of everything'."""
    old = SceneReading.model_validate({
        "elements": [{"room_id": "kitchen", "semantic_type": "bar_stool",
                      "bbox": [0.1, 0.5, 0.2, 0.8], "check": "ok"}],
    })
    assert old.inventory == []
    assert element_inventory(old)[0].read == 1


# ── counting changed no behaviour ────────────────────────────────────────

def test_counting_does_not_change_what_reaches_the_plan():
    """P17 states the number; it must not alter the number. The plan is the
    same before and after the inventory is computed."""
    for boxes in (CLEAN_BOXES, EDGE_BOXES):
        reading = _stools(boxes)
        mark_duplicates(reading)
        before, _ = merge_reading_into_plan(ObjectPlan(rooms=["kitchen"], items=[]), reading)
        planned_before = sum(i.count for i in before.items)

        reading.inventory = element_inventory(reading)
        after, _ = merge_reading_into_plan(ObjectPlan(rooms=["kitchen"], items=[]), reading)

        assert sum(i.count for i in after.items) == planned_before


def test_the_usable_count_equals_what_the_plan_actually_receives():
    """The number reported and the number planned must be the same number, or
    the report is worse than nothing."""
    reading = _stools(EDGE_BOXES)
    mark_duplicates(reading)
    row = element_inventory(reading)[0]
    plan, _ = merge_reading_into_plan(ObjectPlan(rooms=["kitchen"], items=[]), reading)

    assert sum(i.count for i in plan.items if i.semantic_type == "bar_stool") == row.usable


# ── it reaches the review screen ─────────────────────────────────────────

def test_the_review_route_reports_the_inventory(client):
    """The screen where a human decides what to buy is the screen that has to
    say 'three read, one usable'."""
    pid = client.post("/api/projects", json={"name": "p17"}).json()["project"]["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (150, 160, 140)).save(buf, "JPEG")
    assert client.post(f"/api/projects/{pid}/inputs", data={"description": "A kitchen."},
                       files=[("references", ("k.jpg", buf.getvalue(), "image/jpeg"))]
                       ).status_code == 200

    reading = _stools(EDGE_BOXES)
    mark_duplicates(reading)
    from app.projects.layout import project_dir
    path = project_dir(pid) / "planning" / "scene_reading.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reading.model_dump_json(), encoding="utf-8")

    summary = client.get(f"/api/projects/{pid}/scene-reading").json()["data"]["summary"]
    assert summary["inventory"], "the review screen cannot see the counts"
    row = summary["inventory"][0]
    assert (row["read"], row["usable"]) == (3, 1)
    assert summary["inventory_notes"] == ["kitchen: read 3 bar stool, 1 usable (2 duplicate)"]

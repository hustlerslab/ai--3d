"""P1-FRONTEND-001: element states, authoritative counts, and assumptions -
decided by the backend so the review screen only displays them."""
from __future__ import annotations

from app.intelligence.element_states import STATES, assumptions, element_states, inventory_counts
from app.intelligence.scene_reading import resolve_elements
from app.intelligence.schema import SceneElement, SceneReading
from tests.test_asset_rebind import _project_with_render, client  # noqa: F401
from tests.test_element_first import _plan_with


def _el(i, **over) -> SceneElement:
    base = dict(element_id=f"el_{i}", room_id="kitchen", name="black bar stool", semantic_type="bar_stool",
                bbox=(0.1 + 0.2 * i, 0.5, 0.2 + 0.2 * i, 0.8), check="ok", material="oak", color="black")
    base.update(over)
    return SceneElement(**base)


def _states(reading: SceneReading) -> dict[str, str]:
    definitions, instances = resolve_elements(reading)
    return element_states(reading, definitions, instances)


def test_each_row_gets_one_of_the_four_states():
    reading = SceneReading(elements=[
        _el(0, approved=True),                       # checked and confirmed
        _el(1, approved=None),                       # checked, waiting for the person
        _el(2, approved=False),                      # the person said no
        _el(3, check="mismatch", approved=None),     # a check removed it
    ])
    states = _states(reading)
    assert set(states.values()) <= set(STATES)
    assert states["el_0"] == "validated"
    assert states["el_1"] == "detected"
    assert states["el_2"] == "rejected"
    assert states["el_3"] == "rejected"


def test_a_piece_with_nothing_to_match_on_is_unresolved():
    # no material, colour or size: identity cannot be established
    reading = SceneReading(elements=[_el(0, material="", color="", approved=True)])
    definitions, instances = resolve_elements(reading)
    assert definitions[0].identity_method == "unresolved"
    assert element_states(reading, definitions, instances)["el_0"] == "unresolved"


def test_counts_are_counted_from_what_is_sent():
    reading = SceneReading(elements=[_el(i, approved=True) for i in range(3)] + [_el(9, approved=False)])
    definitions, instances = resolve_elements(reading)
    states = element_states(reading, definitions, instances)
    counts = inventory_counts(reading, definitions, instances, states)
    assert counts["detected_rows"] == 4
    assert counts["canonical"] == len(definitions) == 1, "three matching stools are one piece"
    assert counts["instances"] == len(instances) == 3
    assert counts["assets"] == 0
    assert counts["by_state"] == {"validated": 3, "rejected": 1, "detected": 0, "unresolved": 0}
    assert sum(counts["by_state"].values()) == counts["detected_rows"]


def test_every_estimate_is_listed_in_plain_words():
    reading = SceneReading(elements=[
        _el(0, position_source="derived", approved=True),
        _el(1, position_source="read", approved=True),
        _el(2, position_source="", approved=True, name="", semantic_type="floor_lamp", material="", color=""),
        _el(3, position_source="derived", approved=False),       # rejected rows are not assumptions
    ])
    definitions, instances = resolve_elements(reading)
    states = element_states(reading, definitions, instances)
    analysis = {"rooms": [{"room_id": "kitchen", "name": "Kitchen", "width_m": 3.0, "length_m": 4.2, "estimated": True},
                          {"room_id": "bedroom", "name": "Bedroom", "width_m": 3.2, "length_m": 3.6, "estimated": False}]}
    found = assumptions(reading, states, definitions, analysis)
    kinds = [(a["kind"], a["ref"]) for a in found]
    assert ("room_size", "kitchen") in kinds and ("room_size", "bedroom") not in kinds
    assert ("position", "el_0") in kinds, "a derived position is an estimate"
    assert ("position", "el_1") not in kinds, "a read position is not"
    assert ("position", "el_2") in kinds, "no position at all is a guess by the layout"
    assert ("position", "el_3") not in kinds, "a rejected piece is not something the design rests on"
    for a in found:
        assert a["statement"] and a["change"]
        assert "_" not in a["statement"], "plain words, no internal keys or ids"


def test_same_kind_pieces_kept_apart_is_an_assumption():
    reading = SceneReading(elements=[_el(i, material="", color="", approved=True) for i in range(2)])
    definitions, instances = resolve_elements(reading)
    states = element_states(reading, definitions, instances)
    found = [a for a in assumptions(reading, states, definitions, None) if a["kind"] == "identity"]
    assert len(found) == 1
    assert found[0]["statement"].startswith("2 bar stool pieces")


def test_the_review_endpoint_carries_states_counts_and_assumptions(client, monkeypatch):  # noqa: F811
    pid, ctx = _project_with_render(client)
    _plan_with(ctx, monkeypatch, force=False)
    from app.jobs import get_job_store
    from app.jobs.schema import JobStatus

    get_job_store().update(ctx.job.job_id, status=JobStatus.CANCELLED)
    data = client.get(f"/api/projects/{pid}/scene-reading").json()["data"]
    reading, summary = data["reading"], data["summary"]
    assert set(summary["element_states"]) == {e["element_id"] for e in reading["elements"]}
    assert summary["counts"]["detected_rows"] == len(reading["elements"])
    assert summary["counts"]["canonical"] == len(summary["definitions"])
    assert summary["counts"]["instances"] == len(summary["instances"])
    assert any(a["kind"] == "room_size" for a in summary["assumptions"]), "the mock analysis estimates room sizes"

"""P21: the client decides on the pictured pieces BEFORE the room is painted,
and that decision follows the piece onto the moodboard reading.

Two things are pinned here. The PATCH route stores {element_id: build?} on
the canonical piece, validates ids, merges rather than replaces, and echoes
the stored set. And `_carry_element_decisions` moves those decisions onto
the reading rows that are the same piece - by canonical key, never by
position - without ever overwriting a decision a human made on the review
screen. GPU off throughout, as in P20.
"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.intelligence.schema import ElementDefinition, ElementImageSet, SceneElement
from app.jobs import get_runner
from app.jobs.handlers.scene_plan import _carry_element_decisions
from app.projects.layout import project_dir


@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "false")
    from app.core import config
    config.get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c


def _project(client) -> str:
    pid = client.post("/api/projects", json={"name": "p21"}).json()["project"]["project_id"]
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (150, 160, 140)).save(buf, "JPEG")
    r = client.post(f"/api/projects/{pid}/inputs",
                    data={"description": "A living room with one sofa, two armchairs and a coffee table."},
                    files=[("references", ("sofa.jpg", buf.getvalue(), "image/jpeg"))])
    assert r.status_code == 200
    return pid


def _run(client, path, body=None, timeout=300):
    r = client.post(path, json=body or {})
    assert r.status_code == 200, r.text
    job_id = r.json()["job"]["job_id"]
    assert get_runner().wait_idle(timeout)
    return client.get(f"/api/jobs/{job_id}").json()["data"]["job"]


def _pictured(client) -> tuple[str, list[str]]:
    pid = _project(client)
    assert _run(client, f"/api/projects/{pid}/analyze", {"paint": False})["status"] == "SUCCEEDED"
    assert _run(client, f"/api/projects/{pid}/element-images")["status"] == "SUCCEEDED"
    ids = [d["element_id"] for d in client.get(f"/api/projects/{pid}/element-images").json()["data"]["definitions"]]
    assert ids, "no pieces were planned"
    return pid, ids


# ── the route ───────────────────────────────────────────────────────────

def test_deciding_before_the_pieces_exist_is_a_clear_404(client):
    pid = _project(client)
    r = client.patch(f"/api/projects/{pid}/element-images", json={"decisions": {"cel_nope": True}})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ELEMENT_IMAGES_NOT_READY"


def test_an_unknown_piece_is_refused_and_nothing_is_written(client):
    pid, ids = _pictured(client)
    r = client.patch(f"/api/projects/{pid}/element-images",
                     json={"decisions": {ids[0]: True, "cel_0000000000": False}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UNKNOWN_ELEMENT"
    on_disk = json.loads((project_dir(pid) / "planning" / "element_images.json").read_text(encoding="utf-8"))
    assert all(d["approved"] is None for d in on_disk["definitions"])


def test_decisions_are_stored_merged_and_echoed(client):
    pid, ids = _pictured(client)
    first = client.patch(f"/api/projects/{pid}/element-images", json={"decisions": {ids[0]: False}})
    assert first.status_code == 200
    by_id = {d["element_id"]: d["approved"] for d in first.json()["data"]["definitions"]}
    assert by_id[ids[0]] is False
    assert all(by_id[i] is None for i in ids[1:])

    # A second decision on another piece does not undo the first.
    if len(ids) > 1:
        second = client.patch(f"/api/projects/{pid}/element-images", json={"decisions": {ids[1]: True}})
        by_id = {d["element_id"]: d["approved"] for d in second.json()["data"]["definitions"]}
        assert by_id[ids[0]] is False and by_id[ids[1]] is True

    # GET answers with the same stored truth, URLs included.
    got = client.get(f"/api/projects/{pid}/element-images").json()["data"]
    assert {d["element_id"]: d["approved"] for d in got["definitions"]} == by_id
    on_disk = json.loads((project_dir(pid) / "planning" / "element_images.json").read_text(encoding="utf-8"))
    assert {d["element_id"]: d["approved"] for d in on_disk["definitions"]} == by_id


# ── the carry-over onto the reading ────────────────────────────────────

class _Ctx:
    """Just enough of JobContext: the one checkpoint the carry-over reads."""

    def __init__(self, images: ElementImageSet | None):
        self._data = None if images is None else images.model_dump(mode="json")

    def has_checkpoint(self, rel: str) -> bool:
        return self._data is not None

    def read_json(self, rel: str):
        return self._data


def _definition(element_id: str, stype: str, approved, *, material="plastic", color="#111111",
                room="kitchen") -> ElementDefinition:
    return ElementDefinition(element_id=element_id, room_id=room, semantic_type=stype,
                             canonical_name=stype, material=material, color=color, dimensions_m=None,
                             identity_method="room_type_dims_material_colour", instance_count=1,
                             source_element_ids=[f"{room}.{stype}.0"], canonical_asset_id="",
                             approved=approved)


def _row(element_id: str, stype: str, *, material="plastic", color="#111111", room="kitchen",
         approved=None) -> SceneElement:
    return SceneElement(element_id=element_id, room_id=room, semantic_type=stype, material=material,
                        color=color, bbox=(0.1, 0.5, 0.2, 0.8), check="ok", approved=approved)


def test_a_decided_piece_carries_onto_its_reading_rows_by_identity_only():
    images = ElementImageSet(definitions=[
        _definition("cel_stool", "bar_stool", True),
        _definition("cel_lamp", "floor_lamp", False, material="brass", color="#C0A060"),
    ])
    reading = SimpleNamespace(elements=[
        _row("el_1", "bar_stool"),                       # same stool, different position
        _row("el_2", "bar_stool"),                       # a second one: same identity, same verdict
        _row("el_3", "floor_lamp", material="brass", color="#C0A060"),
        _row("el_4", "bar_stool", material="oak"),       # different evidence: not the same piece
        _row("el_5", "sofa", material="linen"),          # the pictures never covered it
    ])
    carried = _carry_element_decisions(_Ctx(images), reading)

    assert carried == 3
    verdicts = {e.element_id: e.approved for e in reading.elements}
    assert verdicts == {"el_1": True, "el_2": True, "el_3": False, "el_4": None, "el_5": None}


def test_a_human_decision_on_the_reading_is_never_overwritten():
    images = ElementImageSet(definitions=[_definition("cel_stool", "bar_stool", True)])
    reading = SimpleNamespace(elements=[_row("el_1", "bar_stool", approved=False)])
    assert _carry_element_decisions(_Ctx(images), reading) == 0
    assert reading.elements[0].approved is False


def test_undecided_pieces_and_missing_pictures_carry_nothing():
    undecided = ElementImageSet(definitions=[_definition("cel_stool", "bar_stool", None)])
    reading = SimpleNamespace(elements=[_row("el_1", "bar_stool")])
    assert _carry_element_decisions(_Ctx(undecided), reading) == 0
    assert _carry_element_decisions(_Ctx(None), reading) == 0
    assert reading.elements[0].approved is None


def test_no_evidence_never_inherits_a_decision():
    """An unresolved key is `room|type|?<id>`: two such pieces are never the
    same piece, so a decision on one cannot land on the other."""
    images = ElementImageSet(definitions=[_definition("cel_t", "side_table", True, material="", color="")])
    reading = SimpleNamespace(elements=[_row("el_1", "side_table", material="", color="")])
    assert _carry_element_decisions(_Ctx(images), reading) == 0
    assert reading.elements[0].approved is None

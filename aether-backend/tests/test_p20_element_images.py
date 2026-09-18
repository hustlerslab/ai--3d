"""P20: the pieces are decided and pictured BEFORE any room is painted.

Stage 1 of element-first. The inventory comes from the object plan - the
client's photographed pieces plus the brief, with counts - and each canonical
piece gets one isolated picture. These run with local image generation OFF so
they are deterministic and GPU-free: they assert the inventory, the identity
sharing with the moodboard reading, the prompt, the Meshy-input preference and
the routes. The pictures themselves are measured in the research harness.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.intelligence.prompts import ELEMENT_NEGATIVE, SD_NEGATIVE, element_prompt_sd
from app.intelligence.schema import ObjectPlan, ObjectPlanItem, SceneElement
from app.intelligence.scene_reading import canonical_key, canonical_key_for, definitions_from_plan
from app.jobs import get_runner
from app.projects.layout import project_dir


def _item(key: str, room: str, stype: str, count: int = 1, material: str = "", color: str = "",
          crop: str = "") -> ObjectPlanItem:
    return ObjectPlanItem(object_key=key, semantic_type=stype, room_id=room, count=count,
                          material_hint=material, color_hint=color, crop_ref=crop)


@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "false")
    from app.core import config
    config.get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c


# ── the inventory before the room ─────────────────────────────────────

def test_a_planned_count_becomes_that_many_instances_of_one_piece():
    plan = ObjectPlan(rooms=["kitchen"], items=[_item("kitchen.bar_stool.0", "kitchen", "bar_stool",
                                                      count=3, material="plastic", color="#111111")])
    definitions, instances = definitions_from_plan(plan)

    assert len(definitions) == 1
    assert definitions[0].instance_count == 3
    assert len(instances) == 3
    assert {i.element_id for i in instances} == {definitions[0].element_id}


def test_two_planned_rows_of_the_same_piece_fold_into_one():
    """The planner may list a piece twice; identity, not row count, decides."""
    plan = ObjectPlan(rooms=["living_room"], items=[
        _item("living_room.armchair.0", "living_room", "armchair", material="linen", color="#D8CFC0"),
        _item("living_room.armchair.1", "living_room", "armchair", material="linen", color="#D8CFC0"),
    ])
    definitions, instances = definitions_from_plan(plan)
    assert len(definitions) == 1 and definitions[0].instance_count == 2
    assert len(instances) == 2


def test_different_evidence_stays_separate_and_no_evidence_never_merges():
    plan = ObjectPlan(rooms=["dining"], items=[
        _item("dining.chair.0", "dining", "dining_chair", material="linen"),
        _item("dining.chair.1", "dining", "dining_chair", material="velvet"),
        _item("dining.table.0", "dining", "side_table"),
        _item("dining.table.1", "dining", "side_table"),
    ])
    definitions, _ = definitions_from_plan(plan)
    assert len(definitions) == 4
    assert sum(1 for d in definitions if d.identity_method == "unresolved") == 2


def test_a_plan_piece_and_a_reading_row_share_one_identity():
    """The whole point of one key: a piece decided before the moodboard is the
    same piece when it is later read out of the moodboard."""
    plan = ObjectPlan(rooms=["kitchen"], items=[_item("kitchen.bar_stool.0", "kitchen", "bar_stool",
                                                      material="plastic", color="#111111")])
    d = definitions_from_plan(plan)[0][0]
    read = SceneElement(element_id="el_x", room_id="kitchen", semantic_type="bar_stool",
                        material="plastic", color="#111111", bbox=(0.1, 0.5, 0.2, 0.8), check="ok")
    plan_key = canonical_key_for(d.room_id, d.semantic_type, d.material, d.color, d.dimensions_m,
                                 "kitchen.bar_stool.0")
    assert plan_key == canonical_key(read)


def test_definitions_are_deterministic_and_position_free():
    plan = ObjectPlan(rooms=["r"], items=[_item("r.sofa.0", "r", "sofa", material="fabric")])
    assert len({definitions_from_plan(plan)[0][0].element_id for _ in range(5)}) == 1


# ── the picture prompt ─────────────────────────────────────────────────

def test_the_element_prompt_asks_for_one_isolated_piece():
    prompt = element_prompt_sd("bar_stool", "black bar stool", "plastic", ["modern", "warm"])
    assert "single" in prompt and "isolated" in prompt and "bar stool" in prompt
    assert "plastic" in prompt


def test_the_element_negative_is_the_mirror_of_the_room_negative():
    """A room must not be a product shot; a piece must be nothing but one."""
    assert "product photo" in SD_NEGATIVE and "product photo" not in ELEMENT_NEGATIVE
    assert "room" in ELEMENT_NEGATIVE and "interior" in ELEMENT_NEGATIVE
    assert "multiple objects" in ELEMENT_NEGATIVE


def test_the_prompt_never_sends_a_hex_colour():
    assert "#" not in element_prompt_sd("sofa", "sofa", "linen")


# ── the routes, GPU off ─────────────────────────────────────────────────

def _project(client) -> str:
    pid = client.post("/api/projects", json={"name": "p20"}).json()["project"]["project_id"]
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


def test_element_images_before_analysis_is_refused(client):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/element-images", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ANALYSIS_REQUIRED"


def test_analyze_without_paint_writes_no_room_image(client):
    pid = _project(client)
    job = _run(client, f"/api/projects/{pid}/analyze", {"paint": False})
    assert job["status"] == "SUCCEEDED", job.get("error")
    assert (project_dir(pid) / "analysis" / "design_analysis.json").exists()
    assert not list((project_dir(pid) / "analysis").glob("moodboard_room_*.png"))
    events = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["events"]
    assert any("not painted" in e["message"] for e in events)


def test_element_images_writes_the_inventory_with_or_without_pictures(client):
    pid = _project(client)
    assert _run(client, f"/api/projects/{pid}/analyze", {"paint": False})["status"] == "SUCCEEDED"
    job = _run(client, f"/api/projects/{pid}/element-images")
    assert job["status"] == "SUCCEEDED", job.get("error")

    data = json.loads((project_dir(pid) / "planning" / "element_images.json").read_text(encoding="utf-8"))
    assert data["definitions"], "no pieces were planned"
    assert sum(d["instance_count"] for d in data["definitions"]) == len(data["instances"])
    # GPU off: the inventory exists and says plainly that no picture was made
    assert data["images"] == []
    assert any("disabled" in w for w in data["warnings"])


def test_the_element_images_route_returns_what_was_written(client):
    pid = _project(client)
    assert _run(client, f"/api/projects/{pid}/analyze", {"paint": False})["status"] == "SUCCEEDED"
    assert _run(client, f"/api/projects/{pid}/element-images")["status"] == "SUCCEEDED"
    body = client.get(f"/api/projects/{pid}/element-images").json()["data"]
    assert body["definitions"] and "instances" in body and "images" in body


def test_element_images_reuses_the_plan_scene_plan_writes(client):
    """One object plan, one file: the element stage and the scene plan must
    agree on the inventory rather than each planning their own."""
    pid = _project(client)
    assert _run(client, f"/api/projects/{pid}/analyze")["status"] == "SUCCEEDED"
    assert _run(client, f"/api/projects/{pid}/element-images")["status"] == "SUCCEEDED"
    first = json.loads((project_dir(pid) / "planning" / "object_plan.json").read_text(encoding="utf-8"))
    assert _run(client, f"/api/projects/{pid}/scene-plan")["status"] == "SUCCEEDED"
    second = json.loads((project_dir(pid) / "planning" / "object_plan.json").read_text(encoding="utf-8"))
    assert [i["object_key"] for i in first["items"]] == [i["object_key"] for i in second["items"]]


# ── the Meshy input preference ─────────────────────────────────────────

def test_meshy_input_prefers_a_matching_element_image_and_falls_back_to_the_crop(client):
    from app.jobs import get_job_store
    from app.jobs.context import JobContext
    from app.jobs.handlers.generate_elements import element_image_for
    from app.projects import get_project_store

    pid = _project(client)
    assert _run(client, f"/api/projects/{pid}/analyze", {"paint": False})["status"] == "SUCCEEDED"
    assert _run(client, f"/api/projects/{pid}/element-images")["status"] == "SUCCEEDED"
    root = project_dir(pid)
    data = json.loads((root / "planning" / "element_images.json").read_text(encoding="utf-8"))
    d = data["definitions"][0]

    # pretend the picture was painted: matching key, file present, no error
    rel = f"planning/element_images/{d['element_id']}.png"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(b"png")
    key = canonical_key_for(d["room_id"], d["semantic_type"], d["material"], d["color"],
                            d["dimensions_m"], d["source_element_ids"][0])
    data["images"] = [{"element_image_id": "eim_t", "element_id": d["element_id"],
                       "canonical_key": key, "image_ref": rel}]
    (root / "planning" / "element_images.json").write_text(json.dumps(data), encoding="utf-8")

    job = get_job_store().latest_of_type(pid, "element_images")
    ctx = JobContext(job, get_project_store().get(pid), get_job_store(), get_project_store())
    matching = SceneElement(element_id="el_m", room_id=d["room_id"], semantic_type=d["semantic_type"],
                            material=d["material"], color=d["color"], bbox=(0.1, 0.1, 0.3, 0.3),
                            crop_ref="planning/scene_crops/x.png", check="ok")
    other = SceneElement(element_id="el_o", room_id=d["room_id"], semantic_type="floor_lamp",
                         material="brass", bbox=(0.1, 0.1, 0.3, 0.3),
                         crop_ref="planning/scene_crops/y.png", check="ok")

    assert element_image_for(ctx, matching) == rel
    assert element_image_for(ctx, other) is None, "no match: the crop is used, as before"

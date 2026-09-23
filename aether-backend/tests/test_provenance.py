"""P1-IDENTITY-005 - the provenance chain is QUERYABLE, for every object.

The acceptance criterion in task.md is stated over every object in a golden
scene: render -> blender_object -> scene_object -> instance -> element ->
SceneElement.crop_ref -> DesignIntent -> input_id -> ref_NN. This file builds
that golden scene on disk - the reading, the plan, the committed spec, the
Blender manifest, the moodboard and the classified intents - through the same
files the pipeline writes, and then asks the endpoint about every object.

Hand-authored rather than produced by the pipeline because the MockProvider
has no `read_scene_elements`: the mock path yields an empty reading, so every
object would be a catalog piece and the chain would be trivially complete
without a single identity hop being exercised. The identity layer itself is
NOT hand-typed: `resolve_elements()` derives the definitions and instances,
so the ids the chain resolves through are the ones production would mint.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin

from app.intelligence.schema import SceneElement, SceneReading
from app.intelligence.scene_reading import resolve_elements
from app.projects.layout import project_dir

FIXTURE = Path(__file__).parent / "fixtures" / "golden_project"
ROOM = "living_room"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _write(root: Path, rel: str, data: dict) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _element(eid: str, semantic_type: str, name: str, *, color: str, material: str,
             dims=(0.4, 0.75, 0.4), approved=True, check="ok") -> SceneElement:
    return SceneElement(
        element_id=eid, room_id=ROOM, name=name, semantic_type=semantic_type,
        material=material, color=color, dimensions_m=dims, crop_px=(300, 400),
        crop_ref=f"planning/scene_crops/{ROOM}/{eid}.png", approved=approved, check=check,
        bbox=(0.1, 0.1, 0.3, 0.5))


def golden(client) -> tuple[str, dict]:
    """A living room with: 1 sofa (matched to a photographed reference), 3
    identical stools (one definition, three instances), 2 side tables that
    differ in colour (two definitions - no false merge), and 1 catalog lamp the
    planner added with no element behind it. Returns (project_id, notes)."""
    pid = client.post("/api/projects", json={"name": "Golden provenance"}).json()["project"]["project_id"]
    files = [("references", (p.name, p.read_bytes(), "image/png"))
             for p in sorted((FIXTURE / "references").iterdir())]
    r = client.post(f"/api/projects/{pid}/inputs",
                    data={"description": "living room around the blue sofa"}, files=files)
    assert r.status_code == 200, r.text
    inputs = [i for i in client.get(f"/api/projects/{pid}/inputs").json()["data"] if i["kind"] == "reference"]
    assert len(inputs) == 3
    sofa_input = next(i for i in inputs if i["filename"] == "living.png")

    root = project_dir(pid)
    reading = SceneReading(elements=[
        _element("el_sofa", "sofa", "blue three-seater sofa", color="#2a4d8f", material="fabric",
                 dims=(2.1, 0.8, 0.9)),
        _element("el_stool_a", "stool", "black bar stool", color="#111111", material="metal"),
        _element("el_stool_b", "stool", "black bar stool", color="#111111", material="metal"),
        _element("el_stool_c", "stool", "black bar stool", color="#111111", material="metal"),
        _element("el_side_oak", "side_table", "oak side table", color="#b08a5a", material="oak",
                 dims=(0.5, 0.5, 0.5)),
        _element("el_side_blk", "side_table", "black side table", color="#111111", material="metal",
                 dims=(0.5, 0.5, 0.5)),
    ])
    reading.definitions, reading.instances = resolve_elements(reading)
    assert len(reading.definitions) == 4, "sofa, stool, 2 side tables"
    assert len(reading.instances) == 6
    _write(root, "planning/scene_reading.json", reading.model_dump(mode="json"))

    intent = {"intent_id": "di_sofa", "reference_class": "exact_object", "object_category": "sofa",
              "room_hint": "living room", "confidence": 0.95,
              "provenance": {"input_id": sofa_input["input_id"], "filename": "living.png",
                             "image_ref": "input/references/ref_03.png",
                             "stage": "reference_classification", "model": "test"}}
    _write(root, "planning/design_intent.json", {"intents": [intent]})

    # The plan: one item per element, the sofa naming its intent. The lamp is
    # the planner's own - no element_id, no intent.
    items = [{"object_key": f"{ROOM}.{e.semantic_type}.{n}", "semantic_type": e.semantic_type,
              "room_id": ROOM, "element_id": e.element_id, "count": 1,
              "source_intent_ids": ["di_sofa"] if e.element_id == "el_sofa" else []}
             for n, e in enumerate(reading.elements)]
    items.append({"object_key": f"{ROOM}.floor_lamp.0", "semantic_type": "floor_lamp",
                  "room_id": ROOM, "element_id": "", "count": 1, "source_intent_ids": []})
    _write(root, "planning/object_plan.json", {"items": items})

    # The committed scene, in the shape the compiler writes since P1-IDENTITY-002
    # - except ONE object left in the pre-V4 shape (element_id null) to prove
    # the plan_key fallback, since every real scene_spec.json on disk is that.
    inst_for = {i.source_element_id: i for i in reading.instances}
    objects = []
    for n, e in enumerate(reading.elements):
        inst = inst_for[e.element_id]
        pre_v4 = e.element_id == "el_stool_c"
        objects.append({"object_id": f"obj_{e.element_id}", "semantic_type": e.semantic_type,
                        "room_id": ROOM, "position": [1.0, 0.0, 1.0], "dimensions": list(e.dimensions_m),
                        "plan_key": f"{ROOM}.{e.semantic_type}.{n}#0",
                        # As the compiler writes them: the READING row id, and
                        # the derived `<element_id>#<n>` (P1-IDENTITY-002).
                        "element_id": None if pre_v4 else e.element_id,
                        "instance_id": None if pre_v4 else f"{e.element_id}#0",
                        "asset_id": f"asset_{inst.element_id}"})
    objects.append({"object_id": "obj_lamp", "semantic_type": "floor_lamp", "room_id": ROOM,
                    "position": [0.5, 0.0, 0.5], "dimensions": [0.3, 1.6, 0.3],
                    "plan_key": f"{ROOM}.floor_lamp.0#0", "element_id": None, "instance_id": None})
    _write(root, "planning/scene_spec.json", {"scene_id": "scene_g", "objects": objects})

    _write(root, "blender/build_manifest.json", {
        "manifest_version": "1.2",
        "objects": [{"id": o["object_id"], "name": o["semantic_type"],
                     "element_id": o["element_id"], "instance_id": o["instance_id"]} for o in objects]})
    _write(root, "analysis/moodboard_spec.json", {"room_scenes": [{
        "room_id": ROOM, "url": f"/files/projects/{pid}/analysis/moodboard_room_{ROOM}.png",
        "reference_resolved": True, "reference_note": "blue sofa in living.png"}]})
    return pid, {"objects": [o["object_id"] for o in objects], "sofa_input": sofa_input["input_id"],
                 "stool_def": inst_for["el_stool_a"].element_id}


# -- THE acceptance criterion: every object resolves ------------------------

def test_every_object_in_the_golden_scene_resolves_end_to_end(client):
    pid, g = golden(client)
    for oid in g["objects"]:
        r = client.get(f"/api/projects/{pid}/provenance/{oid}")
        assert r.status_code == 200, (oid, r.text)
        chain = r.json()["data"]
        assert chain["complete"], (oid, chain["gaps"], [h for h in chain["hops"] if not h["resolved"]])
        assert chain["gaps"] == []
        assert chain["hops"][0]["hop"] == "blender_object" and chain["hops"][0]["resolved"]

    cov = client.get(f"/api/projects/{pid}/provenance").json()["data"]
    assert cov["objects"] == 7
    assert cov["complete"] == 7
    assert cov["gaps"] == {}
    assert cov["origins"] == {"moodboard_element": 6, "planner_catalog": 1}
    assert cov["traced_to_element"] == 6
    assert cov["reached_source_image_exact"] == 1          # the sofa, via its intent
    assert cov["reached_source_image_via_moodboard"] == 5  # the rest, via the approved render


def test_the_sofa_names_the_photograph_that_caused_it(client):
    """The chain the task states, hop by hop, down to the uploaded file."""
    pid, g = golden(client)
    chain = client.get(f"/api/projects/{pid}/provenance/obj_el_sofa").json()["data"]
    hops = {h["hop"]: h for h in chain["hops"]}
    assert [h["hop"] for h in chain["hops"]] == [
        "blender_object", "scene_object", "instance", "element", "scene_element", "moodboard", "design_intent"]
    assert all(h["resolved"] for h in chain["hops"])
    assert hops["scene_object"]["note"] == "identity read from scene_object.element_id"
    assert hops["instance"]["id"].endswith(".1")
    assert hops["element"]["detail"]["instance_count"] == 1
    assert hops["scene_element"]["detail"]["crop_url"] == f"/files/projects/{pid}/planning/scene_crops/{ROOM}/el_sofa.png"
    assert hops["design_intent"]["id"] == "di_sofa"
    assert chain["terminus"] == "source_image"
    assert len(chain["source_images"]) == 1
    img = chain["source_images"][0]
    assert img["input_id"] == g["sofa_input"]
    assert img["via"] == "design_intent"
    assert img["in_inputs_table"] is True
    assert img["filename"] == "living.png"
    assert img["path"].endswith(".png") and "ref_" in img["path"]
    assert client.get(img["url"]).status_code == 200, "the photograph is served"


def test_three_identical_stools_share_one_element_and_keep_three_instances(client):
    pid, g = golden(client)
    chains = [client.get(f"/api/projects/{pid}/provenance/obj_el_stool_{s}").json()["data"] for s in "abc"]
    elements = {next(h for h in c["hops"] if h["hop"] == "element")["id"] for c in chains}
    instances = [next(h for h in c["hops"] if h["hop"] == "instance")["id"] for c in chains]
    assert elements == {g["stool_def"]}, "one definition"
    assert len(set(instances)) == 3, "three distinct instances"
    assert all(next(h for h in c["hops"] if h["hop"] == "element")["detail"]["instance_count"] == 3 for c in chains)
    # No photo shows THIS stool; the chain says so instead of guessing one.
    for c in chains:
        assert c["source_images"], "the render's references are still offered, labelled as weaker"
        assert all(i["via"] == "moodboard_reference" for i in c["source_images"])


def test_a_pre_v4_scene_object_resolves_through_the_plan_key_and_says_so(client):
    """Every real scene_spec.json on disk carries element_id: null."""
    pid, _ = golden(client)
    chain = client.get(f"/api/projects/{pid}/provenance/obj_el_stool_c").json()["data"]
    so = next(h for h in chain["hops"] if h["hop"] == "scene_object")
    assert so["note"].startswith("identity read from plan_key join")
    assert chain["complete"]


def test_a_catalog_piece_is_complete_at_scene_object_not_a_broken_chain(client):
    pid, _ = golden(client)
    chain = client.get(f"/api/projects/{pid}/provenance/obj_lamp").json()["data"]
    assert chain["origin"] == "planner_catalog"
    assert chain["complete"] and chain["gaps"] == []
    assert chain["terminus"] == "scene_object"
    assert [h["hop"] for h in chain["hops"]] == ["blender_object", "scene_object"]


def test_unknown_object_is_404_and_anonymous_is_401(client):
    pid, _ = golden(client)
    r = client.get(f"/api/projects/{pid}/provenance/obj_nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "OBJECT_NOT_FOUND"
    anon = TestClient(client.app)
    assert anon.get(f"/api/projects/{pid}/provenance/obj_el_sofa").status_code == 401
    assert anon.get(f"/api/projects/{pid}/provenance").status_code == 401


# -- Teeth: a real break is a gap, and the index follows the file ---------

def test_a_missing_definition_is_a_gap_and_the_index_rebuilds_from_the_file(client):
    from app.provenance import index_is_stale

    pid, _ = golden(client)
    assert client.get(f"/api/projects/{pid}/provenance").json()["data"]["complete"] == 7
    assert not index_is_stale(pid)

    # Drop the sofa's reading rows entirely: the scene still places it, so the
    # instance and scene_element hops now have their inputs present and fail.
    path = project_dir(pid) / "planning" / "scene_reading.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["elements"] = [e for e in data["elements"] if e["element_id"] != "el_sofa"]
    data["definitions"] = [d for d in data["definitions"] if "el_sofa" not in d["source_element_ids"]]
    data["instances"] = [i for i in data["instances"] if i["source_element_id"] != "el_sofa"]
    time.sleep(0.02)                    # strictly newer than the index, whatever the clock resolution
    path.write_text(json.dumps(data), encoding="utf-8")
    assert index_is_stale(pid)

    chain = client.get(f"/api/projects/{pid}/provenance/obj_el_sofa").json()["data"]
    assert chain["complete"] is False
    assert "instance" in chain["gaps"] and "scene_element" in chain["gaps"]
    inst = next(h for h in chain["hops"] if h["hop"] == "instance")
    assert inst["gap"] and not inst["resolved"] and inst["note"]
    cov = client.get(f"/api/projects/{pid}/provenance").json()["data"]
    assert cov["complete"] == 6 and cov["gaps"] == {"instance": 1, "scene_element": 1}
    assert not index_is_stale(pid), "the read re-indexed"


def test_a_rejected_element_is_not_evidence_and_review_re_resolves_it(client):
    """The review fix from P1-IDENTITY-005: approving a crop the check had
    rejected must re-resolve identity, or the piece stays outside the canonical
    set forever - and two approved identical chairs become two generations."""
    pid, _ = golden(client)
    path = project_dir(pid) / "planning" / "scene_reading.json"
    reading = SceneReading.model_validate(json.loads(path.read_text(encoding="utf-8")))
    reading.elements.append(_element("el_rug", "rug", "linen rug", color="#d9cdb8", material="linen",
                                     dims=(2.0, 0.01, 1.5), approved=None, check="crowded"))
    reading.definitions, reading.instances = resolve_elements(reading)
    assert not any("el_rug" in d.source_element_ids for d in reading.definitions)
    path.write_text(json.dumps(reading.model_dump(mode="json")), encoding="utf-8")

    r = client.patch(f"/api/projects/{pid}/scene-reading", json={"decisions": {"el_rug": True}})
    assert r.status_code == 200, r.text
    after = SceneReading.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert any("el_rug" in d.source_element_ids for d in after.definitions), "re-resolved on approval"
    assert len(after.definitions) == 5


def test_deleting_the_project_clears_its_index_rows(client):
    from app.db.sqlite import get_db

    pid, _ = golden(client)
    client.get(f"/api/projects/{pid}/provenance")
    assert get_db().one("SELECT COUNT(*) AS n FROM element_instances WHERE project_id = ?", (pid,))["n"] == 6
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert get_db().one("SELECT COUNT(*) AS n FROM element_instances WHERE project_id = ?", (pid,))["n"] == 0
    assert get_db().one("SELECT COUNT(*) AS n FROM elements WHERE project_id = ?", (pid,))["n"] == 0

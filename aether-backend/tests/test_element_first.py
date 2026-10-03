"""Phase 9 — Element-First (P1-ELEM-001 · 002 · 003 · 004)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from tests.test_asset_rebind import Reader, _fake_vendor, _project_with_render, client  # noqa: F401

from app.intelligence.schema import MoodboardOccurrence, SceneElement, SceneReading, SpatialRelation, moodboard_occurrences
from app.jobs import JobContext, get_job_store
from app.projects import get_project_store
from app.projects.layout import CHECKPOINTS
from app.spatial.coordinate_frames import FRAME_REGISTRY, FrameId, relation_frame
from app.spatial.transforms import FrameMismatchError, Rigid3

APP = Path(__file__).resolve().parents[1] / "app"


# ── P1-ELEM-001: MoodboardOccurrence ───────────────────────────────────────


def _el(**kw):
    base = dict(element_id="el_1", room_id="living_room", name="oak tv unit", semantic_type="tv_unit",
                bbox=(0.10, 0.40, 0.45, 0.70), crop_ref="planning/element_crops/living_room/00_oak.png",
                crop_px=(280, 180), wall="back")
    return SceneElement(**{**base, **kw})


def test_an_occurrence_is_pinned_to_the_moodboard_frame():
    o = MoodboardOccurrence.from_element(_el())
    assert o.frame == "MOODBOARD" and o.derived_from == "SceneElement"
    with pytest.raises(ValidationError):
        MoodboardOccurrence(frame="ROOM", element_id="e", room_id="r", bbox=(0.1, 0.1, 0.2, 0.2))
    with pytest.raises(ValidationError):
        o.model_copy(update={"frame": "ROOM"}).model_validate(o.model_dump() | {"frame": "ROOM"})


@pytest.mark.parametrize("bad", [
    {"bbox": (0.5, 0.2, 2.4, 1.1)},                       # metres, not fractions
    {"bbox": (1.2, 0.0, 3.6, 0.9)},
    {"bbox": (0.6, 0.2, 0.4, 0.5)},                       # inverted
    {"position_m": (1.2, 0.0, 0.8)},                      # a metric field does not exist on it
    {"dimensions_m": (2.0, 0.9, 0.8)},
    {"crop_px": (12.5, 30)},
])
def test_constructing_one_from_a_metric_value_fails(bad):
    base = dict(element_id="e", room_id="r", bbox=(0.1, 0.1, 0.2, 0.2))
    with pytest.raises(ValidationError):
        MoodboardOccurrence(**{**base, **bad})


def test_it_is_derived_not_authored_and_frozen():
    reading = SceneReading(elements=[_el(), _el(element_id="el_2", bbox=None), _el(element_id="el_3")])
    occ = moodboard_occurrences(reading)
    assert [o.element_id for o in occ] == ["el_1", "el_3"], "an element nobody located has no occurrence"
    assert occ[0].bbox == reading.elements[0].bbox and occ[0].crop_px == reading.elements[0].crop_px
    with pytest.raises(ValidationError):
        occ[0].bbox = (0.0, 0.0, 1.0, 1.0)                 # frozen: a view cannot be edited


def test_crop_px_is_the_native_size_before_upscaling(tmp_path):
    from app.intelligence.scene_reading import PAD, write_element_crops

    render = tmp_path / "room.png"
    Image.new("RGB", (800, 600), (200, 190, 170)).save(render)
    el = _el(bbox=(0.10, 0.20, 0.25, 0.50), crop_ref="", crop_px=(0, 0))
    reading = SceneReading(elements=[el])
    write_element_crops(reading, {"living_room": render}, tmp_path)
    x0, y0, x1, y1 = el.bbox
    px, py = (x1 - x0) * PAD, (y1 - y0) * PAD
    native = (int(min(1.0, x1 + px) * 800) - int(max(0.0, x0 - px) * 800),
              int(min(1.0, y1 + py) * 600) - int(max(0.0, y0 - py) * 600))
    assert reading.elements[0].crop_px == native
    with Image.open(tmp_path / reading.elements[0].crop_ref) as saved:
        assert saved.size != native, "the saved crop is enlarged; crop_px records what was really seen"
    assert MoodboardOccurrence.from_element(reading.elements[0]).crop_px == native


def test_the_artifact_is_registered_and_written_beside_its_source(client):  # noqa: F811
    from app.jobs.handlers import scene_plan

    assert CHECKPOINTS["moodboard_occurrences"] == "planning/moodboard_occurrences.json"
    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    try:
        scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    finally:
        ctx.close()
    doc = ctx.read_json("planning/moodboard_occurrences.json")
    reading = SceneReading.model_validate(ctx.read_json("planning/scene_reading.json"))
    assert doc["frame"] == "MOODBOARD" and doc["derived_from"] == "planning/scene_reading.json"
    assert doc["reading_version"] == reading.version
    assert [o["element_id"] for o in doc["occurrences"]] == [o.element_id for o in moodboard_occurrences(reading)]
    assert all(o["frame"] == "MOODBOARD" for o in doc["occurrences"])
    out = Path(__file__).resolve().parents[2] / "version 4" / "evidence" / "P1-ELEM"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample_moodboard_occurrences.json").write_text(json.dumps(doc, indent=2), "utf-8")


# ── P1-ELEM-002: the MOODBOARD frame ───────────────────────────────────────


def test_moodboard_is_the_eighth_frame_non_metric_and_parentless():
    spec = FRAME_REGISTRY[FrameId.MOODBOARD]
    assert spec.metric is False and spec.parent is None and spec.units == "fraction"
    assert len(FrameId) == 8 and set(FRAME_REGISTRY) == set(FrameId)
    import app.spatial.coordinate_frames as cf

    doc = cf.__doc__ or ""
    assert "EIGHT FRAMES" in doc and all(f.value in doc for f in FrameId), "the docstring lists all eight"


def test_no_rigid_transform_connects_moodboard_to_anything():
    for other in (FrameId.ROOM, FrameId.CAMERA, FrameId.OBJECT):
        for src, dst in ((FrameId.MOODBOARD, other), (other, FrameId.MOODBOARD)):
            with pytest.raises(FrameMismatchError):
                Rigid3(source=src, target=dst, rotation=((1.0, 0, 0), (0, 1.0, 0), (0, 0, 1.0)),
                       translation=(0.0, 0.0, 0.0), provenance="attempted")
    from app.spatial import frame_graph

    assert "MOODBOARD" not in frame_graph.describe_graph()
    src = (APP / "spatial" / "frame_graph.py").read_text("utf-8")
    assert "FrameId.MOODBOARD" not in src, "the frame graph holds no edge for the moodboard"


def test_existing_metric_edges_are_unaffected():
    from app.spatial.frame_graph import camera_to_blender, opencv_to_room, room_to_blender

    assert opencv_to_room().target == FrameId.ROOM and room_to_blender() and camera_to_blender()


# ── P1-ELEM-003: "floor_plan" means one thing ──────────────────────────────


def test_the_two_concepts_no_longer_share_a_string():
    from typing import get_args

    from app.projects.schema import InputKind
    from app.spatial.relation_model import Frame

    assert set(get_args(Frame)) == {"room_plan", "camera"}
    assert set(get_args(Frame)) & {k.value for k in InputKind} == set()
    rel_frames = set(get_args(SpatialRelation.model_fields["frame"].annotation))
    assert rel_frames & {k.value for k in InputKind} == set()


def test_no_code_uses_floor_plan_as_a_frame():
    """The only remaining "floor_plan" literals are the document kind and the
    legacy-load shim. Nothing compares a frame with the document kind."""
    allowed = {"projects/schema.py", "spatial/coordinate_frames.py"}
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"""["']floor_plan["']""", code) and rel not in allowed and '"""' not in line:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == []


def test_relations_serialized_before_the_rename_still_load():
    from app.spatial.relation_model import GeometricRelation
    from app.spatial.scene_serialization import _relation_from_dict as relation_from_dict

    assert relation_frame("floor_plan") == "room_plan" and relation_frame("camera") == "camera"
    old = {"subject_id": "sofa_1", "predicate": "AGAINST_WALL", "object_id": "", "confidence": "HIGH",
           "source": "geometry", "frame": "floor_plan", "note": ""}
    assert SpatialRelation.model_validate(old).frame == "room_plan"
    assert GeometricRelation.from_bridge_dict(old).frame == "room_plan"
    stored = GeometricRelation.from_bridge_dict(old)
    d = {"relation_id": stored.relation_id, "subject_id": "sofa_1", "predicate": "AGAINST_WALL", "object_id": "",
         "kind": stored.kind.value, "status": stored.status.value, "confidence": "HIGH", "source": "geometry",
         "frame": "floor_plan", "note": "", "provenance": "p", "verified_at_position": None, "evidence_refs": []}
    assert relation_from_dict(d).frame == "room_plan"
    with pytest.raises(ValidationError):
        SpatialRelation.model_validate({**old, "frame": "moodboard"})


# ── P1-ELEM-004: keep this furniture ───────────────────────────────────────


class CheckingReader(Reader):
    def check_element_crop(self, crop, room_type, vertical) -> dict:
        for slug, sem in (("sofa", "sofa"), ("bar_stool", "bar_stool"), ("side_table", "side_table")):
            if slug in crop.name:
                return {"sees": sem.replace("_", " "), "semantic_type": sem, "certain": True, "fills_frame": True}
        return {}


def _plan_with(ctx, monkeypatch, *, force: bool, shift: float = 0.0):
    from app.jobs.handlers import scene_plan

    reader = CheckingReader()
    reader.shift = shift                       # a re-read moves every box, so every row id changes
    monkeypatch.setattr(scene_plan, "get_provider", lambda: reader)
    ctx.params["force"] = force
    ctx.params["force_read"] = force
    try:
        return scene_plan.scene_plan(ctx)
    finally:
        ctx.close()


def _fresh_ctx(pid, type_="scene_plan"):
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type=type_, lane="ai")
    return JobContext(job, projects.get(pid), jobs, projects)


def test_a_kept_piece_is_in_the_scene_costs_nothing_is_labelled_yours_and_traces_to_its_image(client, monkeypatch):  # noqa: F811
    from app.jobs.handlers import generate_elements as gen

    pid, ctx = _project_with_render(client)
    _plan_with(ctx, monkeypatch, force=False)
    reading = client.get(f"/api/projects/{pid}/scene-reading").json()["data"]["reading"]
    sofa = next(e for e in reading["elements"] if e["semantic_type"] == "sofa")
    others = [e["element_id"] for e in reading["elements"] if e["element_id"] != sofa["element_id"]]

    # the structured control - not phrasing in a brief
    r = client.patch(f"/api/projects/{pid}/scene-reading",
                     json={"decisions": {i: True for i in others}, "keep": {sofa["element_id"]: True}})
    assert r.status_code == 200, r.text
    kept = next(e for e in r.json()["data"]["reading"]["elements"] if e["element_id"] == sofa["element_id"])
    assert kept["client_owned"] is True and kept["approved"] is True, "keeping implies it is in the room"

    # zero generations for the kept piece
    calls = _fake_vendor(monkeypatch)
    gctx = _fresh_ctx(pid, "generate_elements")
    try:
        result = gen.generate_elements(gctx)
    finally:
        gctx.close()
    assert calls["submit"] == 2, "the two approved pieces were generated; the kept sofa was not"
    submitted = [e for e in get_job_store().list_events(pid, limit=2000) if e.event_type == "asset.requested"]
    assert all(sofa["element_id"] not in e.entity_ids for e in submitted)
    assert all("sofa" not in k for k in result["made"])

    # re-plan from a fresh read: the flag follows the piece, the piece is placed, labelled yours
    _plan_with(_fresh_ctx(pid), monkeypatch, force=True, shift=0.02)
    from app.projects.layout import project_dir

    after = SceneReading.model_validate(json.loads(
        (project_dir(pid) / "planning" / "scene_reading.json").read_text("utf-8")))
    re_sofa = next(e for e in after.elements if e.semantic_type == "sofa")
    assert re_sofa.client_owned and re_sofa.element_id != sofa["element_id"], "carried to the re-read row"
    assert any(d.client_owned for d in after.definitions if d.semantic_type == "sofa")

    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]["scene"]
    placed = [o for o in spec["objects"] if o.get("client_owned")]
    assert placed and all(o["semantic_type"] == "sofa" for o in placed), "the kept piece is in the final scene"

    from app.provenance import ensure_indexed, resolve

    ensure_indexed(pid)
    chain = resolve(pid, placed[0]["object_id"])
    assert chain.terminus in ("moodboard", "source_image"), chain
    assert any(h.detail.get("crop_ref") for h in chain.hops if getattr(h, "detail", None)), \
        "provenance reaches the image that shows the client's piece"

    from app.blender.manifest import build_manifest
    from app.scene.store import get_store

    manifest = build_manifest(get_store().load(spec["scene_id"]), project_id=pid, project_root=project_dir(pid))
    assert any(o["client_owned"] for o in manifest["objects"]), "the viewer/renderer is told it is theirs"


def test_the_inventory_counts_yours():
    from app.intelligence.scene_reading import element_inventory

    reading = SceneReading(elements=[_el(check="ok", client_owned=True), _el(element_id="b", check="ok")])
    rows = element_inventory(reading)
    assert rows[0].usable == 2 and rows[0].yours == 1


def test_a_kept_piece_is_never_offered_for_generation_whatever_its_approval():
    from app.intelligence.scene_reading import approved_for_generation

    ready, held = approved_for_generation(SceneReading(elements=[_el(approved=True, client_owned=True)]))
    assert ready == [] and "kept, not generated" in held[0]

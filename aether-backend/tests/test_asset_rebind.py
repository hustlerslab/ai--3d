"""P1-ASSET-001 - a moodboard re-read never strands a mesh already paid for.

Reading ids are minted from `room|type|name|bbox`. A re-read moves every box,
so every id changes, and until this task the `asset_id` bound to the old row
vanished with it - the next generation run could buy the same stool again.
The binding now follows the PIECE (the position-free canonical key), not the
box, and `generate_elements` treats a group that already carries a resolvable
asset as paid for before it looks at any file.

Acceptance (task.md): re-reading a project with bound assets issues ZERO new
Meshy calls; every asset remains bound; a changed piece gets a new binding.
The vendor is faked at the adapter boundary and every submission is counted.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin

from app.assets.registry import get_registry
from app.assets.schema import AssetFiles, AssetRecord
from app.intelligence.mock_provider import MockProvider
from app.intelligence.schema import SceneElement, SceneReading
from app.intelligence.scene_reading import canonical_key, carry_asset_bindings, shape_key
from app.jobs import get_job_store
from app.jobs.context import JobContext
from app.jobs.handlers import generate_elements as gen
from app.jobs.handlers import scene_plan
from app.projects import get_project_store
from app.projects.layout import project_dir
from app.providers import meshy

FIXTURE = Path(__file__).parent / "fixtures" / "golden_project"
READING = "planning/scene_reading.json"


# -- the pure function -------------------------------------------------------

def _el(eid, sem, material, color, bbox=(0.1, 0.5, 0.25, 0.8), dims=None, asset_id="", room="living_room"):
    return SceneElement(element_id=eid, room_id=room, semantic_type=sem, name=sem, material=material,
                        color=color, dimensions_m=dims, bbox=bbox, crop_ref=f"planning/scene_crops/{eid}.png",
                        asset_id=asset_id)


def test_bindings_follow_the_piece_not_the_box_or_the_id():
    before = SceneReading(elements=[_el("old_1", "bar_stool", "metal", "#111111", asset_id="gen_stool"),
                                    _el("old_2", "sofa", "fabric", "#2A4D8F", asset_id="gen_sofa")])
    after = SceneReading(elements=[_el("new_9", "sofa", "fabric", "#2a4d8f", bbox=(0.6, 0.4, 0.9, 0.9)),
                                   _el("new_7", "bar_stool", "metal", "#111111", bbox=(0.3, 0.5, 0.45, 0.8))])
    counts = carry_asset_bindings(before, after)
    assert counts == {"carried": 2, "carried_loose": 0, "unbound": 0}
    assert {e.semantic_type: e.asset_id for e in after.elements} == {"sofa": "gen_sofa", "bar_stool": "gen_stool"}
    assert canonical_key(before.elements[0]) == canonical_key(after.elements[1]), "same piece, same key"
    assert shape_key(before.elements[0]) != shape_key(after.elements[1]), "the OLD key would have lost it"


def test_a_changed_piece_carries_nothing_and_is_reported():
    before = SceneReading(elements=[_el("old_1", "bar_stool", "metal", "#111111", asset_id="gen_stool")])
    after = SceneReading(elements=[_el("new_1", "bar_stool", "metal", "#F2F2F2")])   # now a white stool
    counts = carry_asset_bindings(before, after)
    assert counts == {"carried": 0, "carried_loose": 0, "unbound": 1}
    assert after.elements[0].asset_id == ""


def test_no_evidence_never_inherits_a_mesh():
    """Two side tables with nothing known about either are not known to be the
    same piece - and a `|?` key is id-bound anyway."""
    before = SceneReading(elements=[_el("old_1", "side_table", "", "", asset_id="gen_table")])
    after = SceneReading(elements=[_el("new_1", "side_table", "", "")])
    assert carry_asset_bindings(before, after)["carried"] == 0
    assert after.elements[0].asset_id == ""


def test_a_remeasured_piece_across_a_dimension_bucket_is_still_found_when_unique():
    before = SceneReading(elements=[_el("old_1", "bar_stool", "metal", "#111111", dims=(0.44, 0.75, 0.44),
                                        asset_id="gen_stool")])
    after = SceneReading(elements=[_el("new_1", "bar_stool", "metal", "#111111", dims=(0.46, 0.75, 0.46))])
    assert canonical_key(before.elements[0]) != canonical_key(after.elements[0]), "bucket boundary splits"
    counts = carry_asset_bindings(before, after)
    assert counts == {"carried": 0, "carried_loose": 1, "unbound": 0}
    assert after.elements[0].asset_id == "gen_stool"


def test_the_loose_match_never_hands_one_mesh_to_two_pieces():
    """Two black metal stools of different sizes on the old side, one on the
    new side: ambiguous, so nothing is carried rather than guessing."""
    before = SceneReading(elements=[_el("a", "bar_stool", "metal", "#111111", dims=(0.4, 0.7, 0.4), asset_id="gen_a"),
                                    _el("b", "bar_stool", "metal", "#111111", dims=(0.6, 1.0, 0.6), asset_id="gen_b")])
    after = SceneReading(elements=[_el("c", "bar_stool", "metal", "#111111", dims=(0.5, 0.8, 0.5))])
    counts = carry_asset_bindings(before, after)
    assert counts["carried"] == 0 and counts["carried_loose"] == 0 and counts["unbound"] == 2


def test_an_asset_that_no_longer_resolves_is_not_carried():
    before = SceneReading(elements=[_el("old_1", "sofa", "fabric", "#2A4D8F", asset_id="gen_gone")])
    after = SceneReading(elements=[_el("new_1", "sofa", "fabric", "#2A4D8F")])
    counts = carry_asset_bindings(before, after, valid=lambda aid: aid != "gen_gone")
    assert counts == {"carried": 0, "carried_loose": 0, "unbound": 0}
    assert after.elements[0].asset_id == ""


# -- the integration: re-read, then generate, counting every vendor call -----

class Reader(MockProvider):
    """The mock, plus a reader whose boxes the test controls. The model's
    non-determinism is simulated by shifting every box between reads."""

    shift = 0.0
    stool_color = "#111111"

    def read_scene_elements(self, image, room, style, vertical) -> dict:
        def el(name, sem, x, material, color):
            return {"name": name, "semantic_type": sem, "material": material, "color": color,
                    "bbox": [x + self.shift, 0.45, x + self.shift + 0.15, 0.8]}
        return {"elements": [
            el("blue sofa", "sofa", 0.05, "fabric", "#2A4D8F"),
            el("black bar stool", "bar_stool", 0.35, "metal", self.stool_color),
            el("oak side table", "side_table", 0.62, "oak", "#B08A5A"),
        ], "surfaces": {}}


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _project_with_render(client) -> tuple[str, JobContext]:
    """A project analysed by the mock (rooms + style on disk) with one approved
    room render, so `_read_scene` has something to read."""
    from app.jobs import get_runner

    pid = client.post("/api/projects", json={"name": "Rebind"}).json()["project"]["project_id"]
    files = [("references", (p.name, p.read_bytes(), "image/png")) for p in sorted((FIXTURE / "references").iterdir())]
    assert client.post(f"/api/projects/{pid}/inputs",
                       data={"description": (FIXTURE / "brief.txt").read_text(encoding="utf-8")},
                       files=files).status_code == 200
    client.post(f"/api/projects/{pid}/analyze", json={"paint": False})
    assert get_runner().wait_idle(60)
    root = project_dir(pid)
    analysis = json.loads((root / "analysis" / "design_analysis.json").read_text(encoding="utf-8"))
    room = analysis["rooms"][0]["room_id"]
    render = root / "analysis" / f"moodboard_room_{room}.png"
    # A render big enough that a 15%-wide box is a legible crop (the golden
    # fixture PNGs are 96x72, which puts every crop under MIN_LEGIBLE_PX).
    Image.new("RGB", (800, 600), (204, 190, 170)).save(render)
    (root / "analysis" / "moodboard_spec.json").write_text(json.dumps({
        "title": "t", "style_name": "s",
        "room_scenes": [{"room_id": room, "url": f"/files/projects/{pid}/analysis/{render.name}"}],
    }), encoding="utf-8")
    jobs, projects = get_job_store(), get_project_store()
    job = jobs.create(project_id=pid, type="scene_plan", lane="ai")
    return pid, JobContext(job, projects.get(pid), jobs, projects)


def _buy_everything(ctx, reading: SceneReading) -> dict[str, str]:
    """Simulate a completed generation run from BEFORE canonical naming: each
    row bound to a registered asset whose file sits under the old
    position-keyed name - the case `storage_key` cannot find after a re-read."""
    from app.core.config import get_settings

    bought = {}
    for el in reading.elements:
        asset_id = f"gen_{el.semantic_type}"
        # A real purchase has its normalized bytes in Allure storage; a record
        # without them is not a receipt (P1-ASSET-004).
        norm = get_registry().normalized_path(asset_id)
        norm.parent.mkdir(parents=True, exist_ok=True)
        norm.write_bytes(b"glTF-normalized")
        rel = str(norm.resolve().relative_to(get_settings().data_dir)).replace("\\", "/")
        get_registry().upsert(AssetRecord(asset_id=asset_id, name=el.name, semantic_type=el.semantic_type,
                                          files=AssetFiles(original="", normalized=rel)))
        legacy = ctx.path(gen._glb_rel(shape_key(el)))
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"glTF")
        el.asset_id = asset_id
        el.approved = True
        bought[el.semantic_type] = asset_id
    ctx.write_json(READING, reading)
    return bought


def _fake_vendor(monkeypatch):
    """Meshy at the adapter boundary. Every submission is counted; nothing
    reaches the network."""
    calls = {"submit": 0}
    monkeypatch.setenv("MESHY_API_KEY", "test-key")
    from app.core import config
    config.get_settings.cache_clear()

    async def submit(*a, **k):
        calls["submit"] += 1
        return f"task_{calls['submit']}"

    async def wait(*a, **k):
        return meshy.GeneratedModel("task", "https://assets.example/model.glb", "", 30, False)

    async def download(client, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"glTF")
        return dest

    async def balance(*a, **k):
        return 4100

    def ingest(path, meta):
        # What the real pipeline leaves behind: a normalized copy in Allure
        # storage. P1-ASSET-004 refuses to record completion without it.
        from app.core.config import get_settings

        norm = get_registry().normalized_path(meta.asset_id)
        norm.parent.mkdir(parents=True, exist_ok=True)
        norm.write_bytes(b"glTF-normalized")
        rel = str(norm.resolve().relative_to(get_settings().data_dir)).replace("\\", "/")
        rec = AssetRecord(asset_id=meta.asset_id, name=meta.name, semantic_type=meta.semantic_type,
                          source=meta.source, files=AssetFiles(original=str(path), normalized=rel))
        get_registry().upsert(rec)
        return rec

    monkeypatch.setattr(meshy, "submit_image_to_3d", submit)
    monkeypatch.setattr(meshy, "wait_for", wait)
    monkeypatch.setattr(meshy, "download_glb", download)
    monkeypatch.setattr(meshy, "balance", balance)
    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", ingest)
    return calls


def _approve_all(ctx) -> SceneReading:
    reading = SceneReading.model_validate(ctx.read_json(READING))
    for el in reading.elements:
        el.approved = True
    ctx.write_json(READING, reading)
    return reading


def test_a_re_read_keeps_every_binding_and_the_next_run_submits_nothing(client, monkeypatch):
    pid, ctx = _project_with_render(client)
    try:
        analysis, style = scene_plan._load_specs(ctx)
        first = scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
        assert len(first.elements) == 3 and not any(e.asset_id for e in first.elements)
        bought = _buy_everything(ctx, first)

        again = Reader()
        again.shift = 0.2                                    # every box moved: every id changes
        second = scene_plan._read_scene(ctx, analysis, style, again, force=True)
        assert {e.element_id for e in second.elements}.isdisjoint({e.element_id for e in first.elements})
        assert {e.semantic_type: e.asset_id for e in second.elements} == bought, "every asset remains bound"
        assert all(e.approved is None for e in second.elements), "approvals are not carried - the crop is new"
        on_disk = SceneReading.model_validate(ctx.read_json(READING))
        assert {e.asset_id for e in on_disk.elements} == set(bought.values()), "and it is what the file says"

        calls = _fake_vendor(monkeypatch)
        _approve_all(ctx)
        result = gen.generate_elements(ctx)
        assert calls["submit"] == 0, "zero new Meshy calls"
        assert result["made"] == {} and result["credits"] == 0
        assert result["reused"] == 3 and result["attached"] == 3
        final = SceneReading.model_validate(ctx.read_json(READING))
        assert {e.semantic_type: e.asset_id for e in final.elements} == bought
    finally:
        ctx.close()


def test_a_changed_piece_gets_a_new_binding_and_only_it_is_bought(client, monkeypatch):
    pid, ctx = _project_with_render(client)
    try:
        analysis, style = scene_plan._load_specs(ctx)
        first = scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
        bought = _buy_everything(ctx, first)

        changed = Reader()
        changed.shift, changed.stool_color = 0.1, "#F2F2F2"  # the stool is now white
        second = scene_plan._read_scene(ctx, analysis, style, changed, force=True)
        by_type = {e.semantic_type: e for e in second.elements}
        assert by_type["sofa"].asset_id == bought["sofa"] and by_type["side_table"].asset_id == bought["side_table"]
        assert by_type["bar_stool"].asset_id == "", "a different piece carries nothing"

        calls = _fake_vendor(monkeypatch)
        _approve_all(ctx)
        result = gen.generate_elements(ctx)
        assert calls["submit"] == 1, "exactly one submission: the changed stool"
        assert result["reused"] == 2 and len(result["made"]) == 1
        final = {e.semantic_type: e.asset_id for e in SceneReading.model_validate(ctx.read_json(READING)).elements}
        assert final["sofa"] == bought["sofa"] and final["side_table"] == bought["side_table"]
        assert final["bar_stool"] and final["bar_stool"] != bought["bar_stool"], "a new binding"
    finally:
        ctx.close()


def test_without_the_carry_the_legacy_mesh_would_have_been_bought_again(client, monkeypatch):
    """The regression this task exists for, shown rather than asserted by
    absence: strip the carried bindings and the same run pays for all three."""
    pid, ctx = _project_with_render(client)
    try:
        analysis, style = scene_plan._load_specs(ctx)
        first = scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
        _buy_everything(ctx, first)
        again = Reader()
        again.shift = 0.2
        scene_plan._read_scene(ctx, analysis, style, again, force=True)

        calls = _fake_vendor(monkeypatch)
        reading = _approve_all(ctx)
        for el in reading.elements:
            el.asset_id = ""                                 # what a re-read used to leave behind
        ctx.write_json(READING, reading)
        gen.generate_elements(ctx)
        assert calls["submit"] == 3, "the old behaviour: three meshes bought twice"
    finally:
        ctx.close()

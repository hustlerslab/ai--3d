"""P1-ASSET-004 - a paid mesh is ours before anything says "done".

Meshy keeps generated files for 3 days on non-Enterprise plans, behind
signed, time-limited URLs. The adapter already downloaded before completion;
the invariant was never stated or tested, and the vendor's signed thumbnail
URL was being stored on the asset record and served to the UI - a reference
that dies with the retention window.

Now `assets.pipeline.persisted()` must answer "" (the original AND the
normalized copy are in Allure storage, non-empty, and no vendor file URL is
on the record) before a generation is recorded as SUCCEEDED or checkpointed.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.test_asset_rebind import Reader, _approve_all, _fake_vendor, _project_with_render, client  # noqa: F401
from tests.test_assets_pipeline import write_box_gltf

from app.assets import pipeline as asset_pipeline
from app.assets.registry import get_registry
from app.assets.schema import AssetFiles, AssetRecord, AssetSource, IngestMeta
from app.core.config import get_settings
from app.intelligence.schema import SceneReading
from app.jobs.handlers import generate_elements as gen
from app.jobs.handlers import scene_plan
from app.providers import meshy
from app.spend.tasks import project_tasks

READING = "planning/scene_reading.json"
VENDOR = "assets.example"                     # the fake CDN host every vendor URL in these tests uses
THUMB = b"PNG-thumb-bytes"


# -- the invariant itself ---------------------------------------------------------

def _record(tmp_path, *, normalized=True, thumb="") -> tuple[AssetRecord, Path]:
    data = get_settings().data_dir
    source = tmp_path / "orig.glb"
    source.write_bytes(b"glTF")
    rel = ""
    if normalized:
        norm = data / "assets" / "normalized" / "a.glb"
        norm.parent.mkdir(parents=True, exist_ok=True)
        norm.write_bytes(b"glTF-normalized")
        rel = "assets/normalized/a.glb"
    rec = AssetRecord(asset_id="a", name="a", semantic_type="chair",
                      source=AssetSource(provider="meshy", thumbnail_url=thumb),
                      files=AssetFiles(original=str(source), normalized=rel))
    return rec, source


def test_persisted_is_empty_only_when_everything_is_ours(env, tmp_path):
    rec, source = _record(tmp_path, thumb="/files/projects/p/assets/elements/x.thumb.png")
    assert asset_pipeline.persisted(rec, source) == ""

    rec, source = _record(tmp_path, normalized=False)
    assert "no normalized copy" in asset_pipeline.persisted(rec, source)

    rec, source = _record(tmp_path)
    (get_settings().data_dir / "assets" / "normalized" / "a.glb").write_bytes(b"")
    assert "normalized copy missing or empty" in asset_pipeline.persisted(rec, source)

    rec, source = _record(tmp_path)
    source.unlink()
    assert "original missing" in asset_pipeline.persisted(rec, source)

    rec, source = _record(tmp_path, thumb="https://assets.meshy.ai/thumb.png?sig=abc")
    assert "points at the vendor" in asset_pipeline.persisted(rec, source)


# -- the fault: the vendor URL expires after the download ------------------------------

def _real_glb(tmp_path) -> bytes:
    """A genuine binary GLB: the synthetic box run through the real ingester once."""
    (tmp_path / "box").mkdir()
    src = write_box_gltf(tmp_path / "box")
    rec = asset_pipeline.ingest_file(src, IngestMeta(asset_id="seed_box", name="box", semantic_type="box",
                                                     expected_dimensions=(2.0, 0.8, 1.0)))
    assert rec.status == "normalized", rec.validation
    return (get_settings().data_dir / rec.files.normalized).read_bytes()


def _vendor_files(pid) -> list[str]:
    """Every place a vendor file URL could hide after completion."""
    root = get_settings().data_dir
    hits = []
    for path in [root / "assets" / "registry.json", *(root / "projects" / pid).rglob("*.json")]:
        if path.is_file() and VENDOR in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(root)))
    return hits


def test_expiring_the_vendor_url_after_download_breaks_nothing(client, monkeypatch, tmp_path):
    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    _approve_all(ctx)
    calls = _fake_vendor(monkeypatch)
    glb = _real_glb(tmp_path)

    # The real ingester this time, on a real GLB; the vendor serves a thumbnail too.
    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", asset_pipeline.ingest_file)

    async def download(client_, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(glb)
        return dest

    async def wait(client_, task_id, **kw):
        return meshy.GeneratedModel(task_id, f"https://{VENDOR}/{task_id}.glb?sig=live",
                                    f"https://{VENDOR}/{task_id}.png?sig=live", 30, True)

    def cdn(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=THUMB)

    monkeypatch.setattr(meshy, "download_glb", download)
    monkeypatch.setattr(meshy, "wait_for", wait)
    monkeypatch.setattr(meshy, "make_client", lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(cdn)))
    try:
        result = gen.generate_elements(ctx)
    finally:
        ctx.close()
    assert calls["submit"] == 3 and len(result["made"]) == 3, result["warnings"]
    rows = project_tasks(pid)
    assert {r["status"] for r in rows} == {"SUCCEEDED"}

    # A completed task's mesh is in Allure storage before completion was recorded.
    for r in rows:
        rec = get_registry().get(r["asset_id"])
        assert rec is not None and rec.status == "normalized"
        assert (get_settings().data_dir / rec.files.normalized).stat().st_size > 0
        assert ctx.path(gen._glb_rel(r["item_key"])).stat().st_size > 0
        assert asset_pipeline.persisted(rec, ctx.path(gen._glb_rel(r["item_key"]))) == ""
        assert rec.source.thumbnail_url.startswith(f"/files/projects/{pid}/assets/elements/"), rec.source.thumbnail_url
        assert ctx.path(gen._glb_rel(r["item_key"])[:-4] + ".thumb.png").read_bytes() == THUMB
        assert rec.source.url.startswith("https://api.meshy.ai/"), "the task id is provenance, not a file"
    assert _vendor_files(pid) == [], "no vendor file URL survives completion"

    # Now the vendor's window closes: every signed URL is dead.
    async def expired(client_, url, dest):
        raise meshy.MeshyError(f"could not download the finished mesh: HTTP 403 for {url}")

    monkeypatch.setattr(meshy, "download_glb", expired)
    monkeypatch.setattr(meshy, "download_thumbnail", expired)

    # ...and nothing downstream notices: the meshes resolve from Allure storage,
    # the next run buys nothing and downloads nothing, the thumbnails still serve.
    from app.jobs import get_job_store
    from app.jobs.context import JobContext
    from app.projects import get_project_store

    jobs, projects = get_job_store(), get_project_store()
    ctx2 = JobContext(jobs.create(project_id=pid, type="generate_elements", lane="ai"), projects.get(pid), jobs, projects)
    try:
        again = gen.generate_elements(ctx2)
    finally:
        ctx2.close()
    assert calls["submit"] == 3 and again["made"] == {} and again["reused"] == 3 and again["attached"] == 3
    reading = SceneReading.model_validate(ctx2.read_json(READING))
    for el in reading.elements:
        rec = get_registry().get(el.asset_id)
        assert (get_settings().data_dir / rec.files.normalized).is_file()
        assert client.get(rec.source.thumbnail_url).status_code == 200, "served from Allure, not the vendor"
    registry_json = json.loads((get_settings().data_dir / "assets" / "registry.json").read_text(encoding="utf-8"))
    assert VENDOR not in json.dumps(registry_json)


def test_a_mesh_that_did_not_persist_is_not_recorded_as_done(client, monkeypatch):
    """The ingester answers without a normalized copy: no SUCCEEDED, no asset,
    the receipt stays resumable so a retry downloads again in the window."""
    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    _approve_all(ctx)
    calls = _fake_vendor(monkeypatch)

    def hollow_ingest(path, meta):
        rec = AssetRecord(asset_id=meta.asset_id, name=meta.name, semantic_type=meta.semantic_type,
                          source=meta.source, files=AssetFiles(original=str(path)))
        get_registry().upsert(rec)
        return rec

    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", hollow_ingest)
    try:
        result = gen.generate_elements(ctx)
    finally:
        ctx.close()
    assert calls["submit"] == 3
    assert result["made"] == {} and result["credits"] == 0
    assert all("mesh not persisted" in w for w in result["warnings"]), result["warnings"]
    assert {r["status"] for r in project_tasks(pid)} == {"SUBMITTED"}, "still resumable"
    reading = SceneReading.model_validate(ctx.read_json(READING))
    assert not any(e.asset_id for e in reading.elements), "nothing bound to a file that is not there"


def _lose_normalized_bytes(pid) -> int:
    """Simulate a restore without assets: the registry rows stay, the files go."""
    gone = 0
    reading = json.loads((get_settings().data_dir / "projects" / pid / READING).read_text(encoding="utf-8"))
    for el in SceneReading.model_validate(reading).elements:
        rec = get_registry().get(el.asset_id)
        path = get_settings().data_dir / rec.files.normalized
        if path.is_file():
            path.unlink()
            gone += 1
    return gone


def _generated(client, monkeypatch, tmp_path):
    """Three pieces generated through the real ingester (as in the expiry test)."""
    pid, ctx = _project_with_render(client)
    analysis, style = scene_plan._load_specs(ctx)
    scene_plan._read_scene(ctx, analysis, style, Reader(), force=False)
    _approve_all(ctx)
    calls = _fake_vendor(monkeypatch)
    glb = _real_glb(tmp_path)
    monkeypatch.setattr(gen.asset_pipeline, "ingest_file", asset_pipeline.ingest_file)

    async def download(client_, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(glb)
        return dest

    monkeypatch.setattr(meshy, "download_glb", download)
    try:
        assert len(gen.generate_elements(ctx)["made"]) == 3
    finally:
        ctx.close()
    return pid, calls


def _run_again(pid):
    from app.jobs import get_job_store
    from app.jobs.context import JobContext
    from app.projects import get_project_store

    jobs, projects = get_job_store(), get_project_store()
    ctx = JobContext(jobs.create(project_id=pid, type="generate_elements", lane="ai"), projects.get(pid), jobs, projects)
    try:
        return gen.generate_elements(ctx), ctx.read_json(READING)
    finally:
        ctx.close()


def test_a_record_whose_bytes_are_gone_is_reingested_from_the_download_not_reused_blind(client, monkeypatch, tmp_path):
    pid, calls = _generated(client, monkeypatch, tmp_path)
    assert _lose_normalized_bytes(pid) == 3
    result, reading = _run_again(pid)
    assert calls["submit"] == 3, "the download is still on disk: nothing is bought"
    assert result["made"] == {} and result["reused"] == 3 and result["attached"] == 3
    for el in reading["elements"]:
        rec = get_registry().get(el["asset_id"])
        assert asset_pipeline.has_normalized(rec), "re-ingested from the download, bytes back in storage"


def test_a_mesh_lost_entirely_is_redownloaded_from_the_open_task_not_bought_again(client, monkeypatch, tmp_path):
    pid, calls = _generated(client, monkeypatch, tmp_path)
    assert _lose_normalized_bytes(pid) == 3
    for path in (get_settings().data_dir / "projects" / pid / "assets" / "elements").glob("*.glb"):
        path.unlink()                                          # the download too
    polled: list[str] = []

    async def still_there(client_, task_id, **kw):
        polled.append(task_id)
        return meshy.GeneratedModel(task_id, f"https://{VENDOR}/{task_id}.glb?sig=fresh", "", 30, True)

    monkeypatch.setattr(meshy, "wait_for", still_there)
    before = {r["task_id"] for r in project_tasks(pid)}
    result, reading = _run_again(pid)
    assert calls["submit"] == 3, "inside the retention window the task is polled, never re-submitted"
    assert set(polled) == before and len(result["made"]) == 3
    assert all(asset_pipeline.has_normalized(get_registry().get(el["asset_id"])) for el in reading["elements"])

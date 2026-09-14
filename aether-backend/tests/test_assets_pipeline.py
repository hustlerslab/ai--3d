"""Pipeline tests on a synthetic glTF — no downloads, no GPU.

Builds a 2000 x 800 x 1000 (mm-authored) box with an external .bin and a
1x1 PNG texture, ingests it, and checks the normalized GLB is self-contained,
measures 2.0 x 0.8 x 1.0 m, sits on y=0, and is centred on the origin.
"""
from __future__ import annotations

import base64
import json
import math
import struct
from pathlib import Path

import pytest

from app.assets import gltf, normalization, validation

# 1x1 white PNG
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def write_box_gltf(folder: Path, size=(2000.0, 800.0, 1000.0), offset=(500.0, 100.0, -300.0)) -> Path:
    sx, sy, sz = size
    ox, oy, oz = offset
    # 8 corners, offset away from origin so translation is exercised.
    corners = [
        (ox + x * sx, oy + y * sy, oz + z * sz)
        for x in (0, 1) for y in (0, 1) for z in (0, 1)
    ]
    positions = b"".join(struct.pack("<fff", *c) for c in corners)
    # 12 triangles (36 indices) — any valid closed box order works for measuring.
    faces = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
        (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
        (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]
    indices = b"".join(struct.pack("<HHH", *f) for f in faces)
    bin_blob = positions + indices
    (folder / "box.bin").write_bytes(bin_blob)
    (folder / "tex.png").write_bytes(PNG_1X1)

    mn = [min(c[i] for c in corners) for i in range(3)]
    mx = [max(c[i] for c in corners) for i in range(3)]
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "box"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0}],
        "images": [{"uri": "tex.png"}],
        "buffers": [{"uri": "box.bin", "byteLength": len(bin_blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": mn, "max": mx},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    path = folder / "box.gltf"
    path.write_text(json.dumps(doc), "utf-8")
    return path


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path / "data"))
    from app.core import config
    from app.assets import registry as reg

    config.get_settings.cache_clear()
    reg._registry = None
    yield tmp_path
    config.get_settings.cache_clear()
    reg._registry = None


def test_measure_and_unit_detection(tmp_path):
    path = write_box_gltf(tmp_path)
    doc = gltf.load(path)
    m = gltf.measure(doc)
    assert m.triangles == 12
    assert m.size == pytest.approx((2000.0, 800.0, 1000.0))
    unit, scale = normalization.detect_unit(m.size)
    assert unit == "millimeter" and scale == 0.001


def test_normalized_glb_is_grounded_centred_and_self_contained(tmp_path, data_dir):
    from app.assets import pipeline
    from app.assets.schema import IngestMeta

    src = write_box_gltf(tmp_path)
    record = pipeline.ingest_file(src, IngestMeta(asset_id="test_box", name="Box", semantic_type="sofa"))
    assert record.status == "normalized", record.validation
    assert record.dimensions == pytest.approx((2.0, 0.8, 1.0))
    assert record.normalization.detected_unit == "millimeter"

    out = data_dir / "data" / record.files.normalized
    assert out.exists() and out.read_bytes()[:4] == b"glTF"
    doc = gltf.load(out)
    assert doc.missing_files == []
    assert all("uri" not in img for img in doc.json["images"])  # texture embedded
    assert len(doc.json["buffers"]) == 1 and "uri" not in doc.json["buffers"][0]

    m = gltf.measure(doc)  # root transform applied during traversal
    assert m.size == pytest.approx((2.0, 0.8, 1.0), abs=1e-4)
    assert m.bbox_min[1] == pytest.approx(0.0, abs=1e-6)
    assert m.center[0] == pytest.approx(0.0, abs=1e-6)
    assert m.center[2] == pytest.approx(0.0, abs=1e-6)


def test_yaw_offset_swaps_footprint(tmp_path, data_dir):
    from app.assets import pipeline
    from app.assets.schema import IngestMeta

    src = write_box_gltf(tmp_path)
    record = pipeline.ingest_file(
        src, IngestMeta(asset_id="test_box_yaw", name="Box", semantic_type="sofa", yaw_offset=math.pi / 2)
    )
    assert record.dimensions == pytest.approx((1.0, 0.8, 2.0), abs=1e-4)
    doc = gltf.load(data_dir / "data" / record.files.normalized)
    m = gltf.measure(doc)
    assert m.size == pytest.approx((1.0, 0.8, 2.0), abs=1e-4)
    assert m.bbox_min[1] == pytest.approx(0.0, abs=1e-6)


def test_expected_dimensions_override(tmp_path):
    path = write_box_gltf(tmp_path, size=(2.0, 0.8, 1.0), offset=(0, 0, 0))
    doc = gltf.load(path)
    m = gltf.measure(doc)
    plan = normalization.plan(m, expected_dimensions=(4.0, 1.6, 2.0))
    assert plan.info.strategy == "expected_dimensions"
    assert plan.dimensions == pytest.approx((4.0, 1.6, 2.0))


def test_validation_flags_missing_texture(tmp_path):
    path = write_box_gltf(tmp_path)
    (tmp_path / "tex.png").unlink()
    doc = gltf.load(path)
    m = gltf.measure(doc)
    plan = normalization.plan(m)
    issues = validation.validate(doc, m, gltf.texture_summary(doc), plan.dimensions)
    assert any(i.code == "MISSING_FILES" and i.severity == "hard" for i in issues)


def test_catalog_prefers_real_model(tmp_path, data_dir):
    from app.assets import pipeline
    from app.assets.schema import IngestMeta
    from app.catalog.catalog import find_by_semantic, search

    src = write_box_gltf(tmp_path)
    pipeline.ingest_file(src, IngestMeta(asset_id="real_sofa", name="Real Sofa", semantic_type="sofa", style_tags=["luxury"]))
    best = find_by_semantic("sofa")
    assert best is not None and best.asset_id == "real_sofa" and best.model_url
    ranked = search("sofa")
    assert ranked[0].asset_id == "real_sofa"


def test_a_surface_mounted_asset_ingests(tmp_path, data_dir):
    """Regression: `Mount` was Literal["floor","ceiling","wall"] and never
    widened when spec 1.1 added "surface" (a lamp on a bedside table), so every
    surface-mounted asset raised a ValidationError on ingest — uploads and
    generated models alike. Surfaced by the first live Meshy run, 11 Sep 2026.
    """
    from app.assets import pipeline
    from app.assets.schema import IngestMeta

    folder = tmp_path / "vase"
    folder.mkdir()
    src = write_box_gltf(folder)
    record = pipeline.ingest_file(
        src, IngestMeta(asset_id="surface_vase", name="Vase", semantic_type="vase", mount="surface")
    )

    assert record.mount == "surface"
    assert record.status == "normalized"


def test_every_planner_mount_is_accepted_by_the_ingester(tmp_path, data_dir):
    """The planner's PLACEMENT_MOUNT is the only producer of asset mounts, so
    its full range must round-trip. This fails if either side drifts again."""
    from app.assets import pipeline
    from app.assets.schema import IngestMeta
    from app.planning.asset_decision import PLACEMENT_MOUNT

    for i, mount in enumerate(sorted(set(PLACEMENT_MOUNT.values()))):
        folder = tmp_path / f"m{i}"
        folder.mkdir()
        src = write_box_gltf(folder)
        record = pipeline.ingest_file(
            src, IngestMeta(asset_id=f"mount_{mount}", name=mount, semantic_type="vase", mount=mount)
        )
        assert record.mount == mount, f"{mount} did not survive ingestion"


# ── the two defects the multi-angle render exposed ───────────────────────


def _plan_item(**kw):
    from app.intelligence.schema import ObjectPlanItem

    base = dict(object_key="r.x.0", semantic_type="x", room_id="r", priority=1, count=1)
    return ObjectPlanItem(**{**base, **kw})


def _style():
    from app.intelligence.schema import StyleSpec

    return StyleSpec(name="warm_modern", tags=["modern", "warm"], materials=[])


def _with_models(monkeypatch, *items):
    """Put real catalog entries in front of the ladder. The `env` fixture gives
    a clean data dir, so the ingested ph_* models are absent and every lookup
    would otherwise fall to the parametric rung for the wrong reason."""
    from app.catalog.catalog import CatalogItem
    from app.planning import asset_decision

    catalog = [
        CatalogItem(asset_id="ph_classic_bed", semantic_type="bed", name="Carved Wooden Bed",
                    dimensions=(1.4938, 1.5338, 2.04), color="#4a3624", mount="floor",
                    shape="model", model_url="/files/assets/ph_classic_bed.glb"),
        CatalogItem(asset_id="ph_art_frame_01", semantic_type="wall_art", name="Minimal Framed Art",
                    dimensions=(0.594, 0.841, 0.0157), color="#f2ebdf", mount="wall",
                    shape="model", model_url="/files/assets/ph_art_frame_01.glb"),
    ]
    keep = [c for c in catalog if c.asset_id in items] if items else catalog
    monkeypatch.setattr(asset_decision, "all_items", lambda: keep)
    return keep


def test_a_mattress_photographed_upright_is_still_laid_out_as_a_bed(env, monkeypatch):
    """The reading measures the box it can see. In a showroom a mattress is
    often standing on its end, which passed through as a 2 m tall, 20 cm thick
    slab against the wall — and put the real bed model out of reach."""
    from app.planning.asset_decision import _target, decide_asset

    upright = _plan_item(semantic_type="bed", name="blue mattress upright",
                         approx_dimensions=(1.5, 1.9, 0.2), from_photo=True)
    flat = _plan_item(semantic_type="bed", name="mattress on the floor",
                      approx_dimensions=(1.8, 0.25, 2.0), from_photo=True)

    for item in (upright, flat):
        w, h, d = _target(item)[0]
        assert h < w and h < d, f"bed is still standing on end: {(w, h, d)}"
        assert 1.2 <= w <= 2.1 and 1.7 <= d <= 2.3, f"implausible bed footprint {(w, d)}"

    # and the real model becomes reachable again instead of a bare box
    _with_models(monkeypatch, "ph_classic_bed")
    for item in (upright, flat):
        decision = decide_asset(item, _style())
        assert decision.has_model, decision.reason
        assert decision.asset_id == "ph_classic_bed", decision.asset_id


def test_a_correctly_measured_object_survives_reposing_untouched(env):
    """The re-pose must be a no-op on good input, and must not rotate anything.
    Forcing the footprint to (shorter, longer) would turn every wide rug 90
    degrees; a bookcase and a floor lamp are genuinely taller than their
    footprint and must not be laid on their backs."""
    from app.planning.asset_decision import _in_room_dims, _target

    assert _in_room_dims("bed", (1.6, 0.55, 2.05), (1.6, 0.55, 2.05)) == (1.6, 0.55, 2.05)
    assert _in_room_dims("rug", (2.4, 0.03, 1.7), (2.4, 0.02, 1.7))[0] == 2.4   # width, not depth
    assert _in_room_dims("rug", (3.5, 2.5, 0.03), (2.4, 0.02, 1.7)) == (3.5, 0.02, 2.5)

    for sem, dims in (("bookshelf", (1.1, 2.1, 0.5)), ("floor_lamp", (0.3, 1.5, 0.3)),
                      ("sofa", (2.0, 0.9, 0.85))):
        item = _plan_item(semantic_type=sem, approx_dimensions=dims, from_photo=True)
        assert _target(item)[0] == dims, f"{sem} was re-posed and should not have been"


def test_a_thin_frame_is_not_rejected_for_being_thin(env, monkeypatch):
    """ph_art_frame_01 matched its target's width and height to three decimals
    and lost on 1.4 cm of thickness, because worst-axis scoring treats depth as
    a constraint. A picture hangs flat whatever its depth."""
    from app.planning.asset_decision import _fit, decide_asset

    model, target = (0.594, 0.841, 0.0157), (0.59, 0.84, 0.03)
    assert _fit(model, target) < 0.70, "the old worst-axis score is the thing being fixed"
    assert _fit(model, target, "wall_art") >= 0.85

    _with_models(monkeypatch, "ph_art_frame_01")
    decision = decide_asset(_plan_item(semantic_type="wall_art", name="Minimal Framed Art",
                                       placement="wall", family="art",
                                       approx_dimensions=(0.59, 0.84, 0.03)), _style())
    assert decision.asset_id == "ph_art_frame_01" and decision.has_model, decision.reason


def test_a_soft_axis_cannot_rescue_a_model_that_is_wrong_where_it_counts(env):
    """The soft axis trims the score; it must not become a licence to fit any
    box at all. A frame of the right thickness but half the width still fails."""
    from app.planning.asset_decision import _fit

    assert _fit((0.30, 0.841, 0.03), (0.59, 0.84, 0.03), "wall_art") < 0.70
    assert _fit((1.494, 1.534, 2.04), (1.5, 0.55, 0.9), "bed") < 0.70   # wrong footprint


# ── style-aware selection (bounded) ──────────────────────────────────────


def _catalog(*specs):
    from app.catalog.catalog import CatalogItem

    return [CatalogItem(asset_id=a, semantic_type=t, name=n, dimensions=d, color="#808080",
                        mount="floor", shape="model", model_url=f"/files/assets/{a}.glb",
                        style_tags=list(tags))
            for a, t, n, d, tags in specs]


BRIEF_TAGS = ["modern", "warm", "scandinavian", "warm_neutral", "natural"]


def test_style_breaks_the_near_tie_that_put_a_chesterfield_in_a_modern_room(env, monkeypatch):
    """Measured on the sample project: ph_sofa_03 (luxury/classic/victorian) beat
    ph_sofa_02 (modern/...) by 0.022 of dimensional fit, and style never entered
    the comparison because it sat in the sort key's tiebreak position."""
    from app.intelligence.schema import StyleSpec
    from app.planning import asset_decision
    from app.planning.asset_decision import decide_asset

    monkeypatch.setattr(asset_decision, "all_items", lambda: _catalog(
        ("ph_sofa_02", "sofa", "Leather & Fabric Sofa", (1.8072, 0.7095, 0.8178),
         ("modern", "luxury", "mid_century")),
        ("ph_sofa_03", "sofa", "Chesterfield Leather Sofa", (2.7312, 1.1183, 0.9271),
         ("luxury", "classic", "victorian")),
    ))
    style = StyleSpec(name="warm_modern_family", tags=BRIEF_TAGS, materials=[])
    item = _plan_item(semantic_type="sofa", name="grey pull-out sofa bed",
                      approx_dimensions=(2.1, 0.95, 0.9), from_photo=True)
    assert decide_asset(item, style).asset_id == "ph_sofa_02"


def test_the_style_weight_cannot_rescue_a_model_of_the_wrong_size(env, monkeypatch):
    """The bound is the point. Style is a multiplier in [0.85, 1.0], so it can
    never overturn a candidate that is more than ~18 % better on fit — this must
    hold by construction, not by luck in one project's numbers."""
    from app.intelligence.schema import StyleSpec
    from app.planning import asset_decision
    from app.planning.asset_decision import STYLE_WEIGHT, decide_asset

    monkeypatch.setattr(asset_decision, "all_items", lambda: _catalog(
        # exactly the right size, and not one tag in common with the brief
        ("ph_right_size", "ottoman", "Ottoman A", (0.8, 0.42, 0.8), ("victorian", "baroque")),
        # a flawless style match that is half the size
        ("ph_right_style", "ottoman", "Ottoman B", (0.4, 0.2, 0.4), tuple(BRIEF_TAGS)),
    ))
    style = StyleSpec(name="warm_modern_family", tags=BRIEF_TAGS, materials=[])
    item = _plan_item(semantic_type="ottoman", approx_dimensions=(0.8, 0.42, 0.8))
    assert decide_asset(item, style).asset_id == "ph_right_size"
    assert 0 < STYLE_WEIGHT <= 0.2, "a larger weight would stop being a tiebreak"


def test_style_moves_exactly_one_pick_and_leaves_the_others_alone():
    """The weight is sized to correct the wrong choice and nothing else.

    Runs against the REAL asset library — a stand-in catalog would only prove
    the arithmetic on numbers I chose. The plan items are inlined rather than
    read from the sample project, because that project's plan is regenerated
    whenever the pipeline re-runs and the assertion would rot.
    """
    from app.catalog.catalog import all_items
    from app.intelligence.schema import StyleSpec
    from app.planning.asset_decision import decide_asset

    if not any(i.asset_id == "ph_sofa_02" for i in all_items()):
        pytest.skip("ingested ph_* library not present in this checkout")

    style = StyleSpec(name="warm_modern_family", tags=BRIEF_TAGS, materials=[])
    # (name, semantic_type, target dims, expected asset) — taken from the sample
    # project's plan at the time the style weight was introduced.
    cases = [
        ("blue upholstered sofa with patterned back strip", "sofa", (2.0, 0.9, 0.85), "ph_sofa_02"),
        ("grey pull-out sofa bed", "sofa", (2.1, 0.95, 0.9), "ph_sofa_02"),   # the one that changes
        ("Stone & Wood Coffee Table", "coffee_table", (1.3, 0.49, 1.3), "ph_coffee_table_round"),
        ("Minimal Side Table", "side_table", (0.55, 0.45, 0.55), "ph_side_table"),
        ("Potted Plant, Tall", "plant", (0.59, 1.35, 0.63), "ph_plant_01"),
        ("Minimal Side Table", "bedside_table", (0.55, 0.45, 0.55), "ph_side_table"),
        ("Drawer Cabinet", "wardrobe", (1.14, 1.88, 0.49), "ph_drawer_cabinet"),
    ]
    for name, sem, dims, want in cases:
        got = decide_asset(_plan_item(semantic_type=sem, name=name, approx_dimensions=dims), style)
        assert got.asset_id == want, f"{sem} {name!r}: {got.asset_id} != {want}"


def test_a_projects_own_generated_model_is_not_offered_to_other_projects(env):
    """One client's sofa must never turn up in another client's living room.

    Generated element models were registered into the same registry the shared
    catalog reads, so every project could match them. It surfaced as a broken
    test rather than as a leak - a project's generated side table shadowed the
    catalog's name-matched one - but the leak was the real defect: `all_items()`
    is what every project's asset ladder searches.
    """
    from app.assets.registry import get_registry
    from app.assets.schema import AssetFiles, AssetRecord
    from app.catalog.catalog import all_items

    registry = get_registry()
    shared = AssetRecord(asset_id="lib_chair", name="library chair", semantic_type="chair",
                         dimensions=(0.5, 0.9, 0.5), files=AssetFiles(normalized="lib_chair.glb"))
    mine = AssetRecord(asset_id="el_abcd1234_living_room_chair", name="the client's chair",
                       semantic_type="chair", dimensions=(0.5, 0.9, 0.5),
                       files=AssetFiles(normalized="el_abcd1234_living_room_chair.glb"),
                       project_id="proj_abcd1234")
    registry.upsert(shared)
    registry.upsert(mine)

    ids = {i.asset_id for i in all_items()}
    assert "lib_chair" in ids
    assert "el_abcd1234_living_room_chair" not in ids, "a project's own model leaked into the catalog"

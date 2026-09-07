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

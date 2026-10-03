"""P2-VIEWER-002: the viewer's copy of a model is Draco-compressed; Blender's is not.

The model here is shaped like what image-to-3D actually returns: a 32 k-triangle
mesh with position, normal and UV, and 2048 px base-colour and normal maps.
Compression is checked from the outside, not by trusting the encoder: the Draco
geometry is decoded again with DracoPy (a separate binding of Google's library)
and compared with the source triangles, and the file is run through the Khronos
glTF validator that ships with gltf-transform.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import struct
import subprocess
from pathlib import Path

import DracoPy          # required, in requirements.txt: a missing decoder fails, never skips
import pytest

from app.assets import gltf, web_variant
from app.assets.schema import IngestMeta
from app.core import config


try:
    from PIL import Image
except ImportError:                                        # pragma: no cover
    Image = None                                           # type: ignore


# ── a model like the ones Meshy returns ───────────────────────────────────


def _sphere(rings: int = 128, segments: int = 128, radius: float = 0.5):
    pos, nrm, uv, idx = [], [], [], []
    for r in range(rings + 1):
        v = r / rings
        phi = v * math.pi
        for s in range(segments + 1):
            u = s / segments
            theta = u * 2 * math.pi
            n = (math.sin(phi) * math.cos(theta), math.cos(phi), math.sin(phi) * math.sin(theta))
            nrm.append(n)
            # Squashed a little, so the three extents differ and bounds prove orientation.
            pos.append((n[0] * radius * 1.6, n[1] * radius * 0.9 + 0.45, n[2] * radius))
            uv.append((u, v))
    row = segments + 1
    for r in range(rings):
        for s in range(segments):
            a, b = r * row + s, (r + 1) * row + s
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return pos, nrm, uv, idx


def _texture(px: int, seed: int) -> bytes:
    """A textured JPEG - smooth gradients plus detail, so it compresses like a photo."""
    im = Image.new("RGB", (px, px))
    im.putdata([((x * 7 + seed) % 256, (y * 5 + x) % 256, ((x ^ y) + seed) % 256)
                for y in range(px) for x in range(px)])
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=90)
    return out.getvalue()


def write_meshy_like_glb(path: Path, *, rings: int = 128, texture_px: int = 2048) -> Path:
    pos, nrm, uv, idx = _sphere(rings, rings)
    blobs = [
        b"".join(struct.pack("<3f", *p) for p in pos),
        b"".join(struct.pack("<3f", *n) for n in nrm),
        b"".join(struct.pack("<2f", *t) for t in uv),
        struct.pack(f"<{len(idx)}I", *idx),
    ]
    images = [_texture(texture_px, 11), _texture(texture_px, 97)]
    bin_, views = b"", []
    for data in blobs + images:
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data)})
        bin_ += data + b"\0" * (-len(data) % 4)
    for i in range(3):
        views[i]["target"] = 34962
    views[3]["target"] = 34963
    xs, ys, zs = zip(*pos)
    doc = {
        "asset": {"version": "2.0", "generator": "test_web_compression"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "piece"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                                    "indices": 3, "material": 0}]}],
        "materials": [{"name": "fabric", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0},
                                                                  "metallicFactor": 0.0},
                       "normalTexture": {"index": 1}}],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"bufferView": 4, "mimeType": "image/jpeg"}, {"bufferView": 5, "mimeType": "image/jpeg"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(uv), "type": "VEC2"},
            {"bufferView": 3, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_)}],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), gltf.CHUNK_JSON) + js + struct.pack("<II", len(bin_), gltf.CHUNK_BIN) + bin_
    path.write_bytes(struct.pack("<III", gltf.GLB_MAGIC, 2, 12 + len(body)) + body)
    return path


def _draco_primitive(path: Path):
    """(decoded Draco mesh, the glTF primitive) for the model's first primitive."""
    doc = gltf.load(path)
    prim = doc.json["meshes"][0]["primitives"][0]
    ext = prim["extensions"][web_variant.DRACO_EXTENSION]
    view = doc.json["bufferViews"][ext["bufferView"]]
    start = view.get("byteOffset", 0)
    return DracoPy.decode(bytes(doc.buffers[view["buffer"]][start:start + view["byteLength"]])), prim, doc


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One real build, shared: gltf-transform takes a second or two per model."""
    d = tmp_path_factory.mktemp("web")
    src = write_meshy_like_glb(d / "piece.glb")
    stats = web_variant.build(src, d / "piece.web.glb")
    return src, d / "piece.web.glb", stats


# ── the tool is there, pinned, and used ───────────────────────────────────


def test_the_pinned_tool_is_installed():
    tool = web_variant.gltf_transform_command()
    assert tool, "run `npm ci` in aether-backend/tools - the compression tests fail, never skip, without it"
    pinned = json.loads((Path(web_variant.__file__).resolve().parents[2] / "tools" / "package.json").read_text())
    assert pinned["dependencies"]["@gltf-transform/cli"] == "4.5.0"      # exact, no range


def test_the_web_copy_is_draco_compressed_and_measurably_smaller(built):
    src, web, stats = built
    assert stats["geometry_compressed"] is True, stats["geometry_note"]
    j = gltf.load(web).json
    assert web_variant.DRACO_EXTENSION in j["extensionsUsed"]
    # Required, not merely used: a loader without Draco must refuse the file
    # rather than draw nothing.
    assert web_variant.DRACO_EXTENSION in j["extensionsRequired"]
    # The Draco step alone, against the same resized copy without it.
    geometry_before = stats["resized_bytes"]
    assert stats["dest_bytes"] < geometry_before
    saved = geometry_before - stats["dest_bytes"]
    raw_geometry = sum(v["byteLength"] for v in gltf.load(src).json["bufferViews"][:4])
    assert saved > 0.6 * raw_geometry, (saved, raw_geometry)   # most of the geometry bytes are gone
    # And the whole copy against the model Blender uses.
    assert stats["dest_bytes"] < 0.5 * stats["source_bytes"]


def test_decoded_geometry_is_the_same_mesh(built):
    src, web, _ = built
    mesh, prim, doc = _draco_primitive(web)
    source = gltf.load(src)
    src_pos = gltf.read_accessor(source, 0)
    import numpy as np

    def areas(points, faces):
        p, f = np.asarray(points, float), np.asarray(faces).reshape(-1, 3)
        return 0.5 * np.linalg.norm(np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]]), axis=1)

    # Every triangle with area survives. Draco may drop zero-area ones (the
    # sphere's poles have 256), which draw nothing; measured: 125 of them go.
    src_area = areas(src_pos, gltf.read_accessor(source, 3))
    got_area = areas(mesh.points, mesh.faces)
    assert (got_area > 1e-12).sum() == (src_area > 1e-12).sum() == 128 * 128 * 2 - 256
    assert abs(got_area.sum() - src_area.sum()) < 1e-4 * src_area.sum()
    # Edgebreaker may reorder and weld vertices, so compare the shape, not the order.
    got = np.asarray(mesh.points, dtype=float)
    want = np.asarray(src_pos, dtype=float)
    extent = want.max(0) - want.min(0)
    step = extent / (2 ** 14 - 1)                              # 14-bit quantization grid
    assert np.all(np.abs(got.min(0) - want.min(0)) <= step + 1e-7)
    assert np.all(np.abs(got.max(0) - want.max(0)) <= step + 1e-7)
    # Every decoded vertex sits within one grid step of a real source vertex.
    from scipy.spatial import cKDTree
    dist, _ = cKDTree(want).query(got)
    assert dist.max() <= float(np.linalg.norm(step)) + 1e-7, dist.max()
    # The accessor bounds the viewer sizes the piece from still match the source.
    acc = doc.json["accessors"][prim["attributes"]["POSITION"]]
    assert np.allclose(acc["min"], want.min(0), atol=float(step.max()) + 1e-6)
    assert np.allclose(acc["max"], want.max(0), atol=float(step.max()) + 1e-6)
    # Normals and UVs travel inside the Draco stream too.
    assert set(prim["extensions"][web_variant.DRACO_EXTENSION]["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0"}


def test_textures_pass_through_compression_untouched(tmp_path, built):
    src, _, _ = built
    plain = tmp_path / "plain.glb"
    web_variant.build(src, plain, compress=False)
    before = gltf.load(plain)
    after = gltf.load(built[1])

    def image_bytes(doc):
        out = []
        for img in doc.json["images"]:
            v = doc.json["bufferViews"][img["bufferView"]]
            s = v.get("byteOffset", 0)
            out.append(bytes(doc.buffers[v["buffer"]][s:s + v["byteLength"]]))
        return out

    assert image_bytes(after) == image_bytes(before)          # byte-identical: Draco is geometry only
    assert [Image.open(io.BytesIO(b)).size for b in image_bytes(after)] == [(1024, 1024)] * 2


def test_the_khronos_validator_finds_no_errors(built):
    run = subprocess.run([web_variant.gltf_transform_command(), "validate", str(built[1])],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=120, env={**os.environ, "NO_COLOR": "1"})
    report = re.sub(r"\x1b\[[0-9;]*m", "", run.stdout + run.stderr)
    assert run.returncode == 0, report
    errors = report.split(" WARNING")[0]
    assert "ERROR" in errors and "No errors found." in errors, report


# ── Blender never sees it ─────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path / "data"))
    from app.assets import registry as reg

    config.get_settings.cache_clear()
    reg._registry = None
    yield tmp_path
    config.get_settings.cache_clear()
    reg._registry = None


def test_ingest_compresses_the_viewer_copy_and_leaves_blenders_alone(data_dir):
    from app.assets import pipeline

    src = write_meshy_like_glb(data_dir / "meshy.glb")
    rec = pipeline.ingest_file(src, IngestMeta(asset_id="gen_sofa", name="sofa", semantic_type="sofa",
                                               expected_dimensions=(1.6, 0.9, 1.0)))
    assert rec.status == "normalized", rec.validation
    root = config.get_settings().data_dir
    normalized, web = root / rec.files.normalized, root / rec.files.web
    assert not web_variant.is_draco(normalized)                # Blender reads this one
    assert web_variant.is_draco(web)                           # the viewer reads this one
    assert web.stat().st_size < normalized.stat().st_size / 2
    # The normalized copy is still plain accessors the dependency-free reader can measure.
    assert gltf.measure(gltf.load(normalized)).triangles == 128 * 128 * 2
    # And it is the one the Blender manifest hands to Blender.
    from app.blender.manifest import _asset_entry
    entry = _asset_entry("gen_sofa", "sofa")
    assert entry["kind"] == "glb" and Path(entry["path"]) == normalized


def test_a_model_with_small_textures_still_gets_a_compressed_copy(data_dir):
    """Before P2-VIEWER-002 a web copy existed only when textures were resized."""
    from app.assets import pipeline

    src = write_meshy_like_glb(data_dir / "small.glb", texture_px=256)
    rec = pipeline.ingest_file(src, IngestMeta(asset_id="gen_small", name="stool", semantic_type="stool",
                                               expected_dimensions=(1.6, 0.9, 1.0)))
    assert rec.files.web, "geometry compression alone is worth a web copy"
    assert web_variant.is_draco(config.get_settings().data_dir / rec.files.web)


# ── never fatal, never bigger ─────────────────────────────────────────────


def test_without_the_tool_the_copy_ships_uncompressed_and_says_why(tmp_path, monkeypatch, built):
    monkeypatch.setattr(web_variant, "gltf_transform_command", lambda: None)
    stats = web_variant.build(built[0], tmp_path / "w.glb")
    assert stats["geometry_compressed"] is False
    assert "not installed" in stats["geometry_note"]
    assert not web_variant.is_draco(tmp_path / "w.glb")
    assert gltf.load(tmp_path / "w.glb").json["meshes"]                    # a valid model all the same


def test_a_failing_tool_leaves_a_valid_uncompressed_copy(tmp_path, monkeypatch, built):
    broken = tmp_path / ("broken.cmd" if subprocess.os.name == "nt" else "broken.sh")
    # Dies half-way through writing its output, as a crashed or killed run does.
    broken.write_text("@echo half a model> %3\n@exit /b 3\n" if subprocess.os.name == "nt"
                      else "#!/bin/sh\necho 'half a model' > \"$3\"\nexit 3\n")
    broken.chmod(0o755)
    monkeypatch.setattr(web_variant, "gltf_transform_command", lambda: str(broken))
    stats = web_variant.build(built[0], tmp_path / "w.glb")
    assert stats["geometry_compressed"] is False and "failed" in stats["geometry_note"]
    assert not list(tmp_path.glob("*.tmp.glb"))                            # no temp file left behind
    assert gltf.measure(gltf.load(tmp_path / "w.glb")).triangles == 128 * 128 * 2


def test_compression_that_would_grow_the_file_is_not_kept(tmp_path, monkeypatch, built):
    """A stand-in tool whose "compressed" output is larger than its input."""
    bigger = built[1]                                          # a real Draco file, 1.2 MB
    if subprocess.os.name == "nt":
        tool = tmp_path / "grows.cmd"
        tool.write_text(f'@copy /y "{bigger}" %3 >nul\n')
    else:
        tool = tmp_path / "grows.sh"
        tool.write_text(f'#!/bin/sh\ncp "{bigger}" "$3"\n')
        tool.chmod(0o755)
    monkeypatch.setattr(web_variant, "gltf_transform_command", lambda: str(tool))
    tiny = write_meshy_like_glb(tmp_path / "tiny.glb", rings=4, texture_px=8)
    before = tiny.read_bytes()
    assert len(before) < bigger.stat().st_size
    compressed, why = web_variant.compress_geometry(tiny)
    assert compressed is False and "smaller" in why
    assert tiny.read_bytes() == before                         # the original stays, byte for byte

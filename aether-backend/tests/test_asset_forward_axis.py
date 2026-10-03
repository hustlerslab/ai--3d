"""P1-ASSET-005 — the forward axis is measured at ingest and stored.

Synthetic chairs (a seat slab plus a backrest slab) authored facing each of
the four quarter turns go through the real ingester; the recorded yaw must
turn each one to face -Z, the normalized file must come out canonical, the
frame graph must carry a real ASSET -> OBJECT rotation for it, and records
that predate the measurement must keep identity. No downloads, no GPU.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from app.assets import gltf, orientation
from app.assets.schema import AssetRecord, IngestMeta, NormalizationInfo
from app.spatial.coordinate_frames import FrameId
from app.spatial.frame_graph import asset_to_object_transform
from app.spatial.transforms import IDENTITY_MAT3, Vector3, is_orthonormal


# ── fixtures ──────────────────────────────────────────────────────────────


def _box(lo, hi):
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    faces = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
        (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
        (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]
    return corners, faces


def write_boxes_gltf(path: Path, boxes) -> Path:
    """One mesh made of axis-aligned boxes, given as (min, max) corners."""
    positions: list[tuple] = []
    indices: list[tuple] = []
    for lo, hi in boxes:
        corners, faces = _box(lo, hi)
        base = len(positions)
        positions.extend(corners)
        indices.extend((a + base, b + base, c + base) for a, b, c in faces)
    pos_blob = b"".join(struct.pack("<fff", *p) for p in positions)
    idx_blob = b"".join(struct.pack("<HHH", *f) for f in indices)
    blob = pos_blob + idx_blob
    mn = [min(p[i] for p in positions) for i in range(3)]
    mx = [max(p[i] for p in positions) for i in range(3)]
    (path.parent / f"{path.stem}.bin").write_bytes(blob)
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": path.stem}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"uri": f"{path.stem}.bin", "byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_blob)},
            {"buffer": 0, "byteOffset": len(pos_blob), "byteLength": len(idx_blob)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3", "min": mn, "max": mx},
            {"bufferView": 1, "componentType": 5123, "count": len(indices) * 3, "type": "SCALAR"},
        ],
    }
    path.write_text(json.dumps(doc), "utf-8")
    return path


def write_chair_gltf(folder: Path, facing: str) -> Path:
    """A 0.5 m chair: seat 0.40-0.45 m high, backrest 0.05 m thick rising to
    0.95 m on the side OPPOSITE the way it faces. Authored in metres."""
    seat = ((-0.25, 0.40, -0.25), (0.25, 0.45, 0.25))
    back = {
        "-z": ((-0.25, 0.45, 0.20), (0.25, 0.95, 0.25)),   # backrest at +Z: canonical
        "+z": ((-0.25, 0.45, -0.25), (0.25, 0.95, -0.20)),
        "+x": ((-0.25, 0.45, -0.25), (-0.20, 0.95, 0.25)),
        "-x": ((0.20, 0.45, -0.25), (0.25, 0.95, 0.25)),
    }[facing]
    return write_boxes_gltf(folder / f"chair_{facing.replace('+', 'p').replace('-', 'm')}.gltf", [seat, back])


def _backrest_centroid_xz(doc) -> tuple[float, float]:
    """Where the tall part of the mesh sits, read back from the file itself."""
    part = orientation.tall_part(doc)
    assert part is not None
    return part.centroid_x, part.centroid_z


def _ingest(path: Path, **meta):
    from app.assets import pipeline

    defaults = dict(asset_id=path.stem, name=path.stem, semantic_type="chair")
    return pipeline.ingest_file(path, IngestMeta(**{**defaults, **meta}))


def _normalized_doc(record):
    from app.core.config import get_settings

    return gltf.load(get_settings().data_dir / record.files.normalized)


# ── acceptance: a deliberately rotated asset records a non-zero yaw ───────


@pytest.mark.parametrize("facing, expected", [
    ("-z", 0.0), ("+z", math.pi), ("+x", math.pi / 2), ("-x", -math.pi / 2),
])
def test_a_rotated_chair_records_the_yaw_that_turns_it_to_face_minus_z(env, tmp_path, facing, expected):
    record = _ingest(write_chair_gltf(tmp_path, facing))

    assert record.status == "normalized", record.validation
    assert record.normalization.yaw_source == "measured"
    assert record.normalization.yaw_offset == pytest.approx(expected, abs=1e-9)

    # Placement honours it: the normalized file is canonical - its backrest
    # now sits at +Z, so it faces -Z and measures as needing no correction.
    doc = _normalized_doc(record)
    bx, bz = _backrest_centroid_xz(doc)
    assert bz > 0.15 and abs(bx) < 1e-6, (bx, bz)
    assert orientation.measure_forward_yaw(doc, "chair") == 0.0
    # and the footprint is still a 0.5 m square standing on the floor
    m = gltf.measure(doc)
    assert m.size == pytest.approx((0.5, 0.55, 0.5), abs=1e-6)
    assert m.bbox_min[1] == pytest.approx(0.0, abs=1e-6)


def test_a_symmetric_piece_measures_zero_and_is_still_marked_measured(env, tmp_path):
    path = write_boxes_gltf(tmp_path / "block.gltf", [((-1.0, 0.0, -0.4), (1.0, 0.8, 0.4))])
    record = _ingest(path, semantic_type="sofa")
    assert record.normalization.yaw_offset == 0.0
    assert record.normalization.yaw_source == "measured"


def test_a_type_without_a_facing_rule_is_left_alone(env, tmp_path):
    record = _ingest(write_chair_gltf(tmp_path, "+x"), semantic_type="vase")
    assert record.normalization.yaw_offset == 0.0
    assert record.normalization.yaw_source == "measured"


def test_a_thin_piece_faces_along_its_thin_axis(env, tmp_path):
    across = _ingest(write_boxes_gltf(tmp_path / "tv_x.gltf", [((-0.025, 0.0, -0.5), (0.025, 0.6, 0.5))]),
                     semantic_type="tv")
    assert across.normalization.yaw_offset == pytest.approx(math.pi / 2)
    facing = _ingest(write_boxes_gltf(tmp_path / "tv_z.gltf", [((-0.5, 0.0, -0.025), (0.5, 0.6, 0.025))]),
                     semantic_type="tv")
    assert facing.normalization.yaw_offset == 0.0
    assert facing.dimensions[0] > facing.dimensions[2] and across.dimensions[0] > across.dimensions[2]


def test_a_declared_yaw_beats_the_measurement_even_when_it_is_zero(env, tmp_path):
    record = _ingest(write_chair_gltf(tmp_path, "+x"), yaw_offset=0.0)
    assert record.normalization.yaw_offset == 0.0
    assert record.normalization.yaw_source == "declared"
    bx, _ = _backrest_centroid_xz(_normalized_doc(record))
    assert bx < -0.15, "a declared zero must leave the mesh exactly as authored"


def test_renormalize_re_measures_unless_the_yaw_was_declared(env, tmp_path):
    from app.assets import pipeline

    measured = _ingest(write_chair_gltf(tmp_path, "+x"))
    again = pipeline.renormalize(measured.asset_id)
    assert again.normalization.yaw_offset == pytest.approx(math.pi / 2)
    assert again.normalization.yaw_source == "measured"

    folder = tmp_path / "declared"
    folder.mkdir()
    declared = _ingest(write_chair_gltf(folder, "+x"), asset_id="declared_chair", yaw_offset=math.pi)
    again = pipeline.renormalize("declared_chair")
    assert again.normalization.yaw_offset == pytest.approx(math.pi)
    assert again.normalization.yaw_source == "declared"
    turned = pipeline.renormalize("declared_chair", yaw_offset=math.pi / 2)
    assert turned.normalization.yaw_offset == pytest.approx(math.pi / 2)


# ── acceptance: the audited catalog keeps identity ────────────────────────


def test_records_that_predate_the_measurement_load_unmeasured_and_keep_identity(env):
    from app.assets.registry import get_registry

    legacy = AssetRecord.model_validate({
        "asset_id": "ph_sofa_02", "name": "Leather & Fabric Sofa", "semantic_type": "sofa",
        "normalization": {"detected_unit": "meter", "unit_scale": 1.0, "yaw_offset": 0.0},
    })
    assert legacy.normalization.yaw_source == "unmeasured"
    assert legacy.normalization.yaw_offset == 0.0
    get_registry().upsert(legacy)

    t = asset_to_object_transform("ph_sofa_02")
    assert t.rotation == IDENTITY_MAT3 and t.translation == (0.0, 0.0, 0.0)
    assert t.source == t.target == FrameId.OBJECT
    assert "unmeasured" in t.provenance

    assert asset_to_object_transform("no_such_asset").rotation == IDENTITY_MAT3
    assert NormalizationInfo().yaw_source == "unmeasured"


# ── acceptance: a non-zero measured yaw is a real Rigid3 on ASSET -> OBJECT ─


def test_a_measured_yaw_becomes_a_real_rotation_on_the_asset_edge(env, tmp_path):
    record = _ingest(write_chair_gltf(tmp_path, "+x"))
    t = asset_to_object_transform(record.asset_id)

    assert t.source == FrameId.ASSET and t.target == FrameId.OBJECT
    assert t.rotation != IDENTITY_MAT3 and is_orthonormal(t.rotation)
    assert t.confidence == 0.9 and "measured" in t.provenance
    # the chair was authored facing +X; in OBJECT space it faces -Z
    fwd = t.apply_vector(Vector3(1.0, 0.0, 0.0, frame=FrameId.ASSET))
    assert (fwd.x, fwd.y, fwd.z) == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
    # and the round trip through the inverse is the identity
    back = t.inverse().compose(t)
    for i in range(3):
        for j in range(3):
            assert back.rotation[i][j] == pytest.approx(IDENTITY_MAT3[i][j], abs=1e-12)

    declared = asset_to_object_transform(yaw_offset=math.pi, yaw_source="declared")
    assert declared.confidence == 1.0
    fwd = declared.apply_vector(Vector3(0.0, 0.0, 1.0, frame=FrameId.ASSET))
    assert (fwd.x, fwd.z) == pytest.approx((0.0, -1.0), abs=1e-9)


def test_the_frame_graph_rotation_is_the_one_normalization_bakes_into_the_file(env, tmp_path):
    """Two codepaths, one convention: the Rigid3 must move a point exactly as
    normalization.plan's root-node quaternion does, or the frame graph would
    describe a rotation the file does not carry."""
    from app.assets import normalization

    for yaw in (math.pi / 2, math.pi, -math.pi / 2):
        t = asset_to_object_transform(yaw_offset=yaw, yaw_source="declared")
        for p in ((1.0, 0.2, 0.0), (0.3, 0.0, -0.7), (-0.4, 0.9, 0.5)):
            x, z = normalization._rotate_y(p[0], p[2], yaw)
            got = t.apply_vector(Vector3(*p, frame=FrameId.ASSET))
            assert (got.x, got.y, got.z) == pytest.approx((x, p[1], z), abs=1e-12)


# ── the measurement reaches Blender ───────────────────────────────────────


def test_the_manifest_carries_the_forward_axis_to_the_importer(env, tmp_path):
    from app.blender.manifest import _asset_entry

    record = _ingest(write_chair_gltf(tmp_path, "+z"))
    entry = _asset_entry(record.asset_id, "chair")
    assert entry["kind"] == "glb"
    assert entry["forward"] == {"yaw_offset": pytest.approx(math.pi), "source": "measured"}

    declared = _ingest(write_chair_gltf(tmp_path, "-x"), yaw_offset=0.0)
    assert _asset_entry(declared.asset_id, "chair")["forward"] == {"yaw_offset": 0.0, "source": "declared"}


def test_the_importer_only_guesses_for_unmeasured_records():
    """The Blender script cannot be imported here (it needs bpy), so the rule it
    applies is pinned by reading it: the build-time heuristic must be gated on
    the manifest saying the forward axis was never measured."""
    src = (Path(__file__).resolve().parents[1] / "blender" / "scripts" / "import_assets.py").read_text("utf-8")
    assert 'forward.get("source", "unmeasured")' in src
    assert 'if forward_source == "unmeasured":' in src
    gate = src.index('if forward_source == "unmeasured":')
    call = src.index("_native_forward_yaw(children", gate)
    assert call - gate < 200, "the heuristic call must sit inside the unmeasured gate"

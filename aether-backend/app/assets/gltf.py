"""Dependency-free glTF 2.0 / GLB reader, packer and measurer.

Everything the pipeline needs from a model — its bounding box, triangle
count, textures, and a single self-contained GLB — is derived here without
a mesh library. Geometry is *read*, never rewritten: normalization is
expressed as a root node transform (see normalization.py), so the source
mesh data passes through byte-for-byte.

glTF facts relied on:
  - POSITION accessors must carry min/max (spec requirement); we still fall
    back to decoding the floats when they are missing.
  - Node transforms are TRS or a column-major 4x4 matrix.
  - GLB = 12-byte header + JSON chunk + optional BIN chunk, 4-byte aligned.
"""
from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_FORMATS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}

MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".ktx2": "image/ktx2"}


class GltfError(Exception):
    pass


@dataclass
class GltfDocument:
    json: dict[str, Any]
    buffers: list[bytes]                # decoded buffer bytes, index-aligned with json["buffers"]
    base_dir: Optional[Path] = None
    image_bytes: dict[int, bytes] = field(default_factory=dict)  # image index → bytes (external ones)
    missing_files: list[str] = field(default_factory=list)


# ── Loading ───────────────────────────────────────────────────────────────


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def _read_uri(uri: str, base_dir: Optional[Path], missing: list[str]) -> Optional[bytes]:
    if uri.startswith("data:"):
        _, _, data = uri.partition(",")
        return base64.b64decode(data)
    if base_dir is None:
        missing.append(uri)
        return None
    path = base_dir / uri
    if not path.exists():
        missing.append(uri)
        return None
    return path.read_bytes()


def load(path: Path) -> GltfDocument:
    """Load a .glb or .gltf (with external .bin/images) from disk."""
    path = Path(path)
    raw = path.read_bytes()
    if raw[:4] == struct.pack("<I", GLB_MAGIC):
        return _load_glb(raw, path.parent)
    try:
        doc_json = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GltfError(f"Not a glTF/GLB file: {path.name}") from exc
    return _load_gltf(doc_json, path.parent, bin_chunk=None)


def _load_glb(raw: bytes, base_dir: Path) -> GltfDocument:
    if len(raw) < 12:
        raise GltfError("GLB too short")
    magic, version, length = struct.unpack_from("<III", raw, 0)
    if version != 2:
        raise GltfError(f"Unsupported GLB version {version}")
    offset = 12
    json_chunk: Optional[bytes] = None
    bin_chunk: Optional[bytes] = None
    while offset + 8 <= len(raw):
        chunk_len, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        data = raw[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == CHUNK_JSON:
            json_chunk = data
        elif chunk_type == CHUNK_BIN:
            bin_chunk = data
    if json_chunk is None:
        raise GltfError("GLB has no JSON chunk")
    return _load_gltf(json.loads(json_chunk.decode("utf-8")), base_dir, bin_chunk)


def _load_gltf(doc_json: dict, base_dir: Path, bin_chunk: Optional[bytes]) -> GltfDocument:
    missing: list[str] = []
    buffers: list[bytes] = []
    for i, buf in enumerate(doc_json.get("buffers", [])):
        uri = buf.get("uri")
        if uri is None:
            if i == 0 and bin_chunk is not None:
                buffers.append(bin_chunk)
            else:
                missing.append(f"buffer[{i}]")
                buffers.append(b"")
            continue
        data = _read_uri(uri, base_dir, missing)
        buffers.append(data or b"")

    images: dict[int, bytes] = {}
    for i, img in enumerate(doc_json.get("images", [])):
        uri = img.get("uri")
        if uri is not None:
            data = _read_uri(uri, base_dir, missing)
            if data is not None:
                images[i] = data
    return GltfDocument(json=doc_json, buffers=buffers, base_dir=base_dir, image_bytes=images, missing_files=missing)


# ── Accessors ─────────────────────────────────────────────────────────────


def _buffer_view_bytes(doc: GltfDocument, view_index: int) -> tuple[bytes, int]:
    view = doc.json["bufferViews"][view_index]
    buf = doc.buffers[view["buffer"]]
    start = view.get("byteOffset", 0)
    return buf[start : start + view["byteLength"]], view.get("byteStride", 0)


def read_accessor(doc: GltfDocument, accessor_index: int) -> list[tuple[float, ...]]:
    acc = doc.json["accessors"][accessor_index]
    if "bufferView" not in acc:
        return []
    data, stride = _buffer_view_bytes(doc, acc["bufferView"])
    n = TYPE_COUNTS[acc["type"]]
    fmt_char = COMPONENT_FORMATS[acc["componentType"]]
    comp_size = COMPONENT_SIZES[acc["componentType"]]
    elem_size = n * comp_size
    stride = stride or elem_size
    offset = acc.get("byteOffset", 0)
    fmt = "<" + fmt_char * n
    out = []
    for i in range(acc["count"]):
        pos = offset + i * stride
        out.append(struct.unpack_from(fmt, data, pos))
    return out


# ── Transforms ────────────────────────────────────────────────────────────

Mat4 = list[float]  # column-major, 16 floats


def identity() -> Mat4:
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def mat_mul(a: Mat4, b: Mat4) -> Mat4:
    """a * b for column-major 4x4 matrices."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


def trs_matrix(t, r, s) -> Mat4:
    x, y, z, w = r
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    m = [
        (1 - 2 * (yy + zz)) * s[0], (2 * (xy + wz)) * s[0], (2 * (xz - wy)) * s[0], 0,
        (2 * (xy - wz)) * s[1], (1 - 2 * (xx + zz)) * s[1], (2 * (yz + wx)) * s[1], 0,
        (2 * (xz + wy)) * s[2], (2 * (yz - wx)) * s[2], (1 - 2 * (xx + yy)) * s[2], 0,
        t[0], t[1], t[2], 1,
    ]
    return m


def node_local_matrix(node: dict) -> Mat4:
    if "matrix" in node:
        return list(node["matrix"])
    return trs_matrix(
        node.get("translation", [0, 0, 0]),
        node.get("rotation", [0, 0, 0, 1]),
        node.get("scale", [1, 1, 1]),
    )


def transform_point(m: Mat4, p) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


# ── Measurement ───────────────────────────────────────────────────────────


@dataclass
class Measurement:
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    triangles: int
    mesh_instances: int
    has_nan: bool = False

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(self.bbox_max[i] - self.bbox_min[i] for i in range(3))  # type: ignore[return-value]

    @property
    def center(self) -> tuple[float, float, float]:
        return tuple((self.bbox_max[i] + self.bbox_min[i]) / 2 for i in range(3))  # type: ignore[return-value]


def _primitive_bounds(doc: GltfDocument, prim: dict) -> Optional[tuple[list[float], list[float]]]:
    pos_index = prim.get("attributes", {}).get("POSITION")
    if pos_index is None:
        return None
    acc = doc.json["accessors"][pos_index]
    if "min" in acc and "max" in acc and len(acc["min"]) == 3:
        return list(acc["min"]), list(acc["max"])
    pts = read_accessor(doc, pos_index)
    if not pts:
        return None
    mn = [min(p[i] for p in pts) for i in range(3)]
    mx = [max(p[i] for p in pts) for i in range(3)]
    return mn, mx


def _primitive_triangles(doc: GltfDocument, prim: dict) -> int:
    mode = prim.get("mode", 4)
    if "indices" in prim:
        count = doc.json["accessors"][prim["indices"]]["count"]
    else:
        pos_index = prim.get("attributes", {}).get("POSITION")
        if pos_index is None:
            return 0
        count = doc.json["accessors"][pos_index]["count"]
    if mode == 4:
        return count // 3
    if mode in (5, 6):
        return max(0, count - 2)
    return 0


def measure(doc: GltfDocument) -> Measurement:
    """World-space AABB and triangle count across the default scene."""
    nodes = doc.json.get("nodes", [])
    meshes = doc.json.get("meshes", [])
    scenes = doc.json.get("scenes", [])
    scene_index = doc.json.get("scene", 0)
    roots = scenes[scene_index]["nodes"] if scenes else list(range(len(nodes)))

    mn = [math.inf] * 3
    mx = [-math.inf] * 3
    triangles = 0
    instances = 0
    has_nan = False

    def visit(node_index: int, parent: Mat4) -> None:
        nonlocal triangles, instances, has_nan
        node = nodes[node_index]
        world = mat_mul(parent, node_local_matrix(node))
        if any(math.isnan(v) for v in world):
            has_nan = True
        if "mesh" in node:
            instances += 1
            for prim in meshes[node["mesh"]].get("primitives", []):
                triangles += _primitive_triangles(doc, prim)
                bounds = _primitive_bounds(doc, prim)
                if bounds is None:
                    continue
                lo, hi = bounds
                for corner in (
                    (lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]), (lo[0], hi[1], lo[2]), (hi[0], hi[1], lo[2]),
                    (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]), (lo[0], hi[1], hi[2]), (hi[0], hi[1], hi[2]),
                ):
                    p = transform_point(world, corner)
                    for i in range(3):
                        if math.isnan(p[i]):
                            has_nan = True
                            continue
                        mn[i] = min(mn[i], p[i])
                        mx[i] = max(mx[i], p[i])
        for child in node.get("children", []):
            visit(child, world)

    for root in roots:
        visit(root, identity())

    if instances == 0 or any(math.isinf(v) for v in mn + mx):
        return Measurement((0, 0, 0), (0, 0, 0), triangles, instances, has_nan)
    return Measurement(tuple(mn), tuple(mx), triangles, instances, has_nan)  # type: ignore[arg-type]


def texture_summary(doc: GltfDocument) -> dict[str, Any]:
    images = doc.json.get("images", [])
    total = 0
    for i, img in enumerate(images):
        if i in doc.image_bytes:
            total += len(doc.image_bytes[i])
        elif "bufferView" in img:
            data, _ = _buffer_view_bytes(doc, img["bufferView"])
            total += len(data)
    return {"count": len(images), "bytes": total}


# ── Packing to a single GLB ───────────────────────────────────────────────


def pack_glb(doc: GltfDocument, root_transform: Optional[dict] = None) -> bytes:
    """Rewrite the document as a self-contained GLB.

    All buffer views are copied into one buffer; external images are embedded.
    If `root_transform` is given ({translation, rotation, scale}), a new root
    node carrying it is inserted above every scene root — this is how
    normalization is applied without touching vertex data.
    """
    j = json.loads(json.dumps(doc.json))  # deep copy
    blob = bytearray()

    def append(data: bytes) -> int:
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(data)
        return offset

    for view in j.get("bufferViews", []):
        src = doc.buffers[view["buffer"]]
        start = view.get("byteOffset", 0)
        data = src[start : start + view["byteLength"]]
        view["buffer"] = 0
        view["byteOffset"] = append(data)

    for i, img in enumerate(j.get("images", [])):
        if "uri" in img:
            data = doc.image_bytes.get(i)
            if data is None:
                raise GltfError(f"Image file missing: {img['uri']}")
            ext = Path(img["uri"].split("?")[0]).suffix.lower()
            mime = img.get("mimeType") or MIME_BY_EXT.get(ext, "image/png")
            if img["uri"].startswith("data:"):
                mime = img["uri"][5:].split(";")[0] or mime
            offset = append(data)
            j.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
            img["bufferView"] = len(j["bufferViews"]) - 1
            img["mimeType"] = mime
            del img["uri"]

    while len(blob) % 4:
        blob.append(0)
    j["buffers"] = [{"byteLength": len(blob)}]

    if root_transform is not None:
        nodes = j.setdefault("nodes", [])
        scenes = j.get("scenes") or [{"nodes": list(range(len(nodes)))}]
        scene_index = j.get("scene", 0)
        old_roots = scenes[scene_index].get("nodes", [])
        root = {"name": "aether_normalized_root", "children": old_roots}
        root.update({k: v for k, v in root_transform.items() if v is not None})
        nodes.append(root)
        scenes[scene_index]["nodes"] = [len(nodes) - 1]
        j["scenes"] = scenes
        j["scene"] = scene_index

    j.setdefault("asset", {})["generator"] = "Aether asset pipeline"
    json_bytes = json.dumps(j, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "

    total = 12 + 8 + len(json_bytes) + 8 + len(blob)
    out = bytearray()
    out += struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), CHUNK_JSON) + json_bytes
    out += struct.pack("<II", len(blob), CHUNK_BIN) + bytes(blob)
    return bytes(out)

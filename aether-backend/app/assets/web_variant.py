"""A lighter copy of a model for the interactive viewer.

Why this exists, in numbers. A mesh from image-to-3D arrives with three
2048 x 2048 JPEG maps - base colour, metallic-roughness, normal. On disk that is
about 10 MB, of which 88 % is texture. On the GPU it is far worse, because a
decoded texture is stored uncompressed:

    2048 x 2048 x 4 bytes = 16 MB per map, x3 maps = 48 MB per piece

A fifteen-piece room therefore asks for roughly 700 MB of texture memory before
the walls, the floors, or the renderer's own buffers. On the 6 GB laptop card
this runs on, every generated mesh silently failed to appear and the viewer drew
Suspense placeholders instead - which were twice mistaken for the real thing.

Geometry is left exactly as it is: 30 k triangles is about 1 MB and was never
the problem. Only the images are resized, and only in this copy. The full-size
model stays untouched for the Blender walkthrough, which renders once on the
GPU and does not care.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

from . import gltf

try:
    from PIL import Image
except ImportError:                                        # pragma: no cover
    Image = None                                           # type: ignore

log = logging.getLogger("aether.assets.web_variant")

# Bytes a decoded RGBA texture occupies on the GPU, before mipmaps.
BYTES_PER_PIXEL = 4
# Three.js mipmaps power-of-two textures, which costs a third again. Counted,
# because it is real and it is what actually exhausts the card.
MIPMAP_OVERHEAD = 4 / 3

WEB_MAX_TEXTURE_PX = 1024
JPEG_QUALITY = 88


def vram_bytes(width: int, height: int, maps: int = 1) -> int:
    """Decoded GPU cost of `maps` textures at this resolution, with mipmaps."""
    return int(width * height * BYTES_PER_PIXEL * MIPMAP_OVERHEAD) * maps


def _resize(data: bytes, max_px: int, quality: int):
    """(bytes, mime, before, after) or None when it is already small enough."""
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:                                      # noqa: BLE001
        return None                                        # not an image we can touch
    before = im.size
    if max(before) <= max_px:
        return None
    im.thumbnail((max_px, max_px), Image.LANCZOS)
    out = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.convert("RGBA").save(out, format="PNG", optimize=True)
        mime = "image/png"
    else:
        # 4:4:4, no chroma subsampling: a normal map stores direction in its
        # channels, and subsampling those visibly corrugates a flat surface.
        # The saving would be small next to the resize anyway.
        im.convert("RGB").save(out, format="JPEG", quality=quality, subsampling=0, optimize=True)
        mime = "image/jpeg"
    return out.getvalue(), mime, before, im.size


def _image_data(doc, j: dict, index: int, img: dict) -> bytes:
    if "bufferView" in img:
        view = j["bufferViews"][img["bufferView"]]
        buf = doc.buffers[view["buffer"]]
        start = view.get("byteOffset", 0)
        return bytes(buf[start:start + view["byteLength"]])
    return doc.image_bytes.get(index, b"")


def _prune_buffer_views(j: dict) -> int:
    """Drop buffer views nothing points at any more, and reindex the rest.

    Required, not tidying. `pack_glb` copies every buffer view it finds, so a
    resized image that leaves its old view behind ships BOTH copies: the first
    run of this module cut scene VRAM from 896 MB to 224 MB and grew the files
    from 100.6 MB to 107.7 MB, because each one still carried its 2048 px
    original alongside the new 1024 px one.

    Conservative on purpose. If anything other than accessors and images refers
    to buffer views - a Draco or meshopt extension, say - nothing is pruned and
    the file merely stays large, which is survivable. Silently dropping a view
    some extension still needs would corrupt the model.
    """
    views = j.get("bufferViews") or []
    if not views:
        return 0

    known: set[int] = set()
    for acc in j.get("accessors", []):
        if "bufferView" in acc:
            known.add(acc["bufferView"])
        sparse = acc.get("sparse") or {}
        for part in ("indices", "values"):
            if part in sparse and "bufferView" in sparse[part]:
                known.add(sparse[part]["bufferView"])
    for img in j.get("images", []):
        if "bufferView" in img:
            known.add(img["bufferView"])

    # Any other mention of a bufferView means we do not understand the file
    # well enough to prune it safely.
    def mentions(node) -> int:
        if isinstance(node, dict):
            return sum((1 if k == "bufferView" else 0) + mentions(v) for k, v in node.items())
        if isinstance(node, list):
            return sum(mentions(v) for v in node)
        return 0

    if mentions(j) != len(known) + sum(
        1 for acc in j.get("accessors", []) for part in ("indices", "values")
        if part in (acc.get("sparse") or {})
    ):
        # A bufferView is referenced somewhere we did not account for.
        return 0

    keep = sorted(known)
    if len(keep) == len(views):
        return 0
    remap = {old: new for new, old in enumerate(keep)}
    j["bufferViews"] = [views[i] for i in keep]
    for acc in j.get("accessors", []):
        if "bufferView" in acc:
            acc["bufferView"] = remap[acc["bufferView"]]
        sparse = acc.get("sparse") or {}
        for part in ("indices", "values"):
            if part in sparse and "bufferView" in sparse[part]:
                sparse[part]["bufferView"] = remap[sparse[part]["bufferView"]]
    for img in j.get("images", []):
        if "bufferView" in img:
            img["bufferView"] = remap[img["bufferView"]]
    return len(views) - len(keep)


def build(source: Path, dest: Path, *, max_px: int = WEB_MAX_TEXTURE_PX,
          quality: int = JPEG_QUALITY) -> dict:
    """Write a viewer-sized copy of `source` to `dest`. Returns what it cost.

    Never raises on a texture it cannot read: that image is copied through
    untouched and counted in `images_kept`, because a slightly heavy model is a
    better outcome than no model at all.
    """
    doc = gltf.load(source)
    j = doc.json
    resized = kept = 0
    vram_before = vram_after = 0
    notes: list[str] = []

    for index, img in enumerate(j.get("images", [])):
        data = _image_data(doc, j, index, img)
        if not data:
            continue
        result = _resize(data, max_px, quality)
        if result is None:
            if Image is not None:
                try:
                    w, h = Image.open(io.BytesIO(data)).size
                    vram_before += vram_bytes(w, h)
                    vram_after += vram_bytes(w, h)
                except Exception:                          # noqa: BLE001
                    pass
            kept += 1
            continue
        new_bytes, mime, before, after = result
        vram_before += vram_bytes(*before)
        vram_after += vram_bytes(*after)
        resized += 1
        notes.append(f"{before[0]}x{before[1]} -> {after[0]}x{after[1]}")
        # Route the image through `image_bytes` + a uri, which is the path
        # pack_glb re-embeds from; the old bufferView is simply left
        # unreferenced and dropped when the buffer is rebuilt.
        doc.image_bytes[index] = new_bytes
        img.pop("bufferView", None)
        img["uri"] = f"data:{mime};base64,"
        img["mimeType"] = mime

    pruned = _prune_buffer_views(j)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(gltf.pack_glb(doc))
    return {
        "views_pruned": pruned,
        "source_bytes": source.stat().st_size,
        "dest_bytes": dest.stat().st_size,
        "images_resized": resized,
        "images_kept": kept,
        "vram_before": vram_before,
        "vram_after": vram_after,
        "notes": notes,
    }


__all__ = ["build", "vram_bytes", "WEB_MAX_TEXTURE_PX"]

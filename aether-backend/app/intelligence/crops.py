"""Cut each spotted item out of its reference photo (schema 1.1).

Crops feed two rungs of the asset ladder: flat items (art, rugs, pillows)
become textured planes that carry the photo's actual pattern, and sculptural
items hand their crop to image-to-3D when generation is enabled. Crops are
deterministic files under analysis/crops/, so re-runs and retries reuse them.
"""
from __future__ import annotations

from pathlib import Path

from . import vocab
from .schema import DesignAnalysis, InputBundle

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

CROP_DIR = "analysis/crops"
PAD = 0.04          # fraction of the box added on every side
MIN_SIDE = 24       # px: smaller crops are noise


def write_crops(analysis: DesignAnalysis, bundle: InputBundle, project_root: Path, *, force: bool = False) -> list[str]:
    """Write one PNG per spotted item with a bbox; sets `crop_ref` on the item.
    Returns warnings."""
    warnings: list[str] = []
    if Image is None:
        return ["Pillow missing; no crops written"]
    out_dir = project_root / CROP_DIR
    opened: dict[str, "Image.Image"] = {}
    for idx, item in enumerate(analysis.spotted_objects):
        # By stable id, not by position: a deleted photo used to shift every
        # later index down one, so a crop meant for the sofa was cut out of
        # whatever photo had slid into its place, and that crop then went on to
        # texture the object and seed image-to-3D.
        photo = bundle.photo_for(item) if item.bbox is not None else None
        if photo is None:
            if item.bbox is not None and (item.image_ref or item.image_index >= 0):
                warnings.append(f"{item.name}: photo it was read from is no longer in the project; no crop")
            item.crop_ref = ""
            continue
        rel = f"{CROP_DIR}/{idx:02d}_{vocab.slug(item.name or item.semantic_type)[:40]}.png"
        target = project_root / rel
        if target.exists() and not force:
            item.crop_ref = rel
            continue
        try:
            im = opened.get(photo.path)
            if im is None:
                im = Image.open(photo.path).convert("RGB")
                opened[photo.path] = im
            w, h = im.size
            x0, y0, x1, y1 = item.bbox
            px = (x1 - x0) * PAD
            py = (y1 - y0) * PAD
            box = (
                int(max(0.0, x0 - px) * w),
                int(max(0.0, y0 - py) * h),
                int(min(1.0, x1 + px) * w),
                int(min(1.0, y1 + py) * h),
            )
            if box[2] - box[0] < MIN_SIDE or box[3] - box[1] < MIN_SIDE:
                warnings.append(f"{item.name}: crop too small ({box[2] - box[0]}x{box[3] - box[1]} px); skipped")
                item.crop_ref = ""
                continue
            crop = im.crop(box)
            if max(crop.size) > 1024:
                crop.thumbnail((1024, 1024))
            out_dir.mkdir(parents=True, exist_ok=True)
            crop.save(target, format="PNG", optimize=True)
            item.crop_ref = rel
        except Exception as exc:  # one bad photo never sinks the stage
            warnings.append(f"{item.name}: crop failed: {exc}")
            item.crop_ref = ""
    for im in opened.values():
        im.close()
    return warnings

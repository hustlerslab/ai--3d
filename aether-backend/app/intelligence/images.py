"""Reference-image helpers: palette extraction and Gemini encoding."""
from __future__ import annotations

import base64
import io
from collections import Counter
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def palette_from_images(paths: list[str | Path], count: int = 5) -> list[str]:
    """Dominant colours across the reference photos, most frequent first.
    Returns [] when Pillow is missing or no image decodes."""
    if Image is None:
        return []
    tally: Counter[tuple[int, int, int]] = Counter()
    for p in paths:
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((160, 160))
                q = im.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
                pal = q.getpalette()
                for n, idx in q.getcolors() or []:  # (count, palette index)
                    r, g, b = pal[idx * 3 : idx * 3 + 3]
                    # bucket to 16 levels so near-identical shades merge
                    key = (r // 16 * 16 + 8, g // 16 * 16 + 8, b // 16 * 16 + 8)
                    tally[key] += n
        except Exception:
            continue
    if not tally:
        return []
    out: list[str] = []
    for rgb, _ in tally.most_common():
        h = _hex(rgb)
        if h not in out:
            out.append(h)
        if len(out) >= count:
            break
    return out


def encode_for_gemini(path: str | Path, max_side: int = 1024, quality: int = 85) -> Optional[tuple[str, str]]:
    """Downscale + re-encode as JPEG, return (mime, base64). None on failure."""
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def image_size(path: str | Path) -> Optional[tuple[int, int]]:
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None

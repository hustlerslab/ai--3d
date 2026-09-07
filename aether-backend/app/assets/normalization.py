"""Asset normalization (plan §15, Phase 10).

Canonical convention: unit = meter, up = +Y, right = +X, forward = -Z,
pivot = bottom center. glTF already guarantees +Y up, so normalization is
a uniform scale (unit fix), an optional yaw (so the model's front faces -Z),
and a translation that puts the bottom-center on the origin. All three are
expressed as one root-node TRS so the mesh data is untouched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..scene.schema import Vec3
from .gltf import Measurement
from .schema import NormalizationInfo


@dataclass
class NormalizationPlan:
    info: NormalizationInfo
    root_transform: dict
    dimensions: Vec3


def detect_unit(size: tuple[float, float, float]) -> tuple[str, float]:
    """Furniture is 0.1–6 m. Anything far outside was authored in cm or mm."""
    largest = max(size)
    if largest <= 0:
        return "unknown", 1.0
    if largest > 500:
        return "millimeter", 0.001
    if largest > 8:
        return "centimeter", 0.01
    return "meter", 1.0


def _rotate_y(x: float, z: float, yaw: float) -> tuple[float, float]:
    c, s = math.cos(yaw), math.sin(yaw)
    return x * c + z * s, -x * s + z * c


def plan(
    measurement: Measurement,
    expected_dimensions: Optional[Vec3] = None,
    yaw_offset: float = 0.0,
) -> NormalizationPlan:
    size = measurement.size
    lo, hi = measurement.bbox_min, measurement.bbox_max

    if expected_dimensions and max(size) > 0:
        # Match the largest extent so a swapped x/z (yaw) still fits.
        scale = max(expected_dimensions) / max(size)
        unit, strategy = ("meter" if 0.5 < scale < 2 else "unknown"), "expected_dimensions"
    else:
        unit, scale = detect_unit(size)
        strategy = "unit_heuristic"

    # Bounding box after scale + yaw (T * R * S order: scale, rotate, translate).
    corners = [
        (x * scale, y * scale, z * scale)
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]
    rotated = [(*_rotate_y(x, z, yaw_offset), y) for x, y, z in corners]  # (x', z', y)
    xs = [p[0] for p in rotated]
    zs = [p[1] for p in rotated]
    ys = [p[2] for p in rotated]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    min_y, max_y = min(ys), max(ys)

    translation: Vec3 = (
        -(min_x + max_x) / 2,
        -min_y,
        -(min_z + max_z) / 2,
    )
    dimensions: Vec3 = (
        round(max_x - min_x, 4),
        round(max_y - min_y, 4),
        round(max_z - min_z, 4),
    )

    half = yaw_offset / 2
    rotation = [0.0, math.sin(half), 0.0, math.cos(half)] if abs(yaw_offset) > 1e-9 else None
    root_transform = {
        "translation": [round(v, 6) for v in translation],
        "rotation": rotation,
        "scale": [scale, scale, scale] if abs(scale - 1.0) > 1e-12 else None,
    }

    info = NormalizationInfo(
        detected_unit=unit,  # type: ignore[arg-type]
        unit_scale=scale,
        yaw_offset=yaw_offset,
        translation=translation,
        source_size=tuple(round(v, 4) for v in size),  # type: ignore[arg-type]
        strategy=strategy,
    )
    return NormalizationPlan(info=info, root_transform=root_transform, dimensions=dimensions)

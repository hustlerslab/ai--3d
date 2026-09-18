"""Per-plane geometric evidence for "is this candidate actually a room wall?"

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

WHY. Phase 5 handed the geometry engine each object's full 3D extent and it still
scored 51.3% balanced accuracy, because every persistent false wall was an object
flush against a large vertical plane that is NOT a room wall - a kitchen island,
a built-in desk, a bench, a glazed partition. The frozen room fitter admits any
vertical, Manhattan-aligned plane above 6% inlier fraction and 1.5% image extent,
and the contact rule then takes the MINIMUM gap over that set, so a contaminant
that happens to be nearest wins by construction.

The chosen plane's inlier fraction was 0.669 median when the decision was right
and 0.286 when it was wrong. This module asks what ELSE separates the two, using
only geometry the frozen fitter already produced.

HOW THE PIXEL SUPPORT IS RECOVERED. `PlaneFitResult.inlier_mask` is indexed over
the fitter's shrinking `remaining` array, not over pixels, so it cannot be mapped
back to the image directly. Instead the fitter's own accounting is replayed: the
same valid pixels, the same off-floor test (3x threshold from the floor plane),
and each pixel assigned to the FIRST plane in fit order whose distance is under
that plane's threshold. That is what the fitter did, so the counts agree with it.

WHAT IS NOT COMPUTED, AND SAID SO. "Whether the plane terminates at the room
envelope" cannot be computed reliably from a single view and is recorded as
unavailable. Two related quantities that CAN be measured stand in with their own
names, not as a silent substitute: `enclosure_fraction` (how much of the whole
scene lies on the room side of the plane) and `touches_image_edge`.

THE GATE IS DETERMINISTIC AND DECLARED. `WallQualityGate` is a handful of named
floors on those features. The benchmark evaluates a small set of operating
points declared before it runs, plus the exact 0.40 inlier-fraction diagnostic
Phase 5 left behind - which is a pre-existing candidate, not a discovery of this
phase. Nothing here is fitted, trained or optimised against a label.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)

#: Height above the floor below which an inlier counts as "reaching the floor",
#: and above which it counts as "extending upward". Skirting and a chair seat
#: sit under 0.25 m; a wall continues past 1.5 m, a desk or island does not.
FLOOR_BAND_M = 0.25
UPPER_BAND_M = 1.5


@dataclass
class WallFeatures:
    """Everything measurable about one candidate plane, and what could not be."""

    wall_index: int
    # from the frozen fitter, verbatim
    inlier_fraction: float
    extent_fraction: float
    inlier_count_fitter: int
    manhattan_residual_deg: Optional[float]
    residual_median: float
    fitter_uncertain: bool
    fitter_failure_reason: Optional[str]
    normal: tuple
    offset: float
    # recovered pixel support
    inlier_pixels: int
    inlier_pixel_fraction: float          # of all usable scene pixels
    horizontal_extent_frac: float         # pixel bbox width / image width
    vertical_extent_frac: float           # pixel bbox height / image height
    touches_image_edge: bool
    connected_components: int
    largest_component_fraction: float     # of this plane's inliers
    # metric extent
    width_m: float                        # p5-p95 along the in-plane horizontal
    height_m: float                       # p5-p95 of height above floor
    area_m2: float                        # width_m * height_m, a bounding estimate
    min_height_above_floor_m: float       # p5
    max_height_above_floor_m: float       # p95
    reaches_floor: bool                   # min height under FLOOR_BAND_M
    floor_band_fraction: float            # inliers under FLOOR_BAND_M
    upper_band_fraction: float            # inliers over UPPER_BAND_M
    # room relation
    centroid_distance_m: float
    camera_distance_m: float
    enclosure_fraction: Optional[float]   # scene points on the room side
    orientation_ok: bool
    # explicitly unavailable
    terminates_at_room_envelope: str = "unavailable: not reliably computable from one view"

    def as_dict(self) -> dict:
        return asdict(self)


def assign_pixels(pointmap: P.PointMap, room: P.RoomGeometry,
                  exclude: Optional[np.ndarray] = None) -> tuple:
    """Replay the fitter's accounting: which pixel supports which plane.

    Returns (assigned, valid): `assigned` is (H, W) int, -1 for no plane, else
    the wall index; `valid` is the usable-pixel mask the fitter saw.
    """
    valid = pointmap.valid.copy()
    if exclude is not None:
        valid &= ~exclude
    H, W = pointmap.height, pointmap.width
    assigned = np.full((H, W), -1, dtype=np.int32)
    if not room.ok:
        return assigned, valid
    scale = room.scene_scale or pointmap.scene_scale()
    threshold = scale * 0.012
    points = pointmap.points.reshape(-1, 3)

    # The fitter's candidate set: usable pixels that are off the floor.
    dist_floor = room.floor.plane.distance(points).reshape(H, W)
    candidate = valid & (dist_floor > threshold * 3.0)

    # Sequential first-wins assignment, exactly as the fitter removed inliers.
    for k, fit in enumerate(room.walls):
        if fit.plane is None:
            continue
        d = fit.plane.distance(points).reshape(H, W)
        take = candidate & (assigned < 0) & (d < fit.threshold)
        assigned[take] = k
    return assigned, valid


def extract_wall_features(pointmap: P.PointMap, room: P.RoomGeometry,
                          exclude: Optional[np.ndarray] = None) -> list:
    """Replay the fitter's pixel accounting, then measure each plane."""
    if not room.ok:
        return []
    assigned, valid = assign_pixels(pointmap, room, exclude)
    scale = room.scene_scale or pointmap.scene_scale()
    threshold = scale * 0.012
    points = pointmap.points
    H, W = pointmap.height, pointmap.width
    total_usable = int(valid.sum())

    floor = room.floor.plane
    up = np.asarray(room.up, dtype=np.float64)
    up /= (np.linalg.norm(up) or 1.0)
    floor_sign = 1.0 if float(np.dot(floor.normal, up)) > 0 else -1.0

    all_pts = points[valid]
    centre = room_centroid(pointmap)

    out = []
    for k, fit in enumerate(room.walls):
        if fit.plane is None:
            continue
        pix = assigned == k
        n_pix = int(pix.sum())
        pts = points[pix]
        n = np.asarray(fit.plane.normal, dtype=np.float64)

        if n_pix >= 8:
            rows, cols = np.nonzero(pix)
            h_frac = float(cols.max() - cols.min() + 1) / W
            v_frac = float(rows.max() - rows.min() + 1) / H
            edge = bool(cols.min() == 0 or cols.max() == W - 1
                        or rows.min() == 0 or rows.max() == H - 1)
            labels, n_comp = ndimage.label(pix)
            sizes = np.bincount(labels.ravel())[1:] if n_comp else np.array([n_pix])
            largest = float(sizes.max()) / n_pix

            along = np.cross(up, n)
            along /= (np.linalg.norm(along) or 1.0)
            a = pts @ along
            hgt = floor_sign * floor.signed_distance(pts)
            width = float(np.percentile(a, 95) - np.percentile(a, 5))
            h_lo, h_hi = float(np.percentile(hgt, 5)), float(np.percentile(hgt, 95))
            height = h_hi - h_lo
            floor_band = float((hgt < FLOOR_BAND_M).mean())
            upper_band = float((hgt > UPPER_BAND_M).mean())
        else:
            h_frac = v_frac = 0.0
            edge = False
            n_comp, largest = 0, 0.0
            width = height = 0.0
            h_lo = h_hi = float("nan")
            floor_band = upper_band = 0.0

        sign, _src, margin = orient_to_room(fit.plane, centre, scale)
        if sign != 0.0 and all_pts.shape[0]:
            side = sign * fit.plane.signed_distance(all_pts)
            enclosure = float((side > -threshold).mean())
        else:
            enclosure = float("nan")

        out.append(WallFeatures(
            wall_index=k,
            inlier_fraction=round(float(fit.inlier_fraction), 4),
            extent_fraction=round(float(fit.extent_fraction), 4),
            inlier_count_fitter=int(fit.inlier_count),
            manhattan_residual_deg=(round(float(fit.manhattan_residual_deg), 2)
                                    if fit.manhattan_residual_deg is not None else None),
            residual_median=round(float(fit.residual_median), 5),
            fitter_uncertain=bool(fit.uncertain),
            fitter_failure_reason=fit.failure_reason,
            normal=tuple(round(float(v), 5) for v in fit.plane.normal),
            offset=round(float(fit.plane.offset), 5),
            inlier_pixels=n_pix,
            inlier_pixel_fraction=round(n_pix / total_usable, 4) if total_usable else 0.0,
            horizontal_extent_frac=round(h_frac, 4),
            vertical_extent_frac=round(v_frac, 4),
            touches_image_edge=edge,
            connected_components=int(n_comp),
            largest_component_fraction=round(largest, 4),
            width_m=round(width, 3), height_m=round(height, 3),
            area_m2=round(width * height, 3),
            min_height_above_floor_m=round(h_lo, 3),
            max_height_above_floor_m=round(h_hi, 3),
            reaches_floor=bool(h_lo < FLOOR_BAND_M) if n_pix >= 8 else False,
            floor_band_fraction=round(floor_band, 4),
            upper_band_fraction=round(upper_band, 4),
            centroid_distance_m=round(float(margin * scale), 3),
            camera_distance_m=round(abs(float(fit.plane.offset)), 3),
            enclosure_fraction=round(enclosure, 4) if not np.isnan(enclosure) else None,
            orientation_ok=bool(sign != 0.0),
        ))
    return out


@dataclass(frozen=True)
class WallQualityGate:
    """Named floors. A plane must clear every one to count as a room wall.

    `None` disables a floor. Declared per operating point in the benchmark,
    before evaluation; never fitted.
    """

    name: str
    min_inlier_fraction: Optional[float] = None
    min_extent_fraction: Optional[float] = None
    min_height_m: Optional[float] = None
    min_width_m: Optional[float] = None
    min_enclosure_fraction: Optional[float] = None
    min_upper_band_fraction: Optional[float] = None
    #: A plane whose support is concentrated in the bottom FLOOR_BAND_M is not a
    #: wall - it is a plinth, an island front, or a plane fitted where the
    #: floor should have been. Walls in furnished rooms are seen ABOVE the
    #: furniture, so their floor-band fraction is near zero.
    max_floor_band_fraction: Optional[float] = None
    require_reaches_floor: bool = False
    min_largest_component_fraction: Optional[float] = None

    def passes(self, f: WallFeatures) -> tuple:
        """(ok, reasons_failed)"""
        failed = []
        if (self.max_floor_band_fraction is not None
                and f.floor_band_fraction > self.max_floor_band_fraction):
            failed.append(f"floor_band_fraction {f.floor_band_fraction} > "
                          f"{self.max_floor_band_fraction}")
        checks = [
            ("inlier_fraction", self.min_inlier_fraction, f.inlier_fraction),
            ("extent_fraction", self.min_extent_fraction, f.extent_fraction),
            ("height_m", self.min_height_m, f.height_m),
            ("width_m", self.min_width_m, f.width_m),
            ("enclosure_fraction", self.min_enclosure_fraction, f.enclosure_fraction),
            ("upper_band_fraction", self.min_upper_band_fraction, f.upper_band_fraction),
            ("largest_component_fraction", self.min_largest_component_fraction,
             f.largest_component_fraction),
        ]
        for name, floor, value in checks:
            if floor is None:
                continue
            if value is None or value < floor:
                failed.append(f"{name} {value} < {floor}")
        if self.require_reaches_floor and not f.reaches_floor:
            failed.append("does not reach the floor")
        return (not failed), failed


def gated_room(room: P.RoomGeometry, features: list, gate: WallQualityGate) -> tuple:
    """A copy of the room with every wall that fails the gate marked uncertain.

    Indices are preserved, so `planes.wall_contact` can be called on the copy
    unchanged and its `wall_index` still refers to the same plane. The
    production function is not modified; it simply sees fewer candidates.
    """
    by_index = {f.wall_index: f for f in features}
    walls = []
    rejected = {}
    for k, fit in enumerate(room.walls):
        if fit.uncertain or fit.plane is None:
            walls.append(fit)
            continue
        f = by_index.get(k)
        ok, why = gate.passes(f) if f is not None else (False, ["no features"])
        if ok:
            walls.append(fit)
        else:
            walls.append(replace(fit, uncertain=True,
                                 failure_reason="wall-quality gate: " + "; ".join(why)))
            rejected[k] = why
    return (P.RoomGeometry(floor=room.floor, walls=walls, up=room.up,
                           boundary=room.boundary, metric_source=room.metric_source,
                           scene_scale=room.scene_scale, evidence=room.evidence,
                           warnings=room.warnings), rejected)


__all__ = ["WallFeatures", "WallQualityGate", "assign_pixels", "extract_wall_features", "gated_room",
           "FLOOR_BAND_M", "UPPER_BAND_M"]

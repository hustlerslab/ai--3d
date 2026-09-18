"""Floor candidate generation and scoring. The floor is a hypothesis, not a pick.

Research only. `app.spatial.planes` is imported read-only and unmodified; nothing
in `app/` imports this file.

THE DEFECT. `fit_room` finds the floor as the largest horizontal RANSAC plane in
the lower 45% of the image. In a kitchen photographed across an island, that
plane is the COUNTERTOP: Phase 6 measured the camera 0.33 m and 0.63 m above the
fitted "floor" in the two kitchen scenes, against 1.0-1.5 m everywhere else, and
Phase 7 traced two of its three false walls and two of its three misses to those
images. Every height-relative feature in the pipeline is offset by ~0.9 m there.

WHAT THIS DOES INSTEAD. Generate several horizontal-plane candidates over the
whole image, measure each against independent evidence, and pick the best only
when the evidence agrees; otherwise say UNKNOWN. The evidence, all geometric:

    gravity alignment       the normal is close to +Y
    spatial extent          support as a fraction of the scene
    lower-image support     floors are at the bottom of a photograph
    camera height           a camera is 1-2 m above a floor, not 0.3 m
    object contact          floor-standing objects should rest ON it
    below fraction          a floor has (almost) nothing beneath it; a
                            countertop has cabinet fronts and the real floor
    elevation               a substantial horizontal plane sitting 0.3 m+
                            ABOVE another one is a surface on something
    continuity              one connected region, not scattered patches

The "below fraction" is the decisive one and it is the one the current fitter
never looks at. A countertop cannot hide the floor under it from a point cloud.

NOTHING IS TUNED AGAINST LABELS. The weights below were written down once,
from what each piece of evidence physically means, before the benchmark ran.
There is no ground-truth floor in this benchmark; the benchmark scores proxies -
camera height plausibility, object contact, the two eye-verified countertop
failures - and says so.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402

FLOOR_CONFIG = {
    "max_candidates": 5,
    "min_points": 256,
    "threshold_scale": 0.012,              # identical to fit_room
    "normal_vertical_min": 0.55,           # identical to fit_room's floor filter
    "camera_height_plausible_m": (1.0, 2.0),
    "camera_height_soft_m": (0.6, 2.6),
    "contact_band_m": (-0.15, 0.30),
    "below_depth_multiplier": 3.0,         # "below" means > 3x threshold under the plane
    "elevated_ref_extent": 0.03,           # a lower plane needs this much support to count
    "elevated_min_gap_m": 0.30,
    "ambiguity_margin": 0.08,
    "weights": {"gravity": 1.0, "extent": 1.0, "lower_support": 1.0,
                "camera_height": 1.5, "object_contact": 1.5, "continuity": 0.5,
                "below_penalty": 2.0, "elevated_penalty": 1.5},
}


@dataclass
class FloorCandidate:
    index: int
    plane: P.Plane                       # oriented: normal points UP (scene above)
    inlier_count: int
    extent_fraction: float
    gravity_alignment: float
    lower_image_support: float
    camera_height_m: float
    camera_height_score: float
    object_contact_support: Optional[float]
    objects_checked: int
    below_fraction: float
    elevated_above_m: float
    continuity: float
    score: float = 0.0
    category: str = "UNKNOWN"
    evidence: list = field(default_factory=list)


@dataclass
class FloorHypothesis:
    """What the brief asked for: a plane with its score, confidence and rivals."""

    decision: str                        # ROOM_FLOOR | UNKNOWN
    plane: Optional[P.Plane]
    score: Optional[float]
    confidence: float
    category: str
    camera_height_m: Optional[float]
    competing_candidates: list
    provenance: str
    warnings: list = field(default_factory=list)


def _orient_up(plane: P.Plane, pts: np.ndarray) -> P.Plane:
    """Flip the normal so it points UP - along gravity, which in the canonical
    frame is +Y.

    The first version oriented by the side the scene's median point lay on.
    A synthetic test caught the flaw: an elevated surface has most of the scene
    BELOW it, so its normal flipped and the camera read as being under it - the
    plane was rejected as implausible depth by accident instead of by the
    below-fraction evidence built for it. The scene median is used only when
    the normal is nearly horizontal and +Y says nothing.
    """
    n = np.asarray(plane.normal, dtype=np.float64)
    flip = n[1] < 0 if abs(n[1]) > 0.2 else float(np.median(plane.signed_distance(pts))) < 0
    if flip:
        return P.Plane(normal=tuple(-float(v) for v in n), offset=-float(plane.offset))
    return plane


def _clamp01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def generate_floor_candidates(pointmap: P.PointMap, exclude: Optional[np.ndarray],
                              object_masks: list, config: dict = FLOOR_CONFIG) -> list:
    """Sequential horizontal RANSAC over the WHOLE image, then measure each plane."""
    valid = pointmap.valid.copy()
    if exclude is not None:
        valid &= ~exclude
    H, W = pointmap.height, pointmap.width
    all_pts = pointmap.points.reshape(-1, 3)
    scene_pts = pointmap.points[pointmap.valid]
    scale = pointmap.scene_scale()
    if int(valid.sum()) < 512 or scale <= 0:
        return []
    threshold = scale * config["threshold_scale"]

    # index bookkeeping so inlier masks can be mapped back to pixels
    flat_idx = np.flatnonzero(valid.ravel())
    remaining_idx = flat_idx.copy()
    vmin = config["normal_vertical_min"]

    raw = []
    for _k in range(config["max_candidates"]):
        if remaining_idx.shape[0] < config["min_points"]:
            break
        pts = all_pts[remaining_idx]
        fit = P.fit_plane_ransac(pts, threshold=threshold, total_pixels=int(valid.sum()),
                                 normal_filter=lambda n: abs(n[1]) > vmin)
        if not fit.ok or fit.inlier_mask is None:
            break
        pix_idx = remaining_idx[fit.inlier_mask]
        raw.append((fit, pix_idx))
        remaining_idx = remaining_idx[~fit.inlier_mask]

    # object point clouds, computed once
    obj_pts = []
    for m in object_masks:
        um = m & pointmap.valid
        if int(um.sum()) >= 32:
            obj_pts.append(pointmap.points[um])

    cands = []
    for k, (fit, pix_idx) in enumerate(raw):
        plane = _orient_up(fit.plane, scene_pts)
        n = np.asarray(plane.normal)
        pix = np.zeros(H * W, dtype=bool)
        pix[pix_idx] = True
        pix = pix.reshape(H, W)
        rows = np.nonzero(pix)[0]
        lower = float((rows > H * 0.5).mean()) if rows.size else 0.0
        labels, ncomp = ndimage.label(pix)
        sizes = np.bincount(labels.ravel())[1:] if ncomp else np.array([1])
        continuity = float(sizes.max()) / max(1, int(pix.sum()))

        cam_h = float(plane.signed_distance(np.zeros((1, 3)))[0])
        lo, hi = config["camera_height_plausible_m"]
        slo, shi = config["camera_height_soft_m"]
        if lo <= cam_h <= hi:
            cam_score = 1.0
        elif slo <= cam_h < lo:
            cam_score = (cam_h - slo) / (lo - slo)
        elif hi < cam_h <= shi:
            cam_score = (shi - cam_h) / (shi - hi)
        else:
            cam_score = 0.0

        signed_all = plane.signed_distance(scene_pts)
        below = float((signed_all < -config["below_depth_multiplier"] * threshold).mean())

        band_lo, band_hi = config["contact_band_m"]
        contact = None
        if obj_pts:
            hits = 0
            for op in obj_pts:
                h5 = float(np.percentile(plane.signed_distance(op), 5))
                hits += int(band_lo <= h5 <= band_hi)
            contact = hits / len(obj_pts)

        cands.append(FloorCandidate(
            index=k, plane=plane, inlier_count=int(fit.inlier_count),
            extent_fraction=round(float(fit.extent_fraction), 4),
            gravity_alignment=round(float(abs(n[1])), 4),
            lower_image_support=round(lower, 4),
            camera_height_m=round(cam_h, 3), camera_height_score=round(cam_score, 3),
            object_contact_support=(round(contact, 3) if contact is not None else None),
            objects_checked=len(obj_pts),
            below_fraction=round(below, 4), elevated_above_m=0.0,
            continuity=round(continuity, 4)))

    # Elevation relative to the lowest PLAUSIBLE candidate. The first run of this
    # scorer used the lowest substantial plane of any height, and in 13 of 21
    # images that was a plane 3-5 m below the camera with nothing beneath it -
    # MoGe reading depth through a window - which made every real floor look
    # elevated by several metres. A plane that implies a camera height outside
    # the soft range is not a floor in an interior and cannot be the reference.
    slo, shi = config["camera_height_soft_m"]
    substantial = [c for c in cands
                   if c.extent_fraction >= config["elevated_ref_extent"]
                   and slo <= c.camera_height_m <= shi
                   and c.below_fraction <= 0.15]
    if substantial:
        lowest = max(substantial, key=lambda c: c.camera_height_m)
        for c in cands:
            c.elevated_above_m = round(max(0.0, lowest.camera_height_m - c.camera_height_m), 3)

    w = config["weights"]
    wsum = (w["gravity"] + w["extent"] + w["lower_support"] + w["camera_height"]
            + w["object_contact"] + w["continuity"])
    for c in cands:
        contact_score = 0.5 if c.object_contact_support is None else c.object_contact_support
        positive = (w["gravity"] * c.gravity_alignment
                    + w["extent"] * _clamp01(c.extent_fraction / 0.15)
                    + w["lower_support"] * c.lower_image_support
                    + w["camera_height"] * c.camera_height_score
                    + w["object_contact"] * contact_score
                    + w["continuity"] * c.continuity)
        penalty = (w["below_penalty"] * _clamp01(c.below_fraction / 0.30)
                   + w["elevated_penalty"] * _clamp01(c.elevated_above_m / 0.90))
        c.score = round((positive - penalty) / wsum, 4)

        elevated = c.elevated_above_m >= config["elevated_min_gap_m"]
        if not (slo <= c.camera_height_m <= shi):
            # too far above or below the camera for an interior floor: depth
            # read through glass, or a ceiling/outdoor plane. Never a floor,
            # never the elevation reference.
            c.category = "IMPLAUSIBLE_DEPTH"
        elif c.below_fraction > 0.15 or elevated:
            c.category = ("ELEVATED_ARCHITECTURAL_SURFACE"
                          if c.extent_fraction >= 0.10 and c.continuity >= 0.6
                          else "FURNITURE_SURFACE")
        else:
            c.category = "ROOM_FLOOR"
        c.evidence = [f"gravity {c.gravity_alignment}", f"extent {c.extent_fraction}",
                      f"lower {c.lower_image_support}",
                      f"camera {c.camera_height_m} m (score {c.camera_height_score})",
                      f"contact {c.object_contact_support} of {c.objects_checked}",
                      f"below {c.below_fraction}", f"elevated {c.elevated_above_m} m",
                      f"continuity {c.continuity}"]
    return cands


def select_floor(cands: list, config: dict = FLOOR_CONFIG) -> FloorHypothesis:
    """Best ROOM_FLOOR candidate, or UNKNOWN when the evidence does not settle it."""
    ranked = sorted(cands, key=lambda c: c.score, reverse=True)
    summary = [{"index": c.index, "score": c.score, "category": c.category,
                "camera_height_m": c.camera_height_m, "extent": c.extent_fraction,
                "below": c.below_fraction, "contact": c.object_contact_support,
                "elevated_m": c.elevated_above_m} for c in ranked]
    floors = [c for c in ranked if c.category == "ROOM_FLOOR"]
    if not floors:
        return FloorHypothesis("UNKNOWN", None, None, 0.0, "UNKNOWN", None, summary,
                               "no candidate classed ROOM_FLOOR",
                               ["every horizontal plane looks elevated or has scene "
                                "points beneath it"])
    best = floors[0]
    warnings = []
    slo, shi = config["camera_height_soft_m"]
    if not (slo <= best.camera_height_m <= shi):
        return FloorHypothesis("UNKNOWN", None, best.score, 0.0, best.category,
                               best.camera_height_m, summary,
                               "best floor implies an implausible camera height",
                               [f"camera {best.camera_height_m} m above the plane"])
    if len(floors) > 1 and floors[0].score - floors[1].score < config["ambiguity_margin"]:
        return FloorHypothesis("UNKNOWN", None, best.score, 0.3, "UNKNOWN",
                               best.camera_height_m, summary,
                               "two floor candidates within the ambiguity margin",
                               [f"scores {floors[0].score} vs {floors[1].score}"])
    conf = _clamp01(0.5 + 0.5 * best.score)
    if best.object_contact_support is not None and best.object_contact_support < 0.5:
        warnings.append(f"only {best.object_contact_support:.0%} of objects rest on it")
        conf *= 0.7
    return FloorHypothesis("ROOM_FLOOR", best.plane, best.score, round(conf, 3),
                           "ROOM_FLOOR", best.camera_height_m, summary,
                           f"candidate {best.index} of {len(cands)}: " + "; ".join(best.evidence),
                           warnings)


def refit_walls_with_floor(pointmap: P.PointMap, exclude: Optional[np.ndarray],
                           floor: P.Plane, max_walls: int = 4) -> P.RoomGeometry:
    """The frozen fitter's WALL loop, run against a supplied floor.

    A deliberate research-side copy of the wall half of `fit_room` (planes.py):
    same threshold, same off-floor test, same verticality filter, same Manhattan
    snap, same uncertainty rules. It exists so a corrected floor can be pushed
    downstream without touching production. If `fit_room` changes, this must
    follow it; that coupling is the price of not modifying production.
    """
    valid = pointmap.valid.copy()
    if exclude is not None:
        valid &= ~exclude
    total_pixels = int(valid.sum())
    scale = pointmap.scene_scale()
    threshold = scale * 0.012
    flat = pointmap.points[valid]

    up = np.asarray(floor.normal, dtype=np.float64)
    if up[1] < 0:
        up = -up
    inl = floor.distance(flat) < threshold
    floor_fit = P.PlaneFitResult(plane=floor, inlier_count=int(inl.sum()),
                                 total_points=total_pixels,
                                 inlier_fraction=float(inl.mean()) if flat.shape[0] else 0.0,
                                 residual_mean=0.0, residual_median=0.0, residual_p95=0.0,
                                 threshold=threshold, snapped_normal=tuple(up))
    floor_fit.extent_fraction = floor_fit.inlier_fraction

    remaining = flat[floor.distance(flat) > threshold * 3.0]
    walls = []
    for _ in range(max_walls):
        if remaining.shape[0] < 256:
            break
        fit = P.fit_plane_ransac(
            remaining, threshold=threshold, total_pixels=total_pixels,
            normal_filter=lambda n: P.angle_between_deg(n, up) > (
                90.0 - P.WALL_VERTICALITY_TOLERANCE_DEG))
        if not fit.ok:
            break
        snapped, residual = P.snap_manhattan(fit.plane.normal, tuple(up))
        fit.snapped_normal = snapped
        fit.manhattan_residual_deg = residual
        if residual > P.MANHATTAN_SNAP_TOLERANCE_DEG:
            fit.uncertain = True
            fit.failure_reason = f"manhattan residual {residual:.1f} deg"
        if fit.extent_fraction < P.MIN_WALL_EXTENT_FRACTION:
            fit.uncertain = True
            fit.failure_reason = f"extent {fit.extent_fraction:.4f}"
        if fit.inlier_fraction < P.MIN_WALL_INLIER_FRACTION:
            fit.uncertain = True
            fit.failure_reason = f"inlier fraction {fit.inlier_fraction:.3f}"
        walls.append(fit)
        keep = ~fit.inlier_mask if fit.inlier_mask is not None else None
        if keep is None or keep.sum() == remaining.shape[0]:
            break
        remaining = remaining[keep]
    return P.RoomGeometry(floor=floor_fit, walls=walls, up=tuple(up), boundary=None,
                          metric_source=pointmap.metric_source, scene_scale=scale)


__all__ = ["FLOOR_CONFIG", "FloorCandidate", "FloorHypothesis",
           "generate_floor_candidates", "select_floor", "refit_walls_with_floor"]

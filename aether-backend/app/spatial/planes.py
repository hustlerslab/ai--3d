"""Deterministic 3D geometry: point maps, plane fitting, room frames.

NOT IMPORTED BY PRODUCTION. Nothing in the running pipeline calls this module -
verified by grep, the same arrangement `app/vision/` uses. It lives under `app/`
rather than `research/` because it is meant to become production code once the
Phase 1 experiment says whether the approach works; keeping it here means the
experiment and the eventual integration share one implementation instead of
two that drift.

WHY THIS MODULE EXISTS. Phases 1c-1h asked a vision-language model whether a
piece of furniture was against a wall, in six different formulations, and got:
78/78 refusals to abstain, AGAINST 0/30, a wall gate that was a constant
function, and a best-ever false-wall rate of 14.1%. The question was never a
language question. Given a wall plane and an object's extent, "is it against the
wall" is a distance - computable, auditable, and able to say "I cannot tell".

THE THREE RULES THIS MODULE ENFORCES

1. Every fit reports its own trustworthiness. `PlaneFitResult` carries inlier
   count, inlier fraction, residual statistics and the threshold used. A caller
   that wants only the plane has to step past the evidence to get it.
2. `UNKNOWN` is a first-class answer. `WallContact.decision` is a three-valued
   enum, and nothing in here converts UNKNOWN to NO.
3. Nothing is silently metric. `RoomGeometry.metric_source` records where scale
   came from, and it is `UNSCALED` unless something external supplied it.

THE APPROXIMATION YOU MUST KNOW ABOUT. Relative depth models (Depth Anything and
friends) return affine-invariant inverse depth: d = a/Z + b, with a and b
unknown. Unprojecting that with an assumed focal length does NOT give a
Euclidean point cloud - the unknown shift b bends the geometry, and planes stay
planar only if b happens to be zero. Two consequences, both handled rather than
hidden:

  * `unproject` records `metric_source=UNSCALED` and the assumed field of view
    in provenance. Distances it produces are comparable within one scene and
    meaningless between scenes.
  * `plane_residual_in_disparity` fits the same plane in (u, v, disparity)
    space, where a world plane IS exactly an affine function of pixel
    coordinates whatever a and b are. That fit is immune to the ambiguity and
    is the honest cross-check on the unprojected one.

Whether the approximation is good enough for a wall decision is precisely what
the Phase 1 experiment measures. It is not assumed here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Sequence

import numpy as np

Vec3 = tuple[float, float, float]

# ── configuration; every threshold named, none buried in a function body ──

#: Absolute gap below which a piece counts as touching a wall, in metres. Only
#: meaningful when the scene is actually scaled. Chosen to match the existing
#: compiler, which already treats 0.09 m as "flush against a wall"
#: (BOUNDARY_TOLERANCE in app/spatial/validation.py) and allows furniture to sit
#: proud of the skirting.
WALL_CONTACT_DISTANCE_M = 0.12

#: Gap below which a piece counts as touching a wall when the scene is UNSCALED,
#: expressed as a fraction of the room's own extent. A 4 m room and a 12 m room
#: should not share an absolute threshold, and an unscaled reconstruction has no
#: metre to measure against. 0.04 of the room diagonal is roughly 0.12 m in a
#: typical 3 m x 4 m bedroom, so the two thresholds agree where they overlap.
WALL_CONTACT_RELATIVE_TOLERANCE = 0.04

#: A plane supported by fewer than this fraction of the points it was fitted
#: from is not a wall, it is a coincidence. Below this the plane is returned
#: with a failure_reason and callers must treat contact as UNKNOWN.
MIN_WALL_INLIER_FRACTION = 0.06

#: Fraction of an object's pixels that must carry usable depth before its
#: geometry is allowed to decide anything.
MIN_OBJECT_GEOMETRIC_CONFIDENCE = 0.35

#: A candidate wall must cover at least this fraction of the image, otherwise a
#: cushion edge or a picture frame can masquerade as architecture.
MIN_WALL_EXTENT_FRACTION = 0.015

#: How far from perpendicular-to-the-floor a plane may sit and still be called a
#: wall, in degrees.
WALL_VERTICALITY_TOLERANCE_DEG = 25.0

#: Beyond this angular residual a Manhattan snap is a distortion, not a
#: correction, and the plane is marked uncertain instead of forced.
MANHATTAN_SNAP_TOLERANCE_DEG = 20.0

#: Fraction of an object's points that must fall on ONE side of a candidate plane
#: before that plane is accepted as "behind" it rather than "through" it. At 0.85,
#: a plane splitting the object roughly in half is rejected outright.
MIN_ONE_SIDED_FRACTION = 0.85

#: Horizontal field of view assumed when the camera is unknown. Interior
#: photography and our own SD renders sit around here. Recorded in provenance
#: because it is an assumption, not a measurement.
DEFAULT_FOV_DEG = 60.0

#: RANSAC. Seeded, so a rerun on the same input gives the same planes - the
#: determinism Phase 1f/1h showed we cannot get from a model.
RANSAC_ITERATIONS = 400
RANSAC_SEED = 20260915


class MetricSource(str, Enum):
    UNSCALED = "unscaled"
    STATED_DIMS = "stated_dims"
    FLOORPLAN = "floorplan"
    METRIC_MODEL = "metric_model"


class Decision(str, Enum):
    """Three-valued on purpose. UNKNOWN is never folded into NO."""

    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Evidence:
    """Why we believe something, recorded where it is believed."""

    source: Literal["geometry", "detector", "vlm", "vocab_default",
                    "floorplan", "user", "solver"]
    method: str
    confidence: float
    frame: Literal["world", "room", "camera", "image"]
    note: str = ""


@dataclass(frozen=True)
class Plane:
    """n . x + offset = 0, with |n| = 1."""

    normal: Vec3
    offset: float

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        n = np.asarray(self.normal, dtype=np.float64)
        return points @ n + self.offset

    def distance(self, points: np.ndarray) -> np.ndarray:
        return np.abs(self.signed_distance(points))


@dataclass
class PlaneFitResult:
    """A plane AND whether it deserves to be believed.

    Returning a bare plane would let a fit supported by nine stray points look
    exactly like one supported by nine thousand. Every field below exists so a
    caller can refuse the plane.
    """

    plane: Optional[Plane]
    inlier_count: int
    total_points: int
    inlier_fraction: float
    residual_mean: float
    residual_median: float
    residual_p95: float
    threshold: float
    extent_fraction: float = 0.0
    raw_normal: Optional[Vec3] = None
    snapped_normal: Optional[Vec3] = None
    manhattan_residual_deg: Optional[float] = None
    uncertain: bool = False
    failure_reason: Optional[str] = None
    inlier_mask: Optional[np.ndarray] = None

    @property
    def ok(self) -> bool:
        return self.plane is not None and self.failure_reason is None

    def evidence(self, method: str) -> Evidence:
        return Evidence(
            source="geometry", method=method,
            confidence=round(float(self.inlier_fraction), 4), frame="camera",
            note=(f"{self.inlier_count}/{self.total_points} inliers at "
                  f"{self.threshold:.4f}, median residual "
                  f"{self.residual_median:.4f}"
                  + (f", manhattan residual {self.manhattan_residual_deg:.1f} deg"
                     if self.manhattan_residual_deg is not None else "")
                  + (f", UNCERTAIN: {self.failure_reason}" if self.failure_reason else "")))


@dataclass
class PointMap:
    """Per-pixel 3D points in camera space, plus what is trustworthy.

    `points` is (H, W, 3). `valid` is (H, W) bool. `disparity` keeps the model's
    raw output so a caller can work in the affine-invariant space where planes
    are guaranteed to stay planar.
    """

    points: np.ndarray
    valid: np.ndarray
    disparity: np.ndarray
    metric_source: MetricSource
    fov_deg: float
    note: str = ""

    @property
    def height(self) -> int:
        return int(self.points.shape[0])

    @property
    def width(self) -> int:
        return int(self.points.shape[1])

    def valid_points(self) -> np.ndarray:
        return self.points[self.valid]

    def scene_scale(self) -> float:
        """A robust extent for the scene, used as the denominator for relative
        thresholds. The 5-95 percentile spread rather than min-max, because a
        single stray point at infinity should not set the scale of a room."""
        pts = self.valid_points()
        if pts.shape[0] < 16:
            return 0.0
        lo = np.percentile(pts, 5, axis=0)
        hi = np.percentile(pts, 95, axis=0)
        return float(np.linalg.norm(hi - lo))


@dataclass
class RoomGeometry:
    """The reconstructed room frame. Never silently metric."""

    floor: Optional[PlaneFitResult]
    walls: list[PlaneFitResult]
    up: Vec3
    boundary: Optional[list[tuple[float, float]]]
    metric_source: MetricSource
    scene_scale: float
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.floor is not None and self.floor.ok and bool(self.walls)


@dataclass
class WallContact:
    """One deterministic wall-contact decision, with its whole audit trail."""

    decision: Decision
    distance: Optional[float]
    relative_distance: Optional[float]
    wall_index: Optional[int]
    wall_confidence: Optional[float]
    object_geometric_confidence: float
    depth_coverage: float
    metric_source: MetricSource
    threshold_used: Optional[float]
    failure_reason: Optional[str]
    evidence: Optional[Evidence] = None


# ── unprojection ────────────────────────────────────────────────────────

def unproject(disparity: np.ndarray, *, fov_deg: float = DEFAULT_FOV_DEG,
              valid: Optional[np.ndarray] = None,
              metric_source: MetricSource = MetricSource.UNSCALED) -> PointMap:
    """Relative inverse depth -> camera-space points, under a stated assumption.

    The model gives affine-invariant disparity. We invert it to a relative depth
    and unproject through an assumed pinhole camera. Both steps are assumptions
    and both are recorded on the returned PointMap: the result is comparable
    WITHIN one image and meaningless between images.
    """
    disparity = np.asarray(disparity, dtype=np.float64)
    height, width = disparity.shape

    finite = np.isfinite(disparity)
    if valid is not None:
        finite &= valid
    # Disparity at or below zero is "infinitely far" - sky through a window,
    # or the model giving up. Those pixels are dropped, not clamped, because a
    # clamped point lands on a surface that is not there.
    positive = finite & (disparity > 1e-6)

    depth = np.zeros_like(disparity)
    depth[positive] = 1.0 / disparity[positive]

    # Normalise so one scene's numbers are O(1); the affine ambiguity means the
    # absolute value carries no information anyway.
    if positive.any():
        scale = float(np.percentile(depth[positive], 50)) or 1.0
        depth = depth / scale

    focal = 0.5 * width / math.tan(math.radians(fov_deg) * 0.5)
    cx, cy = width * 0.5, height * 0.5
    ys, xs = np.mgrid[0:height, 0:width]

    # Camera looks down -Z; +Y is up in image-space terms once we flip the row
    # axis, which is why (cy - ys) rather than (ys - cy).
    x = (xs - cx) / focal * depth
    y = (cy - ys) / focal * depth
    z = -depth

    points = np.stack([x, y, z], axis=-1)
    points[~positive] = 0.0
    return PointMap(points=points, valid=positive, disparity=disparity,
                    metric_source=metric_source, fov_deg=fov_deg,
                    note=f"unprojected under an assumed {fov_deg:.0f} deg "
                         f"horizontal FoV; depth is relative")


# ── plane fitting ───────────────────────────────────────────────────────

def _plane_from_three(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> Optional[Plane]:
    normal = np.cross(b - a, c - a)
    norm = float(np.linalg.norm(normal))
    if norm < 1e-12:
        return None
    normal = normal / norm
    return Plane(normal=tuple(normal), offset=float(-normal @ a))


def _refit(points: np.ndarray) -> Optional[Plane]:
    """Least-squares plane through the inliers, by SVD. The RANSAC hypothesis
    comes from three points; this is what makes the answer stable."""
    if points.shape[0] < 3:
        return None
    centroid = points.mean(axis=0)
    _u, _s, vh = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vh[-1]
    norm = float(np.linalg.norm(normal))
    if norm < 1e-12:
        return None
    normal = normal / norm
    return Plane(normal=tuple(normal), offset=float(-normal @ centroid))


def fit_plane_ransac(points: np.ndarray, *, threshold: float,
                     iterations: int = RANSAC_ITERATIONS,
                     seed: int = RANSAC_SEED,
                     normal_filter=None,
                     total_pixels: Optional[int] = None) -> PlaneFitResult:
    """Deterministic RANSAC plane fit that reports how much to trust itself.

    `normal_filter` rejects hypotheses whose orientation is wrong for what we
    are looking for - a floor search discards vertical candidates before
    counting inliers, which stops a big wall winning the floor vote.
    """
    points = np.asarray(points, dtype=np.float64)
    total = int(points.shape[0])
    empty = PlaneFitResult(plane=None, inlier_count=0, total_points=total,
                           inlier_fraction=0.0, residual_mean=float("nan"),
                           residual_median=float("nan"), residual_p95=float("nan"),
                           threshold=threshold)
    if total < 32:
        empty.failure_reason = f"only {total} candidate points"
        return empty

    rng = np.random.default_rng(seed)
    best_mask, best_count = None, 0
    for _ in range(iterations):
        idx = rng.choice(total, size=3, replace=False)
        plane = _plane_from_three(points[idx[0]], points[idx[1]], points[idx[2]])
        if plane is None:
            continue
        if normal_filter is not None and not normal_filter(plane.normal):
            continue
        mask = plane.distance(points) < threshold
        count = int(mask.sum())
        if count > best_count:
            best_mask, best_count = mask, count

    if best_mask is None or best_count < 32:
        empty.failure_reason = "no hypothesis reached 32 inliers"
        return empty

    plane = _refit(points[best_mask])
    if plane is None:
        empty.failure_reason = "degenerate inlier set"
        return empty
    # One re-selection against the refitted plane: the SVD moves the plane, and
    # the inlier set should follow it rather than stay with the sample.
    mask = plane.distance(points) < threshold
    if int(mask.sum()) >= 32:
        refit = _refit(points[mask])
        if refit is not None:
            plane, mask = refit, refit.distance(points) < threshold

    residuals = plane.distance(points[mask])
    fraction = float(mask.sum()) / total
    extent = (float(mask.sum()) / total_pixels) if total_pixels else fraction
    return PlaneFitResult(
        plane=plane, inlier_count=int(mask.sum()), total_points=total,
        inlier_fraction=fraction,
        residual_mean=float(residuals.mean()),
        residual_median=float(np.median(residuals)),
        residual_p95=float(np.percentile(residuals, 95)),
        threshold=threshold, extent_fraction=extent,
        raw_normal=plane.normal, inlier_mask=mask)


def angle_between_deg(a: Sequence[float], b: Sequence[float]) -> float:
    av = np.asarray(a, dtype=np.float64)
    bv = np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom < 1e-12:
        return 180.0
    cos = float(np.clip((av @ bv) / denom, -1.0, 1.0))
    return math.degrees(math.acos(abs(cos)))      # planes are sign-agnostic


def snap_manhattan(normal: Vec3, up: Vec3) -> tuple[Vec3, float]:
    """Snap a wall normal to the horizontal plane; report how far it moved.

    The brief is explicit that Manhattan must not be forced blindly, so this
    only removes the component along `up` - which is what "a wall is vertical"
    actually asserts - and hands back the angular residual so the caller can
    decide the plane is uncertain instead of accepting a distortion.
    """
    n = np.asarray(normal, dtype=np.float64)
    u = np.asarray(up, dtype=np.float64)
    u = u / (np.linalg.norm(u) + 1e-12)
    horizontal = n - (n @ u) * u
    norm = float(np.linalg.norm(horizontal))
    if norm < 1e-9:
        return tuple(n), 90.0
    snapped = horizontal / norm
    return tuple(snapped), angle_between_deg(n, snapped)


def plane_residual_in_disparity(disparity: np.ndarray, mask: np.ndarray) -> dict:
    """Fit an affine ramp to disparity over a region, immune to the affine
    ambiguity.

    For a pinhole camera, a world plane appears as an EXACTLY affine function of
    pixel coordinates in inverse-depth space, whatever the unknown scale and
    shift. So this residual says whether a region is really planar without
    inheriting the unprojection's assumptions - the honest cross-check on a fit
    made in guessed-camera space.
    """
    ys, xs = np.nonzero(mask)
    if ys.size < 32:
        return {"points": int(ys.size), "rms": float("nan"), "ok": False}
    d = disparity[ys, xs].astype(np.float64)
    finite = np.isfinite(d)
    if finite.sum() < 32:
        return {"points": int(finite.sum()), "rms": float("nan"), "ok": False}
    ys, xs, d = ys[finite], xs[finite], d[finite]
    design = np.stack([xs, ys, np.ones_like(xs)], axis=1).astype(np.float64)
    coeffs, *_ = np.linalg.lstsq(design, d, rcond=None)
    rms = float(np.sqrt(np.mean((design @ coeffs - d) ** 2)))
    spread = float(np.percentile(d, 95) - np.percentile(d, 5)) or 1.0
    return {"points": int(d.size), "rms": rms, "relative_rms": rms / spread,
            "ok": True}


# ── room frame ──────────────────────────────────────────────────────────

def fit_room(pointmap: PointMap, *, exclude: Optional[np.ndarray] = None,
             max_walls: int = 4,
             up_hint: Optional[Vec3] = None) -> RoomGeometry:
    """Floor first, then walls perpendicular to it. Deterministic throughout.

    `exclude` masks pixels that must not vote - windows and mirrors above all,
    because a depth model reads straight through both and the points it returns
    sit somewhere outside the building.

    `up_hint` is an ABLATION KNOB, not a tuning parameter. Left at None the
    behaviour is bit-identical to Phase 1: the up vector comes from the fitted
    floor's own normal. Supplied, the floor's orientation is taken as given and
    only its offset is fitted, which isolates "is the floor fit the weak link?"
    from "is the point cloud the weak link?". No benchmark run uses it except
    the ablation that says so.
    """
    valid = pointmap.valid.copy()
    if exclude is not None:
        valid &= ~exclude
    total_pixels = int(valid.sum())
    warnings: list[str] = []
    scale = pointmap.scene_scale()
    if total_pixels < 512 or scale <= 0:
        return RoomGeometry(floor=None, walls=[], up=(0.0, 1.0, 0.0),
                            boundary=None, metric_source=pointmap.metric_source,
                            scene_scale=scale,
                            warnings=[f"only {total_pixels} usable pixels"])

    threshold = scale * 0.012
    height = pointmap.height
    flat = pointmap.points[valid]

    # The floor is in the lower part of the frame and its normal is roughly
    # vertical in image terms. Restricting the search there is not a shortcut,
    # it is the Manhattan prior applied where it is safe.
    rows = np.nonzero(valid)[0]
    lower = rows > int(height * 0.45)
    floor_pts = flat[lower]
    if up_hint is not None:
        # Orientation given; fit only the offset. Keeps the same inlier
        # accounting so the reported evidence stays comparable.
        hint = np.asarray(up_hint, dtype=np.float64)
        hint = hint / (np.linalg.norm(hint) + 1e-12)
        floor_fit = fit_plane_ransac(
            floor_pts, threshold=threshold, total_pixels=total_pixels,
            normal_filter=lambda n: angle_between_deg(n, hint) < 12.0)
    else:
        floor_fit = fit_plane_ransac(
            floor_pts, threshold=threshold, total_pixels=total_pixels,
            normal_filter=lambda n: abs(n[1]) > 0.55)
    if not floor_fit.ok:
        return RoomGeometry(floor=floor_fit, walls=[], up=(0.0, 1.0, 0.0),
                            boundary=None, metric_source=pointmap.metric_source,
                            scene_scale=scale,
                            warnings=[floor_fit.failure_reason or "floor fit failed"])

    up = np.asarray(floor_fit.plane.normal, dtype=np.float64)
    if up[1] < 0:
        up = -up                                   # point it at the ceiling
    floor_fit.snapped_normal = tuple(up)

    # Walls: everything not on the floor, fitted one plane at a time and removed.
    off_floor = floor_fit.plane.distance(flat) > threshold * 3.0
    remaining = flat[off_floor]
    walls: list[PlaneFitResult] = []
    for _ in range(max_walls):
        if remaining.shape[0] < 256:
            break
        fit = fit_plane_ransac(
            remaining, threshold=threshold, total_pixels=total_pixels,
            normal_filter=lambda n: angle_between_deg(n, up) > (
                90.0 - WALL_VERTICALITY_TOLERANCE_DEG))
        if not fit.ok:
            break
        snapped, residual = snap_manhattan(fit.plane.normal, tuple(up))
        fit.snapped_normal = snapped
        fit.manhattan_residual_deg = residual
        if residual > MANHATTAN_SNAP_TOLERANCE_DEG:
            fit.uncertain = True
            fit.failure_reason = (f"manhattan residual {residual:.1f} deg exceeds "
                                  f"{MANHATTAN_SNAP_TOLERANCE_DEG:.0f}")
        if fit.extent_fraction < MIN_WALL_EXTENT_FRACTION:
            fit.uncertain = True
            fit.failure_reason = (f"extent {fit.extent_fraction:.4f} below "
                                  f"{MIN_WALL_EXTENT_FRACTION}")
        if fit.inlier_fraction < MIN_WALL_INLIER_FRACTION:
            fit.uncertain = True
            fit.failure_reason = (f"inlier fraction {fit.inlier_fraction:.3f} below "
                                  f"{MIN_WALL_INLIER_FRACTION}")
        walls.append(fit)
        keep = ~fit.inlier_mask if fit.inlier_mask is not None else None
        if keep is None or keep.sum() == remaining.shape[0]:
            break
        remaining = remaining[keep]

    usable = [w for w in walls if not w.uncertain]
    if not usable:
        warnings.append("no wall plane passed the extent/inlier/manhattan checks")

    evidence = [floor_fit.evidence("ransac_floor_plane")]
    evidence += [w.evidence("ransac_wall_plane") for w in walls]
    return RoomGeometry(floor=floor_fit, walls=walls, up=tuple(up), boundary=None,
                        metric_source=pointmap.metric_source, scene_scale=scale,
                        evidence=evidence, warnings=warnings)


# ── the wall question, answered deterministically ───────────────────────

def wall_contact(pointmap: PointMap, room: RoomGeometry, object_mask: np.ndarray,
                 *, distance_m: float = WALL_CONTACT_DISTANCE_M,
                 relative_tolerance: float = WALL_CONTACT_RELATIVE_TOLERANCE,
                 min_confidence: float = MIN_OBJECT_GEOMETRIC_CONFIDENCE) -> WallContact:
    """Is this object against a wall? YES, NO, or honestly UNKNOWN.

    The measurement is the distance from the object's REAR surface to the
    nearest usable wall plane. Rear, not centroid: a three-metre sofa against a
    wall has its centroid a metre and a half away from it, and centroid distance
    would call every large piece free-standing.
    """
    coverage_total = int(object_mask.sum())
    usable = object_mask & pointmap.valid
    coverage = (float(usable.sum()) / coverage_total) if coverage_total else 0.0

    def give_up(reason: str) -> WallContact:
        return WallContact(
            decision=Decision.UNKNOWN, distance=None, relative_distance=None,
            wall_index=None, wall_confidence=None,
            object_geometric_confidence=coverage, depth_coverage=coverage,
            metric_source=pointmap.metric_source, threshold_used=None,
            failure_reason=reason,
            evidence=Evidence(source="geometry", method="wall_contact",
                              confidence=coverage, frame="camera", note=reason))

    if coverage_total == 0:
        return give_up("object mask is empty")
    if coverage < min_confidence:
        return give_up(f"depth coverage {coverage:.2f} below {min_confidence}")
    if not room.ok:
        return give_up("no usable room frame")

    candidates = [(i, w) for i, w in enumerate(room.walls) if not w.uncertain]
    if not candidates:
        return give_up("no wall plane passed its checks")

    points = pointmap.points[usable]
    if points.shape[0] < 32:
        return give_up(f"only {points.shape[0]} object points with depth")

    best_index, best_distance, best_fit = None, float("inf"), None
    rejected_through = 0
    for index, fit in candidates:
        signed = fit.plane.signed_distance(points)
        # A plane that CUTS THROUGH the object is not a wall behind it, it is a
        # plane fitted to the object itself - a sofa back and a counter front are
        # both large planar surfaces and RANSAC finds them happily. Measured on
        # the first run of this experiment: every object reported a wall at
        # distance ~0 because the "wall" was the object. Requiring the object to
        # lie predominantly on ONE side is what tells the two cases apart.
        on_positive = float((signed > 0).mean())
        if MIN_ONE_SIDED_FRACTION > on_positive > (1.0 - MIN_ONE_SIDED_FRACTION):
            rejected_through += 1
            continue
        # The rear surface: the 10th percentile of |distance| is a robust stand-in
        # for "the closest part of the object to this plane" that a handful of
        # noisy depth pixels cannot drag to zero.
        d = float(np.percentile(np.abs(signed), 10))
        if d < best_distance:
            best_index, best_distance, best_fit = index, d, fit

    if best_fit is None:
        return give_up(f"every candidate plane ({rejected_through}) cut through "
                       f"the object rather than sitting behind it")

    scale = room.scene_scale or pointmap.scene_scale()
    relative = (best_distance / scale) if scale > 0 else None

    if pointmap.metric_source is MetricSource.UNSCALED:
        threshold, measured, label = relative_tolerance, relative, "relative"
    else:
        threshold, measured, label = distance_m, best_distance, "metric"

    if measured is None:
        return give_up("scene scale is zero; no threshold applies")

    decision = Decision.YES if measured <= threshold else Decision.NO
    note = (f"{label} gap {measured:.4f} vs threshold {threshold:.4f} to wall "
            f"{best_index} (inlier fraction {best_fit.inlier_fraction:.3f})")
    return WallContact(
        decision=decision, distance=round(best_distance, 5),
        relative_distance=round(relative, 5) if relative is not None else None,
        wall_index=best_index,
        wall_confidence=round(float(best_fit.inlier_fraction), 4),
        object_geometric_confidence=round(coverage, 4),
        depth_coverage=round(coverage, 4), metric_source=pointmap.metric_source,
        threshold_used=threshold, failure_reason=None,
        evidence=Evidence(source="geometry", method="wall_plane_distance",
                          confidence=round(float(best_fit.inlier_fraction), 4),
                          frame="camera", note=note))


def mask_from_box(height: int, width: int, box: Sequence[float]) -> np.ndarray:
    """Pixel mask from an (x1, y1, x2, y2) box, clipped to the image."""
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    mask = np.zeros((height, width), dtype=bool)
    x1, x2 = max(0, min(x1, width)), max(0, min(x2, width))
    y1, y2 = max(0, min(y1, height)), max(0, min(y2, height))
    if x2 > x1 and y2 > y1:
        mask[y1:y2, x1:x2] = True
    return mask


__all__ = [
    "Decision", "Evidence", "MetricSource", "Plane", "PlaneFitResult", "PointMap",
    "RoomGeometry", "WallContact", "angle_between_deg", "fit_plane_ransac",
    "fit_room", "mask_from_box", "plane_residual_in_disparity", "snap_manhattan",
    "unproject", "wall_contact",
    "WALL_CONTACT_DISTANCE_M", "WALL_CONTACT_RELATIVE_TOLERANCE",
    "MIN_WALL_INLIER_FRACTION", "MIN_OBJECT_GEOMETRIC_CONFIDENCE",
    "MIN_WALL_EXTENT_FRACTION", "MIN_ONE_SIDED_FRACTION",
    "WALL_VERTICALITY_TOLERANCE_DEG",
    "MANHATTAN_SNAP_TOLERANCE_DEG", "DEFAULT_FOV_DEG",
]

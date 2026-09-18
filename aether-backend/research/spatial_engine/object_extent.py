"""Catalogue-grounded physical object extent, and wall contact computed from it.

Research only. Reads production modules (`app.spatial.planes`, the asset
registry, the catalogue, the vocab) READ-ONLY; nothing in `app/` imports this.

THE PROBLEM THIS SOLVES, IN ONE LINE. Phase 6 fixed the wall side: with the
enclosure/floor-band gate, every missed positive selects the CORRECT wall and
still reads 0.12-1.01 m from it, because the object side measures the nearest
VISIBLE surface, and a sofa's visible surface is its front. Phase 5 proved that
supplying the object's true depth by hand recovers those cases. This module
supplies the depth from data Allure already holds.

WHERE THE DIMENSIONS COME FROM, IN ORDER, AND HOW MUCH EACH IS TRUSTED.

    registry        measured from the normalised mesh (bottom-centre pivot,
                    metres, -Z forward). Median across records of the type;
                    the spread across records is recorded as uncertainty.
    built-in        the designed catalogue item for the type.
    family default  a generic size for the type's family. Low confidence.
    unknown         the type resolves to nothing. UNKNOWN, never guessed.

Nothing here reads the benchmark label. A sofa is 0.8-0.9 m deep in every
scene; that is what the catalogue knows, and it is all the catalogue knows.

HOW THE EXTENT IS PLACED. Two hypotheses per candidate wall, scored by
geometry, never by the answer:

    depth along the wall normal   (the object's back faces the wall)
    width along the wall normal   (the object's side faces the wall)

For each, the visible points' span along the wall normal is measured (p5-p95,
so a few mask-bleed pixels cannot stretch it). A hypothesis is feasible when
its dimension covers that span; among feasible hypotheses the one whose
dimension is CLOSEST to the visible span wins, because that is the pose most
consistent with what is actually seen. The physical rear extent is then

    rear = min(nearest visible point, farthest visible point - dimension)

which can never be further from the wall than something already visible.

WHAT IS RETURNED WHEN IT CANNOT BE KNOWN. UNKNOWN when no wall survives the
Phase 6 gate, when the type has no metadata, or when the visible span exceeds
every dimension the catalogue offers by more than the tolerance - that last one
means the mask, the geometry or the asset is wrong, and pretending otherwise
would be fabricating hidden geometry.
"""
from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.assets.registry import get_registry                          # noqa: E402
from app.catalog import catalog as CATALOG                            # noqa: E402
from app.intelligence import vocab as V                               # noqa: E402
from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)

# -- configuration, every value named -------------------------------------

#: A hypothesis whose dimension falls short of the visible span by less than
#: this still counts as feasible: p95 of a noisy point cloud overshoots.
SPAN_TOLERANCE_M = 0.10

#: Beyond this much of the visible span unexplained by ANY catalogue dimension,
#: the asset and the observation disagree and the extent is UNKNOWN.
SPAN_UNKNOWN_M = 0.50

#: Trust assigned to each metadata source. Registry dims are measured from a
#: real mesh; built-ins are designed values; family defaults are a shrug.
SOURCE_CONFIDENCE = {"registry": 0.9, "builtin": 0.7, "family_default": 0.4,
                     "unknown": 0.0}

#: Percentiles bounding the visible span along a wall normal.
SPAN_LO, SPAN_HI = 5.0, 95.0


@dataclass
class AssetSpatialMetadata:
    """What the catalogue knows about an object's physical size and mounting."""

    semantic_type: str
    canonical_type: str
    width_m: float
    height_m: float
    depth_m: float
    mount: str                       # floor | wall | ceiling | surface
    placement_class: str             # FLOOR_STANDING | WALL_MOUNTED | ...
    source: str                      # registry | builtin | family_default | unknown
    confidence: float
    n_records: int = 0
    dims_spread_m: float = 0.0       # max-min of depth across registry records
    up_axis: tuple = (0.0, 1.0, 0.0)
    forward_axis: tuple = (0.0, 0.0, -1.0)
    pivot: str = "bottom-centre"
    units: str = "metres"
    notes: list = field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.source != "unknown"


PLACEMENT_CLASS = {"floor": "FLOOR_STANDING", "wall": "WALL_MOUNTED",
                   "ceiling": "CEILING_MOUNTED", "on_surface": "SUPPORTED_ON_SURFACE",
                   "surface": "SUPPORTED_ON_SURFACE"}


def resolve_asset_metadata(object_type: str) -> AssetSpatialMetadata:
    """Registry median -> built-in -> family default -> unknown. Deterministic."""
    canonical = V.canonical_type(object_type, object_type)
    family = V.family_for(canonical, canonical)
    placement = V.placement_for(canonical, canonical)
    pclass = PLACEMENT_CLASS.get(placement, "UNKNOWN")

    records = [r for r in get_registry().list()
               if r.valid and r.semantic_type == canonical]
    if records:
        dims = [tuple(float(v) for v in r.dimensions) for r in records]
        w = statistics.median(d[0] for d in dims)
        h = statistics.median(d[1] for d in dims)
        d = statistics.median(d[2] for d in dims)
        spread = (max(x[2] for x in dims) - min(x[2] for x in dims)) if len(dims) > 1 else 0.0
        mounts = {r.mount for r in records}
        return AssetSpatialMetadata(
            semantic_type=object_type, canonical_type=canonical,
            width_m=round(w, 3), height_m=round(h, 3), depth_m=round(d, 3),
            mount=records[0].mount, placement_class=pclass, source="registry",
            confidence=SOURCE_CONFIDENCE["registry"], n_records=len(records),
            dims_spread_m=round(spread, 3),
            notes=[f"median of {len(records)} registry record(s)"]
                  + ([f"mounts disagree: {sorted(mounts)}"] if len(mounts) > 1 else []))

    builtin = next((i for i in CATALOG.BUILTIN if i.semantic_type == canonical), None)
    if builtin is not None:
        w, h, d = (float(v) for v in builtin.dimensions)
        return AssetSpatialMetadata(
            semantic_type=object_type, canonical_type=canonical,
            width_m=w, height_m=h, depth_m=d, mount=builtin.mount,
            placement_class=pclass, source="builtin",
            confidence=SOURCE_CONFIDENCE["builtin"], n_records=1,
            notes=[f"built-in catalogue item {builtin.asset_id}"])

    fam = V.FAMILY_DEFAULTS.get(family)
    if fam is not None:
        (w, h, d), mount, _shape = fam
        return AssetSpatialMetadata(
            semantic_type=object_type, canonical_type=canonical,
            width_m=w, height_m=h, depth_m=d, mount=mount, placement_class=pclass,
            source="family_default", confidence=SOURCE_CONFIDENCE["family_default"],
            notes=[f"family default for '{family}'; no registry or built-in entry"])

    return AssetSpatialMetadata(
        semantic_type=object_type, canonical_type=canonical, width_m=0.0,
        height_m=0.0, depth_m=0.0, mount="unknown", placement_class="UNKNOWN",
        source="unknown", confidence=0.0, notes=["no metadata of any kind"])


@dataclass
class WallHypothesis:
    """One (wall, orientation) hypothesis and the extent it implies."""

    wall_index: int
    wall_quality: float                 # the gate's enclosure fraction, if known
    wall_inlier_fraction: float
    visible_near_m: float               # p5 of visible points along the normal
    visible_far_m: float                # p95
    visible_span_m: float
    axis_along_normal: str              # "depth" | "width" | "visible_only"
    dimension_m: float
    feasible: bool
    rear_extent_m: float                # may be negative (penetration)
    gap_m: float                        # max(0, rear)
    penetration_m: float


@dataclass
class ObjectExtent:
    """visible / physical / uncertainty, as the brief asks for, plus the decision."""

    case_id: str
    method: str
    metadata: AssetSpatialMetadata
    decision: P.Decision
    distance_m: Optional[float]
    wall_index: Optional[int]
    wall_quality: Optional[float]
    object_extent_confidence: float
    decision_confidence: float
    uncertainty_m: float
    visible_near_m: Optional[float] = None
    visible_far_m: Optional[float] = None
    physical_rear_m: Optional[float] = None
    penetration_m: Optional[float] = None
    orientation: Optional[str] = None
    hypotheses: list = field(default_factory=list)
    failure_reason: Optional[str] = None
    evidence: list = field(default_factory=list)


def extent_wall_contact(case_id: str, pointmap: P.PointMap, gated_room: P.RoomGeometry,
                        mask: np.ndarray, meta: AssetSpatialMetadata, *,
                        wall_quality: Optional[dict] = None,
                        distance_m: float = P.WALL_CONTACT_DISTANCE_M,
                        method: str = "catalogue_wallnormal",
                        orientation_rule: str = "closest") -> ObjectExtent:
    """Physical-extent wall contact against a Phase 6-gated wall set.

    `orientation_rule` is "closest" (pre-declared) or "depth_first" (post hoc).
    """
    def give_up(reason: str, conf: float = 0.0) -> ObjectExtent:
        return ObjectExtent(case_id=case_id, method=method, metadata=meta,
                            decision=P.Decision.UNKNOWN, distance_m=None,
                            wall_index=None, wall_quality=None,
                            object_extent_confidence=conf, decision_confidence=0.0,
                            uncertainty_m=0.0, failure_reason=reason)

    if not meta.known:
        return give_up(f"no asset metadata for '{meta.semantic_type}'")
    if not gated_room.ok:
        return give_up("no usable room frame")
    candidates = [(i, w) for i, w in enumerate(gated_room.walls) if not w.uncertain]
    if not candidates:
        return give_up("no wall survived the wall-quality gate", meta.confidence)

    usable = mask & pointmap.valid
    pts = pointmap.points[usable]
    coverage = float(usable.sum()) / max(1, int(mask.sum()))
    if pts.shape[0] < 32 or coverage < P.MIN_OBJECT_GEOMETRIC_CONFIDENCE:
        return give_up(f"only {pts.shape[0]} object points (coverage {coverage:.2f})",
                       meta.confidence)

    scale = gated_room.scene_scale or pointmap.scene_scale()
    centre = room_centroid(pointmap)
    dims = {"depth": meta.depth_m, "width": meta.width_m}

    hypotheses = []
    for index, fit in candidates:
        sign, _src, _margin = orient_to_room(fit.plane, centre, scale)
        if sign == 0.0:
            continue
        q = sign * fit.plane.signed_distance(pts)
        # The frozen one-sided rule: a plane through the object is not behind it.
        on_pos = float((q > 0).mean())
        if P.MIN_ONE_SIDED_FRACTION > on_pos > (1.0 - P.MIN_ONE_SIDED_FRACTION):
            continue
        near, far = float(np.percentile(q, SPAN_LO)), float(np.percentile(q, SPAN_HI))
        span = far - near
        quality = (wall_quality or {}).get(index, float("nan"))

        feasible = {k: d for k, d in dims.items() if d + SPAN_TOLERANCE_M >= span}
        if feasible:
            if orientation_rule == "depth_first" and "depth" in feasible:
                # The asset's own forward axis: an object backs onto the wall it
                # stands against, so its DEPTH lies along that wall's normal.
                # Used whenever the depth can explain the visible span; width
                # only when it cannot. A physical prior, declared post hoc after
                # the "closest" rule was measured - see the Phase 7 report.
                axis = "depth"
            else:
                # The pose most consistent with what is seen: dimension closest
                # to the visible span. Not the largest (would bias YES), not the
                # smallest (would bias NO). The PRE-DECLARED rule.
                axis = min(feasible, key=lambda k: abs(feasible[k] - span))
            dim = feasible[axis]
            ok = True
        else:
            axis, dim, ok = "visible_only", span, False
        rear = min(near, far - dim)
        hypotheses.append(WallHypothesis(
            wall_index=index, wall_quality=quality,
            wall_inlier_fraction=round(float(fit.inlier_fraction), 4),
            visible_near_m=round(near, 4), visible_far_m=round(far, 4),
            visible_span_m=round(span, 4), axis_along_normal=axis,
            dimension_m=round(dim, 3), feasible=ok,
            rear_extent_m=round(rear, 4), gap_m=round(max(0.0, rear), 4),
            penetration_m=round(max(0.0, -rear), 4)))

    if not hypotheses:
        return give_up("every surviving wall cut through the object", meta.confidence)

    best = min(hypotheses, key=lambda h: h.gap_m)          # the frozen selection rule
    unexplained = best.visible_span_m - max(dims.values())
    if not best.feasible and unexplained > SPAN_UNKNOWN_M:
        return give_up(f"visible span {best.visible_span_m:.2f} m exceeds every "
                       f"catalogue dimension by {unexplained:.2f} m; asset, mask or "
                       f"geometry disagree", meta.confidence * 0.5)

    uncertainty = 0.05 + meta.dims_spread_m / 2.0 + (0.10 if not best.feasible else 0.0)
    margin = abs(best.gap_m - distance_m)
    extent_conf = meta.confidence * (1.0 if best.feasible else 0.6)
    wall_conf = best.wall_quality if not np.isnan(best.wall_quality) else 0.8
    decision_conf = round(min(1.0, extent_conf * wall_conf
                              * (1.0 if margin >= uncertainty else 0.5)), 3)
    decision = P.Decision.YES if best.gap_m <= distance_m else P.Decision.NO

    return ObjectExtent(
        case_id=case_id, method=method, metadata=meta, decision=decision,
        distance_m=best.gap_m, wall_index=best.wall_index,
        wall_quality=(None if np.isnan(best.wall_quality) else best.wall_quality),
        object_extent_confidence=round(extent_conf, 3),
        decision_confidence=decision_conf, uncertainty_m=round(uncertainty, 3),
        visible_near_m=best.visible_near_m, visible_far_m=best.visible_far_m,
        physical_rear_m=best.rear_extent_m, penetration_m=best.penetration_m,
        orientation=best.axis_along_normal, hypotheses=hypotheses,
        evidence=[f"dims from {meta.source} ({meta.canonical_type}): "
                  f"{meta.width_m}x{meta.height_m}x{meta.depth_m} m",
                  f"{best.axis_along_normal} along wall {best.wall_index} normal",
                  f"visible [{best.visible_near_m}, {best.visible_far_m}] m, "
                  f"physical rear {best.rear_extent_m} m"])


def _self_check() -> None:
    """A sofa whose front is 0.9 m from the wall must read ~0 with a 0.9 m depth."""
    h = w = 48
    rng = np.random.default_rng(2)
    pts = np.stack([rng.uniform(-1.0, 1.0, (h, w)), rng.uniform(0.0, 0.8, (h, w)),
                    rng.uniform(-2.15, -2.10, (h, w))], axis=-1)
    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)
    fit = P.PlaneFitResult(plane=plane, inlier_count=1000, total_points=1000,
                           inlier_fraction=0.9, residual_mean=0, residual_median=0,
                           residual_p95=0, threshold=0.01)
    room = P.RoomGeometry(floor=fit, walls=[fit], up=(0.0, 1.0, 0.0), boundary=None,
                          metric_source=P.MetricSource.METRIC_MODEL, scene_scale=4.0)
    pm = P.PointMap(points=pts, valid=np.ones((h, w), bool), disparity=np.ones((h, w)),
                    metric_source=P.MetricSource.METRIC_MODEL, fov_deg=60.0)
    meta = AssetSpatialMetadata("sofa", "sofa", 2.0, 0.8, 0.9, "floor", "FLOOR_STANDING",
                                "builtin", 0.7)
    out = extent_wall_contact("synthetic", pm, room, np.ones((h, w), bool), meta)
    assert out.decision is P.Decision.YES and out.distance_m < 0.06, out
    assert out.orientation == "depth", out.orientation
    far = AssetSpatialMetadata("stool", "stool", 0.4, 0.7, 0.4, "floor", "FLOOR_STANDING",
                               "builtin", 0.7)
    out2 = extent_wall_contact("synthetic2", pm, room, np.ones((h, w), bool), far)
    assert out2.decision is P.Decision.NO and out2.distance_m > 0.4, out2
    print(f"self-check OK: sofa gap={out.distance_m} ({out.orientation}); "
          f"stool gap={out2.distance_m}")


__all__ = ["AssetSpatialMetadata", "ObjectExtent", "WallHypothesis",
           "resolve_asset_metadata", "extent_wall_contact", "SPAN_TOLERANCE_M",
           "SPAN_UNKNOWN_M", "SOURCE_CONFIDENCE"]

if __name__ == "__main__":
    _self_check()

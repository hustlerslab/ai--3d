"""Candidate 3D grounding of a segmented object. Not a placement.

Research only. Reads production modules read-only; nothing in `app/` imports this.

WHAT A GROUNDING IS. Given a mask, metric points, a floor hypothesis, a gated
wall set and the asset's physical size, produce the object's most likely
footprint on its support plane, its position in the room, its depth from the
camera, and ranked orientation hypotheses - each with the evidence it rests on.
The constraint solver (Phase 11) owns the final pose; this owns the candidate.

EVERYTHING HERE IS COMPOSED FROM FROZEN PIECES.

    floor          Phase 8 hypothesis, do-no-harm accepted, else the fitter's
    walls          Phase 6 permissive gate
    extent         Phase 7 catalogue-grounded extent, pre-declared rule
    dimensions     Phase 7 AssetSpatialMetadata
    placement      the vocab's placement class for the type

The only new geometry is the footprint construction. In the floor-standing
case it is a rectangle on the floor plane whose axis along the selected wall's
normal spans [physical rear, physical rear + dimension] - exactly the extent
Phase 7 already computed - and whose axis along the wall is the catalogue's
other dimension, centred on the visible points. Nothing is hand-placed.

PLACEMENT CLASSES ARE EXPLICIT. FLOOR_STANDING is fully implemented.
WALL_MOUNTED computes wall-local coordinates against the selected wall. The
others return UNKNOWN with the reason, because this benchmark contains no
ceiling-mounted or on-surface objects and untested code should not pretend.

UNKNOWN IS RETURNED WHEN: the asset has no metadata; the floor is UNKNOWN; the
mask has too few points; or, for floor-standing objects, the object's lowest
visible points sit far above the floor AND no wall could orient it - a floating
footprint with no orientation is not a grounding.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402
from research.spatial_engine.object_extent import (                   # noqa: E402
    AssetSpatialMetadata, extent_wall_contact)
from research.spatial_engine.rear_extent_wall_contact import (        # noqa: E402
    orient_to_room, room_centroid)

GROUNDING_CONFIG = {
    "contact_band_m": (-0.15, 0.30),     # floor-standing: lowest points vs floor
    "occluded_base_m": 0.30,             # above this the base is probably hidden
    "inside_room_tolerance_m": 0.05,     # footprint corner may sit this far past a wall
    "min_points": 32,
}

PLACEMENT_CLASSES = ["FLOOR_STANDING", "WALL_MOUNTED", "CEILING_MOUNTED",
                     "SUPPORTED_ON_SURFACE", "BUILT_IN", "FREE_HANGING", "UNKNOWN"]


@dataclass
class ObjectGrounding:
    object_id: str
    case_id: str
    placement_class: str
    support: str                                 # floor | wall | surface | unknown
    footprint: Optional[list]                    # 4 corners (x, y, z) on the support plane
    footprint_axes: Optional[dict]               # {"along": [...], "normal": [...]}
    room_position: Optional[tuple]               # footprint centre on the support plane
    depth_m: Optional[float]                     # camera to room_position
    extent_wdh_m: tuple
    orientation_candidates: list
    wall_contact: dict
    floor_contact_m: Optional[float]             # p5 height of visible points above floor
    base_occluded: bool
    confidence: float
    evidence: list = field(default_factory=list)
    failure_reason: Optional[str] = None
    failure_category: str = "NONE"


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _floor_up(floor: P.Plane, pts: np.ndarray) -> np.ndarray:
    """The floor normal pointing into the room (most scene points above it)."""
    n = np.asarray(floor.normal, dtype=np.float64)
    return n if float(np.median(floor.signed_distance(pts))) >= 0 else -n


def _height_above(floor: P.Plane, up: np.ndarray, pts: np.ndarray) -> np.ndarray:
    s = 1.0 if float(np.dot(floor.normal, up)) > 0 else -1.0
    return s * floor.signed_distance(pts)


def _drop_to_plane(p: np.ndarray, plane: P.Plane) -> np.ndarray:
    n = np.asarray(plane.normal, dtype=np.float64)
    return p - float(plane.signed_distance(p.reshape(1, 3))[0]) * n


def ground_object(case_id: str, object_id: str, pointmap: P.PointMap,
                  floor: Optional[P.Plane], gated_room: P.RoomGeometry,
                  wall_quality: dict, mask: np.ndarray, meta: AssetSpatialMetadata,
                  *, floor_confidence: float = 1.0,
                  config: dict = GROUNDING_CONFIG) -> ObjectGrounding:
    def give_up(reason: str, category: str, pclass: str = "UNKNOWN") -> ObjectGrounding:
        return ObjectGrounding(object_id=object_id, case_id=case_id, placement_class=pclass,
                               support="unknown", footprint=None, footprint_axes=None,
                               room_position=None, depth_m=None,
                               extent_wdh_m=(meta.width_m, meta.depth_m, meta.height_m),
                               orientation_candidates=[], wall_contact={"decision": "UNKNOWN"},
                               floor_contact_m=None, base_occluded=False, confidence=0.0,
                               failure_reason=reason, failure_category=category)

    pclass = meta.placement_class if meta.known else "UNKNOWN"
    if not meta.known:
        return give_up(f"no asset metadata for '{meta.semantic_type}'", "ASSET_FAILURE")
    usable = mask & pointmap.valid
    pts = pointmap.points[usable]
    if pts.shape[0] < config["min_points"]:
        return give_up(f"only {pts.shape[0]} object points", "PERCEPTION_FAILURE", pclass)

    if pclass in ("CEILING_MOUNTED", "SUPPORTED_ON_SURFACE", "BUILT_IN", "FREE_HANGING"):
        return give_up(f"{pclass} grounding not implemented: no such object in the "
                       f"benchmark to validate it against", "GROUNDING_FAILURE", pclass)
    if floor is None:
        return give_up("floor hypothesis is UNKNOWN", "FLOOR_FAILURE", pclass)

    scene_pts = pointmap.valid_points()
    up = _floor_up(floor, scene_pts)
    heights = _height_above(floor, up, pts)
    contact = float(np.percentile(heights, 5))
    lo, hi = config["contact_band_m"]
    base_occluded = contact > config["occluded_base_m"]

    # Wall side: the frozen Phase 7 extent against the frozen Phase 6 gate.
    ext = extent_wall_contact(case_id, pointmap, gated_room, mask, meta,
                              wall_quality=wall_quality)
    wall_contact = {"decision": ext.decision.value, "wall_index": ext.wall_index,
                    "distance_m": ext.distance_m, "orientation": ext.orientation,
                    "confidence": ext.decision_confidence}

    evidence = [f"floor contact p5 {contact:.3f} m (band {lo}..{hi})",
                f"dims from {meta.source}: {meta.width_m}x{meta.depth_m}x{meta.height_m} m"]

    if pclass == "WALL_MOUNTED":
        if ext.wall_index is None:
            return give_up("wall-mounted object but no wall survived the gate",
                           "WALL_FAILURE", pclass)
        wall = gated_room.walls[ext.wall_index].plane
        centre = pts.mean(axis=0)
        on_wall = _drop_to_plane(centre, wall)
        n_w = _unit(np.asarray(wall.normal))
        along = _unit(np.cross(up, n_w))
        w, h = meta.width_m, meta.height_m
        base = on_wall - up * (h / 2.0)
        corners = [tuple(np.round(base + a * along + hh * up, 4).tolist())
                   for a in (-w / 2, w / 2) for hh in (0.0, h)]
        height_above_floor = float(_height_above(floor, up, centre.reshape(1, 3))[0])
        return ObjectGrounding(
            object_id=object_id, case_id=case_id, placement_class=pclass, support="wall",
            footprint=corners, footprint_axes={"along": along.round(5).tolist(),
                                               "normal": n_w.round(5).tolist()},
            room_position=tuple(np.round(on_wall, 4).tolist()),
            depth_m=round(float(np.linalg.norm(on_wall)), 3),
            extent_wdh_m=(meta.width_m, meta.depth_m, meta.height_m),
            orientation_candidates=[{"wall_index": ext.wall_index, "axis": "flush", "score": 1.0}],
            wall_contact=wall_contact, floor_contact_m=round(contact, 3), base_occluded=False,
            confidence=round(0.8 * meta.confidence * floor_confidence, 3),
            evidence=evidence + [f"centre {height_above_floor:.2f} m above floor on wall "
                                 f"{ext.wall_index}"])

    # ---- FLOOR_STANDING ------------------------------------------------
    if ext.wall_index is not None and ext.orientation not in (None, "visible_only"):
        wall = gated_room.walls[ext.wall_index].plane
        scale = gated_room.scene_scale or pointmap.scene_scale()
        sign, _s, _m = orient_to_room(wall, room_centroid(pointmap), scale)
        n_w = _unit(np.asarray(wall.normal) * sign)                  # into the room
        n_h = _unit(n_w - np.dot(n_w, up) * up)                       # horizontal
        along = _unit(np.cross(up, n_h))
        dim_n = meta.depth_m if ext.orientation == "depth" else meta.width_m
        dim_a = meta.width_m if ext.orientation == "depth" else meta.depth_m
        q_rear = max(0.0, float(ext.physical_rear_m))
        a = pts @ along
        a_mid = 0.5 * (float(np.percentile(a, 5)) + float(np.percentile(a, 95)))
        # base point on the wall plane, dropped to the floor, with no along-component
        p0 = _drop_to_plane(-float(wall.offset) * np.asarray(wall.normal), floor)
        p0 = p0 - float(p0 @ along) * along
        corners = [tuple(np.round(p0 + aa * along + q * n_h, 4).tolist())
                   for aa in (a_mid - dim_a / 2, a_mid + dim_a / 2)
                   for q in (q_rear, q_rear + dim_n)]
        centre = np.mean(np.array(corners), axis=0)
        alt = "width" if ext.orientation == "depth" else "depth"
        cands = [{"wall_index": h.wall_index, "axis": h.axis_along_normal,
                  "feasible": h.feasible, "gap_m": h.gap_m,
                  "score": round((1.0 if h.feasible else 0.3)
                                 / (1.0 + abs(h.visible_span_m - h.dimension_m)), 3)}
                 for h in ext.hypotheses]
        cands.sort(key=lambda c: c["score"], reverse=True)
        support_ok = lo <= contact <= hi
        conf = (meta.confidence * floor_confidence
                * (ext.wall_quality if ext.wall_quality is not None else 0.8)
                * (1.0 if support_ok else 0.6))
        return ObjectGrounding(
            object_id=object_id, case_id=case_id, placement_class=pclass, support="floor",
            footprint=corners, footprint_axes={"along": along.round(5).tolist(),
                                               "normal": n_h.round(5).tolist()},
            room_position=tuple(np.round(centre, 4).tolist()),
            depth_m=round(float(np.linalg.norm(centre)), 3),
            extent_wdh_m=(meta.width_m, meta.depth_m, meta.height_m),
            orientation_candidates=cands, wall_contact=wall_contact,
            floor_contact_m=round(contact, 3), base_occluded=base_occluded,
            confidence=round(conf, 3),
            evidence=evidence + [f"footprint {dim_a:.2f} m along wall {ext.wall_index}, "
                                 f"{dim_n:.2f} m along its normal from rear {q_rear:.3f} m",
                                 f"alternative orientation: {alt} along normal"])

    # No usable wall: footprint from the visible points only, orientation unknown.
    if base_occluded:
        return give_up("base occluded and no wall to orient against: a floating footprint "
                       "with no orientation is not a grounding", "GROUNDING_FAILURE", pclass)
    centred = pts - pts.mean(axis=0)
    horiz = centred - np.outer(centred @ up, up)
    _u, _sv, vt = np.linalg.svd(horiz, full_matrices=False)
    e1 = _unit(vt[0] - np.dot(vt[0], up) * up)
    e2 = _unit(np.cross(up, e1))
    away = e2 if float(e2 @ pts.mean(axis=0)) > 0 else -e2
    a = pts @ e1
    t = pts @ away
    a_mid = 0.5 * (float(np.percentile(a, 5)) + float(np.percentile(a, 95)))
    t_near = float(np.percentile(t, 5))
    dim_a, dim_t = max(meta.width_m, meta.depth_m), min(meta.width_m, meta.depth_m)
    base = _drop_to_plane(pts.mean(axis=0), floor)
    base = base - float(base @ e1) * e1 - float(base @ away) * away
    corners = [tuple(np.round(base + aa * e1 + tt * away, 4).tolist())
               for aa in (a_mid - dim_a / 2, a_mid + dim_a / 2)
               for tt in (t_near, t_near + dim_t)]
    centre = np.mean(np.array(corners), axis=0)
    return ObjectGrounding(
        object_id=object_id, case_id=case_id, placement_class=pclass, support="floor",
        footprint=corners, footprint_axes={"along": e1.round(5).tolist(),
                                           "normal": away.round(5).tolist()},
        room_position=tuple(np.round(centre, 4).tolist()),
        depth_m=round(float(np.linalg.norm(centre)), 3),
        extent_wdh_m=(meta.width_m, meta.depth_m, meta.height_m),
        orientation_candidates=[{"wall_index": None, "axis": "principal", "feasible": None,
                                 "score": 0.3}],
        wall_contact=wall_contact, floor_contact_m=round(contact, 3),
        base_occluded=base_occluded,
        confidence=round(0.4 * meta.confidence * floor_confidence, 3),
        evidence=evidence + ["no wall survived the gate: footprint anchored to the visible "
                             "near edge, extended away from the camera; orientation UNKNOWN"])


__all__ = ["ObjectGrounding", "ground_object", "GROUNDING_CONFIG", "PLACEMENT_CLASSES"]

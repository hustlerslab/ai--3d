"""The bridge: GroundingHypothesis[] + reconstructed room geometry -> Scene.

Research only. Constructs real `app.scene.schema` objects and calls real
`app.catalog.catalog` asset selection - both READ, neither modified. Nothing
downstream of this module's output is touched: `validate_scene`,
`build_manifest` and Blender run completely unmodified on what this produces.
See architecture_decision.md for why this shape, and for what is deliberately
NOT emitted here (most relation predicates, any second support level, any
learned repair).

THE ONE FABRICATED SHAPE, AND WHY IT CANNOT BE AVOIDED. `Room.boundary` must be
a closed polygon for `validate_scene`'s room-bounds check to run at all; a
single photograph almost never shows all four walls of a room. The boundary
built here is a padded convex hull of the floor's own valid 3D points projected
to the XZ plane - evidence-derived, never invented from nothing - marked with
an explicit low `Room.confidence` naming the approximation. It is padded
OUTWARD only, so it can make the room-bounds check under-strict, never falsely
flag a real object.

ROTATION IS DERIVED THEN VERIFIED, NOT ASSUMED. Two yaw values reproduce any
given footprint rectangle (180 degrees apart - a rectangle's own symmetry, not
a bug). `_resolve_yaw` computes both, rebuilds the footprint with production's
OWN `object_footprint()`-equivalent `footprint_corners()`, and keeps whichever
reproduces the grounding's measured corners more closely. The residual is
recorded on every object as `footprint_reconstruction_error_m` - the testable
transform §10 asks for, not a formula trusted on inspection.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.catalog import catalog as CATALOG                             # noqa: E402
from app.scene.schema import Confidence, ObjectSource, Room, Scene, SceneObject, Wall  # noqa: E402
from app.spatial.geometry import footprint_corners, point_inside_polygon  # noqa: E402
from research.spatial_architecture.grounding_contract import (         # noqa: E402
    GroundingHypothesis)

# -- configuration, every value named -------------------------------------

#: How far the fabricated room boundary is padded beyond the measured floor
#: extent, so it can only be too generous, never too tight.
ROOM_PADDING_M = 1.5

#: A `GroundingHypothesis` this far below overall_confidence is still placed
#: (never silently dropped) but flagged for the caller's own decision.
LOW_CONFIDENCE_FLAG = 0.25


@dataclass
class WallEvidence:
    """What the bridge needs about one gated wall plane. Built by the caller
    from Phase 6/8 output; this module adds no wall-fitting logic of its own."""

    index: int
    normal: tuple
    offset: float
    width_m: float
    enclosure_fraction: Optional[float]
    #: +1 if `normal` already points from the wall INTO the room, -1 if it
    #: points outward. A wall's fitted plane is its visible INNER face; the
    #: rectangle built for collision must sit BEHIND that face (away from the
    #: room), by half its thickness, or it clips every object correctly
    #: placed flush against it. Computed by the caller (it already has the
    #: room centroid this needs); defaults to +1 (no offset) if the caller
    #: could not establish it, which is the old, clip-prone behaviour, not a
    #: silent worse one.
    into_room_sign: float = 1.0


@dataclass
class BridgeResult:
    scene: Scene
    relations: list
    room_confidence: Confidence
    room_boundary_source: str
    objects_placed: int
    objects_skipped: int
    skipped_reasons: dict
    footprint_reconstruction_error_m: dict   # object_id -> metres
    warnings: list = field(default_factory=list)


def _convex_hull(points: list) -> list:
    """Andrew's monotone chain. Deterministic, no external dependency."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _pad_hull(hull: list, pad_m: float) -> list:
    """Push every hull vertex outward from the centroid by `pad_m`."""
    cx = sum(p[0] for p in hull) / len(hull)
    cz = sum(p[1] for p in hull) / len(hull)
    out = []
    for x, z in hull:
        dx, dz = x - cx, z - cz
        n = math.hypot(dx, dz) or 1.0
        out.append((x + dx / n * pad_m, z + dz / n * pad_m))
    return out


def build_room_boundary(floor_points_xz: list) -> tuple:
    """A padded convex hull of the floor's own measured extent. The one
    fabricated shape in this module; see the module docstring."""
    if len(floor_points_xz) < 8:
        # too little floor to hull honestly - fall back to a generous square
        # around whatever points exist, still evidence-anchored, maximally
        # padded, and flagged at the lowest confidence this module ever emits.
        cx = sum(p[0] for p in floor_points_xz) / max(1, len(floor_points_xz))
        cz = sum(p[1] for p in floor_points_xz) / max(1, len(floor_points_xz))
        r = ROOM_PADDING_M * 3
        boundary = [(cx - r, cz - r), (cx + r, cz - r), (cx + r, cz + r), (cx - r, cz + r)]
        return boundary, Confidence(value=0.1, source="reconstructed_partial_view_sparse")
    hull = _convex_hull(floor_points_xz)
    boundary = _pad_hull(hull, ROOM_PADDING_M)
    return boundary, Confidence(value=0.4, source="reconstructed_partial_view")


def _resolve_yaw(normal: tuple, dim_along: float, dim_normal: float,
                 anchor_xz: tuple, target_corners_xz: list) -> tuple:
    """Two yaws reproduce a rectangle's footprint (180 deg apart). Try both
    against production's OWN `footprint_corners()`, keep the closer one, and
    return the residual so the caller can report it rather than trust it."""
    forward = (normal[0], normal[2])
    n = math.hypot(*forward) or 1.0
    forward = (forward[0] / n, forward[1] / n)
    yaw0 = math.atan2(-forward[0], -forward[1])

    def mean_corner_dist(corners: list) -> float:
        # nearest-neighbour match, not index-order match: the two corner sets
        # were built independently and may start at different vertices.
        total = 0.0
        for tc in target_corners_xz:
            total += min(math.hypot(tc[0] - c[0], tc[1] - c[1]) for c in corners)
        return total / len(target_corners_xz)

    d0 = mean_corner_dist(footprint_corners(anchor_xz, dim_along, dim_normal, yaw0))
    yaw1 = yaw0 + math.pi
    d1 = mean_corner_dist(footprint_corners(anchor_xz, dim_along, dim_normal, yaw1))
    return (yaw0, d0) if d0 <= d1 else (yaw1, d1)


def _select_asset(canonical_type: str, extent_wdh_m: tuple) -> tuple:
    """Reuses production's OWN dimension-fit ranking. No new selection logic."""
    hits = CATALOG.search(query=canonical_type, target_dimensions=extent_wdh_m,
                          require_model=True)
    if hits:
        return hits[0].asset_id, "local_asset"
    builtin = CATALOG.find_by_semantic(canonical_type)
    if builtin is not None:
        return builtin.asset_id, "procedural"
    return None, "procedural"


def grounding_to_scene(image_key: str, project_id: str, room_type: str,
                       floor_points_xz: list, walls: list,
                       hypotheses: list) -> BridgeResult:
    """The bridge. `walls` is list[WallEvidence]; `hypotheses` is
    list[GroundingHypothesis], all from the SAME image."""
    boundary, room_conf = build_room_boundary(floor_points_xz)
    room = Room(name=room_type.replace("_", " ").title(), type=room_type,
               boundary=boundary, confidence=room_conf,
               features=["reconstructed from a single photograph"])

    scene_walls = []
    wall_thickness = 0.15                          # Wall's own production default
    for w in walls:
        n = w.normal
        along = (-n[2], n[0])                     # perpendicular to (nx, nz) in XZ
        mag = math.hypot(*along) or 1.0
        along = (along[0] / mag, along[1] / mag)
        p0 = (-w.offset * n[0], -w.offset * n[2])  # the fitted plane's own point: its INNER face
        # Push the centerline OUTWARD (away from the room) by half the wall's
        # thickness, so the rectangle `wall_rectangle` builds from this
        # centerline has its INNER face at the measured plane, not straddling
        # it - see WallEvidence.into_room_sign.
        push = -w.into_room_sign * (wall_thickness / 2.0)
        p0 = (p0[0] + n[0] * push, p0[1] + n[2] * push)
        half = max(0.3, w.width_m / 2.0)
        scene_walls.append(Wall(
            wall_id=f"wall_{w.index}", thickness=wall_thickness,
            start=(p0[0] - along[0] * half, p0[1] - along[1] * half),
            end=(p0[0] + along[0] * half, p0[1] + along[1] * half)))

    scene = Scene(project_id=project_id, name=f"photo:{Path(image_key).stem}",
                  rooms=[room], walls=scene_walls)

    relations = []
    placed = skipped = 0
    skip_reasons: dict = {}
    residuals: dict = {}
    warnings: list = []

    for h in hypotheses:
        if not h.grounded or h.placement_class != "FLOOR_STANDING":
            skipped += 1
            reason = h.failure_reason or f"placement_class={h.placement_class}"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        normal = tuple(h.footprint_axes.get("normal", (0.0, 0.0, 1.0)))
        orient = h.best_orientation
        axis = orient.axis if orient else "principal"
        dim_w, dim_h, dim_d = h.extent_wdh_m
        # dims[0] (local x, "along") vs dims[2] (local z, "normal") match the
        # SAME axis assignment Phase 7 used when it built this footprint.
        dim_along, dim_normal = (dim_w, dim_d) if axis in ("depth", "principal") else (dim_d, dim_w)

        target_xz = [(c[0], c[2]) for c in h.footprint]
        cx = sum(p[0] for p in target_xz) / 4.0
        cz = sum(p[1] for p in target_xz) / 4.0
        yaw, residual = _resolve_yaw(normal, dim_along, dim_normal, (cx, cz), target_xz)
        residuals[h.object_id] = round(residual, 4)
        if residual > 0.15:
            warnings.append(f"{h.object_id}: footprint reconstruction residual "
                            f"{residual:.3f} m exceeds 0.15 m")

        floor_y = min(c[1] for c in h.footprint)     # bottom-center pivot height
        asset_id, strategy = _select_asset(h.canonical_type, h.extent_wdh_m)

        obj = SceneObject(
            object_id=f"obj_{h.case_id}",
            semantic_type=h.canonical_type, asset_id=asset_id, room_id=room.room_id,
            position=(cx, floor_y, cz), rotation_y=round(yaw, 6),
            dimensions=(round(dim_along, 4), round(dim_h, 4), round(dim_normal, 4)),
            source=ObjectSource.CATALOG, source_strategy=strategy, mount="floor",
            confidence=Confidence(value=h.overall_confidence, source=h.weakest_channel),
            plan_key=h.case_id, name=h.semantic_type)

        if not point_inside_polygon((cx, cz), boundary, 0.2):
            skipped += 1
            skip_reasons["room_position_outside_padded_boundary"] = (
                skip_reasons.get("room_position_outside_padded_boundary", 0) + 1)
            continue

        scene.objects.append(obj)
        placed += 1

        if h.wall_decision == "YES" and h.wall_index is not None:
            conf = ("HIGH" if h.wall_confidence >= 0.85
                    else "MEDIUM" if h.wall_confidence >= 0.5 else "LOW")
            relations.append({
                "subject_id": obj.object_id, "predicate": "AGAINST_WALL",
                "object_id": f"wall_{h.wall_index}", "confidence": conf,
                "source": "geometry", "frame": "floor_plan",
                "note": f"wall gap {h.wall_distance_m} m, wall_confidence "
                        f"{h.wall_confidence}"})

    return BridgeResult(scene=scene, relations=relations, room_confidence=room_conf,
                        room_boundary_source=room_conf.source, objects_placed=placed,
                        objects_skipped=skipped, skipped_reasons=skip_reasons,
                        footprint_reconstruction_error_m=residuals, warnings=warnings)


__all__ = ["grounding_to_scene", "build_room_boundary", "WallEvidence", "BridgeResult",
           "ROOM_PADDING_M", "LOW_CONFIDENCE_FLAG"]

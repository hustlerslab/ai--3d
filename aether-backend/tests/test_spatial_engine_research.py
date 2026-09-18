"""Deterministic checks for the spatial-engine research modules (Phases 4-9).

No models, no GPU, no files: every scene here is a synthetic point map whose
right answer is known by construction. These guard the sign conventions and
the UNKNOWN paths - the two things an aggregate benchmark number would never
reveal if they went backwards.
"""
from __future__ import annotations

import numpy as np

from app.spatial import planes as P
from research.spatial_engine.floor_candidates import (
    generate_floor_candidates, select_floor)
from research.spatial_engine.object_extent import (
    AssetSpatialMetadata, extent_wall_contact)
from research.spatial_engine.object_grounding import ground_object
from research.spatial_engine.rear_extent_wall_contact import (
    REAR_EXTENT_PERCENTILE, orient_to_room)
from research.spatial_engine.wall_quality import WallFeatures, WallQualityGate

# Canonical frame: +X right, +Y up, -Z forward, camera at the origin.
CAM_H = 1.4                      # camera height above the synthetic floor
FLOOR_Y = -CAM_H
WALL_Z = -6.0


def _pointmap(points: np.ndarray) -> P.PointMap:
    h, w = points.shape[:2]
    return P.PointMap(points=points, valid=np.ones((h, w), dtype=bool),
                      disparity=np.ones((h, w)), metric_source=P.MetricSource.METRIC_MODEL,
                      fov_deg=60.0)


def _grid(n: int, xs, ys, zs, rng) -> np.ndarray:
    """n*n points uniformly inside the box; a constant range makes a plane."""
    return np.stack([rng.uniform(*xs, (n, n)), rng.uniform(*ys, (n, n)),
                     rng.uniform(*zs, (n, n))], axis=-1)


def _room_scene(with_countertop: bool = False, rng=None) -> P.PointMap:
    """Floor, back wall, and optionally a countertop with a cabinet front under it."""
    rng = rng or np.random.default_rng(0)
    floor = _grid(40, (-3, 3), (FLOOR_Y, FLOOR_Y + 0.002), (WALL_Z, -1.0), rng)
    wall = _grid(40, (-3, 3), (FLOOR_Y, 1.0), (WALL_Z, WALL_Z + 0.002), rng)
    parts = [floor, wall]
    if with_countertop:
        top = _grid(40, (-1, 1), (-0.5, -0.498), (-3.0, -2.0), rng)
        front = _grid(40, (-1, 1), (FLOOR_Y, -0.5), (-2.0, -1.998), rng)
        parts += [top, front]
    return _pointmap(np.concatenate(parts, axis=0))


def _wall_fit() -> P.PlaneFitResult:
    return P.PlaneFitResult(plane=P.Plane(normal=(0.0, 0.0, 1.0), offset=-WALL_Z),
                            inlier_count=1000, total_points=1000, inlier_fraction=0.9,
                            residual_mean=0.0, residual_median=0.0, residual_p95=0.0,
                            threshold=0.01)


def _room_geometry(pointmap: P.PointMap) -> P.RoomGeometry:
    floor = P.PlaneFitResult(plane=P.Plane(normal=(0.0, 1.0, 0.0), offset=-FLOOR_Y),
                             inlier_count=1000, total_points=1000, inlier_fraction=0.5,
                             residual_mean=0.0, residual_median=0.0, residual_p95=0.0,
                             threshold=0.01)
    return P.RoomGeometry(floor=floor, walls=[_wall_fit()], up=(0.0, 1.0, 0.0),
                          boundary=None, metric_source=P.MetricSource.METRIC_MODEL,
                          scene_scale=pointmap.scene_scale())


SOFA = AssetSpatialMetadata("sofa", "sofa", 2.0, 0.8, 0.9, "floor", "FLOOR_STANDING",
                            "builtin", 0.7)
UNKNOWN_ASSET = AssetSpatialMetadata("thing", "thing", 0.0, 0.0, 0.0, "unknown", "UNKNOWN",
                                     "unknown", 0.0)


def _sofa_points(rng) -> np.ndarray:
    """The visible FRONT of a 0.9 m deep sofa whose back touches the wall."""
    return _grid(40, (-1, 1), (FLOOR_Y, FLOOR_Y + 0.8), (WALL_Z + 0.85, WALL_Z + 0.9), rng)


# -- wall normal orientation and rear extent (Phase 4) -----------------------

def test_orientation_points_into_the_room():
    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)          # z = -3
    sign, source, _ = orient_to_room(plane, np.array([0.0, 0.5, -1.5]), 4.0)
    assert sign == 1.0 and "centroid" in source


def test_orientation_is_unknown_when_centroid_lies_on_the_plane():
    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)
    sign, source, _ = orient_to_room(plane, np.array([0.0, 0.5, -3.0]), 4.0)
    assert sign == 0.0 and "ambiguous" in source


def test_signed_projection_expresses_wall_penetration_and_abs_cannot():
    plane = P.Plane(normal=(0.0, 0.0, 1.0), offset=3.0)
    pts = np.array([[0.0, 0.0, z] for z in np.linspace(-3.5, -3.0, 50)])  # behind the wall
    assert np.percentile(plane.signed_distance(pts), REAR_EXTENT_PERCENTILE) < 0.0
    assert np.percentile(np.abs(plane.signed_distance(pts)), REAR_EXTENT_PERCENTILE) > 0.0


# -- wall quality gate (Phase 6) ---------------------------------------------

def _features(enclosure: float, floor_band: float) -> WallFeatures:
    return WallFeatures(wall_index=0, inlier_fraction=0.3, extent_fraction=0.1,
                        inlier_count_fitter=100, manhattan_residual_deg=1.0,
                        residual_median=0.01, fitter_uncertain=False, fitter_failure_reason=None,
                        normal=(0.0, 0.0, 1.0), offset=6.0, inlier_pixels=100,
                        inlier_pixel_fraction=0.1, horizontal_extent_frac=0.5,
                        vertical_extent_frac=0.5, touches_image_edge=False,
                        connected_components=1, largest_component_fraction=1.0,
                        width_m=3.0, height_m=2.0, area_m2=6.0, min_height_above_floor_m=0.5,
                        max_height_above_floor_m=2.5, reaches_floor=False,
                        floor_band_fraction=floor_band, upper_band_fraction=0.4,
                        centroid_distance_m=2.0, camera_distance_m=4.0,
                        enclosure_fraction=enclosure, orientation_ok=True)


PERMISSIVE = WallQualityGate(name="phase6_permissive", min_enclosure_fraction=0.80,
                             max_floor_band_fraction=0.75)


def test_gate_passes_a_room_bounding_wall():
    ok, why = PERMISSIVE.passes(_features(enclosure=0.98, floor_band=0.0))
    assert ok and why == []


def test_gate_rejects_a_partition_that_does_not_enclose_the_room():
    ok, why = PERMISSIVE.passes(_features(enclosure=0.60, floor_band=0.0))
    assert not ok and any("enclosure" in w for w in why)


def test_gate_rejects_an_island_front_whose_support_sits_at_floor_level():
    ok, why = PERMISSIVE.passes(_features(enclosure=0.92, floor_band=0.9))
    assert not ok and any("floor_band" in w for w in why)


# -- floor selection (Phase 8) -----------------------------------------------

def test_floor_is_chosen_over_a_countertop_with_scene_beneath_it():
    pm = _room_scene(with_countertop=True)
    cands = generate_floor_candidates(pm, None, [])
    hyp = select_floor(cands)
    assert hyp.decision == "ROOM_FLOOR"
    assert abs(hyp.camera_height_m - CAM_H) < 0.1
    # the countertop candidate absorbs part of the cabinet front, so its fitted
    # height sits within ~0.15 m of the true 0.5 m; what matters is that it is
    # never classed a floor and that its normal points UP (camera above it)
    counters = [c for c in cands if 0.3 < c.camera_height_m < 0.8]
    assert counters and all(c.category != "ROOM_FLOOR" for c in counters)
    assert all(c.below_fraction > 0.15 for c in counters)


def test_floor_is_unknown_when_no_candidate_implies_a_plausible_camera_height():
    rng = np.random.default_rng(1)
    far = _grid(40, (-3, 3), (-5.0, -4.998), (WALL_Z, -1.0), rng)     # 5 m below the camera
    hyp = select_floor(generate_floor_candidates(_pointmap(far), None, []))
    assert hyp.decision == "UNKNOWN"


# -- catalogue extent (Phase 7) ----------------------------------------------

def test_extent_recovers_an_occluded_rear_face_and_keeps_a_stool_off_the_wall():
    pts = _sofa_points(np.random.default_rng(2))
    pm = _pointmap(pts)
    room = _room_geometry(pm)
    mask = np.ones(pts.shape[:2], dtype=bool)
    out = extent_wall_contact("sofa", pm, room, mask, SOFA)
    assert out.decision is P.Decision.YES and out.distance_m < 0.06
    assert out.orientation == "depth"
    stool = AssetSpatialMetadata("stool", "stool", 0.4, 0.7, 0.4, "floor", "FLOOR_STANDING",
                                 "builtin", 0.7)
    out2 = extent_wall_contact("stool", pm, room, mask, stool)
    assert out2.decision is P.Decision.NO and out2.distance_m > 0.4


def test_extent_is_unknown_without_metadata_or_walls():
    pts = _sofa_points(np.random.default_rng(3))
    pm = _pointmap(pts)
    room = _room_geometry(pm)
    mask = np.ones(pts.shape[:2], dtype=bool)
    assert extent_wall_contact("x", pm, room, mask, UNKNOWN_ASSET).decision is P.Decision.UNKNOWN
    no_walls = P.RoomGeometry(floor=room.floor, walls=[], up=room.up, boundary=None,
                              metric_source=room.metric_source, scene_scale=room.scene_scale)
    assert extent_wall_contact("x", pm, no_walls, mask, SOFA).decision is P.Decision.UNKNOWN


# -- grounding (Phase 9) -----------------------------------------------------

def test_grounding_footprint_covers_its_evidence_and_stays_inside_the_room():
    pts = _sofa_points(np.random.default_rng(4))
    pm = _pointmap(pts)
    room = _room_geometry(pm)
    mask = np.ones(pts.shape[:2], dtype=bool)
    g = ground_object("c", "o", pm, room.floor.plane, room, {0: 0.98}, mask, SOFA)
    assert g.placement_class == "FLOOR_STANDING" and g.support == "floor"
    assert g.footprint is not None and len(g.footprint) == 4
    corners = np.array(g.footprint)
    assert (corners[:, 2] >= WALL_Z - 0.05).all()          # on the room side of the wall
    assert np.allclose(corners[:, 1], FLOOR_Y, atol=0.05)   # on the floor
    zs = pts[..., 2].ravel()                                # covers the visible slab
    assert corners[:, 2].min() - 0.05 <= zs.min() and zs.max() <= corners[:, 2].max() + 0.05
    assert g.wall_contact["decision"] == "YES"


def test_grounding_is_unknown_without_a_floor_or_metadata():
    pts = _sofa_points(np.random.default_rng(5))
    pm = _pointmap(pts)
    room = _room_geometry(pm)
    mask = np.ones(pts.shape[:2], dtype=bool)
    g = ground_object("c", "o", pm, None, room, {}, mask, SOFA)
    assert g.footprint is None and g.failure_category == "FLOOR_FAILURE"
    g2 = ground_object("c", "o", pm, room.floor.plane, room, {}, mask, UNKNOWN_ASSET)
    assert g2.footprint is None and g2.failure_category == "ASSET_FAILURE"

"""Deterministic checks for the perception -> Scene bridge (research/spatial_architecture).

No GPU, no models: synthetic GroundingHypothesis inputs with a known-correct
answer. These guard the two things an aggregate integration number would not
reveal if they went backwards: the yaw/footprint round-trip, and the wall
centerline offset.
"""
from __future__ import annotations

import math

from research.spatial_architecture.grounding_contract import (
    GroundingHypothesis, OrientationCandidate)
from research.spatial_architecture.scene_from_photo import (
    WallEvidence, build_room_boundary, grounding_to_scene)


def _sofa_hypothesis(footprint, along=(1.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0)):
    return GroundingHypothesis(
        object_id="o1", case_id="c1", room_image="img.png", semantic_type="sofa",
        canonical_type="sofa", placement_class="FLOOR_STANDING", support="floor",
        footprint=footprint, footprint_axes={"along": along, "normal": normal},
        room_position=(tuple(sum(c[i] for c in footprint) / 4 for i in range(3))
                       if footprint else None),
        depth_m=3.0, extent_wdh_m=(2.0, 0.8, 0.9), floor_contact_m=0.02,
        base_occluded=False, evidence=["synthetic"],
        orientation_candidates=[OrientationCandidate(wall_index=0, axis="depth",
                                                      feasible=True, score=1.0)],
        wall_decision="YES", wall_index=0, wall_distance_m=0.0,
        perception_confidence=0.9, extent_confidence=0.7, wall_confidence=0.85)


def test_footprint_round_trips_through_production_footprint_corners():
    """An axis-aligned rectangle, exactly as Phase 9 builds one, must reproduce
    with near-zero residual - the failure mode this test exists to catch is a
    wrong axis assignment or a wrong yaw sign, which would show up as a large
    residual even though every individual number "looks" plausible."""
    footprint = [(-1.0, -1.0, -3.0), (-1.0, -1.0, -3.9),
                 (1.0, -1.0, -3.0), (1.0, -1.0, -3.9)]
    h = _sofa_hypothesis(footprint)
    floor_pts = [(x, z) for x in (-5, 5) for z in (-5, 5)] * 3
    result = grounding_to_scene(
        "img.png", "proj", "living_room", floor_points_xz=floor_pts,
        walls=[WallEvidence(index=0, normal=(0.0, 0.0, 1.0), offset=3.0, width_m=4.0,
                            enclosure_fraction=0.95, into_room_sign=1.0)],
        hypotheses=[h])
    assert result.objects_placed == 1
    assert result.footprint_reconstruction_error_m["o1"] < 0.02
    obj = result.scene.objects[0]
    assert obj.dimensions[0] == 2.0 and obj.dimensions[2] == 0.9   # width along, depth normal


def test_wall_centerline_sits_behind_its_own_fitted_plane():
    """The fitted plane is the wall's visible INNER face. The built Wall's
    thickness must extend AWAY from the room, never into it - see
    scene_from_photo.py's module docstring for why this matters."""
    walls = [WallEvidence(index=0, normal=(0.0, 0.0, 1.0), offset=3.0, width_m=4.0,
                          enclosure_fraction=0.9, into_room_sign=1.0)]
    floor_pts = [(x, z) for x in (-5, 5) for z in (-5, 5)] * 3
    result = grounding_to_scene("img.png", "proj", "living_room",
                                floor_points_xz=floor_pts, walls=walls, hypotheses=[])
    wall = result.scene.walls[0]
    # the plane is z = -3 (n=(0,0,1), offset=3 => 0*x+1*z+3=0 => z=-3); the room
    # (positive signed-distance side, since into_room_sign=+1) is z > -3.
    inner_face_z = min(wall.start[1], wall.end[1])
    assert inner_face_z <= -3.0 + 1e-6, (
        "the wall's near edge must not sit inside the room past the fitted plane")


def test_room_boundary_is_padded_outward_never_inward():
    pts = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)] * 3
    boundary, conf = build_room_boundary(pts)
    assert conf.value < 1.0 and "reconstructed" in conf.source
    for x, z in [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]:
        assert min(math.hypot(x - bx, z - bz) for bx, bz in boundary) > 0.5, (
            "padding must push the boundary strictly outward from the measured floor")


def test_ungrounded_object_yields_no_relation_and_stays_skipped():
    h = _sofa_hypothesis(footprint=None)
    floor_pts = [(x, z) for x in (-5, 5) for z in (-5, 5)] * 3
    result = grounding_to_scene("img.png", "proj", "living_room",
                                floor_points_xz=floor_pts, walls=[], hypotheses=[h])
    assert result.objects_placed == 0 and result.objects_skipped == 1
    assert result.relations == []

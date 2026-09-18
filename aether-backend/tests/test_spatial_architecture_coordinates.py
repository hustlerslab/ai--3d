"""Deterministic checks for the P6 coordinate-frame architecture
(coordinate_frames.py, transforms.py, frame_graph.py).

No GPU, no models. See docs/spatial_architecture/coordinate_frames.md for
the audit, research, and design these guard.
"""
from __future__ import annotations

import math

import pytest
from app.scene.schema import Confidence, SceneObject
from app.spatial.coordinate_frames import FrameId
from app.spatial.frame_graph import (
    object_frame_transform, opencv_to_room, room_to_blender,
    wall_frame_transform)
from app.spatial.transforms import (
    Direction3, FrameMismatchError, IDENTITY_MAT3, Point3, Rigid3, Vector3,
    determinant3, is_orthonormal)
from app.spatial.wall_geometry import TiltedWall, up_from_normal

REAL_MEASURED_NORMAL = (0.06009, 0.1888, -0.98018)


# ---- identity, inverse, composition -----------------------------------

def test_identity_preserves_points():
    T = Rigid3.identity(FrameId.ROOM)
    p = Point3(1.0, 2.0, 3.0, frame=FrameId.ROOM)
    out = T.apply_point(p)
    assert (out.x, out.y, out.z) == (1.0, 2.0, 3.0)


def test_inverse_composes_to_identity():
    T = opencv_to_room()
    p = Point3(1.5, -2.5, 3.5, frame=FrameId.CAMERA)
    back = T.inverse().apply_point(T.apply_point(p))
    assert math.isclose(back.x, p.x, abs_tol=1e-9)
    assert math.isclose(back.y, p.y, abs_tol=1e-9)
    assert math.isclose(back.z, p.z, abs_tol=1e-9)
    assert back.frame == FrameId.CAMERA


def test_composition_matches_sequential_application():
    obj = SceneObject(object_id="o", semantic_type="sofa", room_id="r",
                      position=(1.0, 0.0, -2.0), rotation_y=0.4,
                      dimensions=(1, 1, 1), confidence=Confidence(value=0.9))
    obj_to_room = object_frame_transform(obj)
    room_to_bl = room_to_blender()
    chained = room_to_bl.compose(obj_to_room)   # OBJECT -> BLENDER_WORLD directly

    p_obj = Point3(0.3, 0.5, -0.2, frame=FrameId.OBJECT)
    sequential = room_to_bl.apply_point(obj_to_room.apply_point(p_obj))
    combined = chained.apply_point(p_obj)
    assert math.isclose(sequential.x, combined.x, abs_tol=1e-9)
    assert math.isclose(sequential.y, combined.y, abs_tol=1e-9)
    assert math.isclose(sequential.z, combined.z, abs_tol=1e-9)


def test_compose_rejects_mismatched_frames():
    a = Rigid3.identity(FrameId.ROOM)
    b = Rigid3.identity(FrameId.WALL)
    with pytest.raises(FrameMismatchError):
        a.compose(b)


# ---- point / vector / direction distinction ----------------------------

def test_translation_affects_point_not_vector_or_direction():
    T = Rigid3.from_axis_permutation(FrameId.ROOM, FrameId.BLENDER_WORLD,
                                     (1, 0, 0), (0, 0, -1), (0, 1, 0),
                                     translation=(5.0, 5.0, 5.0), provenance="test")
    p = Point3(0.0, 0.0, 0.0, frame=FrameId.ROOM)
    v = Vector3(0.0, 0.0, 0.0, frame=FrameId.ROOM)
    out_p = T.apply_point(p)
    out_v = T.apply_vector(v)
    assert (out_p.x, out_p.y, out_p.z) == (5.0, 5.0, 5.0)
    assert (out_v.x, out_v.y, out_v.z) == (0.0, 0.0, 0.0)


def test_direction3_rejects_zero_length_vector():
    with pytest.raises(ValueError):
        Direction3(0.0, 0.0, 0.0, frame=FrameId.ROOM)


def test_direction3_rejects_non_unit_length():
    with pytest.raises(ValueError):
        Direction3(2.0, 0.0, 0.0, frame=FrameId.ROOM)


# ---- orthonormality / reflection rejection -----------------------------

def test_identity_matrix_is_orthonormal():
    assert is_orthonormal(IDENTITY_MAT3)
    assert determinant3(IDENTITY_MAT3) == 1.0


def test_rigid3_rejects_a_reflection():
    reflection = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))  # det = -1
    assert not is_orthonormal(reflection)
    with pytest.raises(ValueError):
        Rigid3(source=FrameId.ROOM, target=FrameId.BLENDER_WORLD, rotation=reflection,
              translation=(0, 0, 0), provenance="adversarial reflection")


def test_rigid3_rejects_a_degenerate_non_orthogonal_basis():
    degenerate = ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))  # two identical rows
    with pytest.raises(ValueError):
        Rigid3(source=FrameId.ROOM, target=FrameId.WALL, rotation=degenerate,
              translation=(0, 0, 0), provenance="adversarial degenerate basis")


# ---- opencv <-> room ----------------------------------------------------

def test_opencv_to_room_is_proper_rotation():
    T = opencv_to_room()
    assert is_orthonormal(T.rotation)
    assert math.isclose(determinant3(T.rotation), 1.0, abs_tol=1e-9)


def test_opencv_to_room_matches_metric_geometry_convention():
    # a point "down and forward" in OpenCV (+Y down, +Z forward) must land
    # "up and backward" in Room (+Y up, -Z forward) - the exact behaviour
    # research/spatial_engine/metric_geometry.py:_to_canonical documents.
    T = opencv_to_room()
    p = Point3(1.0, 1.0, 1.0, frame=FrameId.CAMERA)
    out = T.apply_point(p)
    assert (out.x, out.y, out.z) == (1.0, -1.0, -1.0)


# ---- room <-> blender ----------------------------------------------------

def test_room_to_blender_is_proper_rotation():
    T = room_to_blender()
    assert is_orthonormal(T.rotation)
    assert math.isclose(determinant3(T.rotation), 1.0, abs_tol=1e-9)


def test_room_to_blender_matches_manifest_convention():
    from app.blender.manifest import to_blender_xyz
    T = room_to_blender()
    for p in [(1.0, 2.0, 3.0), (-1.0, 0.5, -2.0), (0.0, 0.0, 0.0)]:
        expected = to_blender_xyz(p)
        out = T.apply_point(Point3(*p, frame=FrameId.ROOM))
        assert [round(out.x, 4), round(out.y, 4), round(out.z, 4)] == expected


# ---- wall frame, integrating P5, across the tilt sweep -----------------

@pytest.mark.parametrize("tilt_deg", [0, 5, 10, 11, 15, 20])
def test_wall_frame_round_trip_across_the_p5_tilt_sweep(tilt_deg):
    ny = math.sin(math.radians(tilt_deg))
    horiz = math.sqrt(max(0.0, 1.0 - ny * ny))
    normal = (0.06009 / 0.98207 * horiz, ny, -0.98018 / 0.98207 * horiz)
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=up_from_normal(normal))
    T = wall_frame_transform(wall)
    assert is_orthonormal(T.rotation)
    for p in [(0.5, 1.2, -2.3), (-1.0, 0.0, -3.0), (2.0, 2.8, -3.5)]:
        pt = Point3(*p, frame=FrameId.ROOM)
        back = T.inverse().apply_point(T.apply_point(pt))
        assert math.isclose(back.x, p[0], abs_tol=1e-9)
        assert math.isclose(back.y, p[1], abs_tol=1e-9)
        assert math.isclose(back.z, p[2], abs_tol=1e-9)


# ---- object frame, across rotation edge cases --------------------------

@pytest.mark.parametrize("yaw_deg", [0, 90, 180, 270, 37])
def test_object_frame_round_trip_across_rotation_edge_cases(yaw_deg):
    obj = SceneObject(object_id="o", semantic_type="sofa", room_id="r",
                      position=(2.0, 0.0, -1.5), rotation_y=math.radians(yaw_deg),
                      dimensions=(1, 1, 1), confidence=Confidence(value=0.9))
    T = object_frame_transform(obj)   # OBJECT -> ROOM
    assert is_orthonormal(T.rotation)
    for local in [(0.3, 0.0, 0.2), (-0.5, 0.8, 0.0), (0.0, 0.0, 0.0)]:
        p = Point3(*local, frame=FrameId.OBJECT)
        world = T.apply_point(p)
        back = T.inverse().apply_point(world)
        assert math.isclose(back.x, local[0], abs_tol=1e-9)
        assert math.isclose(back.y, local[1], abs_tol=1e-9)
        assert math.isclose(back.z, local[2], abs_tol=1e-9)


def test_object_frame_matches_footprint_corners_convention():
    from app.spatial.geometry import footprint_corners
    obj = SceneObject(object_id="o", semantic_type="sofa", room_id="r",
                      position=(1.0, 0.0, -2.0), rotation_y=0.6,
                      dimensions=(2.0, 1.0, 1.0), confidence=Confidence(value=0.9))
    T = object_frame_transform(obj)
    # a local corner at (width/2, 0, depth/2) must land on production's own
    # footprint_corners() output for the same object.
    hw, hd = 1.0, 0.5
    local_corner = Point3(hw, 0.0, hd, frame=FrameId.OBJECT)
    world = T.apply_point(local_corner)
    expected = [c for c in footprint_corners((obj.position[0], obj.position[2]), 2.0, 1.0, obj.rotation_y)
               if math.isclose(c[0], world.x, abs_tol=1e-6) and math.isclose(c[1], world.z, abs_tol=1e-6)]
    assert expected, f"world corner {(world.x, world.z)} not among footprint_corners output"


# ---- determinism --------------------------------------------------------

def test_determinism_across_repeated_transform_construction():
    obj = SceneObject(object_id="o", semantic_type="sofa", room_id="r",
                      position=(1.0, 0.0, -2.0), rotation_y=0.7,
                      dimensions=(1, 1, 1), confidence=Confidence(value=0.9))
    runs = []
    for _ in range(20):
        T1, T2 = opencv_to_room(), object_frame_transform(obj)
        runs.append((T1.rotation, T1.translation, T2.rotation, T2.translation))
    assert all(r == runs[0] for r in runs[1:])

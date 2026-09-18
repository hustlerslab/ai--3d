"""P6 frame graph: the explicit tree of transforms Allure's pipeline actually
uses. Every edge WRAPS an existing, already-measured-correct conversion
(coordinate_frames.md's audit) as a typed `Rigid3` - none reimplements the
underlying math differently from the production/research code it wraps.

    IMAGE
      |  (pixel -> ray, MoGe-2's own intrinsics - not modeled as a Rigid3:
      |   a projection, not a rigid transform; see coordinate_frames.md §image_to_camera)
      v
    CAMERA
      |  opencv_to_room()  (metric_geometry.py:_to_canonical, 180deg about X)
      v
    ROOM  <---------------------------------+
      |  \\                                  |
      |   \\ wall_frame_transform(wall)       | room_to_blender()
      |    v  (P5, per-wall)                 | (manifest.py:to_blender_xyz)
      |   WALL                               v
      |                                 BLENDER_WORLD
      v
    OBJECT  (object_frame_transform(obj), per-SceneObject)
      |
      v
    ASSET  (identity today - no per-asset forward-axis correction data
             exists; Phase 10's asset audit found none of the 58 registry
             assets needed one, so identity is the measured-correct default,
             not an unfilled placeholder)

IMAGE -> CAMERA is deliberately NOT a `Rigid3`: a pixel is a ray, not a rigid
transform of a point (this needs the camera's intrinsics/depth, a
projection, not a rotation+translation) - modeling it as a rigid transform
would misrepresent what it actually is (coordinate_frames.md's own
research question about this exact distinction).
"""
from __future__ import annotations

import math
from typing import Optional


from app.scene.schema import SceneObject
from app.spatial.coordinate_frames import FrameId
from app.spatial.transforms import Rigid3
from app.spatial.wall_geometry import (
    TiltedWall, wall_local_frame)


def opencv_to_room() -> Rigid3:
    """metric_geometry.py:_to_canonical, exactly: negate Y and Z - a
    180-degree rotation about X, measured on a real benchmark image."""
    return Rigid3.from_diagonal(FrameId.CAMERA, FrameId.ROOM, (1.0, -1.0, -1.0),
                                provenance="metric_geometry.py:_to_canonical (measured, not assumed)")


def room_to_blender() -> Rigid3:
    """app/blender/manifest.py:to_blender_xyz, exactly:
    (x, y, z) -> (x, -z, y). Already round-trip tested in production
    (Phase 13, XY p95 0.015 m) - this wraps it, does not re-derive it."""
    return Rigid3.from_axis_permutation(
        FrameId.ROOM, FrameId.BLENDER_WORLD,
        row0=(1.0, 0.0, 0.0), row1=(0.0, 0.0, -1.0), row2=(0.0, 1.0, 0.0),
        translation=(0.0, 0.0, 0.0),
        provenance="app/blender/manifest.py:to_blender_xyz", confidence=1.0)


def wall_frame_transform(wall: TiltedWall) -> Rigid3:
    """ROOM -> WALL, built from P5's own `wall_local_frame` basis
    (tangent, up, normal) - the SAME basis P5's `world_to_wall` already
    uses, wrapped as a composable, invertible Rigid3 instead of a
    standalone function pair."""
    origin, tangent, up, normal = wall_local_frame(wall)
    rotation = (tangent, up, normal)   # rows: local axes expressed in ROOM coords
    # translation such that apply_point(room_pt) = R @ (room_pt - origin):
    # R@room_pt + t = R@room_pt - R@origin  =>  t = -R@origin
    rt = tuple(-(rotation[i][0] * origin[0] + rotation[i][1] * origin[1] + rotation[i][2] * origin[2])
              for i in range(3))
    return Rigid3(source=FrameId.ROOM, target=FrameId.WALL, rotation=rotation,
                 translation=rt, provenance=f"wall_geometry.py:wall_local_frame({wall.wall_id})",
                 confidence=1.0)


def object_frame_transform(obj: SceneObject) -> Rigid3:
    """OBJECT -> ROOM (local-to-world), matching `app/spatial/geometry.py:
    footprint_corners`'s own rotation convention exactly (c, s = cos(-yaw),
    sin(-yaw)) - the same convention already used and round-trip tested
    throughout P1-P5. ROOM -> OBJECT is this transform's own `.inverse()`."""
    c, s = math.cos(-obj.rotation_y), math.sin(-obj.rotation_y)
    rotation = ((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c))
    return Rigid3(source=FrameId.OBJECT, target=FrameId.ROOM, rotation=rotation,
                 translation=obj.position, provenance=f"footprint_corners convention "
                 f"(object_id={obj.object_id}, rotation_y={obj.rotation_y})", confidence=1.0)


def asset_to_object_transform(asset_id: Optional[str] = None) -> Rigid3:
    """ASSET -> OBJECT: identity today. Phase 10's asset audit (58/58
    registry assets) found no asset needing a forward-axis correction - this
    is the measured-correct default, not an unfilled placeholder. Confidence
    is 1.0 only because it is measured-empty, not because a correction was
    verified per-asset; coordinate_frames.md names this as the one
    remaining open item if a future asset ever needs a real correction."""
    return Rigid3.identity(FrameId.OBJECT, provenance=f"identity (Phase 10 audit, asset_id={asset_id})")


def camera_to_blender(wall: Optional[TiltedWall] = None) -> Rigid3:
    """CAMERA -> BLENDER_WORLD, the full chain a photo-grounded object's
    geometry actually travels through this pipeline."""
    return room_to_blender().compose(opencv_to_room())


def describe_graph() -> str:
    return (
        "IMAGE -> CAMERA (projection, not Rigid3 - see module docstring)\n"
        "CAMERA -> ROOM       : opencv_to_room()\n"
        "ROOM -> WALL         : wall_frame_transform(wall)   [per-wall]\n"
        "ROOM -> OBJECT       : object_frame_transform(obj).inverse()   [per-object]\n"
        "OBJECT -> ASSET      : asset_to_object_transform().inverse()\n"
        "ROOM -> BLENDER_WORLD: room_to_blender()"
    )


__all__ = ["opencv_to_room", "room_to_blender", "wall_frame_transform",
           "object_frame_transform", "asset_to_object_transform", "camera_to_blender",
           "describe_graph"]

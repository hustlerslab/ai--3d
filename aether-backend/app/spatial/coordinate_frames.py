"""P6 frame taxonomy: every spatial quantity in Allure belongs to exactly one
of these frames. Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. See docs/spatial_architecture/coordinate_frames.md
for the full audit and research behind this list.

EIGHT FRAMES, NOT TWELVE: IMAGE, CAMERA, ROOM, WALL, OBJECT, ASSET,
BLENDER_WORLD, MOODBOARD. (Until P1-ELEM-002 this said eight while the enum
held seven; MOODBOARD is the eighth, and the only non-metric frame besides
IMAGE.) The brief's own list names four more (SCREEN,
DEPTH, FLOORPLAN, BUILDING) - none has a concrete reason to exist in this
codebase: no code path produces or consumes a screen-space quantity distinct
from IMAGE, no depth-frame quantity outlives the one function
(`metric_geometry.py:_to_canonical`) that immediately converts it to ROOM,
no floorplan-frame or multi-building quantity exists anywhere in a
single-photo, single-room pipeline. Per principle ("do not create frames
merely for conceptual purity"), they are not added.

FLOOR IS NOT A SEPARATE FRAME. `app/scene/schema.py:Room` has no `Floor`
entity - `floor_height` is a scalar field on `Room` itself. There is nothing
to give FLOOR its own origin/axes distinct from ROOM's own y=0 plane. Adding
one would duplicate ROOM for no capability gain (`wall_baseline.md`'s own
"do not duplicate frames unnecessarily" instruction, reapplied here).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FrameId(str, Enum):
    IMAGE = "IMAGE"                    # 2D pixel space of the source photo
    CAMERA = "CAMERA"                  # 3D, OpenCV convention, camera-relative
    ROOM = "ROOM"                      # 3D, Allure canonical - THE authority frame
    WALL = "WALL"                      # 3D, per-wall local (P5)
    OBJECT = "OBJECT"                  # 3D, per-SceneObject local
    ASSET = "ASSET"                    # 3D, per-catalog-mesh local
    BLENDER_WORLD = "BLENDER_WORLD"    # 3D, Blender's own world
    MOODBOARD = "MOODBOARD"            # 2D, fractions of a GENERATED image - never metric


#: The relation-frame name for "the room seen from above" (ROOM projected to
#: XZ) - P1-ELEM-003. It used to be "floor_plan", the same string as the
#: uploaded-document kind `InputKind.floor_plan`: one word, two unrelated
#: meanings. Files written before the rename still say "floor_plan";
#: `relation_frame()` reads them.
ROOM_PLAN = "room_plan"
LEGACY_RELATION_FRAMES: dict[str, str] = {"floor_plan": ROOM_PLAN}


def relation_frame(value: object) -> object:
    """Normalise a stored relation frame: the legacy name becomes the new
    one; anything else passes through for the type to validate."""
    return LEGACY_RELATION_FRAMES.get(value, value) if isinstance(value, str) else value


@dataclass(frozen=True)
class FrameSpec:
    frame_id: FrameId
    purpose: str
    parent: Optional[FrameId]
    units: str                  # "px" | "m" | "dimensionless"
    handedness: Optional[str]   # "right" | "left" | None (2D frames have none)
    up: Optional[str]           # None where not meaningful (e.g. IMAGE)
    right: Optional[str]
    forward: Optional[str]
    metric: bool                # can distances in this frame be compared in metres?
    persistent: bool            # does a value in this frame outlive one function call?
    serializable: bool          # is this frame ever written to a Scene/manifest file?
    transform_source: str       # where the frame's own definition/pose comes from


#: The audited, not assumed, ground truth for every frame this program
#: actually produces or consumes. Every row cites the exact file this was
#: read from in `coordinate_frames.md`'s audit table.
FRAME_REGISTRY: dict[FrameId, FrameSpec] = {
    FrameId.IMAGE: FrameSpec(
        frame_id=FrameId.IMAGE, purpose="pixel coordinates of the source photo",
        parent=None, units="px", handedness=None, up=None, right="+u", forward=None,
        metric=False, persistent=False, serializable=False,
        transform_source="the photo's own pixel grid (row, col), +Y down (image convention)"),
    FrameId.CAMERA: FrameSpec(
        frame_id=FrameId.CAMERA, purpose="metric 3D points, camera-relative (MoGe-2 raw output)",
        parent=FrameId.IMAGE, units="m", handedness="right", up="-Y", right="+X", forward="+Z",
        metric=True, persistent=False, serializable=False,
        transform_source="MoGe-2's own OpenCV-convention output (metric_geometry.py "
                         "docstring, measured on a real benchmark image, not assumed)"),
    FrameId.ROOM: FrameSpec(
        frame_id=FrameId.ROOM, purpose="Allure's canonical authority frame - every "
                                       "SceneObject, Wall, Room.boundary is expressed here",
        parent=FrameId.CAMERA, units="m", handedness="right", up="+Y", right="+X", forward="-Z",
        metric=True, persistent=True, serializable=True,
        transform_source="app/scene/schema.py:Scene.coordinate_system "
                         "(the field already documents this exact convention)"),
    FrameId.WALL: FrameSpec(
        frame_id=FrameId.WALL, purpose="per-wall local frame (P5): tangent/up/normal",
        parent=FrameId.ROOM, units="m", handedness="right", up="extrusion_direction", right="tangent",
        forward="normal", metric=True, persistent=False, serializable=False,
        transform_source="research/spatial_architecture/wall_geometry.py:wall_local_frame"),
    FrameId.OBJECT: FrameSpec(
        frame_id=FrameId.OBJECT, purpose="per-SceneObject local frame: bottom-center pivot, yaw",
        parent=FrameId.ROOM, units="m", handedness="right", up="+Y", right="+X", forward="-Z",
        metric=True, persistent=False, serializable=False,
        transform_source="app/scene/schema.py:SceneObject.position (bottom-center pivot, "
                         "documented) + rotation_y"),
    FrameId.ASSET: FrameSpec(
        frame_id=FrameId.ASSET, purpose="per-catalog-mesh local frame, as authored",
        parent=FrameId.OBJECT, units="m", handedness="right", up="+Y", right="+X", forward="-Z",
        metric=True, persistent=False, serializable=False,
        transform_source="asset registry NormalizationInfo.yaw_offset / yaw_source (P1-ASSET-005: "
                         "measured or declared at ingest and baked into the normalized file; "
                         "frame_graph.asset_to_object_transform turns it into the ASSET->OBJECT "
                         "Rigid3, identity for records that predate the measurement)"),
    FrameId.BLENDER_WORLD: FrameSpec(
        frame_id=FrameId.BLENDER_WORLD, purpose="Blender's own world, Z-up",
        parent=FrameId.ROOM, units="m", handedness="right", up="+Z", right="+X", forward="+Y",
        metric=True, persistent=True, serializable=True,
        transform_source="app/blender/manifest.py:to_blender_xyz/yaw_to_blender_rz "
                         "(already explicit, already documented, already round-trip tested "
                         "- confirmed by reading, not assumed)"),
    # P1-ELEM-002. The approved moodboard is a GENERATED image: no camera
    # took it, so it has no pose, no intrinsics and no depth, and there is no
    # projection to invert. A bbox or position read from it is a fraction of
    # the picture - ordering evidence, never metres. `parent=None` and NO
    # edge in frame_graph.py: nothing can transform a moodboard value into
    # ROOM, and `Rigid3` refuses to be built on a non-metric frame.
    FrameId.MOODBOARD: FrameSpec(
        frame_id=FrameId.MOODBOARD, purpose="fractions [0,1] of the approved (generated) moodboard image",
        parent=None, units="fraction", handedness=None, up=None, right="+u", forward=None,
        metric=False, persistent=True, serializable=True,
        transform_source="none - a generated image has no camera pose; see MoodboardOccurrence "
                         "(app/intelligence/schema.py), whose frame is pinned to MOODBOARD"),
}


def frame_spec(frame_id: FrameId) -> FrameSpec:
    return FRAME_REGISTRY[frame_id]


__all__ = ["FrameId", "FrameSpec", "FRAME_REGISTRY", "frame_spec", "ROOM_PLAN", "LEGACY_RELATION_FRAMES",
           "relation_frame"]

"""Patch system — the ONLY allowed scene mutation path.

Lifecycle (implementation plan §8):
  receive → schema validate → version check → apply in memory
  → geometry/constraint validate → persist → increment version → publish

Operations:
  add_object, remove_object, move_object, rotate_object, scale_object,
  update_object (color / lock / semantic), rename_room, set_room_material
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..spatial.validation import Violation, validate_scene
from .schema import ObjectSource, Scene, SceneObject, Vec3, new_id
from .store import SceneStore, VersionConflict


class PatchError(Exception):
    def __init__(self, code: str, message: str, violations: list[Violation] | None = None):
        self.code = code
        self.message = message
        self.violations = violations or []
        super().__init__(message)


# ── Operations ──────────────────────────────────────────────────────────


class AddObjectOp(BaseModel):
    type: Literal["add_object"] = "add_object"
    object: SceneObject


class RemoveObjectOp(BaseModel):
    type: Literal["remove_object"] = "remove_object"
    object_id: str


class MoveObjectOp(BaseModel):
    type: Literal["move_object"] = "move_object"
    object_id: str
    position: Vec3


class RotateObjectOp(BaseModel):
    type: Literal["rotate_object"] = "rotate_object"
    object_id: str
    rotation_y: float


class ScaleObjectOp(BaseModel):
    type: Literal["scale_object"] = "scale_object"
    object_id: str
    scale: Vec3


class UpdateObjectOp(BaseModel):
    type: Literal["update_object"] = "update_object"
    object_id: str
    color: Optional[str] = None
    locked: Optional[bool] = None
    semantic_type: Optional[str] = None


class ReplaceAssetOp(BaseModel):
    """Swap the model behind an object (plan §17 replace_asset). Dimensions,
    colour and mount come from the catalog record so the footprint the
    validator sees is the real model's."""
    type: Literal["replace_asset"] = "replace_asset"
    object_id: str
    asset_id: str


class RenameRoomOp(BaseModel):
    type: Literal["rename_room"] = "rename_room"
    room_id: str
    name: str


class SetRoomMaterialOp(BaseModel):
    type: Literal["set_room_material"] = "set_room_material"
    room_id: str
    floor_material: str


PatchOperation = Union[
    AddObjectOp,
    RemoveObjectOp,
    MoveObjectOp,
    RotateObjectOp,
    ScaleObjectOp,
    UpdateObjectOp,
    ReplaceAssetOp,
    RenameRoomOp,
    SetRoomMaterialOp,
]


class Patch(BaseModel):
    patch_id: str = Field(default_factory=lambda: new_id("patch"))
    scene_id: str
    base_version: int
    operations: list[PatchOperation]
    source: str = "user"  # user | ai | system


# ── Application ─────────────────────────────────────────────────────────


def _require_object(scene: Scene, object_id: str) -> SceneObject:
    obj = scene.object(object_id)
    if obj is None:
        raise PatchError("OBJECT_NOT_FOUND", f"Object {object_id} not found.")
    if obj.locked:
        raise PatchError("OBJECT_LOCKED", f"Object {object_id} is locked.")
    return obj


def apply_operations(scene: Scene, operations: list[PatchOperation]) -> Scene:
    """Apply ops to a deep copy; the caller decides whether to persist."""
    working = scene.model_copy(deep=True)
    for op in operations:
        if isinstance(op, AddObjectOp):
            if working.object(op.object.object_id) is not None:
                raise PatchError(
                    "DUPLICATE_OBJECT", f"Object {op.object.object_id} already exists."
                )
            working.objects.append(op.object)
        elif isinstance(op, RemoveObjectOp):
            _require_object(working, op.object_id)
            working.objects = [
                o for o in working.objects if o.object_id != op.object_id
            ]
        elif isinstance(op, MoveObjectOp):
            _require_object(working, op.object_id).position = op.position
        elif isinstance(op, RotateObjectOp):
            _require_object(working, op.object_id).rotation_y = op.rotation_y
        elif isinstance(op, ScaleObjectOp):
            _require_object(working, op.object_id).scale = op.scale
        elif isinstance(op, UpdateObjectOp):
            obj = working.object(op.object_id)
            if obj is None:
                raise PatchError("OBJECT_NOT_FOUND", f"Object {op.object_id} not found.")
            if op.color is not None:
                obj.color = op.color
            if op.locked is not None:
                obj.locked = op.locked
            if op.semantic_type is not None:
                obj.semantic_type = op.semantic_type
        elif isinstance(op, ReplaceAssetOp):
            from ..catalog.catalog import get_item  # local import: catalog depends on scene schema

            obj = _require_object(working, op.object_id)
            item = get_item(op.asset_id)
            if item is None:
                raise PatchError("ASSET_NOT_FOUND", f"Catalog asset {op.asset_id} not found.")
            obj.asset_id = item.asset_id
            obj.semantic_type = item.semantic_type
            obj.dimensions = item.dimensions
            obj.color = item.color
            obj.mount = item.mount
            obj.source = ObjectSource.CATALOG
        elif isinstance(op, RenameRoomOp):
            room = working.room(op.room_id)
            if room is None:
                raise PatchError("ROOM_NOT_FOUND", f"Room {op.room_id} not found.")
            room.name = op.name
        elif isinstance(op, SetRoomMaterialOp):
            room = working.room(op.room_id)
            if room is None:
                raise PatchError("ROOM_NOT_FOUND", f"Room {op.room_id} not found.")
            room.floor_material = op.floor_material
    return working


class CommitResult(BaseModel):
    scene: Scene
    violations: list[Violation] = []


def preview_patch(store: SceneStore, patch: Patch) -> CommitResult:
    """Apply + validate without persisting. Used for previews and drags."""
    scene = store.load(patch.scene_id)
    if scene.version != patch.base_version:
        raise VersionConflict(patch.base_version, scene.version)
    candidate = apply_operations(scene, patch.operations)
    violations = validate_scene(candidate)
    return CommitResult(scene=candidate, violations=violations)


def commit_patch(store: SceneStore, patch: Patch) -> Scene:
    """The full pipeline. Raises PatchError on hard violations."""
    scene = store.load(patch.scene_id)
    if scene.version != patch.base_version:
        raise VersionConflict(patch.base_version, scene.version)
    candidate = apply_operations(scene, patch.operations)
    violations = validate_scene(candidate)
    hard = [v for v in violations if v.severity == "hard"]
    if hard:
        raise PatchError(
            "VALIDATION_FAILED",
            "; ".join(v.message for v in hard[:3]),
            violations=hard,
        )
    return store.commit(candidate, base_version=patch.base_version)

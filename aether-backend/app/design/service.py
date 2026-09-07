"""Design intelligence — instruction → proposal → planned patch.

Pipeline (plan §25):
  instruction → intent → context → LLM (or deterministic mock)
  → structured proposal → spatial planner resolves coordinates
  → validated patch → preview → user approval → commit

The AI never emits coordinates; the planner computes every transform and
the commit pipeline validates it (system design §3.3).
"""
from __future__ import annotations

import json
import math
import threading
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..catalog.catalog import find_by_semantic, semantic_types
from ..core.config import get_settings
from ..providers import gemini
from ..scene.patches import (
    AddObjectOp,
    MoveObjectOp,
    Patch,
    PatchOperation,
    RemoveObjectOp,
    apply_operations,
)
from ..scene.schema import ObjectSource, Room, Scene, SceneObject, new_id
from ..spatial import geometry as geo
from ..spatial.validation import validate_object, validate_scene


class ProposalOperation(BaseModel):
    op: Literal["add", "remove", "move"]
    semantic_type: Optional[str] = None
    object_id: Optional[str] = None
    room_id: Optional[str] = None
    relation: Optional[dict[str, str]] = None


class DesignProposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: new_id("prop"))
    scene_id: str
    base_version: int
    instruction: str
    summary: str
    source: str  # "gemini" | "mock"
    operations: list[ProposalOperation]
    planned_patch: Optional[list[PatchOperation]] = None
    warnings: list[str] = []
    status: Literal["preview", "applied", "rejected"] = "preview"
    estimated_cost_inr: int = 0


# In-memory proposal registry (proposals are ephemeral previews).
_proposals: dict[str, DesignProposal] = {}
_lock = threading.Lock()


def get_proposal(proposal_id: str) -> Optional[DesignProposal]:
    return _proposals.get(proposal_id)


def save_proposal(proposal: DesignProposal) -> None:
    with _lock:
        _proposals[proposal.proposal_id] = proposal


# ── Context builder ─────────────────────────────────────────────────────


def build_context(scene: Scene) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "version": scene.version,
        "rooms": [
            {
                "room_id": r.room_id,
                "name": r.name,
                "type": r.type,
                "area_m2": round(geo.polygon_area(r.boundary), 2),
            }
            for r in scene.rooms
        ],
        "objects": [
            {
                "object_id": o.object_id,
                "semantic_type": o.semantic_type,
                "room_id": o.room_id,
                "locked": o.locked,
            }
            for o in scene.objects
        ],
        "catalog": semantic_types(),
    }


# ── Deterministic mock planner ──────────────────────────────────────────

_SEMANTIC_KEYWORDS = {
    "sofa": ["sofa", "couch"],
    "loveseat": ["loveseat", "two seater", "2 seater"],
    "armchair": ["armchair", "accent chair"],
    "coffee_table": ["coffee table", "center table"],
    "tv_unit": ["tv unit", "tv stand", "television"],
    "dining_table": ["dining table"],
    "chair": ["dining chair", "chair"],
    "bed": ["bed"],
    "wardrobe": ["wardrobe", "closet", "almirah"],
    "bedside_table": ["bedside", "nightstand"],
    "bookshelf": ["bookshelf", "book shelf", "shelf"],
    "rug": ["rug", "carpet"],
    "floor_lamp": ["lamp", "floor lamp"],
    "plant": ["plant", "greenery"],
}


def _match_room(scene: Scene, instruction: str) -> Room:
    text = instruction.lower()
    for room in scene.rooms:
        if room.name.lower() in text or room.type.replace("_", " ") in text:
            return room
    return max(scene.rooms, key=lambda r: geo.polygon_area(r.boundary))


def mock_propose(scene: Scene, instruction: str) -> dict[str, Any]:
    """Keyword-driven proposal so the full loop works with no API key."""
    text = instruction.lower()
    room = _match_room(scene, instruction)
    operations: list[dict[str, Any]] = []

    removing = any(w in text for w in ("remove", "delete", "take out", "get rid"))
    import re

    matched: list[str] = []
    for semantic, keywords in _SEMANTIC_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords):
            matched.append(semantic)

    if removing:
        for semantic in matched:
            target = next(
                (
                    o
                    for o in scene.objects
                    if o.semantic_type == semantic and not o.locked
                ),
                None,
            )
            if target:
                operations.append({"op": "remove", "object_id": target.object_id})
    else:
        for semantic in matched:
            operations.append(
                {"op": "add", "semantic_type": semantic, "room_id": room.room_id}
            )

    if not operations:
        # A style request with no explicit object: propose a warm starter set
        # for the room type, skipping types already present.
        starter = {
            "living_room": ["sofa", "coffee_table", "rug", "floor_lamp", "plant"],
            "bedroom": ["bed", "wardrobe", "bedside_table", "rug"],
            "dining_room": ["dining_table", "chair", "plant"],
        }.get(room.type, ["armchair", "plant"])
        present = {o.semantic_type for o in scene.objects if o.room_id == room.room_id}
        for semantic in starter:
            if semantic not in present:
                operations.append(
                    {"op": "add", "semantic_type": semantic, "room_id": room.room_id}
                )

    summary = (
        f"{'Removed' if removing else 'Proposed'} "
        f"{len(operations)} change(s) for {room.name} based on: “{instruction[:80]}”"
    )
    return {"summary": summary, "operations": operations}


# ── Spatial planner ─────────────────────────────────────────────────────


def _wall_aligned_candidates(scene: Scene, room: Room, width: float, depth: float):
    """Candidate (position, rotation) pairs: against each boundary edge,
    facing into the room, at several points along the edge; then centroid."""
    candidates = []
    n = len(room.boundary)
    centroid = geo.polygon_centroid(room.boundary)
    for i in range(n):
        a, b = room.boundary[i], room.boundary[(i + 1) % n]
        edge_len = geo.distance(a, b)
        if edge_len < width:
            continue
        dx, dz = (b[0] - a[0]) / edge_len, (b[1] - a[1]) / edge_len
        # Inward normal: pick the normal pointing toward the centroid.
        nx, nz = -dz, dx
        mid = geo.segment_lerp(a, b, 0.5)
        if (centroid[0] - mid[0]) * nx + (centroid[1] - mid[1]) * nz < 0:
            nx, nz = -nx, -nz
        rotation = math.atan2(-nx, -nz) + math.pi  # face inward
        inset = depth / 2.0 + 0.12
        for t in (0.5, 0.3, 0.7, 0.2, 0.8):
            edge_point = geo.segment_lerp(a, b, t)
            pos = (edge_point[0] + nx * inset, edge_point[1] + nz * inset)
            candidates.append((pos, rotation))
    candidates.append((centroid, 0.0))
    # A few centroid offsets as last resorts.
    for offset in ((0.8, 0.0), (-0.8, 0.0), (0.0, 0.8), (0.0, -0.8)):
        candidates.append(((centroid[0] + offset[0], centroid[1] + offset[1]), 0.0))
    return candidates


def _relation_candidates(scene: Scene, obj: SceneObject, relation: dict[str, str]):
    """Candidates for move ops expressed as relations ("in front of X")."""
    target = scene.object(relation.get("target_id", ""))
    if target is None:
        return []
    tx, tz = target.position[0], target.position[2]
    gap = (target.dimensions[2] + obj.dimensions[2]) / 2.0 + 0.35
    front = geo.rotate_point((0, -gap), -target.rotation_y)
    candidates = [((tx + front[0], tz + front[1]), target.rotation_y + math.pi)]
    for angle in (math.pi / 2, -math.pi / 2, math.pi):
        side = geo.rotate_point((0, -gap), -(target.rotation_y + angle))
        candidates.append(((tx + side[0], tz + side[1]), target.rotation_y + angle + math.pi))
    return candidates


def plan_operations(
    scene: Scene, ops: list[ProposalOperation]
) -> tuple[list[PatchOperation], list[str]]:
    """Resolve proposal ops into concrete, validated patch operations.

    Placement is planned against a working copy so successive additions
    see each other.
    """
    working = scene.model_copy(deep=True)
    patch_ops: list[PatchOperation] = []
    warnings: list[str] = []

    for op in ops:
        if op.op == "remove" and op.object_id:
            target = working.object(op.object_id)
            if target is None:
                warnings.append(f"Cannot remove {op.object_id}: not found.")
                continue
            if target.locked:
                warnings.append(f"Cannot remove {target.semantic_type}: locked.")
                continue
            patch_ops.append(RemoveObjectOp(object_id=op.object_id))
            working.objects = [
                o for o in working.objects if o.object_id != op.object_id
            ]
            continue

        if op.op == "add" and op.semantic_type:
            item = find_by_semantic(op.semantic_type)
            if item is None:
                warnings.append(f"No catalog asset for '{op.semantic_type}'.")
                continue
            room = working.room(op.room_id or "") or max(
                working.rooms, key=lambda r: geo.polygon_area(r.boundary)
            )
            placed = None
            for (pos, rotation) in _wall_aligned_candidates(
                working, room, item.dimensions[0], item.dimensions[2]
            ):
                candidate = SceneObject(
                    semantic_type=item.semantic_type,
                    asset_id=item.asset_id,
                    room_id=room.room_id,
                    position=(pos[0], room.floor_height, pos[1]),
                    rotation_y=rotation,
                    dimensions=item.dimensions,
                    color=item.color,
                    source=ObjectSource.CATALOG,
                    mount=item.mount,
                )
                working.objects.append(candidate)
                if not validate_object(working, candidate):
                    placed = candidate
                    break
                working.objects.pop()
            if placed is None:
                warnings.append(
                    f"No valid position found for {item.name} in {room.name}."
                )
                continue
            patch_ops.append(AddObjectOp(object=placed))
            continue

        if op.op == "move" and op.object_id and op.relation:
            target = working.object(op.object_id)
            if target is None:
                warnings.append(f"Cannot move {op.object_id}: not found.")
                continue
            moved = None
            for (pos, rotation) in _relation_candidates(working, target, op.relation):
                original_pos, original_rot = target.position, target.rotation_y
                target.position = (pos[0], target.position[1], pos[1])
                target.rotation_y = rotation
                if not validate_object(working, target):
                    moved = (target.position, rotation)
                    break
                target.position, target.rotation_y = original_pos, original_rot
            if moved is None:
                warnings.append(
                    f"No valid position satisfies the relation for {target.semantic_type}."
                )
                continue
            patch_ops.append(
                MoveObjectOp(object_id=op.object_id, position=moved[0])
            )
            continue

        warnings.append(f"Unsupported operation: {op.model_dump()}")

    return patch_ops, warnings


# ── Entry point ─────────────────────────────────────────────────────────


async def create_proposal(scene: Scene, instruction: str) -> DesignProposal:
    context = build_context(scene)
    raw = await gemini.propose(context, instruction)
    source = "gemini"
    if raw is None:
        raw = mock_propose(scene, instruction)
        source = "mock"

    try:
        operations = [ProposalOperation.model_validate(o) for o in raw["operations"]]
    except Exception:
        raw = mock_propose(scene, instruction)
        source = "mock"
        operations = [ProposalOperation.model_validate(o) for o in raw["operations"]]

    patch_ops, warnings = plan_operations(scene, operations)

    cost = 0
    for op in patch_ops:
        if isinstance(op, AddObjectOp) and op.object.asset_id:
            from ..catalog.catalog import get_item

            item = get_item(op.object.asset_id)
            if item:
                cost += item.price_inr

    proposal = DesignProposal(
        scene_id=scene.scene_id,
        base_version=scene.version,
        instruction=instruction,
        summary=raw.get("summary", "Design proposal"),
        source=source,
        operations=operations,
        planned_patch=patch_ops,
        warnings=warnings,
        estimated_cost_inr=cost,
    )
    save_proposal(proposal)
    return proposal


def proposal_preview(scene: Scene, proposal: DesignProposal) -> dict[str, Any]:
    """The candidate scene the proposal would produce, plus a diff."""
    candidate = apply_operations(scene, proposal.planned_patch or [])
    violations = validate_scene(candidate)
    before_ids = {o.object_id for o in scene.objects}
    after_ids = {o.object_id for o in candidate.objects}
    return {
        "proposal": proposal.model_dump(),
        "candidate_scene": candidate.model_dump(),
        "added": [
            o.model_dump() for o in candidate.objects if o.object_id not in before_ids
        ],
        "removed": [
            o.model_dump() for o in scene.objects if o.object_id not in after_ids
        ],
        "violations": [v.model_dump() for v in violations],
    }

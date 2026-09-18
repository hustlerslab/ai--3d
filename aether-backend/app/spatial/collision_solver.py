"""P1 collision resolver: a DFS-family sequential placement pass for
photo-grounded objects, run BEFORE Blender (and before `validate_scene`'s
final check).

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. Calls three existing, unmodified functions
(`validate_object`, `footprint_corners`, `convex_polygons_overlap`) and one
existing type (`Confidence`) from `app/`; adds no new geometry primitive and
no new dependency. See docs/spatial_architecture/collision.md for the
research (Holodeck/RoomCraft/HSM all use a DFS-family sequential search, not
a global optimizer, as their primary placement mechanism) and the decision
matrix that rules out OR-Tools/Shapely/FCL for this measured failure.

WHY SEQUENTIAL, NOT GLOBAL. `app/planning/compiler.py:place_objects` already
resolves 0/547 collisions in the brief path with exactly this pattern: order
objects, commit them one at a time into a working scene, accept the first
candidate that validates clean. This module is the same pattern applied to
already-grounded photo objects, which currently skip it entirely (see
`scene_from_photo.py`, which appends every hypothesis with no pairwise check).

WHY EVIDENCE-ANCHORED CANDIDATES, NOT A LEARNED WEIGHT. RoomCraft's CAPS
scores repositioning candidates with a trained objective
(`alpha*dist_loss + beta*neighbour_loss`); its weights are not published and
are not reproducible here. This module keeps CAPS's actual principle
(minimize deviation from where the evidence placed the object) but makes it
deterministic: a fixed candidate lattice, nearest-to-original accepted first,
no learned or tuned coefficients, no randomness.

WHY A SECOND, SMALLER TIER FOR WALL-ANCHORED OBJECTS. A measured run showed
that a wall-tangent-only slide cannot clear a `COLLIDES_WALL` caused by
footprint-reconstruction residual embedding the object a few centimetres
into the wall rectangle - sliding parallel to the wall never changes the
perpendicular penetration. Rather than declare every such case unresolved
(true P5 wall-tilt cases aside - see EMBED_MAX_M's docstring), a bounded
perpendicular nudge away from the wall is tried second, only after every
tangent offset fails, and only up to EMBED_MAX_M - small enough that it
cannot be mistaken for abandoning the wall-contact evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


from app.scene.schema import Scene, SceneObject
from app.spatial.geometry import polygon_centroid
from app.spatial.validation import validate_object

#: Wall-tangent slide / radial-lattice search bound and step, metres. A
#: bound this small keeps the repair "local" (matching the standing
#: "minimal deviation from evidence" principle); 1.0 m comfortably exceeds
#: the largest measured `COLLIDES_OBJECT` footprint overlap in the frozen
#: 21-image benchmark.
MAX_SEARCH_M = 1.0
STEP_M = 0.1

#: Second-tier fallback for a wall-anchored object the tangent slide cannot
#: fix: a small nudge straight away from the wall (same spot along it). Only
#: reached once every tangent offset has failed. Bounded far smaller than
#: MAX_SEARCH_M because this exists to clear a footprint-reconstruction
#: residual embedding the object a few centimetres into the wall rectangle
#: (docs/spatial_architecture/collision.md §10/measured run), not to move the
#: object meaningfully off the wall it has real photographic contact with.
EMBED_MAX_M = 0.2
EMBED_STEP_M = 0.01


@dataclass(frozen=True)
class CollisionResolution:
    object_id: str
    status: str            # "kept" | "moved" | "unresolved"
    distance_moved_m: float
    candidates_tried: int


def _slide_offsets(max_m: float, step: float) -> list[float]:
    """0, +step, -step, +2*step, -2*step, ... — nearest-to-original first,
    a fixed order so two runs never pick different, equally-valid points."""
    offsets = [0.0]
    n = round(max_m / step)
    for i in range(1, n + 1):
        offsets.append(round(i * step, 6))
        offsets.append(round(-i * step, 6))
    return offsets


def _embed_offsets(max_m: float, step: float) -> list[float]:
    """step, 2*step, ... — ascending distance away from the wall. No zero
    entry: offset 0 is the original position, already known to fail."""
    n = round(max_m / step)
    return [round(i * step, 6) for i in range(1, n + 1)]


def _radial_candidates(max_m: float, step: float) -> list[tuple[float, float]]:
    """(dx, dz) offsets on concentric rings, nearest ring first, fixed angle
    order within a ring — a deterministic lattice, not a random search."""
    out: list[tuple[float, float]] = []
    n = round(max_m / step)
    angles = [i * math.pi / 4.0 for i in range(8)]
    for r in range(1, n + 1):
        radius = round(r * step, 6)
        for a in angles:
            out.append((round(radius * math.cos(a), 6), round(radius * math.sin(a), 6)))
    return out


def _wall_by_object(relations: list[dict]) -> dict[str, str]:
    return {r["subject_id"]: r["object_id"] for r in relations
            if r.get("predicate") == "AGAINST_WALL"}


def find_valid_nudge(working: Scene, obj: SceneObject, wall) -> tuple[Optional[SceneObject], float, int]:
    """The per-object candidate-lattice search P1 uses to clear a conflict:
    wall-tangent slide, then a small perpendicular fallback, if `wall` is
    given (the object has AGAINST_WALL evidence); otherwise a radial ring.
    Returns (candidate-or-None, distance_moved_m, candidates_tried). Pulled
    out of `resolve_collisions` as its own function - P4's repair_engine.py
    is a second, real caller (not a hypothetical one), so this is now an
    actually-shared primitive, not a speculative abstraction. Behaviour is
    unchanged: `resolve_collisions`'s own tests (unchanged) verify that."""
    origin = (obj.position[0], obj.position[2])
    tried = 0
    placed: Optional[SceneObject] = None
    distance = 0.0

    if wall is not None:
        dx, dz = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
        length = math.hypot(dx, dz) or 1.0
        tangent = (dx / length, dz / length)
        for offset in _slide_offsets(MAX_SEARCH_M, STEP_M):
            tried += 1
            cand_xz = (origin[0] + tangent[0] * offset, origin[1] + tangent[1] * offset)
            candidate = obj.model_copy(update={
                "position": (round(cand_xz[0], 6), obj.position[1], round(cand_xz[1], 6))})
            if not validate_object(working, candidate):
                placed, distance = candidate, abs(offset)
                break

        if placed is None:
            room = working.room(obj.room_id)
            if room is not None and len(room.boundary) >= 3:
                cx, cz = polygon_centroid(room.boundary)
                perp = (-tangent[1], tangent[0])
                if (cx - origin[0]) * perp[0] + (cz - origin[1]) * perp[1] < 0:
                    perp = (-perp[0], -perp[1])
                for offset in _embed_offsets(EMBED_MAX_M, EMBED_STEP_M):
                    tried += 1
                    cand_xz = (origin[0] + perp[0] * offset, origin[1] + perp[1] * offset)
                    candidate = obj.model_copy(update={
                        "position": (round(cand_xz[0], 6), obj.position[1], round(cand_xz[1], 6))})
                    if not validate_object(working, candidate):
                        placed, distance = candidate, offset
                        break
    else:
        for dx_r, dz_r in _radial_candidates(MAX_SEARCH_M, STEP_M):
            tried += 1
            cand_xz = (origin[0] + dx_r, origin[1] + dz_r)
            candidate = obj.model_copy(update={
                "position": (round(cand_xz[0], 6), obj.position[1], round(cand_xz[1], 6))})
            if not validate_object(working, candidate):
                placed, distance = candidate, math.hypot(dx_r, dz_r)
                break

    return placed, round(distance, 4), tried


def resolve_collisions(scene: Scene, relations: list[dict]) -> tuple[Scene, list[CollisionResolution]]:
    """Re-commit `scene.objects` one at a time, highest `Confidence.value`
    first (ties by `object_id`), into a working scene, using the existing
    `validate_object` as the sole authority on what counts as a conflict.
    A conflicting object is nudged along a deterministic candidate lattice
    (wall-tangent if it has an AGAINST_WALL relation, else radial) and the
    nearest candidate that validates clean is kept. An object with no valid
    candidate within `MAX_SEARCH_M` is left at its original position and
    reported "unresolved" — never dropped, never silently accepted."""
    wall_of = _wall_by_object(relations)
    ordered = sorted(scene.objects, key=lambda o: (-o.confidence.value, o.object_id))

    working = scene.model_copy(update={"objects": []}, deep=True)
    resolutions: list[CollisionResolution] = []

    for obj in ordered:
        if not validate_object(working, obj):
            working.objects.append(obj)
            resolutions.append(CollisionResolution(obj.object_id, "kept", 0.0, 0))
            continue

        wall_id = wall_of.get(obj.object_id)
        wall = working.wall(wall_id) if wall_id else None
        placed, distance, tried = find_valid_nudge(working, obj, wall)

        if placed is not None:
            working.objects.append(placed)
            resolutions.append(CollisionResolution(obj.object_id, "moved", distance, tried))
        else:
            working.objects.append(obj)
            resolutions.append(CollisionResolution(obj.object_id, "unresolved", 0.0, tried))

    return working, resolutions


__all__ = ["resolve_collisions", "find_valid_nudge", "CollisionResolution", "MAX_SEARCH_M", "STEP_M"]

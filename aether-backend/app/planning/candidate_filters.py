"""P9 candidate filtering: FILTER (impossible) is kept strictly separate
from RANK (possible but preferable) - §17's own explicit requirement.

This module is the ENTIRE filter half. It contains no preference logic at
all - a candidate either passes `app.spatial.validation.validate_object`
(the same, only, hard-feasibility gate P0-P8 have ever used) or it is
removed. Ranking (`candidate_ranker.py`) never sees a candidate this module
has already dropped.
"""
from __future__ import annotations



from app.scene.schema import Room, Scene, SceneObject
from app.spatial.validation import validate_object
from app.planning.candidate_model import Candidate


def _probe(subject_id: str, room_id: str, candidate: Candidate,
          dims: tuple[float, float, float], fallback_y: float) -> SceneObject:
    y = candidate.y if candidate.y is not None else fallback_y
    return SceneObject(object_id=subject_id, semantic_type="probe", room_id=room_id,
                       position=(candidate.position[0], y, candidate.position[1]),
                       rotation_y=candidate.rotation_y, dimensions=dims)


def is_feasible(candidate: Candidate, scene: Scene, room: Room,
               dims: tuple[float, float, float], subject_id: str,
               fallback_y: float = 0.0) -> bool:
    """§18: true iff placing a probe object at this candidate's pose in
    `scene` produces zero hard violations (`validate_object` - reused,
    never reimplemented). The probe's `object_id` matches `subject_id` so a
    caller who left the real subject IN `scene` by mistake does not get a
    false self-collision (`validate_object`'s own H3 check already skips an
    object colliding with itself by id)."""
    probe = _probe(subject_id, room.room_id, candidate, dims, fallback_y)
    return not validate_object(scene, probe)


def filter_feasible(candidates: list[Candidate], scene: Scene, room: Room,
                    dims: tuple[float, float, float], subject_id: str,
                    fallback_y: float = 0.0) -> list[Candidate]:
    """§18: removes every hard-infeasible candidate, preserving the
    generator's own deterministic order among what remains - filtering
    never reorders."""
    return [c for c in candidates if is_feasible(c, scene, room, dims, subject_id, fallback_y)]


__all__ = ["is_feasible", "filter_feasible"]

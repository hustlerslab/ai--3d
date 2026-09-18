"""Deterministic checks for candidate_filters.py: FILTER, strictly separate
from ranking. No GPU, no models.
"""
from __future__ import annotations

from app.scene.schema import Room, Scene, SceneObject
from app.planning.candidate_filters import filter_feasible, is_feasible
from app.planning.candidate_model import Candidate, CandidateSource


def _room():
    return Room(room_id="r1", name="Room", type="living_room",
               boundary=[(-3, -3), (3, -3), (3, 3), (-3, 3)])


def _cand(x, z):
    return Candidate(position=(x, z), rotation_y=0.0, y=None, source=CandidateSource.DISTANCE,
                     constraint_id="c", provenance="t")


def test_feasible_candidate_passes():
    scene = Scene(scene_id="s", project_id="p", name="t", rooms=[_room()], objects=[])
    assert is_feasible(_cand(0.0, 0.0), scene, _room(), (0.5, 0.5, 0.5), "s") is True


def test_out_of_room_candidate_fails():
    scene = Scene(scene_id="s", project_id="p", name="t", rooms=[_room()], objects=[])
    assert is_feasible(_cand(100.0, 100.0), scene, _room(), (0.5, 0.5, 0.5), "s") is False


def test_colliding_candidate_fails():
    blocker = SceneObject(object_id="blocker", semantic_type="bookshelf", room_id="r1",
                          position=(0, 0, 0), dimensions=(2.0, 1.8, 2.0))
    scene = Scene(scene_id="s", project_id="p", name="t", rooms=[_room()], objects=[blocker])
    assert is_feasible(_cand(0.0, 0.0), scene, _room(), (0.5, 0.5, 0.5), "s") is False


def test_filter_feasible_preserves_order_among_survivors():
    good_a, bad, good_b = _cand(0.0, 0.0), _cand(100.0, 100.0), _cand(1.0, 1.0)
    scene = Scene(scene_id="s", project_id="p", name="t", rooms=[_room()], objects=[])
    out = filter_feasible([good_a, bad, good_b], scene, _room(), (0.5, 0.5, 0.5), "s")
    assert out == [good_a, good_b]


def test_probe_does_not_self_collide_with_the_real_subject_left_in_scene():
    """§18: the probe's object_id matches subject_id, so validate_object's
    own H3 same-id skip means leaving the real subject in `scene` by
    mistake does not produce a false collision against itself."""
    subject_still_there = SceneObject(object_id="subject", semantic_type="chair", room_id="r1",
                                      position=(0, 0, 0), dimensions=(0.5, 0.9, 0.5))
    scene = Scene(scene_id="s", project_id="p", name="t", rooms=[_room()], objects=[subject_still_there])
    assert is_feasible(_cand(0.0, 0.0), scene, _room(), (0.5, 0.9, 0.5), "subject") is True

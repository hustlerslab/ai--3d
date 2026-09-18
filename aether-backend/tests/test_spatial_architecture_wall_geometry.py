"""Deterministic checks for the P5 tilted-wall representation
(research/spatial_architecture/wall_geometry.py).

No GPU, no models. See docs/spatial_architecture/wall_geometry.md for the
design these guard, including the real measured 11-degree case this module
is built to represent correctly.
"""
from __future__ import annotations

import math

from app.scene.schema import Confidence, SceneObject
from app.spatial.wall_geometry import (
    TiltedWall, cross_section_at_height, object_wall_collides,
    up_from_normal, wall_to_world, world_to_wall)

REAL_MEASURED_NORMAL = (0.06009, 0.1888, -0.98018)   # moodboard_room_master_bedroom wall_0


def test_vertical_normal_gives_exact_world_up():
    assert up_from_normal((0.0, 0.0, -1.0)) == (0.0, 1.0, 0.0)


def test_real_measured_normal_reproduces_the_11_degree_tilt():
    up = up_from_normal(REAL_MEASURED_NORMAL)
    tilt_deg = math.degrees(math.acos(min(1.0, up[1])))
    assert 10.0 < tilt_deg < 12.0, f"expected ~11 degrees, got {tilt_deg:.2f}"


def test_vertical_wall_cross_section_never_drifts():
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0))
    for h in (0.0, 0.5, 1.0, 2.8):
        s, e = cross_section_at_height(wall, h)
        assert s == wall.start and e == wall.end


def test_tilted_wall_cross_section_drifts_linearly_with_height():
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=up_from_normal(REAL_MEASURED_NORMAL))
    s0, _ = cross_section_at_height(wall, 0.0)
    s1, _ = cross_section_at_height(wall, 1.0)
    drift_per_metre = math.hypot(s1[0] - s0[0], s1[1] - s0[1])
    expected = math.tan(math.radians(10.87))
    assert abs(drift_per_metre - expected) < 0.01


def test_round_trip_world_to_wall_to_world_vertical():
    wall = TiltedWall(wall_id="w", start=(-1.0, 2.0), end=(3.0, 2.0))
    for p in [(0.5, 1.2, 2.0), (-1.0, 0.0, 2.0), (3.0, 2.8, 2.0), (1.5, 1.4, 2.3)]:
        back = wall_to_world(wall, world_to_wall(wall, p))
        assert all(abs(a - b) < 1e-9 for a, b in zip(p, back))


def test_round_trip_world_to_wall_to_world_tilted():
    wall = TiltedWall(wall_id="w", start=(-1.0, 2.0), end=(3.0, 2.0),
                      extrusion_direction=up_from_normal(REAL_MEASURED_NORMAL))
    for p in [(0.5, 1.2, 2.3), (-1.0, 0.0, 1.7), (3.0, 2.8, 2.9), (1.5, 1.4, 1.5)]:
        back = wall_to_world(wall, world_to_wall(wall, p))
        assert all(abs(a - b) < 1e-9 for a, b in zip(p, back))


def _obj(x, y, z, w=1.5, h=0.6, d=0.7):
    return SceneObject(object_id="o", semantic_type="bed", room_id="r",
                       position=(x, y, z), dimensions=(w, h, d),
                       confidence=Confidence(value=0.9))


def test_short_object_with_a_small_real_gap_does_not_collide():
    # This measured wall leans INTO the room as height increases (drift_z >
    # 0), so an object placed with EXACTLY zero gap at the floor would
    # genuinely have its top edge clipped by any positive height at all -
    # physically correct, not a bug (a wall leaning inward truly does
    # encroach on anything flush against its base). Real photo evidence
    # never claims exactly zero gap either (measured gaps in this program
    # are always a small positive figure, e.g. 0.03-0.06 m) - a short object
    # with a realistic small gap must clear the drift at both heights.
    tilt_up = up_from_normal(REAL_MEASURED_NORMAL)
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=tilt_up)
    s0, e0 = cross_section_at_height(wall, 0.0)
    inner_face_z = min(s0[1], e0[1]) + wall.thickness / 2.0
    obj = _obj(0.0, 0.0, inner_face_z + 0.05 + 0.35, h=0.15, d=0.7)  # 0.05 m real gap, short
    assert not object_wall_collides(obj, wall)


def test_tall_object_can_genuinely_clip_the_inward_leaning_wall_at_its_top():
    # The exact NEW capability the flat (single fixed-height) representation
    # structurally could never have: a wall that leans further into the room
    # as height increases will genuinely clip the upper portion of a TALL
    # object even with the same small real gap at the floor that keeps a
    # short object clear - a real geometric fact, not a false positive.
    # `wall_baseline.md`'s own drift figure (~0.19 m per metre of height)
    # makes this measurable at ordinary furniture heights (wardrobe-scale).
    tilt_up = up_from_normal(REAL_MEASURED_NORMAL)
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=tilt_up)
    s0, e0 = cross_section_at_height(wall, 0.0)
    inner_face_z = min(s0[1], e0[1]) + wall.thickness / 2.0
    tall = _obj(0.0, 0.0, inner_face_z + 0.05 + 0.35, h=2.0, d=0.7)  # same 0.05 m gap, tall
    assert object_wall_collides(tall, wall), (
        "a tall object with the same real floor gap as the short one must still show "
        "a genuine top-of-object clearance problem against an inward-leaning wall - "
        "the OLD flat representation could never detect this at all, at any height")


def test_determinism_across_repeated_calls():
    wall = TiltedWall(wall_id="w", start=(-3.0, -3.0), end=(3.0, -3.0),
                      extrusion_direction=up_from_normal(REAL_MEASURED_NORMAL))
    obj = _obj(0.0, 0.0, -2.4)
    runs = [(cross_section_at_height(wall, 0.3), object_wall_collides(obj, wall)) for _ in range(20)]
    assert all(r == runs[0] for r in runs[1:])

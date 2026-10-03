"""P1-EVAL-002: prove the render verifier DETECTS a discrepancy rather than
assuming it would - each of task.md's five acceptance criteria is a
deliberate, real breakage, checked against the actual detector.

Removal/intersection/orientation/disabled-checker are pure-function tests
(MOCK class - fast, no Blender). Occlusion needs a real camera and a real
ray-cast, so that one row runs against real Blender (marker `blender`).
"""
from __future__ import annotations

import math

import pytest

from app.scene.schema import Room, Scene, SceneObject, Wall
from app.verification.render_verifier import verify_scene


def _room() -> Room:
    return Room(name="living_room", type="living_room", boundary=[(0, 0), (5, 0), (5, 5), (0, 5)])


def _sofa(room: Room, **overrides) -> SceneObject:
    base = dict(
        semantic_type="sofa", asset_id="asset_sofa", room_id=room.room_id,
        position=(2.0, 0.0, 2.0), rotation_y=0.0, scale=(1, 1, 1), dimensions=(2.0, 0.8, 0.9),
        mount="floor",
    )
    base.update(overrides)
    return SceneObject(**base)


def _built(obj_ids: list[str]) -> dict:
    """A minimal build_report shaped like validate_scene.py's real output -
    just enough for the drift check to compare against."""
    return {"ok": True, "errors": [], "warnings": [],
            "objects": [{"id": oid, "parts": 1} for oid in obj_ids]}


# ── 1 · removing an object → detected as missing ────────────────────────────


def test_removed_object_is_detected_as_missing():
    room = _room()
    sofa = _sofa(room)
    scene_at_build_time = Scene(project_id="p", rooms=[room], objects=[sofa])
    built = _built([o.object_id for o in scene_at_build_time.objects])

    # The object is removed from the LIVE scene after the build/render, no
    # rebuild - exactly task.md §31 row 12's "moved post-capture".
    scene_now = Scene(project_id="p", rooms=[room], objects=[])
    evidence = verify_scene(scene_now, build_report=built, visibility_detail=[], render_ids=["corner_0"])

    assert evidence.scene_checks["render_matches_committed_scene"] == "fail"
    assert sofa.object_id in evidence.summary["drifted_object_ids"]
    assert not evidence.ok


def test_unchanged_scene_is_not_drifted():
    room = _room()
    sofa = _sofa(room)
    scene = Scene(project_id="p", rooms=[room], objects=[sofa])
    built = _built([sofa.object_id])
    evidence = verify_scene(scene, build_report=built, visibility_detail=[], render_ids=["corner_0"])
    assert evidence.scene_checks["render_matches_committed_scene"] == "pass"
    assert evidence.summary["drifted_object_ids"] == []


# ── 2 · moving an object into a wall → detected as intersecting ────────────


def test_object_moved_into_a_wall_is_detected_as_intersecting():
    # A room 0..5 x 0..5 with a real wall along its right edge (x=5): a sofa
    # pushed up against it collides.
    room = _room()
    wall = Wall(start=(5.0, 0.0), end=(5.0, 5.0))
    sofa = _sofa(room, position=(4.9, 0.0, 2.5))  # half the 2.0m-wide sofa sticks through x=5
    scene = Scene(project_id="p", rooms=[room], walls=[wall], objects=[sofa])
    built = _built([sofa.object_id])
    evidence = verify_scene(scene, build_report=built, visibility_detail=[], render_ids=[])

    assert evidence.scene_checks["severe_intersections"] == "fail"
    obj = next(o for o in evidence.per_object if o.scene_object_id == sofa.object_id)
    assert obj.checks["severe_intersections"] == "fail"
    assert not evidence.ok


# ── 3 · rotating an object 90° → detected as mis-oriented ──────────────────


def test_rotated_object_is_detected_as_mis_oriented():
    room = _room()
    sofa = _sofa(room, rotation_y=math.pi / 2)  # actually facing +X (90 deg)
    sofa.plan_key = "sofa_1"
    scene = Scene(project_id="p", rooms=[room], objects=[sofa])
    # The plan said face -Z (0 degrees) - a 90 degree mismatch.
    object_plan_items = {"sofa_1": {"facing_dir": (0.0, -1.0)}}
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[], object_plan_items=object_plan_items)

    obj = next(o for o in evidence.per_object if o.scene_object_id == sofa.object_id)
    assert obj.checks["orientation"] == "fail"
    assert not evidence.ok


def test_correctly_oriented_object_passes():
    room = _room()
    sofa = _sofa(room, rotation_y=0.0)
    sofa.plan_key = "sofa_1"
    scene = Scene(project_id="p", rooms=[room], objects=[sofa])
    object_plan_items = {"sofa_1": {"facing_dir": (0.0, -1.0)}}
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[], object_plan_items=object_plan_items)
    obj = next(o for o in evidence.per_object if o.scene_object_id == sofa.object_id)
    assert obj.checks["orientation"] == "pass"


# ── 5 · disabling a checker yields unknown, never a pass ────────────────────


def test_disabling_the_visibility_checker_yields_unknown_not_pass():
    """No `visibility_detail` supplied - as if check_visibility.py's step
    were disabled or skipped. The check must not default to pass."""
    room = _room()
    sofa = _sofa(room)
    scene = Scene(project_id="p", rooms=[room], objects=[sofa])
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[])
    obj = next(o for o in evidence.per_object if o.scene_object_id == sofa.object_id)
    assert obj.checks["major_objects_visible"] == "unknown"
    assert obj.visibility == "unknown"
    # unknown is not failure either - the overall verdict is not forced FAIL
    # by a checker that simply didn't run.
    assert evidence.ok


def test_disabling_the_entrance_point_yields_unknown_circulation_not_pass():
    room = _room()
    sofa = _sofa(room)
    scene = Scene(project_id="p", rooms=[room], objects=[sofa])
    evidence = verify_scene(scene, build_report={}, visibility_detail=[], render_ids=[], entrance_xz=None)
    assert evidence.scene_checks["circulation"] == "unknown"


# ── 4 · hiding an object behind another → detected as occluded (ray-cast) ──
# Needs a real camera + real geometry: real Blender.


@pytest.mark.blender
def test_hidden_object_is_detected_as_occluded_by_real_ray_cast(env, blender_path, tmp_path):
    """Builds a tiny real scene: a wide occluder wall directly between the
    camera and a small cube behind it. check_visibility.py's ray-cast must
    report the cube occluded, not visible - and must not need a model to
    say so."""
    from app.blender.runner import BlenderRunner

    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    script = tmp_path / "build_occlusion.py"
    script.write_text(
        """
import bpy, json, sys, os
sys.path.insert(0, os.environ["ALLURE_TEST_SCRIPTS_DIR"])
from _common import emit_result

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 3, 0.2))
hidden = bpy.context.active_object
hidden.name = "obj_hidden_cube"

bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 1.5, 1.0), rotation=(1.5708, 0, 0))
wall = bpy.context.active_object
wall.name = "occluder_wall"

out = os.environ["ALLURE_TEST_BLEND_OUT"]
bpy.ops.wm.save_as_mainfile(filepath=out)
emit_result({"ok": True, "blend": out})
""",
        encoding="utf-8",
    )
    blend_out = tmp_path / "occlusion.blend"
    import os as _os
    from app.core.config import get_settings

    _os.environ["ALLURE_TEST_BLEND_OUT"] = str(blend_out)
    _os.environ["ALLURE_TEST_SCRIPTS_DIR"] = str(get_settings().blender_scripts_dir)
    try:
        runner.run(str(script), log_path=tmp_path / "build.log")

        views_spec = tmp_path / "views.json"
        out_dir = tmp_path / "renders"
        out_dir.mkdir()
        import json as _json

        views_spec.write_text(_json.dumps({
            "out_dir": str(out_dir),
            "views": [{"name": "front", "position": [0.0, 0.0, 0.2], "look_at": [0.0, 3.0, 0.2]}],
        }), encoding="utf-8")

        vis = runner.run(
            "check_visibility.py", ["--spec", str(views_spec)],
            blend=blend_out, log_path=tmp_path / "visibility.log", timeout=120,
        )
        detail = {d["name"]: d for d in vis.result["detail"]}
        assert "obj_hidden_cube" in detail
        assert detail["obj_hidden_cube"]["visible"] == 0
        assert detail["obj_hidden_cube"]["in_frame"] > 0  # in frame, just blocked

        room = Room(name="r", type="living_room", boundary=[(-2, -2), (2, -2), (2, 4), (-2, 4)])
        obj = SceneObject(semantic_type="cube", asset_id="a", room_id=room.room_id,
                          position=(0.0, 0.2, 3.0), rotation_y=0.0, scale=(1, 1, 1),
                          dimensions=(0.4, 0.4, 0.4), mount="floor", object_id="obj_hidden_cube")
        scene = Scene(project_id="p", rooms=[room], objects=[obj])
        evidence = verify_scene(scene, build_report={}, visibility_detail=vis.result["detail"], render_ids=["front"])
        po = next(o for o in evidence.per_object if o.scene_object_id == "obj_hidden_cube")
        assert po.visibility == "occluded"
        assert po.checks["major_objects_visible"] == "fail"
        assert not evidence.ok
    finally:
        for k in ("ALLURE_TEST_BLEND_OUT", "ALLURE_TEST_SCRIPTS_DIR"):
            _os.environ.pop(k, None)

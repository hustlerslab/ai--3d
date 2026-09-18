"""Production contracts introduced by the research-to-production pass
(docs/production/research_to_production.md).

Guards: (1) the P5 `Wall.extrusion_direction` field is backward compatible and
the height-aware H2 check reproduces the old single-rectangle check exactly
for every vertical wall; (2) the research shims and the canonical app modules
expose the SAME objects (no second system); (3) `app/` never imports
`research/`; (4) the un-migrated research portions still exist where the
benchmarks expect them.
"""
from __future__ import annotations

import importlib
import math
import pkgutil
import re
from pathlib import Path

import app
from app.scene.schema import Room, Scene, SceneObject, Wall
from app.spatial import geometry as geo
from app.spatial.validation import object_footprint, validate_object
from app.spatial.wall_geometry import WORLD_UP, object_wall_collides

MIGRATED = {
    "collision_solver": "app.spatial.collision_solver",
    "clearance_engine": "app.spatial.clearance_engine",
    "repair_engine": "app.spatial.repair_engine",
    "wall_geometry": "app.spatial.wall_geometry",
    "coordinate_frames": "app.spatial.coordinate_frames",
    "transforms": "app.spatial.transforms",
    "frame_graph": "app.spatial.frame_graph",
    "relation_model": "app.spatial.relation_model",
    "scene_model": "app.spatial.scene_model",
    "scene_graph": "app.spatial.scene_graph",
    "scene_consistency": "app.spatial.scene_consistency",
    "scene_serialization": "app.spatial.scene_serialization",
    "intent_model": "app.planning.intent_model",
    "constraint_model": "app.planning.constraint_model",
    "constraint_compiler": "app.planning.constraint_compiler",
    "constraint_evaluator": "app.planning.constraint_evaluator",
    "candidate_model": "app.planning.candidate_model",
    "candidate_generators": "app.planning.candidate_generators",
    "candidate_filters": "app.planning.candidate_filters",
    "candidate_ranker": "app.planning.candidate_ranker",
}


def _scene() -> Scene:
    room = Room(room_id="r", name="room", boundary=[(0, 0), (5, 0), (5, 4), (0, 4)])
    walls = [Wall(wall_id="w0", start=(0, 0), end=(5, 0)), Wall(wall_id="w1", start=(5, 0), end=(5, 4)),
             Wall(wall_id="w2", start=(5, 4), end=(0, 4)), Wall(wall_id="w3", start=(0, 4), end=(0, 0))]
    return Scene(scene_id="s", project_id="p", rooms=[room], walls=walls)


def _obj(x: float, z: float, rot: float = 0.0, h: float = 0.9) -> SceneObject:
    return SceneObject(object_id="o", semantic_type="sofa", room_id="r", position=(x, 0.0, z),
                       rotation_y=rot, dimensions=(1.8, h, 0.9))


def test_wall_extrusion_direction_defaults_vertical_and_parses_old_json():
    assert Wall(start=(0, 0), end=(1, 0)).extrusion_direction == WORLD_UP
    old = Wall.model_validate({"wall_id": "w", "start": [0, 0], "end": [1, 0]})
    assert old.extrusion_direction == (0.0, 1.0, 0.0)


def test_h2_height_aware_equals_old_rectangle_test_for_every_vertical_wall():
    scene = _scene()
    xs = [i * 0.25 for i in range(-2, 23)]
    zs = [i * 0.25 for i in range(-2, 19)]
    checked = 0
    for x in xs:
        for z in zs:
            for rot in (0.0, math.pi / 4, math.pi / 2):
                obj = _obj(x, z, rot)
                footprint = object_footprint(obj)
                for wall in scene.walls:
                    old = geo.convex_polygons_overlap(
                        footprint, geo.wall_rectangle(wall.start, wall.end, wall.thickness))
                    assert object_wall_collides(obj, wall) is old, (x, z, rot, wall.wall_id)
                    checked += 1
    assert checked > 5000


def test_h2_reports_collides_wall_for_a_leaning_wall_only_where_it_leans():
    scene = _scene()
    # Object spans z in [0.35, 1.25]; the wall leans ~20 deg into +z, so its
    # cross-section drifts 0.36 m per metre of height: 0.87 m at the tall
    # object's top (collides), 0.14 m at the short one's (clears).
    tall = _obj(2.5, 0.8, h=2.4)
    assert not any(v.code == "COLLIDES_WALL" for v in validate_object(scene, tall))
    leaning = scene.walls[0].model_copy(update={"extrusion_direction": (0.0, 0.94, 0.34)})
    tilted = scene.model_copy(update={"walls": [leaning] + scene.walls[1:]})
    assert any(v.code == "COLLIDES_WALL" for v in validate_object(tilted, tall))
    short = _obj(2.5, 0.8, h=0.4)
    assert not any(v.code == "COLLIDES_WALL" for v in validate_object(tilted, short))


def test_research_shims_reexport_the_canonical_app_objects():
    for research_name, app_name in MIGRATED.items():
        shim = importlib.import_module(f"research.spatial_architecture.{research_name}")
        canonical = importlib.import_module(app_name)
        for name, value in vars(canonical).items():
            if name.startswith("__"):
                continue
            assert getattr(shim, name) is value, f"{research_name}.{name}"


def test_partially_migrated_modules_keep_their_research_only_portion():
    from research.spatial_architecture import failure_taxonomy, scene_optimizer
    from app.spatial.bounded_search import solve_backtracking
    from app.spatial.failures import FailureCategory

    assert scene_optimizer.solve_backtracking is solve_backtracking
    assert set(scene_optimizer.STRATEGIES) >= {"greedy", "beam_5", "greedy_then_repair"}
    assert failure_taxonomy.FailureCategory is FailureCategory
    assert len(failure_taxonomy.HISTORICAL_FAILURES) >= 13
    assert len(FailureCategory) == 12


def test_app_never_imports_research():
    pattern = re.compile(r"^\s*(from|import)\s+research\b", re.M)
    root = Path(app.__file__).parent
    offenders = [p for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_every_migrated_app_module_imports_cleanly():
    for mod in list(MIGRATED.values()) + ["app.spatial.bounded_search", "app.spatial.failures"]:
        importlib.import_module(mod)
    names = {m.name for m in pkgutil.iter_modules([str(Path(app.__file__).parent / "spatial")])}
    assert {"bounded_search", "failures", "repair_engine", "scene_graph"} <= names

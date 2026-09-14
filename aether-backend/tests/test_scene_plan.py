"""M3: layout, object plan, asset decision, compiler, scene_plan job, routes."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.intelligence import InputBundle, StyleSpec
from app.intelligence.mock_provider import MockProvider
from app.intelligence.schema import DesignAnalysis, ObjectPlanItem, RoomAnalysis
from app.planning import compile_scene, decide_asset, layout_rooms, place_objects, resolve_plan
from app.planning.layout import build_walls_and_openings, wall_segments
from app.projects import ProjectStage, get_project_store
from app.projects.layout import project_dir
from app.scene.store import get_store
from app.spatial.validation import validate_scene

BRIEF = (
    "2BHK in Pune for a young couple. Warm modern minimal with oak floors, a big sofa, "
    "a dining table for six and lots of plants. Keep the master bedroom calm."
)


def _analysis() -> DesignAnalysis:
    return MockProvider().analyze_input(InputBundle(project_id="p", description=BRIEF))


def _style(analysis) -> StyleSpec:
    return MockProvider().create_style_spec(analysis, InputBundle(project_id="p", description=BRIEF))


# ── layout ───────────────────────────────────────────────────────────────


def test_layout_is_non_overlapping_and_connected(env):
    rooms = _analysis().rooms
    placed = layout_rooms(rooms)
    assert [p.room_id for p in placed][0] == "living_room"
    # no two rooms overlap in area
    for a in placed:
        for b in placed:
            if a is b:
                continue
            ox = min(a.x1, b.x1) - max(a.x0, b.x0)
            oz = min(a.z1, b.z1) - max(a.z0, b.z0)
            assert not (ox > 1e-6 and oz > 1e-6), f"{a.room_id} overlaps {b.room_id}"
    # every non-hub room has a parent that exists
    ids = {p.room_id for p in placed}
    for p in placed[1:]:
        assert p.parent in ids
    segs = wall_segments(placed)
    keys = {(s.axis, s.c, s.p0, s.p1) for s in segs}
    assert len(keys) == len(segs)  # deduplicated
    shared = [s for s in segs if len(s.rooms) == 2]
    assert shared, "adjacent rooms must share walls"


def test_walls_openings_doors_and_windows(env):
    placed = layout_rooms(_analysis().rooms)
    walls, openings, warnings = build_walls_and_openings(placed)
    wall_ids = {w.wall_id for w in walls}
    assert all(o.wall_id in wall_ids for o in openings)
    doors = [o for o in openings if o.type.value == "door"]
    windows = [o for o in openings if o.type.value == "window"]
    assert any(o.opening_id == "open_entry" for o in doors)
    for p in placed[1:]:
        assert any(o.opening_id == f"open_door_{p.room_id}" for o in doors), p.room_id
    assert len(windows) >= len(placed) - 1
    for o in openings:  # openings fit inside their wall
        wall = next(w for w in walls if w.wall_id == o.wall_id)
        length = ((wall.end[0] - wall.start[0]) ** 2 + (wall.end[1] - wall.start[1]) ** 2) ** 0.5
        assert 0 < o.position - o.width / 2 and o.position + o.width / 2 < length
    assert warnings == []


def test_chained_rooms_when_stack_exceeds_hub(env):
    rooms = [
        RoomAnalysis(room_id="living_room", name="Living", type="living_room", width_m=4.0, length_m=3.0),
        RoomAnalysis(room_id="b1", name="B1", type="bedroom", width_m=3.5, length_m=3.0),
        RoomAnalysis(room_id="b2", name="B2", type="bedroom", width_m=3.5, length_m=3.0),
        RoomAnalysis(room_id="b3", name="B3", type="bedroom", width_m=3.5, length_m=3.0),
    ]
    placed = {p.room_id: p for p in layout_rooms(rooms)}
    assert placed["b1"].parent == "living_room"
    assert placed["b2"].parent == "b1"          # no overlap with the hub left
    assert placed["b3"].parent == "b2"
    _, openings, warnings = build_walls_and_openings(list(placed.values()))
    assert {o.opening_id for o in openings} >= {"open_door_b1", "open_door_b2", "open_door_b3", "open_entry"}
    assert warnings == []


# ── object plan + asset decision ─────────────────────────────────────────


def test_mock_object_plan_prioritises_brief_and_relations(env):
    analysis = _analysis()
    style = _style(analysis)
    plan = MockProvider().plan_objects(analysis, style, InputBundle(project_id="p", description=BRIEF))
    living = [i for i in plan.items if i.room_id == "living_room"]
    sofa = next(i for i in living if i.semantic_type == "sofa")
    assert sofa.priority == 1 and sofa.from_photo
    coffee = next(i for i in living if i.semantic_type == "coffee_table")
    assert coffee.relation and coffee.relation.type == "in_front_of" and coffee.relation.target_key == sofa.object_key
    # no dining room → dining set lands in the living room, chairs around the table
    table = next(i for i in living if i.semantic_type == "dining_table")
    chairs = next(i for i in living if i.semantic_type == "chair")
    assert chairs.relation and chairs.relation.type == "around" and chairs.relation.target_key == table.object_key
    bed = next(i for i in plan.items if i.room_id == "master_bedroom" and i.semantic_type == "bed")
    bedside = next(i for i in plan.items if i.room_id == "master_bedroom" and i.semantic_type == "bedside_table")
    assert bedside.count == 2 and bedside.relation.target_key == bed.object_key
    assert len({i.object_key for i in plan.items}) == len(plan.items)


def test_asset_decision_procedural_without_models_and_local_with_model(env, tmp_path):
    style = StyleSpec(name="warm_modern", tags=["warm", "modern"], materials=["fabric_linen", "veneer_oak", "metal_black"])
    item = ObjectPlanItem(object_key="living_room.sofa.1", semantic_type="sofa", room_id="living_room")
    d = decide_asset(item, style)
    assert d.strategy == "procedural" and d.asset_id == "cat_sofa_3s" and not d.has_model
    assert d.material_overrides == {"primary": "fabric_linen"}
    generic = decide_asset(ObjectPlanItem(object_key="e.console.1", semantic_type="console", room_id="e"), style)
    assert generic.strategy == "procedural" and generic.asset_id is None and generic.dimensions == (1.2, 0.8, 0.35)

    # ingest a real model of a sofa → local_asset / local_modified
    from tests.test_assets_pipeline import write_box_gltf
    from app.assets import pipeline
    from app.assets.schema import AssetSource, IngestMeta

    path = write_box_gltf(tmp_path, size=(2.1, 0.85, 0.9))
    pipeline.ingest_file(
        path,
        IngestMeta(name="Box Sofa", semantic_type="sofa", source=AssetSource(provider="local", source_id="box", license="CC0")),
    )
    exact = decide_asset(ObjectPlanItem(object_key="l.sofa.2", semantic_type="sofa", room_id="l", approx_dimensions=(2.0, 0.85, 0.9)), style)
    assert exact.strategy == "local_asset" and exact.has_model
    scaled = decide_asset(ObjectPlanItem(object_key="l.sofa.3", semantic_type="sofa", room_id="l", approx_dimensions=(1.7, 0.85, 0.9)), style)
    assert scaled.strategy == "local_modified" and scaled.scale[0] < 1.0


def test_resolve_plan_counts(env):
    analysis = _analysis()
    style = _style(analysis)
    plan = MockProvider().plan_objects(analysis, style, InputBundle(project_id="p", description=BRIEF))
    assets = resolve_plan(plan, style)
    assert len(assets.decisions) == len(plan.items)
    assert sum(assets.counts.values()) == len(plan.items)
    assert assets.counts.get("procedural", 0) > 0


# ── compiler ─────────────────────────────────────────────────────────────


def test_compile_and_place_produces_valid_scene(env):
    analysis = _analysis()
    style = _style(analysis)
    scene, warnings = compile_scene("proj_x", analysis, style, name="test")
    assert len(scene.rooms) == 4 and scene.walls and scene.openings
    assert scene.style and scene.style.name == style.name
    assert scene.lighting and len(scene.lighting.interior_lights) == 4
    assert scene.rooms[1].floor_material != scene.rooms[0].floor_material or scene.rooms[1].type != "kitchen"
    plan = MockProvider().plan_objects(analysis, style, InputBundle(project_id="p", description=BRIEF))
    assets = resolve_plan(plan, style)
    ops, place_warnings = place_objects(scene, plan, assets)
    assert len(ops) >= 12, place_warnings
    scene.objects = [op.object for op in ops]
    hard = [v for v in validate_scene(scene) if v.severity == "hard"]
    assert hard == [], hard
    sofa = next(o for o in scene.objects if o.semantic_type == "sofa")
    coffee = next(o for o in scene.objects if o.semantic_type == "coffee_table")
    dist = ((sofa.position[0] - coffee.position[0]) ** 2 + (sofa.position[2] - coffee.position[2]) ** 2) ** 0.5
    assert dist < 2.4  # centre to centre: half sofa + half table + walking gap
    assert sofa.source_strategy == "procedural" and sofa.material_overrides.get("primary")
    chairs = [o for o in scene.objects if o.semantic_type == "chair"]
    assert len(chairs) == 4


# ── job + routes ─────────────────────────────────────────────────────────


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _prepared_project(client, tmp_path) -> str:
    from app.jobs import get_runner

    pid = client.post("/api/projects", json={"name": "Pune 2BHK"}).json()["project"]["project_id"]
    img = tmp_path / "ref.png"
    Image.new("RGB", (64, 64), (180, 150, 120)).save(img)
    client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF},
                files=[("references", ("ref.png", img.read_bytes(), "image/png"))])
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(30)
    return pid


def test_scene_plan_job_end_to_end(client, tmp_path):
    from app.jobs import get_runner

    pid = _prepared_project(client, tmp_path)
    r = client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert get_runner().wait_idle(60)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
    assert polled["status"] == "SUCCEEDED", polled["error"]
    result = polled["result"]
    assert result["rooms"] == 4 and result["objects"] >= 12 and result["hard_violations"] == 0

    root = project_dir(pid)
    for name in ("object_plan.json", "asset_plan.json", "scene_spec.json"):
        assert (root / "planning" / name).exists(), name
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["project"]["stage"] == "ASSETS_READY"
    assert result["scene_id"] in detail["project"]["scene_ids"]

    spec = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]
    assert spec["scene"]["scene_id"] == result["scene_id"]
    assert spec["scene"]["style"]["name"] == "warm_modern_minimal"
    assert spec["violations"] == [] or all(v["severity"] != "hard" for v in spec["violations"])
    assert spec["asset_plan"]["counts"]
    assert spec["scene_specs"][0]["scene_id"] == result["scene_id"]

    # the scene is a normal scene: existing endpoints work on it
    scene = client.get(f"/api/scenes/{result['scene_id']}").json()["data"]
    assert scene["scene"]["version"] == 1 if "scene" in scene else True
    tour = client.get(f"/api/scenes/{result['scene_id']}/walkthrough/tour").json()["data"]
    assert tour["keyframes"]

    # re-run without force: everything skipped, same scene
    job2 = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    assert get_runner().wait_idle(60)
    events = client.get(f"/api/jobs/{job2['job_id']}").json()["data"]["events"]
    # Four checkpointed steps now: scene reading, object plan, asset plan,
    # scene spec. The reading was added when the approved moodboard became the
    # brief for the 3D build.
    assert sum("skipped" in e["message"] for e in events) == 4


def test_scene_plan_requires_analysis(client):
    pid = client.post("/api/projects", json={"name": "Empty"}).json()["project"]["project_id"]
    r = client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ANALYSIS_REQUIRED"
    r = client.get(f"/api/projects/{pid}/scene-spec")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SCENE_NOT_READY"
    r = client.post(f"/api/projects/{pid}/assets/resolve")
    assert r.status_code == 409


def test_resolve_assets_upgrades_to_registry_model(client, tmp_path):
    from app.jobs import get_runner
    from tests.test_assets_pipeline import write_box_gltf
    from app.assets import pipeline
    from app.assets.schema import AssetSource, IngestMeta

    pid = _prepared_project(client, tmp_path)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(60)
    before = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]["scene"]
    sofa_before = next(o for o in before["objects"] if o["semantic_type"] == "sofa")
    assert sofa_before["source_strategy"] == "procedural"

    path = write_box_gltf(tmp_path, size=(2.1, 0.85, 0.9))
    pipeline.ingest_file(path, IngestMeta(name="Box Sofa", semantic_type="sofa",
                                          source=AssetSource(provider="local", source_id="box", license="CC0")))
    r = client.post(f"/api/projects/{pid}/assets/resolve")
    assert r.status_code == 200, r.text
    assert get_runner().wait_idle(60)
    job = client.get(f"/api/jobs/{r.json()['job']['job_id']}").json()["data"]["job"]
    assert job["status"] == "SUCCEEDED", job["error"]
    assert job["result"]["replaced"] >= 1
    after = client.get(f"/api/projects/{pid}/scene-spec").json()["data"]["scene"]
    sofa_after = next(o for o in after["objects"] if o["semantic_type"] == "sofa")
    assert sofa_after["asset_id"] != sofa_before["asset_id"]
    assert after["version"] == before["version"] + 1


def test_wall_placed_furniture_faces_into_the_room(env):
    """Audit B1: every wall-aligned piece must face the room centre, not the wall."""
    import math

    analysis = _analysis()
    style = _style(analysis)
    scene, _ = compile_scene("proj_x", analysis, style, name="facing")
    plan = MockProvider().plan_objects(analysis, style, InputBundle(project_id="p", description=BRIEF))
    ops, _ = place_objects(scene, plan, resolve_plan(plan, style))
    scene.objects = [op.object for op in ops]
    from app.spatial import geometry as geo

    checked = 0
    for o in scene.objects:
        if o.semantic_type not in ("sofa", "bed", "wardrobe", "tv_unit", "kitchen_counter", "curtains", "dresser", "bookshelf"):
            continue
        room = scene.room(o.room_id)
        cx, cz = geo.polygon_centroid(room.boundary)
        fx, fz = -math.sin(o.rotation_y), -math.cos(o.rotation_y)
        vx, vz = cx - o.position[0], cz - o.position[2]
        d = math.hypot(vx, vz)
        if d < 0.6:
            continue  # sits at the centre: no meaningful direction
        assert (fx * vx + fz * vz) / d > 0.2, f"{o.semantic_type} in {o.room_id} faces away from the room"
        checked += 1
    assert checked >= 5

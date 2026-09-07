"""Schema 1.1: open scene reading, crops, surfaces and the asset ladder."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.blender.manifest import build_manifest
from app.intelligence import InputBundle
from app.intelligence.coerce import coerce_analysis, coerce_object_plan
from app.intelligence.crops import write_crops
from app.intelligence.mock_provider import MockProvider
from app.intelligence.schema import ReferenceImage, SpottedObject
from app.planning import compile_scene, decide_asset, place_objects, resolve_plan
from app.intelligence.schema import ObjectPlanItem
from app.spatial.validation import validate_scene

BRIEF = "2BHK in Pune for a young couple. Warm modern minimal with oak floors, a big sofa and lots of plants."

RAW_ANALYSIS = {
    "intent": "Warm traditional living room",
    "rooms": [{"name": "Living Room", "type": "living_room", "width_m": 6.0, "length_m": 4.6, "estimated": True}],
    "spotted_objects": [
        {"name": "mahogany secretary bookcase with fretwork doors", "family": "storage", "semantic_type": "cabinet",
         "placement": "floor", "room_name": "Living Room", "material": "mahogany", "color": "5A2E1B",
         "approx_dimensions": [1.2, 2.2, 0.5], "image_index": 0, "bbox": [0.35, 0.15, 0.62, 0.62], "confidence": 0.9},
        {"name": "blue and white pagoda ornament", "family": "ornament", "semantic_type": "decor",
         "placement": "on_surface", "support": "fireplace mantel", "room_name": "Living Room",
         "image_index": 0, "bbox": [950, 150, 990, 210], "confidence": 0.8},
        {"name": "white fireplace mantel", "family": "architecture", "semantic_type": "fireplace",
         "placement": "floor", "room_name": "Living Room", "approx_dimensions": [1.5, 1.2, 0.35]},
        {"name": "kilim rug", "family": "textile", "semantic_type": "rug", "placement": "floor",
         "room_name": "Living Room", "image_index": 0, "bbox": [0.45, 0.7, 0.75, 1.0]},
        {"name": "something odd", "family": "other", "semantic_type": "gizmo", "placement": "floor", "room_name": "Living Room"},
    ],
    "architecture": ["cornice", "castle_turret"],
    "keywords": ["traditional", "warm"],
    "confidence": 0.85,
}


def _photo(path: Path) -> Path:
    im = Image.new("RGB", (400, 300), (200, 190, 170))
    for x in range(140, 250):
        for y in range(45, 186):
            im.putpixel((x, y), (90, 46, 27))
    im.save(path)
    return path


def test_coerce_keeps_open_items_and_maps_names(env, tmp_path):
    photo = _photo(tmp_path / "ref.png")
    bundle = InputBundle(project_id="p", description=BRIEF, references=[ReferenceImage(path=str(photo))])
    analysis = coerce_analysis(RAW_ANALYSIS, bundle, [], provider="test")
    by_name = {s.name: s for s in analysis.spotted_objects}
    assert by_name["mahogany secretary bookcase with fretwork doors"].semantic_type == "bookshelf"  # mapped from the name
    assert by_name["mahogany secretary bookcase with fretwork doors"].color == "#5A2E1B"
    pagoda = by_name["blue and white pagoda ornament"]
    assert pagoda.semantic_type == "sculpture" and pagoda.placement == "on_surface" and pagoda.support == "fireplace mantel"
    assert pagoda.bbox == (0.95, 0.15, 0.99, 0.21)  # 0..1000 boxes are normalised
    assert by_name["something odd"].semantic_type == "other" and by_name["something odd"].family == "other"
    assert analysis.architecture == ["cornice"]
    assert all(s.room_id == "living_room" for s in analysis.spotted_objects)


def test_crops_are_written_for_boxed_items(env, tmp_path):
    photo = _photo(tmp_path / "ref.png")
    bundle = InputBundle(project_id="p", description=BRIEF, references=[ReferenceImage(path=str(photo))])
    analysis = coerce_analysis(RAW_ANALYSIS, bundle, [], provider="test")
    root = tmp_path / "proj"
    warnings = write_crops(analysis, bundle, root)
    crops = [s for s in analysis.spotted_objects if s.crop_ref]
    assert {s.name for s in crops} == {"mahogany secretary bookcase with fretwork doors", "kilim rug"}
    assert any("pagoda" in w and "too small" in w for w in warnings)
    for s in crops:
        assert (root / s.crop_ref).exists()
    with Image.open(root / crops[0].crop_ref) as im:
        assert im.size[0] > 100 and im.getpixel((im.size[0] // 2, im.size[1] // 2))[0] < 120  # the dark cabinet
    # a second run reuses the files
    assert write_crops(analysis, bundle, root) == warnings


def test_object_plan_carries_reading_and_restores_dropped_items(env, tmp_path):
    bundle = InputBundle(project_id="p", description=BRIEF, references=[ReferenceImage(path=str(_photo(tmp_path / "r.png")))])
    analysis = coerce_analysis(RAW_ANALYSIS, bundle, [], provider="test")
    write_crops(analysis, bundle, tmp_path / "proj")
    raw_plan = {
        "items": [
            {"object_key": "living_room.fireplace.1", "name": "white fireplace mantel", "family": "architecture",
             "semantic_type": "fireplace", "room_id": "living_room", "placement": "floor", "spotted_index": 2, "priority": 1, "count": 1},
            {"object_key": "living_room.sculpture.1", "name": "pagoda", "family": "ornament", "semantic_type": "sculpture",
             "room_id": "living_room", "placement": "on_surface", "support_key": "living_room.fireplace.1", "spotted_index": 1,
             "priority": 1, "count": 1},
            {"object_key": "living_room.sofa.1", "semantic_type": "sofa", "room_id": "living_room", "priority": 1, "count": 1},
        ],
        "confidence": 0.8,
    }
    plan = coerce_object_plan(raw_plan, analysis, provider="test")
    keys = {i.object_key: i for i in plan.items}
    assert keys["living_room.sculpture.1"].support_key == "living_room.fireplace.1"
    # the bookcase, rug and odd item were dropped by the planner: the reading puts them back with their crops
    restored = [i for i in plan.items if i.spotted_index in (0, 3, 4)]
    assert len(restored) == 3
    rug = next(i for i in restored if i.semantic_type == "rug")
    assert rug.crop_ref.startswith("analysis/crops/") and rug.from_photo
    assert any("dropped" in w for w in plan.warnings)


def test_asset_ladder_textures_flat_items_and_sizes_open_ones(env):
    style = MockProvider().create_style_spec(MockProvider().analyze_input(InputBundle(project_id="p", description=BRIEF)),
                                             InputBundle(project_id="p", description=BRIEF))
    art = decide_asset(ObjectPlanItem(object_key="k1", semantic_type="wall_art", room_id="living_room", name="framed print",
                                      family="art", placement="wall", crop_ref="analysis/crops/00_art.png"), style)
    assert art.strategy == "procedural" and art.texture_ref == "analysis/crops/00_art.png" and art.shape == "photo"
    assert art.mount == "wall"
    odd = decide_asset(ObjectPlanItem(object_key="k2", semantic_type="other", room_id="living_room", name="carved totem",
                                      family="ornament", placement="on_surface"), style)
    assert odd.strategy == "procedural" and odd.mount == "surface" and odd.dimensions == (0.25, 0.35, 0.25)
    assert "family" in odd.reason
    lamp = decide_asset(ObjectPlanItem(object_key="k3", semantic_type="table_lamp", room_id="bedroom", placement="on_surface"), style)
    assert lamp.shape == "lamp" and lamp.mount == "surface"
    fire = decide_asset(ObjectPlanItem(object_key="k4", semantic_type="fireplace", room_id="living_room", family="architecture"), style)
    assert fire.shape == "fireplace" and fire.mount == "floor"


def _reading_scene(tmp_path):
    m = MockProvider()
    bundle = InputBundle(project_id="p", description=BRIEF)
    analysis = m.analyze_input(bundle)
    lr = analysis.rooms[0].room_id
    analysis.spotted_objects += [
        SpottedObject(semantic_type="fireplace", name="white fireplace mantel", family="architecture", placement="floor",
                      room_id=lr, approx_dimensions=(1.5, 1.2, 0.35)),
        SpottedObject(semantic_type="sculpture", name="blue and white pagoda ornament", family="ornament", placement="on_surface",
                      support="white fireplace mantel", room_id=lr, approx_dimensions=(0.15, 0.3, 0.15), color="#2B4C8C"),
        SpottedObject(semantic_type="side_table", name="mahogany side table", family="table", placement="floor", room_id=lr,
                      approx_dimensions=(0.6, 0.7, 0.45)),
        SpottedObject(semantic_type="table_lamp", name="ginger jar lamp", family="lighting", placement="on_surface",
                      support="mahogany side table", room_id=lr, approx_dimensions=(0.35, 0.65, 0.35)),
        SpottedObject(semantic_type="wall_art", name="framed art", family="art", placement="wall", room_id=lr,
                      approx_dimensions=(0.9, 0.7, 0.05), crop_ref="analysis/crops/07_framed_art.png"),
        SpottedObject(semantic_type="pillows", name="rust velvet pillows", family="textile", placement="on_surface",
                      support="sofa", room_id=lr, count=2, color="#9C5A2E"),
    ]
    analysis.architecture = ["cornice"]
    style = m.create_style_spec(analysis, bundle)
    plan = m.plan_objects(analysis, style, bundle)
    assets = resolve_plan(plan, style)
    scene, _ = compile_scene("proj_x", analysis, style, name="reading")
    ops, warnings = place_objects(scene, plan, assets)
    scene.objects = [op.object for op in ops]
    return scene, warnings


def test_surfaces_and_wall_hanging(env, tmp_path):
    scene, warnings = _reading_scene(tmp_path)
    assert [v for v in validate_scene(scene) if v.severity == "hard"] == []
    by_id = {o.object_id: o for o in scene.objects}
    lr = scene.rooms[0]
    assert lr.features == ["cornice"]

    lamp = next(o for o in scene.objects if o.semantic_type == "table_lamp" and o.room_id == lr.room_id)
    host = by_id[lamp.parent_id]
    assert host.semantic_type == "side_table" and lamp.mount == "surface"
    assert abs(lamp.position[1] - (host.position[1] + host.dimensions[1] * host.scale[1])) < 1e-6
    # the lamp stands within the table top
    assert abs(lamp.position[0] - host.position[0]) <= host.dimensions[0] * host.scale[0] / 2
    assert abs(lamp.position[2] - host.position[2]) <= host.dimensions[2] * host.scale[2] / 2

    pagoda = next(o for o in scene.objects if o.semantic_type == "sculpture")
    assert by_id[pagoda.parent_id].semantic_type == "fireplace" and pagoda.position[1] > 1.1

    pillows = [o for o in scene.objects if o.semantic_type == "pillows"]
    assert len(pillows) == 2 and all(by_id[p.parent_id].semantic_type == "sofa" for p in pillows)
    assert pillows[0].position[:1] != pillows[1].position[:1]  # two corners, not one spot

    art = next(o for o in scene.objects if o.semantic_type == "wall_art" and o.room_id == lr.room_id)
    assert art.mount == "wall" and 1.0 <= art.position[1] <= 1.4 and art.shape == "photo"
    assert art.texture_ref == "analysis/crops/07_framed_art.png"
    # hung on a wall: within ~20 cm of a boundary edge, not over a window
    xs = [p[0] for p in lr.boundary]
    zs = [p[1] for p in lr.boundary]
    edge = min(abs(art.position[0] - min(xs)), abs(art.position[0] - max(xs)), abs(art.position[2] - min(zs)), abs(art.position[2] - max(zs)))
    assert edge < 0.25
    for o in scene.openings:
        if o.type.value != "window":
            continue
        w = scene.wall(o.wall_id)
        from app.spatial import geometry as geo

        c = geo.segment_lerp(w.start, w.end, o.position / (geo.distance(w.start, w.end) or 1.0))
        assert geo.distance(c, (art.position[0], art.position[2])) > 0.5 + o.width / 2 or abs(c[0] - art.position[0]) > 0.6 and abs(c[1] - art.position[2]) > 0.6


def test_manifest_carries_textures_surfaces_and_features(env, tmp_path):
    scene, _ = _reading_scene(tmp_path)
    crop = tmp_path / "analysis" / "crops" / "07_framed_art.png"
    crop.parent.mkdir(parents=True)
    Image.new("RGB", (64, 48), (120, 80, 60)).save(crop)
    manifest = build_manifest(scene, project_id="proj_x", project_root=tmp_path, preview=False)
    assert manifest["manifest_version"] == "1.1"
    assert manifest["rooms"][0]["features"] == ["cornice"]
    art = next(o for o in manifest["objects"] if o["semantic_type"] == "wall_art" and o["room_id"] == scene.rooms[0].room_id)
    assert art["asset"]["shape"] == "photo" and art["asset"]["texture"] == str(crop)
    lamp = next(o for o in manifest["objects"] if o["semantic_type"] == "table_lamp")
    assert lamp["mount"] == "surface" and lamp["parent"] and lamp["asset"]["shape"] == "lamp"
    assert lamp["location"][2] > 0.5  # Blender z = scene y: on the table, not the floor

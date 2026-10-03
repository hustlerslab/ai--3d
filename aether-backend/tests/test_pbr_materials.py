"""P2-RENDER-001: registry roughness drives the render - glTF metallic-roughness
semantics (roughness = factor x map, or the factor alone when there is no map).

Unit tests for the ingest rule run in the MOCK class; the render and node-graph
tests run real Blender.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from app.assets.schema import AssetSource
from app.materials import pipeline as material_pipeline
from app.materials.registry import get_material_registry

SRC = AssetSource(provider="local", source_id="test", license="CC0")


def _maps(material_id: str, grey: int = 128) -> dict[str, Path]:
    d = get_material_registry().material_dir(material_id)
    d.mkdir(parents=True, exist_ok=True)
    color, rough = d / "color.png", d / "rough.png"
    Image.new("RGB", (16, 16), (170, 130, 90)).save(color)
    Image.new("L", (16, 16), grey).save(rough)
    return {"color": color, "roughness": rough}


# ── the ingest rule (MOCK) ──────────────────────────────────────────────────


def test_a_new_scan_with_a_roughness_map_renders_as_scanned(env):
    rec = material_pipeline.attach_maps("scan_oak", _maps("scan_oak"), SRC, category="wood")
    assert rec.roughness == 1.0, "factor 1.0: the map is used exactly as scanned"


def test_an_explicit_roughness_wins_at_ingest(env):
    rec = material_pipeline.attach_maps("scan_ash", _maps("scan_ash"), SRC, category="wood", roughness=0.4)
    assert rec.roughness == 0.4


def test_an_existing_record_keeps_its_roughness(env):
    """Re-attaching maps to a material that already exists never rewrites a
    value someone set - migrating existing scans is a reviewed decision."""
    registry = get_material_registry()
    base = registry.get("wood_oak")
    assert base is not None and not base.has_maps
    rec = material_pipeline.attach_maps("wood_oak", _maps("wood_oak"), SRC)
    assert rec.roughness == base.roughness


def test_a_scan_without_a_roughness_map_keeps_the_scalar_default(env):
    d = get_material_registry().material_dir("scan_paint")
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (200, 200, 200)).save(d / "color.png")
    rec = material_pipeline.attach_maps("scan_paint", {"color": d / "color.png"}, SRC)
    assert rec.roughness == 0.8


# ── real Blender ────────────────────────────────────────────────────────────

INSPECT = textwrap.dedent("""
    import bpy, os, sys
    sys.path.insert(0, os.environ["ALLURE_TEST_SCRIPTS_DIR"])
    from _common import emit_result
    out = {}
    for m in bpy.data.materials:
        if not m.use_nodes or not m.name.startswith(os.environ["ALLURE_TEST_MATERIAL"] + "|"):
            continue
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        sock = bsdf.inputs["Roughness"]
        src = sock.links[0].from_node if sock.links else None
        out[m.name] = {"linked_from": src.bl_idname if src else None,
                       "factor": src.inputs[1].default_value if src and src.bl_idname == "ShaderNodeMath" else None,
                       "scalar": sock.default_value}
    emit_result({"ok": True, "materials": out})
""")


def _build_with_floor(root: Path, material_id: str, blender_path: str) -> tuple[Path, Path]:
    from app.blender.manifest import build_manifest, write_manifest
    from app.blender.runner import BlenderRunner
    from tests.test_blender_build import _compiled_scene

    scene = _compiled_scene()
    for room in scene.rooms:
        room.floor_material = material_id
    manifest = build_manifest(scene, project_id="proj_pbr", project_root=root, preview=True, preview_profile="preview")
    assert material_id in manifest["materials"], "the floor material crosses to Blender"
    path = root / "blender" / "build_manifest.json"
    write_manifest(manifest, path)
    res = BlenderRunner(blender_path=blender_path, timeout=300).run(
        "build_scene.py", ["--manifest", str(path)], log_path=root / "build.log")
    return Path(res.result["preview"]), Path(res.result["blend"])


def _inspect(blend: Path, material_id: str, blender_path: str, tmp: Path) -> dict:
    from app.blender.runner import BlenderRunner

    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    script = tmp / "inspect.py"
    script.write_text(INSPECT, encoding="utf-8")
    os.environ["ALLURE_TEST_SCRIPTS_DIR"] = str(runner.scripts_dir)
    os.environ["ALLURE_TEST_MATERIAL"] = material_id
    try:
        return runner.run(str(script), blend=blend, log_path=tmp / "inspect.log").result["materials"]
    finally:
        os.environ.pop("ALLURE_TEST_SCRIPTS_DIR", None)
        os.environ.pop("ALLURE_TEST_MATERIAL", None)


def _changed_fraction(a: Path, b: Path) -> float:
    import numpy as np

    pa = np.array(Image.open(a).convert("RGB"), dtype=float)
    pb = np.array(Image.open(b).convert("RGB"), dtype=float)
    return float((abs(pa - pb).max(axis=2) > 10).mean())


def _set_roughness(material_id: str, value: float) -> None:
    registry = get_material_registry()
    rec = registry.get(material_id)
    rec.roughness = value
    registry.upsert(rec)


@pytest.mark.blender
def test_changing_a_registry_roughness_changes_the_render(env, blender_path, tmp_path):
    """A material with no map: the scalar path."""
    renders = {}
    for value in (0.9, 0.05):
        _set_roughness("wood_oak", value)
        renders[value], _ = _build_with_floor(tmp_path / f"scalar_{value}", "wood_oak", blender_path)
    assert _changed_fraction(renders[0.9], renders[0.05]) > 0.001


@pytest.mark.blender
def test_a_mapped_material_multiplies_its_map_by_the_registry_roughness(env, blender_path, tmp_path):
    """The gap this task closes: a roughness map used to replace the registry
    value, so changing it changed nothing. Now the map is multiplied by it -
    in the node graph Blender actually built, and in the pixels."""
    material_pipeline.attach_maps("scan_floor", _maps("scan_floor", grey=200), SRC, category="wood")
    renders = {}
    for value in (1.0, 0.1):
        _set_roughness("scan_floor", value)
        root = tmp_path / f"mapped_{value}"
        renders[value], blend = _build_with_floor(root, "scan_floor", blender_path)
        graph = _inspect(blend, "scan_floor", blender_path, root)
        assert graph, "the mapped floor material was built"
        for name, g in graph.items():
            assert g["linked_from"] == "ShaderNodeMath", f"{name}: the map must pass through the factor"
            assert abs(g["factor"] - value) < 1e-6, f"{name}: factor {g['factor']} != registry {value}"
    assert _changed_fraction(renders[1.0], renders[0.1]) > 0.001


# ── every asset is glTF metallic-roughness (MOCK) ──────────────────────────

from app.assets.gltf import GltfDocument  # noqa: E402
from app.assets.validation import SPEC_GLOSS, material_workflow  # noqa: E402


def _doc(materials, used=()):
    return GltfDocument(json={"asset": {"version": "2.0"}, "materials": materials,
                              "extensionsUsed": list(used)}, buffers=[])


def test_a_metallic_roughness_asset_passes():
    assert material_workflow(_doc([{"name": "oak", "pbrMetallicRoughness": {"roughnessFactor": 0.7}}])) == []


def test_a_specular_glossiness_asset_is_refused():
    found = material_workflow(_doc([{"name": "oak", "extensions": {SPEC_GLOSS: {}}}], used=[SPEC_GLOSS]))
    assert [(i.code, i.severity) for i in found] == [("NOT_METALLIC_ROUGHNESS", "hard")]


def test_a_material_without_metallic_roughness_values_is_warned_as_bare_metal():
    found = material_workflow(_doc([{"name": "seat fabric"}]))
    assert [(i.code, i.severity) for i in found] == [("MATERIAL_DEFAULTS_TO_METAL", "warn")]
    assert "seat fabric" in found[0].message


def test_a_specular_glossiness_upload_is_kept_out_of_the_catalog(env, tmp_path):
    """Through the real ingest pipeline: the hard issue keeps it out."""
    import json as _json

    from app.assets import pipeline
    from app.assets.schema import IngestMeta
    from tests.test_asset_forward_axis import write_boxes_gltf

    path = write_boxes_gltf(tmp_path / "specgloss.gltf", [((-0.3, 0.0, -0.3), (0.3, 0.8, 0.3))])
    doc = _json.loads(path.read_text("utf-8"))
    doc["extensionsUsed"] = [SPEC_GLOSS]
    doc["materials"] = [{"name": "old", "extensions": {SPEC_GLOSS: {"diffuseFactor": [1, 1, 1, 1]}}}]
    doc["meshes"][0]["primitives"][0]["material"] = 0
    path.write_text(_json.dumps(doc), "utf-8")
    record = pipeline.ingest_file(path, IngestMeta(asset_id="specgloss", name="old", semantic_type="chair"))
    assert any(v.code == "NOT_METALLIC_ROUGHNESS" for v in record.validation)
    assert not record.valid


def test_the_library_audit_runs_and_lists_scans_to_review(env):
    """The audit for the machine that holds the real library: here, one scan
    registered 'before' the change (factor 0.8) is listed for review, and one
    registered since (factor 1.0) is not."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit", Path(__file__).resolve().parents[1] / "scripts" / "audit_material_workflow.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    material_pipeline.attach_maps("scan_new", _maps("scan_new"), SRC)
    registry = get_material_registry()
    legacy = material_pipeline.attach_maps("scan_legacy", _maps("scan_legacy"), SRC)
    legacy.roughness = 0.8                                   # as a pre-change scan would carry
    registry.upsert(legacy)
    report = audit.audit()
    review = {m["material_id"]: m["review"] for m in report["mapped_materials"]}
    assert review == {"scan_legacy": True, "scan_new": False}


def test_editing_a_built_in_material_does_not_leak_into_the_next_registry(env, tmp_path):
    """Found while writing this task: the registry handed out the module-level
    seed objects, so an in-memory edit to a built-in (a roughness change,
    attach_maps) leaked into every registry built later in the process."""
    from app.materials.registry import MaterialRegistry
    from app.materials.seed import BUILTIN_MATERIALS

    seed = next(m for m in BUILTIN_MATERIALS if m.material_id == "wood_oak")
    before = seed.roughness
    first = MaterialRegistry(tmp_path / "a")
    first.get("wood_oak").roughness = 0.01                  # not persisted: a built-in without maps
    assert seed.roughness == before, "the seed itself was mutated"
    assert MaterialRegistry(tmp_path / "b").get("wood_oak").roughness == before

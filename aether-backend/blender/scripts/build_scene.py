"""Orchestrator: build a scene from build_manifest.json (DPR §12–§14).

    blender -b --factory-startup --python-exit-code 1 \
        --python build_scene.py -- --manifest <path> [--no-preview] [--stop-after <stage>]

Stages, each logged as `ALLURE_STAGE <name> <seconds>` and checkpointed by
saving the .blend: reset → rooms → walls → objects → materials → lighting →
camera → save → validate → preview. Business logic stays in the backend:
this file only executes the manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from _common import Timer, emit_result, fail, parse
import apply_materials
import build_room
import import_assets
import render_preview
import setup_lighting
import validate_scene


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium Contrast"
    except TypeError:
        pass
    scene.render.film_transparent = False


def stage(name: str, timer: Timer, stages: dict) -> None:
    stages[name] = round(timer.seconds, 2)
    print(f"ALLURE_STAGE {name} {stages[name]}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--stop-after", default="")
    ns = parse(parser)

    with open(ns.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    out = manifest["output"]
    os.makedirs(os.path.dirname(out["blend"]), exist_ok=True)

    timer = Timer()
    stages: dict[str, float] = {}
    warnings: list[str] = []

    reset_scene()
    stage("reset", timer, stages)

    collections = build_room.make_collections(manifest)
    materials = apply_materials.MaterialLibrary(manifest.get("materials", {}), manifest.get("style", {}))
    build_room.build_rooms(manifest, collections, materials)
    stage("rooms", timer, stages)
    build_room.build_walls(manifest, collections, materials, warnings)
    build_room.build_exterior(manifest, collections, materials)
    stage("walls", timer, stages)

    placed = import_assets.build_objects(manifest, collections, materials, warnings)
    stage("objects", timer, stages)
    bpy.ops.wm.save_as_mainfile(filepath=out["blend"])
    stage("materials", timer, stages)

    setup_lighting.setup(manifest, collections, warnings)
    stage("lighting", timer, stages)

    camera = render_preview.setup_camera(manifest)
    stage("camera", timer, stages)

    bpy.ops.wm.save_as_mainfile(filepath=out["blend"])
    stage("save", timer, stages)

    report = validate_scene.validate(manifest, placed, warnings)
    report["stages"] = stages
    with open(out["report"], "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    stage("validate", timer, stages)

    preview_path = ""
    if out.get("preview") and not ns.no_preview and ns.stop_after != "validate":
        preview_path = render_preview.render_still(manifest, camera, out["preview"], out.get("preview_profile", "preview"))
        stage("preview", timer, stages)

    emit_result(
        {
            "ok": True,
            "blend": out["blend"],
            "report": out["report"],
            "preview": preview_path,
            "objects": len(placed),
            "rooms": len(manifest["rooms"]),
            "walls": len(manifest["walls"]),
            "validation_ok": report["ok"],
            "errors": report["errors"],
            "warnings": warnings + report["warnings"],
            "stages": stages,
            "seconds": timer.seconds,
            "blender": bpy.app.version_string,
        }
    )


try:
    main()
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    fail(f"{type(exc).__name__}: {exc}")

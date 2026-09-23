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


#: Colour management for every build. AgX supersedes the deprecated Filmic and
#: gives ~16.5 stops with film-like highlight desaturation.
#:
#: THE LOOK NAME IS NAMESPACED. Blender 5.2 accepts only these, probed on the
#: configured install 2026-09-21:
#:   None · AgX - Punchy · AgX - Greyscale · AgX - Very High Contrast ·
#:   AgX - High Contrast · AgX - Medium High Contrast · AgX - Base Contrast ·
#:   AgX - Medium Low Contrast · AgX - Low Contrast · AgX - Very Low Contrast
#:
#: "AgX - Medium Contrast" - what this file asked for until 2026-09-21 - is NOT
#: in that set. It raised TypeError, an `except TypeError: pass` swallowed it,
#: and EVERY render this project ever produced shipped with no look applied.
#: `AgX - Medium High Contrast` is the nearest accepted value to that intent and
#: is the contrast the renders were missing.
VIEW_TRANSFORM = "AgX"
LOOK = "AgX - Medium High Contrast"


def apply_colour_management(scene) -> None:
    """Set the view transform and look, and PROVE they applied.

    Never swallow the failure. A rejected enum value must stop the build: a
    silently-unapplied look is indistinguishable from a correct render until
    somebody compares two builds months later.
    """
    vs = scene.view_settings
    for attr, wanted in (("view_transform", VIEW_TRANSFORM), ("look", LOOK)):
        try:
            setattr(vs, attr, wanted)
        except TypeError as exc:
            valid = [i.identifier for i in vs.bl_rna.properties[attr].enum_items]
            raise RuntimeError(
                f"colour management: {attr}={wanted!r} rejected by this Blender "
                f"({exc}). Accepted values: {valid}"
            ) from exc
    # Setting an enum can succeed and still not stick if the OCIO config
    # swaps underneath; assert rather than assume.
    if vs.view_transform != VIEW_TRANSFORM or vs.look != LOOK:
        raise RuntimeError(
            f"colour management did not stick: asked for "
            f"{VIEW_TRANSFORM!r}/{LOOK!r}, got {vs.view_transform!r}/{vs.look!r}"
        )
    print(f"ALLURE_COLOUR view_transform={vs.view_transform} look={vs.look}", flush=True)


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    apply_colour_management(scene)
    scene.render.film_transparent = False


#: Elapsed at the end of the previous stage, so `stage()` can report a
#: DURATION rather than a timestamp.
_last_mark = 0.0


def stage(name: str, timer: Timer, stages: dict) -> None:
    """Record how long THIS stage took.

    It used to record `timer.seconds`, which is elapsed-since-start - a
    cumulative mark, not a duration. Every consumer read it as a duration:
    the build handler prints `", ".join(f"{k} {v}s")` straight into the
    project's event feed, so a build spent almost entirely in `objects` was
    reported to the operator as though `lighting`, `camera` and `save` had each
    taken seven seconds too. Measured on a real build: the log claimed
    `lighting 7.82s`; lighting actually took 0.00s.

    The total is unaffected - `main()` reports `timer.seconds` separately.
    """
    global _last_mark
    now = timer.seconds
    stages[name] = round(max(0.0, now - _last_mark), 2)
    _last_mark = now
    print(f"ALLURE_STAGE {name} {stages[name]}", flush=True)


#: Manifest major versions this script understands. A manifest whose MAJOR
#: differs has changed or removed a key, so building from it would produce a
#: scene from a document this reader has misunderstood - quietly, and in a way
#: that looks like a successful build.
SUPPORTED_MANIFEST_MAJORS = (1,)


def require_supported_manifest(manifest: dict) -> None:
    """Refuse a manifest this reader cannot be trusted to understand.

    A MINOR bump only adds keys, which an older reader ignores harmlessly - so
    only the major is checked. An ABSENT version is accepted: manifests written
    before the field existed are still valid 1.x documents.
    """
    raw = str(manifest.get("manifest_version", "") or "").strip()
    if not raw:
        return
    try:
        major = int(raw.split(".", 1)[0])
    except ValueError:
        raise RuntimeError(
            f"manifest_version {raw!r} is not a version this reader can parse; "
            f"expected <major>.<minor> with major in {SUPPORTED_MANIFEST_MAJORS}"
        ) from None
    if major not in SUPPORTED_MANIFEST_MAJORS:
        raise RuntimeError(
            f"manifest_version {raw} has major {major}, which this build script "
            f"does not understand (supported: {SUPPORTED_MANIFEST_MAJORS}). "
            "Refusing to build a scene from a document it would misread."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--stop-after", default="")
    ns = parse(parser)

    with open(ns.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    require_supported_manifest(manifest)
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

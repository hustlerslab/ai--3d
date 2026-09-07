"""Smoke test: render the factory-startup cube to --out.

    blender -b --factory-startup --python-exit-code 1 --python smoke.py -- \
        --out C:/path/smoke.png --engine CYCLES --samples 16
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from _common import Timer, configure_engine, emit_result, fail, parse, set_output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--engine", default="CYCLES")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    ns = parse(parser)

    timer = Timer()
    scene = bpy.context.scene
    device = configure_engine(scene, ns.engine, ns.samples)
    set_output(scene, ns.out, ns.width, ns.height)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:  # noqa: BLE001
        fail(f"render failed: {exc}")
    if not os.path.exists(ns.out):
        fail(f"render produced no file at {ns.out}")

    emit_result(
        {
            "ok": True,
            "out": ns.out,
            "engine": scene.render.engine,
            "device": device,
            "samples": ns.samples,
            "seconds": timer.seconds,
            "blender": bpy.app.version_string,
        }
    )


main()

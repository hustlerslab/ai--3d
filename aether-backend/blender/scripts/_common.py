"""Shared helpers for Aether Blender scripts.

Scripts run inside Blender's bundled Python. They must not import the
backend package and must not reach the network. Each script ends with
emit_result({...}) so the backend runner can parse the outcome.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Iterable, Optional

import bpy  # type: ignore

RESULT_PREFIX = "ALLURE_RESULT "


def script_args() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def parse(parser: argparse.ArgumentParser) -> argparse.Namespace:
    return parser.parse_args(script_args())


def emit_result(data: dict[str, Any]) -> None:
    print(RESULT_PREFIX + json.dumps(data), flush=True)


def fail(message: str, **extra: Any) -> None:
    emit_result({"ok": False, "error": message, **extra})
    sys.exit(1)


def enable_gpu(prefer: Iterable[str] = ("OPTIX", "CUDA", "HIP", "METAL")) -> str:
    """Pick the first available Cycles compute backend. Returns the device
    type in use ("CPU" if no GPU backend has devices)."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return "CPU"
    for kind in prefer:
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        gpu = [d for d in prefs.devices if d.type == kind]
        if not gpu:
            continue
        for d in prefs.devices:
            d.use = d.type == kind
        return kind
    prefs.compute_device_type = "NONE"
    return "CPU"


def configure_engine(scene, engine: str, samples: int, denoise: bool = True) -> str:
    """Apply an engine + sample count. Returns the compute device label."""
    engine = engine.upper()
    if engine == "CYCLES":
        scene.render.engine = "CYCLES"
        device = enable_gpu()
        scene.cycles.device = "GPU" if device != "CPU" else "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        return device
    # Blender 5.x: the only Eevee is Eevee Next, id BLENDER_EEVEE.
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    return "GPU"


def set_output(scene, path: str, width: int, height: int, fmt: str = "PNG") -> None:
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = fmt
    scene.render.filepath = path


class Timer:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.t0, 2)

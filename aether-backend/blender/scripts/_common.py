"""Shared helpers for Aether Blender scripts.

Scripts run inside Blender's bundled Python. They must not import the
backend package and must not reach the network. Each script ends with
emit_result({...}) so the backend runner can parse the outcome.
"""
from __future__ import annotations

import argparse
import json
import os
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


#: EEVEE Next raytracing (P1-RENDER-002). Off by default in Blender 5.x -
#: without it, indirect light comes from a pre-filtered light-probe
#: pipeline, which Blender's own manual describes as the choice "when visual
#: fidelity is not the primary goal." Probed live inside Blender 5.2.1 LTS
#: (2026-09-25) with dir()/bl_rna, since the property defaults could not be
#: read from the docs pages (U18, corrections C4): `ray_tracing_method` is
#: an enum of `('PROBE', 'SCREEN')`; `SCREEN` traces against the screen
#: depth buffer (falling back to probes at the edges) and is both the
#: higher-fidelity option and Blender's own default for the enum - the gap
#: was only ever `use_raytracing` itself defaulting to `False`.
#: `RaytraceEEVEE` (`scene.eevee.ray_tracing_options`) has no per-ray COUNT
#: the way Cycles does - task.md asked to record one, written before the
#: API was probed; there isn't one to record. The closest tunables are
#: `resolution_scale` (trace buffer resolution - a STRING enum of
#: `('1','2','4','8','16')`, not an int, despite looking numeric; default
#: `'2'` = half-res) and `screen_trace_quality` (float, default 0.25). Both
#: are left at Blender's own defaults and recorded explicitly rather than
#: invented.
RAYTRACE_METHOD = "SCREEN"
RAYTRACE_MAX_ROUGHNESS = 0.5
RAYTRACE_RESOLUTION_SCALE = "2"
RAYTRACE_SCREEN_TRACE_QUALITY = 0.25


def apply_raytracing(scene) -> dict:
    """Enable EEVEE Next raytracing and PROVE it stuck.

    Same discipline as build_scene.py's apply_colour_management: a setting
    that silently failed to apply is indistinguishable from one that worked,
    until somebody compares renders months later.
    """
    eevee = scene.eevee
    eevee.use_raytracing = True
    eevee.ray_tracing_method = RAYTRACE_METHOD
    opts = eevee.ray_tracing_options
    opts.trace_max_roughness = RAYTRACE_MAX_ROUGHNESS
    opts.resolution_scale = RAYTRACE_RESOLUTION_SCALE
    opts.screen_trace_quality = RAYTRACE_SCREEN_TRACE_QUALITY
    if not eevee.use_raytracing or eevee.ray_tracing_method != RAYTRACE_METHOD:
        raise RuntimeError(
            f"raytracing did not stick: use_raytracing={eevee.use_raytracing}, "
            f"ray_tracing_method={eevee.ray_tracing_method!r}"
        )
    settings = {
        "use_raytracing": eevee.use_raytracing,
        "ray_tracing_method": eevee.ray_tracing_method,
        "trace_max_roughness": round(opts.trace_max_roughness, 4),
        "resolution_scale": opts.resolution_scale,
        "screen_trace_quality": round(opts.screen_trace_quality, 4),
    }
    print(f"ALLURE_RAYTRACE {json.dumps(settings)}", flush=True)
    return settings


def configure_engine(scene, engine: str, samples: int, denoise: bool = True) -> str:
    """Apply an engine + sample count. Returns the compute device label.

    Always logs the resolved device as `ALLURE_DEVICE`, so a render's actual
    hardware path is on record rather than assumed. When `AETHER_REQUIRE_GPU=1`
    is set (P1-BLENDER-001) and Cycles could not find a GPU backend, this is a
    misconfiguration: fail loudly by name instead of silently taking the slow
    CPU path with no trace of having done so.
    """
    engine = engine.upper()
    if engine == "CYCLES":
        scene.render.engine = "CYCLES"
        device = enable_gpu()
        scene.cycles.device = "GPU" if device != "CPU" else "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        print(f"ALLURE_DEVICE engine=CYCLES device={device}", flush=True)
        if device == "CPU" and os.environ.get("AETHER_REQUIRE_GPU") == "1":
            raise RuntimeError(
                "render device misconfigured: AETHER_REQUIRE_GPU=1 but Cycles found no "
                "usable OPTIX/CUDA/HIP/METAL device on this machine; refusing to silently "
                "render on CPU"
            )
        return device
    # Blender 5.x: the only Eevee is Eevee Next, id BLENDER_EEVEE - GPU-only,
    # no CPU fallback exists to misconfigure.
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    apply_raytracing(scene)
    print("ALLURE_DEVICE engine=BLENDER_EEVEE device=GPU", flush=True)
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

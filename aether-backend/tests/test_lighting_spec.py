"""P2-RENDER-002: the design's LightingSpec drives the render.

Real Blender. The same compiled scene is built under two lighting moods; the
saved .blend is read back to prove every interior light sits where the spec
put it, and the two renders are compared to prove the spec changes what the
person sees - not just a number in a file.
"""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from app.blender.manifest import build_manifest, write_manifest
from app.blender.runner import BlenderRunner
from app.planning.compiler import LIGHTING_PRESETS
from app.scene.schema import LightingSpec

#: Same threshold as the visual regression suite (P1-QA-004): above the
#: measured render-noise floor, so a pass here is a real visual change.
CHANGED_PIXEL_MAGNITUDE = 10
CHANGED_PIXEL_FRACTION = 0.001

READBACK = textwrap.dedent("""
    import bpy, json, sys, os
    sys.path.insert(0, os.environ["ALLURE_TEST_SCRIPTS_DIR"])
    from _common import emit_result
    lights = []
    for o in bpy.data.objects:
        if o.type == "LIGHT" and o.data.type != "SUN":
            lights.append({"id": o.name, "type": o.data.type, "location": list(o.location),
                           "energy": o.data.energy, "color": list(o.data.color)})
    emit_result({"ok": True, "lights": lights, "exposure": bpy.context.scene.view_settings.exposure})
""")


def _with_mood(scene, mood: str):
    preset = LIGHTING_PRESETS[mood]
    lighting = scene.lighting.model_copy(deep=True)
    for k in ("sun_azimuth_deg", "sun_elevation_deg", "sun_strength", "sky_turbidity", "exposure_ev"):
        setattr(lighting, k, preset[k])
    lighting.mood = mood
    for light in lighting.interior_lights:
        light.color_temp_k = preset["color_temp_k"]
    return scene.model_copy(update={"lighting": LightingSpec.model_validate(lighting.model_dump())})


def _build(scene, root: Path, runner: BlenderRunner) -> tuple[dict, Path, Path]:
    manifest = build_manifest(scene, project_id="proj_lighting", project_root=root, preview=True,
                              preview_profile="preview")
    path = root / "blender" / "build_manifest.json"
    write_manifest(manifest, path)
    res = runner.run("build_scene.py", ["--manifest", str(path)], log_path=root / "build.log")
    return manifest, Path(res.result["preview"]), Path(res.result["blend"])


def _readback(blend: Path, runner: BlenderRunner, tmp: Path) -> dict:
    script = tmp / "readback.py"
    script.write_text(READBACK, encoding="utf-8")
    os.environ["ALLURE_TEST_SCRIPTS_DIR"] = str(runner.scripts_dir)
    try:
        return runner.run(str(script), blend=blend, log_path=tmp / "readback.log").result
    finally:
        os.environ.pop("ALLURE_TEST_SCRIPTS_DIR", None)


def _pixels(path: Path):
    from PIL import Image
    import numpy as np

    return np.array(Image.open(path).convert("RGB"), dtype=float)


@pytest.fixture
def built(env, blender_path, tmp_path):
    """The same room, built under cool daylight and under evening."""
    from tests.test_blender_build import _compiled_scene

    runner = BlenderRunner(blender_path=blender_path, timeout=300)
    base = _compiled_scene()
    out = {}
    for mood in ("cool_daylight", "evening"):
        root = tmp_path / mood
        manifest, preview, blend = _build(_with_mood(base, mood), root, runner)
        out[mood] = {"manifest": manifest, "preview": preview, "blend": blend,
                     "readback": _readback(blend, runner, root)}
    return out


@pytest.mark.blender
def test_every_interior_light_is_built_where_the_spec_puts_it(built):
    for mood, b in built.items():
        wanted = {l["id"]: l for l in b["manifest"]["lighting"]["interior_lights"]}
        assert wanted, "the compiled scene specifies interior lights"
        got = {l["id"]: l for l in b["readback"]["lights"]}
        assert set(got) == set(wanted), f"{mood}: lights built {sorted(got)} != specified {sorted(wanted)}"
        for lid, spec in wanted.items():
            for axis in range(3):
                assert abs(got[lid]["location"][axis] - spec["location"][axis]) < 1e-4, (mood, lid, axis)
            assert abs(got[lid]["energy"] - spec["power_w"]) < 1e-4
            assert got[lid]["type"] == {"area": "AREA", "point": "POINT", "spot": "SPOT"}[spec["type"]]


@pytest.mark.blender
def test_the_spec_exposure_reaches_the_render(built):
    for mood, b in built.items():
        assert abs(b["readback"]["exposure"] - LIGHTING_PRESETS[mood]["exposure_ev"]) < 1e-6, mood


@pytest.mark.blender
def test_changing_the_lighting_spec_changes_the_render(built):
    a, b = _pixels(built["cool_daylight"]["preview"]), _pixels(built["evening"]["preview"])
    changed = (abs(a - b).max(axis=2) > CHANGED_PIXEL_MAGNITUDE).mean()
    assert changed > CHANGED_PIXEL_FRACTION, f"only {changed:.4%} of pixels changed"


@pytest.mark.blender
def test_a_warm_evening_renders_warmer_than_cool_daylight(built):
    """The outcome task.md asks for, measured: the red/blue balance of the
    evening render sits above the cool-daylight one."""
    def warmth(path):
        px = _pixels(path)
        return float(px[..., 0].mean() / max(px[..., 2].mean(), 1e-6))

    cool, evening = warmth(built["cool_daylight"]["preview"]), warmth(built["evening"]["preview"])
    # A margin, not just ">": with the spec ignored, two identical renders
    # differ only by noise, and noise alone once put "evening" a hair ahead.
    # Measured real gap: 0.118 (1.017 -> 1.135).
    assert evening - cool > 0.02, f"evening R/B {evening:.3f} is not clearly warmer than cool daylight {cool:.3f}"
    (Path(built["evening"]["preview"]).parent / "warmth.json").write_text(
        json.dumps({"cool_daylight_r_over_b": cool, "evening_r_over_b": evening}), encoding="utf-8")

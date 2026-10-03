"""P1-RENDER-002: EEVEE raytracing is enabled, with named settings recorded
and asserted applied - not just requested and hoped for (same discipline as
build_scene.py's colour management, P0-RENDER-001).

Real Blender (marker `blender`). Skipped unless BLENDER_PATH is set.
"""
from __future__ import annotations

import json
import re

import pytest

from app.blender.runner import BlenderRunner


def _allure_raytrace(log_text: str) -> dict:
    m = re.search(r"ALLURE_RAYTRACE (\{.*\})", log_text)
    assert m, f"no ALLURE_RAYTRACE line in log:\n{log_text}"
    return json.loads(m.group(1))


@pytest.mark.blender
def test_raytracing_is_on_for_every_eevee_render(env, blender_path, tmp_path):
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    out = tmp_path / "smoke.png"
    log = tmp_path / "smoke.log"
    runner.smoke(out, engine="BLENDER_EEVEE", samples=8, log_path=log)
    settings = _allure_raytrace(log.read_text(encoding="utf-8"))
    assert settings["use_raytracing"] is True
    assert settings["ray_tracing_method"] == "SCREEN"


@pytest.mark.blender
def test_raytracing_settings_are_named_and_recorded(env, blender_path, tmp_path):
    """Not just 'on' - the specific values this task adopted, on the record."""
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    out = tmp_path / "smoke.png"
    log = tmp_path / "smoke.log"
    runner.smoke(out, engine="BLENDER_EEVEE", samples=8, log_path=log)
    settings = _allure_raytrace(log.read_text(encoding="utf-8"))
    assert settings == {
        "use_raytracing": True,
        "ray_tracing_method": "SCREEN",
        "trace_max_roughness": 0.5,
        "resolution_scale": "2",
        "screen_trace_quality": 0.25,
    }


@pytest.mark.blender
def test_cycles_render_is_unaffected(env, blender_path, tmp_path):
    """Raytracing is an EEVEE concept; Cycles is already full path tracing
    and must not be touched by this change."""
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    out = tmp_path / "smoke.png"
    log = tmp_path / "smoke.log"
    runner.smoke(out, engine="CYCLES", samples=4, log_path=log)
    text = log.read_text(encoding="utf-8")
    assert "ALLURE_RAYTRACE" not in text
    assert "ALLURE_DEVICE engine=CYCLES" in text

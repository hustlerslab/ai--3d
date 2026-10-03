"""P1-BLENDER-001: the render device is logged, and a required-but-missing
GPU backend fails the build loudly instead of silently taking the CPU path.

Real Blender (marker `blender`). Skipped unless BLENDER_PATH is set.
"""
from __future__ import annotations

import re
import textwrap

import pytest

from app.blender.runner import BlenderError, BlenderRunner
from app.core.config import get_settings


@pytest.mark.blender
def test_device_is_logged_for_a_real_cycles_render(env, blender_path, tmp_path):
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    out = tmp_path / "smoke.png"
    log = tmp_path / "smoke.log"
    result = runner.smoke(out, engine="CYCLES", samples=4, log_path=log)
    assert result.result["device"]  # whatever this machine actually resolved to
    text = log.read_text(encoding="utf-8")
    assert re.search(r"ALLURE_DEVICE engine=CYCLES device=\w+", text), text


@pytest.mark.blender
def test_eevee_render_also_logs_its_device(env, blender_path, tmp_path):
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    out = tmp_path / "smoke.png"
    log = tmp_path / "smoke.log"
    runner.smoke(out, engine="BLENDER_EEVEE", samples=4, log_path=log)
    text = log.read_text(encoding="utf-8")
    assert "ALLURE_DEVICE engine=BLENDER_EEVEE device=GPU" in text


#: Simulates "no GPU backend available" regardless of this machine's actual
#: hardware, by monkeypatching enable_gpu() before it's called - the only way
#: to exercise the failure path on a machine that does have a working GPU.
_FORCE_CPU_SCRIPT = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, os.environ["ALLURE_TEST_SCRIPTS_DIR"])
    import bpy
    import _common
    from _common import configure_engine, emit_result, fail

    _common.enable_gpu = lambda *a, **k: "CPU"
    try:
        configure_engine(bpy.context.scene, "CYCLES", 4)
    except RuntimeError as exc:
        fail(str(exc))
    emit_result({"ok": True})
    """
)


@pytest.mark.blender
def test_require_gpu_fails_loudly_with_no_gpu_backend(env, blender_path, tmp_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    monkeypatch.setenv("BLENDER_REQUIRE_GPU", "1")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.blender_require_gpu is True

        script = tmp_path / "force_cpu.py"
        script.write_text(_FORCE_CPU_SCRIPT, encoding="utf-8")
        monkeypatch.setenv("ALLURE_TEST_SCRIPTS_DIR", str(settings.blender_scripts_dir))

        runner = BlenderRunner(blender_path=blender_path, timeout=120)
        log = tmp_path / "fail.log"
        with pytest.raises(BlenderError) as exc_info:
            runner.run(str(script), log_path=log)
        assert "misconfigured" in str(exc_info.value).lower()
        assert "gpu" in str(exc_info.value).lower()
    finally:
        get_settings.cache_clear()


@pytest.mark.blender
def test_require_gpu_off_by_default_does_not_fail(env, blender_path, tmp_path, monkeypatch):
    """Off by default: a machine with no discrete GPU keeps rendering on CPU
    rather than every build failing outright."""
    settings = get_settings()
    assert settings.blender_require_gpu is False

    script = tmp_path / "force_cpu.py"
    script.write_text(_FORCE_CPU_SCRIPT, encoding="utf-8")
    monkeypatch.setenv("ALLURE_TEST_SCRIPTS_DIR", str(settings.blender_scripts_dir))
    runner = BlenderRunner(blender_path=blender_path, timeout=120)
    log = tmp_path / "ok.log"
    result = runner.run(str(script), log_path=log)
    assert result.result["ok"] is True

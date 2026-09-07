"""M8: a Blender run that overruns its timeout is killed, not left running."""
from __future__ import annotations

import time

import pytest

from app.blender import BlenderRunner, BlenderTimeout


@pytest.mark.blender
def test_blender_timeout_kills_process(env, blender_path, monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", blender_path)
    from app.core import config

    config.get_settings.cache_clear()
    runner = BlenderRunner()
    log = tmp_path / "timeout.log"
    t0 = time.monotonic()
    with pytest.raises(BlenderTimeout):
        # a render far too big to finish in 3 s
        runner.run(
            "smoke.py",
            ["--out", str(tmp_path / "never.png"), "--engine", "CYCLES", "--samples", "4096", "--width", "4096", "--height", "4096"],
            log_path=log,
            timeout=3,
        )
    elapsed = time.monotonic() - t0
    assert elapsed < 20, f"kill took {elapsed:.1f}s"
    assert not (tmp_path / "never.png").exists()
    assert "killed: timeout" in log.read_text(encoding="utf-8")

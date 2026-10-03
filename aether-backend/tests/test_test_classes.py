"""P1-QA-001 — the class separation itself, tested (class=MOCK)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def _pytest(*args, env_extra=None, tmp=None):
    import os

    env = {**os.environ, **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=BACKEND, capture_output=True, text=True, env=env, timeout=600)


def test_a_default_run_is_mock_only_and_says_so(tmp_path):
    report = tmp_path / "r.json"
    r = _pytest("tests/test_jobs.py", "tests/real", env_extra={"ALLURE_TEST_REPORT": str(report)})
    assert r.returncode == 0, r.stdout[-800:]
    assert "class=MOCK passed=" in r.stdout and "class=REAL-PROVIDER did not run" in r.stdout
    counts = json.loads(report.read_text())["classes"]
    assert counts["MOCK"]["passed"] > 0 and sum(counts["REAL-PROVIDER"].values()) == 0


def test_a_selection_that_mixes_classes_is_refused():
    r = _pytest("-m", "mock or real_provider", "tests/test_jobs.py", "tests/real")
    assert r.returncode == 4 and "mixes test classes" in (r.stdout + r.stderr)


def test_the_real_provider_class_runs_on_its_own_and_names_each_provider(tmp_path):
    report = tmp_path / "r.json"
    r = _pytest("-m", "real_provider", "-rs", env_extra={
        "ALLURE_TEST_REPORT": str(report), "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "",
        "MESHY_API_KEY": "", "BLENDER_PATH": "", "OLLAMA_BASE_URL": "http://127.0.0.1:9"})
    assert r.returncode == 0, r.stdout[-800:]
    for provider in ("gemini", "anthropic", "qwen", "meshy", "blender"):
        assert f"did not run for {provider}" in r.stdout
    counts = json.loads(report.read_text())["classes"]
    assert counts["REAL-PROVIDER"]["skipped"] == 5 and sum(counts["MOCK"].values()) == 0


def test_the_mock_class_blanks_keys_and_the_real_class_does_not():
    import os

    import tests.real.test_provider_smoke as smoke

    assert os.environ.get("GEMINI_API_KEY", "") == "", "inside a MOCK test every key is blank"
    assert smoke.pytestmark.name == "real_provider"


@pytest.mark.parametrize("reports, ok, reason", [
    ({"MOCK": {"passed": 10}, "REAL-PROVIDER": {"passed": 3}}, True, ""),
    ({"MOCK": {"passed": 10}, "REAL-PROVIDER": {"skipped": 5}}, False, "REAL-PROVIDER did not run"),
    ({"MOCK": {"passed": 10}}, False, "REAL-PROVIDER did not run"),
    ({"MOCK": {"passed": 10}, "REAL-PROVIDER": {"passed": 2, "failed": 1}}, False, "REAL-PROVIDER failed=1"),
    ({"MOCK": {"passed": 9, "failed": 1}, "REAL-PROVIDER": {"passed": 3}}, False, "MOCK failed=1"),
    ({"REAL-PROVIDER": {"passed": 3}}, False, "MOCK did not run"),
])
def test_the_release_gate_fails_unless_real_provider_ran(tmp_path, reports, ok, reason):
    files = []
    for cls, counts in reports.items():
        f = tmp_path / f"{cls}.json"
        f.write_text(json.dumps({"classes": {cls: counts}}))
        files.append(str(f))
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "release_gate.py"), *files],
                       capture_output=True, text=True)
    assert (r.returncode == 0) is ok, r.stdout
    if reason:
        assert reason in r.stdout
    assert "class=MOCK" in r.stdout and "class=REAL-PROVIDER" in r.stdout
    assert "total" not in r.stdout.lower(), "classes are never summed"


def test_ci_runs_mock_per_commit_and_the_other_classes_elsewhere():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    nightly = (ROOT / ".github" / "workflows" / "nightly-real-provider.yml").read_text("utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    assert "pytest -m mock" in ci and "real_provider" not in ci.split("Run the MOCK suite", 1)[1].split("Label", 1)[0]
    assert "pytest -m real_provider" in nightly and "schedule" in nightly
    assert "release_gate.py" in release and "needs: [mock, real-provider]" in release

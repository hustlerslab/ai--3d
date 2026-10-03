"""P1-QA-001 — the three test classes, kept apart.

"1446 tests pass" is a MOCK number: no provider key, no vendor network, no
GPU. It proves the code holds together and nothing about Gemini, Meshy or
Blender. So every test belongs to exactly ONE class, a run may contain only
one class, and each class is counted on its own line - never summed.

    MOCK             every commit     (the default; no -m needed)
    REAL-PROVIDER    nightly          pytest -m real_provider      (tests/real/)
    PRODUCTION-PATH  pre-release      pytest -m production_path    (Blender / GPU)

This module is imported by conftest.py; the hooks live there.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

CLASSES = ("MOCK", "REAL-PROVIDER", "PRODUCTION-PATH")
MARKER_FOR = {"MOCK": "mock", "REAL-PROVIDER": "real_provider", "PRODUCTION-PATH": "production_path"}
REAL_DIR = Path(__file__).resolve().parent / "real"


def class_of(item: Any) -> str:
    if item.get_closest_marker("production_path") or item.get_closest_marker("blender"):
        return "PRODUCTION-PATH"
    if item.get_closest_marker("real_provider") or REAL_DIR in Path(str(item.fspath)).resolve().parents:
        return "REAL-PROVIDER"
    return "MOCK"


def tag(item: Any) -> None:
    """Give an item its class marker AS IT IS COLLECTED - before `-m` filters,
    so `-m mock` selects exactly the MOCK class."""
    cls = class_of(item)
    item.user_properties.append(("test_class", cls))
    item.add_marker(getattr(pytest.mark, MARKER_FOR[cls]))


def assign(config: Any, items: list) -> None:
    """After `-m` has filtered: the run must hold ONE class. With no -m, only
    MOCK runs (the others need keys, a GPU, money). With a -m that still
    selects more than one class, the run is refused."""
    present = {class_of(i) for i in items}
    if len(present) <= 1:
        return
    if config.getoption("markexpr"):
        raise pytest.UsageError(
            f"this selection mixes test classes {sorted(present)}; each class is run and reported on its own "
            "(P1-QA-001): use -m mock, -m real_provider or -m production_path")
    keep = [i for i in items if class_of(i) == "MOCK"]
    dropped = [i for i in items if class_of(i) != "MOCK"]
    config.hook.pytest_deselected(items=dropped)
    items[:] = keep


class Tally:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, int]] = {c: {"passed": 0, "failed": 0, "skipped": 0, "error": 0} for c in CLASSES}

    def record(self, report: Any) -> None:
        cls = dict(report.user_properties).get("test_class", "MOCK")
        if report.when == "call":
            outcome = "passed" if report.passed else ("skipped" if report.skipped else "failed")
            if getattr(report, "wasxfail", None) is not None:
                outcome = "skipped" if report.skipped else "passed"
            self.counts[cls][outcome] += 1
        elif report.failed:
            self.counts[cls]["error"] += 1
        elif report.skipped and report.when == "setup":
            self.counts[cls]["skipped"] += 1

    def lines(self) -> list[str]:
        out = []
        for cls in CLASSES:
            c = self.counts[cls]
            ran = sum(c.values())
            if ran:
                out.append(f"class={cls} passed={c['passed']} failed={c['failed']} error={c['error']} "
                           f"skipped={c['skipped']}")
            else:
                out.append(f"class={cls} did not run")
        return out

    def write(self) -> None:
        path = os.environ.get("ALLURE_TEST_REPORT")
        if path:
            Path(path).write_text(json.dumps({"classes": self.counts}, indent=2), "utf-8")

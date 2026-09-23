"""Measure the pipeline's runtime across several projects — P0-QA-003.

    python research/v4_runtime_baseline.py --data <COPY of data dir> [--repeat 1]

The figures this replaces were all **N=1**: one project, one run, quoted ever
since as though they were rates. `scene_plan ~2 min`, `Blender build 40-60 s`,
`placement 91% within 1.0 m`, `composite 98%`. A single observation is not a
rate, and the honest fix is not a disclaimer but more observations.

So every number written here carries its own `N`, its own spread, and the date
it was taken. A stage measured once is reported as `N=1` and labelled
`single_observation` - never averaged into something that reads as typical.

**Run it against a COPY of the data directory.** Building rewrites `blender/`,
and a benchmark that damages what it measures is not a benchmark.

**What this costs.** Blender and the renders cost time and GPU only. Nothing
here can generate a mesh - there is no path from this script to
`generate_elements` - so it cannot spend a Meshy credit.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import defaultdict

#: build_scene.py's ALLURE_STAGE lines used to be CUMULATIVE - `stage()`
#: recorded `Timer.seconds`, elapsed-since-start - and every consumer read them
#: as durations. Found by this benchmark, fixed at source on 2026-09-21; the
#: script now emits true per-stage durations that sum to the reported total.
#:
#: The check below is not paranoia: it is how the benchmark would notice if the
#: source ever regressed. Cumulative marks are monotonically non-decreasing and
#: their last value equals the total; durations are not and do not.
STAGE_ORDER = ("reset", "rooms", "walls", "objects", "materials",
               "lighting", "camera", "save", "validate", "preview")


def looks_cumulative(stages: dict, total: float) -> bool:
    """True when the values look like timestamps rather than durations."""
    ordered = [float(stages[n]) for n in STAGE_ORDER if n in stages]
    if len(ordered) < 3:
        return False
    monotonic = all(b >= a for a, b in zip(ordered, ordered[1:]))
    sums_over = sum(ordered) > total * 1.5 if total else False
    return monotonic and sums_over


def stage_durations(cumulative: dict) -> dict:
    """Difference cumulative checkpoints into per-stage durations."""
    out, previous = {}, 0.0
    for name in STAGE_ORDER:
        if name not in cumulative:
            continue
        mark = float(cumulative[name])
        out[name] = round(max(0.0, mark - previous), 2)
        previous = mark
    for name, value in cumulative.items():
        if name not in out:
            out[f"{name}__unordered"] = float(value)
    return out


from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:                                    # noqa: BLE001
        return "unknown"


class Samples:
    """Durations for one stage, with the honesty rules attached.

    `summary()` refuses to present one observation as a central tendency. That
    is the entire point: the previous baseline reported single runs as though
    repeating them would land nearby, and nobody could tell from the number
    that it would not.
    """

    def __init__(self, unit: str = "seconds"):
        self.values: list[float] = []
        self.unit = unit
        self.failures: list[str] = []

    def add(self, value: float) -> None:
        self.values.append(round(float(value), 2))

    def fail(self, reason: str) -> None:
        self.failures.append(reason)

    def summary(self) -> dict:
        n = len(self.values)
        out: dict = {"N": n, "unit": self.unit, "runs": self.values}
        if self.failures:
            out["failures"] = self.failures
        if n == 0:
            out["status"] = "not measured"
            return out
        if n == 1:
            out["status"] = "single_observation"
            out["value"] = self.values[0]
            out["warning"] = "N=1. One observation, not a rate."
            return out
        out["status"] = "measured"
        out["mean"] = round(statistics.mean(self.values), 2)
        out["median"] = round(statistics.median(self.values), 2)
        out["min"] = min(self.values)
        out["max"] = max(self.values)
        if n >= 3:
            out["stdev"] = round(statistics.stdev(self.values), 2)
        return out


def _environment() -> dict:
    env = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    try:
        from app.core.config import get_settings

        s = get_settings()
        env["blender_path"] = s.blender_path if s.blender_configured else ""
        env["intelligence_provider"] = s.intelligence_provider
        env["scene_image_enabled"] = s.scene_image_enabled
    except Exception as exc:                             # noqa: BLE001
        env["settings_error"] = str(exc)
    if shutil.which("nvidia-smi"):
        try:
            env["gpu"] = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:                                # noqa: BLE001
            pass
    return env


def build_once(data_dir: Path, project_id: str, log_dir: Path) -> dict:
    """One real Blender build. Returns {"total": s, "stages": {...}, "objects": n}.

    Driven from the manifest already on disk, so the number is Blender's and
    not the planner's. `build_scene.py` emits `ALLURE_STAGE <name> <seconds>`
    for each phase, which is where the per-stage figures come from - measured
    inside the process rather than inferred from the outside.
    """
    from app.blender import BlenderRunner

    manifest = data_dir / "projects" / project_id / "blender" / "build_manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"{project_id}: no build_manifest.json")

    runner = BlenderRunner()
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    res = runner.run(
        "build_scene.py",
        ["--manifest", str(manifest)],
        log_path=log_dir / f"{project_id}.blender.log",
        timeout=900,
    )
    wall = time.monotonic() - started
    result = res.result or {}
    raw = result.get("stages", {}) or {}
    total = float(result.get("seconds") or getattr(res, "duration_s", wall))
    # Durations as emitted, unless the source has regressed to cumulative marks.
    cumulative = looks_cumulative(raw, total)
    return {
        "total": getattr(res, "duration_s", wall),
        "wall": wall,
        "stages_were_cumulative": cumulative,
        "stages": stage_durations(raw) if cumulative else {
            k: round(float(v), 2) for k, v in raw.items()},
        "objects": result.get("objects"),
        "rooms": result.get("rooms"),
        "validation_ok": result.get("validation_ok"),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="P0-QA-003 runtime baseline")
    parser.add_argument("--data", required=True,
                        help="a COPY of the data directory, never the live one")
    parser.add_argument("--projects", nargs="*", default=None)
    parser.add_argument("--repeat", type=int, default=1,
                        help="repeat per project, to separate project variance "
                             "from run-to-run variance")
    parser.add_argument("--out", default="../docs/benchmarks/v4_runtime_baseline.json")
    args = parser.parse_args(argv)

    data_dir = Path(args.data).resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"no such data directory: {data_dir}")
    os.environ["AETHER_DATA_DIR"] = str(data_dir)

    from app.core import config

    config.get_settings.cache_clear()

    conn = sqlite3.connect(f"file:{data_dir / 'allure.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        known = {r["project_id"]: r["name"] for r in
                 conn.execute("SELECT project_id, name FROM projects")}
    finally:
        conn.close()

    projects = args.projects or [
        p for p in known
        if (data_dir / "projects" / p / "blender" / "build_manifest.json").exists()
    ]

    print(f"data:     {data_dir}")
    print(f"projects: {len(projects)} -> {', '.join(projects)}")
    print(f"repeat:   {args.repeat}\n")

    total = Samples()
    stages: dict[str, Samples] = defaultdict(Samples)
    per_project: dict[str, dict] = {}
    log_dir = data_dir / "_benchmark_logs"

    for project_id in projects:
        runs = []
        for attempt in range(args.repeat):
            label = f"{project_id} ({attempt + 1}/{args.repeat})"
            print(f"  building {label} ... ", end="", flush=True)
            try:
                run = build_once(data_dir, project_id, log_dir)
            except Exception as exc:                     # noqa: BLE001
                print(f"FAILED: {type(exc).__name__}: {exc}")
                total.fail(f"{project_id}: {type(exc).__name__}: {exc}")
                continue
            runs.append(run)
            total.add(run["total"])
            for stage, seconds in run["stages"].items():
                stages[stage].add(seconds)
            print(f"{run['total']:.1f}s  objects={run['objects']} "
                  f"rooms={run['rooms']} valid={run['validation_ok']}")
        if runs:
            per_project[project_id] = {
                "name": known.get(project_id, ""),
                "N": len(runs),
                "build_seconds": [round(r["total"], 2) for r in runs],
                "objects": runs[0]["objects"],
                "rooms": runs[0]["rooms"],
                "validation_ok": runs[0]["validation_ok"],
            }

    report = {
        "_comment": (
            "P0-QA-003. Every figure carries its own N. A stage measured once is "
            "labelled single_observation and is NOT a rate - the figures this "
            "replaces were all N=1 and were quoted as though they were rates."
        ),
        "schema_version": "1.0",
        "captured_at": _now_iso(),
        "git_sha": _git_sha(),
        "data_dir": str(data_dir),
        "measurement": {
            "projects_measured": projects,
            "project_count": len(projects),
            "repeats_per_project": args.repeat,
            "what_was_measured": (
                "A real Blender build per project, driven from each project's "
                "existing build_manifest.json. Per-stage figures are DERIVED "
                "from build_scene.py's ALLURE_STAGE lines, which are cumulative "
                "elapsed times rather than per-stage durations - see "
                "stage_durations() and the note in blender_stages_note."
            ),
            "what_was_not_measured": (
                "Provider stages (analyze, scene_plan) and accuracy scoring are "
                "not in this run; both call a vision model and belong to a "
                "separate, explicitly-costed measurement."
            ),
        },
        "environment": _environment(),
        "per_project": per_project,
        "blender_build_total": total.summary(),
        "blender_stages_note": (
            "Per-stage DURATIONS. build_scene.py emitted cumulative elapsed "
            "times under these names until 2026-09-21, when this benchmark "
            "found it: the build handler printed them into the project's event "
            "feed as though they were durations, so a build spent almost "
            "entirely in `objects` was reported as though `lighting`, `camera` "
            "and `save` had each taken seven seconds too. Fixed at source; the "
            "stages now sum to the reported total."
        ),
        "blender_stages": {name: s.summary() for name, s in sorted(stages.items())},
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nwritten: {out.resolve()}")
    print(f"  build total: {json.dumps(report['blender_build_total'])}")
    for name, summary in report["blender_stages"].items():
        print(f"  {name}: N={summary['N']} "
              f"{summary.get('mean', summary.get('value'))}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""P1-IDENTITY-006 - identity accuracy as a measured number, with N.

The identity guards exist (`resolve_elements`, the canonical key chosen by
research/element-first/identity_ablation.py). Their effectiveness on the
PRODUCTION code path had never been measured: the ablation scored candidate
key functions, not the shipped resolver, and it counted "assets generated" as
"number of keys" rather than by the rule `generate_elements` actually spends
under.

This harness runs the shipped resolver over a hand-labelled set and reports:

* false-merge rate   - definitions that hold two different labelled pieces
* false-split rate   - labelled pieces spread over more than one definition
* instance-count accuracy - per (room, type), predicted instances == labelled
* generations, by the production spend rule - `distinct_shapes` over
  `approved_for_generation`, minus groups whose mesh already exists on disk
  (`storage_key`), which is exactly the loop in `generate_elements`
* asset reuse rate   - instances served per generation

Labelled set = the six ablation cases (one of them the 26 real reading rows
of proj_553cb09794, labelled by eye) + the V4 golden composition of task.md
section 29.1 + the two acceptance cases named in P1-IDENTITY-006.

Every figure states its N. Nothing here calls a model or a provider.

    python -u research/p1_identity_benchmark.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.intelligence.schema import SceneElement, SceneReading                  # noqa: E402
from app.intelligence.scene_reading import (approved_for_generation, distinct_shapes,  # noqa: E402
                                            mark_duplicates, resolve_elements)
from app.jobs.handlers.generate_elements import _glb_rel, storage_key            # noqa: E402

OUT = ROOT.parent / "docs" / "benchmarks" / "p1_identity_benchmark.json"
ABLATION = ROOT.parent / "research" / "element-first" / "identity_ablation.py"
ROOM = "living_room"


def _ablation_cases() -> dict:
    spec = importlib.util.spec_from_file_location("identity_ablation", ABLATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                     # type: ignore[union-attr]
    cases = dict(mod.CASES)
    if not Path(mod.REAL).is_file():
        # The 26 real rows live in the data dir, which CI does not have. The
        # synthetic cases still run; the report says the real case was absent.
        cases.pop("real_project", None)
    return cases


# -- the V4 golden composition (task.md section 29.1) ------------------------

def _el(eid: str, stype: str, name: str, material: str, color: str, dims, box_x: float,
        approved: bool = True, asset_id: str = "") -> SceneElement:
    """One approved, crop-bearing reading row at its own place in the render.
    Boxes are spread along x and kept off the image edge so `mark_duplicates`
    judges them as production would: distinct pieces, not one piece re-read."""
    return SceneElement(element_id=eid, room_id=ROOM, semantic_type=stype, name=name,
                        material=material, color=color, dimensions_m=dims,
                        bbox=(box_x, 0.45, box_x + 0.06, 0.62), crop_px=(240, 320),
                        crop_ref=f"planning/scene_crops/{ROOM}/{eid}.png",
                        check="ok", approved=approved, asset_id=asset_id)


def golden_living_room() -> tuple[list[SceneElement], dict[str, str]]:
    """GOLDEN-LIVING-ROOM-01: 10 element kinds, 17 pieces. `truth` maps a row
    to its labelled design; two rows share a label iff they are one design.
    The TV unit is the client's own piece: its mesh already exists (see
    `generations()`), so it binds without spend."""
    rows: list[tuple[str, str, str, str, str, tuple, str]] = [
        # eid,          type,          name,                   material, colour,    dims,               label
        ("sofa",        "sofa",        "blue three-seater",    "fabric", "#2a4d8f", (2.1, 0.8, 0.9),    "sofa"),
        ("chair_1",     "lounge_chair","green lounge chair",   "velvet", "#4a5a3f", (0.8, 0.8, 0.85),   "chair"),
        ("chair_2",     "lounge_chair","green lounge chair",   "velvet", "#4a5a3f", (0.8, 0.8, 0.85),   "chair"),
        ("stool_1",     "bar_stool",   "black bar stool",      "metal",  "#111111", (0.4, 0.75, 0.4),   "stool"),
        ("stool_2",     "bar_stool",   "black bar stool",      "metal",  "#111111", (0.4, 0.75, 0.4),   "stool"),
        ("stool_3",     "bar_stool",   "black bar stool",      "metal",  "#111111", (0.4, 0.75, 0.4),   "stool"),
        ("side_oak",    "side_table",  "oak side table",       "oak",    "#b08a5a", (0.5, 0.5, 0.5),    "side_oak"),
        ("side_black",  "side_table",  "black side table",     "metal",  "#111111", (0.5, 0.5, 0.5),    "side_black"),
        ("coffee",      "coffee_table","oak coffee table",     "oak",    "#b08a5a", (1.2, 0.4, 0.6),    "coffee"),
        ("cushion_1",   "cushion",     "linen cushion",        "linen",  "#d9cdb8", (0.45, 0.15, 0.45), "cushion"),
        ("cushion_2",   "cushion",     "linen cushion",        "linen",  "#d9cdb8", (0.45, 0.15, 0.45), "cushion"),
        ("cushion_3",   "cushion",     "linen cushion",        "linen",  "#d9cdb8", (0.45, 0.15, 0.45), "cushion"),
        ("cushion_4",   "cushion",     "linen cushion",        "linen",  "#d9cdb8", (0.45, 0.15, 0.45), "cushion"),
        ("lamp",        "floor_lamp",  "brass floor lamp",     "brass",  "#c9a227", (0.3, 1.6, 0.3),    "lamp"),
        ("rug",         "rug",         "wool rug",             "wool",   "#d0c8b0", (2.4, 0.01, 1.6),   "rug"),
        ("tv_unit",     "tv_unit",     "walnut tv unit",       "walnut", "#5a3a2a", (1.8, 0.5, 0.4),    "tv_unit"),
        ("television",  "television",  "television",          "plastic","#0a0a0a", (1.4, 0.8, 0.05),   "television"),
    ]
    els = [_el(eid, stype, name, mat, col, dims, box_x=0.05 + 0.052 * n)
           for n, (eid, stype, name, mat, col, dims, _label) in enumerate(rows)]
    return els, {eid: label for (eid, *_rest, label) in rows}


def two_dark_one_light_stool() -> tuple[list[SceneElement], dict[str, str]]:
    """Acceptance: 2 dark + 1 light stool -> 2 definitions. Neither merged
    across the colour difference nor split within it."""
    els = [_el("dark_1", "bar_stool", "black bar stool", "metal", "#111111", (0.4, 0.75, 0.4), 0.10),
           _el("dark_2", "bar_stool", "black bar stool", "metal", "#111111", (0.4, 0.75, 0.4), 0.20),
           _el("light_1", "bar_stool", "white bar stool", "metal", "#f2f2f2", (0.4, 0.75, 0.4), 0.30)]
    return els, {"dark_1": "dark", "dark_2": "dark", "light_1": "light"}


def television_is_not_tv_unit() -> tuple[list[SceneElement], dict[str, str]]:
    """Acceptance criterion 7: same room, same colour, same finish family -
    still two things, because the type is part of what a piece IS."""
    els = [_el("tvu", "tv_unit", "black tv unit", "metal", "#0a0a0a", (1.8, 0.5, 0.4), 0.10),
           _el("tv", "television", "television", "metal", "#0a0a0a", (1.4, 0.8, 0.05), 0.30)]
    return els, {"tvu": "unit", "tv": "screen"}


def one_rejected_stool() -> tuple[list[SceneElement], dict[str, str]]:
    """Three identical stools, one of which the second look rejected. The
    rejected row is not evidence of a piece: one definition, TWO instances,
    and the excluded row is reported as excluded, never as a third stool."""
    els = [_el(f"s{i}", "bar_stool", "black bar stool", "metal", "#111111", (0.4, 0.75, 0.4), 0.1 + 0.1 * i)
           for i in range(3)]
    els[2].check, els[2].approved = "mismatch", None
    return els, {e.element_id: "stool" for e in els}


CASES = {
    "golden_living_room_01": golden_living_room,
    "acceptance_one_rejected_stool_is_excluded": one_rejected_stool,
    "acceptance_two_dark_one_light_stool": two_dark_one_light_stool,
    "acceptance_television_vs_tv_unit": television_is_not_tv_unit,
}
CASES.update({f"ablation_{k}": v for k, v in _ablation_cases().items()})


# -- scoring ---------------------------------------------------------------

def score(els: list[SceneElement], truth: dict[str, str]) -> dict:
    """Run the SHIPPED resolver and score it against the labels.

    Only rows the resolver would use take part (`trustworthy()` - check ok or
    human-approved); the rest are counted as excluded, not as errors, because
    a row a check removed is not evidence of a piece.
    """
    reading = SceneReading(elements=[e.model_copy(deep=True) for e in els])
    mark_duplicates(reading)                       # production runs this first
    definitions, instances = resolve_elements(reading)
    used = {i.source_element_id for i in instances}
    truth_used = {k: v for k, v in truth.items() if k in used}

    by_def: dict[str, list[str]] = {d.element_id: list(d.source_element_ids) for d in definitions}
    false_merges = sum(1 for ids in by_def.values() if len({truth_used[i] for i in ids}) > 1)
    defs_per_truth: dict[str, set[str]] = defaultdict(set)
    for did, ids in by_def.items():
        for i in ids:
            defs_per_truth[truth_used[i]].add(did)
    false_splits = sum(len(d) - 1 for d in defs_per_truth.values())
    truth_groups = len(set(truth_used.values()))

    # instance count per (room, type): predicted vs labelled
    pred: dict[tuple[str, str], int] = defaultdict(int)
    want: dict[tuple[str, str], int] = defaultdict(int)
    for i in instances:
        pred[(i.room_id, next(e.semantic_type for e in els if e.element_id == i.source_element_id))] += 1
    for e in els:
        if e.element_id in used:
            want[(e.room_id, e.semantic_type)] += 1
    cells = sorted(set(pred) | set(want))
    correct = sum(1 for c in cells if pred[c] == want[c])

    return {
        "n_elements": len(els),
        "n_trustworthy": len(used),
        "n_excluded": len(els) - len(used),
        "definitions": len(definitions),
        "truth_groups": truth_groups,
        "instances": len(instances),
        "false_merges": false_merges,
        "false_splits": false_splits,
        "false_merge_rate": round(false_merges / len(definitions), 4) if definitions else 0.0,
        "false_split_rate": round(false_splits / truth_groups, 4) if truth_groups else 0.0,
        "instance_count": {"cells": len(cells), "cells_correct": correct,
                           "accuracy": round(correct / len(cells), 4) if cells else 1.0,
                           "predicted": len(instances), "truth": sum(want.values())},
        "definition_sizes": sorted((len(v) for v in by_def.values()), reverse=True),
    }


def generations(els: list[SceneElement], owned: tuple[str, ...] = ("tv_unit",)) -> dict:
    """How many meshes `generate_elements` would BUY for these rows - by its
    own rule, with no Meshy client: approved rows with a crop, grouped by
    canonical identity, minus groups whose file already exists on disk.

    `owned` names the rows whose mesh the client already has. Today the only
    mechanism that binds a client-owned piece without spend is a mesh already
    present under the group's storage key (the reuse path that finds meshes
    bought under the old key). P1-ELEM-004 is to make that a first-class
    control; until then the benchmark places the file, which is what the
    production loop checks.
    """
    ready, held = approved_for_generation(SceneReading(elements=els))
    groups = distinct_shapes(ready)
    with tempfile.TemporaryDirectory(prefix="p1_identity_") as tmp:
        root = Path(tmp)
        exists = lambda rel: (root / rel).is_file()                        # noqa: E731
        for key, members in groups.items():
            if any(m.element_id in owned for m in members):
                path = root / _glb_rel(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"glTF-stub")
        todo, reused = [], []
        for key, members in groups.items():
            disk = storage_key(exists, key, members)
            (reused if exists(_glb_rel(disk)) else todo).append(key)
    bound = sum(len(v) for v in groups.values())
    return {
        "ready_rows": len(ready), "held_rows": len(held), "groups": len(groups),
        "generations": len(todo), "reused_groups": len(reused),
        "instances_bound": bound,
        "instances_per_generation": round(bound / len(todo), 3) if todo else None,
        "asset_reuse_rate": round(1 - len(todo) / bound, 4) if bound else None,
        "owned_rows": [e.element_id for e in els if e.element_id in owned],
    }


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:                                                      # noqa: BLE001
        return "unknown"


def run() -> dict:
    report: dict = {
        "_about": __doc__.strip().splitlines()[0],
        "schema_version": "1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "resolver": "app.intelligence.scene_reading.resolve_elements (shipped code, no model)",
        "cases": {},
        "absent_cases": [c for c in ("ablation_real_project",) if c not in CASES],
    }
    totals = {"n_elements": 0, "n_trustworthy": 0, "definitions": 0, "truth_groups": 0,
              "instances": 0, "false_merges": 0, "false_splits": 0, "cells": 0, "cells_correct": 0}
    for name, build in CASES.items():
        els, truth = build()
        s = score(els, truth)
        report["cases"][name] = s
        for k in ("n_elements", "n_trustworthy", "definitions", "truth_groups",
                  "instances", "false_merges", "false_splits"):
            totals[k] += s[k]
        totals["cells"] += s["instance_count"]["cells"]
        totals["cells_correct"] += s["instance_count"]["cells_correct"]

    g_els, _ = golden_living_room()
    gen = generations(g_els)
    report["cases"]["golden_living_room_01"]["spend"] = gen

    report["totals"] = {
        **totals,
        "cases": len(CASES),
        "false_merge_rate": round(totals["false_merges"] / totals["definitions"], 4),
        "false_split_rate": round(totals["false_splits"] / totals["truth_groups"], 4),
        "instance_count_accuracy": round(totals["cells_correct"] / totals["cells"], 4),
    }
    g = report["cases"]["golden_living_room_01"]
    report["golden_acceptance"] = {
        "element_kinds_rows": 10,
        "definitions": g["definitions"],
        "instances": g["instances"],
        "generations": gen["generations"],
        "false_merges": g["false_merges"],
        "false_splits": g["false_splits"],
        "note": ("task.md section 29.1 states '10 definitions, 17 instances, <=9 generations' AND "
                 "requires the 2 side tables to stay 2 definitions. Both cannot hold: 10 element "
                 "rows with the side-table row split is 11 definitions and, with the TV unit "
                 "already owned, 10 generations. The no-false-merge rule governs (the ablation's "
                 "own decision rule), so 11 / 17 / 10 is the correct arithmetic. Recorded as "
                 "correction C10 in TRACK_RECORD.md."),
    }
    return report


def main() -> int:
    report = run()
    print(f"{'case':42s}{'N':>4s}{'defs':>6s}{'truth':>7s}{'inst':>6s}{'fm':>4s}{'fs':>4s}{'cnt-acc':>9s}")
    for name, s in report["cases"].items():
        print(f"{name:42s}{s['n_trustworthy']:>4d}{s['definitions']:>6d}{s['truth_groups']:>7d}"
              f"{s['instances']:>6d}{s['false_merges']:>4d}{s['false_splits']:>4d}"
              f"{s['instance_count']['accuracy']:>9.3f}")
    t = report["totals"]
    print(f"\nTOTAL over {t['cases']} cases, N={t['n_trustworthy']} rows: false-merge rate "
          f"{t['false_merge_rate']} ({t['false_merges']}/{t['definitions']} definitions), "
          f"false-split rate {t['false_split_rate']} ({t['false_splits']}/{t['truth_groups']} pieces), "
          f"instance-count accuracy {t['instance_count_accuracy']} ({t['cells_correct']}/{t['cells']} cells)")
    g = report["golden_acceptance"]
    sp = report["cases"]["golden_living_room_01"]["spend"]
    print(f"golden: {g['definitions']} definitions, {g['instances']} instances, {g['generations']} generations "
          f"({sp['reused_groups']} group reused: {sp['owned_rows']}), "
          f"reuse rate {sp['asset_reuse_rate']}, {sp['instances_per_generation']} instances/generation")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

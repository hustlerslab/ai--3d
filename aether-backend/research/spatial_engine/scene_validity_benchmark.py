"""Phases 11-12: audit the PRODUCTION solver and validator across many briefs.

    python -u research/spatial_engine/scene_validity_benchmark.py

Research only. Nothing in `app/` imports this. It drives production code
(`compile_scene`, `resolve_plan`, `place_objects`, `validate_scene`) exactly as
the scene-plan job does, on an isolated scratch data directory, and measures
what comes out. No production file is modified.

WHY AN AUDIT AND NOT A NEW SOLVER. The brief asks for a deterministic
candidate-pose placement solver with hard/soft constraints and a collision /
clearance / bounds validator. Production already has both: `place_objects`
generates wall-, surface- and relation-anchored candidates and ranks them;
`validate_scene` runs SAT footprint collision, wall collision, room bounds and
door clearance. What it does not have is a measurement of how often the
result is valid beyond one asserted brief. That is what this produces.

METRICS, per brief and overall: objects requested vs placed, hard violations
by code (COLLIDES_OBJECT, COLLIDES_WALL, OUTSIDE_ROOM, BLOCKS_DOOR, ...), warn
violations by code, scene validity (zero hard violations), determinism (two
runs, identical positions), latency.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

# Isolated data directory, exactly as tests/conftest.py's `env` fixture does,
# BEFORE any app import caches settings.
_SCRATCH = Path(tempfile.mkdtemp(prefix="allure_scene_validity_"))
os.environ["AETHER_DATA_DIR"] = str(_SCRATCH / "data")
for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MESHY_API_KEY"):
    os.environ[k] = ""
os.environ["INTELLIGENCE_PROVIDER"] = "auto"
os.environ["SCENE_IMAGE_ENABLED"] = "false"

from app.core import config                                            # noqa: E402
config.get_settings.cache_clear()

from app.intelligence import InputBundle                               # noqa: E402
from app.intelligence.mock_provider import MockProvider                # noqa: E402
from app.intelligence.vocab import Vertical                            # noqa: E402
from app.planning import compile_scene, place_objects, resolve_plan     # noqa: E402
from app.spatial.validation import validate_scene                      # noqa: E402

OUT = HERE / "scene_validity_results.json"

#: A fixed brief set spanning verticals, sizes and room mixes. Frozen here.
BRIEFS = [
    ("res_1bhk", "residential", "1BHK in Mumbai for a single professional. Compact, a sofa, a small dining table for two, a work desk."),
    ("res_2bhk", "residential", "2BHK in Pune for a young couple. Warm modern minimal with oak floors, a big sofa, a dining table for six and lots of plants. Keep the master bedroom calm."),
    ("res_3bhk", "residential", "3BHK in Bangalore for a family of four. Kids bedroom, master bedroom, guest room, living room with a large sectional, dining for eight, home office corner."),
    ("res_studio", "residential", "Studio apartment. Bed, wardrobe, a two-seater sofa, a coffee table, a small kitchen counter and a tv unit."),
    ("res_villa", "residential", "4 bedroom villa in Goa. Two living rooms, a formal dining room for ten, a library with bookshelves and armchairs, a master suite with a dresser."),
    ("res_minimal", "residential", "Minimal 2 bedroom flat. Very little furniture: a bed in each room, one sofa, one dining table for four."),
    ("hosp_hotel", "hospitality", "Boutique hotel with 24 keys. Lobby with lounge sofas and a reception desk, a restaurant for 60 covers, guest rooms with a bed and desk."),
    ("hosp_restaurant", "hospitality", "Brasserie restaurant for 80 covers. Banquettes along the walls, booths, a long bar counter, tables for four."),
    ("off_open", "industrial", "Open plan office for 40 staff. Bench workstations, two meeting rooms for eight, a reception, a private office."),
    ("off_small", "industrial", "Small studio office for 8 people. Workstations, one meeting table, a lounge corner with a sofa."),
    ("res_dense", "residential", "2BHK packed with furniture: a sofa, two armchairs, a coffee table, a side table, a tv unit, a bookshelf, a dining table for six with chairs, a bed with two bedside tables and a wardrobe in each bedroom, plants everywhere."),
    ("res_odd", "residential", "Small 2 bedroom home with a very long narrow living room. A sofa, a dining table for four, a console, a floor lamp."),
]


def run_brief(brief_id: str, vertical: str, text: str) -> dict:
    try:
        vert = Vertical(vertical)
    except Exception:                                                   # noqa: BLE001
        vert = Vertical.RESIDENTIAL
    bundle = InputBundle(project_id=f"bench_{brief_id}", description=text, vertical=vert)
    mock = MockProvider()

    def once() -> tuple:
        t = time.perf_counter()
        analysis = mock.analyze_input(bundle)
        style = mock.create_style_spec(analysis, bundle)
        scene, warnings = compile_scene(f"bench_{brief_id}", analysis, style, name=brief_id)
        plan = mock.plan_objects(analysis, style, bundle)
        assets = resolve_plan(plan, style)
        ops, place_warnings = place_objects(scene, plan, assets)
        scene.objects = [op.object for op in ops]
        violations = validate_scene(scene)
        return (scene, plan, ops, list(warnings) + list(place_warnings), violations,
                time.perf_counter() - t)

    scene, plan, ops, warnings, violations, secs = once()
    _scene2, _p2, ops2, _w2, _v2, _s2 = once()
    pos1 = [(o.object.semantic_type, tuple(round(v, 6) for v in o.object.position),
             round(o.object.rotation_y, 6)) for o in ops]
    pos2 = [(o.object.semantic_type, tuple(round(v, 6) for v in o.object.position),
             round(o.object.rotation_y, 6)) for o in ops2]

    hard = [{"code": v.code, "object_id": v.object_id, "related_id": v.related_id,
             "message": v.message} for v in violations if v.severity == "hard"]
    warn = [{"code": v.code, "object_id": v.object_id} for v in violations if v.severity != "hard"]
    requested = sum(int(getattr(i, "count", 1) or 1) for i in plan.items)
    return {"id": brief_id, "vertical": vert.value, "brief": text,
            "rooms": [r.type for r in scene.rooms], "room_count": len(scene.rooms),
            "requested": requested, "plan_items": len(plan.items), "placed": len(ops),
            "placed_pct": round(100.0 * len(ops) / max(1, requested), 1),
            "unplaced": [w for w in warnings if "place" in w.lower() or "skip" in w.lower()][:10],
            "warnings_total": len(warnings),
            "hard": hard, "warn": warn, "valid": not hard,
            "hard_by_code": {c: sum(1 for h in hard if h["code"] == c) for c in {h["code"] for h in hard}},
            "deterministic": pos1 == pos2, "latency_s": round(secs, 3),
            "objects_by_type": {t: sum(1 for o in ops if o.object.semantic_type == t)
                                for t in sorted({o.object.semantic_type for o in ops})}}


def main() -> int:
    rows = []
    for brief_id, vertical, text in BRIEFS:
        try:
            r = run_brief(brief_id, vertical, text)
        except Exception as exc:                                        # noqa: BLE001
            r = {"id": brief_id, "vertical": vertical, "brief": text,
                 "error": f"{type(exc).__name__}: {exc}"[:300],
                 "valid": False, "requested": 0, "placed": 0, "hard": [], "warn": [],
                 "deterministic": None}
        rows.append(r)
        print(f"  {brief_id:16} {r.get('vertical', '?'):12} rooms={r.get('room_count', '?'):>2} "
              f"placed {r['placed']:>2}/{r['requested']:<2} hard={len(r['hard'])} "
              f"warn={len(r['warn'])} valid={r['valid']} det={r['deterministic']} "
              f"{r.get('error', '')}", flush=True)

    hard_by, warn_by = {}, {}
    for r in rows:
        for h in r["hard"]:
            hard_by[h["code"]] = hard_by.get(h["code"], 0) + 1
        for w in r["warn"]:
            warn_by[w["code"]] = warn_by.get(w["code"], 0) + 1
    requested = sum(r["requested"] for r in rows)
    placed = sum(r["placed"] for r in rows)
    lat = sorted(r.get("latency_s", 0) for r in rows)
    summary = {"scenes": len(rows), "valid": sum(1 for r in rows if r["valid"]),
               "valid_pct": round(100.0 * sum(1 for r in rows if r["valid"]) / len(rows), 1),
               "errors": sum(1 for r in rows if "error" in r),
               "requested": requested, "placed": placed,
               "placed_pct": round(100.0 * placed / max(1, requested), 1),
               "hard_violations": sum(len(r["hard"]) for r in rows),
               "hard_by_code": hard_by, "warn_by_code": warn_by,
               "deterministic": all(r["deterministic"] for r in rows
                                    if r["deterministic"] is not None),
               "latency_s_median": lat[len(lat) // 2] if lat else None,
               "scene_success_definition": "zero hard violations from validate_scene AND every "
                                           "requested object placed; stylistic warnings do "
                                           "not fail it",
               "scene_success": sum(1 for r in rows if r["valid"] and r["placed"] == r["requested"]),
               "provider": "MockProvider (deterministic; no VLM) - this measures the SOLVER "
                           "and VALIDATOR, not the language model"}
    OUT.write_text(json.dumps({"_about": "Phases 11-12 audit of the production placement solver "
                                         "and validator across a frozen brief set.",
                               "summary": summary, "briefs": rows}, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n  scenes {summary['scenes']}  valid {summary['valid']} ({summary['valid_pct']}%)  "
          f"success {summary['scene_success']}  placed {placed}/{requested} ({summary['placed_pct']}%)")
    print(f"  hard by code {hard_by}  warn by code {warn_by}  deterministic {summary['deterministic']}")
    print(f"  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

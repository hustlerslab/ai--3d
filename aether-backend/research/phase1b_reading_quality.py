"""Phase 1b: is the local reading good enough to plan a room from?

    python research/phase1b_reading_quality.py [--tag before|after]

Reads five real moodboard renders FRESH through the real local provider, then
walks the whole chain - coercion, spatial graph, object-plan bridge - counting
what survives each step. Writes docs/benchmarks/phase_1b_<tag>.json.

Deliberately calls `OllamaProvider` directly rather than `get_provider()`. The
resilient wrapper falls back to the mock on failure, and a mock sofa would be
counted here as a real one. A failed read must be reported as a failed read.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence.ollama_provider import OllamaError, OllamaProvider  # noqa: E402
from app.intelligence.scene_reading import coerce_room_reading        # noqa: E402
from app.intelligence.schema import (                                 # noqa: E402
    ObjectPlan, ObjectPlanItem, SceneReading, StyleSpec)
from app.planning.spatial_graph import apply_spatial_graph, build_spatial_graph  # noqa: E402

OUT_DIR = ROOT.parent / "docs" / "benchmarks"

#: The same five renders Phase 0d used, so results line up across phases.
IMAGES = [
    ("living_room", "data/projects/proj_553cb09794/analysis/moodboard_room_living_room.png"),
    ("kitchen", "data/projects/proj_553cb09794/analysis/moodboard_room_kitchen.png"),
    ("bathroom", "data/projects/proj_553cb09794/analysis/moodboard_room_bathroom.png"),
    ("master_bedroom", "data/archive/proj_5db681f48c/moodboard/moodboard_room_master_bedroom.png"),
    ("living_room", "data/archive/proj_5db681f48c/moodboard/moodboard_room_living_room.png"),
]

_CAMERA = ("left", "right", "front", "back", "rear", "behind", "up", "down",
           "north", "south", "east", "west", "forward", "upward", "downward")
_WALLISH = ("wall", "window", "glazing", "corner", "french door", "alcove")
_ROOMISH = ("into the room", "room", "centre", "center", "middle", "inward", "inside")
#: Answers that are true but carry no arrangement information. Everything stands
#: on the floor, so "floor" tells a planner nothing about where in the room.
_VACUOUS = ("floor", "ground", "carpet", "nothing", "none", "n/a", "the floor")


class _Room:
    def __init__(self, room_type: str):
        self.room_id = self.name = room_type
        self.type = room_type
        self.width_m, self.length_m = 5.0, 4.0


def classify(value: str, siblings: set[str]) -> str:
    """named_target | wall | room | vacuous | camera_relative | empty | unknown."""
    text = (value or "").strip().lower()
    if not text:
        return "empty"
    if text in _VACUOUS:
        return "vacuous"
    for sibling in siblings:
        if sibling and sibling.replace("_", " ") in text:
            return "named_target"
    if any(word in text for word in _WALLISH):
        return "wall"
    if any(word in text for word in _ROOMISH):
        return "room"
    if any(word in text for word in _CAMERA):
        return "camera_relative"
    if any(word in text for word in ("floor", "ground")):
        return "vacuous"
    return "unknown"


def read_room(provider, room_type: str, image: Path, room_id: str = "") -> dict:
    started = time.perf_counter()
    room_id = room_id or room_type
    row: dict = {"room_type": room_type, "room_id": room_id,
                 "image": str(image).replace("\\", "/")}
    try:
        raw = provider.read_scene_elements(
            image, _Room(room_type), StyleSpec(name="B", tags=["modern"]), "residential")
        row["status"] = "ok"
    except OllamaError as exc:
        row.update(status="QWEN FAILURE", code=getattr(exc, "code", "?"),
                   error=str(exc)[:160], elapsed_s=round(time.perf_counter() - started, 1))
        return row
    row["elapsed_s"] = round(time.perf_counter() - started, 1)
    row["generation_status"] = raw.get("_status", "complete")
    row["salvaged"] = bool(raw.get("_warnings"))
    row["elements_raw"] = len(raw.get("elements") or [])

    warnings: list[str] = []
    elements, _surfaces = coerce_room_reading(raw, _Room(room_type), "residential", warnings)
    for index, el in enumerate(elements):
        el.room_id = room_id
        if not el.element_id:
            el.element_id = f"{room_id}_{index}"
    row["elements_coerced"] = len(elements)
    row["rejected"] = row["elements_raw"] - len(elements)
    row["rejection_reasons"] = warnings[:8]
    row["with_bbox"] = sum(1 for e in elements if e.bbox)

    siblings = {e.semantic_type for e in elements}
    for field in ("against", "faces"):
        tally: dict[str, int] = {}
        samples: list[str] = []
        for el in elements:
            value = getattr(el, field)
            kind = classify(value, siblings - {el.semantic_type})
            tally[kind] = tally.get(kind, 0) + 1
            if value and len(samples) < 6:
                samples.append(f"{el.semantic_type}: {value!r} -> {kind}")
        row[field] = tally
        row[f"{field}_samples"] = samples
    row["on_surface"] = sum(1 for e in elements if e.placement == "on_surface")
    row["_elements"] = elements
    return row


def _merge_tallies(rows, field) -> dict:
    out: dict[str, int] = {}
    for row in rows:
        for key, count in row[field].items():
            out[key] = out.get(key, 0) + count
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _count(items, attribute) -> dict:
    out: dict[str, int] = {}
    for obj in items:
        key = str(getattr(obj, attribute))
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="before")
    args = parser.parse_args()

    provider = OllamaProvider()
    print(f"model: {provider.label}   images: {len(IMAGES)}   tag: {args.tag}\n", flush=True)

    rows = []
    for index, (room_type, rel) in enumerate(IMAGES):
        # A unique room id per READ. Two of the five renders are living rooms,
        # and sharing an id merged them into one room: every piece in render A
        # became a neighbour of every piece in render B, which inflated the
        # pairwise relation count without any of it being real.
        row = read_room(provider, room_type, ROOT / rel, room_id=f"{room_type}_{index}")
        if row["status"] != "ok":
            print(f"  {room_type:15} {row['status']} [{row.get('code')}] "
                  f"{row['elapsed_s']}s", flush=True)
        else:
            print(f"  {room_type:15} {row['elements_coerced']:2} elements "
                  f"({row['rejected']} rejected)  against={row['against']}  "
                  f"faces={row['faces']}  {row['elapsed_s']}s", flush=True)
        rows.append(row)

    usable = [r for r in rows if r["status"] == "ok"]
    elements = [e for r in usable for e in r["_elements"]]
    reading = SceneReading(elements=elements, provider=provider.label)
    graph = build_spatial_graph(reading)

    plan = ObjectPlan(provider="benchmark", rooms=sorted({e.room_id for e in elements}),
                      items=[ObjectPlanItem(
                          object_key=f"{e.room_id}.{e.semantic_type}.{i}",
                          semantic_type=e.semantic_type, room_id=e.room_id,
                          element_id=e.element_id, placement=e.placement)
                          for i, e in enumerate(elements)])
    plan, notes = apply_spatial_graph(plan, graph)

    predicates: dict[str, int] = {}
    for relation in graph.relations:
        predicates[relation.predicate] = predicates.get(relation.predicate, 0) + 1

    summary = {
        "tag": args.tag,
        "model": provider.label,
        "rooms_read": len(rows),
        "rooms_failed": sum(1 for r in rows if r["status"] != "ok"),
        "elements_total": len(elements),
        "avg_elapsed_s": round(statistics.mean([r["elapsed_s"] for r in rows]), 1),
        "against": _merge_tallies(usable, "against"),
        "faces": _merge_tallies(usable, "faces"),
        "graph": {
            "nodes": len(graph.nodes), "relations": len(graph.relations),
            "predicates": predicates,
            "camera_frame": sum(1 for r in graph.relations if r.frame == "camera"),
            "semantic": sum(1 for r in graph.relations
                            if r.source in ("semantic", "placement", "semantic+geometry")),
            "confidence": _count(graph.relations, "confidence"),
            "groups": len(graph.groups), "conflicts": len(graph.conflicts),
        },
        "plan": {
            "items": len(plan.items),
            "relation_populated": sum(1 for i in plan.items if i.relation),
            "support_key_populated": sum(1 for i in plan.items if i.support_key),
            "relation_types": _count([i.relation for i in plan.items if i.relation], "type"),
            "notes": notes,
        },
        "per_room": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"phase_1b_{args.tag}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    good = summary["rooms_read"] - summary["rooms_failed"]
    print(f"\n  elements   : {summary['elements_total']} over {good} good read(s)")
    print(f"  against    : {summary['against']}")
    print(f"  faces      : {summary['faces']}")
    print(f"  graph      : {summary['graph']['nodes']} nodes, "
          f"{summary['graph']['relations']} relations, "
          f"{summary['graph']['semantic']} semantic, "
          f"{summary['graph']['camera_frame']} camera-frame")
    print(f"  predicates : {predicates}")
    print(f"  plan       : relation={summary['plan']['relation_populated']}, "
          f"support_key={summary['plan']['support_key_populated']} "
          f"of {summary['plan']['items']} items")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

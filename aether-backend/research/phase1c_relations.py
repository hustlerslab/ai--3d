"""Phase 1c: can the local model answer ONE spatial question at a time?

    python -u research/phase1c_relations.py [--variants A,B,C] [--limit N]

Research only. Imports production code, writes nothing into it.

Phase 1b measured the bulk scene read and found the relationship fields empty:
across 31 elements over 10 fresh reads, `faces` named a piece ZERO times. The
hypothesis under test here is that the failure is the QUESTION, not the model -
that a reader asked to box eleven objects, name their materials and describe
two surfaces in one pass has no attention left for "what is this turned toward",
and that asked on its own, with a closed list of answers, it can say.

Three things make this a measurement of relation extraction and nothing else:

* The object inventory is the HAND-ANNOTATED one, not a fresh read. A fresh read
  would fold detection quality back into the score, and Phase 1b already
  measured that separately. Production would feed the reader's own inventory,
  whose quality is the Phase 1b number.
* The answer is constrained by a JSON Schema `enum` of the candidate ids, so an
  invented target is not merely penalised, it is unrepresentable. Hallucination
  therefore means something sharper here - naming a real object where the truth
  is that nothing qualifies - and that is what the negative controls test.
* Geometry is never consulted. This asks what the model can see.

Nothing here touches coordinates, Blender, the compiler or the spatial graph.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence import vocab                                      # noqa: E402
from app.intelligence.ollama_provider import (                          # noqa: E402
    OllamaError, OllamaProvider)

FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
OUT_DIR = ROOT.parent / "docs" / "benchmarks"
CROP_DIR = Path(tempfile.gettempdir()) / "phase1c_crops"

#: Pieces with a front. Built from the vocab families rather than a new list:
#: everything that seats a person is turned toward something, plus the two
#: worked-at pieces. `ottoman` and `stool` are excluded deliberately - a
#: backless block has no front, so the question is meaningless for them.
FACES_ELIGIBLE = {t for t, fam in vocab.FAMILY_BY_TYPE.items() if fam == "seating"}
FACES_ELIGIBLE -= {"ottoman", "stool"}
FACES_ELIGIBLE |= {"bed", "desk"}

#: Pieces that back onto something. The brief names "sofa, bed, cabinet,
#: console, tv_unit, bookshelf"; `cabinet` is not a type in this vocabulary, and
#: the pieces that ARE cabinets here are the ones listed after console.
AGAINST_ELIGIBLE = {
    "sofa", "loveseat", "lounge_sofa", "bed", "console", "tv_unit", "bookshelf",
    "sideboard", "wardrobe", "dresser", "kitchen_counter", "vanity",
    "bar_counter", "reception_desk", "banquette",
}

#: Pieces that stand ON another piece. Straight out of the existing vocabulary,
#: as the brief requires: no new taxonomy. `plant` reaches it through
#: SUPPORT_PREFERENCE, since PLACEMENT_BY_TYPE leaves plants on the floor and
#: both are true - some stand on a console, some on the ground.
SUPPORTED_ELIGIBLE = ({t for t, p in vocab.PLACEMENT_BY_TYPE.items() if p == "on_surface"}
                      | set(vocab.SUPPORT_PREFERENCE))

#: The anchors Budget B asks about, from the brief.
BUDGET_B_TYPES = {"sofa", "bed", "desk", "dining_table", "tv_unit", "kitchen_counter",
                  "sideboard", "console", "wardrobe", "vanity"}

QUESTION = {
    "faces": "Which ONE of the listed candidates is this piece turned towards?",
    "against": "Which ONE of the listed candidates is this piece pushed up against, "
               "or immediately next to?",
    "supported_by": "Which ONE of the listed candidates is this piece standing ON?",
}

RULE = {
    "faces": ("A sofa faces a television. A dining chair faces the table. A bar stool "
              "faces the counter it is pulled up to. If the piece is turned towards "
              "nothing in particular - out into the middle of the room - answer "
              "open_room. If you cannot tell from the picture, answer unknown."),
    "against": ("Answer wall if its back is flat against a wall, window if it stands "
                "under or against a window, or name the piece it touches. The FLOOR IS "
                "NOT AN ANSWER and is not offered: everything stands on the floor. If "
                "it stands free in the room, or you cannot tell, answer unknown."),
    "supported_by": ("Only answer with a piece whose top surface this object is resting "
                     "on. A cushion rests on a sofa. A vase rests on a coffee table. If "
                     "this object is on the floor, hanging on the wall, or you cannot "
                     "see what holds it, answer unknown - do not guess a likely one."),
}

EXTRA_CANDIDATES = {
    "faces": ["window", "open_room", "unknown"],
    "against": ["wall", "window", "unknown"],
    "supported_by": ["unknown"],
}


def eligible(relation: str, semantic_type: str) -> bool:
    return semantic_type in {"faces": FACES_ELIGIBLE, "against": AGAINST_ELIGIBLE,
                             "supported_by": SUPPORTED_ELIGIBLE}[relation]


def candidates_for(relation: str, source: dict, objects: list[dict]) -> list[dict]:
    """The closed list this query may answer from.

    For `supported_by` the list is filtered by the existing vocabulary -
    SURFACE_HEIGHT is the set of types with a usable top - so the model is never
    offered a rug or a mirror as a support and cannot pick one.
    """
    others = [o for o in objects if o["id"] != source["id"]]
    if relation == "supported_by":
        others = [o for o in others if o["type"] in vocab.SURFACE_HEIGHT]
    return others


def crop_path(room_key: str, obj: dict, image: Path) -> Path:
    """The source object cut out of the render, cached on disk.

    Padded by 5% so the piece is not shaved by annotation error, and upscaled to
    at least 224 px because a 14-pixel-tall floating shelf carries no signal at
    native size.
    """
    from PIL import Image

    CROP_DIR.mkdir(parents=True, exist_ok=True)
    out = CROP_DIR / f"{room_key}__{obj['id'].replace('.', '_')}.png"
    if out.is_file():
        return out
    with Image.open(image) as im:
        im = im.convert("RGB")
        x1, y1, x2, y2 = obj["bbox"]
        pad_x, pad_y = int((x2 - x1) * 0.05) + 2, int((y2 - y1) * 0.05) + 2
        box = (max(0, x1 - pad_x), max(0, y1 - pad_y),
               min(im.width, x2 + pad_x), min(im.height, y2 + pad_y))
        piece = im.crop(box)
        if min(piece.size) < 224:
            scale = 224 / max(1, min(piece.size))
            piece = piece.resize((max(1, int(piece.width * scale)),
                                  max(1, int(piece.height * scale))), Image.LANCZOS)
        piece.save(out)
    return out


def build_prompt(relation: str, room: dict, source: dict, candidates: list[dict],
                 variant: str) -> str:
    extras = EXTRA_CANDIDATES[relation]
    lines = []
    if variant == "A":
        lines.append("You are looking at one photograph of a room.")
    elif variant == "B":
        lines.append("You are looking at a close-up of ONE piece of furniture, cut "
                     "out of a photograph of a room.")
    else:
        lines.append("You are looking at TWO images of the same room. The FIRST is a "
                     "close-up of one piece, cut out of the second. The SECOND is the "
                     "whole room, so you can see what surrounds that piece.")
    lines += [
        "",
        f"Room: {room['room_type'].replace('_', ' ')}.",
        f"The piece in question is: {source['desc']} (a {source['type'].replace('_', ' ')}).",
        "",
        QUESTION[relation],
        RULE[relation],
        "",
        "Answer with ONE id from this list and nothing else. Do not invent an id.",
    ]
    for cand in candidates:
        lines.append(f"  {cand['id']} - {cand['desc']} (a {cand['type'].replace('_', ' ')})")
    for extra in extras:
        lines.append(f"  {extra}")
    lines += [
        "",
        'Reply as JSON: {"target_id": "<one id from the list>", '
        '"confidence": "high" | "medium" | "low"}',
    ]
    return "\n".join(lines)


def build_schema(candidates: list[dict], relation: str) -> dict:
    """An enum of exactly the ids on offer.

    This is the candidate-ID contract made mechanical rather than requested. A
    free-text `target_id` would need fuzzy matching back onto the plan and could
    name furniture that is not in the room; an enum cannot.
    """
    ids = [c["id"] for c in candidates] + EXTRA_CANDIDATES[relation]
    return {
        "type": "object",
        "properties": {
            "target_id": {"type": "string", "enum": ids},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["target_id", "confidence"],
    }


def default_answer(relation: str, source: dict, objects: list[dict]) -> str:
    """What the system already assumes with no evidence at all.

    Used to grade architectural value: an answer that matches this changes no
    placement, however correct it is. Verified against the compiler, not guessed
    - `_floor_candidates` falls through to `_wall_aligned_candidates` for every
    floor piece, which both backs it onto a wall and turns it into the room, and
    `_pick_support` ranks hosts by SUPPORT_PREFERENCE when `support_key` is empty.
    """
    if relation == "faces":
        return "open_room"
    if relation == "against":
        return "wall"
    prefs = vocab.SUPPORT_PREFERENCE.get(source["type"], [])
    present = {o["type"]: o["id"] for o in objects if o["id"] != source["id"]}
    for pref in prefs:
        if pref in present:
            return present[pref]
    return "unknown"


def run_query(provider: OllamaProvider, relation: str, room: dict, source: dict,
              candidates: list[dict], variant: str, image: Path) -> dict:
    prompt = build_prompt(relation, room, source, candidates, variant)
    schema = build_schema(candidates, relation)
    max_px = provider._settings.ollama_scene_image_max_px

    if variant == "A":
        images = [provider._encode(image, max_px)]
    elif variant == "B":
        images = [provider._encode(crop_path(room["room_key"], source, image), max_px)]
    else:
        images = [provider._encode(crop_path(room["room_key"], source, image), max_px),
                  provider._encode(image, max_px)]

    row = {"variant": variant, "room": room["room_key"], "source": source["id"],
           "relation": relation, "candidates": len(candidates) + len(EXTRA_CANDIDATES[relation])}
    started = time.perf_counter()
    try:
        # `array_key=None` on purpose: there is no array to loop over here, so the
        # guard watches only for a runaway string - which is the failure shape a
        # one-field answer can actually have.
        payload, status = provider._generate_traced(
            prompt, schema, f"relation:{relation}", images=images, array_key=None)
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["status"] = status.value
        row["answer"] = (payload or {}).get("target_id") or ""
        row["confidence"] = (payload or {}).get("confidence") or ""
        valid = {c["id"] for c in candidates} | set(EXTRA_CANDIDATES[relation])
        row["off_list"] = bool(row["answer"]) and row["answer"] not in valid
    except OllamaError as exc:
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["status"] = getattr(exc, "code", "MODEL_FAILURE")
        row["answer"] = ""
        row["error"] = str(exc)[:160]
        row["off_list"] = False
    return row


def score(row: dict, truth: dict, objects: list[dict]) -> dict:
    """Grade one answer. Six independent judgements, never merged into one."""
    answer, target = row["answer"], truth["target"]
    lenient_set = {target} | set(truth.get("also_acceptable") or [])
    known_ids = {o["id"] for o in objects}

    row["truth"] = target
    row["verdict"] = truth["verdict"]
    row["scoreable"] = truth["verdict"] == "TRUE" and bool(answer)
    row["answered"] = bool(answer)
    row["strict"] = bool(answer) and answer == target
    row["lenient"] = bool(answer) and answer in lenient_set
    row["is_negative_control"] = target in ("unknown", "open_room")
    # A hallucinated relation: the model named a real object where the truth is
    # a different object or no object at all. Naming an object that is merely
    # the WRONG one is exactly as damaging to a Blender placement as inventing
    # a relation from nothing, so both count.
    row["hallucinated"] = bool(answer) and answer in known_ids and not row["lenient"]
    row["abstained"] = answer in ("unknown", "open_room")
    # Architectural value: does acting on this answer move anything the system
    # would not already have done for free?
    row["useful"] = row["lenient"] and target != default_answer(
        row["relation"], next(o for o in objects if o["id"] == row["source"]), objects)
    return row


def budgets(rows: list[dict], fixture: dict) -> dict:
    """Budgets B and C are SUBSETS of the queries budget A already ran, so they
    cost no extra GPU time - they are a filter over the same answers, which is
    also the only way to compare them on identical model behaviour."""
    by_id = {o["id"]: o for room in fixture["rooms"] for o in room["objects"]}

    def anchor(row) -> bool:
        return by_id[row["source"]]["type"] in BUDGET_B_TYPES

    def ambiguous(row) -> bool:
        """Budget C: only where the free default is not already the answer.

        This is the honest version of 'objects whose orientation is ambiguous
        after initial planning' - the planner's default IS the prior, so the
        queries worth spending are the ones where it is wrong. Selected on the
        GROUND TRUTH, so this is an upper bound on what a real pre-filter could
        achieve, not a shippable rule. Reported as such."""
        room = next(r for r in fixture["rooms"] if r["room_key"] == row["room"])
        return row["truth"] != default_answer(row["relation"], by_id[row["source"]],
                                              room["objects"])

    out = {}
    for name, keep in (("A", lambda r: True), ("B", anchor), ("C", ambiguous)):
        subset = [r for r in rows if keep(r)]
        scoreable = [r for r in subset if r["scoreable"]]
        rooms_seen = len({r["room"] for r in rows}) or 1
        out[name] = {
            "queries": len(subset),
            "queries_per_room": round(len(subset) / rooms_seen, 1),
            "accuracy_lenient": _pct(sum(r["lenient"] for r in scoreable), len(scoreable)),
            "useful_relations": sum(r["useful"] for r in scoreable),
            "estimated_room_latency_s": round(
                (len(subset) / rooms_seen) * _median([r["elapsed_s"] for r in subset]), 1),
        }
    return out


def _pct(part: int, whole: int):
    return None if not whole else round(100.0 * part / whole, 1)


def _median(values):
    return round(statistics.median(values), 2) if values else 0.0


def _p95(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2)


def summarise(rows: list[dict]) -> dict:
    lat = [r["elapsed_s"] for r in rows]
    scoreable = [r for r in rows if r["scoreable"]]
    negatives = [r for r in rows if r["is_negative_control"] and r["verdict"] == "TRUE"]
    truthful = [r for r in rows if r["verdict"] == "TRUE"]
    return {
        "queries": len(rows),
        "answered": sum(r["answered"] for r in rows),
        "json_success_pct": _pct(sum(r["answered"] for r in rows), len(rows)),
        "off_list_answers": sum(r["off_list"] for r in rows),
        "status": _tally(r["status"] for r in rows),
        "scoreable": len(scoreable),
        "accuracy_strict_pct": _pct(sum(r["strict"] for r in scoreable), len(scoreable)),
        "accuracy_lenient_pct": _pct(sum(r["lenient"] for r in scoreable), len(scoreable)),
        "hallucination_pct": _pct(sum(r["hallucinated"] for r in truthful), len(truthful)),
        "negative_controls": len(negatives),
        "negative_controls_correct": sum(r["lenient"] for r in negatives),
        "abstained": sum(r["abstained"] for r in rows),
        "useful_relations": sum(r["useful"] for r in scoreable),
        "latency": {"mean": round(statistics.mean(lat), 2) if lat else 0.0,
                    "median": _median(lat), "p95": _p95(lat),
                    "worst": round(max(lat), 2) if lat else 0.0},
    }


def _tally(values) -> dict:
    out: dict = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def by_relation(rows: list[dict]) -> dict:
    out = {}
    for relation in ("faces", "against", "supported_by"):
        subset = [r for r in rows if r["relation"] == relation]
        if subset:
            out[relation] = summarise(subset)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", default="A,B,C")
    parser.add_argument("--limit", type=int, default=0, help="first N queries per variant")
    args = parser.parse_args()

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provider = OllamaProvider()
    variants = [v.strip().upper() for v in args.variants.split(",") if v.strip()]

    plan = []
    for room in fixture["rooms"]:
        objects = room["objects"]
        by_id = {o["id"]: o for o in objects}
        for truth in room["relations"]:
            source = by_id[truth["source"]]
            if not eligible(truth["relation"], source["type"]):
                print(f"  SKIP {truth['source']} {truth['relation']}: not eligible by vocab")
                continue
            plan.append((room, source, truth,
                         candidates_for(truth["relation"], source, objects)))

    print(f"model: {provider.label}   rooms: {len(fixture['rooms'])}   "
          f"queries/variant: {len(plan)}   variants: {','.join(variants)}\n", flush=True)

    all_rows: list[dict] = []
    for variant in variants:
        print(f"-- variant {variant} " + "-" * 40, flush=True)
        todo = plan[:args.limit] if args.limit else plan
        for room, source, truth, candidates in todo:
            row = run_query(provider, truth["relation"], room, source, candidates,
                            variant, ROOT / room["image"])
            score(row, truth, room["objects"])
            mark = "ok " if row["lenient"] else ("HALL" if row["hallucinated"] else "  x")
            if truth["verdict"] != "TRUE":
                mark = "  -"
            print(f"  {mark} {row['relation']:12} {row['source']:34} "
                  f"-> {row['answer'] or '(failed)':34} (truth {row['truth']}) "
                  f"{row['elapsed_s']}s {row['status']}", flush=True)
            all_rows.append(row)

    report = {
        "model": provider.label,
        "dataset": {
            "rooms": len(fixture["rooms"]),
            "objects": sum(len(r["objects"]) for r in fixture["rooms"]),
            "annotated_relations": sum(len(r["relations"]) for r in fixture["rooms"]),
            "true": sum(1 for r in fixture["rooms"] for x in r["relations"]
                        if x["verdict"] == "TRUE"),
            "false": sum(1 for r in fixture["rooms"] for x in r["relations"]
                         if x["verdict"] == "FALSE"),
            "unknown": sum(1 for r in fixture["rooms"] for x in r["relations"]
                           if x["verdict"] == "UNKNOWN"),
            "queried": len(plan),
        },
        "overall": {v: summarise([r for r in all_rows if r["variant"] == v]) for v in variants},
        "by_relation": {v: by_relation([r for r in all_rows if r["variant"] == v])
                        for v in variants},
        "budgets": {v: budgets([r for r in all_rows if r["variant"] == v], fixture)
                    for v in variants},
        "rows": all_rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "phase_1c_raw.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    for variant in variants:
        s = report["overall"][variant]
        print(f"  {variant}: strict {s['accuracy_strict_pct']}%  lenient "
              f"{s['accuracy_lenient_pct']}%  halluc {s['hallucination_pct']}%  "
              f"json {s['json_success_pct']}%  median {s['latency']['median']}s  "
              f"useful {s['useful_relations']}")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

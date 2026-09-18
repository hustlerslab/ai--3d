"""Phase 1d: can the local model answer a spatial question that has a NO in it?

    python -u research/phase1d_binary_relations.py [--pilot-only] [--limit N]

Research only. Imports production code, writes nothing into it.

Phase 1c established the failure precisely. Asked to pick one target from a list
holding objects, `wall`, `window`, `open_room` and `unknown`, the model picked an
object 78 times out of 78 - so AGAINST, whose true answer was `wall` in all 30
cases, scored zero. It could see (`sofa -> television`, `vase -> coffee table`);
it could not decline.

So this phase stops asking it to decline against a list of objects. Each relation
becomes a chain of yes/no decisions, and the object list is only ever shown once
the yes/no gate has already established that an object is the answer:

    against      wall? --no--> beside furniture? --yes--> which piece?
    faces        front visible? --yes--> faces an object? --yes--> which piece?
    supported_by on furniture? --yes--> which piece?

At the moment the model finally chooses a target it is choosing OBJECT vs OBJECT,
never OBJECT vs WALL. That is the whole hypothesis.

The binary answer carries no confidence field on purpose: Phase 1c returned
"high" on 56 of 78 answers including most of the wrong ones, so a confidence
number from this model is a second thing to be wrong about, not a filter.

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
CROP_DIR = Path(tempfile.gettempdir()) / "phase1c_crops"   # shared with 1c; same boxes

BINARY_SCHEMA = {"type": "object",
                 "properties": {"answer": {"type": "boolean"}},
                 "required": ["answer"]}

#: Mode per relation, from the Phase 1c evidence: crop-only never helped, and the
#: full room was both fastest and most accurate for the two relations that need
#: context. Only support - where the object is a vase or a cushion a few pixels
#: across - gets the crop as well.
MODE = {"against": "full", "faces": "full", "supported_by": "crop+full"}

BUDGET_B_TYPES = {"sofa", "bed", "desk", "dining_table", "tv_unit", "kitchen_counter",
                  "sideboard", "console", "wardrobe", "vanity", "cabinet"}

#: Types that cannot anchor another piece's placement or be faced: textiles that
#: lie on the floor, things hung on walls, and small things that sit on surfaces.
#: All read out of the existing vocabulary - no new taxonomy.
_WALL_MOUNTED = {t for t, p in vocab.PLACEMENT_BY_TYPE.items() if p in ("wall", "ceiling")}
_ON_SURFACE = {t for t, p in vocab.PLACEMENT_BY_TYPE.items() if p == "on_surface"}
_NOT_AN_ANCHOR = _WALL_MOUNTED | _ON_SURFACE | {"rug", "curtains"}


# ── prompts ─────────────────────────────────────────────────────────────
#
# Exactly two wordings per question, as the brief requires. A is plain. B names
# the negative case out loud before asking, on the theory that Phase 1c's model
# never considered "not against a wall" to be an available world-state. Piloted
# once, then frozen - no C, no D.

def _piece(obj: dict) -> str:
    return f"{obj['desc']} (a {obj['type'].replace('_', ' ')})"


def _wall_a(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is its back or main side directly against a wall of the room?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _wall_b(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            "Furniture is placed in one of two ways, and both are common: pushed back "
            "flat against a wall, or standing out in the open floor with space behind "
            "it.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is its back or main side directly against a wall? Answer false if it "
            "stands out in the open floor.\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _adjacent_a(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is it directly against, or immediately beside, another piece of furniture?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _adjacent_b(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            "A piece standing away from the walls is sometimes placed right up against "
            "another piece - a stool pulled up to a counter, a table in front of a sofa "
            "- and sometimes stands on its own with clear floor all around it.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is it directly against, or immediately beside, another piece of furniture?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _orientation_a(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Can you tell which way it is facing from this image?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _orientation_b(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            "Some pieces have a front: a sofa, a chair, a bed, a television. Others have "
            "no front at all - a coffee table, an ottoman, a rug - and for those there "
            "is no facing direction to find.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Does it have a front whose direction you can see in this image?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _faces_object_a(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is it facing a particular object in the room?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _faces_object_b(room, obj):
    return (f"You are looking at a photograph of a {room['room_type'].replace('_', ' ')}.\n\n"
            "A piece can be turned toward a particular thing - a sofa toward a "
            "television - or simply turned out into the open room, with nothing "
            "in front of it at all.\n\n"
            f"Look at this piece: {_piece(obj)}.\n\n"
            "Is there a particular object in front of it that it faces?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _supported_a(room, obj):
    return ("The FIRST image is a close-up of one object. The SECOND is the whole "
            f"{room['room_type'].replace('_', ' ')} it was cut from.\n\n"
            f"The object is: {_piece(obj)}.\n\n"
            "Is it resting on top of another piece of furniture, rather than on the "
            "floor?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


def _supported_b(room, obj):
    return ("The FIRST image is a close-up of one object. The SECOND is the whole "
            f"{room['room_type'].replace('_', ' ')} it was cut from.\n\n"
            "Some objects rest on top of furniture - a vase on a table, a cushion on a "
            "sofa. Others stand on the floor, or hang on a wall, held up by no "
            "furniture at all.\n\n"
            f"The object is: {_piece(obj)}.\n\n"
            "Is it resting on top of another piece of furniture?\n"
            'Answer with JSON: {"answer": true} or {"answer": false}')


PROMPTS = {
    "wall": {"A": _wall_a, "B": _wall_b},
    "adjacent": {"A": _adjacent_a, "B": _adjacent_b},
    "orientation": {"A": _orientation_a, "B": _orientation_b},
    "faces_object": {"A": _faces_object_a, "B": _faces_object_b},
    "supported": {"A": _supported_a, "B": _supported_b},
}

#: Which binary question belongs to which relation, and which fixture field holds
#: its truth.
STAGE_TRUTH = {
    "wall": ("against", "wall"),
    "adjacent": ("against", "adjacent_object"),
    "orientation": ("faces", "orientation_visible"),
    "faces_object": ("faces", "faces_object"),
    "supported": ("supported_by", "supported"),
}

GATES = {"against": ("wall", "adjacent"),
         "faces": ("orientation", "faces_object"),
         "supported_by": ("supported", None)}

TARGET_QUESTION = {
    "against": "Which one of these is it directly against or immediately beside?",
    "faces": "Which one of these is it facing?",
    "supported_by": "Which one of these is it resting on top of?",
}


# ── candidate filtering (existing vocabulary + annotated geometry only) ──

def _gap(a: list[int], b: list[int]) -> float:
    """Pixel gap between two boxes; 0 when they touch or overlap."""
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx ** 2 + dy ** 2) ** 0.5


def adjacency_candidates(room: dict, source: dict) -> list[dict]:
    """Floor furniture near the source in the image.

    Geometry is used ONLY to shorten the list, never to answer - the brief keeps
    the coordinate decision with the compiler, and this is a pixel gap on a
    hand-annotated box, not a position.
    """
    out = [o for o in room["objects"]
           if o["id"] != source["id"] and o["type"] not in _NOT_AN_ANCHOR]
    return [o for o in out if _gap(source["bbox"], o["bbox"]) <= 0.25 * 704]


def faces_candidates(room: dict, source: dict) -> list[dict]:
    """Things a piece can be turned toward.

    A sofa is never offered a vase, a rug, a cushion or a lamp - the brief asks
    for that filtering explicitly, and `PLACEMENT_BY_TYPE` already encodes it.
    """
    return [o for o in room["objects"]
            if o["id"] != source["id"] and o["type"] not in _NOT_AN_ANCHOR]


def support_candidates(room: dict, source: dict) -> list[dict]:
    """Pieces with a usable top, preferred hosts first.

    `SURFACE_HEIGHT` is the existing set of types whose top is a surface;
    `SUPPORT_PREFERENCE` is the existing ranking. Neither is new.
    """
    prefs = vocab.SUPPORT_PREFERENCE.get(source["type"], [])
    hosts = [o for o in room["objects"]
             if o["id"] != source["id"] and o["type"] in vocab.SURFACE_HEIGHT]
    hosts.sort(key=lambda o: prefs.index(o["type"]) if o["type"] in prefs else 99)
    return hosts


CANDIDATES = {"against": adjacency_candidates, "faces": faces_candidates,
              "supported_by": support_candidates}


# ── the deterministic baseline (§15) ────────────────────────────────────

def deterministic(chain: str, source: dict, room: dict) -> dict:
    """What the existing rules answer, with no model involved at all.

    Read out of the compiler and the vocabulary, not invented: `_floor_candidates`
    falls through to `_wall_aligned_candidates` for every floor piece, so the
    rules always say "against a wall" and always turn it into the room;
    `_pick_support` ranks hosts by `SUPPORT_PREFERENCE`.
    """
    if chain == "against":
        return {"wall": True, "adjacent_object": None, "target": "wall"}
    if chain == "faces":
        return {"orientation_visible": True, "faces_object": False, "target": None}
    hosts = support_candidates(room, source)
    return {"supported": bool(hosts), "target": hosts[0]["id"] if hosts else None}


# ── model calls ─────────────────────────────────────────────────────────

def crop_path(room_key: str, obj: dict, image: Path) -> Path:
    from PIL import Image

    CROP_DIR.mkdir(parents=True, exist_ok=True)
    out = CROP_DIR / f"{room_key}__{obj['id'].replace('.', '_')}.png"
    if out.is_file():
        return out
    with Image.open(image) as im:
        im = im.convert("RGB")
        x1, y1, x2, y2 = obj["bbox"]
        pad_x, pad_y = int((x2 - x1) * 0.05) + 2, int((y2 - y1) * 0.05) + 2
        piece = im.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                         min(im.width, x2 + pad_x), min(im.height, y2 + pad_y)))
        if min(piece.size) < 224:
            scale = 224 / max(1, min(piece.size))
            piece = piece.resize((max(1, int(piece.width * scale)),
                                  max(1, int(piece.height * scale))), Image.LANCZOS)
        piece.save(out)
    return out


def _images(provider, mode: str, room: dict, obj: dict, image: Path) -> list[str]:
    px = provider._settings.ollama_scene_image_max_px
    if mode == "full":
        return [provider._encode(image, px)]
    return [provider._encode(crop_path(room["room_key"], obj, image), px),
            provider._encode(image, px)]


def ask_binary(provider, qkey: str, variant: str, room: dict, obj: dict,
               image: Path) -> dict:
    relation = STAGE_TRUTH[qkey][0]
    prompt = PROMPTS[qkey][variant](room, obj)
    images = _images(provider, MODE[relation], room, obj, image)
    row = {"stage": qkey, "prompt_variant": variant, "room": room["room_key"],
           "source": obj["id"], "kind": "binary"}
    started = time.perf_counter()
    try:
        payload, status = provider._generate_traced(
            prompt, BINARY_SCHEMA, f"binary:{qkey}", images=images, array_key=None)
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        answer = (payload or {}).get("answer")
        row["answer"] = answer if isinstance(answer, bool) else None
        row["status"] = status.value
    except OllamaError as exc:
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["answer"] = None
        row["status"] = getattr(exc, "code", "MODEL_FAILURE")
        row["error"] = str(exc)[:160]
    return row


def ask_target(provider, relation: str, room: dict, obj: dict,
               candidates: list[dict], image: Path) -> dict:
    ids = [c["id"] for c in candidates]
    if MODE[relation] == "full":
        lines = [f"You are looking at a photograph of a "
                 f"{room['room_type'].replace('_', ' ')}."]
    else:
        lines = ["The FIRST image is a close-up of one object. The SECOND is the "
                 f"whole {room['room_type'].replace('_', ' ')} it was cut from."]
    lines += ["", f"The piece in question is: {_piece(obj)}.", "",
              TARGET_QUESTION[relation], ""]
    for cand in candidates:
        lines.append(f"  {cand['id']} - {cand['desc']} "
                     f"(a {cand['type'].replace('_', ' ')})")
    lines += ["", 'Answer with JSON: {"target_id": "<one id from the list>"}']

    schema = {"type": "object",
              "properties": {"target_id": {"type": "string", "enum": ids}},
              "required": ["target_id"]}
    images = _images(provider, MODE[relation], room, obj, image)
    row = {"stage": f"target:{relation}", "prompt_variant": "-",
           "room": room["room_key"], "source": obj["id"], "kind": "target",
           "candidates": len(ids)}
    started = time.perf_counter()
    try:
        payload, status = provider._generate_traced(
            "\n".join(lines), schema, f"target:{relation}", images=images,
            array_key=None)
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["answer"] = (payload or {}).get("target_id") or None
        row["status"] = status.value
    except OllamaError as exc:
        row["elapsed_s"] = round(time.perf_counter() - started, 2)
        row["answer"] = None
        row["status"] = getattr(exc, "code", "MODEL_FAILURE")
        row["error"] = str(exc)[:160]
    return row


# ── running one chain ───────────────────────────────────────────────────

def run_chain(provider, room: dict, truth: dict, frozen: dict, image: Path,
              by_id: dict) -> dict:
    chain = truth["chain"]
    source = by_id[truth["source"]]
    out = {"room": room["room_key"], "source": truth["source"], "chain": chain,
           "verdict": truth["verdict"], "queries": [], "steps": {}}
    gate_a, gate_b = GATES[chain]

    row = ask_binary(provider, gate_a, frozen[gate_a], room, source, image)
    out["queries"].append(row)
    out["steps"][gate_a] = row["answer"]
    a = row["answer"]

    # Step B. For `against` the second gate only runs when the wall gate said NO;
    # for the other two it only runs when the first gate said YES. That asymmetry
    # is the chain's shape, not a special case: "not against a wall" opens the
    # object question, while "no visible front" closes it.
    ask_second = (a is False) if chain == "against" else (a is True)
    b = None
    if gate_b and ask_second:
        row = ask_binary(provider, gate_b, frozen[gate_b], room, source, image)
        out["queries"].append(row)
        out["steps"][gate_b] = row["answer"]
        b = row["answer"]

    # Step C: only now, and only among objects.
    reach_target = (a is True) if chain == "supported_by" else (b is True)
    out["target"] = None
    if reach_target:
        candidates = CANDIDATES[chain](room, source)
        out["candidate_count"] = len(candidates)
        if candidates:
            row = ask_target(provider, chain, room, source, candidates, image)
            out["queries"].append(row)
            out["target"] = row["answer"]
            out["truth_in_candidates"] = (
                truth["target"] in {c["id"] for c in candidates}
                if truth.get("target") else None)
    out["elapsed_s"] = round(sum(q["elapsed_s"] for q in out["queries"]), 2)
    return out


def grade(out: dict, truth: dict, room: dict, by_id: dict) -> dict:
    chain = truth["chain"]
    steps = out["steps"]
    det = deterministic(chain, by_id[truth["source"]], room)
    gate_a, gate_b = GATES[chain]
    truth_a = truth[STAGE_TRUTH[gate_a][1]]
    truth_b = truth[STAGE_TRUTH[gate_b][1]] if gate_b else None

    out["truth_steps"] = {gate_a: truth_a}
    if gate_b:
        out["truth_steps"][gate_b] = truth_b
    out["truth_target"] = truth.get("target")
    out["deterministic"] = det

    lenient = {truth.get("target")} | set(truth.get("also_acceptable") or [])
    out["target_correct"] = bool(out["target"]) and out["target"] in lenient

    # End to end: every step the chain actually needed, right.
    if truth["verdict"] != "TRUE":
        out["end_to_end"] = None
    elif chain == "against":
        if truth_a is True:
            out["end_to_end"] = steps.get("wall") is True
        elif truth_b is False:
            out["end_to_end"] = (steps.get("wall") is False
                                 and steps.get("adjacent") is False)
        else:
            out["end_to_end"] = (steps.get("wall") is False
                                 and steps.get("adjacent") is True
                                 and out["target_correct"])
    elif chain == "faces":
        if truth_a is False:
            out["end_to_end"] = steps.get("orientation") is False
        elif truth_b is False:
            out["end_to_end"] = (steps.get("orientation") is True
                                 and steps.get("faces_object") is False)
        else:
            out["end_to_end"] = (steps.get("orientation") is True
                                 and steps.get("faces_object") is True
                                 and out["target_correct"])
    else:
        if truth_a is False:
            out["end_to_end"] = steps.get("supported") is False
        else:
            out["end_to_end"] = steps.get("supported") is True and out["target_correct"]

    # Deterministic end-to-end on the same chain, for the §15 table.
    if truth["verdict"] != "TRUE":
        out["deterministic_correct"] = None
    elif chain == "against":
        out["deterministic_correct"] = truth_a is True
    elif chain == "faces":
        out["deterministic_correct"] = (truth_a is True and truth_b is False)
    else:
        out["deterministic_correct"] = (
            det["supported"] == truth_a
            and (truth_a is False or det["target"] in lenient))

    # Hallucination taxonomy (§12).
    out["halluc"] = []
    if chain == "against" and truth_a is False and steps.get("wall") is True:
        out["halluc"].append("A")                      # claims a wall that is not there
    if chain == "against" and truth_b is False and steps.get("adjacent") is True:
        out["halluc"].append("B")
    if chain == "faces" and truth_b is False and steps.get("faces_object") is True:
        out["halluc"].append("B")
    if chain == "supported_by" and truth_a is False and steps.get("supported") is True:
        out["halluc"].append("D")                      # invents physical support
    if out["target"] and not out["target_correct"] and truth.get("target"):
        out["halluc"].append("C")                      # right to ask, wrong pick
    return out


# ── metrics ─────────────────────────────────────────────────────────────

def confusion(pairs) -> dict:
    """pairs of (truth: bool, answer: bool|None). YES is the positive class;
    NO precision/recall are reported too, because declining is the capability
    under test."""
    tp = sum(1 for t, a in pairs if t is True and a is True)
    tn = sum(1 for t, a in pairs if t is False and a is False)
    fp = sum(1 for t, a in pairs if t is False and a is True)
    fn = sum(1 for t, a in pairs if t is True and a is False)
    unanswered = sum(1 for _t, a in pairs if a is None)
    n = tp + tn + fp + fn

    def ratio(num, den):
        return None if not den else round(100.0 * num / den, 1)

    prec, rec = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = None
    if prec is not None and rec is not None and (prec + rec):
        f1 = round(2 * prec * rec / (prec + rec), 1)
    return {"n": n, "yes_truth": tp + fn, "no_truth": tn + fp,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn, "unanswered": unanswered,
            "accuracy": ratio(tp + tn, n),
            "yes_precision": prec, "yes_recall": rec, "f1": f1,
            "no_precision": ratio(tn, tn + fn), "no_recall": ratio(tn, tn + fp)}


def _stats(values) -> dict:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "worst": 0.0}
    ordered = sorted(values)
    return {"mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2),
            "worst": round(max(values), 2)}


def pilot(provider, chains, per_question: int) -> dict:
    """Prompt A vs prompt B on a small, deliberately NO-heavy sample.

    NO cases go in first. A pilot drawn at random would be almost all YES - the
    dataset is - and would pick whichever wording says yes more, which is exactly
    the bias Phase 1c died of.
    """
    results = {}
    for qkey, (relation, field) in STAGE_TRUTH.items():
        pool = [(room, t, by_id) for room, t, by_id in chains
                if t["chain"] == relation and t.get(field) is not None
                and t["verdict"] == "TRUE"]
        pool.sort(key=lambda x: x[1][field] is True)       # False first
        sample = pool[:per_question]
        if not sample:
            continue
        scores = {}
        for variant in ("A", "B"):
            pairs = []
            for room, t, by_id in sample:
                row = ask_binary(provider, qkey, variant, room,
                                 by_id[t["source"]], ROOT / room["image"])
                pairs.append((t[field], row["answer"]))
            scores[variant] = confusion(pairs)
        # Pick on accuracy, break ties on NO-recall: a wording that scores the
        # same while actually saying no is the one worth freezing.
        best = max(("A", "B"), key=lambda v: (scores[v]["accuracy"] or 0,
                                              scores[v]["no_recall"] or 0))
        results[qkey] = {"sample": len(sample),
                         "no_cases": sum(1 for _r, t, _b in sample if t[field] is False),
                         "A": scores["A"], "B": scores["B"], "chosen": best}
        print(f"  pilot {qkey:13} A acc={scores['A']['accuracy']}% "
              f"no_rec={scores['A']['no_recall']}%  |  B acc={scores['B']['accuracy']}% "
              f"no_rec={scores['B']['no_recall']}%  -> {best}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument("--pilot-size", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provider = OllamaProvider()

    chains = []
    for room in fixture["rooms"]:
        by_id = {o["id"]: o for o in room["objects"]}
        for truth in room.get("binary_relations", []):
            chains.append((room, truth, by_id))
    scoreable = [c for c in chains if c[1]["verdict"] == "TRUE"]

    print(f"model: {provider.label}   rooms: {len(fixture['rooms'])}   "
          f"chains: {len(chains)} ({len(scoreable)} scoreable)\n", flush=True)

    print("-- prompt pilot (A vs B, frozen after) " + "-" * 25, flush=True)
    pilot_result = pilot(provider, chains, args.pilot_size)
    frozen = {q: r["chosen"] for q, r in pilot_result.items()}
    print(f"\n  frozen prompts: {frozen}\n", flush=True)
    if args.pilot_only:
        return 0

    print("-- full benchmark " + "-" * 45, flush=True)
    todo = scoreable[:args.limit] if args.limit else scoreable
    results = []
    for room, truth, by_id in todo:
        out = run_chain(provider, room, truth, frozen, ROOT / room["image"], by_id)
        grade(out, truth, room, by_id)
        mark = "ok " if out["end_to_end"] else "  x"
        print(f"  {mark} {out['chain']:13} {out['source']:34} "
              f"got={out['steps']}/{out['target']} "
              f"want={out['truth_steps']}/{out['truth_target']} "
              f"{out['elapsed_s']}s", flush=True)
        results.append(out)

    # ── aggregate ───────────────────────────────────────────────────────
    stages = {}
    for qkey, (relation, field) in STAGE_TRUTH.items():
        pairs = []
        for out, (_room, truth, _b) in zip(results, todo):
            if truth["chain"] != relation or truth.get(field) is None:
                continue
            if qkey not in out["steps"]:
                continue                       # the chain never reached this gate
            pairs.append((truth[field], out["steps"][qkey]))
        if pairs:
            stages[qkey] = confusion(pairs)

    graded = [o for o in results if o["end_to_end"] is not None]
    by_chain = {}
    for chain in ("against", "faces", "supported_by"):
        subset = [o for o in graded if o["chain"] == chain]
        if not subset:
            continue
        reached = [o for o in subset if o["target"] is not None]
        by_chain[chain] = {
            "chains": len(subset),
            "end_to_end_pct": round(100.0 * sum(bool(o["end_to_end"]) for o in subset)
                                    / len(subset), 1),
            "deterministic_pct": round(100.0 * sum(bool(o["deterministic_correct"])
                                                   for o in subset) / len(subset), 1),
            "target_asked": len(reached),
            "target_correct": sum(o["target_correct"] for o in reached),
            "target_accuracy_pct": (round(100.0 * sum(o["target_correct"] for o in reached)
                                          / len(reached), 1) if reached else None),
            "ai_better": sum(1 for o in subset
                             if o["end_to_end"] and not o["deterministic_correct"]),
            "ai_worse": sum(1 for o in subset
                            if not o["end_to_end"] and o["deterministic_correct"]),
            "latency": _stats([o["elapsed_s"] for o in subset]),
        }

    halluc = {t: sum(1 for o in graded if t in o["halluc"]) for t in ("A", "B", "C", "D")}
    every_query = [q for o in results for q in o["queries"]]
    binary_q = [q for q in every_query if q["kind"] == "binary"]
    target_q = [q for q in every_query if q["kind"] == "target"]
    rooms_seen = len({o["room"] for o in results}) or 1

    def budget(keep) -> dict:
        subset = [o for o in graded if keep(o)]
        queries = sum(len(o["queries"]) for o in subset)
        return {"chains": len(subset), "queries": queries,
                "queries_per_room": round(queries / rooms_seen, 1),
                "end_to_end_pct": (round(100.0 * sum(bool(o["end_to_end"]) for o in subset)
                                         / len(subset), 1) if subset else None),
                "ai_better": sum(1 for o in subset
                                 if o["end_to_end"] and not o["deterministic_correct"]),
                "seconds_per_room": round(sum(o["elapsed_s"] for o in subset)
                                          / rooms_seen, 1)}

    budgets = {
        "A_all_eligible": budget(lambda o: True),
        "B_major_anchors": budget(
            lambda o: o["source"].split(".")[1] in BUDGET_B_TYPES
            or o["chain"] == "supported_by"),
        "C_uncertain_oracle": budget(lambda o: not o["deterministic_correct"]),
    }

    dropped = [o["source"] for o in results if o.get("truth_in_candidates") is False]

    report = {
        "model": provider.label,
        "prompt_pilot": pilot_result,
        "frozen_prompts": frozen,
        "dataset": {
            "rooms": len(fixture["rooms"]),
            "binary_chains": len(chains),
            "scoreable": len(scoreable),
            "unknown": len(chains) - len(scoreable),
            "negative_controls": sum(
                1 for _r, t, _b in scoreable
                if t.get("wall") is False or t.get("orientation_visible") is False
                or t.get("faces_object") is False or t.get("supported") is False),
            "phase1c_relations_carried_unchanged": sum(len(r["relations"])
                                                       for r in fixture["rooms"]),
        },
        "stages": stages,
        "by_chain": by_chain,
        "hallucination": halluc,
        "latency": {"binary": _stats([q["elapsed_s"] for q in binary_q]),
                    "target": _stats([q["elapsed_s"] for q in target_q]),
                    "queries": len(every_query),
                    "queries_per_room": round(len(every_query) / rooms_seen, 1),
                    "seconds_per_room": round(sum(o["elapsed_s"] for o in results)
                                              / rooms_seen, 1),
                    "worst_room_s": round(max(
                        sum(o["elapsed_s"] for o in results if o["room"] == r)
                        for r in {o["room"] for o in results}), 1)},
        "reliability": {
            "queries": len(every_query),
            "valid_json": sum(1 for q in every_query if q["answer"] is not None),
            "valid_json_pct": round(100.0 * sum(1 for q in every_query
                                                if q["answer"] is not None)
                                    / max(1, len(every_query)), 1),
            "status": {s: sum(1 for q in every_query if q["status"] == s)
                       for s in {q["status"] for q in every_query}},
        },
        "budgets": budgets,
        "candidate_filter_dropped_truth": dropped,
        "chains": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "phase_1d_raw.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    for qkey, c in stages.items():
        print(f"  {qkey:13} acc {c['accuracy']}%  (yes {c['yes_truth']} / no "
              f"{c['no_truth']})  NO-recall {c['no_recall']}%  F1 {c['f1']}")
    print()
    for chain, c in by_chain.items():
        print(f"  {chain:13} end-to-end {c['end_to_end_pct']}%  vs deterministic "
              f"{c['deterministic_pct']}%  (AI better {c['ai_better']}, worse "
              f"{c['ai_worse']})")
    print(f"\n  hallucination {halluc}")
    print(f"  json {report['reliability']['valid_json_pct']}%  "
          f"queries/room {report['latency']['queries_per_room']}  "
          f"s/room {report['latency']['seconds_per_room']}  "
          f"worst room {report['latency']['worst_room_s']}s")
    if dropped:
        print(f"  WARNING candidate filter dropped the true target for: {dropped}")
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 0d gate: can either model's boxes be trusted for scene geometry?

    python research/phase0d_geometry.py

Writes docs/benchmarks/phase_0d_geometry_report.md and phase_0d_raw.json.
Changes no production behaviour and no project data.

Four questions, measured separately:
  1. are Qwen's boxes VALID (in range, right way round, non-zero)?
  2. are the valid ones ACCURATE (IoU against hand-placed ground truth)?
  3. are Grounding DINO's boxes better?
  4. can either safely contribute geometry?

Nothing here clamps. Phase 0c saw Qwen emit 1148 on a 0-1000 scale; silently
folding that to 1000 would report a valid box where the model produced a wrong
one. Raw validity and "would clamping have rescued it" are counted apart.
"""
from __future__ import annotations

import base64
import io
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence import vocab                                     # noqa: E402
from app.intelligence.ollama_provider import OllamaProvider            # noqa: E402
from app.intelligence.prompts import SCENE_READING_SCHEMA, scene_reading_prompt  # noqa: E402
from app.intelligence.schema import StyleSpec                          # noqa: E402
from app.vision.benchmark_detector import (                            # noqa: E402
    ARCHITECTURAL_LABELS, RESIDENTIAL_LABELS, describe, detect_objects, unload)

FIXTURE = ROOT / "tests" / "fixtures" / "geometry_benchmark.json"
OUT_DIR = ROOT.parent / "docs" / "benchmarks"
EXCLUDED = set(ARCHITECTURAL_LABELS)
BOX_THRESHOLD, TEXT_THRESHOLD = 0.30, 0.25
RESOLUTIONS = (512, 768, 1024)
DEFAULT_PX = 768

_CAMERA_WORDS = ("left", "right", "front", "back", "rear", "behind", "up", "down",
                 "north", "south", "east", "west", "forward", "upward", "downward")
_RESOLVABLE_WORDS = ("window", "glazing", "french door", "corner", "centre", "center",
                     "middle", "room", "inward", "inside", "free-standing", "freestanding")


class _Room:
    def __init__(self, room_type: str):
        self.room_id = self.name = room_type
        self.type = room_type
        self.width_m, self.length_m = 5.0, 4.0


# ── box plumbing (benchmark-only; production schema untouched) ───────────

def _to_pixels(raw, w: int, h: int):
    """Model box -> pixel [x1,y1,x2,y2] WITHOUT repairing anything.

    Mirrors `_bbox`'s convention sniff (max > 1.5 means 0-1000) so the
    benchmark judges the same numbers production would, then stops - no
    clamping, no sorting, no rejection.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if any(v != v or v in (float("inf"), float("-inf")) for v in vals):
        return None
    if max(vals) > 1.5:                      # 0-1000 convention
        vals = [v / 1000.0 for v in vals]
    return [vals[0] * w, vals[1] * h, vals[2] * w, vals[3] * h]


def classify(raw, w: int, h: int) -> str:
    """VALID / OUT_OF_RANGE / INVERTED / ZERO_AREA / MISSING / MALFORMED."""
    if raw is None:
        return "MISSING"
    box = _to_pixels(raw, w, h)
    if box is None:
        return "MALFORMED"
    x1, y1, x2, y2 = box
    # Order matters: a box can be both out of range and inverted. Range is
    # reported first because that is the failure Phase 0c actually saw.
    if min(box) < -0.01 * max(w, h) or x2 > w * 1.01 or y2 > h * 1.01:
        return "OUT_OF_RANGE"
    if x2 <= x1 or y2 <= y1:
        return "INVERTED"
    if (x2 - x1) * (y2 - y1) <= 0:
        return "ZERO_AREA"
    return "VALID"


def repairable(raw, w: int, h: int) -> bool:
    """Would clamping into frame have produced a usable box? Measured, never applied."""
    box = _to_pixels(raw, w, h)
    if box is None:
        return False
    x1, y1, x2, y2 = box
    x1, x2 = max(0.0, min(x1, w)), max(0.0, min(x2, w))
    y1, y2 = max(0.0, min(y1, h)), max(0.0, min(y2, h))
    return (x2 - x1) > 1 and (y2 - y1) > 1


def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def norm_label(name: str) -> str:
    raw = str(name or "").strip().lower()
    if not raw or raw in EXCLUDED:
        return ""
    sem = raw.replace(" ", "_")
    if sem not in vocab.ALL_SEMANTIC_TYPES:
        sem = vocab.canonical_type(raw)
    return "" if sem in ("other", "") or sem in EXCLUDED else sem


def match(preds: list[dict], truths: list[dict]) -> list[float]:
    """Greedy max-IoU matching, same canonical type only, one prediction per truth.

    Three identical bar stools must not all match the same ground-truth stool,
    and a sofa must never be scored against a coffee table.
    """
    pairs = []
    for pi, p in enumerate(preds):
        for ti, t in enumerate(truths):
            if p["label"] == t["label"]:
                pairs.append((iou(p["bbox"], t["bbox"]), pi, ti))
    pairs.sort(key=lambda x: -x[0])
    used_p, used_t, scores = set(), set(), []
    for score, pi, ti in pairs:
        if pi in used_p or ti in used_t:
            continue
        used_p.add(pi)
        used_t.add(ti)
        scores.append(score)
    # Returned SEPARATELY, never pre-mixed. Padding misses with 0.0 before
    # averaging is how a DETECTION failure gets reported as bad GEOMETRY, and
    # the two lead to opposite architectures: a model with tight boxes and poor
    # recall wants a different fix from one that finds everything and boxes it
    # loosely. The caller decides which question it is asking.
    return {"matched": scores,
            "missed_truths": len(truths) - len(used_t),
            "unmatched_preds": len(preds) - len(used_p),
            "truths": len(truths), "preds": len(preds)}


def both_views(m: dict) -> dict:
    """The three metrics kept apart.

      detection  - did it find the object at all (recall over ground truth)
      geometry   - of the ones it DID find, how good is the box (matched only)
      combined   - geometry with misses scored 0, i.e. detection x geometry
    """
    found = len(m["matched"])
    return {
        "detection": {"found": found, "truths": m["truths"],
                      "recall": round(found / m["truths"], 3) if m["truths"] else 0.0,
                      "unmatched_preds": m["unmatched_preds"]},
        "geometry": iou_stats(m["matched"]),
        "combined": iou_stats(m["matched"] + [0.0] * m["missed_truths"]),
    }


def iou_stats(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0,
                "at25": 0, "at50": 0, "at75": 0}
    return {"n": len(scores),
            "mean": round(statistics.mean(scores), 3),
            "median": round(statistics.median(scores), 3),
            "min": round(min(scores), 3), "max": round(max(scores), 3),
            "at25": sum(1 for s in scores if s >= 0.25),
            "at50": sum(1 for s in scores if s >= 0.50),
            "at75": sum(1 for s in scores if s >= 0.75)}


def classify_relation(value: str, room_labels: set[str]) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "EMPTY"
    if any(w in v for w in _RESOLVABLE_WORDS):
        return "RESOLVABLE"
    for label in room_labels:
        if label and label.replace("_", " ") in v:
            return "RESOLVABLE"
    if any(w in v for w in _CAMERA_WORDS):
        return "CAMERA_RELATIVE"
    return "UNKNOWN"


# ── prompt variants (benchmark-only; production prompt untouched) ────────

PROMPT_B_RULE = (
    "\nRELATIONSHIP RULE\n"
    "`against` and `faces` must each be one of: the name of another piece in "
    "this room, a window, a door, the room perimeter, the middle of the room, "
    'or the empty string "". Never a direction.\n')

PROMPT_C_RULE = (
    "\nRELATIONSHIP EXAMPLES\n"
    'BAD  against: "left wall"      GOOD against: "the window"\n'
    'BAD  against: "back wall"      GOOD against: "the television"\n'
    'BAD  faces:   "front"          GOOD faces:   "the sofa"\n'
    'BAD  faces:   "up"             GOOD faces:   "into the room"\n'
    'When unsure, answer "" rather than a direction.\n')

PROMPTS = {"A": "", "B": PROMPT_B_RULE, "C": PROMPT_C_RULE}


def read_once(provider, image: Path, room, max_px: int, extra: str):
    """One Qwen read. Returns (raw, seconds, response bytes, error)."""
    from PIL import Image

    with Image.open(image) as im:
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode()

    prompt = scene_reading_prompt(room, StyleSpec(name="B", tags=["modern"]), "residential") + extra
    started = time.perf_counter()
    try:
        raw = provider._generate(prompt, SCENE_READING_SCHEMA, "phase0d", images=[encoded])
    except Exception as exc:                                       # noqa: BLE001
        return {}, round(time.perf_counter() - started, 2), 0, f"{type(exc).__name__}: {exc}"
    elapsed = round(time.perf_counter() - started, 2)
    return raw, elapsed, len(json.dumps(raw).encode()), ""


def _truths(entry: dict) -> list[dict]:
    out = [{"label": norm_label(o["label"]), "bbox": [float(v) for v in o["bbox"]]}
           for o in entry["objects"]]
    return [t for t in out if t["label"]]


def score_reading(raw: dict, entry: dict, w: int, h: int) -> dict:
    """Validity + IoU + relationship quality for one Qwen answer."""
    elements = raw.get("elements") or []
    truths = _truths(entry)
    room_labels = {t["label"] for t in truths}

    counts = {k: 0 for k in ("VALID", "OUT_OF_RANGE", "INVERTED", "ZERO_AREA",
                             "MISSING", "MALFORMED")}
    repair = 0
    preds = []
    rel = {f: {k: 0 for k in ("RESOLVABLE", "CAMERA_RELATIVE", "EMPTY", "UNKNOWN")}
           for f in ("against", "faces")}

    for el in elements:
        verdict = classify(el.get("bbox"), w, h)
        counts[verdict] += 1
        if verdict != "VALID" and repairable(el.get("bbox"), w, h):
            repair += 1
        label = norm_label(el.get("semantic_type") or el.get("name") or "")
        if verdict == "VALID" and label:
            preds.append({"label": label, "bbox": _to_pixels(el["bbox"], w, h)})
        for field in ("against", "faces"):
            rel[field][classify_relation(el.get(field, ""), room_labels)] += 1

    m = match(preds, truths)
    return {"validity": counts, "repairable": repair, "elements": len(elements),
            "scores": m["matched"], "missed_truths": m["missed_truths"],
            **both_views(m), "relationships": rel}


def run_dino(entry: dict, path: Path) -> dict:
    labels = [lab for lab in RESIDENTIAL_LABELS if lab.lower() not in EXCLUDED]
    det = detect_objects(path, labels, box_threshold=BOX_THRESHOLD,
                         text_threshold=TEXT_THRESHOLD)
    preds = []
    for o in det["objects"]:
        label = norm_label(o["label"])
        if not label:
            continue
        b = o["bbox"]
        preds.append({"label": label,
                      "bbox": [b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]],
                      "confidence": o["confidence"]})
    m = match(preds, _truths(entry))
    return {"scores": m["matched"], "missed_truths": m["missed_truths"],
            **both_views(m), "boxes": len(det["objects"]),
            "elapsed_s": det["elapsed_s"], "peak_vram_mb": det["peak_vram_mb"],
            "mean_confidence": round(statistics.mean(
                [p["confidence"] for p in preds]), 3) if preds else 0.0}


def pool(rows: list[dict]) -> dict:
    """Aggregate rows by POOLING raw scores, not by averaging per-image means.

    A bathroom with 2 objects must not weigh the same as a living room with 11.
    """
    scores = [x for r in rows for x in r["scores"]]
    missed = sum(r["missed_truths"] for r in rows)
    truths = sum(r["detection"]["truths"] for r in rows)
    return {"detection": {"found": len(scores), "truths": truths,
                          "recall": round(len(scores) / truths, 3) if truths else 0.0,
                          "unmatched_preds": sum(r["detection"]["unmatched_preds"] for r in rows)},
            "geometry": iou_stats(scores),
            "combined": iou_stats(scores + [0.0] * missed)}


def _merge(dicts: list[dict]) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    images = fixture["images"]
    w, h = fixture["image_size"]
    env = describe()
    provider = OllamaProvider()
    print(f"{env}\nimages: {len(images)}  objects: "
          f"{sum(len(e['objects']) for e in images)}\n", flush=True)

    raw_out: dict = {"environment": env, "image_size": [w, h],
                     "box_threshold": BOX_THRESHOLD, "resolutions": {},
                     "prompts": {}, "per_image": [], "dino": {}, "errors": []}

    # ── Grounding DINO, once per image (deterministic) ───────────────────
    dino_rows = []
    for entry in images:
        path = ROOT / entry["image"]
        d = run_dino(entry, path)
        dino_rows.append({"image": entry["image"], **d})
        print(f"  DINO  {entry['room_type']:16} geom={d['geometry']['mean']:.3f} "
              f"found={d['detection']['found']}/{d['detection']['truths']} {d['elapsed_s']}s", flush=True)
    unload()
    raw_out["dino"] = {"per_image": dino_rows, **pool(dino_rows),
                       "peak_vram_mb": max(r["peak_vram_mb"] for r in dino_rows),
                       "avg_s": round(statistics.mean([r["elapsed_s"] for r in dino_rows]), 2)}

    # ── Qwen: resolution sweep on prompt A ───────────────────────────────
    for px in RESOLUTIONS:
        rows = []
        for entry in images:
            path = ROOT / entry["image"]
            raw, secs, nbytes, err = read_once(provider, path, _Room(entry["room_type"]), px, "")
            if err:
                raw_out["errors"].append(f"{px}px {entry['room_type']}: {err}")
            s = score_reading(raw, entry, w, h)
            rows.append({"image": entry["image"], "room_type": entry["room_type"],
                         "elapsed_s": secs, "bytes": nbytes, **s})
            print(f"  qwen{px:5} {entry['room_type']:16} el={s['elements']:2} "
                  f"valid={s['validity']['VALID']:2} oor={s['validity']['OUT_OF_RANGE']:2} "
                  f"geom={s['geometry']['mean']:.3f} "
                  f"found={s['detection']['found']}/{s['detection']['truths']} {secs}s", flush=True)
        raw_out["resolutions"][str(px)] = {
            "per_image": rows,
            "validity": _merge([r["validity"] for r in rows]),
            "repairable": sum(r["repairable"] for r in rows),
            "elements": sum(r["elements"] for r in rows),
            **pool(rows),
            "avg_s": round(statistics.mean([r["elapsed_s"] for r in rows]), 2),
            "avg_bytes": int(statistics.mean([r["bytes"] for r in rows])),
            "relationships": {f: _merge([r["relationships"][f] for r in rows])
                              for f in ("against", "faces")},
        }
        if px == DEFAULT_PX:
            raw_out["per_image"] = rows

    # ── Qwen: prompt sweep at the default resolution ─────────────────────
    for name, extra in PROMPTS.items():
        if name == "A":
            raw_out["prompts"]["A"] = raw_out["resolutions"][str(DEFAULT_PX)]
            continue
        rows = []
        for entry in images:
            path = ROOT / entry["image"]
            raw, secs, nbytes, err = read_once(
                provider, path, _Room(entry["room_type"]), DEFAULT_PX, extra)
            if err:
                raw_out["errors"].append(f"prompt {name} {entry['room_type']}: {err}")
            s = score_reading(raw, entry, w, h)
            rows.append({"image": entry["image"], "elapsed_s": secs, "bytes": nbytes, **s})
            print(f"  prompt{name} {entry['room_type']:16} el={s['elements']:2} "
                  f"valid={s['validity']['VALID']:2} geom={s['geometry']['mean']:.3f}", flush=True)
        raw_out["prompts"][name] = {
            "per_image": rows,
            "validity": _merge([r["validity"] for r in rows]),
            "repairable": sum(r["repairable"] for r in rows),
            "elements": sum(r["elements"] for r in rows),
            **pool(rows),
            "avg_s": round(statistics.mean([r["elapsed_s"] for r in rows]), 2),
            "avg_bytes": int(statistics.mean([r["bytes"] for r in rows])),
            "relationships": {f: _merge([r["relationships"][f] for r in rows])
                              for f in ("against", "faces")},
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "phase_0d_raw.json").write_text(json.dumps(raw_out, indent=2), encoding="utf-8")
    _report(raw_out, images)
    print(f"\nwrote {OUT_DIR / 'phase_0d_geometry_report.md'}")
    return 0


def _report(d: dict, images: list[dict]) -> None:
    L, add = [], None
    L = []
    add = L.append
    env = d["environment"]
    default = d["resolutions"][str(DEFAULT_PX)]
    dino = d["dino"]

    add("# Phase 0d - box geometry and local scene reading quality\n")
    add("Can either model's bounding boxes be trusted to contribute scene")
    add("geometry? Measurement only: no production behaviour was changed, and")
    add("nothing here clamps or repairs a box.\n")

    add("## 1. Environment\n")
    add(f"- GPU: {env.get('gpu')}, {env.get('vram_gb')} GB, CUDA {env.get('cuda')}")
    add(f"- torch {env.get('torch')}")
    add("- reader: ollama qwen2.5vl:3b, batch 1")
    add(f"- detector: `{env.get('model')}`, box {BOX_THRESHOLD} / text {TEXT_THRESHOLD}")
    add(f"- image resolutions tested: {', '.join(str(r) for r in RESOLUTIONS)} px\n")

    add("## 2. Dataset\n")
    add(f"- {len(images)} real renders at {d['image_size'][0]}x{d['image_size'][1]}, "
        f"{sum(len(e['objects']) for e in images)} hand-placed boxes")
    add("- rooms: " + ", ".join(sorted({e["room_type"] for e in images})))
    add("- ground truth: `tests/fixtures/geometry_benchmark.json`, placed by eye\n")
    add("**Limitations.** Boxes were placed by eye with no labelling tool, so each")
    add("edge carries perhaps 5% error; a 0.02 difference in mean IoU is noise. All")
    add("five renders are residential. Ground truth contains repeated types (three")
    add("bar stools, two sofas, two tv_units) specifically to exercise matching.\n")
    if d["errors"]:
        add("**Errors during the run:**\n")
        for e in d["errors"][:10]:
            add(f"- {e}")
        add("")

    add("## 3. Box validity (Qwen, 768 px, production prompt)\n")
    v = default["validity"]
    total = sum(v.values())
    add("| Total | Valid | Out of range | Inverted | Zero area | Malformed | Missing |")
    add("|---|---|---|---|---|---|---|")
    add(f"| {total} | {v['VALID']} | {v['OUT_OF_RANGE']} | {v['INVERTED']} | "
        f"{v['ZERO_AREA']} | {v['MALFORMED']} | {v['MISSING']} |")
    pct = (100.0 * v["VALID"] / total) if total else 0.0
    add(f"\n**{pct:.0f}% of boxes are valid as produced.** "
        f"{default['repairable']} of the {total - v['VALID']} invalid ones would become "
        "usable if clamped into frame - measured, not applied.\n")

    add("## 4. Three metrics, kept apart")
    add("")
    add("A detection failure and a bad box are different defects with opposite")
    add("fixes, so they are never averaged together here.")
    add("")
    add("**4a. Semantic detection** - did it find the object at all?")
    add("")
    add("| System | Ground-truth objects | Matched | Recall | Unmatched predictions |")
    add("|---|---|---|---|---|")
    for name, blk in (("Qwen 768px", default), ("Grounding DINO", dino)):
        d0 = blk["detection"]
        add(f"| {name} | {d0['truths']} | {d0['found']} | {d0['recall']} | "
            f"{d0['unmatched_preds']} |")
    add("")
    add("**4b. Box geometry** - of the objects it DID find, how good is the box?")
    add("Matched pairs only; misses excluded, so this is geometry alone.")
    add("")
    add("| System | n | Mean IoU | Median | Min | Max | >=0.25 | >=0.50 | >=0.75 |")
    add("|---|---|---|---|---|---|---|---|---|")
    for name, blk in (("Qwen 768px", default), ("Grounding DINO", dino)):
        g = blk["geometry"]
        add(f"| {name} | {g['n']} | {g['mean']} | {g['median']} | {g['min']} | {g['max']} | "
            f"{g['at25']} | {g['at50']} | {g['at75']} |")
    add("")
    add("**4c. Detection x geometry** - misses scored 0. What fraction of the room")
    add("ends up correctly boxed. This matters for a pipeline consuming boxes")
    add("wholesale, and it is NOT a geometry score.")
    add("")
    add("| System | n | Mean IoU | Median | >=0.25 | >=0.50 | >=0.75 |")
    add("|---|---|---|---|---|---|---|")
    for name, blk in (("Qwen 768px", default), ("Grounding DINO", dino)):
        c = blk["combined"]
        add(f"| {name} | {c['n']} | {c['mean']} | {c['median']} | {c['at25']} | "
            f"{c['at50']} | {c['at75']} |")
    add("")
    add("Scores pooled across images, matched greedily by max IoU within the same")
    add("canonical type; one prediction per ground-truth object.")
    add("")

    add("## 5. Object identification\n")
    add("Unchanged from Phase 0b; see `phase_0b_detector_report.md`. Not re-run.\n")

    add("## 6. Relationship quality (Qwen, 768 px, production prompt)\n")
    add("| Field | Resolvable | Camera-relative | Empty | Unknown |")
    add("|---|---|---|---|---|")
    for field in ("against", "faces"):
        r = default["relationships"][field]
        add(f"| `{field}` | {r['RESOLVABLE']} | {r['CAMERA_RELATIVE']} | "
            f"{r['EMPTY']} | {r['UNKNOWN']} |")
    add("")

    add("## 7. Prompt comparison (768 px)\n")
    add("| Prompt | Elements | Valid boxes | Mean IoU | `against` resolvable | "
        "`against` camera-rel | `faces` resolvable | Time |")
    add("|---|---|---|---|---|---|---|---|")
    for name in ("A", "B", "C"):
        p = d["prompts"].get(name)
        if not p:
            continue
        ra, rf = p["relationships"]["against"], p["relationships"]["faces"]
        label = {"A": "A (production)", "B": "B (explicit rule)",
                 "C": "C (examples)"}[name]
        add(f"| {label} | {p['elements']} | {p['validity']['VALID']} | {p['iou']['mean']} | "
            f"{ra['RESOLVABLE']} | {ra['CAMERA_RELATIVE']} | {rf['RESOLVABLE']} | {p['avg_s']}s |")
    add("")

    add("## 8. Resolution comparison (production prompt)\n")
    add("| Resolution | Time | Elements | Valid boxes | Out of range | Mean IoU | Avg bytes |")
    add("|---|---|---|---|---|---|---|")
    for px in RESOLUTIONS:
        r = d["resolutions"][str(px)]
        add(f"| {px} px | {r['avg_s']}s | {r['elements']} | {r['validity']['VALID']} | "
            f"{r['validity']['OUT_OF_RANGE']} | {r['iou']['mean']} | {r['avg_bytes']} |")
    add("")

    add("## 9. Response size (truncation risk)\n")
    add("`ollama_num_predict` is 8192 tokens. Phase 0c saw `plan_objects` truncate at")
    add("~27 KB; scene reading is a smaller answer. Average response bytes per image:\n")
    for px in RESOLUTIONS:
        r = d["resolutions"][str(px)]
        per = (r["avg_bytes"] / max(1, r["elements"] / len(images))) if r["elements"] else 0
        add(f"- {px} px: {r['avg_bytes']} bytes, {r['elements']} elements total, "
            f"~{per:.0f} bytes per element")
    add("")

    add("## 10. Hardware\n")
    add(f"- Grounding DINO: {dino['avg_s']}s per image, peak {dino['peak_vram_mb']} MB VRAM")
    for px in RESOLUTIONS:
        add(f"- Qwen at {px} px: {d['resolutions'][str(px)]['avg_s']}s per image")
    add("- run sequentially, batch 1; the detector is unloaded before the reader runs\n")
    (OUT_DIR / "phase_0d_geometry_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

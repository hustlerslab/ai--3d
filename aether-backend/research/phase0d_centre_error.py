"""Phase 0d supplement: centre error, and a durable record of every box.

    python research/phase0d_centre_error.py

Writes docs/benchmarks/phase_0d_centre_error.json.

Why this is its own metric
--------------------------
IoU conflates position with size. A box centred perfectly but twice too large
scores badly, and so does a correctly-sized box shifted sideways - yet those are
different defects. For a pipeline that hands POSITION to a constraint solver and
takes SIZE from a catalogue, being in the right place is the part the solver
cannot recover on its own, so it deserves its own number.

It also fixes the omission that forced a re-run: every predicted box is written
to disk here, so a further metric can be computed from the file rather than from
another GPU pass.

Runs at the default resolution only - the resolution sweep lives in
phase0d_geometry.py and does not need repeating. Reuses that module's matching
and classification so the two reports cannot disagree about what matched what.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import phase0d_geometry as g                                          # noqa: E402
from app.intelligence.ollama_provider import OllamaProvider           # noqa: E402
from app.vision.benchmark_detector import (                           # noqa: E402
    ARCHITECTURAL_LABELS, RESIDENTIAL_LABELS, detect_objects, unload)


def centre(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def centre_error(pred, truth, diag: float) -> tuple[float, float]:
    """Pixels between the two centres, and that as a % of the image diagonal.

    The percentage is what travels between datasets: 30 px means something
    different on a 704-wide render than on a 4K one.
    """
    px, py = centre(pred)
    tx, ty = centre(truth)
    err = math.hypot(px - tx, py - ty)
    return round(err, 1), round(100.0 * err / diag, 2)


def paired(preds: list[dict], truths: list[dict]) -> list[tuple[dict, dict, float]]:
    """The same greedy max-IoU pairing phase0d_geometry uses, but returning the
    boxes themselves rather than only the scores."""
    pairs = []
    for pi, p in enumerate(preds):
        for ti, t in enumerate(truths):
            if p["label"] == t["label"]:
                pairs.append((g.iou(p["bbox"], t["bbox"]), pi, ti))
    pairs.sort(key=lambda x: -x[0])
    used_p, used_t, out = set(), set(), []
    for score, pi, ti in pairs:
        if pi in used_p or ti in used_t:
            continue
        used_p.add(pi)
        used_t.add(ti)
        out.append((preds[pi], truths[ti], score))
    return out


def qwen_preds(provider, path: Path, room, w: int, h: int) -> list[dict]:
    raw, _secs, _bytes, err = g.read_once(provider, path, room, g.DEFAULT_PX, "")
    if err:
        return []
    preds = []
    for el in (raw.get("elements") or []):
        if g.classify(el.get("bbox"), w, h) != "VALID":
            continue                       # centre error is only meaningful on a valid box
        label = g.norm_label(el.get("semantic_type") or el.get("name") or "")
        if label:
            preds.append({"label": label, "bbox": g._to_pixels(el["bbox"], w, h)})
    return preds


def dino_preds(path: Path) -> list[dict]:
    labels = [lab for lab in RESIDENTIAL_LABELS
              if lab.lower() not in set(ARCHITECTURAL_LABELS)]
    det = detect_objects(path, labels, box_threshold=g.BOX_THRESHOLD,
                         text_threshold=g.TEXT_THRESHOLD)
    preds = []
    for o in det["objects"]:
        label = g.norm_label(o["label"])
        if not label:
            continue
        b = o["bbox"]
        preds.append({"label": label,
                      "bbox": [b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]]})
    return preds


def main() -> int:
    fixture = json.loads(g.FIXTURE.read_text(encoding="utf-8"))
    w, h = fixture["image_size"]
    diag = math.hypot(w, h)
    provider = OllamaProvider()
    rows: list[dict] = []

    for entry in fixture["images"]:
        path = ROOT / entry["image"]
        truths = g._truths(entry)
        room = g._Room(entry["room_type"])
        for system, preds in (("qwen", qwen_preds(provider, path, room, w, h)),
                              ("dino", dino_preds(path))):
            for pred, truth, score in paired(preds, truths):
                err_px, err_pct = centre_error(pred["bbox"], truth["bbox"], diag)
                rows.append({
                    "image": entry["image"], "room_type": entry["room_type"],
                    "system": system, "label": pred["label"],
                    "pred": [round(v, 1) for v in pred["bbox"]],
                    "truth": [round(v, 1) for v in truth["bbox"]],
                    "iou": round(score, 3),
                    "centre_err_px": err_px, "centre_err_pct_diag": err_pct,
                })
            print(f"  {entry['room_type']:16} {system:5} matched "
                  f"{len([r for r in rows if r['image'] == entry['image'] and r['system'] == system])}",
                  flush=True)
    unload()

    totals = {}
    for system in ("qwen", "dino"):
        errs = [r["centre_err_px"] for r in rows if r["system"] == system]
        pcts = [r["centre_err_pct_diag"] for r in rows if r["system"] == system]
        totals[system] = {
            "n": len(errs),
            "mean_px": round(statistics.mean(errs), 1) if errs else 0.0,
            "median_px": round(statistics.median(errs), 1) if errs else 0.0,
            "max_px": round(max(errs), 1) if errs else 0.0,
            "mean_pct_diag": round(statistics.mean(pcts), 2) if pcts else 0.0,
            "median_pct_diag": round(statistics.median(pcts), 2) if pcts else 0.0,
            "within_5pct": sum(1 for p in pcts if p <= 5.0),
            "within_10pct": sum(1 for p in pcts if p <= 10.0),
        }

    g.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (g.OUT_DIR / "phase_0d_centre_error.json").write_text(
        json.dumps({"resolution_px": g.DEFAULT_PX, "image_size": [w, h],
                    "diagonal_px": round(diag, 1), "per_object": rows,
                    "totals": totals}, indent=2), encoding="utf-8")
    print(f"\nwrote {g.OUT_DIR / 'phase_0d_centre_error.json'}")
    for system in ("qwen", "dino"):
        t = totals[system]
        print(f"  {system:5} n={t['n']:3} mean={t['mean_px']}px "
              f"({t['mean_pct_diag']}% of diagonal)  median={t['median_px']}px  "
              f"within 5%={t['within_5pct']}  within 10%={t['within_10pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

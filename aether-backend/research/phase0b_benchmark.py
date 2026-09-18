"""Phase 0b gate: does an open-vocabulary detector identify objects better than
the scene reader does?

    python research/phase0b_benchmark.py

Writes docs/benchmarks/phase_0b_detector_report.md and phase_0b_raw.json.
Touches no production code and no project data.

Why the reader baseline is wired by hand here
---------------------------------------------
`OllamaProvider` does NOT implement `read_scene_elements`; only the Gemini
provider does. `scene_plan.py:82` discovers the method with `getattr` and, when
it is missing, returns an EMPTY SceneReading. So a local-only install reads zero
elements out of its moodboards today - there is nothing to benchmark through the
normal path.

Rather than add the method to production (Phase 0b is measurement-only, by
instruction), this script makes the same call the Gemini provider makes -
`scene_reading_prompt()`, the same schema, the same normalisation - against
qwen2.5vl through `OllamaProvider._generate`. That measures exactly what an
Ollama reader would score, changing nothing.
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

from app.intelligence import vocab                                    # noqa: E402
from app.intelligence.ollama_provider import OllamaProvider           # noqa: E402
from app.intelligence.prompts import SCENE_READING_SCHEMA, scene_reading_prompt  # noqa: E402
from app.intelligence.schema import StyleSpec                         # noqa: E402
from app.vision.benchmark_detector import (                           # noqa: E402
    ARCHITECTURAL_LABELS, RESIDENTIAL_LABELS, describe, detect_objects, unload)

FIXTURE = ROOT / "tests" / "fixtures" / "detection_benchmark.json"
OUT_DIR = ROOT.parent / "docs" / "benchmarks"
BOX_THRESHOLD = 0.30          # one value for the whole benchmark, never per image
TEXT_THRESHOLD = 0.25
EXCLUDED = set(ARCHITECTURAL_LABELS)


class _Room:
    """The minimum `scene_reading_prompt()` reads off a room."""

    def __init__(self, room_id: str, room_type: str):
        self.room_id = self.name = room_id
        self.type = room_type
        self.width_m, self.length_m = 5.0, 4.0


def _norm(names) -> set[str]:
    """Both systems onto one vocabulary, using the app's own normaliser.

    `vocab.canonical_type` is what the reader's open names already go through
    ("couch" -> sofa, "nightstand" -> bedside_table), so the detector's prompts
    ride the same path rather than a second table invented for the benchmark.
    """
    out = set()
    for n in names:
        if not n:
            continue
        raw = str(n).strip().lower()
        if raw in EXCLUDED:
            continue
        # An already-canonical slug must NOT be re-mapped. `canonical_type`
        # matches whole words, so "pillows" does not match the keyword "pillow"
        # and comes back "other" - it maps open NAMES onto slugs, it is not
        # idempotent on slugs. Measured: pillows, curtains, side_table and
        # coffee_table all collapse to "other", and bar_stool to "stool".
        # Ground truth and the reader's own `semantic_type` are already slugs.
        sem = raw.replace(" ", "_")
        if sem not in vocab.ALL_SEMANTIC_TYPES:
            sem = vocab.canonical_type(raw)
        if sem and sem != "other" and sem not in EXCLUDED:
            out.add(sem)
    return out


def _score(found: set[str], expected: set[str]) -> dict:
    tp = len(found & expected)
    fp = len(found - expected)
    fn = len(expected - found)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": f1, "missing": sorted(expected - found), "spurious": sorted(found - expected)}


def _read_with_ollama(provider: OllamaProvider, image: Path, room: _Room) -> tuple[set[str], float, str]:
    """One scene read through qwen2.5vl. Returns (names, seconds, error)."""
    from PIL import Image

    im = Image.open(image).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")

    style = StyleSpec(name="Benchmark", tags=["modern"])
    started = time.perf_counter()
    try:
        raw = provider._generate(scene_reading_prompt(room, style, "residential"),
                                 SCENE_READING_SCHEMA, "benchmark_read", images=[encoded])
    except Exception as exc:                                       # noqa: BLE001
        return set(), round(time.perf_counter() - started, 2), f"{type(exc).__name__}: {exc}"
    elapsed = round(time.perf_counter() - started, 2)
    elements = raw.get("elements") or []
    names = [(e or {}).get("name") or "" for e in elements]
    types = [(e or {}).get("semantic_type") or "" for e in elements]
    return _norm(names) | _norm(types), elapsed, ""


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    images = fixture["images"]
    env = describe()
    provider = OllamaProvider()
    labels = [lab for lab in RESIDENTIAL_LABELS if lab.lower() not in EXCLUDED]

    print(f"model: {env}\nthreshold: {BOX_THRESHOLD}\nimages: {len(images)}\n", flush=True)
    rows, errors = [], []

    for entry in images:
        path = ROOT / entry["image"]
        expected = _norm(entry["expected_objects"])
        room = _Room(entry["room_type"], entry["room_type"])
        print(f"  {entry['room_type']:16} reader...", end="", flush=True)
        reader_found, reader_s, err = _read_with_ollama(provider, path, room)
        if err:
            errors.append(f"{entry['room_type']}: {err}")
        print(f" {reader_s:6.2f}s {len(reader_found):2} found   dino...", end="", flush=True)

        det = detect_objects(path, labels, box_threshold=BOX_THRESHOLD,
                             text_threshold=TEXT_THRESHOLD)
        dino_found = _norm(o["label"] for o in det["objects"])
        print(f" {det['elapsed_s']:5.2f}s {len(dino_found):2} found", flush=True)

        # Two combination rules, SIMULATED only - neither is the production
        # reconciliation, which would also match boxes:
        #
        #   UNION   - "CV finds geometry, the LLM names things". Takes both
        #             systems' recall AND both systems' false positives.
        #   CONFIRM - intersection: keep only what both systems independently
        #             saw. The detector votes on the reader's answer instead of
        #             replacing it. Precision is the metric that maps to money
        #             here: a false positive that survives review is 30 credits
        #             of mesh for something that was never in the picture.
        hybrid_found = dino_found | reader_found
        confirm_found = dino_found & reader_found

        rows.append({
            "image": entry["image"], "room_type": entry["room_type"],
            "source": entry["source"], "expected": sorted(expected),
            "reader": {"found": sorted(reader_found), "elapsed_s": reader_s,
                       "error": err, **_score(reader_found, expected)},
            "dino": {"found": sorted(dino_found), "elapsed_s": det["elapsed_s"],
                     "peak_vram_mb": det["peak_vram_mb"], "raw_boxes": len(det["objects"]),
                     **_score(dino_found, expected)},
            "hybrid": {"found": sorted(hybrid_found), **_score(hybrid_found, expected)},
            "confirm": {"found": sorted(confirm_found), **_score(confirm_found, expected)},
        })

    def agg(system: str) -> dict:
        """Micro-averaged: pool tp/fp/fn across images, so a 3-object room does
        not weigh the same as a 7-object one."""
        tp = sum(r[system]["tp"] for r in rows)
        fp = sum(r[system]["fp"] for r in rows)
        fn = sum(r[system]["fn"] for r in rows)
        p = tp / (tp + fp) if (tp + fp) else 0.0
        rc = tp / (tp + fn) if (tp + fn) else 0.0
        times = [r[system].get("elapsed_s", 0.0) for r in rows if r[system].get("elapsed_s")]
        return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": rc,
                "f1": (2 * p * rc / (p + rc)) if (p + rc) else 0.0,
                "avg_s": round(statistics.mean(times), 2) if times else 0.0}

    totals = {s: agg(s) for s in ("reader", "dino", "hybrid", "confirm")}
    peak = max((r["dino"]["peak_vram_mb"] for r in rows), default=0.0)
    unload()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "phase_0b_raw.json").write_text(json.dumps(
        {"environment": env, "box_threshold": BOX_THRESHOLD,
         "text_threshold": TEXT_THRESHOLD, "labels": labels,
         "excluded_labels": sorted(EXCLUDED), "errors": errors,
         "per_image": rows, "totals": totals}, indent=2), encoding="utf-8")
    _write_report(env, rows, totals, peak, errors, labels)
    print(f"\nwrote {OUT_DIR / 'phase_0b_detector_report.md'}")
    for s in ("reader", "dino", "hybrid", "confirm"):
        t = totals[s]
        print(f"  {s:8} P={t['precision']:.2f} R={t['recall']:.2f} F1={t['f1']:.2f} "
              f"fp={t['fp']} fn={t['fn']} avg={t['avg_s']}s")
    return 0


def _write_report(env, rows, totals, peak, errors, labels) -> None:
    L = []
    add = L.append
    add("# Phase 0b - object detection benchmark gate\n")
    add("Does an open-vocabulary detector identify objects in a moodboard render")
    add("better than the scene reader does? Measurement only: no production code")
    add("was changed and nothing here is wired into the pipeline.\n")

    add("## Environment\n")
    add(f"- GPU: {env.get('gpu', 'n/a')}, {env.get('vram_gb', '?')} GB")
    add(f"- CUDA available: {env.get('cuda')}")
    add(f"- torch: {env.get('torch')}")
    add(f"- detector: `{env.get('model')}`")
    add(f"- thresholds: box {BOX_THRESHOLD}, text {TEXT_THRESHOLD} - one pair for every image\n")

    add("## Dataset\n")
    add(f"- {len(rows)} real moodboard renders, 704x448, from two real projects")
    add("- room types: " + ", ".join(sorted({r["room_type"] for r in rows})))
    add("- ground truth: `tests/fixtures/detection_benchmark.json`, labelled by eye\n")
    add("**Limitations.** No hospitality or industrial room has ever been run through")
    add("this pipeline, so every image is residential and the label list is the")
    add("residential one. Windows, doors, walls, floors and ceilings are excluded from")
    add("both the detector's prompt and the scoring, because `scene_reading_prompt()`")
    add("forbids the reader from boxing them. Both systems are normalised with")
    add("`vocab.canonical_type()`, which folds a television and a media console onto")
    add("the single type `tv_unit` - a coarseness of the existing vocabulary that")
    add("costs both systems equally.\n")
    if errors:
        add("**Errors during the run:**\n")
        for e in errors:
            add(f"- {e}")
        add("")

    add("## Results\n")
    add("Micro-averaged over all images: true/false positives pooled, so a")
    add("three-object bathroom does not weigh as much as a seven-object living room.\n")
    add("| Metric | Scene reader (qwen2.5vl:3b) | Grounding DINO | Hybrid (union) | Confirm (both agree) |")
    add("|---|---|---|---|---|")
    for key, label, fmt in (("precision", "Precision", "{:.2f}"), ("recall", "Recall", "{:.2f}"),
                            ("f1", "F1", "{:.2f}"), ("fp", "False positives", "{}"),
                            ("fn", "False negatives", "{}"), ("avg_s", "Avg time / image", "{}s")):
        add(f"| {label} | " + " | ".join(
            fmt.format(totals[s][key]) for s in ("reader", "dino", "hybrid", "confirm")) + " |")
    add("")

    add("## Per image\n")
    for r in rows:
        add(f"### {r['room_type']} - `{Path(r['image']).name}`")
        add(f"*{r['source']}*\n")
        add(f"- expected: `{'`, `'.join(r['expected']) or '-'}`")
        for s, name in (("reader", "reader"), ("dino", "DINO"), ("hybrid", "hybrid union"),
                        ("confirm", "confirm (both)")):
            d = r[s]
            add(f"- **{name}** P={d['precision']:.2f} R={d['recall']:.2f} F1={d['f1']:.2f} - "
                f"found `{'`, `'.join(d['found']) or '-'}`")
            if d["missing"]:
                add(f"  - missed: `{'`, `'.join(d['missing'])}`")
            if d["spurious"]:
                add(f"  - spurious: `{'`, `'.join(d['spurious'])}`")
        add("")

    add("## Hardware performance\n")
    add(f"- detector: {totals['dino']['avg_s']}s per image on GPU, peak {peak} MB VRAM")
    add(f"- reader: {totals['reader']['avg_s']}s per image (qwen2.5vl:3b, local)")
    add("- batch size 1, inference only, no CPU fallback needed\n")
    add(f"- detector label set ({len(labels)} prompts): `{'`, `'.join(labels)}`\n")
    (OUT_DIR / "phase_0b_detector_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

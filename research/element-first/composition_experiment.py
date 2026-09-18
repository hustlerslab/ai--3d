"""May the moodboard be painted FROM the element images?

The element-first goal is that the room render shows the pieces that were
decided and pictured before it. The renderer conditions on reference photos
through IP-Adapter, and the repository already records the risk: "IP-Adapter
takes ONE embedding, so several references average into mush". So this is
measured, not assumed, before the moodboard changes.

Three ways of painting the same room, same prompt, same seeds:

  A_current         today's conditioning: the one anchor photo, or none
  B_all_elements    every element image of the room as references
  C_anchor_element  the element image of the room's anchor piece only

Each render is read back by the SAME scene reader production uses, and the
pieces it finds are compared with the element inventory for that room:
type recall, instance-count accuracy, and pieces the render invented. The
variant that reaches the most of the inventory without inventing wins; a tie
goes to the cheaper one. If nothing beats A, the moodboard does not change.

    python -u research/element-first/composition_experiment.py <project_id> [room_id] [seeds]
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "aether-backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings                                  # noqa: E402
from app.intelligence import build_input_bundle, get_provider             # noqa: E402
from app.intelligence.prompts import SD_NEGATIVE, compose_room_prompt     # noqa: E402
from app.intelligence.schema import DesignAnalysis, ElementImageSet, StyleSpec  # noqa: E402
from app.intelligence.scene_reading import coerce_room_reading            # noqa: E402
from app.jobs.handlers.analyze import _ANCHOR_TYPES, _scene_reference     # noqa: E402
from app.projects.layout import project_dir                               # noqa: E402
from app.providers import local_image                                     # noqa: E402

OUT_JSON = Path(__file__).resolve().parent / "composition-results.json"
OUT_DIR = Path(os.environ.get("COMPOSITION_OUT",
                              str(Path(__file__).resolve().parent / "composition_renders")))


def main() -> int:
    pid = sys.argv[1]
    room_id = sys.argv[2] if len(sys.argv) > 2 else ""
    seeds = [11, 23, 37][: int(sys.argv[3]) if len(sys.argv) > 3 else 3]
    settings = get_settings()
    root = project_dir(pid)

    analysis = DesignAnalysis.model_validate(json.loads((root / "analysis/design_analysis.json").read_text("utf-8")))
    style = StyleSpec.model_validate(json.loads((root / "analysis/style_spec.json").read_text("utf-8")))
    images = ElementImageSet.model_validate(json.loads((root / "planning/element_images.json").read_text("utf-8")))
    bundle = build_input_bundle(pid)
    provider = get_provider()

    room = next((r for r in analysis.rooms if not room_id or r.room_id == room_id), analysis.rooms[0])
    defs = [d for d in images.definitions if d.room_id == room.room_id]
    pics = {im.element_id: root / im.image_ref for im in images.images
            if not im.error and im.image_ref and (root / im.image_ref).is_file()}
    expected = Counter({d.semantic_type: d.instance_count for d in defs if d.element_id in pics})
    if not expected:
        raise SystemExit(f"{room.room_id}: no pictured pieces to compose from")

    anchor = next((d for t in _ANCHOR_TYPES for d in defs if d.semantic_type == t and d.element_id in pics), None)
    current_ref, current_note = _scene_reference(analysis, bundle, room_id=room.room_id)
    prompt, _ = compose_room_prompt(provider, analysis, style, bundle, room)

    variants = {
        "A_current": ([current_ref] if current_ref else None),
        "B_all_elements": [pics[d.element_id] for d in defs if d.element_id in pics],
        "C_anchor_element": ([pics[anchor.element_id]] if anchor else None),
    }
    print(f"room {room.room_id} | expected {dict(expected)} | anchor "
          f"{anchor.semantic_type if anchor else '-'} | current ref: {current_note}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"_about": __doc__.strip().splitlines()[0], "project": pid, "room": room.room_id,
              "expected": dict(expected), "prompt": prompt, "seeds": seeds, "variants": {}}
    try:
        for name, refs in variants.items():
            rows = []
            for seed in seeds:
                t0 = time.perf_counter()
                try:
                    gen = local_image.generate(
                        prompt, model=settings.scene_image_model, negative_prompt=SD_NEGATIVE,
                        steps=settings.scene_image_steps, width=settings.scene_image_width,
                        height=settings.scene_image_height, seed=seed, references=refs,
                        reference_scale=settings.scene_image_reference_scale if refs else 0.0)
                except Exception as exc:                                      # noqa: BLE001
                    # A variant the renderer cannot do is a RESULT, not an abort:
                    # "several references" is exactly what the repo warned about.
                    rows.append({"seed": seed, "error": f"{type(exc).__name__}: {exc}"[:300]})
                    print(f"  {name:18s} seed {seed:3d}  FAILED  {str(exc)[:110]}")
                    break
                dest = OUT_DIR / f"{room.room_id}_{name}_{seed}.png"
                local_image.write(gen, dest)
                render_s = time.perf_counter() - t0

                raw = provider.read_scene_elements(dest, room, style, bundle.vertical)
                elements, _surfaces = coerce_room_reading(raw, room, bundle.vertical, [])
                found = Counter(e.semantic_type for e in elements)
                hit_types = [t for t in expected if found.get(t)]
                count_ok = sum(1 for t in expected if found.get(t) == expected[t])
                extra = {t: n for t, n in found.items() if t not in expected}
                rows.append({"seed": seed, "found": dict(found),
                             "type_recall": round(len(hit_types) / len(expected), 3),
                             "count_accuracy": round(count_ok / len(expected), 3),
                             "extra_types": len(extra), "render_seconds": round(render_s, 1),
                             "image": str(dest)})
                print(f"  {name:18s} seed {seed:3d}  recall {rows[-1]['type_recall']:.2f}  "
                      f"counts {rows[-1]['count_accuracy']:.2f}  extra {len(extra)}  "
                      f"{render_s:5.1f}s  {dict(found)}")
            good = [r for r in rows if "error" not in r]
            n = len(good)
            report["variants"][name] = {
                "references": len(refs or []),
                "type_recall": round(sum(r["type_recall"] for r in good) / n, 3) if n else 0.0,
                "count_accuracy": round(sum(r["count_accuracy"] for r in good) / n, 3) if n else 0.0,
                "extra_types": round(sum(r["extra_types"] for r in good) / n, 2) if n else 99.0,
                "error": next((r["error"] for r in rows if "error" in r), ""),
                "runs": rows,
            }
    finally:
        local_image.unload()

    ranked = sorted(report["variants"].items(),
                    key=lambda kv: (-kv[1]["type_recall"], -kv[1]["count_accuracy"], kv[1]["extra_types"]))
    report["selected"] = ranked[0][0]
    base = report["variants"]["A_current"]
    best = report["variants"][report["selected"]]
    report["beats_current"] = (best["type_recall"] > base["type_recall"]
                               or (best["type_recall"] == base["type_recall"]
                                   and best["count_accuracy"] > base["count_accuracy"]))
    print(f"\nselected: {report['selected']} | beats current: {report['beats_current']}")
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

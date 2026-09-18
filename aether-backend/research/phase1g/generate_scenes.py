"""Phase 1g: generate interior scenes to harvest wall-contact negatives from.

    python -u research/phase1g/generate_scenes.py [--only N]

Research only. Calls the project's own local image provider - the same
`app.providers.local_image` the moodboard stage uses, at the same 704x448 and
the same step count - so the benchmark imagery is the imagery production makes.
Nothing in app/ is modified.

WHY GENERATE RATHER THAN ANNOTATE HARDER: Phase 1f examined all 11 existing
renders and all 8 reference photos and found 5 negatives. That is not an
annotation failure, it is what finished-room photography contains - furniture is
shot against the walls. To measure a false-wall rate the dataset has to be
*designed* to contain free-standing furniture, and the only in-domain way to do
that is to ask the generator for it.

WHAT THE PROMPTS DO AND DO NOT DO: the probe established that SD 1.5 does not
obey spatial instructions. Asked for "an ottoman alone in the middle of the
floor" it returned a sectional and a rug; asked for "stools pulled back from the
island" it tucked them under it. So the prompts here only BIAS the sampler
toward layouts where free-standing furniture is likely - open plan, seating
islands, chairs at wall-desks. What is actually in each image is decided later,
by looking at it. The `intent_bias` field records what was asked for precisely
so that it can be checked against what was annotated, and a case is never
labelled from it.

Seeds are fixed so the set is reproducible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings                                # noqa: E402
from app.providers import local_image                                   # noqa: E402

SCENES_DIR = HERE / "scenes"
MANIFEST = HERE / "scene_manifest.json"

NEGATIVE_PROMPT = ("cluttered, people, person, text, watermark, logo, blurry, "
                   "distorted, deformed furniture, low quality, collage, "
                   "multiple rooms, floor plan")

#: 18 scenes over 8 room types. Two thirds are asked for layouts where a piece
#: stands clear of the walls (bias "A"), one third for a piece drawn up to a
#: wall-backed mass (bias "B"), and several ask for both in one room so that
#: category cannot end up meaning scene - the confound that made Phase 1f's
#: Category B uninterpretable.
SCENES: list[dict] = [
    {"scene_id": "s01", "room_type": "living_room", "seed": 1101, "intent_bias": "A+B",
     "prompt": "interior photograph of an open plan living room, two armchairs "
               "facing each other in the middle of the open floor with clear space "
               "behind them, a low media cabinet fixed along the far wall, wide "
               "wooden floor, daylight, architectural photography"},
    {"scene_id": "s02", "room_type": "living_room", "seed": 1202, "intent_bias": "A",
     "prompt": "interior photograph of a large minimal living room, a single round "
               "ottoman and a low coffee table standing together in the centre of "
               "the floor, generous empty floor all around them, pale walls far "
               "away, daylight, architectural photography"},
    {"scene_id": "s03", "room_type": "living_room", "seed": 1303, "intent_bias": "B",
     "prompt": "interior photograph of a living room, a lounge chair placed in front "
               "of a long wall-mounted television cabinet, the chair standing clear "
               "of the cabinet on open floor, warm daylight, architectural photography"},
    {"scene_id": "s04", "room_type": "bedroom", "seed": 1404, "intent_bias": "A+B",
     "prompt": "interior photograph of a spacious hotel style bedroom, an upholstered "
               "bench standing alone on the floor at the foot of the bed with space "
               "around it, a desk built against the side wall with a chair drawn up "
               "to it, daylight, architectural photography"},
    {"scene_id": "s05", "room_type": "bedroom", "seed": 1505, "intent_bias": "A",
     "prompt": "interior photograph of a large bedroom suite, an armchair and a floor "
               "lamp standing together in the middle of the room away from every wall, "
               "wide floor, soft daylight, architectural photography"},
    {"scene_id": "s06", "room_type": "kitchen", "seed": 1606, "intent_bias": "B",
     "prompt": "interior photograph of a modern kitchen, tall bar stools drawn up to a "
               "long counter that runs along the back wall, floor visible under and "
               "behind the stools, daylight, architectural photography"},
    {"scene_id": "s07", "room_type": "kitchen", "seed": 1707, "intent_bias": "A+B",
     "prompt": "interior photograph of an open plan kitchen, a freestanding island in "
               "the middle of the room with clear floor on every side, stools at the "
               "island, fitted cabinets along the far wall, daylight, architectural "
               "photography"},
    {"scene_id": "s08", "room_type": "dining_room", "seed": 1808, "intent_bias": "A+B",
     "prompt": "interior photograph of a dining room, a dining table and chairs "
               "standing in the middle of the floor well away from the walls, a long "
               "sideboard fixed against the back wall behind them, daylight, "
               "architectural photography"},
    {"scene_id": "s09", "room_type": "office", "seed": 1909, "intent_bias": "B",
     "prompt": "interior photograph of a home office, a desk chair pulled back from a "
               "desk that is built against the wall, clear floor between the chair and "
               "the desk, shelves on the wall, daylight, architectural photography"},
    {"scene_id": "s10", "room_type": "office", "seed": 2010, "intent_bias": "A",
     "prompt": "interior photograph of a large studio office, a meeting table with "
               "chairs standing in the centre of an open floor, plenty of empty floor "
               "between the furniture and the distant walls, daylight, architectural "
               "photography"},
    {"scene_id": "s11", "room_type": "lounge", "seed": 2111, "intent_bias": "A",
     "prompt": "interior photograph of a hotel lounge, a cluster of armchairs and a "
               "low table forming an island of seating in the middle of a wide floor, "
               "walls far in the background, daylight, architectural photography"},
    {"scene_id": "s12", "room_type": "lounge", "seed": 2212, "intent_bias": "A+B",
     "prompt": "interior photograph of a lounge, an ottoman standing alone on open "
               "floor, and a bench placed in front of a long wall-backed console, "
               "daylight, architectural photography"},
    {"scene_id": "s13", "room_type": "living_room", "seed": 2313, "intent_bias": "A",
     "prompt": "interior photograph of a wide living room, a coffee table standing "
               "alone on a bare wooden floor with clear space all around, sofa far "
               "back against the wall, daylight, architectural photography"},
    {"scene_id": "s14", "room_type": "bedroom", "seed": 2414, "intent_bias": "B",
     "prompt": "interior photograph of a bedroom, a small stool standing in front of a "
               "dressing table that is fixed against the wall, clear floor around the "
               "stool, daylight, architectural photography"},
    {"scene_id": "s15", "room_type": "kitchen", "seed": 2515, "intent_bias": "A",
     "prompt": "interior photograph of a large kitchen, a freestanding butcher block "
               "table standing alone in the centre of the floor, clear floor on all "
               "sides, daylight, architectural photography"},
    {"scene_id": "s16", "room_type": "dining_room", "seed": 2616, "intent_bias": "B",
     "prompt": "interior photograph of a dining area, chairs drawn up to a bench table "
               "that stands against a panelled wall, floor visible around the chairs, "
               "daylight, architectural photography"},
    {"scene_id": "s17", "room_type": "office", "seed": 2717, "intent_bias": "A+B",
     "prompt": "interior photograph of an open plan office, a low armchair standing "
               "alone on the floor between desks, a workstation run fixed along the "
               "wall behind it, daylight, architectural photography"},
    {"scene_id": "s18", "room_type": "lounge", "seed": 2818, "intent_bias": "A",
     "prompt": "interior photograph of a large reception lounge, a long bench standing "
               "by itself in the middle of a stone floor, wide empty floor, walls "
               "distant, daylight, architectural photography"},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, default=0, help="first N scenes")
    args = parser.parse_args()

    if not local_image.available():
        print("local image generation is unavailable:", local_image.describe())
        return 1

    settings = get_settings()
    width, height = settings.scene_image_width, settings.scene_image_height
    steps = settings.scene_image_steps
    SCENES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"device: {local_image.describe()}")
    print(f"size {width}x{height}  steps {steps}  scenes "
          f"{args.only or len(SCENES)}\n", flush=True)

    todo = SCENES[:args.only] if args.only else SCENES
    rows = []
    for scene in todo:
        path = SCENES_DIR / f"{scene['scene_id']}_{scene['room_type']}.png"
        row = {**scene, "path": str(path.relative_to(ROOT)).replace("\\", "/"),
               "width": width, "height": height, "steps": steps,
               "model": settings.scene_image_model}
        if path.is_file():
            print(f"  {scene['scene_id']}  exists, skipping", flush=True)
            rows.append(row)
            continue
        started = time.perf_counter()
        try:
            image = local_image.generate(
                scene["prompt"], negative_prompt=NEGATIVE_PROMPT, steps=steps,
                guidance=7.0, width=width, height=height, seed=scene["seed"])
            local_image.write(image, path)
            row["elapsed_s"] = round(time.perf_counter() - started, 1)
            print(f"  {scene['scene_id']}  {scene['room_type']:13} "
                  f"bias={scene['intent_bias']:3}  {row['elapsed_s']}s", flush=True)
        except Exception as exc:                                  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            print(f"  {scene['scene_id']}  FAILED {row['error']}", flush=True)
        rows.append(row)

    local_image.unload()
    MANIFEST.write_text(json.dumps(
        {"_about": "Phase 1g generated scenes. `intent_bias` records what the prompt "
                   "asked for; it is NOT ground truth and no case is labelled from it. "
                   "Ground truth comes from looking at the image.",
         "model": settings.scene_image_model, "negative_prompt": NEGATIVE_PROMPT,
         "scenes": rows}, indent=2), encoding="utf-8")
    ok = sum(1 for r in rows if "error" not in r)
    print(f"\n  {ok}/{len(rows)} scenes generated -> {SCENES_DIR}")
    print(f"  wrote {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

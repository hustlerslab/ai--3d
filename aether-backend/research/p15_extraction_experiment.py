"""P15: does the reference prompt get visual evidence into the STRUCTURED fields?

P14 measured `frame_finish` at 0 of 8 real photographs and concluded extraction,
not rendering, was the binding constraint. This runs three prompt variants over
those same 8 images through the LIVE Gemini provider and scores each against
ground truth established by looking at the pictures.

The ground truth matters more than the population count. Four of the eight
images are mattresses, which have no frame at all, so a prompt that pushes
`frame_finish` to 8 of 8 has hallucinated four times, not improved four times.
Population is reported next to false positives, never instead of them.

    python -u research/p15_extraction_experiment.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings                                  # noqa: E402
from app.intelligence.gemini_provider import GeminiProvider               # noqa: E402
from app.intelligence.prompts import (REFERENCE_CLASSIFICATION_SCHEMA,    # noqa: E402
                                      reference_classification_prompt)
from app.intelligence.reference_reader import attributes_from_raw         # noqa: E402
from app.intelligence.images import encode_for_gemini                     # noqa: E402

REFS = ROOT / "data" / "projects" / "proj_553cb09794" / "input" / "references"
OUT = ROOT.parent / "docs" / "benchmarks" / "p15_reference_extraction.json"
PACE = 6.0   # seconds between calls; the free-tier quota is per minute
BRIEF = ("Two bedroom flat: living room, master bedroom, kids room, kitchen. "
         "Warm and calm, natural materials.")
FIELDS = ["material", "upholstery", "frame_finish", "color_words", "color_hex",
          "pattern", "visual_descriptors", "style_descriptors"]

# ── ground truth ─────────────────────────────────────────────────────────
#
# Established by viewing each photograph. `accept` lists substrings any one of
# which makes the answer correct. `None` means the attribute is NOT visibly
# supported, so ANY non-empty answer is a false positive. `over_specific` lists
# answers the image cannot justify (P15 section 8: generic wood must not become
# a named species).
GROUND_TRUTH: dict[str, dict] = {
    "ref_04": {  # teal fabric sofa, skirted base, NO legs or frame visible
        "object": "sofa",
        "upholstery": {"accept": ["fabric", "chenille", "velvet", "woven", "textile", "linen"]},
        "frame_finish": None,
        "color_words": {"accept": ["teal", "blue", "turquoise", "petrol"]},
        "pattern": {"accept": ["geometric", "hexagon", "cube", "diamond"]},
        "material": {"accept": ["fabric", "textile", "chenille", "velvet"], "optional": True},
    },
    "ref_05": {  # grey sofa-bed, GOLD metal arm bars, quilted base panel
        "object": "sofa",
        "upholstery": {"accept": ["fabric", "linen", "woven", "textile", "polyester"]},
        "frame_finish": {"accept": ["gold", "brass", "metal", "metallic"],
                         "over_specific": ["walnut", "oak", "teak", "wood"]},
        "color_words": {"accept": ["grey", "gray", "silver", "greige", "taupe"]},
        "pattern": {"accept": ["quilted", "diamond", "lattice"]},
        "material": {"accept": ["fabric", "textile"], "optional": True},
    },
    "ref_06": {  # two-tone brown/beige sofa, small dark feet, quilted panels
        "object": "sofa",
        "upholstery": {"accept": ["fabric", "suede", "velvet", "microfibre", "microfiber", "textile"]},
        "frame_finish": {"accept": ["wood", "dark", "black", "espresso", "brown"],
                         "over_specific": ["walnut", "oak", "teak", "mahogany"],
                         "optional": True},  # the feet are small; missing them is fair
        "color_words": {"accept": ["brown", "beige", "cream", "tan", "mauve", "plum", "taupe"]},
        "pattern": {"accept": ["quilted", "diamond", "tufted"]},
        "material": {"accept": ["fabric", "textile", "suede"], "optional": True},
    },
    "ref_07": {  # sage tufted sofa on an unmistakable DARK WOOD frame
        "object": "sofa",
        "upholstery": {"accept": ["fabric", "linen", "woven", "textile", "cotton"]},
        "frame_finish": {"accept": ["wood", "wooden", "timber", "dark wood", "mahogany", "cherry"],
                         "over_specific": ["walnut", "oak", "ash", "birch"]},
        "color_words": {"accept": ["sage", "green", "mint", "eucalyptus", "celadon"]},
        "pattern": {"accept": ["tufted", "button", "grid", "quilted"], "optional": True},
        "material": {"accept": ["wood", "fabric", "textile"], "optional": True},
    },
    # ── the four mattresses: no frame exists on any of them ──────────────
    "ref_09": {
        "object": "mattress",
        "upholstery": {"accept": ["knit", "fabric", "quilted", "textile", "jacquard", "cotton", "damask"]},
        "frame_finish": None,
        "color_words": {"accept": ["white", "grey", "gray", "blue", "navy", "cream", "ivory"]},
        "pattern": {"accept": ["quilted", "damask", "floral", "houndstooth", "jacquard", "geometric"]},
        "material": {"accept": ["fabric", "textile", "knit", "foam"], "optional": True},
    },
    "ref_10": {
        "object": "mattress",
        "upholstery": {"accept": ["knit", "fabric", "quilted", "textile", "jacquard", "cotton"]},
        "frame_finish": None,
        "color_words": {"accept": ["white", "navy", "blue", "grey", "gray"]},
        "pattern": {"accept": ["quilted", "diamond", "damask", "jacquard", "geometric"]},
        "material": {"accept": ["fabric", "textile", "knit", "foam"], "optional": True},
    },
    "ref_11": {
        "object": "mattress",
        "upholstery": {"accept": ["knit", "fabric", "quilted", "textile", "jacquard", "cotton"]},
        "frame_finish": None,
        "color_words": {"accept": ["white", "cream", "ivory", "navy", "blue", "beige"]},
        "pattern": {"accept": ["quilted", "damask", "jacquard", "geometric", "striped"]},
        "material": {"accept": ["fabric", "textile", "knit", "foam"], "optional": True},
    },
    "ref_12": {
        "object": "mattress",
        "upholstery": {"accept": ["knit", "fabric", "quilted", "textile", "mesh", "jacquard"]},
        "frame_finish": None,
        "color_words": {"accept": ["blue", "navy", "light blue", "white"]},
        "pattern": {"accept": ["quilted", "diamond", "damask", "jacquard", "geometric"]},
        "material": {"accept": ["fabric", "textile", "knit", "foam"], "optional": True},
    },
}

# color_hex is never in ground truth: no image carries an authoritative hex, so
# ANY hex is an unsupported inference. That is the P15 section 11 rule, measured
# rather than asserted.


# ── prompt variants ──────────────────────────────────────────────────────

#: The attribute half of the prompt EXACTLY as P14 left it, frozen as a literal.
#: It must not call the live function: P15 rewrote that function, so calling it
#: would silently turn the baseline into a second copy of the new prompt and the
#: before/after comparison would compare nothing.
_P14_ATTRIBUTE_BLOCK = [
    "",
    "DESCRIBE WHAT YOU SEE, only where you are sure (leave a field out otherwise):",
    "  color_words        - colours in plain words, e.g. ['sage green', 'brushed brass']",
    "  color_hex          - #RRGGBB only if you are confident of the exact shade",
    "  material           - the dominant material, e.g. 'oak', 'linen', 'marble'",
    "  upholstery         - covering of a soft piece, e.g. 'tufted velvet', 'boucle'",
    "  pattern            - e.g. 'vertical stripes', 'floral', 'plain'",
    "  frame_finish       - legs/frame finish, e.g. 'walnut', 'matte black steel'",
    "  style_descriptors  - e.g. ['japandi', 'mid-century']",
    "  visual_descriptors - other visible traits, e.g. ['low back', 'rounded arms']",
    "  room_hint          - the room it belongs in, if the image makes that clear",
    "",
    "confidence is 0.0-1.0 for the CLASS you chose. Below 0.25 is treated as uncertain, "
    "so use a low number honestly rather than inflating it.",
    "Describe colours in words. Do not invent a hex code you are not sure of.",
]


def prompt_a(description: str, vertical) -> str:
    """The production prompt as P14 left it: classification half from the live
    function, attribute half frozen above."""
    live = reference_classification_prompt(description, vertical)
    head = live.split("FILL THE STRUCTURED FIELDS")[0].rstrip()
    return head + "\n" + "\n".join(_P14_ATTRIBUTE_BLOCK)


_STRUCTURED_BLOCK = [
    "",
    "FILL THE STRUCTURED FIELDS. Downstream systems read ONLY the structured",
    "fields - a detail written into visual_descriptors and nowhere else is lost.",
    "Answer every field. Use an empty string or empty list when the image does",
    "not support an answer: empty is a correct, expected answer and is always",
    "better than a guess.",
    "",
    "  material     - the primary/body surface material, when independently",
    "                 visible: wood, marble, glass, metal, stone, leather.",
    "                 Leave empty for a fully upholstered piece.",
    "  upholstery   - the soft covering: linen, velvet, boucle, leather, cotton,",
    "                 knit fabric. This is NOT the same field as material.",
    "  frame_finish - the finish of the visible structural frame, base, legs,",
    "                 arms or trim.",
    "  color_words  - the visible colours in plain words: 'sage green', 'warm",
    "                 beige', 'charcoal'. Always words, never a hex code.",
    "  color_hex    - ONLY if an exact shade is genuinely certain. Do NOT convert",
    "                 a colour word into a hex value. Empty is almost always right.",
    "  pattern      - ONLY an actually visible pattern: striped, floral,",
    "                 geometric, herringbone, quilted. Not a style, not a mood.",
    "  style_descriptors  - design idiom: 'japandi', 'mid-century', 'art deco'.",
    "  visual_descriptors - remaining visible detail that fits no field above.",
]

_PART_BLOCK = [
    "",
    "INSPECT THE PIECE IN PARTS, in this order, before answering:",
    "  1. the whole object        5. the arms",
    "  2. the main body           6. the legs or base",
    "  3. the upholstered areas   7. the trim and accent regions",
    "  4. the structural frame    8. surface, colour, pattern",
    "",
    "Keep these four apart. They are different fields:",
    "  the body material   vs   the upholstery",
    "  vs the structural frame finish   vs the trim/accent finish",
    "",
    "FRAME FINISH - this is the field most often lost. If you can see the",
    "material or finish of a frame, structural frame, armrest, structural arm,",
    "leg, base, trim or accent trim, put it in frame_finish. Do not leave it",
    "only in visual_descriptors. You may ALSO keep the descriptive phrase in",
    "visual_descriptors for traceability.",
    "",
    "  'wooden frame'         -> frame_finish: 'wood'",
    "  'wooden armrests'      -> frame_finish: 'wood'",
    "  'black metal frame'    -> frame_finish: 'black metal'",
    "  'gold metal trim'      -> frame_finish: 'gold metal'",
    "  'brass trim'           -> frame_finish: 'brass'",
    "  'blackened metal base' -> frame_finish: 'blackened metal'",
    "",
    "But ONLY when you can actually see it. Many pieces have no visible frame",
    "at all - an upholstered piece on a hidden or skirted base, or a mattress,",
    "has no frame, and frame_finish must then be empty. Never assume a frame",
    "exists because pieces of this kind usually have one.",
    "",
    "Say what you can see, not what you can identify. Generic wood grain is",
    "'wood'; call it 'walnut' or 'oak' only if the image truly shows that",
    "species. The same restraint applies to every field.",
]


def _head(description: str, vertical) -> str:
    """The classification half, shared by every variant. Taken from the live
    prompt up to the attribute section so all four variants differ ONLY in the
    attribute instructions being compared."""
    live = reference_classification_prompt(description, vertical)
    return live.split("FILL THE STRUCTURED FIELDS")[0].rstrip()


def prompt_b(description: str, vertical) -> str:
    """A + explicit structured-attribute instructions."""
    return _head(description, vertical) + "\n".join(_STRUCTURED_BLOCK)


def prompt_c(description: str, vertical) -> str:
    """B + part-aware inspection and frame-specific routing. This is the
    variant P15 promoted into production."""
    return (_head(description, vertical)
            + "\n".join(_STRUCTURED_BLOCK) + "\n".join(_PART_BLOCK))


def _required_schema() -> dict:
    """The same schema with the attribute fields REQUIRED.

    The repository already learned this lesson once: `against` and `faces` in
    SCENE_READING_SCHEMA were optional and flash-lite omitted them on every
    element of every room until they were made required. A required field may
    still come back empty, which the caller reads as 'nothing to say'; an absent
    one cannot be told apart from a field the model never considered.
    """
    schema = json.loads(json.dumps(REFERENCE_CLASSIFICATION_SCHEMA))
    schema["required"] = ["reference_class", "confidence"] + FIELDS
    return schema


#: Sentinel: call the real production entry point instead of building parts
#: here, so the AFTER number proves the promoted prompt is actually wired.
PRODUCTION = "production"

def _p14_schema() -> dict:
    """The schema as P14 left it: only the class and confidence were required.
    Frozen for the same reason the P14 prompt is - P15 made the attribute
    fields required in the live schema, and the baseline must not inherit that."""
    schema = json.loads(json.dumps(REFERENCE_CLASSIFICATION_SCHEMA))
    schema["required"] = ["reference_class", "confidence"]
    return schema


VARIANTS = {
    "A_current": (prompt_a, _p14_schema()),
    "B_structured": (prompt_b, _required_schema()),
    "C_part_aware": (prompt_c, _required_schema()),
    "D_production": (PRODUCTION, PRODUCTION),
}


# ── scoring ──────────────────────────────────────────────────────────────

def _value_text(value) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value).lower()
    return str(value or "").lower()


def score_one(stem: str, attrs) -> dict:
    """Classify every field of one answer against the picture."""
    truth = GROUND_TRUTH[stem]
    rows = {}
    for field in FIELDS:
        value = getattr(attrs, field)
        text = _value_text(value)
        expected = truth.get(field)

        if field == "color_hex":
            # No image carries an authoritative hex.
            rows[field] = {"value": value,
                           "verdict": "unsupported_inference" if text else "correctly_empty"}
            continue
        if field in ("visual_descriptors", "style_descriptors"):
            rows[field] = {"value": value, "verdict": "present" if text else "empty"}
            continue

        if expected is None:                      # not visible: must stay empty
            rows[field] = {"value": value,
                           "verdict": "false_positive" if text else "correctly_empty"}
            continue
        if not isinstance(expected, dict):
            rows[field] = {"value": value, "verdict": "unscored"}
            continue

        if not text:
            rows[field] = {"value": value,
                           "verdict": "acceptable_miss" if expected.get("optional") else "missed"}
            continue
        if any(word in text for word in expected.get("over_specific", [])) \
                and not any(word in text for word in expected["accept"]):
            rows[field] = {"value": value, "verdict": "unsupported_inference"}
            continue
        hit = any(word in text for word in expected["accept"])
        rows[field] = {"value": value, "verdict": "correct" if hit else "incorrect"}
    return rows


def run_variant(provider, name: str, prompt_fn, schema: dict) -> dict:
    images, population, verdicts = [], {f: 0 for f in FIELDS}, {}
    for path in sorted(REFS.glob("*.jpeg")):
        stem = path.stem
        if stem not in GROUND_TRUTH:
            continue
        if prompt_fn is PRODUCTION:
            parts = None
        else:
            mime, data = encode_for_gemini(str(path), max_side=1024)
            parts = [
                {"text": prompt_fn(BRIEF, "residential")},
                {"inline_data": {"mime_type": mime, "data": data}},
                {"text": "The reference image is attached above."},
            ]
        raw = None
        for attempt in range(6):
            try:
                raw = (provider.classify_reference(path, BRIEF, "residential",
                                                   filename=path.name)
                       if parts is None else
                       provider._generate(parts, schema, f"p15.{name}"))
                break
            except Exception as exc:                                      # noqa: BLE001
                if attempt == 5:
                    raise
                wait = 20 * (attempt + 1)
                print(f"    {path.name}: {type(exc).__name__}; waiting {wait}s")
                time.sleep(wait)
        time.sleep(PACE)
        attrs = attributes_from_raw(raw)
        rows = score_one(stem, attrs)
        for field in FIELDS:
            if _value_text(getattr(attrs, field)):
                population[field] += 1
            verdicts.setdefault(field, {})
            v = rows[field]["verdict"]
            verdicts[field][v] = verdicts[field].get(v, 0) + 1
        images.append({"file": path.name, "object": GROUND_TRUTH[stem]["object"],
                       "reference_class": raw.get("reference_class", ""), "fields": rows})
        print(f"  {name:14s} {path.name:13s} frame={str(attrs.frame_finish)[:26]!r:28s} "
              f"uph={str(attrs.upholstery)[:20]!r}")

    false_positives = sum(v.get("false_positive", 0) + v.get("unsupported_inference", 0)
                          for v in verdicts.values())
    correct = sum(v.get("correct", 0) for v in verdicts.values())
    supported = correct + sum(v.get("missed", 0) + v.get("incorrect", 0) for v in verdicts.values())
    return {
        "population": population,
        "verdicts": verdicts,
        "false_positive_and_unsupported": false_positives,
        "extraction_fidelity": round(correct / supported, 4) if supported else None,
        "correct": correct, "visibly_supported": supported,
        "images": images,
    }


def main() -> int:
    provider = GeminiProvider(get_settings())
    print(f"provider: {provider.label}\n")
    report = {
        "_about": "P15 reference extraction. Three prompt variants over the SAME 8 real "
                  "photographs through the live Gemini provider, scored against ground truth "
                  "read off the pictures. Four of the eight are mattresses with no frame, so "
                  "they double as the false-positive control.",
        "stack": {"vision": "gemini", "asset_generation": "meshy",
                  "spatial": "allure", "executor": "blender"},
        "model": provider.label,
        "images": sorted(p.name for p in REFS.glob("*.jpeg") if p.stem in GROUND_TRUTH),
        "ground_truth": {k: {"object": v["object"],
                             "frame_finish_visible": v["frame_finish"] is not None}
                         for k, v in GROUND_TRUTH.items()},
        "variants": {},
    }
    if OUT.exists():
        prior = json.loads(OUT.read_text(encoding="utf-8")).get("variants", {})
        report["variants"].update(prior)
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for name, (fn, schema) in VARIANTS.items():
        if only and only != name:
            continue
        if name in report["variants"] and not only:
            print(f"-- {name} (already measured, kept) --")
            continue
        print(f"-- {name} --")
        report["variants"][name] = run_variant(provider, name, fn, schema)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print()

    done = [n for n in VARIANTS if n in report["variants"]]
    print(f"{'attribute':22s}" + "".join(f"{n:>16s}" for n in done))
    for field in FIELDS:
        cells = "".join(f"{report['variants'][n]['population'][field]:>16d}" for n in done)
        print(f"{field:22s}{cells}")
    print(f"{'false pos/unsupported':22s}"
          + "".join(f"{report['variants'][n]['false_positive_and_unsupported']:>16d}" for n in done))
    print(f"{'extraction fidelity':22s}"
          + "".join(f"{str(report['variants'][n]['extraction_fidelity']):>16s}" for n in done))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage prompts and output schemas shared by every LLM provider (DPR §27).

Schemas are plain JSON Schema (the Anthropic shape). `gemini_schema()`
converts one to Gemini's OpenAPI subset. Prompts are provider-neutral text;
images are attached by each provider in its own wire format.

Schema 1.1 reads the photos with an open vocabulary: every item gets a free
`name`, a coarse `family`, where it sits (`placement` + `support`) and a
bounding box in the photo, so nothing visible is dropped for lack of a type.
"""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from ..projects.schema import Vertical
from . import vocab
from .schema import DesignAnalysis, InputBundle, StyleSpec

# ── JSON schemas ─────────────────────────────────────────────────────────


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def analysis_schema(vertical: Vertical | str) -> dict[str, Any]:
    """Stage-5 schema for one vertical. The room `enum` is the mechanism that
    stops a hotel project coming back with `bedroom`, so it is built per
    project rather than baked in at import."""
    return _obj(
        {
            "intent": {"type": "string"},
            "rooms": {
                "type": "array",
                "items": _obj(
                    {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": vocab.room_types(vertical)},
                        "width_m": {"type": "number"},
                        "length_m": {"type": "number"},
                        "height_m": {"type": "number"},
                        "estimated": {"type": "boolean"},
                        "notes": {"type": "string"},
                    }
                ),
            },
            "constraints": {"type": "array", "items": {"type": "string"}},
            "spotted_objects": {
                "type": "array",
                "items": _obj(
                    {
                        "name": {"type": "string"},
                        "family": {"type": "string", "enum": vocab.FAMILIES},
                        "semantic_type": {"type": "string"},
                        "placement": {"type": "string", "enum": vocab.PLACEMENTS},
                        "support": {"type": "string"},
                        "room_name": {"type": "string"},
                        "count": {"type": "integer"},
                        "material": {"type": "string"},
                        "color": {"type": "string"},
                        "approx_dimensions": {"type": "array", "items": {"type": "number"}},
                        "image_index": {"type": "integer"},
                        "bbox": {"type": "array", "items": {"type": "number"}},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                    }
                ),
            },
            "architecture": {"type": "array", "items": {"type": "string", "enum": vocab.ARCHITECTURE_FEATURES}},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        }
    )


def style_schema(vertical: Vertical | str) -> dict[str, Any]:
    """Stage-6 schema for one vertical: the tag `enum` is what keeps a
    hospitality project inside the hospitality style vocabulary."""
    return _obj(
        {
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string", "enum": vocab.style_tags(vertical)}},
            "palette": {"type": "array", "items": {"type": "string"}},
            "materials": {"type": "array", "items": {"type": "string"}},
            "lighting_mood": {"type": "string", "enum": vocab.LIGHTING_MOODS},
            "description": {"type": "string"},
            "confidence": {"type": "number"},
        }
    )


OBJECT_PLAN_SCHEMA: dict[str, Any] = _obj(
    {
        "items": {
            "type": "array",
            "items": _obj(
                {
                    "object_key": {"type": "string"},
                    "name": {"type": "string"},
                    "family": {"type": "string", "enum": vocab.FAMILIES},
                    "semantic_type": {"type": "string"},
                    "room_id": {"type": "string"},
                    "placement": {"type": "string", "enum": vocab.PLACEMENTS},
                    "support_key": {"type": "string"},
                    "spotted_index": {"type": "integer"},
                    "priority": {"type": "integer"},
                    "count": {"type": "integer"},
                    "approx_dimensions": {"type": "array", "items": {"type": "number"}},
                    "relation_type": {
                        "type": "string",
                        "enum": ["in_front_of", "beside", "facing", "under", "around", "against_wall"],
                    },
                    "relation_target": {"type": "string"},
                    "style_notes": {"type": "string"},
                    "material_hint": {"type": "string"},
                    "color_hint": {"type": "string"},
                    "from_photo": {"type": "boolean"},
                    "unique": {"type": "boolean"},
                }
            ),
        },
        "confidence": {"type": "number"},
    }
)


def gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema → Gemini responseSchema (uppercase types, no additionalProperties)."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, str):
            out[key] = value.upper()
        elif key == "properties":
            out[key] = {k: gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = gemini_schema(value)
        else:
            out[key] = value
    return out


# ── prompts ──────────────────────────────────────────────────────────────

# The room-listing rule is the one part of the analysis prompt that is
# genuinely per-market: a hotel lobby estimated at apartment scale is a wrong
# answer, not a small one. The residential text is unchanged.
_ROOM_RULES: dict[Vertical, str] = {
    Vertical.RESIDENTIAL: (
        "- List every room the home needs. Use the supplied dimensions when present and set "
        "estimated=false for those; otherwise estimate generous, comfortable sizes for a modern apartment and set estimated=true. Typical: living room 5.5-6.5 m by 4.2-5.0 m (larger when it doubles as dining), master bedroom 4.5-5.0 by 4.0-4.5, other bedrooms 3.8-4.2 by 3.4-3.8, kitchen 3.6-4.2 by 2.8-3.2, dining room 4.0-4.5 by 3.4-3.8, study 3.4-3.8 by 3.0-3.4. Never go below the low end. Ceiling 3.0 m.\n"
    ),
    Vertical.HOSPITALITY: (
        "- List every room the property needs. Use the supplied dimensions when present and set "
        "estimated=false for those; otherwise estimate commercial sizes for a hotel or restaurant and set estimated=true. Typical: hotel lobby 11-14 m by 8-10 m, restaurant floor 12-16 by 9-11 (allow ~1.7 m2 per cover plus service aisles), cafe floor 8-10 by 6-8, bar 7-9 by 5-7, guest room 4.2-5.0 by 5.5-6.5, suite 6.5-8.0 by 7.5-9.0, banquet hall 18-22 by 12-16, reception 5-7 by 3.5-4.5, corridor 2.2-2.6 by 14-20. Never go below the low end. Ceiling 3.4 m.\n"
    ),
    Vertical.INDUSTRIAL: (
        "- List every room the workplace needs. Use the supplied dimensions when present and set "
        "estimated=false for those; otherwise estimate office sizes for a loft-style workplace and set estimated=true. Typical: open plan office 14-18 m by 9-12 m (allow ~8 m2 per desk including circulation), private office 3.6-4.4 by 3.2-4.0, meeting room 5.5-6.5 by 4.0-4.5, reception 5-7 by 3.5-4.5, breakout 6-8 by 4.5-5.5, pantry 3.5-4.5 by 2.6-3.4. Never go below the low end. Ceiling 3.2 m.\n"
    ),
}

# the closing, room-specific line of the object-planning prompt
_PLANNING_RULES: dict[Vertical, str] = {
    Vertical.RESIDENTIAL: (
        "- Kitchens need a kitchen_counter along the longest wall; living rooms need curtains at the window.\n"
    ),
    Vertical.HOSPITALITY: (
        "- Restaurant and cafe floors need restaurant_tables with chairs (and banquette or booth_seating "
        "along the walls); a bar needs a bar_counter with bar_stools; reception needs a reception_desk; "
        "a lobby needs lounge_sofas in seating clusters.\n"
    ),
    Vertical.INDUSTRIAL: (
        "- Open plan offices need workstations in runs with office_chairs; meeting rooms need a "
        "meeting_table with office_chairs around it; reception needs a reception_desk.\n"
    ),
}


def analysis_prompt(bundle: InputBundle) -> str:
    vertical = vocab._v(bundle.vertical)
    hints = [h.model_dump() for h in bundle.room_hints]
    return (
        "You are the input-analysis agent of an interior design pipeline.\n"
        "Read the client's brief, the room dimensions they supplied (may be empty) and the "
        "reference photos. Extract structured facts only; do not design yet.\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ROOM DIMENSIONS SUPPLIED BY CLIENT (metres):\n{json.dumps(hints) if hints else '(none)'}\n\n"
        "Rules:\n"
        + _ROOM_RULES[vertical]
        + f"- room.type must be one of: {', '.join(vocab.room_types(vertical))}.\n"
        "- spotted_objects: EVERY distinct furnishing, decor piece and built-in element visible in the "
        "photos, plus anything requested in the brief. Be exhaustive (up to 40 items): sofas, tables, "
        "cabinets, lamps, plants in urns, pedestals, rugs (each layer), curtains, pillows, trays, books, "
        "vases, ornaments on brackets, art, mirrors, fireplaces. One entry per kind; use count for copies.\n"
        "  - name: short, specific, open vocabulary, e.g. 'mahogany secretary bookcase with fretwork doors', "
        "'wicker urn with fern on wicker pedestal', 'blue and white pagoda ornament'.\n"
        f"  - family: one of {', '.join(vocab.FAMILIES)}.\n"
        f"  - semantic_type: the closest of {', '.join(t for t in vocab.semantic_types(vertical) if t != 'other')}; "
        "use 'other' only when nothing is close.\n"
        "  - placement: floor | wall (hung on a wall) | ceiling | on_surface (rests on another listed item).\n"
        "  - support: for on_surface, the exact name of the listed item it rests on; else ''.\n"
        "  - material and color (hex) as seen; approx_dimensions [width, height, depth] in metres.\n"
        "  - image_index: 0-based index of the photo the item is in (-1 if only in the brief). "
        "bbox: [x_min, y_min, x_max, y_max] as fractions 0..1 of that photo's width and height, a tight "
        "box around ONE instance. Omit bbox when the item is not visible.\n"
        "  - room_name should match one of the rooms you listed. Put observations in notes.\n"
        f"- architecture: built-in features seen in the photos, from: {', '.join(vocab.ARCHITECTURE_FEATURES)}.\n"
        "- constraints: explicit client requirements (budget, things to avoid, must-haves) as short sentences.\n"
        f"- keywords: style words from this list only: {', '.join(vocab.style_tags(vertical))}.\n"
        "- confidence: 0..1 for the overall extraction.\n"
    )


def style_prompt(analysis: DesignAnalysis, bundle: InputBundle, catalog: list[dict[str, Any]]) -> str:
    vertical = vocab._v(bundle.vertical)
    spotted = [s.model_dump(include={"name", "semantic_type", "material", "color"}) for s in analysis.spotted_objects[:40]]
    return (
        "You are the style-interpretation agent of an interior design pipeline.\n"
        "From the brief, the extracted analysis and the reference photos, define one coherent "
        "style direction. The palette must come from the photos when photos are present: "
        "dominant wall tone first, then floor, then the main upholstery colour, then two accents.\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ANALYSIS:\n{json.dumps(analysis.model_dump(include={'intent', 'rooms', 'keywords', 'architecture'}), default=str)}\n\n"
        f"ITEMS SEEN:\n{json.dumps(spotted)}\n\n"
        f"AVAILABLE MATERIALS (choose ids from this list only):\n{json.dumps(catalog)}\n\n"
        "Rules:\n"
        "- name: snake_case, 2-4 words, e.g. modern_warm_minimal.\n"
        f"- tags: 3-6 from: {', '.join(vocab.style_tags(vertical))}.\n"
        "- palette: exactly 5 hex colours in the order wall, floor, upholstery, accent, accent.\n"
        "- materials: 4-8 ids covering at least one floor, one wall and one fabric material.\n"
        f"- lighting_mood: one of {', '.join(vocab.LIGHTING_MOODS)}.\n"
        "- description: one sentence a client would understand.\n"
    )


def objects_prompt(
    analysis: DesignAnalysis,
    style: StyleSpec,
    bundle: InputBundle,
    catalog: list[dict[str, Any]] | None = None,
) -> str:
    vertical = vocab._v(bundle.vertical)
    rooms = [
        {"room_id": r.room_id, "name": r.name, "type": r.type, "width_m": r.width_m, "length_m": r.length_m}
        for r in analysis.rooms
    ]
    # `reference` items are deliberately withheld. They were read from shop or
    # inspiration photos, and the planner's instruction is "keep every one" —
    # offer it four mattresses and it will dutifully furnish a bedroom with
    # four beds. They still reach the style stage, which reads the whole
    # analysis, so the palette and materials they carry are not lost.
    spotted = [
        {
            "spotted_index": i,
            **s.model_dump(include={"name", "family", "semantic_type", "placement", "support", "room_id", "count",
                                    "material", "color", "approx_dimensions", "notes"}),
        }
        for i, s in enumerate(analysis.spotted_objects)
        if s.role == "place"
    ]
    return (
        "You are the furniture-planning agent of an interior design pipeline. Decide WHAT goes in "
        "each room; never give coordinates (a spatial planner places things later).\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ROOMS:\n{json.dumps(rooms)}\n\n"
        f"STYLE:\n{json.dumps(style.model_dump(include={'name', 'tags', 'palette', 'lighting_mood'}))}\n\n"
        f"ITEMS SEEN IN PHOTOS OR REQUESTED (keep every one; carry its spotted_index):\n{json.dumps(spotted)}\n\n"
        + (
            "ASSET LIBRARY — what this studio can already render. `model: true` means a real 3D "
            "model exists and the piece will look like furniture; `model: false` means only a "
            "parametric primitive exists and the piece renders as a plain block.\n"
            f"{json.dumps(catalog)}\n\n"
            if catalog
            else ""
        )
        + "Rules:\n"
        "- Every item above appears in the plan with priority 1, from_photo true when seen, its "
        "spotted_index, its name, family, placement and support carried over. Then complete each room "
        "with what the style needs (spotted_index -1).\n"
        f"- semantic_type: the closest of {', '.join(t for t in vocab.semantic_types(vertical) if t != 'other')} or 'other'.\n"
        f"- family: one of {', '.join(vocab.FAMILIES)}. placement: floor | wall | ceiling | on_surface.\n"
        "- support_key: for on_surface items, the object_key of the item it rests on (same room); else ''.\n"
        "- room_id must be one of the ROOMS ids.\n"
        "- object_key: '<room_id>.<semantic_type>.<n>' unique per item.\n"
        "- priority: 1 essential, 2 recommended, 3 optional. Small rooms get fewer items.\n"
        "- count: identical copies (e.g. 2 bedside tables, 6 dining chairs).\n"
        "- approx_dimensions: [width, height, depth] in metres, realistic for the room size.\n"
        "- relation: how a floor item sits relative to another item's object_key in the same room, "
        "type one of in_front_of, beside, facing, under, around; or against_wall with no target.\n"
        "- color_hint: a hex colour for the piece taken from the photos or the palette.\n"
        "- material_hint: fabric | wood | metal | glass | stone.\n"
        + _PLANNING_RULES[vertical]
        + "- unique: true for a bespoke or sculptural piece no catalog would have (a carved secretary, an ornament).\n"
        + (
            "- When you ADD a piece the brief never asked for, prefer a semantic_type the ASSET "
            "LIBRARY marks `model: true`, and size it near that entry's dimensions. A modelled "
            "piece reads as furniture; an unmodelled one reads as a box, so a well-chosen chair "
            "beats an unrenderable chaise. This applies to your own additions only — never drop "
            "or substitute something the photos or the brief actually asked for.\n"
            "- unique stays reserved for genuinely bespoke pieces. Do not set it merely because "
            "the library lacks the type; that decision belongs to the asset stage.\n"
            if catalog
            else ""
        )
    )


# Stable Diffusion's CLIP text encoder hard-truncates at 77 tokens. The Gemini
# scene prompt is ~330 and loses everything after the first sentence — palette,
# lighting and composition all silently discarded. This builds a compact,
# comma-weighted phrase instead, the form SD actually responds to.
# The last four terms do real work. IP-Adapter conditions on a photo of one
# piece of furniture, and left alone the model happily returns another photo of
# one piece of furniture — a catalogue shot filling the frame, no room around
# it. Naming that failure here pushes against it from the other side of the
# prompt while the furniture list below pulls towards a furnished room.
SD_NEGATIVE = (
    "text, watermark, logo, label, people, collage, grid, swatches, "
    "blurry, distorted, deformed, lowres, cartoon, cluttered, "
    "close-up, product photo, single piece of furniture, furniture catalogue shot"
)


def _scene_furniture(analysis: DesignAnalysis, room) -> str:
    """The pieces the room should be furnished with, essentials first.

    Reuses ROOM_SETS — the same per-room, per-vertical set the rule-based
    planner lays out — so the moodboard promises a room the later stages can
    actually build, rather than a second opinion about what belongs in it.
    Pieces the reading actually saw come first: those are the ones the client
    owns, and the ones IP-Adapter is simultaneously conditioning on.

    Kept to five. CLIP truncates at 77 tokens, and a long list of nouns costs
    the framing and lighting words at the end of the prompt, which are what
    stop the render becoming a close-up in the first place.
    """
    from .mock_provider import ROOM_SETS      # local: keeps the prompts module leaf-like

    room_type = getattr(room, "type", "") or "living_room"
    planned = [t for t, priority, _ in ROOM_SETS.get(room_type, []) if priority <= 2]
    if not planned:
        return ""
    room_id = getattr(room, "room_id", None)
    seen = [s.semantic_type for s in analysis.spotted_objects
            if s.room_id == room_id and s.semantic_type in planned]
    ordered = list(dict.fromkeys(seen + planned))[:5]
    words = [t.replace("_", " ") for t in ordered]
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0]


# Asking the reading model to write the image prompt, instead of joining a
# keyword list with commas. The engine is SD 1.5 behind CLIP, so the brief is
# unusually specific about length and about what actually survives encoding.
ROOM_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}

CLIP_WINDOW = 77                     # hard: CLIP silently truncates past this
ROOM_PROMPT_MAX_TOKENS = 70          # what we ask for, leaving headroom
# Asked-for word budget. Measured: at "~45 words" Gemini came back over the
# CLIP window on 2 of 5 rooms (112 and 95 tokens) and both had to fall back to
# the template. Models overshoot a stated budget, so the ask is set well under
# what the window allows rather than at it.
ROOM_PROMPT_MAX_WORDS = 34

# The framing clause is ours, not the model's. Measured: asked to include it,
# the model wrote "wide angle interior render" and spent the rest of its budget
# on adjectives — and the bathroom came back as a close-up of the bathtub. It is
# appended verbatim to every composed prompt so the framing cannot be dropped,
# and the word budget above is cut to pay for it.
FRAMING_TAIL = "wide angle, whole room, far from the subject, two walls and floor visible"

# Fixtures a room needs in the PICTURE but the 3D planner has no semantic type
# for, so ROOM_SETS cannot offer them. A moodboard image is a photograph, not a
# plan: it can show a toilet and a shower even though nothing will place one.
# Without this the bathroom prompt named only vanity, mirror and bathtub —
# everything SEMANTIC_TYPES knows — and read as a tub in an alcove.
PICTURE_ONLY_FIXTURES: dict[str, str] = {
    "bathroom": "toilet, basin, walk-in shower with a glass screen, towel rail",
    "kitchen": "sink, hob and oven, extractor, upper cabinets",
}


def room_prompt_request(analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle, room) -> str:
    """Ask the intelligence layer to compose one room's image prompt.

    Deliberately hands over ONLY this room: its own pieces, the shared style,
    and the brief. Passing the whole reading is how another room's furniture
    ends up in the picture — the same leak the per-room reference chooser was
    fixed for.
    """
    mine = [
        {k: v for k, v in s.model_dump(include={"name", "semantic_type", "material", "color"}).items() if v}
        for s in analysis.spotted_objects
        if s.room_id == room.room_id and s.role == "place"
    ]
    staples = _scene_furniture(analysis, room)
    fixtures = PICTURE_ONLY_FIXTURES.get(room.type, "")
    return (
        "You write prompts for a Stable Diffusion 1.5 interior render. "
        'Return JSON {"prompt": "..."}.\n\n'
        f"ROOM: {room.name} ({room.type.replace('_', ' ')}), "
        f"{room.width_m:.1f} x {room.length_m:.1f} m.\n"
        f"THE CLIENT'S OWN PIECES HERE: "
        f"{json.dumps(mine) if mine else 'none photographed'}\n"
        f"PIECES THE ROOM STILL NEEDS: {staples or 'use your judgement'}\n"
        + (f"ALSO SHOW, the room is not complete without them: {fixtures}\n" if fixtures else "")
        + f"STYLE: {', '.join(style.tags) or 'modern, warm'}; "
        + f"materials {', '.join(style.materials) or 'wood, plaster'}; "
        + f"light {style.lighting_mood.replace('_', ' ')}\n"
        + f"BRIEF: {(bundle.description or analysis.intent)[:300]}\n\n"
        + "RULES\n"
        + f"- HARD LIMIT {ROOM_PROMPT_MAX_WORDS} words. Over that and the prompt "
        "is discarded for the keyword template. Count them.\n"
        "- Do NOT write camera or framing words (wide angle, whole room, eye "
        "level, shot, view, render). They are appended for you — spend every "
        "word on what is IN the room instead.\n"
        "- One flowing phrase of comma-separated clauses, not a list.\n"
        "- Name every piece listed above that a person would notice on walking "
        "in, the client's own pieces first.\n"
        "- Describe materials and light in words; CLIP cannot read hex codes.\n"
        "- Only this room. Never mention another room's furniture.\n"
        "- No camera brands, no artist names, no quality tokens."
    )


log = logging.getLogger("aether.intelligence.prompts")


_TOKENIZER: Any = None


@lru_cache(maxsize=1)
def _rules_fingerprint() -> str:
    """Hash of the instructions handed to the model, taken from the source of
    the two functions that build a prompt. Source-derived so that editing a
    rule invalidates old images automatically — nobody has to remember."""
    import inspect

    try:
        text = inspect.getsource(room_prompt_request) + inspect.getsource(scene_prompt_sd)
    except (OSError, TypeError):                       # frozen/zipped install
        return "nosource"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def scene_recipe_version() -> str:
    """A short hash of everything that decides what a room image looks like.

    Stored beside each generated image. When the recipe changes — the framing
    clause, the fixture vocabulary, the rules handed to the model, the negative
    prompt, the render size or the reference strength — the hash changes, and
    every image made under the old recipe becomes detectably stale.

    Without this, staleness was invisible: an image written after a code change
    can still predate it, because the server loads code once at start-up. File
    timestamps actively mislead — a bathroom image newer than prompts.py was
    produced by a process that started ten minutes before the change landed.

    Deliberately content-derived rather than a number someone must remember to
    bump: the failure mode of a manual version is forgetting it, which returns
    us to exactly the silent staleness this exists to end.
    """
    from ..core.config import get_settings

    settings = get_settings()
    material = "|".join([
        "v1",
        FRAMING_TAIL,
        SD_NEGATIVE,
        repr(sorted(PICTURE_ONLY_FIXTURES.items())),
        str(ROOM_PROMPT_MAX_WORDS),
        str(ROOM_PROMPT_MAX_TOKENS),
        _rules_fingerprint(),
        f"{settings.scene_image_width}x{settings.scene_image_height}",
        str(settings.scene_image_steps),
        str(settings.scene_image_reference_scale),
        settings.scene_image_model,
    ])
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def _clip_tokens_estimate(text: str) -> int:
    """Word-based fallback when the real tokenizer is unavailable.

    Measured against CLIP on real prompts it over-counts by 6-20 %, which is
    not the safe direction it looks like: it scored the keyword template at 81
    against a true 70 and rejected composed prompts that fit comfortably. Kept
    only so this module works without the image stack installed.
    """
    return int(len(text.split()) * 1.3) + sum(text.count(c) for c in ",.;:()") + 2


def clip_tokens(text: str) -> int:
    """How many tokens CLIP will actually make of this, measured not guessed.

    CLIP's window is the real constraint on an SD prompt and a guess is no
    better than the thing it guards: an over-count silently throws away good
    prompts, an under-count silently loses the end of one. The tokenizer is
    already a dependency of the image stack, costs one lazy load, and is then
    cached for the life of the process.
    """
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            from transformers import CLIPTokenizer

            _TOKENIZER = CLIPTokenizer.from_pretrained("openai/clip-vit-base-patch32")
        except Exception as exc:                       # noqa: BLE001
            log.warning("CLIP tokenizer unavailable (%s); falling back to the word estimate", exc)
            _TOKENIZER = False
    if _TOKENIZER is False:
        return _clip_tokens_estimate(text)
    return len(_TOKENIZER(text)["input_ids"])


def compose_room_prompt(provider, analysis: DesignAnalysis, style: StyleSpec,
                        bundle: InputBundle, room) -> tuple[str, str]:
    """This room's image prompt, and where it came from ("llm" or "template").

    Asks the intelligence layer to write it; falls back to the keyword template
    when the provider has no such capability, returns nothing, or returns
    something CLIP would truncate. The source is returned rather than hidden, so
    the moodboard can say which one it used.
    """
    compose = getattr(provider, "compose_scene_prompt", None)
    if callable(compose):
        try:
            text = " ".join((compose(analysis, style, bundle, room) or "").split())
        except Exception as exc:                       # noqa: BLE001
            log.exception("%s: composed prompt failed", room.room_id)
            text = ""
        if text:
            # The framing is appended, never left to the model. Asked to write
            # it, the model produced "wide angle interior render" and the
            # bathroom came back as a close-up of the bathtub.
            text = f"{text.rstrip(' .,')}, {FRAMING_TAIL}"
        if text and clip_tokens(text) <= CLIP_WINDOW:
            return text, "llm"
        if text:
            log.warning("%s: composed prompt is %d CLIP tokens (limit %d); using the template",
                        room.room_id, clip_tokens(text), CLIP_WINDOW)
    return scene_prompt_sd(analysis, style, bundle, room), "template"


#: The mirror image of SD_NEGATIVE. A room render must NOT be a product shot;
#: an element image must be NOTHING BUT one. Everything that makes a room a
#: room is unwanted here, and so is a second object.
ELEMENT_NEGATIVE = (
    "room, interior, wall, floor, window, curtain, rug, plant, multiple objects, "
    "two pieces, pair, set, collage, grid, text, watermark, logo, label, people, "
    "hands, blurry, distorted, deformed, lowres, cartoon, cropped, cut off, close-up"
)


def element_prompt_sd(semantic_type: str, canonical_name: str = "", material: str = "",
                      style_tags: Optional[list[str]] = None) -> str:
    """A <=77-token prompt for one isolated piece on a neutral ground.

    Words that carry weight in SD: the material name and the piece's own name.
    A hex colour carries none, so it is not sent; when the piece was
    photographed, its colour reaches the render through IP-Adapter on the crop
    instead. The framing words are the counterweight to that conditioning,
    which otherwise reproduces the crop's context along with its object.
    """
    what = (canonical_name or semantic_type.replace("_", " ")).strip()
    kind = semantic_type.replace("_", " ")
    if kind not in what:
        what = f"{what} {kind}"
    material = (material or "").strip().replace("_", " ")
    tags = ", ".join((style_tags or [])[:2]).replace("_", " ")
    parts = [
        f"product photo of a single {material + ' ' if material else ''}{what}",
        tags,
        "isolated on a plain light grey studio background, centered, entire piece in frame",
        "three-quarter view, soft even studio lighting, photorealistic, sharp focus",
    ]
    return ", ".join(p for p in parts if p)


def scene_prompt_sd(analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle, room=None) -> str:
    """A <=77-token prompt for a local Stable Diffusion render.

    Deliberately terse and keyword-led. The client's actual furniture does NOT
    come from this text — it reaches the image through IP-Adapter conditioning
    on the reference photo, because no 77-token prompt can describe a specific
    sofa. This only has to establish room, style, materials and light.
    """
    # `room` is the room being painted. It defaults to the first for callers
    # that still want a single hero image.
    room = room or (analysis.rooms[0] if analysis.rooms else None)
    where = (room.type.replace("_", " ") if room else "living room")
    style_words = ", ".join((style.tags or ["modern", "warm"])[:3]).replace("_", " ")
    mood = style.lighting_mood.replace("_", " ")

    # Material names carry more visual weight in SD than hex codes, which it
    # cannot read at all.
    materials = ", ".join(m.replace("_", " ") for m in (style.materials or [])[:2])

    furniture = _scene_furniture(analysis, room)

    parts = [
        f"photo of a {style_words} {where}",
        f"furnished with {furniture}" if furniture else "",
        materials,
        f"{mood} from a window",
        # "whole room" and "far from the subject" are the counterweight to
        # IP-Adapter, which carries the reference's framing as well as its
        # object and will otherwise reproduce a close-up of one sofa.
        "wide angle, whole room, far from the subject, eye level, two walls and floor visible",
        "photorealistic interior photography, lived-in, natural light",
    ]
    return ", ".join(p for p in parts if p)


# ── real-world size of each piece ─────────────────────────────────────────

ELEMENT_DIMENSIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "width_m": {"type": "number"},
                    "height_m": {"type": "number"},
                    "depth_m": {"type": "number"},
                    "sure": {"type": "boolean"},
                },
                "required": ["ref", "width_m", "height_m", "depth_m", "sure"],
            },
        }
    },
    "required": ["items"],
}


def element_dimensions_prompt(room, elements, vertical) -> str:
    """Ask how big each piece really is, in metres.

    A generated mesh arrives in arbitrary units and is scaled at ingest to
    `expected_dimensions`. Those came from a per-type table, so every bed was
    1.6 x 0.55 x 2.05 m whether the picture showed a single or a king, and a
    wall mirror was always 0.8 x 1.2 m. One table cannot describe a specific
    piece in a specific room.

    Asked per room and in one call, because the room's own size is most of the
    evidence: a wardrobe in a 2.5 m bathroom is not the wardrobe in a 4 m
    bedroom, and the pieces constrain each other.

    `sure` matters more than the numbers. An unsure answer is dropped by the
    caller in favour of the table, which is merely generic - where a confident
    wrong answer would scale a mesh to something absurd and place it anyway.
    """
    lines = [
        "You are estimating the REAL size of furniture seen in a photograph of "
        "one room, so each piece can be built to scale in 3D.",
        "",
        f"ROOM: {room.name} ({room.type.replace('_', ' ')}), "
        f"{room.width_m:.1f} x {room.length_m:.1f} m, ceiling {room.height_m:.1f} m.",
        "",
        "PIECES, each with the label it was given and how much of the frame it fills:",
    ]
    for el in elements:
        box = el.bbox or (0.0, 0.0, 0.0, 0.0)
        w_frac, h_frac = box[2] - box[0], box[3] - box[1]
        lines.append(
            f"- ref={el.element_id} · {el.name or el.semantic_type} "
            f"({el.semantic_type.replace('_', ' ')}) · fills {w_frac:.0%} of the width "
            f"and {h_frac:.0%} of the height of the picture · sits on the {el.placement}"
        )
    lines += [
        "",
        "For each, give width_m, height_m and depth_m as a real object in this room:",
        "- width is side to side, height is floor to top, depth is front to back.",
        "- Give the size the PIECE would really be, not the size it looks in the",
        "  picture: a photograph has no depth and does not obey the room's size.",
        "- They must fit in this room together, and be sane against each other.",
        "- sure: false if the piece is cut off, hidden, or you are guessing.",
        "  A false here is respected - a generic size is used instead, which is",
        "  a better outcome than a confident wrong one.",
    ]
    return "\n".join(lines)


# ── checking one crop on its own ──────────────────────────────────────────

ELEMENT_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "sees": {"type": "string"},
        "semantic_type": {"type": "string"},
        "fills_frame": {"type": "boolean"},
        "certain": {"type": "boolean"},
    },
    "required": ["sees", "semantic_type", "fills_frame", "certain"],
}


def element_check_prompt(room_type: str, vertical) -> str:
    """Ask what a single crop shows, WITHOUT naming what we think it shows.

    The defect this exists for is a box that is structurally perfect and around
    the wrong thing: a floor plank returned as "table lamp", a bed returned as
    "rug", the whole kitchen returned as "kitchen counter". No geometric guard
    can see that, because the geometry is fine.

    Asked "is this a table lamp?" a vision model agrees, so the expected label
    is deliberately absent from this prompt and the crop arrives with no scene
    around it. The caller compares the answer to the label instead. Same reason
    the scene read is not allowed to grade its own work.

    `fills_frame` catches the whole-room box: a crop of one piece has one piece
    in it, and a crop of half a kitchen does not.
    """
    types = ", ".join(sorted(vocab.semantic_types(vertical))[:60])
    room = room_type.replace("_", " ")
    return "\n".join([
        f"This is a small crop cut out of a photograph of a {room}.",
        "",
        "Answer only from what is in this image:",
        "- sees: the single main thing in it, plainly: 'wooden side table',",
        "  'bare floorboards', 'a corner of a bed'. If it is mostly floor, wall",
        "  or empty space, say so - do not name furniture at the edges.",
        f"- semantic_type: the closest of: {types}. Use 'other' if none fit.",
        "- fills_frame: true if ONE piece of furniture or fitting takes up most",
        "  of this image. False if it is a wide view holding several things, or",
        "  is mostly background.",
        "- certain: false if the crop is too tight, too blurred or too partial",
        "  to tell what the thing is.",
    ])


# ── reading the approved moodboard back out ──────────────────────────────

REFERENCE_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        # REQUIRED so the model commits to a class instead of omitting the
        # field and leaving the caller to guess - the same lesson as `against`
        # and `faces` below. An honest "uncertain" is a valid answer; silence
        # is not.
        "reference_class": {
            "type": "string",
            "enum": ["exact_object", "design_reference", "style_reference",
                     "inspiration_only", "uncertain"],
        },
        "object_name": {"type": "string"},
        "object_category": {"type": "string"},
        "room_hint": {"type": "string"},
        "color_words": {"type": "array", "items": {"type": "string"}},
        "color_hex": {"type": "string"},
        "material": {"type": "string"},
        "upholstery": {"type": "string"},
        "pattern": {"type": "string"},
        "frame_finish": {"type": "string"},
        "style_descriptors": {"type": "array", "items": {"type": "string"}},
        "visual_descriptors": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    # P15: the attribute fields are REQUIRED, the same lesson `against` and
    # `faces` taught in SCENE_READING_SCHEMA below. Left optional, flash-lite
    # simply omitted them: MEASURED at frame_finish 0/8, color_words 1/8 and
    # pattern 1/8 on 8 real photographs. Required, the same 8 images give
    # frame_finish 2/8 (both genuinely visible), color_words 8/8, pattern 8/8,
    # with zero false positives. A required field can still come back empty,
    # which the caller reads as "nothing to say"; an absent one cannot be told
    # apart from a field the model never considered.
    # Measured: docs/benchmarks/p15_reference_extraction.json
    "required": ["reference_class", "confidence", "material", "upholstery", "frame_finish",
                 "color_words", "color_hex", "pattern", "visual_descriptors",
                 "style_descriptors"],
}


def reference_classification_prompt(description: str, vertical) -> str:
    """Read ONE reference photo: what did the client mean by showing it?

    One photo per call on purpose. Batched onto a single call the model's
    attribute extraction thins out as images accumulate (measured:
    docs/benchmarks/p11_reference_capacity.json), and worse, nothing ties an
    attribute back to the picture that justified it.

    The class matters more than the description: "the sofa I own" and "a mood I
    like" are different instructions, and the whole failure this phase exists
    to fix is the two being indistinguishable by the time an asset is chosen.
    So the prompt spells out the consequence of each class and says plainly
    that guessing costs more than admitting uncertainty.

    P15 rewrote the attribute half. The old wording invited omission ("leave a
    field out otherwise") and the model took it: on 8 real photographs it filled
    `frame_finish` 0 times, `color_words` once and `pattern` once, putting the
    frame information into `visual_descriptors` instead ("wooden frame", "gold
    accent trim"). Three variants were run over those same 8 images and scored
    against ground truth read off the pictures; this is the winner, measured at
    extraction fidelity 0.96 with zero false positives and zero invented hex
    values. The part-by-part inspection order and the explicit "a mattress has
    no frame" instruction both earn their place: four of the eight images are
    mattresses, and they are what keeps a frame-hunting prompt honest.

    Measured: docs/benchmarks/p15_reference_extraction.json
    """
    types = ", ".join(sorted(vocab.semantic_types(vertical))[:60])
    lines = [
        "You are classifying ONE reference image a client uploaded for an interior design project.",
        "Return JSON describing what this image is FOR.",
        "",
        f"THE CLIENT'S BRIEF: {description.strip()[:600] or '(none given)'}",
        "",
        "CHOOSE EXACTLY ONE reference_class:",
        "  exact_object     - a specific piece the client owns or wants exactly. It WILL be "
        "built into their 3D room. Only choose this if one piece is clearly the subject.",
        "  design_reference - the look for a piece of that kind (this colour, this material). "
        "It shapes the piece we choose or make, but is not copied literally.",
        "  style_reference  - an overall mood, palette or material direction. It influences "
        "colours and materials and creates NO furniture by itself.",
        "  inspiration_only - saved for feel only. It creates nothing and changes nothing.",
        "  uncertain        - you cannot tell. ALWAYS choose this rather than guessing.",
        "",
        "An exact_object or design_reference MUST name object_category from this list, or you "
        "must answer uncertain instead:",
        f"  {types}",
        "",
        "FILL THE STRUCTURED FIELDS. Downstream systems read ONLY the structured fields - "
        "a detail written into visual_descriptors and nowhere else is lost.",
        "Answer every field. Use an empty string or empty list when the image does not "
        "support an answer: empty is a correct, expected answer and is always better than "
        "a guess.",
        "",
        "  material           - the primary/body surface material, when independently "
        "visible: wood, marble, glass, metal, stone, leather. Leave empty for a fully "
        "upholstered piece.",
        "  upholstery         - the soft covering: linen, velvet, boucle, leather, cotton, "
        "knit fabric. This is NOT the same field as material.",
        "  frame_finish       - the finish of the visible structural frame, base, legs, "
        "arms or trim.",
        "  color_words        - the visible colours in plain words, e.g. ['sage green', "
        "'warm beige']. Always words, never a hex code.",
        "  color_hex          - #RRGGBB ONLY if an exact shade is genuinely certain. Do NOT "
        "convert a colour word into a hex value. Empty is almost always right.",
        "  pattern            - ONLY an actually visible pattern: 'vertical stripes', "
        "'floral', 'geometric', 'herringbone', 'quilted'. Not a style, not a mood.",
        "  style_descriptors  - design idiom, e.g. ['japandi', 'mid-century']",
        "  visual_descriptors - remaining visible detail that fits no field above, "
        "e.g. ['low back', 'rounded arms']",
        "  room_hint          - the room it belongs in, if the image makes that clear",
        "",
        "INSPECT THE PIECE IN PARTS, in this order, before answering:",
        "  1. the whole object        5. the arms",
        "  2. the main body           6. the legs or base",
        "  3. the upholstered areas   7. the trim and accent regions",
        "  4. the structural frame    8. surface, colour, pattern",
        "",
        "Keep these four apart. They are different fields: the body material, "
        "the upholstery, the structural frame finish, the trim/accent finish.",
        "",
        "FRAME FINISH is the field most often lost. If you can see the material or finish "
        "of a frame, structural frame, armrest, structural arm, leg, base, trim or accent "
        "trim, put it in frame_finish. Do not leave it only in visual_descriptors. You may "
        "ALSO keep the descriptive phrase in visual_descriptors for traceability.",
        "  'wooden frame'         -> frame_finish: 'wood'",
        "  'wooden armrests'      -> frame_finish: 'wood'",
        "  'black metal frame'    -> frame_finish: 'black metal'",
        "  'gold metal trim'      -> frame_finish: 'gold metal'",
        "  'brass trim'           -> frame_finish: 'brass'",
        "  'blackened metal base' -> frame_finish: 'blackened metal'",
        "",
        "But ONLY when you can actually see it. Many pieces have no visible frame at all - "
        "an upholstered piece on a hidden or skirted base, or a mattress, has no frame, and "
        "frame_finish must then be empty. Never assume a frame exists because pieces of "
        "this kind usually have one.",
        "",
        "Say what you can see, not what you can identify. Generic wood grain is 'wood'; "
        "call it 'walnut' or 'oak' only if the image truly shows that species. The same "
        "restraint applies to every field.",
        "",
        "confidence is 0.0-1.0 for the CLASS you chose. Below 0.25 is treated as uncertain, "
        "so use a low number honestly rather than inflating it.",
    ]
    return "\n".join(lines)


SCENE_READING_SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "semantic_type": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "integer"}},
                    "material": {"type": "string"},
                    "color": {"type": "string"},
                    "placement": {"type": "string"},
                    "against": {"type": "string"},
                    "faces": {"type": "string"},
                    # P22: the picture's own frame, which the model answers in
                    # readily (30 of 30 `against` answers were camera-relative
                    # before the prompt forbade it). The plan adopts this frame
                    # per room, so here it is asked for on purpose, as numbers.
                    "wall": {"type": "string", "enum": ["back", "left", "right", "front", "none"]},
                    "along": {"type": "integer"},
                    "depth": {"type": "integer"},
                    "height": {"type": "integer"},
                    "facing": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                # `against` and `faces` are REQUIRED so the model actually
                # answers them. Left optional, flash-lite simply omitted both on
                # every element of every room - 0 of 26 - and the arrangement
                # intent the planner was built to use never existed. A required
                # field can still come back empty or unsure, which the caller
                # treats as "no hint"; an absent one cannot be told apart from
                # "the model had nothing to say".
                "required": ["name", "semantic_type", "bbox", "against", "faces",
                             "wall", "along", "depth", "facing"],
            },
        },
        "surfaces": {
            "type": "object",
            "properties": {
                "wall_color": {"type": "string"},
                "wall_material": {"type": "string"},
                "floor_color": {"type": "string"},
                "floor_material": {"type": "string"},
                "notes": {"type": "string"},
                # P22: finish zones per named wall, so tiles to waist height
                # and paint above, or a feature wall, survive the reading.
                "walls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "wall": {"type": "string", "enum": ["back", "left", "right", "front"]},
                            "material": {"type": "string"},
                            "color": {"type": "string"},
                            "pattern": {"type": "string"},
                            "span": {"type": "array", "items": {"type": "integer"}},
                            "band": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["wall", "material", "span", "band"],
                    },
                },
            },
        },
    },
    "required": ["elements"],
}


def scene_reading_prompt(room, style: StyleSpec, vertical) -> str:
    """Read one APPROVED room image back into elements and surfaces.

    The inverse of the moodboard prompt: the client agreed to that picture, so
    the picture is now the brief. Every piece is boxed so its crop can become a
    mesh; walls and floor are described as MATERIALS because room geometry stays
    procedural — Blender builds it from the room boundary, which keeps doors
    aligned and lets the validator prove nothing blocks a doorway.

    Positions are asked for in words, not coordinates. A 2D render has no depth
    and does not obey the room's real size — the bathroom render is a long spa,
    the room is 2.5 x 2.0 m — so it is intent for the planner, never metres.
    """
    types = ", ".join(sorted(vocab.semantic_types(vertical))[:60])
    lines = [
        "You are reading a rendered interior so it can be rebuilt in 3D.",
        'Return JSON {"elements": [...], "surfaces": {...}}.',
        "",
        f"ROOM: {room.name} ({room.type.replace('_', ' ')}), "
        f"{room.width_m:.1f} x {room.length_m:.1f} m.",
        f"STYLE: {', '.join(style.tags) or 'modern'}",
        "",
        "FOR EVERY DISTINCT PIECE OF FURNITURE OR FITTING YOU CAN SEE:",
        "- name: what it is, plainly ('low oak sideboard', 'freestanding bath')",
        f"- semantic_type: the closest of: {types}. Use 'other' if none fit.",
        # Whole numbers out of 1000, not fractions. Asked for "fractions,
        # 0-1" the model mixed the two conventions inside a single box in
        # a third of cases - and per axis: x as 0-1 beside y as 0-1000,
        # e.g. [0.0, 483, 1.0, 936]. One integer convention removes the
        # choice; a decimal point is then self-evidently wrong.
        "- bbox: [x0, y0, x1, y1] as WHOLE NUMBERS out of 1000 measured from",
        "  the top-left corner, e.g. [402, 237, 806, 712]. Never decimals,",
        "  never 0-1 fractions. x0 < x1 and y0 < y1 always.",
        "  Keep it tight: the box is cut out and turned into a 3D model, so",
        "  one that catches the wall or a neighbour produces a wrong mesh.",
        "- material and color (hex if you can judge it)",
        "- placement: floor, wall, ceiling or on_surface",
        # P22: the picture's frame, deliberately. `against`/`faces` below must
        # name pieces because a direction alone cannot be mapped onto the
        # plan; these four CAN, because the plan adopts the picture's frame
        # for the room: the wall you look at is its back wall. Whole numbers
        # out of 1000, same convention as bbox, for the same reason.
        "- wall: the wall this piece stands against or hangs on, IN THE",
        "  PICTURE'S FRAME: 'back' is the wall you are looking at, 'left' and",
        "  'right' are the picture's left and right, 'front' is behind the",
        "  camera. 'none' if it stands free of every wall.",
        "- along: where it is from left to right across the room, as a WHOLE",
        "  NUMBER out of 1000 (0 = touching the left wall, 1000 = the right).",
        "- depth: how far it is from the back wall towards the camera, 0-1000",
        "  (0 = touching the back wall, 1000 = nearest the camera).",
        "- height: for wall and ceiling pieces, the height of its bottom edge",
        "  above the floor, 0-1000 of the ceiling. 0 for anything on the floor.",
        "- facing: the way its front is turned, in the picture's frame:",
        "  'back', 'left', 'right', 'front' (towards the camera), 'up', 'down',",
        "  or the NAME of the piece it is turned towards if that is clearer.",
        # Both of these must NAME something. Asked for them "in words" the
        # model answered in the camera's frame on every element of both sample
        # projects - "left wall", "back wall", "front", "right", "up" - and the
        # planner discards those, correctly: a render has no fixed left or back
        # against the floor plan. Measured on the two stored readings: 30 of 30
        # `against` values and 30 of 30 `faces` values were camera-relative, so
        # the whole arrangement-hint path did nothing in production. Naming a
        # thing survives the translation; naming a direction cannot.
        # Measured over five fresh reads: offering "into the room" beside the
        # specific answer meant the model took the easy one 10 times out of 14
        # and named a piece ZERO times, and "what it sits against" drew "floor"
        # - true, and useless, since everything stands on the floor. Both are
        # now last resorts, stated after the answer that is actually wanted.
        "- against: NAME the piece of furniture this one backs onto or stands",
        "  beside - 'the sofa', 'the kitchen island'. If it touches no piece,",
        "  answer 'wall', 'window' or 'corner'. The FLOOR IS NOT AN ANSWER:",
        "  everything stands on the floor, so it says nothing about where.",
        "  Never a direction - 'left wall' and 'back wall' are discarded,",
        "  because the floor plan has no left or back.",
        "- faces: NAME the piece this one is turned towards - 'the television',",
        "  'the dining table', 'the window'. A sofa faces a television; a chair",
        "  faces a desk. ONLY if it faces no particular piece, answer 'into the",
        "  room'. Never 'front', 'right' or 'up'.",
        "",
        "SURFACES: the wall and floor colour and material. Describe them only —",
        "they are rebuilt as geometry, not cut out.",
        "- walls: one entry per DISTINCT finish zone you can see, named by",
        "  wall in the picture's frame (back, left, right, front). A wall that",
        "  is tiled to waist height and painted above is TWO entries. Each:",
        "  material, color (hex), pattern ('herringbone', 'vertical panelling',",
        "  '' if plain), span [from, to] out of 1000 along the wall from its",
        "  left end, band [from, to] out of 1000 up from the floor. One plain",
        "  finish on every wall: a single entry per wall, span [0,1000],",
        "  band [0,1000], or leave the list empty.",
        "",
        "RULES",
        "- One entry per distinct piece. Never box the room, a wall, the floor,",
        "  the ceiling, a window or a doorway as an element.",
        # Written two-dimensionally on purpose. "smaller than a book" was
        # read as "thin", and the model dropped a towel rail it could
        # plainly see - the same mistake the 64 px-per-side crop gate made
        # with a rug seen edge-on. Long and thin is not small.
        "- Skip only specks: a tap, a knob, a soap dish, a switch. A piece",
        "  that is long but thin - a rail, a shelf, a rug seen edge-on - is",
        "  NOT small. Box it.",
        "- Do not invent pieces that are not visible in the image.",
    ]
    return "\n".join(lines)
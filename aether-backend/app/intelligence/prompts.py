"""Stage prompts and output schemas shared by every LLM provider (DPR §27).

Schemas are plain JSON Schema (the Anthropic shape). `gemini_schema()`
converts one to Gemini's OpenAPI subset. Prompts are provider-neutral text;
images are attached by each provider in its own wire format.

Schema 1.1 reads the photos with an open vocabulary: every item gets a free
`name`, a coarse `family`, where it sits (`placement` + `support`) and a
bounding box in the photo, so nothing visible is dropped for lack of a type.
"""
from __future__ import annotations

import json
from typing import Any

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


ANALYSIS_SCHEMA: dict[str, Any] = _obj(
    {
        "intent": {"type": "string"},
        "rooms": {
            "type": "array",
            "items": _obj(
                {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": vocab.ROOM_TYPES},
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

STYLE_SCHEMA: dict[str, Any] = _obj(
    {
        "name": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string", "enum": vocab.STYLE_TAGS}},
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


def analysis_prompt(bundle: InputBundle) -> str:
    hints = [h.model_dump() for h in bundle.room_hints]
    return (
        "You are the input-analysis agent of an interior design pipeline.\n"
        "Read the client's brief, the room dimensions they supplied (may be empty) and the "
        "reference photos. Extract structured facts only; do not design yet.\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ROOM DIMENSIONS SUPPLIED BY CLIENT (metres):\n{json.dumps(hints) if hints else '(none)'}\n\n"
        "Rules:\n"
        "- List every room the home needs. Use the supplied dimensions when present and set "
        "estimated=false for those; otherwise estimate generous, comfortable sizes for a modern apartment and set estimated=true. Typical: living room 5.5-6.5 m by 4.2-5.0 m (larger when it doubles as dining), master bedroom 4.5-5.0 by 4.0-4.5, other bedrooms 3.8-4.2 by 3.4-3.8, kitchen 3.6-4.2 by 2.8-3.2, dining room 4.0-4.5 by 3.4-3.8, study 3.4-3.8 by 3.0-3.4. Never go below the low end. Ceiling 3.0 m.\n"
        f"- room.type must be one of: {', '.join(vocab.ROOM_TYPES)}.\n"
        "- spotted_objects: EVERY distinct furnishing, decor piece and built-in element visible in the "
        "photos, plus anything requested in the brief. Be exhaustive (up to 40 items): sofas, tables, "
        "cabinets, lamps, plants in urns, pedestals, rugs (each layer), curtains, pillows, trays, books, "
        "vases, ornaments on brackets, art, mirrors, fireplaces. One entry per kind; use count for copies.\n"
        "  - name: short, specific, open vocabulary, e.g. 'mahogany secretary bookcase with fretwork doors', "
        "'wicker urn with fern on wicker pedestal', 'blue and white pagoda ornament'.\n"
        f"  - family: one of {', '.join(vocab.FAMILIES)}.\n"
        f"  - semantic_type: the closest of {', '.join(t for t in vocab.SEMANTIC_TYPES if t != 'other')}; "
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
        f"- keywords: style words from this list only: {', '.join(vocab.STYLE_TAGS)}.\n"
        "- confidence: 0..1 for the overall extraction.\n"
    )


def style_prompt(analysis: DesignAnalysis, bundle: InputBundle, catalog: list[dict[str, Any]]) -> str:
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
        f"- tags: 3-6 from: {', '.join(vocab.STYLE_TAGS)}.\n"
        "- palette: exactly 5 hex colours in the order wall, floor, upholstery, accent, accent.\n"
        "- materials: 4-8 ids covering at least one floor, one wall and one fabric material.\n"
        f"- lighting_mood: one of {', '.join(vocab.LIGHTING_MOODS)}.\n"
        "- description: one sentence a client would understand.\n"
    )


def objects_prompt(analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> str:
    rooms = [
        {"room_id": r.room_id, "name": r.name, "type": r.type, "width_m": r.width_m, "length_m": r.length_m}
        for r in analysis.rooms
    ]
    spotted = [
        {
            "spotted_index": i,
            **s.model_dump(include={"name", "family", "semantic_type", "placement", "support", "room_id", "count",
                                    "material", "color", "approx_dimensions", "notes"}),
        }
        for i, s in enumerate(analysis.spotted_objects)
    ]
    return (
        "You are the furniture-planning agent of an interior design pipeline. Decide WHAT goes in "
        "each room; never give coordinates (a spatial planner places things later).\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ROOMS:\n{json.dumps(rooms)}\n\n"
        f"STYLE:\n{json.dumps(style.model_dump(include={'name', 'tags', 'palette', 'lighting_mood'}))}\n\n"
        f"ITEMS SEEN IN PHOTOS OR REQUESTED (keep every one; carry its spotted_index):\n{json.dumps(spotted)}\n\n"
        "Rules:\n"
        "- Every item above appears in the plan with priority 1, from_photo true when seen, its "
        "spotted_index, its name, family, placement and support carried over. Then complete each room "
        "with what the style needs (spotted_index -1).\n"
        f"- semantic_type: the closest of {', '.join(t for t in vocab.SEMANTIC_TYPES if t != 'other')} or 'other'.\n"
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
        "- Kitchens need a kitchen_counter along the longest wall; living rooms need curtains at the window.\n"
        "- unique: true for a bespoke or sculptural piece no catalog would have (a carved secretary, an ornament).\n"
    )

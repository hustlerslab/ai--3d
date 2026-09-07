"""Stage prompts and output schemas shared by every LLM provider (DPR §27).

Schemas are plain JSON Schema (the Anthropic shape). `gemini_schema()`
converts one to Gemini's OpenAPI subset. Prompts are provider-neutral text;
images are attached by each provider in its own wire format.
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
                    "semantic_type": {"type": "string"},
                    "room_name": {"type": "string"},
                    "count": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "notes": {"type": "string"},
                }
            ),
        },
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
                    "semantic_type": {"type": "string"},
                    "room_id": {"type": "string"},
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
        "- spotted_objects: furniture and decor visible in the photos or requested in the brief. "
        f"semantic_type must be one of: {', '.join(vocab.SEMANTIC_TYPES)}. Put photo observations "
        "(colour, material, shape) in notes. room_name should match one of the rooms you listed.\n"
        "- constraints: explicit client requirements (budget, things to avoid, must-haves) as short sentences.\n"
        f"- keywords: style words from this list only: {', '.join(vocab.STYLE_TAGS)}.\n"
        "- confidence: 0..1 for the overall extraction.\n"
    )


def style_prompt(analysis: DesignAnalysis, bundle: InputBundle, catalog: list[dict[str, Any]]) -> str:
    return (
        "You are the style-interpretation agent of an interior design pipeline.\n"
        "From the brief, the extracted analysis and the reference photos, define one coherent "
        "style direction. The palette must come from the photos when photos are present: "
        "dominant wall tone first, then floor, then the main upholstery colour, then two accents.\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ANALYSIS:\n{json.dumps(analysis.model_dump(include={'intent', 'rooms', 'keywords', 'spotted_objects'}), default=str)}\n\n"
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
    spotted = [s.model_dump(include={"semantic_type", "room_id", "count", "notes"}) for s in analysis.spotted_objects]
    return (
        "You are the furniture-planning agent of an interior design pipeline. Decide WHAT goes in "
        "each room; never give coordinates (a spatial planner places things later).\n\n"
        f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
        f"ROOMS:\n{json.dumps(rooms)}\n\n"
        f"STYLE:\n{json.dumps(style.model_dump(include={'name', 'tags', 'palette', 'lighting_mood'}))}\n\n"
        f"OBJECTS REQUESTED OR SEEN IN PHOTOS:\n{json.dumps(spotted)}\n\n"
        "Rules:\n"
        f"- semantic_type must be one of: {', '.join(vocab.SEMANTIC_TYPES)}.\n"
        "- room_id must be one of the ROOMS ids.\n"
        "- object_key: '<room_id>.<semantic_type>.<n>' unique per item.\n"
        "- priority: 1 essential, 2 recommended, 3 optional. Small rooms get fewer items.\n"
        "- count: identical copies (e.g. 2 bedside tables, 6 dining chairs).\n"
        "- approx_dimensions: [width, height, depth] in metres, realistic for the room size.\n"
        "- relation: how the item sits relative to another item's object_key in the same room, "
        "type one of in_front_of, beside, facing, under, around; or against_wall with no target.\n"
        "- color_hint: a hex colour for the piece taken from the palette or the photos.\n"
        "- material_hint: fabric | wood | metal | glass | stone.\n"
        "- Every requested/seen object must appear with priority 1 and from_photo true when seen.\n"
        "- Kitchens need a kitchen_counter along the longest wall; living rooms need curtains at the window.\n"
        "- unique: true only for a bespoke piece that no catalog would have.\n"
    )

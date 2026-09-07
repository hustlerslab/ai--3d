"""Gemini vision provider: one structured call per stage (DPR §27).

Each call sends a stage-specific prompt, the reference photos inline, and a
response schema so Gemini returns JSON. The JSON is validated into the
Pydantic contract; unknown material ids or room types are coerced or
dropped with a warning rather than failing the stage. One repair retry is
attempted when the first response is not valid JSON.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from ..core.config import Settings, get_settings
from ..materials.registry import get_material_registry
from . import vocab
from .images import encode_for_gemini
from .schema import DesignAnalysis, InputBundle, ObjectPlan, RoomAnalysis, SpottedObject, StyleSpec

log = logging.getLogger("aether.intelligence.gemini")


class GeminiError(Exception):
    pass


# ── response schemas (Gemini's OpenAPI subset) ───────────────────────────

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING"},
        "rooms": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "type": {"type": "STRING", "enum": vocab.ROOM_TYPES},
                    "width_m": {"type": "NUMBER"},
                    "length_m": {"type": "NUMBER"},
                    "height_m": {"type": "NUMBER"},
                    "estimated": {"type": "BOOLEAN"},
                    "notes": {"type": "STRING"},
                },
                "required": ["name", "type", "width_m", "length_m", "estimated"],
            },
        },
        "constraints": {"type": "ARRAY", "items": {"type": "STRING"}},
        "spotted_objects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "semantic_type": {"type": "STRING"},
                    "room_name": {"type": "STRING"},
                    "count": {"type": "INTEGER"},
                    "confidence": {"type": "NUMBER"},
                    "notes": {"type": "STRING"},
                },
                "required": ["semantic_type", "confidence"],
            },
        },
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["intent", "rooms", "constraints", "spotted_objects", "keywords", "confidence"],
}

STYLE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": vocab.STYLE_TAGS}},
        "palette": {"type": "ARRAY", "items": {"type": "STRING"}},
        "materials": {"type": "ARRAY", "items": {"type": "STRING"}},
        "lighting_mood": {"type": "STRING", "enum": vocab.LIGHTING_MOODS},
        "description": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["name", "tags", "palette", "materials", "lighting_mood", "description", "confidence"],
}


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.BaseTransport] = None):
        self._settings = settings or get_settings()
        if not self._settings.gemini_configured:
            raise GeminiError("GEMINI_API_KEY is not configured")
        self._client = httpx.Client(timeout=self._settings.gemini_timeout_seconds, transport=transport)

    @property
    def _url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._settings.gemini_model}:generateContent"
        )

    # ── transport ────────────────────────────────────────────────────────
    def _generate(self, parts: list[dict[str, Any]], schema: dict[str, Any], stage: str) -> dict[str, Any]:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.2,
            },
        }
        text = self._call(body, stage)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Gemini %s returned invalid JSON (%s); asking for a repair", stage, exc)
            repair = {
                "contents": [
                    {"role": "user", "parts": parts},
                    {"role": "model", "parts": [{"text": text}]},
                    {
                        "role": "user",
                        "parts": [{"text": "That was not valid JSON. Return ONLY the corrected JSON object."}],
                    },
                ],
                "generationConfig": body["generationConfig"],
            }
            text = self._call(repair, stage + ".repair")
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc2:
                raise GeminiError(f"{stage}: response is not JSON after repair: {exc2}") from exc2

    def _call(self, body: dict[str, Any], stage: str) -> str:
        try:
            response = self._client.post(
                self._url,
                params={"key": self._settings.gemini_api_key.get_secret_value()},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise GeminiError(f"{stage}: network error: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:300].replace("\n", " ")
            raise GeminiError(f"{stage}: HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
                raise GeminiError(f"{stage}: blocked ({candidate.get('finishReason')})")
            return candidate["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise GeminiError(f"{stage}: unexpected response shape: {exc}") from exc

    def _image_parts(self, bundle: InputBundle, limit: int = 6) -> tuple[list[dict[str, Any]], list[str]]:
        parts: list[dict[str, Any]] = []
        warnings: list[str] = []
        for ref in bundle.references[:limit]:
            encoded = encode_for_gemini(ref.path)
            if encoded is None:
                warnings.append(f"could not encode {ref.filename or ref.path} for Gemini")
                continue
            mime, data = encoded
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
        if len(bundle.references) > limit:
            warnings.append(f"only the first {limit} of {len(bundle.references)} references were sent to Gemini")
        return parts, warnings

    # ── stage 5: input analysis ──────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        hints = [h.model_dump() for h in bundle.room_hints]
        prompt = (
            "You are the input-analysis agent of an interior design pipeline.\n"
            "Read the client's brief, the room dimensions they supplied (may be empty) and the "
            "reference photos. Extract structured facts only; do not design yet.\n\n"
            f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
            f"ROOM DIMENSIONS SUPPLIED BY CLIENT (metres):\n{json.dumps(hints) if hints else '(none)'}\n\n"
            "Rules:\n"
            "- List every room the home needs. Use the supplied dimensions when present and set "
            "estimated=false for those; otherwise estimate realistic Indian-apartment sizes and set estimated=true.\n"
            f"- room.type must be one of: {', '.join(vocab.ROOM_TYPES)}.\n"
            "- spotted_objects: furniture and decor visible in the photos or requested in the brief. "
            f"semantic_type must be one of: {', '.join(vocab.SEMANTIC_TYPES)}. Put photo observations "
            "(colour, material, shape) in notes. room_name should match one of the rooms you listed.\n"
            "- constraints: explicit client requirements (budget, things to avoid, must-haves) as short sentences.\n"
            f"- keywords: style words from this list only: {', '.join(vocab.STYLE_TAGS)}.\n"
            "- confidence: 0..1 for the overall extraction.\n"
        )
        images, warnings = self._image_parts(bundle)
        parts = [{"text": prompt}, *images]
        if images:
            parts.append({"text": f"{len(images)} reference photo(s) attached above."})
        raw = self._generate(parts, ANALYSIS_SCHEMA, "analyze_input")
        return _coerce_analysis(raw, bundle, warnings)

    # ── stage 5/6: style ─────────────────────────────────────────────────
    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        prompt = (
            "You are the style-interpretation agent of an interior design pipeline.\n"
            "From the brief, the extracted analysis and the reference photos, define one coherent "
            "style direction.\n\n"
            f"BRIEF:\n{bundle.description.strip() or '(none)'}\n\n"
            f"ANALYSIS:\n{json.dumps(analysis.model_dump(include={'intent', 'rooms', 'keywords', 'spotted_objects'}), default=str)}\n\n"
            f"AVAILABLE MATERIALS (choose ids from this list only):\n{json.dumps(catalog)}\n\n"
            "Rules:\n"
            "- name: snake_case, 2-4 words, e.g. modern_warm_minimal.\n"
            f"- tags: 3-6 from: {', '.join(vocab.STYLE_TAGS)}.\n"
            "- palette: 5 hex colours dominant first, taken from the photos when present.\n"
            "- materials: 4-8 ids covering at least one floor, one wall and one fabric material.\n"
            f"- lighting_mood: one of {', '.join(vocab.LIGHTING_MOODS)}.\n"
            "- description: one sentence a client would understand.\n"
        )
        images, warnings = self._image_parts(bundle)
        raw = self._generate([{"text": prompt}, *images], STYLE_SCHEMA, "create_style_spec")
        return _coerce_style(raw, {m.material_id for m in materials}, warnings)


    # ── stages 6–7: object plan ──────────────────────────────────────────
    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        rooms = [
            {"room_id": r.room_id, "name": r.name, "type": r.type, "width_m": r.width_m, "length_m": r.length_m}
            for r in analysis.rooms
        ]
        spotted = [s.model_dump(include={"semantic_type", "room_id", "count", "notes"}) for s in analysis.spotted_objects]
        prompt = (
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
            "- Every requested/seen object must appear with priority 1 and from_photo true when seen.\n"
            "- unique: true only for a bespoke piece that no catalog would have.\n"
        )
        raw = self._generate([{"text": prompt}], OBJECT_PLAN_SCHEMA, "plan_objects")
        return _coerce_object_plan(raw, analysis)


OBJECT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "object_key": {"type": "STRING"},
                    "semantic_type": {"type": "STRING"},
                    "room_id": {"type": "STRING"},
                    "priority": {"type": "INTEGER"},
                    "count": {"type": "INTEGER"},
                    "approx_dimensions": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                    "relation_type": {"type": "STRING", "enum": ["in_front_of", "beside", "facing", "under", "around", "against_wall"]},
                    "relation_target": {"type": "STRING"},
                    "style_notes": {"type": "STRING"},
                    "material_hint": {"type": "STRING"},
                    "color_hint": {"type": "STRING"},
                    "from_photo": {"type": "BOOLEAN"},
                    "unique": {"type": "BOOLEAN"},
                },
                "required": ["object_key", "semantic_type", "room_id", "priority", "count", "relation_type"],
            },
        },
        "confidence": {"type": "NUMBER"},
    },
    "required": ["items", "confidence"],
}


# ── coercion into the contracts ──────────────────────────────────────────


def _coerce_object_plan(raw: dict[str, Any], analysis: DesignAnalysis) -> ObjectPlan:
    from .schema import ObjectPlanItem, ObjectRelation

    room_ids = {r.room_id for r in analysis.rooms}
    warnings: list[str] = []
    items: list[ObjectPlanItem] = []
    keys: set[str] = set()
    for item in raw.get("items") or []:
        sem = str(item.get("semantic_type") or "").strip().lower().replace(" ", "_")
        room_id = str(item.get("room_id") or "")
        if sem not in vocab.SEMANTIC_TYPES:
            warnings.append(f"ignored unknown object type {sem!r}")
            continue
        if room_id not in room_ids:
            warnings.append(f"ignored {sem} in unknown room {room_id!r}")
            continue
        key = str(item.get("object_key") or f"{room_id}.{sem}.{len(items) + 1}")
        if key in keys:
            key = f"{key}_{len(items) + 1}"
        keys.add(key)
        dims = item.get("approx_dimensions")
        approx = None
        if isinstance(dims, list) and len(dims) == 3:
            try:
                approx = tuple(max(0.05, float(d)) for d in dims)  # type: ignore[assignment]
            except (TypeError, ValueError):
                approx = None
        rel_type = item.get("relation_type") or "against_wall"
        target = item.get("relation_target") or None
        relation = ObjectRelation(type=rel_type, target_key=None if rel_type == "against_wall" else target)
        items.append(
            ObjectPlanItem(
                object_key=key,
                semantic_type=sem,
                room_id=room_id,
                priority=max(1, min(3, int(item.get("priority") or 2))),
                count=max(1, min(12, int(item.get("count") or 1))),
                approx_dimensions=approx,
                relation=relation,
                style_notes=str(item.get("style_notes") or ""),
                material_hint=str(item.get("material_hint") or ""),
                color_hint=str(item.get("color_hint") or ""),
                from_photo=bool(item.get("from_photo", False)),
                unique=bool(item.get("unique", False)),
            )
        )
    # relations must point at keys in the same room; otherwise fall back to a wall
    by_key = {i.object_key: i for i in items}
    for it in items:
        if it.relation and it.relation.target_key:
            target = by_key.get(it.relation.target_key)
            if target is None or target.room_id != it.room_id:
                warnings.append(f"{it.object_key}: relation target {it.relation.target_key!r} not found; placed against a wall")
                it.relation = ObjectRelation(type="against_wall")
    if not items:
        warnings.append("Gemini returned no items; using the rule-based plan")
        from .mock_provider import MockProvider

        plan = MockProvider().plan_objects(analysis, StyleSpec(name="modern"), InputBundle(project_id="x"))
        plan.provider = "gemini→mock"
        plan.warnings += warnings
        return plan
    return ObjectPlan(
        rooms=[r.room_id for r in analysis.rooms],
        items=items,
        provider="gemini",
        confidence=_clamp(raw.get("confidence", 0.7)),
        warnings=warnings,
    )


def _coerce_analysis(raw: dict[str, Any], bundle: InputBundle, warnings: list[str]) -> DesignAnalysis:
    rooms: list[RoomAnalysis] = []
    seen: dict[str, int] = {}
    name_to_id: dict[str, str] = {}
    for item in raw.get("rooms") or []:
        rtype = item.get("type") if item.get("type") in vocab.ROOM_TYPES else "other"
        name = str(item.get("name") or vocab.ROOM_LABELS.get(rtype, "Room")).strip()
        base = vocab.slug(name)
        seen[base] = seen.get(base, 0) + 1
        room_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        dw, dl = vocab.ROOM_DEFAULT_DIMS.get(rtype, vocab.ROOM_DEFAULT_DIMS["other"])
        try:
            rooms.append(
                RoomAnalysis(
                    room_id=room_id,
                    name=name,
                    type=rtype,
                    width_m=float(item.get("width_m") or dw),
                    length_m=float(item.get("length_m") or dl),
                    height_m=float(item.get("height_m") or 3.0),
                    estimated=bool(item.get("estimated", True)),
                    notes=str(item.get("notes") or ""),
                )
            )
            name_to_id[name.lower()] = room_id
        except Exception as exc:  # a single bad room should not sink the stage
            warnings.append(f"dropped room {name!r}: {exc}")
    if not rooms:
        warnings.append("Gemini returned no rooms; using defaults")
        from .mock_provider import _default_rooms

        rooms = _default_rooms()

    spotted: list[SpottedObject] = []
    for item in raw.get("spotted_objects") or []:
        sem = str(item.get("semantic_type") or "").strip().lower().replace(" ", "_")
        if sem not in vocab.SEMANTIC_TYPES:
            warnings.append(f"ignored unknown object type {sem!r}")
            continue
        room_name = str(item.get("room_name") or "").lower()
        room_id = name_to_id.get(room_name)
        if room_id is None:
            default_room = vocab.OBJECT_DEFAULT_ROOM.get(sem)
            room_id = next((r.room_id for r in rooms if r.type == default_room), rooms[0].room_id)
        spotted.append(
            SpottedObject(
                semantic_type=sem,
                room_id=room_id,
                count=max(1, int(item.get("count") or 1)),
                confidence=_clamp(item.get("confidence", 0.5)),
                notes=str(item.get("notes") or ""),
            )
        )

    keywords = [k for k in (raw.get("keywords") or []) if k in vocab.STYLE_TAGS]
    return DesignAnalysis(
        intent=str(raw.get("intent") or bundle.description[:200] or "Interior design brief"),
        rooms=rooms,
        constraints=[str(c) for c in (raw.get("constraints") or [])][:12],
        spotted_objects=spotted,
        keywords=keywords,
        confidence=_clamp(raw.get("confidence", 0.7)),
        provider="gemini",
        warnings=warnings,
    )


def _coerce_style(raw: dict[str, Any], valid_materials: set[str], warnings: list[str]) -> StyleSpec:
    tags = [t for t in (raw.get("tags") or []) if t in vocab.STYLE_TAGS]
    materials = []
    for m in raw.get("materials") or []:
        if m in valid_materials:
            materials.append(m)
        else:
            warnings.append(f"ignored unknown material id {m!r}")
    mood = raw.get("lighting_mood") if raw.get("lighting_mood") in vocab.LIGHTING_MOODS else "warm_daylight"
    name = vocab.slug(str(raw.get("name") or "_".join(tags[:3]) or "modern_warm_minimal"))
    spec = StyleSpec(
        name=name,
        tags=tags or ["modern", "warm", "minimal"],
        palette=[str(p) for p in (raw.get("palette") or [])],
        materials=materials,
        lighting_mood=mood,
        description=str(raw.get("description") or ""),
        confidence=_clamp(raw.get("confidence", 0.7)),
        provider="gemini",
        warnings=warnings,
    )
    if not spec.palette:
        lead = next((t for t in spec.tags if t in vocab.STYLE_PALETTES), "modern")
        spec.palette = list(vocab.STYLE_PALETTES[lead])
        warnings.append("Gemini palette was empty or invalid; used style default")
    if not spec.materials:
        from .mock_provider import _pick_materials

        spec.materials = _pick_materials(spec.tags)
        warnings.append("Gemini chose no valid materials; picked by style tags")
    return spec


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.5

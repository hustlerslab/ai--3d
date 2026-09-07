"""Turn a provider's raw JSON into the validated contracts.

Shared by every LLM provider: unknown enum values are dropped with a
warning, room ids are made stable, relations are checked, and empty results
fall back to the rule-based planner rather than failing the stage.
"""
from __future__ import annotations

from typing import Any

from . import vocab
from .schema import (
    DesignAnalysis,
    InputBundle,
    ObjectPlan,
    ObjectPlanItem,
    ObjectRelation,
    RoomAnalysis,
    SpottedObject,
    StyleSpec,
)


def clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.5


def coerce_analysis(raw: dict[str, Any], bundle: InputBundle, warnings: list[str], provider: str) -> DesignAnalysis:
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
        warnings.append("model returned no rooms; using defaults")
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
                confidence=clamp(item.get("confidence", 0.5)),
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
        confidence=clamp(raw.get("confidence", 0.7)),
        provider=provider,
        warnings=warnings,
    )


def coerce_style(raw: dict[str, Any], valid_materials: set[str], warnings: list[str], provider: str) -> StyleSpec:
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
        confidence=clamp(raw.get("confidence", 0.7)),
        provider=provider,
        warnings=warnings,
    )
    if not spec.palette:
        lead = next((t for t in spec.tags if t in vocab.STYLE_PALETTES), "modern")
        spec.palette = list(vocab.STYLE_PALETTES[lead])
        warnings.append("model palette was empty or invalid; used style default")
    if not spec.materials:
        from .mock_provider import _pick_materials

        spec.materials = _pick_materials(spec.tags)
        warnings.append("model chose no valid materials; picked by style tags")
    return spec


def coerce_object_plan(raw: dict[str, Any], analysis: DesignAnalysis, provider: str) -> ObjectPlan:
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
        color = str(item.get("color_hint") or "").strip()
        if color and not color.startswith("#"):
            color = ""
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
                color_hint=color,
                from_photo=bool(item.get("from_photo", False)),
                unique=bool(item.get("unique", False)),
            )
        )
    by_key = {i.object_key: i for i in items}
    for it in items:
        if it.relation and it.relation.target_key:
            target_item = by_key.get(it.relation.target_key)
            if target_item is None or target_item.room_id != it.room_id:
                warnings.append(f"{it.object_key}: relation target {it.relation.target_key!r} not found; placed against a wall")
                it.relation = ObjectRelation(type="against_wall")
    if not items:
        warnings.append("model returned no items; using the rule-based plan")
        from .mock_provider import MockProvider

        plan = MockProvider().plan_objects(analysis, StyleSpec(name="modern"), InputBundle(project_id="x"))
        plan.provider = f"{provider}→mock"
        plan.warnings += warnings
        return plan
    return ObjectPlan(
        rooms=[r.room_id for r in analysis.rooms],
        items=items,
        provider=provider,
        confidence=clamp(raw.get("confidence", 0.7)),
        warnings=warnings,
    )

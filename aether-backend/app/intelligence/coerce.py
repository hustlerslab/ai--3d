"""Turn a provider's raw JSON into the validated contracts.

Shared by every LLM provider: unknown enum values are dropped with a
warning, room ids are made stable, relations are checked, and empty results
fall back to the rule-based planner rather than failing the stage.

Schema 1.1: item types are open. An unknown `semantic_type` is mapped from
the item's name (vocab.canonical_type) and otherwise kept as "other" with its
family, so a "pagoda ornament" survives as an ornament instead of vanishing.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from ..projects.schema import Vertical
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


# How far past the planner's own per-room set a count may go before the extras
# read as catalogue browsing rather than furniture. ROOM_SETS already says what
# a room of each type holds ("bedroom" → one bed); +1 keeps the honest cases —
# two sofas in a living room, a spare bed in a guest room — and only demotes
# what is clearly beyond a real room.
CAPACITY_SLACK = 1


def _capacity(room_type: str, semantic_type: str) -> Optional[int]:
    """How many of this type a room of this type plausibly holds, or None for
    no opinion (small decor: nobody is surprised by five cushions)."""
    from .mock_provider import ROOM_SETS

    for sem, _priority, count in ROOM_SETS.get(room_type, []):
        if sem == semantic_type:
            return count + CAPACITY_SLACK
    return None


def assign_ids(analysis: DesignAnalysis) -> None:
    """Give every read item a stable id, in place.

    Content-derived, not random: the same reading re-run over the same photos
    yields the same ids, so a client's place/reference decisions are not thrown
    away by a re-analysis. Genuinely identical items in the same room get an
    occurrence suffix, which is the only place position still enters — and two
    interchangeable items are the one case where that is harmless.
    """
    seen: dict[str, int] = {}
    for item in analysis.spotted_objects:
        if item.object_id:
            continue
        seed = "|".join([
            item.semantic_type, item.name, item.room_id or "",
            item.image_ref, str(item.bbox or ""),
        ])
        n = seen.get(seed, 0)
        seen[seed] = n + 1
        digest = hashlib.sha1(f"{seed}#{n}".encode("utf-8")).hexdigest()[:10]
        item.object_id = f"it_{digest}"


def assign_roles(analysis: DesignAnalysis) -> None:
    """Default each read item to `place` or `reference`, in place.

    Only items read from a photo can be demoted — anything the planner added to
    furnish the room is there because the room needs it. Within a (room, type)
    the most confident readings keep their place, so the demoted ones are the
    weakest observations rather than whichever happened to be last.

    This is a DEFAULT, not a verdict: the review screen is where the client
    settles it, because no signal available here distinguishes "four photos of
    the bed I own" from "four beds I am choosing between". Measured: CLIP puts
    two views of one sofa at 0.804 and two different pieces at 0.936, so
    visual similarity cannot make that call either.
    """
    room_type = {r.room_id: r.type for r in analysis.rooms}
    counted: dict[tuple[Optional[str], str], int] = {}
    strongest_first = sorted(
        analysis.spotted_objects, key=lambda s: (-s.confidence, s.name)
    )
    for item in strongest_first:
        if not item.image_ref and item.image_index < 0:
            continue                                   # not from a photo
        cap = _capacity(room_type.get(item.room_id or "", ""), item.semantic_type)
        if cap is None:
            continue
        key = (item.room_id, item.semantic_type)
        counted[key] = counted.get(key, 0) + max(1, item.count)
        if counted[key] > cap:
            item.role = "reference"


def _ensure_declared_rooms(rooms: list[RoomAnalysis], bundle: InputBundle,
                           room_types: list[str], default_dims: dict, warnings: list[str]) -> None:
    """Every room the client declared must exist, in place.

    A room chosen at setup ("Full 2BHK") is a statement about the property, not
    a hint about the brief: a 2BHK has two bedrooms, a living room, a kitchen
    and a bathroom whether or not the client thought to mention them. The brief
    then *conditions* those rooms — what each is for, what it must hold.

    Before this, the room list came only from the model's answer and the hints
    were merely offered to it in the prompt. The reading duly invented rooms
    the brief never mentioned and varied between runs: the same project came
    back with a bathroom one run and without it the next, with nothing broken
    and nothing to point at.

    A hint is matched to a room by name first, then by an unclaimed room of the
    same type, so "Bedroom 1" declared and "Master Bedroom" read are one room
    rather than two.
    """
    hints = list(bundle.room_hints or [])
    if not hints:
        return
    claimed: set[int] = set()
    for hint in hints:
        htype = hint.type if hint.type in room_types else "other"
        hslug = vocab.slug(hint.name or htype)
        match = next((i for i, r in enumerate(rooms)
                      if i not in claimed and vocab.slug(r.name) == hslug), None)
        if match is None:
            match = next((i for i, r in enumerate(rooms)
                          if i not in claimed and r.type == htype), None)
        if match is not None:
            claimed.add(match)
            continue

        dw, dl = default_dims.get(htype, default_dims["other"])
        name = (hint.name or vocab.ROOM_LABELS.get(htype, "Room")).strip()
        base = vocab.slug(name)
        room_id = base
        n = 1
        while any(r.room_id == room_id for r in rooms):
            n += 1
            room_id = f"{base}_{n}"
        rooms.append(
            RoomAnalysis(
                room_id=room_id, name=name, type=htype,
                width_m=float(hint.width_m or dw),
                length_m=float(hint.length_m or dl),
                height_m=float(getattr(hint, "height_m", None) or 3.0),
                estimated=not (hint.width_m and hint.length_m),
                notes="declared at setup",
            )
        )
        claimed.add(len(rooms) - 1)
        warnings.append(f"{name} was declared for this space but not described; added with default dimensions")


def clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _hex(value: Any) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 7 and all(c in "0123456789abcdefABCDEF" for c in v[1:]):
        return v.upper()
    return ""


def _dims(value: Any) -> Optional[tuple[float, float, float]]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            dims = tuple(max(0.03, min(6.0, float(d))) for d in value)
            return dims  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _bbox(value: Any) -> Optional[tuple[float, float, float, float]]:
    """[x0, y0, x1, y1] as fractions; accepts 0..1000 (Gemini's habit) too."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        vals = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if max(vals) > 1.0:
        scale = 1000.0 if max(vals) > 100.0 else 100.0
        vals = [v / scale for v in vals]
    x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in vals)
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


def coerce_analysis(raw: dict[str, Any], bundle: InputBundle, warnings: list[str], provider: str) -> DesignAnalysis:
    # the bundle carries the vertical, so the room and tag vocabularies used
    # to validate the model's answer are the same ones its schema offered
    vertical = bundle.vertical
    room_types = vocab.room_types(vertical)
    default_dims = vocab.room_default_dims(vertical)
    rooms: list[RoomAnalysis] = []
    seen: dict[str, int] = {}
    name_to_id: dict[str, str] = {}
    for item in raw.get("rooms") or []:
        rtype = item.get("type") if item.get("type") in room_types else "other"
        name = str(item.get("name") or vocab.ROOM_LABELS.get(rtype, "Room")).strip()
        base = vocab.slug(name)
        seen[base] = seen.get(base, 0) + 1
        room_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        dw, dl = default_dims.get(rtype, default_dims["other"])
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

        rooms = _default_rooms(vertical)
    # The client's declared rooms are not negotiable; the reading only fills
    # in what each one is for.
    _ensure_declared_rooms(rooms, bundle, room_types, default_dims, warnings)

    spotted: list[SpottedObject] = []
    n_refs = len(bundle.references)
    for item in raw.get("spotted_objects") or []:
        name = str(item.get("name") or "").strip()
        given = str(item.get("semantic_type") or "").strip().lower().replace(" ", "_")
        sem = vocab.canonical_type(name, given)
        if sem == "other" and not name:
            warnings.append(f"ignored unnamed object of unknown type {given!r}")
            continue
        if sem == "other" and given and given != "other":
            warnings.append(f"kept {name!r} as 'other' (unknown type {given!r})")
        family = vocab.family_for(sem, str(item.get("family") or ""))
        placement = vocab.placement_for(sem, str(item.get("placement") or ""))
        room_name = str(item.get("room_name") or "").lower()
        room_id = name_to_id.get(room_name)
        if room_id is None:
            default_room = vocab.OBJECT_DEFAULT_ROOM.get(sem)
            room_id = next((r.room_id for r in rooms if r.type == default_room), rooms[0].room_id)
        try:
            image_index = int(item.get("image_index", -1))
        except (TypeError, ValueError):
            image_index = -1
        bbox = _bbox(item.get("bbox"))
        if bbox is not None and not (0 <= image_index < n_refs):
            image_index = 0 if n_refs else -1
            if image_index < 0:
                bbox = None
        # Pin the position to the upload's stable id NOW, while the bundle in
        # hand is still the one the model was shown. Everything downstream
        # resolves on the id, so deleting or reordering a photo can no longer
        # re-point a reading at somebody else's furniture.
        image_ref = bundle.references[image_index].input_id if 0 <= image_index < n_refs else ""
        spotted.append(
            SpottedObject(
                semantic_type=sem,
                name=name or sem.replace("_", " "),
                family=family,
                placement=placement,
                support=str(item.get("support") or "").strip() if placement == "on_surface" else "",
                material=str(item.get("material") or "").strip(),
                color=_hex(item.get("color")),
                approx_dimensions=_dims(item.get("approx_dimensions")),
                room_id=room_id,
                count=max(1, min(12, int(item.get("count") or 1))),
                confidence=clamp(item.get("confidence", 0.5)),
                notes=str(item.get("notes") or ""),
                image_ref=image_ref,
                image_index=image_index,
                bbox=bbox,
            )
        )

    architecture = [a for a in (raw.get("architecture") or []) if a in vocab.ARCHITECTURE_FEATURES]
    keywords = [k for k in (raw.get("keywords") or []) if k in vocab.style_tags(vertical)]
    analysis = DesignAnalysis(
        intent=str(raw.get("intent") or bundle.description[:200] or "Interior design brief"),
        rooms=rooms,
        constraints=[str(c) for c in (raw.get("constraints") or [])][:12],
        spotted_objects=spotted[:40],
        architecture=list(dict.fromkeys(architecture)),
        keywords=keywords,
        confidence=clamp(raw.get("confidence", 0.7)),
        provider=provider,
        warnings=warnings,
    )
    assign_ids(analysis)
    assign_roles(analysis)
    return analysis


def coerce_style(
    raw: dict[str, Any],
    valid_materials: set[str],
    warnings: list[str],
    provider: str,
    vertical: Vertical | str = Vertical.RESIDENTIAL,
) -> StyleSpec:
    tags = [t for t in (raw.get("tags") or []) if t in vocab.style_tags(vertical)]
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
        name = str(item.get("name") or "").strip()
        given = str(item.get("semantic_type") or "").strip().lower().replace(" ", "_")
        sem = vocab.canonical_type(name, given)
        room_id = str(item.get("room_id") or "")
        if sem == "other" and not name:
            warnings.append(f"ignored unnamed object of unknown type {given!r}")
            continue
        if room_id not in room_ids:
            warnings.append(f"ignored {name or sem} in unknown room {room_id!r}")
            continue
        key = str(item.get("object_key") or f"{room_id}.{sem}.{len(items) + 1}")
        if key in keys:
            key = f"{key}_{len(items) + 1}"
        keys.add(key)
        rel_type = item.get("relation_type") or "against_wall"
        target = item.get("relation_target") or None
        relation = ObjectRelation(type=rel_type, target_key=None if rel_type == "against_wall" else target)
        try:
            spotted_index = int(item.get("spotted_index", -1))
        except (TypeError, ValueError):
            spotted_index = -1
        spotted = analysis.spotted_objects[spotted_index] if 0 <= spotted_index < len(analysis.spotted_objects) else None
        # The reference items were filtered out of the prompt, but their indices
        # were not renumbered, so the planner sees gaps (0, 2, 3, 4) and will
        # sometimes emit the missing one. Resolving it here would copy the
        # reference item's name, crop and dimensions straight back into the
        # plan — which is exactly how a shop photo re-entered the room after it
        # had been excluded. An index pointing at a reference resolves to
        # nothing; whatever the planner meant, it is not that item.
        if spotted is not None and spotted.role != "place":
            spotted, spotted_index = None, -1
        family = vocab.family_for(sem, str(item.get("family") or (spotted.family if spotted else "")))
        placement = vocab.placement_for(sem, str(item.get("placement") or (spotted.placement if spotted else "")))
        support_key = str(item.get("support_key") or "").strip() or None
        color = _hex(item.get("color_hint")) or (spotted.color if spotted else "")
        dims = _dims(item.get("approx_dimensions")) or (spotted.approx_dimensions if spotted else None)
        items.append(
            ObjectPlanItem(
                object_key=key,
                semantic_type=sem,
                room_id=room_id,
                name=name or (spotted.name if spotted else sem.replace("_", " ")),
                family=family,
                placement=placement,
                support_key=support_key if placement == "on_surface" else None,
                crop_ref=spotted.crop_ref if spotted else "",
                spotted_index=spotted_index if spotted else -1,
                priority=max(1, min(3, int(item.get("priority") or 2))),
                count=max(1, min(12, int(item.get("count") or 1))),
                approx_dimensions=dims,
                relation=relation,
                style_notes=str(item.get("style_notes") or ""),
                material_hint=str(item.get("material_hint") or (spotted.material if spotted else "")),
                color_hint=color,
                from_photo=bool(item.get("from_photo", spotted is not None)),
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
        if it.support_key:
            support = by_key.get(it.support_key)
            if support is None or support.room_id != it.room_id:
                warnings.append(f"{it.object_key}: support {it.support_key!r} not found; the planner will pick a surface")
                it.support_key = None
    # spotted items the planner forgot still get in (the reading is the
    # contract) — except references, which were never offered to it and must
    # not arrive through the back door.
    carried = {i.spotted_index for i in items if i.spotted_index >= 0}
    for idx, s in enumerate(analysis.spotted_objects):
        if idx in carried or s.room_id not in room_ids or s.role != "place":
            continue
        key = f"{s.room_id}.{s.semantic_type}.{idx + 1}"
        if key in keys:
            key = f"{key}_{len(items) + 1}"
        keys.add(key)
        items.append(
            ObjectPlanItem(
                object_key=key, semantic_type=s.semantic_type, room_id=s.room_id or "", name=s.name,
                family=s.family, placement=s.placement, crop_ref=s.crop_ref, spotted_index=idx,
                priority=1, count=s.count, approx_dimensions=s.approx_dimensions,
                relation=ObjectRelation(type="against_wall"), material_hint=s.material, color_hint=s.color,
                from_photo=True,
            )
        )
        warnings.append(f"added {s.name!r} from the reading; the planner had dropped it")
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

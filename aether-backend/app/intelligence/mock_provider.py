"""Deterministic provider: keyword rules, defaults and image colour averages.

Runs with zero API keys. Tests, the golden project and Gemini fallbacks all
depend on it, so it must never raise on ordinary input.
"""
from __future__ import annotations

import re
from typing import Optional

from ..materials.registry import get_material_registry
from . import vocab
from .images import palette_from_images
from .schema import (
    DesignAnalysis,
    InputBundle,
    MoodboardSpec,
    ObjectPlan,
    ObjectPlanItem,
    ObjectRelation,
    RoomAnalysis,
    SpottedObject,
    StyleSpec,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CONSTRAINT_HINTS = ("no ", "not ", "avoid", "must", "keep", "budget", "don't", "without", "only", "need")


class MockProvider:
    name = "mock"

    # ── stage 5: input analysis ──────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        text = bundle.description.strip()
        lower = text.lower()
        warnings: list[str] = []

        rooms = _rooms_from_hints(bundle) or _rooms_from_text(lower)
        if not rooms:
            rooms = _default_rooms()
            warnings.append("no rooms described; assumed a living room and a bedroom with estimated sizes")

        keywords = _keywords(lower)
        spotted = _spotted_objects(lower, rooms)
        constraints = _constraints(text)
        intent = _intent(text, rooms)

        confidence = 0.45
        if bundle.room_hints:
            confidence += 0.2
        if len(text) > 40:
            confidence += 0.15
        if bundle.references:
            confidence += 0.1

        return DesignAnalysis(
            intent=intent,
            rooms=rooms,
            constraints=constraints,
            spotted_objects=spotted,
            keywords=keywords,
            confidence=min(confidence, 0.95),
            provider=self.name,
            warnings=warnings,
        )

    # ── stage 5/6: style ─────────────────────────────────────────────────
    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        lower = bundle.description.lower()
        tags = _style_tags(lower, analysis.keywords)
        warnings: list[str] = []

        palette = palette_from_images([r.path for r in bundle.references], count=5)
        if not palette:
            lead = next((t for t in tags if t in vocab.STYLE_PALETTES), "modern")
            palette = list(vocab.STYLE_PALETTES.get(lead, vocab.DEFAULT_PALETTE))
            if bundle.references:
                warnings.append("reference images could not be decoded; palette taken from style defaults")

        mood = _lighting_mood(lower, tags)
        materials = _pick_materials(tags)
        name = "_".join(tags[:3]) if tags else "modern_warm_minimal"

        return StyleSpec(
            name=name,
            tags=tags,
            palette=palette,
            materials=materials,
            lighting_mood=mood,
            description=_style_description(tags, mood),
            confidence=0.5 if not bundle.references else 0.6,
            provider=self.name,
            warnings=warnings,
        )


    # ── stages 6–7: object plan ──────────────────────────────────────────
    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        items: list[ObjectPlanItem] = []
        warnings: list[str] = []
        has_dining_room = any(r.type == "dining_room" for r in analysis.rooms)
        spotted_by_room: dict[str, set[str]] = {}
        for s in analysis.spotted_objects:
            spotted_by_room.setdefault(s.room_id or "", set()).add(s.semantic_type)

        for room in analysis.rooms:
            area = room.area_m2
            counts: dict[str, int] = {}
            # ── items read from the photos / brief come first, with everything the reading knows
            spotted_here = [(i, s) for i, s in enumerate(analysis.spotted_objects) if s.room_id == room.room_id]
            key_by_index: dict[int, str] = {}
            for idx, s in spotted_here:
                sem = s.semantic_type
                counts[sem] = counts.get(sem, 0) + 1
                key = f"{room.room_id}.{sem}.{counts[sem]}"
                key_by_index[idx] = key
                items.append(
                    ObjectPlanItem(
                        object_key=key,
                        semantic_type=sem,
                        room_id=room.room_id,
                        name=s.name or sem.replace("_", " "),
                        family=s.family or vocab.family_for(sem),
                        placement=s.placement,
                        crop_ref=s.crop_ref,
                        spotted_index=idx,
                        priority=1,
                        count=s.count,
                        approx_dimensions=s.approx_dimensions,
                        relation=_relation_for(sem, room.room_id, items) if s.placement == "floor" else ObjectRelation(type="against_wall"),
                        material_hint=s.material or MATERIAL_HINTS.get(sem, ""),
                        color_hint=s.color,
                        from_photo=True,
                        style_notes=", ".join(style.tags[:2]),
                    )
                )
            # resolve "rests on <name>" to the supporting item's key
            for idx, s in spotted_here:
                if s.placement != "on_surface" or not s.support:
                    continue
                want = s.support.lower()
                match = next(
                    (j for j, t in spotted_here if j != idx and (t.name.lower() == want or want in t.name.lower() or t.name.lower() in want)),
                    None,
                )
                if match is not None:
                    item = next(i for i in items if i.object_key == key_by_index[idx])
                    item.support_key = key_by_index[match]
            # ── then what the room type needs, minus what was already seen
            wanted = list(ROOM_SETS.get(room.type, ROOM_SETS["other"]))
            if room.type == "living_room" and not has_dining_room and area >= 16:
                wanted += [("dining_table", 2, 1), ("chair", 2, 4)]
            seen_types = spotted_by_room.get(room.id_for_plan, set())
            for sem, priority, count in wanted:
                if sem in seen_types:
                    continue
                if area < 8 and priority >= 2:
                    continue
                if area < 11 and priority == 3:
                    continue
                counts[sem] = counts.get(sem, 0) + 1
                key = f"{room.room_id}.{sem}.{counts[sem]}"
                placement = vocab.placement_for(sem)
                items.append(
                    ObjectPlanItem(
                        object_key=key,
                        semantic_type=sem,
                        room_id=room.room_id,
                        name=sem.replace("_", " "),
                        family=vocab.family_for(sem),
                        placement=placement,
                        priority=priority,
                        count=count,
                        relation=_relation_for(sem, room.room_id, items) if placement == "floor" else ObjectRelation(type="against_wall"),
                        material_hint=MATERIAL_HINTS.get(sem, ""),
                        from_photo=False,
                        style_notes=", ".join(style.tags[:2]),
                    )
                )
            if not any(i.room_id == room.room_id for i in items):
                warnings.append(f"{room.name}: no furniture planned (room type {room.type})")

        return ObjectPlan(
            rooms=[r.room_id for r in analysis.rooms],
            items=items,
            provider=self.name,
            confidence=0.55,
            warnings=warnings,
        )


# semantic_type, priority, count — per room type, in placement order
ROOM_SETS: dict[str, list[tuple[str, int, int]]] = {
    "living_room": [
        ("sofa", 1, 1), ("coffee_table", 1, 1), ("tv_unit", 1, 1), ("rug", 2, 1),
        ("armchair", 2, 1), ("floor_lamp", 2, 1), ("plant", 2, 1), ("curtains", 2, 1),
        ("side_table", 3, 1), ("wall_art", 3, 1), ("books", 3, 1), ("pillows", 3, 2),
    ],
    "bedroom": [("bed", 1, 1), ("wardrobe", 1, 1), ("bedside_table", 1, 2), ("table_lamp", 2, 2), ("rug", 2, 1), ("curtains", 2, 1), ("plant", 3, 1)],
    "master_bedroom": [
        ("bed", 1, 1), ("wardrobe", 1, 1), ("bedside_table", 1, 2), ("table_lamp", 2, 2), ("rug", 2, 1),
        ("curtains", 2, 1), ("dresser", 2, 1), ("wall_art", 3, 1), ("armchair", 3, 1), ("plant", 3, 1),
    ],
    "kids_bedroom": [("bed", 1, 1), ("wardrobe", 1, 1), ("desk", 2, 1), ("chair", 2, 1), ("bookshelf", 3, 1), ("rug", 3, 1)],
    "kitchen": [("kitchen_counter", 1, 1), ("fridge", 1, 1), ("kitchen_island", 3, 1), ("bar_stool", 3, 2)],
    "dining_room": [("dining_table", 1, 1), ("chair", 1, 4), ("sideboard", 2, 1), ("pendant_lamp", 2, 1), ("plant", 3, 1)],
    "study": [("desk", 1, 1), ("chair", 1, 1), ("bookshelf", 2, 1), ("floor_lamp", 3, 1), ("plant", 3, 1)],
    "entry": [("console", 2, 1), ("mirror", 2, 1), ("plant", 3, 1)],
    "balcony": [("chair", 2, 2), ("plant", 2, 2), ("side_table", 3, 1)],
    "bathroom": [],
    "other": [("armchair", 2, 1), ("side_table", 3, 1), ("plant", 3, 1)],
}

MATERIAL_HINTS: dict[str, str] = {
    "sofa": "fabric", "loveseat": "fabric", "armchair": "fabric", "ottoman": "fabric", "chair": "fabric",
    "bed": "fabric", "rug": "fabric", "pillows": "fabric", "curtains": "fabric", "bar_stool": "fabric",
    "coffee_table": "wood", "side_table": "wood", "tv_unit": "wood", "dining_table": "wood",
    "wardrobe": "wood", "bedside_table": "wood", "dresser": "wood", "desk": "wood", "bookshelf": "wood",
    "sideboard": "wood", "console": "wood", "kitchen_island": "wood", "kitchen_counter": "wood", "vanity": "wood",
    "fridge": "metal",
    "floor_lamp": "metal", "pendant_lamp": "metal", "chandelier": "metal", "table_lamp": "metal",
    "mirror": "metal", "lantern": "metal",
}

# how an object relates to something already planned in the same room
_RELATION_RULES: dict[str, tuple[str, str]] = {
    "coffee_table": ("in_front_of", "sofa"),
    "tv_unit": ("facing", "sofa"),
    "rug": ("under", "sofa"),
    "floor_lamp": ("beside", "sofa"),
    "side_table": ("beside", "sofa"),
    "armchair": ("facing", "sofa"),
    "bedside_table": ("beside", "bed"),
    "chair": ("around", "dining_table"),
    "bar_stool": ("beside", "kitchen_island"),
    "pendant_lamp": ("under", "dining_table"),
}
_BED_RUG = ("under", "bed")


def _relation_for(sem: str, room_id: str, planned: list[ObjectPlanItem]) -> Optional[ObjectRelation]:
    rule = _RELATION_RULES.get(sem)
    if sem == "rug" and not any(i.room_id == room_id and i.semantic_type == "sofa" for i in planned):
        rule = _BED_RUG
    if sem == "chair" and not any(i.room_id == room_id and i.semantic_type == "dining_table" for i in planned):
        rule = ("in_front_of", "desk")
    if rule is None:
        return ObjectRelation(type="against_wall")
    rel_type, target_sem = rule
    target = next((i for i in planned if i.room_id == room_id and i.semantic_type == target_sem), None)
    if target is None:
        return ObjectRelation(type="against_wall")
    return ObjectRelation(type=rel_type, target_key=target.object_key)


# ── helpers ──────────────────────────────────────────────────────────────


def build_moodboard(analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> MoodboardSpec:
    title = bundle.project_name or style.name.replace("_", " ").title()
    return MoodboardSpec(
        title=f"{title} · {style.name.replace('_', ' ').title()}",
        style_name=style.name,
        style_tags=style.tags,
        palette=style.palette,
        material_ids=style.materials,
        lighting_mood=style.lighting_mood,
        reference_urls=[r.url for r in bundle.references if r.url],
        keywords=analysis.keywords,
        rooms=[r.name for r in analysis.rooms],
    )


def _rooms_from_hints(bundle: InputBundle) -> list[RoomAnalysis]:
    rooms: list[RoomAnalysis] = []
    counts: dict[str, int] = {}
    for hint in bundle.room_hints:
        rtype = hint.type if hint.type in vocab.ROOM_TYPES else vocab.ROOM_KEYWORDS.get(hint.type.lower(), "other")
        counts[rtype] = counts.get(rtype, 0) + 1
        dw, dl = vocab.ROOM_DEFAULT_DIMS.get(rtype, vocab.ROOM_DEFAULT_DIMS["other"])
        estimated = hint.width_m is None or hint.length_m is None or hint.estimated
        base = vocab.slug(hint.name) if hint.name else rtype
        room_id = base if base not in {r.room_id for r in rooms} else f"{base}_{counts[rtype]}"
        rooms.append(
            RoomAnalysis(
                room_id=room_id,
                name=hint.name or vocab.ROOM_LABELS.get(rtype, "Room"),
                type=rtype,
                width_m=hint.width_m or dw,
                length_m=hint.length_m or dl,
                height_m=hint.height_m or 3.0,
                estimated=estimated,
            )
        )
    return rooms


def _rooms_from_text(lower: str) -> list[RoomAnalysis]:
    types: list[str] = []
    beds = vocab.bedroom_count(lower)
    has_master = "master bedroom" in lower or "primary bedroom" in lower
    if beds:
        types += ["living_room", "kitchen"]
        if has_master:
            types += ["master_bedroom"] + ["bedroom"] * (beds - 1)
        else:
            types += ["bedroom"] * beds
    for phrase, rtype in vocab.ROOM_KEYWORDS.items():
        if phrase in lower and rtype not in types:
            if beds and rtype in ("bedroom", "master_bedroom"):
                continue  # already counted from the BHK / bedroom count
            types.append(rtype)
    return _make_rooms(types)


def _default_rooms() -> list[RoomAnalysis]:
    return _make_rooms(["living_room", "bedroom"])


def _make_rooms(types: list[str]) -> list[RoomAnalysis]:
    rooms: list[RoomAnalysis] = []
    seen: dict[str, int] = {}
    for rtype in types:
        seen[rtype] = seen.get(rtype, 0) + 1
        n = seen[rtype]
        total = types.count(rtype)
        room_id = rtype if total == 1 else f"{rtype}_{n}"
        label = vocab.ROOM_LABELS.get(rtype, "Room")
        name = label if total == 1 else f"{label} {n}"
        w, l = vocab.ROOM_DEFAULT_DIMS.get(rtype, vocab.ROOM_DEFAULT_DIMS["other"])
        rooms.append(RoomAnalysis(room_id=room_id, name=name, type=rtype, width_m=w, length_m=l, estimated=True))
    return rooms


def _keywords(lower: str) -> list[str]:
    """Style tags in the order they appear in the brief (the first one leads
    the style name and palette), then mentioned object types."""
    positions: dict[str, int] = {}
    for phrase, tag in vocab.STYLE_KEYWORDS.items():
        pos = lower.find(phrase)
        if pos >= 0 and (tag not in positions or pos < positions[tag]):
            positions[tag] = pos
    found = [tag for tag, _ in sorted(positions.items(), key=lambda kv: kv[1])]
    for sem, phrases in vocab.OBJECT_KEYWORDS.items():
        if any(p in lower for p in phrases) and sem not in found:
            found.append(sem)
    return found


def _spotted_objects(lower: str, rooms: list[RoomAnalysis]) -> list[SpottedObject]:
    room_by_type: dict[str, str] = {}
    for r in rooms:
        room_by_type.setdefault(r.type, r.room_id)
        if r.type in ("master_bedroom", "kids_bedroom"):
            room_by_type.setdefault("bedroom", r.room_id)
    out: list[SpottedObject] = []
    for sem, phrases in vocab.OBJECT_KEYWORDS.items():
        hit = next((p for p in phrases if p in lower), None)
        if hit is None:
            continue
        default_room = vocab.OBJECT_DEFAULT_ROOM.get(sem, "living_room")
        room_id = room_by_type.get(default_room) or (rooms[0].room_id if rooms else None)
        out.append(
            SpottedObject(
                semantic_type=sem, name=hit, family=vocab.family_for(sem), placement=vocab.placement_for(sem),
                room_id=room_id, confidence=0.6, notes="mentioned in brief",
            )
        )
    return out


def _constraints(text: str) -> list[str]:
    out: list[str] = []
    for sentence in _SENTENCE.split(text):
        s = sentence.strip()
        if s and any(h in s.lower() for h in _CONSTRAINT_HINTS):
            out.append(s.rstrip("."))
    return out[:8]


def _intent(text: str, rooms: list[RoomAnalysis]) -> str:
    first = _SENTENCE.split(text.strip())[0].strip() if text.strip() else ""
    if first:
        return first[:200]
    names = ", ".join(r.name for r in rooms)
    return f"Design {names}"


def _style_tags(lower: str, keywords: list[str]) -> list[str]:
    tags = [k for k in keywords if k in vocab.STYLE_TAGS]
    if not tags:
        tags = ["modern", "warm", "minimal"]
    # a leading tag drives the palette; keep at most six
    return tags[:6]


def _lighting_mood(lower: str, tags: list[str]) -> str:
    for phrase, mood in vocab.LIGHTING_KEYWORDS.items():
        if phrase in lower:
            return mood
    if "moody" in tags or "dark" in tags:
        return "evening"
    return "warm_daylight"


# style tag → material registry tag synonyms
_TAG_SYNONYMS: dict[str, list[str]] = {
    "warm": ["warm_neutral", "warm"],
    "natural": ["warm_neutral", "natural"],
    "indian_contemporary": ["modern_indian"],
    "contemporary": ["modern"],
    "scandinavian": ["japandi", "warm_neutral"],
    "japandi": ["japandi", "warm_neutral", "calm"],
    "minimal": ["minimal", "modern"],
    "moody": ["moody", "dark"],
    "dark": ["dark", "moody"],
    "traditional": ["classic"],
    "art_deco": ["luxury", "classic"],
}

# role → (categories, required applies_to slot)
_MATERIAL_ROLES: list[tuple[str, set[str], str]] = [
    ("floor", {"wood", "tile", "stone", "marble"}, "floor"),
    ("wall", {"plaster", "paint", "marble"}, "wall"),
    ("furniture_wood", {"wood"}, "furniture"),
    ("fabric", {"fabric", "leather"}, "furniture"),
    ("accent", {"metal", "glass"}, "furniture"),
]


def _pick_materials(tags: list[str], limit: int = 7) -> list[str]:
    """One material per role (floor, wall, furniture wood, fabric, accent)
    chosen by style-tag overlap, then the best remaining matches up to limit."""
    records = get_material_registry().list()
    wanted: set[str] = set()
    for t in tags:
        wanted.add(t)
        wanted.update(_TAG_SYNONYMS.get(t, []))

    def score(rec) -> tuple[int, int, int]:
        return (len(wanted & set(rec.style_tags)), int(rec.has_maps), -len(rec.style_tags))

    picked: list[str] = []
    for _role, categories, slot in _MATERIAL_ROLES:
        candidates = [r for r in records if r.category in categories and slot in r.applies_to and r.material_id not in picked]
        if candidates:
            best = max(candidates, key=score)
            picked.append(best.material_id)
    for rec in sorted(records, key=score, reverse=True):
        if len(picked) >= limit:
            break
        if rec.material_id not in picked and score(rec)[0] > 0:
            picked.append(rec.material_id)
    return picked[:limit]


def _style_description(tags: list[str], mood: str) -> str:
    human = ", ".join(t.replace("_", " ") for t in tags) or "modern"
    return f"{human.capitalize()} interior with {mood.replace('_', ' ')} lighting."


def describe_provider() -> Optional[str]:
    return MockProvider.name

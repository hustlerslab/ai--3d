"""Controlled vocabularies shared by the mock and Gemini providers.

Keeping these in one place means both providers emit the same tags, room
types and semantic types, so downstream planners never special-case the
provider.
"""
from __future__ import annotations

import re

# ── Style tags ───────────────────────────────────────────────────────────
STYLE_TAGS: list[str] = [
    "modern", "contemporary", "minimal", "warm", "scandinavian", "japandi",
    "industrial", "luxury", "classic", "traditional", "bohemian", "coastal",
    "mid_century", "moody", "dark", "light", "natural", "rustic", "art_deco",
    "indian_contemporary", "warm_neutral", "mediterranean",
]

# keyword/phrase → tag (lower-case substring match on the brief)
STYLE_KEYWORDS: dict[str, str] = {
    "modern": "modern", "contemporary": "contemporary", "minimal": "minimal",
    "minimalist": "minimal", "clean lines": "minimal", "warm": "warm",
    "cozy": "warm", "cosy": "warm", "scandi": "scandinavian",
    "scandinavian": "scandinavian", "nordic": "scandinavian", "japandi": "japandi",
    "japanese": "japandi", "zen": "japandi", "industrial": "industrial",
    "loft": "industrial", "exposed brick": "industrial", "luxury": "luxury",
    "luxurious": "luxury", "premium": "luxury", "high-end": "luxury",
    "opulent": "luxury", "classic": "classic", "traditional": "traditional",
    "heritage": "traditional", "boho": "bohemian", "bohemian": "bohemian",
    "eclectic": "bohemian", "coastal": "coastal", "beach": "coastal",
    "mid-century": "mid_century", "mid century": "mid_century", "retro": "mid_century",
    "moody": "moody", "dramatic": "moody", "dark": "dark", "black": "dark",
    "bright": "light", "airy": "light", "light-filled": "light", "white": "light",
    "natural": "natural", "wood": "natural", "oak": "natural", "walnut": "natural",
    "earthy": "natural", "rustic": "rustic", "farmhouse": "rustic",
    "art deco": "art_deco", "deco": "art_deco", "brass": "art_deco",
    "indian": "indian_contemporary", "ethnic": "indian_contemporary",
    "neutral": "warm_neutral", "beige": "warm_neutral", "taupe": "warm_neutral",
    "mediterranean": "mediterranean", "terracotta": "mediterranean",
}

# ── Rooms ────────────────────────────────────────────────────────────────
ROOM_TYPES: list[str] = [
    "living_room", "bedroom", "master_bedroom", "kids_bedroom", "kitchen",
    "dining_room", "bathroom", "study", "balcony", "entry", "other",
]

# default (width_m, length_m) when the user gave no dimensions
ROOM_DEFAULT_DIMS: dict[str, tuple[float, float]] = {
    "living_room": (5.0, 4.2),
    "bedroom": (4.0, 3.6),
    "master_bedroom": (4.6, 4.0),
    "kids_bedroom": (3.6, 3.2),
    "kitchen": (3.6, 3.0),
    "dining_room": (4.0, 3.4),
    "bathroom": (2.4, 2.0),
    "study": (3.4, 3.0),
    "balcony": (3.0, 1.5),
    "entry": (2.4, 2.0),
    "other": (3.5, 3.5),
}

ROOM_KEYWORDS: dict[str, str] = {
    "living room": "living_room", "living": "living_room", "lounge": "living_room",
    "drawing room": "living_room", "hall": "living_room", "family room": "living_room",
    "master bedroom": "master_bedroom", "primary bedroom": "master_bedroom",
    "kids room": "kids_bedroom", "kids bedroom": "kids_bedroom", "children": "kids_bedroom",
    "bedroom": "bedroom", "guest room": "bedroom",
    "kitchen": "kitchen", "dining room": "dining_room", "dining area": "dining_room",
    "dining space": "dining_room", "bathroom": "bathroom",
    "washroom": "bathroom", "toilet": "bathroom", "study room": "study",
    "study area": "study", "home office": "study", "office": "study",
    "workspace": "study", "balcony": "balcony",
    "terrace": "balcony", "entry": "entry", "foyer": "entry", "entrance": "entry",
}

ROOM_LABELS: dict[str, str] = {
    "living_room": "Living Room", "bedroom": "Bedroom", "master_bedroom": "Master Bedroom",
    "kids_bedroom": "Kids Bedroom", "kitchen": "Kitchen", "dining_room": "Dining Room",
    "bathroom": "Bathroom", "study": "Study", "balcony": "Balcony", "entry": "Entry",
    "other": "Room",
}

_BHK = re.compile(r"(\d)\s*-?\s*bhk", re.IGNORECASE)
_BED = re.compile(r"(\d|one|two|three|four)\s*-?\s*(?:bed(?:room)?s?)\b", re.IGNORECASE)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}


def bedroom_count(text: str) -> int | None:
    """'2BHK', '3 bhk', 'two bedroom' → number of bedrooms."""
    m = _BHK.search(text)
    if m:
        return int(m.group(1))
    m = _BED.search(text)
    if m:
        token = m.group(1).lower()
        return _WORDS.get(token, int(token) if token.isdigit() else None)
    return None


# ── Objects ──────────────────────────────────────────────────────────────
# semantic types the catalog and asset registry understand
SEMANTIC_TYPES: list[str] = [
    "sofa", "loveseat", "armchair", "ottoman", "coffee_table", "side_table",
    "tv_unit", "dining_table", "chair", "bar_stool", "bed", "wardrobe",
    "bedside_table", "dresser", "desk", "bookshelf", "sideboard", "console",
    "rug", "floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "plant",
    "mirror", "wall_art", "curtains", "vase", "sculpture", "pillows", "lantern",
    "kitchen_island", "kitchen_counter", "bathtub", "vanity",
]

OBJECT_KEYWORDS: dict[str, list[str]] = {
    "sofa": ["sofa", "couch", "sectional"],
    "loveseat": ["loveseat", "two seater", "2 seater", "two-seater"],
    "armchair": ["armchair", "accent chair", "lounge chair"],
    "ottoman": ["ottoman", "pouf", "pouffe"],
    "coffee_table": ["coffee table", "center table", "centre table"],
    "side_table": ["side table", "end table"],
    "tv_unit": ["tv unit", "tv stand", "television", "tv console", "media unit"],
    "dining_table": ["dining table", "dining set"],
    "chair": ["dining chair", "chairs"],
    "bar_stool": ["bar stool", "stool"],
    "bed": ["bed", "king bed", "queen bed"],
    "wardrobe": ["wardrobe", "closet", "almirah"],
    "bedside_table": ["bedside", "nightstand", "night stand"],
    "dresser": ["dresser", "chest of drawers"],
    "desk": ["desk", "work table", "study table"],
    "bookshelf": ["bookshelf", "book shelf", "bookcase", "shelving"],
    "sideboard": ["sideboard", "credenza", "buffet"],
    "console": ["console table", "console"],
    "rug": ["rug", "carpet"],
    "floor_lamp": ["floor lamp", "standing lamp"],
    "pendant_lamp": ["pendant", "hanging light", "hanging lamp"],
    "chandelier": ["chandelier"],
    "table_lamp": ["table lamp", "desk lamp"],
    "plant": ["plant", "greenery", "planter", "indoor plants"],
    "mirror": ["mirror"],
    "wall_art": ["wall art", "painting", "artwork", "art work", "frames"],
    "curtains": ["curtain", "drapes", "sheer"],
    "kitchen_island": ["island", "breakfast counter"],
    "kitchen_counter": ["kitchen counter", "countertop", "modular kitchen", "cabinets"],
}

# where an object lives when the brief does not say
OBJECT_DEFAULT_ROOM: dict[str, str] = {
    "sofa": "living_room", "loveseat": "living_room", "armchair": "living_room",
    "ottoman": "living_room", "coffee_table": "living_room", "side_table": "living_room",
    "tv_unit": "living_room", "rug": "living_room", "floor_lamp": "living_room",
    "plant": "living_room", "wall_art": "living_room", "console": "entry",
    "mirror": "entry", "bookshelf": "study", "desk": "study",
    "dining_table": "dining_room", "chair": "dining_room", "sideboard": "dining_room",
    "pendant_lamp": "dining_room", "chandelier": "dining_room",
    "bed": "bedroom", "wardrobe": "bedroom", "bedside_table": "bedroom",
    "dresser": "bedroom", "table_lamp": "bedroom", "curtains": "bedroom",
    "kitchen_island": "kitchen", "bar_stool": "kitchen", "kitchen_counter": "kitchen",
}

# ── Lighting ─────────────────────────────────────────────────────────────
LIGHTING_MOODS: list[str] = ["warm_daylight", "cool_daylight", "evening", "studio"]
LIGHTING_KEYWORDS: dict[str, str] = {
    "evening": "evening", "night": "evening", "moody": "evening", "dim": "evening",
    "candle": "evening", "cool": "cool_daylight", "crisp": "cool_daylight",
    "bright white": "cool_daylight", "studio": "studio", "showroom": "studio",
    "daylight": "warm_daylight", "sunlit": "warm_daylight", "sunny": "warm_daylight",
    "golden": "warm_daylight", "warm light": "warm_daylight",
}

# ── Palettes by leading tag (used when no photos are available) ──────────
STYLE_PALETTES: dict[str, list[str]] = {
    "modern": ["#F3EFE8", "#D9D2C5", "#8C8578", "#3B3A36", "#B08D57"],
    "minimal": ["#F7F5F0", "#E8E3DA", "#C9C2B6", "#6E6A63", "#2E2C29"],
    "warm": ["#F3E9DA", "#D9C2A3", "#B08968", "#7A5C43", "#3F3129"],
    "scandinavian": ["#FAF8F4", "#E6DFD3", "#C8B79E", "#8D9B8A", "#3C3F3A"],
    "japandi": ["#F1ECE3", "#D6CBB8", "#9A8B72", "#5F5648", "#2B2925"],
    "industrial": ["#DED9D2", "#9E9891", "#6B6560", "#3D3A37", "#A65E2E"],
    "luxury": ["#EFE8DC", "#C9B48A", "#8A6F44", "#3A3230", "#1E1B1A"],
    "classic": ["#F2ECE2", "#D9CBB0", "#9C7C5B", "#5C4634", "#2F2620"],
    "moody": ["#2A2A2E", "#3F3D45", "#5A4E4A", "#8C6E5A", "#C7B299"],
    "dark": ["#1F1F22", "#33343A", "#55575E", "#8B8578", "#C2B7A5"],
    "coastal": ["#F6F4EE", "#DCE6E8", "#A9C4CB", "#6F8E97", "#3E5760"],
    "natural": ["#F1EBE0", "#CDBFA4", "#9C8A6C", "#6D7B5D", "#3E3B33"],
    "mid_century": ["#F0E6D3", "#D8A65B", "#B4643C", "#4F6D5A", "#2E2A26"],
    "bohemian": ["#F4E8D6", "#D9A77A", "#B2714F", "#7E8B6C", "#4A3B34"],
    "indian_contemporary": ["#F5E9D8", "#D9A05B", "#B2533E", "#5F7A61", "#3B2E2A"],
    "mediterranean": ["#F6EEE2", "#E0C4A0", "#C4784F", "#7C9C8B", "#3E4A55"],
}
DEFAULT_PALETTE = STYLE_PALETTES["modern"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "room"

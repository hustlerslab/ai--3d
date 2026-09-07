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
    "living_room": (6.0, 4.6),
    "bedroom": (4.0, 3.6),
    "master_bedroom": (4.8, 4.2),
    "kids_bedroom": (3.8, 3.4),
    "kitchen": (3.8, 3.0),
    "dining_room": (4.2, 3.6),
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
    "kitchen_island", "kitchen_counter", "fridge", "bathtub", "vanity",
    # open-reading additions (photo decor and architecture)
    "fireplace", "stool", "pedestal", "books", "tray", "sconce", "wall_shelf",
    "wall_clock", "throw", "candle", "basket", "other",
]

# ── Open scene reading ──────────────────────────────────────────────────
# Every spotted item carries an open `name` plus a coarse family, so pieces
# the closed type list never heard of (a secretary bookcase, a pagoda
# ornament) still get sized, placed and built.
FAMILIES: list[str] = [
    "seating", "table", "storage", "bed", "lighting", "plant", "textile",
    "art", "ornament", "appliance", "architecture", "other",
]
PLACEMENTS: list[str] = ["floor", "wall", "ceiling", "on_surface"]
ARCHITECTURE_FEATURES: list[str] = ["cornice", "wainscot", "panelled_doors", "exposed_beams", "arches"]

FAMILY_BY_TYPE: dict[str, str] = {
    "sofa": "seating", "loveseat": "seating", "armchair": "seating", "ottoman": "seating", "chair": "seating",
    "bar_stool": "seating", "stool": "seating",
    "coffee_table": "table", "side_table": "table", "dining_table": "table", "desk": "table", "console": "table",
    "bedside_table": "table", "kitchen_island": "table",
    "tv_unit": "storage", "wardrobe": "storage", "dresser": "storage", "bookshelf": "storage", "sideboard": "storage",
    "kitchen_counter": "storage", "vanity": "storage", "wall_shelf": "storage", "pedestal": "storage", "basket": "storage",
    "bed": "bed",
    "floor_lamp": "lighting", "pendant_lamp": "lighting", "chandelier": "lighting", "table_lamp": "lighting",
    "sconce": "lighting", "lantern": "lighting", "candle": "lighting",
    "plant": "plant",
    "rug": "textile", "curtains": "textile", "pillows": "textile", "throw": "textile",
    "mirror": "art", "wall_art": "art", "wall_clock": "art",
    "vase": "ornament", "sculpture": "ornament", "books": "ornament", "tray": "ornament",
    "fridge": "appliance", "bathtub": "appliance",
    "fireplace": "architecture",
}

# where a type sits when the reader does not say
PLACEMENT_BY_TYPE: dict[str, str] = {
    "wall_art": "wall", "mirror": "wall", "sconce": "wall", "wall_shelf": "wall", "wall_clock": "wall",
    "curtains": "wall",
    "pendant_lamp": "ceiling", "chandelier": "ceiling",
    "table_lamp": "on_surface", "vase": "on_surface", "books": "on_surface", "tray": "on_surface",
    "sculpture": "on_surface", "lantern": "on_surface", "pillows": "on_surface", "throw": "on_surface",
    "candle": "on_surface",
}

# (w, h, d) metres, mount, procedural shape: when a type has no built-in and
# no default of its own, its family decides
FAMILY_DEFAULTS: dict[str, tuple[tuple[float, float, float], str, str]] = {
    "seating": ((0.8, 0.85, 0.8), "floor", "seat"),
    "table": ((1.0, 0.45, 0.6), "floor", "table"),
    "storage": ((1.0, 0.9, 0.45), "floor", "box"),
    "bed": ((1.6, 0.55, 2.05), "floor", "box"),
    "lighting": ((0.35, 1.6, 0.35), "floor", "tall"),
    "plant": ((0.6, 1.2, 0.6), "floor", "tall"),
    "textile": ((0.5, 0.15, 0.5), "floor", "box"),
    "art": ((0.7, 0.9, 0.05), "wall", "photo"),
    "ornament": ((0.25, 0.35, 0.25), "floor", "vase"),
    "appliance": ((0.6, 0.9, 0.6), "floor", "box"),
    "architecture": ((1.4, 1.2, 0.4), "floor", "fireplace"),
    "other": ((0.6, 0.6, 0.6), "floor", "box"),
}

# objects whose top is a usable surface: type -> height of that surface above
# the object's pivot (None = the object's full height)
SURFACE_HEIGHT: dict[str, float | None] = {
    "coffee_table": None, "side_table": None, "dining_table": None, "desk": None, "console": None,
    "bedside_table": None, "sideboard": None, "dresser": None, "tv_unit": None, "kitchen_island": None,
    "bookshelf": None, "pedestal": None, "fireplace": None, "wall_shelf": None, "ottoman": None, "stool": None,
    "kitchen_counter": 0.90, "sofa": 0.45, "loveseat": 0.45, "armchair": 0.45, "bed": None,
}

# which supports each on-surface type prefers, best first
SUPPORT_PREFERENCE: dict[str, list[str]] = {
    "table_lamp": ["bedside_table", "side_table", "console", "sideboard", "desk", "dresser", "tv_unit"],
    "vase": ["console", "sideboard", "coffee_table", "dining_table", "fireplace", "dresser", "side_table"],
    "books": ["coffee_table", "side_table", "console", "bookshelf", "desk", "bedside_table"],
    "tray": ["coffee_table", "ottoman", "dining_table", "console", "kitchen_island"],
    "sculpture": ["sideboard", "console", "fireplace", "bookshelf", "pedestal", "coffee_table"],
    "lantern": ["console", "sideboard", "coffee_table", "fireplace", "side_table"],
    "candle": ["coffee_table", "fireplace", "console", "dining_table", "sideboard"],
    "pillows": ["sofa", "loveseat", "bed", "armchair"],
    "throw": ["sofa", "bed", "armchair", "loveseat"],
    "plant": ["console", "sideboard", "pedestal", "side_table", "bookshelf"],
}

# open name -> closest canonical type (checked after OBJECT_KEYWORDS; first hit wins)
NAME_KEYWORDS: list[tuple[str, str]] = [
    ("fireplace", "fireplace"), ("mantel", "fireplace"), ("hearth", "fireplace"),
    ("secretary", "bookshelf"), ("bookcase", "bookshelf"), ("hutch", "bookshelf"),
    ("chest of drawers", "dresser"), ("drawer", "dresser"), ("credenza", "sideboard"), ("buffet", "sideboard"),
    ("cabinet", "sideboard"),
    ("urn", "plant"), ("fern", "plant"), ("palm", "plant"), ("tree", "plant"), ("planter", "plant"),
    ("pedestal", "pedestal"), ("plinth", "pedestal"), ("column", "pedestal"),
    ("daybed", "loveseat"), ("settee", "loveseat"), ("chaise", "loveseat"), ("bench", "loveseat"),
    ("sectional", "sofa"), ("couch", "sofa"), ("sofa", "sofa"),
    ("lounge chair", "armchair"), ("accent chair", "armchair"), ("wing", "armchair"), ("armchair", "armchair"),
    ("footstool", "stool"), ("stool", "stool"), ("pouf", "ottoman"), ("ottoman", "ottoman"),
    ("waterfall table", "side_table"), ("end table", "side_table"), ("side table", "side_table"),
    ("nightstand", "bedside_table"), ("bedside", "bedside_table"),
    ("coffee table", "coffee_table"), ("cocktail table", "coffee_table"), ("centre table", "coffee_table"),
    ("dining table", "dining_table"), ("console", "console"), ("desk", "desk"), ("writing table", "desk"),
    ("floor lamp", "floor_lamp"), ("standing lamp", "floor_lamp"), ("table lamp", "table_lamp"),
    ("ginger jar lamp", "table_lamp"), ("lamp", "table_lamp"), ("sconce", "sconce"), ("wall light", "sconce"),
    ("chandelier", "chandelier"), ("pendant", "pendant_lamp"), ("lantern", "lantern"), ("candle", "candle"),
    ("mirror", "mirror"), ("painting", "wall_art"), ("print", "wall_art"), ("photo frame", "wall_art"),
    ("picture frame", "wall_art"), ("framed", "wall_art"), ("artwork", "wall_art"), ("art", "wall_art"),
    ("wall bracket", "wall_shelf"), ("bracket", "wall_shelf"), ("wall shelf", "wall_shelf"), ("shelf", "wall_shelf"),
    ("clock", "wall_clock"), ("curtain", "curtains"), ("drape", "curtains"), ("blind", "curtains"),
    ("rug", "rug"), ("carpet", "rug"), ("kilim", "rug"), ("pillow", "pillows"), ("cushion", "pillows"),
    ("throw", "throw"), ("blanket", "throw"), ("vase", "vase"), ("jar", "vase"), ("pot", "vase"),
    ("sculpture", "sculpture"), ("bust", "sculpture"), ("figurine", "sculpture"), ("pagoda", "sculpture"),
    ("ornament", "sculpture"), ("statue", "sculpture"), ("coral", "sculpture"), ("box", "tray"),
    ("tray", "tray"), ("book", "books"), ("basket", "basket"), ("wardrobe", "wardrobe"), ("armoire", "wardrobe"),
    ("closet", "wardrobe"), ("bed", "bed"), ("headboard", "bed"), ("tv", "tv_unit"), ("media", "tv_unit"),
    ("fridge", "fridge"), ("refrigerator", "fridge"), ("counter", "kitchen_counter"), ("island", "kitchen_island"),
    ("dining chair", "chair"), ("chair", "chair"), ("bathtub", "bathtub"), ("vanity", "vanity"),
]


def canonical_type(name: str, given: str = "") -> str:
    """Closest canonical type for an open item name; `given` wins when valid."""
    g = (given or "").strip().lower().replace(" ", "_")
    if g in SEMANTIC_TYPES and g != "other":
        return g
    lower = (name or "").lower()

    def has(phrase: str) -> bool:  # whole words only: "print" must not match "blueprints"
        return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lower) is not None

    for sem, phrases in OBJECT_KEYWORDS.items():
        if any(has(p) for p in phrases):
            return sem
    for phrase, sem in NAME_KEYWORDS:
        if has(phrase):
            return sem
    return "other"


def family_for(semantic_type: str, given: str = "") -> str:
    g = (given or "").strip().lower()
    if g in FAMILIES and g != "other":
        return g
    return FAMILY_BY_TYPE.get(semantic_type, g if g in FAMILIES else "other")


def placement_for(semantic_type: str, given: str = "") -> str:
    g = (given or "").strip().lower()
    if g in PLACEMENTS:
        return g
    return PLACEMENT_BY_TYPE.get(semantic_type, "floor")

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
    "bar_stool": ["bar stool", "counter stool"],
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
    "fridge": ["fridge", "refrigerator"],
}

# where an object lives when the brief does not say
OBJECT_DEFAULT_ROOM: dict[str, str] = {
    "fireplace": "living_room", "stool": "living_room", "pedestal": "living_room", "books": "living_room",
    "tray": "living_room", "sconce": "living_room", "wall_shelf": "living_room", "wall_clock": "living_room",
    "throw": "living_room", "candle": "living_room", "basket": "living_room", "table_lamp": "bedroom",
    "vase": "living_room", "sculpture": "living_room", "lantern": "living_room", "pillows": "living_room",
    "sofa": "living_room", "loveseat": "living_room", "armchair": "living_room",
    "ottoman": "living_room", "coffee_table": "living_room", "side_table": "living_room",
    "tv_unit": "living_room", "rug": "living_room", "floor_lamp": "living_room",
    "plant": "living_room", "wall_art": "living_room", "console": "entry",
    "mirror": "entry", "bookshelf": "study", "desk": "study",
    "dining_table": "dining_room", "chair": "dining_room", "sideboard": "dining_room",
    "pendant_lamp": "dining_room", "chandelier": "dining_room",
    "bed": "bedroom", "wardrobe": "bedroom", "bedside_table": "bedroom",
    "dresser": "bedroom", "table_lamp": "bedroom", "curtains": "bedroom",
    "kitchen_island": "kitchen", "bar_stool": "kitchen", "kitchen_counter": "kitchen", "fridge": "kitchen",
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

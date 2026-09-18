"""Controlled vocabularies shared by the mock and Gemini providers.

Keeping these in one place means both providers emit the same tags, room
types and semantic types, so downstream planners never special-case the
provider.

The room, style and object vocabularies are keyed by `Vertical`: a hotel
brief must never be offered `bedroom`, and an office brief must never be
offered `banquet_hall`. Reach them through the accessors — `room_types`,
`room_default_dims`, `room_keywords`, `style_tags`, `semantic_types`. An
unknown vertical raises instead of quietly falling back to residential.
"""
from __future__ import annotations

import re

from ..projects.schema import Vertical


def _v(vertical: Vertical | str) -> Vertical:
    """The enum for a vertical; anything else is a bug, not a default."""
    try:
        return Vertical(vertical)
    except (ValueError, TypeError) as exc:
        known = ", ".join(v.value for v in Vertical)
        raise ValueError(f"unknown vertical {vertical!r}; expected one of: {known}") from exc


# ── Style tags ───────────────────────────────────────────────────────────
_RESIDENTIAL_STYLE_TAGS: list[str] = [
    "modern", "contemporary", "minimal", "warm", "scandinavian", "japandi",
    "industrial", "luxury", "classic", "traditional", "bohemian", "coastal",
    "mid_century", "moody", "dark", "light", "natural", "rustic", "art_deco",
    "indian_contemporary", "warm_neutral", "mediterranean",
]

# hospitality adds two house styles; industrial reuses `industrial` (loft,
# exposed brick), which the residential list already carries.
_STYLE_TAGS: dict[Vertical, list[str]] = {
    Vertical.RESIDENTIAL: _RESIDENTIAL_STYLE_TAGS,
    Vertical.HOSPITALITY: _RESIDENTIAL_STYLE_TAGS + ["boutique_hotel", "brasserie"],
    Vertical.INDUSTRIAL: _RESIDENTIAL_STYLE_TAGS,
}


def style_tags(vertical: Vertical | str) -> list[str]:
    return _STYLE_TAGS[_v(vertical)]

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
    # hospitality-only tags; style_tags() filters them out for the others
    "boutique": "boutique_hotel", "boutique hotel": "boutique_hotel",
    "brasserie": "brasserie", "bistro": "brasserie",
}

# ── Rooms ────────────────────────────────────────────────────────────────
_ROOM_TYPES: dict[Vertical, list[str]] = {
    Vertical.RESIDENTIAL: [
        "living_room", "bedroom", "master_bedroom", "kids_bedroom", "kitchen",
        "dining_room", "bathroom", "study", "balcony", "entry", "other",
    ],
    # a hotel / restaurant floor plate: the public rooms are commercial-scale
    Vertical.HOSPITALITY: [
        "hotel_lobby", "guest_room", "suite", "restaurant_floor", "cafe_floor",
        "bar", "reception", "banquet_hall", "corridor", "other",
    ],
    # loft and exposed-brick OFFICES — no plant, warehouse or machine floor
    Vertical.INDUSTRIAL: [
        "open_plan_office", "private_office", "meeting_room", "reception",
        "breakout", "pantry", "other",
    ],
}


def room_types(vertical: Vertical | str) -> list[str]:
    return _ROOM_TYPES[_v(vertical)]


# default (width_m, length_m) when the user gave no dimensions
_ROOM_DEFAULT_DIMS: dict[Vertical, dict[str, tuple[float, float]]] = {
    Vertical.RESIDENTIAL: {
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
    },
    # sized for covers and circulation, not for a family
    Vertical.HOSPITALITY: {
        "hotel_lobby": (12.0, 9.0),        # seating clusters either side of a walk-through route
        "guest_room": (4.5, 6.0),          # ~27 m2 key: bed, desk, luggage bench, ensuite wall
        "suite": (7.0, 8.0),               # a key plus its own living area
        "restaurant_floor": (14.0, 10.0),  # ~80 covers at ~1.7 m2 each with service aisles
        "cafe_floor": (9.0, 7.0),          # ~30 covers plus the counter
        "bar": (8.0, 6.0),                 # back bar, counter run and standing room
        "reception": (6.0, 4.0),           # front desk plus a queue
        "banquet_hall": (20.0, 14.0),      # ~200 seated at rounds
        "corridor": (2.4, 18.0),           # a guest-floor circulation run
        "other": (6.0, 5.0),
    },
    # office-scale: ~8 m2 per desk including circulation
    Vertical.INDUSTRIAL: {
        "open_plan_office": (16.0, 10.0),  # ~20 desks with aisles
        "private_office": (4.0, 3.6),
        "meeting_room": (6.0, 4.2),        # a table for eight
        "reception": (6.0, 4.0),
        "breakout": (7.0, 5.0),
        "pantry": (4.0, 3.0),
        "other": (6.0, 5.0),
    },
}


def room_default_dims(vertical: Vertical | str) -> dict[str, tuple[float, float]]:
    return _ROOM_DEFAULT_DIMS[_v(vertical)]


_ROOM_KEYWORDS: dict[Vertical, dict[str, str]] = {
    Vertical.RESIDENTIAL: {
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
    },
    Vertical.HOSPITALITY: {
        "hotel lobby": "hotel_lobby", "lobby": "hotel_lobby", "atrium": "hotel_lobby",
        "hotel": "hotel_lobby",
        "guest room": "guest_room", "guestroom": "guest_room", "bedroom": "guest_room",
        "suite": "suite", "penthouse": "suite",
        "restaurant": "restaurant_floor", "dining hall": "restaurant_floor",
        "fine dining": "restaurant_floor", "brasserie": "restaurant_floor",
        "cafe": "cafe_floor", "café": "cafe_floor", "coffee shop": "cafe_floor",
        "bistro": "cafe_floor",
        "bar": "bar", "cocktail": "bar", "speakeasy": "bar",
        "reception": "reception", "front desk": "reception", "check-in": "reception",
        "banquet": "banquet_hall", "ballroom": "banquet_hall", "function hall": "banquet_hall",
        "event hall": "banquet_hall",
        "corridor": "corridor", "hallway": "corridor", "guest floor": "corridor",
    },
    Vertical.INDUSTRIAL: {
        "open plan": "open_plan_office", "open-plan": "open_plan_office",
        "workstation": "open_plan_office", "desks": "open_plan_office",
        "office floor": "open_plan_office", "studio floor": "open_plan_office",
        "private office": "private_office", "cabin": "private_office",
        "executive office": "private_office",
        "meeting room": "meeting_room", "conference room": "meeting_room",
        "boardroom": "meeting_room", "huddle": "meeting_room",
        "reception": "reception", "front desk": "reception", "lobby": "reception",
        "breakout": "breakout", "break out": "breakout", "lounge": "breakout",
        "pantry": "pantry", "kitchenette": "pantry", "tea point": "pantry",
    },
}


def room_keywords(vertical: Vertical | str) -> dict[str, str]:
    return _ROOM_KEYWORDS[_v(vertical)]


ROOM_LABELS: dict[str, str] = {
    "living_room": "Living Room", "bedroom": "Bedroom", "master_bedroom": "Master Bedroom",
    "kids_bedroom": "Kids Bedroom", "kitchen": "Kitchen", "dining_room": "Dining Room",
    "bathroom": "Bathroom", "study": "Study", "balcony": "Balcony", "entry": "Entry",
    "hotel_lobby": "Hotel Lobby", "guest_room": "Guest Room", "suite": "Suite",
    "restaurant_floor": "Restaurant Floor", "cafe_floor": "Cafe Floor", "bar": "Bar",
    "reception": "Reception", "banquet_hall": "Banquet Hall", "corridor": "Corridor",
    "open_plan_office": "Open Plan Office", "private_office": "Private Office",
    "meeting_room": "Meeting Room", "breakout": "Breakout", "pantry": "Pantry",
    "other": "Room",
}

# ── Counting the brief ───────────────────────────────────────────────────
# Every vertical is sold in a different unit. The BHK / bedroom regexes are
# residential-only: "40-key hotel" must never read as 40 bedrooms.
_BHK = re.compile(r"(\d)\s*-?\s*bhk", re.IGNORECASE)
_BED = re.compile(r"(\d|one|two|three|four)\s*-?\s*(?:bed(?:room)?s?)\b", re.IGNORECASE)
_KEYS = re.compile(r"(\d{1,4})\s*-?\s*(?:keys?\b|guest\s*rooms?\b)", re.IGNORECASE)
_COVERS = re.compile(r"(\d{1,4})\s*-?\s*(?:covers?|seats?)\b", re.IGNORECASE)
_DESKS = re.compile(r"(\d{1,4})\s*-?\s*(?:desks?|workstations?|people|staff|seats?)\b", re.IGNORECASE)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}


def bedroom_count(text: str) -> int | None:
    """'2BHK', '3 bhk', 'two bedroom' → number of bedrooms (residential only)."""
    m = _BHK.search(text)
    if m:
        return int(m.group(1))
    m = _BED.search(text)
    if m:
        token = m.group(1).lower()
        return _WORDS.get(token, int(token) if token.isdigit() else None)
    return None


def brief_counts(text: str, vertical: Vertical | str) -> dict[str, int]:
    """What the brief counts, in the unit its vertical is sold in: bedrooms
    (residential), keys and covers (hospitality), desks (industrial). Used for
    room notes and sizing — never expanded into one room per key."""
    v = _v(vertical)
    out: dict[str, int] = {}
    if v is Vertical.RESIDENTIAL:
        beds = bedroom_count(text)
        if beds:
            out["bedrooms"] = beds
        return out
    if v is Vertical.HOSPITALITY:
        keys = _KEYS.search(text)
        if keys:
            out["keys"] = int(keys.group(1))
        covers = _COVERS.search(text)
        if covers:
            out["covers"] = int(covers.group(1))
        return out
    desks = _DESKS.search(text)
    if desks:
        out["desks"] = int(desks.group(1))
    return out


# ── Objects ──────────────────────────────────────────────────────────────
# semantic types the catalog and asset registry understand
_RESIDENTIAL_SEMANTIC_TYPES: list[str] = [
    "sofa", "loveseat", "armchair", "ottoman", "coffee_table", "side_table",
    "tv_unit", "television", "dining_table", "chair", "bar_stool", "bed", "wardrobe",
    "bedside_table", "dresser", "desk", "bookshelf", "sideboard", "console",
    "rug", "floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "plant",
    "mirror", "wall_art", "curtains", "vase", "sculpture", "pillows", "lantern",
    "kitchen_island", "kitchen_counter", "fridge", "bathtub", "vanity",
    # open-reading additions (photo decor and architecture)
    "fireplace", "stool", "pedestal", "books", "tray", "sconce", "wall_shelf",
    "wall_clock", "throw", "candle", "basket", "other",
]

# contract pieces the two commercial verticals need on top of the domestic
# list (bar_stool is already there). Kept before "other" so the prompts'
# "everything except other" slice still reads naturally.
_CONTRACT_SEMANTIC_TYPES: list[str] = [
    "banquette", "booth_seating", "restaurant_table", "bar_counter",
    "reception_desk", "workstation", "office_chair", "meeting_table",
    "lounge_sofa",
]


def _with_contract(base: list[str]) -> list[str]:
    return base[:-1] + _CONTRACT_SEMANTIC_TYPES + base[-1:]   # keep "other" last


_SEMANTIC_TYPES: dict[Vertical, list[str]] = {
    Vertical.RESIDENTIAL: _RESIDENTIAL_SEMANTIC_TYPES,
    Vertical.HOSPITALITY: _with_contract(_RESIDENTIAL_SEMANTIC_TYPES),
    Vertical.INDUSTRIAL: _with_contract(_RESIDENTIAL_SEMANTIC_TYPES),
}

# the union, for code that maps a name to a type without knowing the project
ALL_SEMANTIC_TYPES: list[str] = _SEMANTIC_TYPES[Vertical.HOSPITALITY]


def semantic_types(vertical: Vertical | str) -> list[str]:
    return _SEMANTIC_TYPES[_v(vertical)]

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
    "television": "appliance", "tv_unit": "storage", "wardrobe": "storage", "dresser": "storage", "bookshelf": "storage", "sideboard": "storage",
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
    # contract pieces (hospitality + office)
    "banquette": "seating", "booth_seating": "seating", "office_chair": "seating",
    "lounge_sofa": "seating",
    "restaurant_table": "table", "reception_desk": "table", "workstation": "table",
    "meeting_table": "table",
    "bar_counter": "storage",
}

# where a type sits when the reader does not say
PLACEMENT_BY_TYPE: dict[str, str] = {
    "wall_art": "wall", "mirror": "wall", "sconce": "wall", "wall_shelf": "wall", "wall_clock": "wall",
    "television": "wall",
    "curtains": "wall",
    "pendant_lamp": "ceiling", "chandelier": "ceiling",
    "table_lamp": "on_surface", "vase": "on_surface", "books": "on_surface", "tray": "on_surface",
    "sculpture": "on_surface", "lantern": "on_surface", "pillows": "on_surface", "throw": "on_surface",
    "candle": "on_surface",
    # contract pieces all stand on the floor; spelled out rather than implied
    "banquette": "floor", "booth_seating": "floor", "restaurant_table": "floor",
    "bar_counter": "floor", "reception_desk": "floor", "workstation": "floor",
    "office_chair": "floor", "meeting_table": "floor", "lounge_sofa": "floor",
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
    "restaurant_table": None, "meeting_table": None, "workstation": None, "reception_desk": None,
    "bar_counter": 1.05, "banquette": 0.45, "booth_seating": 0.45, "lounge_sofa": 0.45,
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
    ("closet", "wardrobe"), ("bed", "bed"), ("headboard", "bed"), ("television", "television"), ("flat screen", "television"),
    ("tv", "tv_unit"), ("media", "tv_unit"),
    ("fridge", "fridge"), ("refrigerator", "fridge"), ("counter", "kitchen_counter"), ("island", "kitchen_island"),
    ("dining chair", "chair"), ("chair", "chair"), ("bathtub", "bathtub"), ("vanity", "vanity"),
]


def canonical_type(name: str, given: str = "") -> str:
    """Closest canonical type for an open item name; `given` wins when valid."""
    g = (given or "").strip().lower().replace(" ", "_")
    if g in ALL_SEMANTIC_TYPES and g != "other":
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
    # contract pieces first: "reception desk" must beat "desk" and "lounge
    # sofa" must beat "sofa". None of these phrases occur in a domestic
    # brief, so the residential reading order is untouched.
    "reception_desk": ["reception desk", "front desk"],
    "lounge_sofa": ["lounge sofa", "lobby sofa"],
    "banquette": ["banquette"],
    "booth_seating": ["booth seating", "booth"],
    "restaurant_table": ["restaurant table", "cafe table", "bistro table"],
    "bar_counter": ["bar counter", "back bar", "drinks counter"],
    "workstation": ["workstation", "work station", "bench desk"],
    "office_chair": ["office chair", "task chair", "desk chair"],
    "meeting_table": ["meeting table", "conference table", "boardroom table"],
    "sofa": ["sofa", "couch", "sectional"],
    "loveseat": ["loveseat", "two seater", "2 seater", "two-seater"],
    "armchair": ["armchair", "accent chair", "lounge chair"],
    "ottoman": ["ottoman", "pouf", "pouffe"],
    "coffee_table": ["coffee table", "center table", "centre table"],
    "side_table": ["side table", "end table"],
    "television": ["television", "wall mounted tv", "wall-mounted television", "flat screen",
                   "flatscreen", "tv screen", "smart tv"],
    "tv_unit": ["tv unit", "tv stand", "tv console", "media unit", "media console"],
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

# Types that are genuinely implausible OUTSIDE these rooms, and nothing else.
#
# Deliberately NOT derived from OBJECT_DEFAULT_ROOM below. That map answers a
# different question - "where does this go when the brief does not say" - and
# reading it as plausibility would flag ordinary designs: it puts `rug` and
# `plant` in the living room, so a rug in a bedroom would come back suspicious,
# and the sample bedroom render has one. It also has no entry for `bathtub` at
# all, so it could not catch the hallucination that prompted this list - a
# freestanding bath read into a living room.
#
# Short on purpose. A type absent from here is NEVER flagged: most furniture is
# genuinely room-agnostic, and false suspicion trains a reviewer to click past
# warnings, which costs more than the occasional oddity it would have caught.
ROOM_BOUND_TYPES: dict[str, set[str]] = {
    "bathtub": {"bathroom"},
    "vanity": {"bathroom"},
    "kitchen_counter": {"kitchen"},
    "kitchen_island": {"kitchen"},
    "fridge": {"kitchen"},
    "bed": {"bedroom", "master_bedroom", "kids_bedroom", "guest_room", "suite"},
}


def room_bound(semantic_type: str) -> set[str]:
    """Rooms where this type is plausible, or an empty set meaning 'anywhere'."""
    return ROOM_BOUND_TYPES.get((semantic_type or "").strip().lower(), set())


# where an object lives when the brief does not say
OBJECT_DEFAULT_ROOM: dict[str, str] = {
    "fireplace": "living_room", "stool": "living_room", "pedestal": "living_room", "books": "living_room",
    "tray": "living_room", "sconce": "living_room", "wall_shelf": "living_room", "wall_clock": "living_room",
    "throw": "living_room", "candle": "living_room", "basket": "living_room", "table_lamp": "bedroom",
    "vase": "living_room", "sculpture": "living_room", "lantern": "living_room", "pillows": "living_room",
    "sofa": "living_room", "loveseat": "living_room", "armchair": "living_room",
    "ottoman": "living_room", "coffee_table": "living_room", "side_table": "living_room",
    "tv_unit": "living_room", "television": "living_room",
    "rug": "living_room", "floor_lamp": "living_room",
    "plant": "living_room", "wall_art": "living_room", "console": "entry",
    "mirror": "entry", "bookshelf": "study", "desk": "study",
    "dining_table": "dining_room", "chair": "dining_room", "sideboard": "dining_room",
    "pendant_lamp": "dining_room", "chandelier": "dining_room",
    "bed": "bedroom", "wardrobe": "bedroom", "bedside_table": "bedroom",
    "dresser": "bedroom", "table_lamp": "bedroom", "curtains": "bedroom",
    "kitchen_island": "kitchen", "bar_stool": "kitchen", "kitchen_counter": "kitchen", "fridge": "kitchen",
    # contract pieces (the room type only exists in their own vertical, so a
    # residential project never resolves to one of these)
    "banquette": "restaurant_floor", "booth_seating": "restaurant_floor",
    "restaurant_table": "restaurant_floor", "bar_counter": "bar",
    "lounge_sofa": "hotel_lobby", "reception_desk": "reception",
    "workstation": "open_plan_office", "office_chair": "open_plan_office",
    "meeting_table": "meeting_room",
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
    # hospitality
    "boutique_hotel": ["#EDE6DB", "#C8B49B", "#7E6A57", "#2F3A3A", "#B8894C"],
    "brasserie": ["#F2E7D5", "#D6B77E", "#8E4A3C", "#2C3A34", "#1C1A18"],
}
DEFAULT_PALETTE = STYLE_PALETTES["modern"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "room"

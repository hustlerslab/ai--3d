# Style presets — what exists per vertical

The product's own reference for the vocabulary each vertical offers: room
types, the sizes assumed when the client gives none, style tags, palettes and
the objects the planner can place.

Source of truth is `aether-backend/app/intelligence/vocab.py` (and
`app/catalog/catalog.py` for the built-in models). This file describes it; the
code decides it. Room type and style tag strings are exact — the frontend sends
room types verbatim as `RoomHint.type`, and both are used as JSON-schema
`enum`s, so a typo is a rejected answer.

Reach the maps through the accessors (`room_types()`, `room_default_dims()`,
`room_keywords()`, `style_tags()`, `semantic_types()`, `brief_counts()`), never
directly. An unknown vertical raises.

---

## Residential — homes and apartments

Default vertical. Unchanged from before verticals existed; every previous
project is on this path.

### Rooms (11)

| Room type | Default size (W × L m) |
|---|---|
| `living_room` | 6.0 × 4.6 |
| `bedroom` | 4.0 × 3.6 |
| `master_bedroom` | 4.8 × 4.2 |
| `kids_bedroom` | 3.8 × 3.4 |
| `kitchen` | 3.8 × 3.0 |
| `dining_room` | 4.2 × 3.6 |
| `bathroom` | 2.4 × 2.0 |
| `study` | 3.4 × 3.0 |
| `balcony` | 3.0 × 1.5 |
| `entry` | 2.4 × 2.0 |
| `other` | 3.5 × 3.5 |

Prompt guidance: ceiling 3.0 m, generous mid-range apartment sizes, never below
the stated low end.

Counted from the brief: **bedrooms** — `2BHK`, `3 bhk`, "two bedroom". A
`master bedroom` / `primary bedroom` mention promotes the first one.

### Style tags (22)

`modern`, `contemporary`, `minimal`, `warm`, `scandinavian`, `japandi`,
`industrial`, `luxury`, `classic`, `traditional`, `bohemian`, `coastal`,
`mid_century`, `moody`, `dark`, `light`, `natural`, `rustic`, `art_deco`,
`indian_contemporary`, `warm_neutral`, `mediterranean`.

This list is the base for all three verticals.

---

## Hospitality — hotels, restaurants, cafés, bars

### Rooms (10)

| Room type | Default size (W × L m) | Sized for |
|---|---|---|
| `hotel_lobby` | 12.0 × 9.0 | seating clusters either side of a walk-through route |
| `guest_room` | 4.5 × 6.0 | a ~27 m² key: bed, desk, luggage bench, ensuite wall |
| `suite` | 7.0 × 8.0 | a key plus its own living area |
| `restaurant_floor` | 14.0 × 10.0 | ~80 covers at ~1.7 m² each with service aisles |
| `cafe_floor` | 9.0 × 7.0 | ~30 covers plus the counter |
| `bar` | 8.0 × 6.0 | back bar, counter run, standing room |
| `reception` | 6.0 × 4.0 | front desk plus a queue |
| `banquet_hall` | 20.0 × 14.0 | ~200 seated at rounds |
| `corridor` | 2.4 × 18.0 | a guest-floor circulation run |
| `other` | 6.0 × 5.0 | — |

Prompt guidance: ceiling 3.4 m, commercial scale.

Counted from the brief: **keys** (`40 keys`, `40 guest rooms`) and **covers**
(`80 covers`, `80 seats`). A count becomes a note on the matching room — "40
keys in the property" on the guest room — never forty rooms on one floor plate.

### Style tags (24)

The residential 22 plus two house styles:

| Tag | Brief phrases | Palette (wall, floor, upholstery, accent, accent) |
|---|---|---|
| `boutique_hotel` | "boutique", "boutique hotel" | `#EDE6DB` `#C8B49B` `#7E6A57` `#2F3A3A` `#B8894C` |
| `brasserie` | "brasserie", "bistro" | `#F2E7D5` `#D6B77E` `#8E4A3C` `#2C3A34` `#1C1A18` |

Both are hospitality-only. `style_tags()` filters them out elsewhere, so
"boutique" reads as a style word only on a hospitality project.

---

## Industrial — loft-style offices and workspaces

An aesthetic, not a manufacturing vertical. Factory and manufacturing-facility
design is permanently out of scope and the engine declines briefs that ask for
it; see `aether-backend/README.md` and
[`ADR-001-verticals.md`](ADR-001-verticals.md).

### Rooms (7)

| Room type | Default size (W × L m) | Sized for |
|---|---|---|
| `open_plan_office` | 16.0 × 10.0 | ~20 desks with aisles, ~8 m² per desk |
| `private_office` | 4.0 × 3.6 | — |
| `meeting_room` | 6.0 × 4.2 | a table for eight |
| `reception` | 6.0 × 4.0 | front desk plus a queue |
| `breakout` | 7.0 × 5.0 | — |
| `pantry` | 4.0 × 3.0 | — |
| `other` | 6.0 × 5.0 | — |

Prompt guidance: ceiling 3.2 m, office scale.

Counted from the brief: **desks** (`40 desks`, `40 workstations`, `40 people`,
`40 staff`, `40 seats`).

### Style tags (22)

The residential list unchanged. The loft look is the existing `industrial` tag
(brief phrases "industrial", "loft", "exposed brick"), palette `#DED9D2`
`#9E9891` `#6B6560` `#3D3A37` `#A65E2E`.

---

## Objects

`semantic_types(vertical)` is what the analysis and the object planner may
name. Residential has 48 types; hospitality and industrial share the same 57 —
the residential list plus nine contract pieces:

`banquette`, `booth_seating`, `restaurant_table`, `bar_counter`,
`reception_desk`, `workstation`, `office_chair`, `meeting_table`,
`lounge_sofa`.

(`bar_stool` was already in the residential list and is reused as-is.)

Nine built-in catalog models cover them:

| Vertical | `asset_id` | Piece | W × H × D (m) | Rooms | ₹ |
|---|---|---|---|---|---|
| Hospitality | `cat_restaurant_table` | Restaurant Table for Four | 0.9 × 0.75 × 0.9 | restaurant / cafe floor, bar, banquet hall | 16,000 |
| Hospitality | `cat_banquette` | Wall Banquette (2 m run) | 2.0 × 1.1 × 0.65 | restaurant / cafe floor, bar | 52,000 |
| Hospitality | `cat_booth` | Dining Booth | 1.6 × 1.25 × 1.8 | restaurant floor, bar | 78,000 |
| Hospitality | `cat_bar_counter` | Bar Counter (3 m run) | 3.0 × 1.1 × 0.7 | bar, cafe floor, hotel lobby | 145,000 |
| Hospitality | `cat_lounge_sofa` | Lobby Lounge Sofa | 2.4 × 0.78 × 0.95 | hotel lobby, suite, breakout, reception | 96,000 |
| Hospitality | `cat_reception_desk` | Reception Desk | 2.6 × 1.1 × 0.8 | reception, hotel lobby | 120,000 |
| Industrial | `cat_workstation` | Bench Workstation | 1.6 × 0.74 × 0.8 | open plan / private office | 24,000 |
| Industrial | `cat_office_chair` | Task Chair | 0.65 × 1.05 × 0.65 | open plan / private office, meeting room, reception | 18,000 |
| Industrial | `cat_meeting_table` | Meeting Table for Eight | 2.4 × 0.75 × 1.1 | meeting room, private office | 68,000 |

The rest of the built-in catalog (sofas, beds, tables, lamps, plants) is
vertical-neutral and serves all three; the asset ladder (reuse → modify →
procedural) is unchanged.

Vertical-neutral tables that every vertical shares: `LIGHTING_MOODS`,
`STYLE_PALETTES`, `STYLE_KEYWORDS`, `ROOM_LABELS`, and the open-reading set
(`FAMILIES`, `PLACEMENTS`, `FAMILY_BY_TYPE`, `PLACEMENT_BY_TYPE`,
`FAMILY_DEFAULTS`, `SURFACE_HEIGHT`, `SUPPORT_PREFERENCE`, `NAME_KEYWORDS`).

## What the mock provider furnishes

With no API key the deterministic mock runs the whole pipeline. `ROOM_SETS` in
`app/intelligence/mock_provider.py` gives every room type above a starter set
— a `restaurant_floor` gets 8 tables, 12 chairs, 2 banquettes, 2 booths and 4
pendants; an `open_plan_office` gets 12 workstations, 12 task chairs, a
bookshelf, 4 pendants and plants. When a brief names no rooms at all the mock
assumes a living room + bedroom (residential), a lobby + guest room
(hospitality), or an open-plan floor + meeting room (industrial), and says so
in a warning.

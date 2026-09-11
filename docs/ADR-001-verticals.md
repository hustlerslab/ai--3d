# ADR-001 — Verticals are an explicit field, not an inference

Date: 2026-09-11. Status: accepted, shipped.
Scope: `aether-backend` (`app/projects`, `app/intelligence`, `app/db`),
`aether-frontend` (Studio step 1).

## Context

The pipeline was written for one market. Room types, default room sizes, the
brief keyword table, the style tags and the object vocabulary were flat
module-level constants in `app/intelligence/vocab.py`, and every one of them
described a home: `bedroom`, `kitchen`, `balcony`, "2BHK", living rooms sized
for a family. The JSON schemas handed to the provider for constrained decoding
(`ANALYSIS_SCHEMA`, `STYLE_SCHEMA`) were built from those constants at import
time.

Hotel, restaurant and loft-office briefs arrive anyway. On the flat vocabulary
they degraded in ways that looked like small errors and were not: a "40-key
boutique hotel" read as forty bedrooms, because the BHK/bedroom regex was the
only counting rule there was; a restaurant floor came back as a `dining_room`
at 4.2 × 3.6 m, because that is what the room enum offered and what the
defaults said a dining room measures. The model was answering correctly inside
a vocabulary that did not contain the right answer.

There was a second problem with the same shape. "Industrial" is a style people
ask for — loft, exposed brick, open plan. It is also one word away from
manufacturing-facility design: safety compliance, structural load calculation,
fire-code and machine-guarding logic, the Factories Act, the OSH Code. That is
regulated professional work; getting it wrong hurts people, and nothing here is
built to do it. Whatever shape the market vocabulary took, the boundary had to
be somewhere a reader and a test could both point at.

## Decision

A `vertical` field on the project — `residential` (default) | `hospitality` |
`industrial` — chosen by the user at creation, stored on the project row, fixed
after the project leaves `CREATED`.

1. **The user picks it; nothing infers it.** Three radios in Studio step 1,
   `residential` preselected.
2. **It selects a vocabulary, not a pipeline.** The flat constants became
   `dict[Vertical, ...]` maps behind accessors — `room_types()`,
   `room_default_dims()`, `room_keywords()`, `style_tags()`,
   `semantic_types()`, plus `brief_counts()`, which reads what the brief counts
   in the unit its market is sold in (bedrooms, keys and covers, desks). An
   unknown vertical raises rather than falling back to residential. Genuinely
   shared vocabularies (lighting moods, palettes, the open-reading families and
   surface tables) stayed flat.
3. **It travels inside `InputBundle`.** `InputBundle` is already a parameter of
   all three `IntelligenceProvider` Protocol methods, so **no Protocol
   signature changed** and a replacement vendor still drops in unmodified.
   `ANALYSIS_SCHEMA` / `STYLE_SCHEMA` became `analysis_schema(vertical)` /
   `style_schema(vertical)` inside the shipped providers, because the room and
   tag `enum`s are the mechanism that keeps an answer inside its vocabulary and
   an enum built at import time cannot know the project.
4. **It is locked after `CREATED`.** `PATCH /api/projects/{id}` returns 409
   `VERTICAL_LOCKED` if the change would alter a vertical that analysis has
   already assumed.
5. **The exclusion is enforced, not merely documented.** `Vertical` has exactly
   three members, and a scope guard on the brief returns 422 `OUT_OF_SCOPE` for
   facility and regulatory phrases (`manufacturing plant`, `factory floor`,
   `machine guarding`, `load bearing`, `structural load`, `fire code`,
   `factories act`, `osh code`, …) on create, update and input upload.

Storing the field also forced a real migration ladder in `app/db/sqlite.py`
(`MIGRATIONS`, `_add_column()` guarded by `PRAGMA table_info`). The
pre-existing bug it exposed: `SCHEMA_VERSION` was stamped unconditionally while
no `ALTER` path existed, so column additions never reached an existing
database. See the backend README.

### Alternatives rejected

**Infer the vertical from the brief.** Cheapest to build, one classifier call
or a keyword table, no UI. Rejected on two counts. The user cannot correct a
wrong guess: a guess is not a field, so there is nothing to disagree with, and
a mis-read brief silently produces a whole project's work in the wrong
vocabulary. And it makes the exclusion boundary unenforceable — if the vertical
is a property of the text rather than a choice on the record, "what does this
product decline to do" has no stable answer, and the refusal becomes a
judgement about a building rather than a fixed statement about the product.

**A fully data-driven preset library now** — verticals, rooms, sizes and style
sets loaded from files, authored without code changes. Rejected as premature.
It solves an authoring problem nobody has yet: there are three verticals,
all edited by the same people who edit the Python, and no request for a fourth.
The maps in `vocab.py` are the same data one indirection earlier, so the
library remains available the moment the authoring problem appears.

**A separate pipeline per vertical** — parallel handlers, prompts and planners.
Rejected: it triples the tested surface for no capability gain. The stages do
not differ. Only the vocabulary the stages draw on differs, and one pipeline
reading a keyed map expresses that exactly, with one set of tests.

## Why the guard is intentionally weak, and where the real boundary is

This section exists so nobody fixes the wrong thing. Read it before changing
`_brief_refusal` or the room vocabularies.

`_brief_refusal` in `app/api/projects_routes.py` is a lowercase substring scan
over ten fixed phrases. It is **not** a security control and was never meant to
be one. Measured, it has at least 17 working evasions — double spaces
(`manufacturing  plant`), hyphens (`manufacturing-plant`), Cyrillic and
fullwidth lookalikes, and terms simply not on the list (bare `factory`,
`shop floor`, `assembly line`, `egress`, `NFPA`, `OSHA`). It also never sees
four brief-text surfaces: the project `name`, `room_hints[].name`, room names
inside `dimensions`, and the `intent` / `constraints` free text on
`PATCH /projects/{id}/analysis`.

**All of that is acceptable, because the guard computes nothing.** Its only
possible outcome is a refusal. Text that slips past is inert. The guard is a
courtesy: it tells someone asking for factory work, early and in plain words,
that they are in the wrong product — before they spend an afternoon uploading
photographs.

**The real boundary is the closed room vocabulary.** A project can only produce
room types from `vocab.room_types(vertical)`, and none of the three lists holds
a production space. No code anywhere in the backend evaluates a load, a fire
code, an egress path, an occupancy limit or a machine guard:
`test_no_compliance_logic_anywhere_in_the_backend` scans every `.py` under
`app/`, `blender/` and `scripts/` and asserts that regulatory vocabulary appears
only inside the refusal list and its comments. A brief that evades the guard
entirely still comes out the far end as offices —
`test_a_bypassed_factory_brief_still_produces_only_interior_rooms` drives a
confirmed evasion end to end and asserts exactly that.

Two consequences for whoever comes next:

1. **Do not harden the guard into something that looks authoritative.** Unicode
   normalisation, fuzzy matching or a longer phrase list would make it *feel*
   like a control without becoming one. A substring scan over user-authored
   prose cannot be made sound, and the first person to believe it is sound is
   the person who then relaxes something that matters. If the product ever needs
   to refuse reliably, that is a different mechanism — an explicit
   classification step with a recorded decision — and it needs its own ADR.
2. **Do not weaken the vocabulary closure on the grounds that the guard covers
   it.** It does not. If `room_types()` ever gains a free-text path, or a
   provider's room type stops being coerced against the vertical's list, the
   boundary is gone no matter what the guard says. The two tests named above are
   the ones to keep green.

One known soft spot, recorded rather than fixed: `RoomAnalysis.type` is a plain
`str`, so the vertical constraint is enforced by the JSON-schema enum and
`coerce.py` — that is, only for providers whose raw JSON is coerced. A Protocol
provider returning typed objects directly is not filtered and *can* hand back a
room type outside its vertical. The constraint holds for the mock and for the
schema-constrained live providers; it is not a structural invariant.
`test_a_vendor_provider_cannot_return_a_room_outside_its_vertical` pins this as
a strict xfail, so it fails the day someone closes it.

## Consequences

- The room, style and object vocabularies are per-vertical from stage 5 through
  the object plan. A hotel project cannot come back with `bedroom`, and an
  office project cannot come back with `banquet_hall`: the schema `enum`
  forbids it and the coercion layer re-checks it, so a provider that ignores
  the schema is still caught.
- Adding a vertical means adding an enum member and an entry in each map in
  `vocab.py`, plus the frontend's `verticals.ts`. Nothing else. Adding one is
  also the only way to widen scope, which is the point.
- The vocabulary maps are now the thing to keep in step across two repos.
  `verticals.test.ts` asserts the frontend's room-type spellings literally
  against the backend enum, because a typo there is a silently mis-typed room.
- Existing projects are `residential`, backfilled by the migration's `NOT NULL
  DEFAULT`. Every previous behaviour is the residential path unchanged.
- The vertical is named on the AI-stage events, which carry `duration_ms`, so
  per-vertical stage cost is measurable from the event feed. It is measured,
  not billed: there is no credits system, no payment integration and no
  subscription tier in this codebase.
- Locking the vertical after `CREATED` means a user who picked wrong starts
  over. That is deliberate — the analysis, moodboard, plan and layout were all
  composed for the old vertical, and a re-analysis in place would leave
  half-converted artifacts on disk.
- The scope guard is a substring scan and will occasionally decline a brief
  that merely mentions a phrase in passing. That trade is accepted: it declines
  work rather than evaluating any of it, and a false refusal costs a reworded
  sentence while a false acceptance costs something that cannot be undone. The
  aesthetic words (`industrial`, `loft`, `exposed brick`, `warehouse`) are
  deliberately not in the list, so a loft-look flat is ordinary work.

### Breaking change — seven names were removed, not renamed

Seven public module-level names were **deleted outright** when the flat
constants became per-vertical maps. They have no new spelling; do not go looking
for one. Each is replaced by an accessor that takes a `Vertical`:

| Removed | Replaced by |
|---|---|
| `vocab.ROOM_TYPES` | `vocab.room_types(vertical)` |
| `vocab.ROOM_KEYWORDS` | `vocab.room_keywords(vertical)` |
| `vocab.ROOM_DEFAULT_DIMS` | `vocab.room_default_dims(vertical)` |
| `vocab.SEMANTIC_TYPES` | `vocab.semantic_types(vertical)` |
| `vocab.STYLE_TAGS` | `vocab.style_tags(vertical)` |
| `prompts.ANALYSIS_SCHEMA` | `prompts.analysis_schema(vertical)` |
| `prompts.STYLE_SCHEMA` | `prompts.style_schema(vertical)` |

No shims were added, because nothing imports them. Verified before the change
landed: one branch (`ai-3d`), one worktree, no stashes, a single contributor,
and no in-tree importer outside `vocab.py`'s own internals. Out-of-tree code
cannot be proven absent — an external provider importing any of these breaks on
import, and the fix is the accessor in the right-hand column.
`test_the_shared_helper_constants_a_pre_feature_provider_used_still_exist` pins
all seven as strict xfails, so the removal is recorded in the suite rather than
only in this document.

Note the scope of the compatibility claim: **the `IntelligenceProvider` Protocol
is unchanged** — its three method signatures are byte-identical to the previous
commit, and a provider that never reads the vertical runs against all three.
That is a narrower statement than "`app.intelligence` is backward compatible",
which is not true.

Not in scope of this decision, and still absent from the codebase: auth,
row-level security, a hosted database (this is local SQLite), and any billing
of any kind. The auth and authorization gap is the subject of its own plan —
see [`AUTH_PLAN.md`](AUTH_PLAN.md).

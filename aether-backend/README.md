# Aether backend — Allure hybrid local pipeline

Local-first engine that turns a client's photos and brief into a structured
scene, builds it in Blender, and delivers a 360° walkthrough the client opens
in the browser. One laptop runs everything: FastAPI on `:8000`, SQLite,
worker threads, and Blender as a headless subprocess.

```
inputs ─▶ analyze ─▶ scene_plan ─▶ build ─▶ preview ─▶ walkthrough ─▶ film (optional)
 (ai)      (ai)        (ai)      (render)  (render)     (render)      (render)
```

The full plan, decisions and milestone status live in
[`../docs/ALLURE_HYBRID_LOCAL_PLAN.md`](../docs/ALLURE_HYBRID_LOCAL_PLAN.md).
Decision records live beside it: [`ADR-001 — verticals`](../docs/ADR-001-verticals.md).
What each vertical offers is catalogued in [`STYLE_PRESETS.md`](../docs/STYLE_PRESETS.md).

## Run

```bash
cd aether-backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cp .env.example .env            # set BLENDER_PATH (portable Blender 5.2 LTS) and GEMINI_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Without a Gemini key the intelligence layer runs on a deterministic mock, so
the whole pipeline still works end to end. Without `BLENDER_PATH` the render
lane refuses jobs with `BLENDER_NOT_CONFIGURED`; everything up to the 3D scene
plan (which the web viewer shows) still works.

The frontend (`../aether-frontend`, Next.js on `:3001`) drives all of this from
the Studio; the public share page is `/w/{projectId}`.

## Pipeline stages

| Job | Lane | Project stage | Writes |
|---|---|---|---|
| `analyze` | ai | ANALYZING → DESIGN_SPEC_READY | `analysis/design_analysis.json`, `style_spec.json`, `moodboard_spec.json` |
| `scene_plan` | ai | ASSET_PLANNING → ASSETS_READY | `planning/object_plan.json`, `asset_plan.json`, `scene_spec.json`; a `Scene` in `data/scenes/` |
| `resolve_assets` | ai | — | re-runs the asset decision on the current scene after edits |
| `build` | render | SCENE_BUILDING → SCENE_VALIDATING | `blender/build_manifest.json`, `scene.blend`, `validation_report.json`, `previews/build_preview.png` |
| `preview` | render | CAMERA_PLANNING → PREVIEW_RENDERING | `blender/camera_path.json`, 2K panoramas, `outputs/web/tour.json` |
| `walkthrough` | render | FINAL_RENDERING → COMPLETED | 4K panoramas, hero stills, `outputs/manifest.json` |
| `film` | render | — | `renders/walkthrough_<profile>.mp4` + poster |

Every stage writes checkpoint files under `data/projects/{project_id}/`
(DPR §20 layout). A retry or a restart resumes from the last checkpoint;
successful outputs are never overwritten unless `force` is passed.

## Verticals

Every project carries a `vertical`, chosen when it is created and stored on the
project row:

| Value | Covers | Default rooms when the brief names none |
|---|---|---|
| `residential` (default) | Homes and apartments | living room + bedroom |
| `hospitality` | Hotels, restaurants, cafés, bars | hotel lobby + guest room |
| `industrial` | Loft-style offices and workspaces | open-plan floor + meeting room |

The vertical picks a vocabulary and nothing else. There is one pipeline, one
set of job handlers and one provider interface; what changes is the list of
room types, the default room dimensions, the room keyword table, the style tags
and the semantic types the model is allowed to answer with. A hotel brief must
never be offered `bedroom`, and an office brief must never be offered
`banquet_hall`.

`app/intelligence/vocab.py` keeps those as `dict[Vertical, ...]` behind
accessors. Reach for the accessor, not the map:

| Accessor | Returns |
|---|---|
| `room_types(vertical)` | the room `type` enum used in the analysis schema |
| `room_default_dims(vertical)` | `{room_type: (width_m, length_m)}` when the client gave no sizes |
| `room_keywords(vertical)` | brief phrase → room type (`"ballroom"` → `banquet_hall`) |
| `style_tags(vertical)` | the style tag enum |
| `semantic_types(vertical)` | the object types the planner and catalog understand |
| `brief_counts(text, vertical)` | what the brief counts, in the unit its market is sold in: `bedrooms`, `keys` / `covers`, `desks` |

An unknown vertical raises `ValueError` instead of falling back to residential:
a silent fallback would hand a hotel project the domestic vocabulary and
nothing downstream would notice. `brief_counts` is why "40-key hotel" no longer
reads as forty bedrooms — the BHK and bedroom regexes are residential-only, and
a count becomes a note on the room, never one room per key.

Vocabularies that are genuinely shared stay flat: `LIGHTING_MOODS`,
`STYLE_PALETTES`, `STYLE_KEYWORDS`, `ROOM_LABELS`, and the whole open-reading
set (`FAMILIES`, `PLACEMENTS`, `FAMILY_BY_TYPE`, `PLACEMENT_BY_TYPE`,
`FAMILY_DEFAULTS`, `SURFACE_HEIGHT`, `SUPPORT_PREFERENCE`, `NAME_KEYWORDS`).

What each vertical actually contains — rooms, sizes, style tags, catalog pieces
— is written down once in
[`../docs/STYLE_PRESETS.md`](../docs/STYLE_PRESETS.md).

### How the vertical reaches the provider

`InputBundle.vertical`, set once in `build_input_bundle()` from the project
row. `InputBundle` is already a parameter of all three `IntelligenceProvider`
methods, so **the Protocol signatures did not change**:

```python
class IntelligenceProvider(Protocol):
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis: ...
    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec: ...
    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan: ...
```

That is the architectural point of the design: a replacement vendor still drops
in unmodified, and a provider that does not care about verticals can ignore the
field entirely.

Inside the shipped providers the constrained-decoding schemas became functions
of the vertical — `analysis_schema(vertical)` and `style_schema(vertical)`
replace the old module-level `ANALYSIS_SCHEMA` / `STYLE_SCHEMA` constants —
because the room and tag `enum`s are the mechanism that keeps the answer inside
the right vocabulary, and an enum built at import time cannot know the project.
`coerce_analysis` and `coerce_style` then re-check the answer against the same
vocabulary the schema offered, so a provider that ignores the schema is still
caught. Three prompt fragments vary per vertical: the room-listing rule (a
hotel lobby estimated at apartment scale is a wrong answer, not a small one),
the `room.type` list, and the closing object-planning rule.

`analyze` names the vertical on the `analyze.inputs`, `analyze.analysis` and
`analyze.style` events, `scene_plan` on `plan.objects`, and the `analyze` job
result carries `"vertical"`. Those events carry `duration_ms`, so per-vertical
stage cost is measurable straight from the event feed. Nothing is billed:
there is no credits system, no payment integration and no subscription tier in
this codebase.

### "Industrial" means offices — factories are permanently out of scope

`industrial` is an aesthetic: loft-style offices, exposed brick, open-plan
floors, meeting rooms, breakouts, pantries. It is not a manufacturing vertical
and will not become one.

Literal factory and manufacturing-facility design is permanently out of scope —
safety compliance, structural load calculation, fire-code and machine-guarding
logic, the Factories Act, the OSH Code. This is not a missing feature waiting
for a milestone. It is regulated professional work, getting it wrong hurts
people, and nothing in this codebase is built to do it.

Two things enforce it:

1. **A three-member enum.** `Vertical` has exactly `residential`,
   `hospitality`, `industrial`. There is no fourth value to select, and no room
   type, style tag or catalog item anywhere in `vocab.py` describes a plant, a
   warehouse or a machine floor.
2. **A scope guard on the brief.** `_scope_refusal()` in
   `app/api/projects_routes.py` scans the incoming description for facility and
   regulatory phrases — `manufacturing plant`, `manufacturing facility`,
   `factory floor`, `machine guarding`, `load bearing`, `load-bearing`,
   `structural load`, `fire code`, `factories act`, `osh code` — and returns
   **422 `OUT_OF_SCOPE`** on the first hit, naming the phrase and what the
   product does do instead. It runs on `POST /api/projects`,
   `PATCH /api/projects/{id}` and `POST /api/projects/{id}/inputs`, and it
   refuses before anything is created or stored.

The guard **declines work**; it does not evaluate anything. It is a plain
substring scan whose only outcome is a refusal — no load is checked, no code is
interpreted, no judgement is made about any building. The aesthetic vocabulary
(`industrial`, `loft`, `exposed brick`, `warehouse`) is deliberately absent
from the term list: a loft-look flat is ordinary work.

## Layers

- `app/projects` — project records, inputs, the stage state machine, the on-disk layout.
- `app/jobs` — job registry, two-lane runner (`ai` ×2 threads, `render` ×1 owning the GPU), retry, restart recovery, events feed.
- `app/intelligence` — contracts (`DesignAnalysis`, `StyleSpec`, `ObjectPlan`, `AssetPlan`), the mock provider, the Gemini vision provider, and a resilient wrapper that falls back per stage.
- `app/planning` — hub-and-spoke floor-plan layout, asset decision (reuse → modify → procedural → generate), scene compiler (relation-aware placement through the existing spatial validator).
- `app/scene`, `app/spatial`, `app/walkthrough`, `app/design`, `app/catalog`, `app/assets`, `app/materials` — the original scene engine: patches, validation, guided tour, AI proposals, catalog and CC0 asset/material registries. Unchanged API.
- `app/blender` — manifest compiler (Y-up scene → Z-up manifest) and the subprocess runner.
- `blender/scripts` — pure functions of the manifest: rooms, walls with openings, procedural stand-ins, GLB import, PBR materials, lighting, validation, preview still, panoramas, film. No business logic, no network.

## Database schema and migrations

`app/db/sqlite.py` holds two halves and they do different jobs:

- **`SCHEMA`** — `CREATE TABLE IF NOT EXISTS` statements. These only ever build
  a *fresh* database. They do nothing at all to a file that already exists.
- **`MIGRATIONS`** — `list[tuple[int, Callable[[sqlite3.Connection], None]]]`,
  the steps that change an existing database.

`Database._migrate()` runs the `CREATE`s, reads the version stamped in
`meta.schema_version`, runs every migration whose version is higher than that,
then stamps `SCHEMA_VERSION`. An absent or unreadable marker reads as `0`,
which replays the whole ladder — every step is written to be safe to run twice.

The ladder is new. Before it, `SCHEMA_VERSION` was stamped unconditionally and
no `ALTER` path existed anywhere, so a column added to a `CREATE TABLE`
statement reached new databases only and never reached one that had already
been created. The version number said 1 either way. Adding `projects.vertical`
is what surfaced the bug. **If you add a column, it needs a migration step, or
existing installs break on the first query that names it.**

### Adding the next migration

Say v3 adds `projects.budget_inr`.

1. Add the column to the `CREATE TABLE` in `SCHEMA`, for fresh databases:

   ```python
   budget_inr  INTEGER NOT NULL DEFAULT 0,
   ```

2. Write the step. `_add_column()` checks `PRAGMA table_info` first, so it is
   idempotent for free:

   ```python
   def _v3_project_budget(c: sqlite3.Connection) -> None:
       """projects.budget_inr — the client's stated budget, 0 when unsaid."""
       _add_column(c, "projects", "budget_inr", "INTEGER NOT NULL DEFAULT 0")
   ```

3. Append it to the ladder, keyed by the version that introduces it:

   ```python
   MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
       (2, _v2_project_vertical),
       (3, _v3_project_budget),
   ]
   ```

4. Bump `SCHEMA_VERSION` to `3`.

Rules for a step: it takes the open connection and returns nothing; it must be
safe to run twice; it runs inside the same transaction as the `CREATE`s, so a
raising step rolls everything back and the version is not stamped. Give a new
`NOT NULL` column a `DEFAULT` — SQLite backfills existing rows with it as the
column is added, which is exactly how every pre-existing project became
`residential` without a separate backfill pass.

Storage is SQLite on the local disk (`data/allure.db`). There is no hosted
database, no auth layer and no row-level security to configure.

## API

Project pipeline (all long work returns a job to poll):

```
POST  /api/projects                       {name, description, room_hints, vertical}
GET   /api/projects/{id}                  project + inputs + jobs + checkpoints + outputs
PATCH /api/projects/{id}                  {name?, description?, room_hints?, vertical?}
POST  /api/projects/{id}/inputs           multipart: description, dimensions (json), references[]
POST  /api/projects/{id}/analyze          {force}         GET/PATCH /api/projects/{id}/analysis
POST  /api/projects/{id}/scene-plan       {force}         GET /api/projects/{id}/scene-spec
POST  /api/projects/{id}/assets/resolve
POST  /api/projects/{id}/build            {force, preview, preview_profile}   GET /api/projects/{id}/build
POST  /api/projects/{id}/preview          {force, profile}
POST  /api/projects/{id}/walkthrough      {force, profile, hero_stills}
POST  /api/projects/{id}/film             {force, profile}
GET   /api/projects/{id}/tour             read-only web package for /w/{id}
GET   /api/projects/{id}/events?after=    progress feed
GET   /api/jobs/{job_id}                  job + its events        GET /api/jobs/types
GET   /files/projects/{id}/{path}         project artifacts (confined to the project folder)
```

Scene engine routes (`/api/scenes/*`, `/api/catalog`, `/api/assets`,
`/api/materials`) are unchanged; a compiled project scene is an ordinary scene.

Responses use one envelope: reads `{success, data}`, writes flat
`{success, ...}`, errors `{success: false, error: {code, message, retryable}}`.

Two error codes belong to the vertical:

| Code | Status | When |
|---|---|---|
| `VERTICAL_LOCKED` | 409 | `PATCH /api/projects/{id}` would change `vertical` on a project that has left `CREATED`. Everything analysed so far assumed the old one, so the change is refused; start a new project instead. |
| `OUT_OF_SCOPE` | 422 | The brief asks for regulated industrial-facility work. Nothing is created, updated or stored. Raised by `POST /projects`, `PATCH /projects/{id}` and `POST /projects/{id}/inputs`. |

## Render profiles (RTX 3050, 4 GB)

| Profile | Engine | Output | Measured |
|---|---|---|---|
| `preview` still | Eevee | 960×540 | ~1 s |
| `hero_still` | Cycles | 1080p, 256 spp + denoise | ~53 s |
| `pano_preview` | Cycles | 2048×1024 equirect, 32 spp | ~16 s per node |
| `pano_final` | Cycles | 4096×2048, 128 spp | minutes per node |
| film `preview` | Eevee | 960×540 @ 12 fps | ~150 s for 27 s |
| film `standard` | Eevee | 1080p @ 24 fps | tens of minutes |

## Tests

```bash
.venv/Scripts/python -m pytest -q                         # 50+ tests, no keys needed
BLENDER_PATH=D:/Blender/blender.exe .venv/Scripts/python -m pytest -q   # also runs the Blender-marked tests
```

The `blender` marker covers the smoke render, the full build, panoramas,
the film, the timeout kill, and the golden project (`tests/fixtures/golden_project`)
against the DPR §30 acceptance criteria.

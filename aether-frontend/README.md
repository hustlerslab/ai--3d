# Aether Frontend — Allure Walkthrough

The standalone walkthrough product. Three routes:

| Route | What | Backend |
|---|---|---|
| `/` | Walkthrough Studio — the homeowner journey (project → moodboard → 3D space → share → designer) | Aether engine |
| `/3d` | Interactive 3D viewer — orbit, first-person walk, guided tour, AI design proposals, real furniture | Aether engine |
| `/cinematic` | Photo → cinematic film studio | RE Walkthrough Pro engine (optional) |

## Run

Backend first (from `../aether-backend`):

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Then this app:

```bash
npm install
npm run dev
```

Open http://localhost:3001. Port 3001 is deliberate so it can run beside the
Allure demo site on 3000.

## Configuration

Copy `.env.example` to `.env.local` if the engines run somewhere other than
localhost. No API keys belong here — they live in the backend's `.env`.

## Verticals

Step 1 of the Studio asks which market the project is for. Three native radios
in a fieldset (`VerticalField` in
`src/features/walkthrough-studio/components/walkthrough-studio.tsx`) — arrow
keys move between them for free, and the focus ring is drawn on the card
through `:has()` so the visually hidden input still shows focus.

| Value | Label | Blurb |
|---|---|---|
| `residential` (default) | Residential | Homes and apartments |
| `hospitality` | Hospitality | Hotels, restaurants, cafés and bars |
| `industrial` | Industrial | Loft-style offices and workspaces |

`src/features/studio/verticals.ts` is the single source for everything that
varies by vertical:

| Export | What it does |
|---|---|
| `VERTICAL_OPTIONS`, `DEFAULT_VERTICAL` | the selector's options, residential first |
| `roomTypeOptions(vertical)` | the room-type `<select>` list for the "Room sizes" rows |
| `defaultRoomType(vertical)` | what "+ Add room" inserts |
| `coerceRoomType(vertical, type)` | keeps a room row submittable when the vertical changes under it |
| `roomTypeLabel(type)` | `master_bedroom` → "master bedroom" |
| `isVerticalLocked(stage)` | true once the project has left `CREATED` |

The room types and styles each vertical offers are catalogued in
[`../docs/STYLE_PRESETS.md`](../docs/STYLE_PRESETS.md).

Room type strings must match the backend's spelling exactly — they travel to
the API as `RoomHint.type`. `verticals.test.ts` asserts them literally against
`aether-backend/app/projects/schema.py` for that reason.

"Industrial" here is an aesthetic — loft-style offices — not
manufacturing-facility work. The exclusion and the guard that enforces it are
described in the backend README.

### The locked state

Once a project has left `CREATED` the vertical is fixed: the analysis,
moodboard and layout were all composed for it. The selector is then replaced by
a read-only `StatusPill` carrying the chosen label, its blurb, and a line
saying why — deliberately not a disabled radio group. A disabled control says
"unavailable"; this says "decided, and here is why". Continuing from step 1 on
a locked project walks forward rather than quietly starting a second project.

Sending the vertical a project already has is a no-op; changing it is what
fails.

### Error surfacing

`EngineError` renders a `ProjectsApiError` from the API client. Two codes are
boundaries rather than breakages, so they get the info tone, `role="status"`, a
heading, and a line on what to do next — nothing is broken and there is nothing
to retry:

| Code | Status | Heading → next step |
|---|---|---|
| `OUT_OF_SCOPE` | 422 | "That part sits outside what Allure designs" → describe the interior instead; anything structural or code-related belongs with your own engineer. |
| `VERTICAL_LOCKED` | 409 | "The vertical is already set for this project" → carry on with the vertical shown, or start a new project for a different one. |

Every other code (`NETWORK_ERROR`, `PARTIAL_UPLOAD`, `TIMEOUT`, `UNKNOWN`, …)
keeps the warning tone and `role="alert"`. `NETWORK_ERROR` additionally prints
the command that starts the engine.

## Tests

```bash
npm test          # vitest run
```

`vitest` is the only test dependency and this is the first test infrastructure
in the repo — there was none before. No config file, no jsdom, no component
rendering: `src/features/studio/verticals.test.ts` covers plain TypeScript
(the vertical vocabulary, the room-type coercion and the lock rule) and runs on
vitest's defaults.

## Layout

```
src/
├── app/                      routes + shell (layout.tsx) + tokens (globals.css)
├── features/
│   ├── studio/               projects API client, shared types, verticals.ts (+ its test)
│   ├── walkthrough-studio/   the step-based journey
│   ├── walkthrough3d/        R3F viewer, Aether API client, camera rigs, materials
│   └── walkthrough/          cinematic film client (port 4000 engine)
├── components/shared/        Button, StatusPill
├── components/portal/        PageHeader
└── lib/                      format (INR), utils (cn), mock data used by the studio
```

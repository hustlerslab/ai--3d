# Allure — photos and a brief, into a 3D space you can walk

A local-first pipeline. A client uploads photographs of their room and describes
what they want; the engine reads the brief, paints a moodboard, reads the
moodboard back into a list of real objects, lets a human confirm each one, buys
3D meshes for the confirmed ones, lays them out in a room, and serves the result
as an interactive scene in the browser.

Everything runs on one machine: FastAPI and SQLite on `:8000`, Next.js on
`:3001`, Blender as a headless subprocess, and a Stable Diffusion pipeline on
the local GPU. The only things that leave the laptop are the vision-model call
and, if you turn it on, the paid mesh generation.

```
upload ─▶ analyze ─▶ moodboard ─▶ read & confirm ─▶ generate meshes ─▶ plan 3D ─▶ walk it
          (ai)        (gpu)        (ai + human)       (paid)          (render)   (browser)
```

## Layout

| Path | What |
|---|---|
| [aether-backend/](aether-backend/) | FastAPI engine, job runner, intelligence layer, planner, Blender driver. [Its README](aether-backend/README.md) is the reference for stages, schema and API. |
| [aether-frontend/](aether-frontend/) | Next.js 15 app: the Studio (`/`), the 3D viewer (`/3d`), the share page (`/w/{id}`), the cinematic route (`/cinematic`). [Its README](aether-frontend/README.md). |
| [aether-backend/blender/scripts/](aether-backend/blender/scripts/) | Pure functions of a build manifest — rooms, walls, materials, lighting, panoramas. No business logic, no network. |
| [docs/](docs/) | The plan and the decision records. Start at [ALLURE_HYBRID_LOCAL_PLAN.md](docs/ALLURE_HYBRID_LOCAL_PLAN.md). |
| [aether-backend/research/](aether-backend/research/) | Bounded probes that answered a question and stopped. Not part of the product. |
| `sample/` | Reference photographs and furniture models. The `.glb` files are deliberately untracked (535 MB); the jpegs are committed. |

---

## Setup

This section gets every working part running. Each tier after step 2 is
optional and says what it unlocks — the engine starts and the whole journey
runs with none of them, on deterministic mocks.

### Prerequisites

| | Version used here | Notes |
|---|---|---|
| Python | 3.14 | 3.11+ should be fine. |
| Node | 24 | 20+ should be fine. |
| Blender | 5.2 LTS, portable | Only for the render lane. Newer majors move the compositor API — see *Known limits*. |
| GPU | NVIDIA, 6 GB | Only for local image generation. CPU works but is minutes per image. |

### 1. Clone and install

```bash
git clone https://github.com/hustlerslab/ai--3d.git
cd ai--3d

# backend
cd aether-backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux/macOS: .venv/bin/pip
cp .env.example .env
cd ..

# frontend
cd aether-frontend
npm install
cd ..
```

### 2. Run it

Two terminals. The backend runs **without** `--reload` on purpose — a reload in
the middle of a render job kills the job — so restart it by hand after changing
backend code.

```bash
# terminal 1
cd aether-backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000

# terminal 2
cd aether-frontend && npm run dev
```

Open **http://localhost:3001**. `GET http://localhost:8000/api/health` should
answer `{"status":"ok"}`.

At this point the full nine-step journey works end to end on the mock provider:
projects, uploads, a moodboard, the element review, the 3D plan, the viewer and
the share page. What you do not get is a *good* moodboard — the mock is
deterministic, not designed. Add the tiers below for that.

### 3. Vision and design intelligence — the one to add first

This is what reads the client's photographs and the brief. Put a key in
`aether-backend/.env`:

```ini
INTELLIGENCE_PROVIDER=auto     # Claude if ANTHROPIC_API_KEY, else Gemini, else mock
ANTHROPIC_API_KEY=sk-ant-...   # https://console.anthropic.com
# or
GEMINI_API_KEY=...             # https://aistudio.google.com/app/apikey
```

Unlocks: a real reading of the photos, a real style spec, a real object plan,
and the second isolated look that flags mislabelled elements in step 4.

Fully local alternative, no key and no network — slower and weaker, so `auto`
never picks it and you have to ask for it by name:

```ini
INTELLIGENCE_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5vl:3b      # 3b, not 7b: 7b does not fit 6 GB and falls to the CPU
```

Verify: create a project, upload the jpegs from `sample/`, run step 2. The
`analyze.analysis` event in the feed should name your rooms, not the mock's.

### 4. Local image generation (the moodboard) — GPU

The moodboard renders on your own card through Stable Diffusion 1.5 with
IP-Adapter, so the client's own furniture appears rather than a generic room.
No API key, no per-image cost.

`torch` must be the **CUDA** build. `pip install diffusers` pulls CPU-only torch
from PyPI and will silently replace a CUDA install; the symptom is a version
string ending in `+cpu` and minutes per image.

```bash
cd aether-backend
.venv/Scripts/pip install --index-url https://download.pytorch.org/whl/cu126 torch torchvision
.venv/Scripts/pip install "diffusers==0.35.1" "transformers<5" accelerate safetensors
```

Weights download on first use (~4 GB, cached under `~/.cache/huggingface`). Turn
the whole thing off with `SCENE_IMAGE_ENABLED=false`: the moodboard then has no
hero image, the reason lands in `scene_error`, and nothing else changes — a
missing picture never fails the analysis.

Verify:

```bash
.venv/Scripts/python -c "from app.providers import local_image; print(local_image.describe())"
```

The reported torch version must not end in `+cpu`.

### 5. The 3D asset library (CC0)

The planner reuses real furniture before it builds anything. A fresh clone has
an empty library, so every piece falls back to a procedural box.

```bash
cd aether-backend
.venv/Scripts/python scripts/source_cc0.py --dry-run   # list files and sizes, download nothing
.venv/Scripts/python scripts/source_cc0.py --run       # download + ingest
```

Resumable: re-running after a partial failure fetches only what is missing.

### 6. Blender — the render lane

Point at a portable Blender 5.2 LTS executable:

```ini
BLENDER_PATH=D:/Blender/blender.exe
BLENDER_TIMEOUT_SECONDS=1800
```

Unlocks `build`, `preview`, `walkthrough` and `film` — the built `.blend`, the
360° panoramas and the video. Without it those jobs fail fast with
`BLENDER_NOT_CONFIGURED`, and everything up to and including the interactive 3D
plan still works, because the viewer reads the scene spec directly rather than a
render.

Verify: `.venv/Scripts/python -m pytest -q -m blender` (needs `BLENDER_PATH`).

### 7. Meshy — paid mesh generation

**This spends real money.** Each confirmed piece costs 30 credits, charged when
the job runs, whether or not you like the result.

```ini
MESHY_API_KEY=msy_...          # https://www.meshy.ai
MESHY_MAX_PER_PROJECT=6        # a cap, so one large plan cannot drain the account
```

Nothing is bought without a human pressing *Build* on that specific crop in step
4 and confirming. `GET /api/credits` reports the balance, and the Studio shows it
beside the paid step. Leave the key unset and the asset ladder simply never
reaches that rung.

### Running the tests

```bash
cd aether-backend  && .venv/Scripts/python -m pytest -q    # 271 passing, no keys needed
cd aether-frontend && npm test                             # vitest
```

The backend suite is hermetic: it writes to a temp directory and never touches
`aether-backend/data/`.

---

## What works today

The nine steps of the Studio, in order:

| Step | What it does | Needs |
|---|---|---|
| 1 Create Project | Name, brief, vertical (residential / hospitality / industrial) | — |
| 2 Upload & Describe | Up to 12 reference photographs, room dimensions | — |
| 3 Generate Moodboard | One painted image per room, redrawable per room on a fresh seed | tier 4 for a good one |
| 4 Review & Refine | Reads the approved moodboard back into labelled crops; a second isolated look flags the doubtful ones; **a human confirms or rejects each piece** | tier 3 |
| 5 Plan 3D Space | Lays the confirmed pieces out in the room and shows them in the viewer | — |
| 6 Generate 3D Space | Buys meshes for the confirmed pieces | tier 7 |
| 7 View 3D Experience | Orbit, first-person walk, guided tour | — |
| 8 Save / Share | Public read-only page at `/w/{projectId}` | — |
| 9 Connect with Designer | Hand-off | — |

Also working: resuming any project from the history list at the furthest stage
it reached, and deleting a project — which archives the uploads, every moodboard
image and the generated meshes into `data/archive/<id>/` before removing it.

### Known limits — read before trusting the output

- **Generated meshes are plausible, not faithful.** Two independent methods
  (Meshy image-to-3D, and ControlNet conditioned on geometry) hit the same wall:
  position and structure can be made correct, object *identity* cannot. Meshy
  invents convincing detail that was never in the moodboard — a shelf under a
  side table, for instance. This is an open product question, written up in
  [ADR-003 §9](docs/ADR-003-reading-the-moodboard-into-3d.md) and
  [ADR-004](docs/ADR-004-styling-known-geometry.md), not a bug with a fix
  pending.
- **Deleting a project cannot be undone.** The archive keeps the uploads, the
  moodboard images and the generated meshes; the project, its jobs and its
  renders go.
- **Blender 5.2 removed the compositor node the old depth pass used.** The render
  lane is unaffected — only the research depth path was, and it now computes
  depth analytically from the scene spec instead.
- Three catalog meshes have their longest axis on the wrong axis, so mirrors can
  come out rotated.
- Factory and manufacturing-facility design is **permanently out of scope** and
  refused at the API with `OUT_OF_SCOPE`. `industrial` here means loft-style
  offices — an aesthetic, not a regulated engineering domain.

## Where to read next

- [aether-backend/README.md](aether-backend/README.md) — stages, job lanes, database migrations, the full API, render profiles.
- [docs/ALLURE_HYBRID_LOCAL_PLAN.md](docs/ALLURE_HYBRID_LOCAL_PLAN.md) — the plan and milestone status.
- [docs/ADR-003-reading-the-moodboard-into-3d.md](docs/ADR-003-reading-the-moodboard-into-3d.md) — how the moodboard becomes objects, and what that costs.
- [docs/STYLE_PRESETS.md](docs/STYLE_PRESETS.md) — what each vertical actually contains.

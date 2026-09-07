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

## Layers

- `app/projects` — project records, inputs, the stage state machine, the on-disk layout.
- `app/jobs` — job registry, two-lane runner (`ai` ×2 threads, `render` ×1 owning the GPU), retry, restart recovery, events feed.
- `app/intelligence` — contracts (`DesignAnalysis`, `StyleSpec`, `ObjectPlan`, `AssetPlan`), the mock provider, the Gemini vision provider, and a resilient wrapper that falls back per stage.
- `app/planning` — hub-and-spoke floor-plan layout, asset decision (reuse → modify → procedural → generate), scene compiler (relation-aware placement through the existing spatial validator).
- `app/scene`, `app/spatial`, `app/walkthrough`, `app/design`, `app/catalog`, `app/assets`, `app/materials` — the original scene engine: patches, validation, guided tour, AI proposals, catalog and CC0 asset/material registries. Unchanged API.
- `app/blender` — manifest compiler (Y-up scene → Z-up manifest) and the subprocess runner.
- `blender/scripts` — pure functions of the manifest: rooms, walls with openings, procedural stand-ins, GLB import, PBR materials, lighting, validation, preview still, panoramas, film. No business logic, no network.

## API

Project pipeline (all long work returns a job to poll):

```
POST  /api/projects                       {name, description, room_hints}
GET   /api/projects/{id}                  project + inputs + jobs + checkpoints + outputs
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

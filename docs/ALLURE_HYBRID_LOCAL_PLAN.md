# Allure Hybrid Local Pipeline — Implementation Plan

Date: 2026-09-06. Inputs reconciled: the **Phase 1 Backend Architecture** diagram
(11-stage AI pipeline, cloud-shaped infra), the **Hybrid Local Architecture DPR**
(local-first, SceneSpec contract, Blender automation), and the **code that already
exists** in `aether-backend` / `aether-frontend`.

Verdict in one line: keep the DPR's local-first deployment and SceneSpec contract,
adopt the diagram's 11 stages as the pipeline's stage names and state machine, and
build it *on top of* the current patch-based scene engine rather than beside it.

---

## 1. Where the three inputs agree and disagree

| Topic | Diagram (Phase 1) | DPR | Existing code | Decision |
|---|---|---|---|---|
| Deployment | Cloud: API gateway, JWT, CDN, GPU workers | One laptop, no hosted backend | FastAPI on 8000, Next on 3001, all local | **DPR.** Local now; the diagram is the later hosted shape. No auth in local mode. |
| Queue | Redis / RabbitMQ | Local worker processes | None (everything runs inside the request) | **SQLite job table + in-process worker threads.** Same job/status API shape the diagram wants, no broker. |
| Database | PostgreSQL | SQLite | JSON files | **SQLite for projects, inputs, jobs, events, outputs. Scenes stay JSON** (they are already versioned artifacts with undo/redo). |
| Storage / CDN | Object storage + CDN | `data/projects/{id}/…` | `data/assets`, `data/scenes` | **DPR layout**, served by the existing `/files` static mount. |
| LLM | "GPT-6 Astra" | Provider-abstracted `IntelligenceProvider` | Gemini adapter + deterministic mock | **Provider interface, Gemini first, mock always available.** |
| 3D generation | "3D Generation Models" | Custom path only for unique objects | Meshy configured, no adapter | **Off by default.** Procedural fallback so a build never waits on generation. |
| Scene contract | Not specified | SceneSpec (Z-up, degrees) | `Scene` (Y-up, radians, patch-mutated) | **`Scene` is the SceneSpec.** Extend it; compile a Z-up *build manifest* for Blender. |
| Renderer | "Web App (Three.js/WebGL)" | Blender preview + final walkthrough | R3F viewer, tour keyframes | **The client sees the walkthrough in the browser.** Web viewer = the interactive walkthrough (all tiers). Blender = quality that flows back into the website (360° panorama tour, baked scene GLB); video is a secondary export. See §8A. |
| Rendering hardware | GPU worker pool | Local CPU/GPU | — | **This laptop: RTX 3050 (4 GB), 16 GB RAM.** Eevee for video, Cycles for hero stills only. |

Diagram box → where it lives locally:

| Diagram box | Local home |
|---|---|
| 1 User Input Layer | Studio "Upload & Describe" step → `POST /projects/{id}/inputs` |
| 2 API Gateway | FastAPI itself (rate limiting / auth deferred to hosted phase) |
| 3 Core Backend Services | `app/projects`, `app/jobs`; notifications = events feed; analytics = event log |
| 4 Job Queue & Orchestrator | `app/jobs` (SQLite table, worker threads, checkpoints, retry) |
| 5 Input Analysis | `app/intelligence/agents/input_analyzer.py`, `style_interpreter.py` |
| 6 AI Reasoning & Scene Planning | `spatial_planner.py`, `furniture_planner.py` |
| 7 Prompt Optimization | Stage-specific prompt builders inside each agent (no separate service) |
| 8 Asset & Material Generation | `asset_decision.py` + existing `app/assets`, `app/materials`, `app/catalog` |
| 9 3D Scene Assembly | `scene_compiler.py` → `Scene` via `commit_patch`; then `blender/scripts/*` |
| 10 Validation & Refinement | existing `app/spatial/validation.py` + `quality_validator.py` + Blender scene validation |
| 11 Walkthrough Generation | existing `app/walkthrough/service.py` + `create_camera_path.py`, `render_*.py` |
| AI & External Services | `app/providers` (gemini, polyhaven, meshy stub) |
| Data & Storage Layer | `data/allure.db` + `data/projects/{id}` |
| GPU & Rendering Workers | one Blender subprocess at a time on the local GPU |
| Delivery Layer | Next.js Studio; MP4 + stills + package zip under `/files` |

---

## 2. Hardware and toolchain facts that shape the plan

Verified on this machine on 2026-09-06:

- GPU: NVIDIA GeForce RTX 3050 Laptop, 4 GB VRAM. Also an AMD iGPU (ignore).
- RAM 16 GB. CPU Ryzen 5 5600H (6c/12t). Python 3.13.7.
- Blender was not installed on 2026-09-06; installed 2026-09-07 (see below).
- FFmpeg 9.0 is installed (winget, Gyan build).
- `bpy` is not in the backend venv and should stay out of it (3.13 wheel availability and no GPU control).

Consequences:

- **Blender 5.2.1 LTS is installed** (portable build at `D:\Blender\blender.exe`; verified headless on 2026-09-07, OptiX and CUDA both see the RTX 3050). Point `BLENDER_PATH` at it. Pin the version; Blender's Python API changes between releases. In 5.x the only Eevee engine id is `BLENDER_EEVEE` (it is Eevee Next).
- Drive Blender by subprocess: `blender -b blender/templates/base.blend --python blender/scripts/build_scene.py -- --manifest <path>`. One Blender process at a time (single GPU).
- Render profiles (all 16:9):

| Profile | Engine | Resolution | FPS | Samples | Use |
|---|---|---|---|---|---|
| `preview` | Eevee | 960×540 | 12 | 16 | Validate path, exposure, clipping. Minutes. |
| `standard` | Eevee | 1920×1080 | 24 | 64 | Client walkthrough video. 45 s ≈ 1080 frames ≈ 20–50 min. |
| `hero_still` | Cycles (OptiX) | 1920×1080 | — | 256 + denoise | 3–6 marketing stills per project. Textures capped at 2K for 4 GB VRAM. |
| `panorama` | Cycles (OptiX) | 4096×2048 equirect | — | 128 + denoise | One 360° node per tour keyframe (8–12 per apartment), 2–4 min each. Feeds the in-browser tour (§8A). |
| `bake` | Cycles (OptiX) | 1K–2K lightmap per object | — | 64 + denoise | Bakes lighting into a web GLB for the premium real-time viewer (§8A). 10–25 min per apartment. |

Cycles video is out of scope on this hardware. Cycles stills, panoramas and bakes are not: they are one frame each, and they are what the website shows.

---

## 3. Target architecture (local)

```
aether-frontend (Next 15, :3001)         aether-backend (FastAPI, :8000)
  Studio wizard ---- polls ------>  /api/projects, /api/jobs, /api/projects/{id}/events
  R3F viewer   ---- patches ----->  /api/scenes/*  (unchanged)
                                       |
                                       v
                               app/jobs  (SQLite jobs + events, worker threads,
                                          checkpoints, retry, resume)
                                       |
          +----------------------------+-----------------------------+
          v                            v                             v
  app/intelligence            app/scenespec                    app/blender
  agents 5-8 (mock/Gemini)    Scene ext + validator +          runner, manifest, log capture
  DesignAnalysis, StyleSpec,  build-manifest compiler          -> blender/scripts/*.py
  ObjectPlan, AssetPlan       (Y-up -> Z-up)                      build_room, import_assets,
          |                            |                            place_assets, apply_materials,
          +------> existing: scene/patches, spatial, walkthrough,   setup_lighting, create_camera_path,
                   assets, materials, catalog                       render_preview, render_final
                                                                             |
                                          data/projects/{id}/ <--------------+
                                          input/ analysis/ planning/ assets/ blender/ previews/ renders/ logs/
```

Principles carried over from the DPR and kept as hard rules:

1. No raw prompt ever reaches Blender. Blender reads `build_manifest.json` only.
2. The web `Scene` (patch pipeline, validator) remains the single system of record. Blender is a consumer.
3. Reuse a local asset before generating. Procedural before Meshy.
4. Every stage writes a checkpoint file; resume finds the last complete checkpoint.
5. No API request blocks on analysis or rendering. Everything long is a job.

---

## 4. Data model

### 4.1 SceneSpec = `Scene` plus four additions

Keep `app/scene/schema.py` conventions (meters, +Y up, −Z forward, yaw radians). Add, all optional with defaults so existing scene files still load:

```python
class StyleSpec(BaseModel):
    name: str                      # "modern_warm_minimal"
    tags: list[str]
    palette: list[str]             # hex
    materials: list[str]           # material_ids from app/materials
    lighting_mood: Literal["warm_daylight","cool_daylight","evening","studio"]

class LightingSpec(BaseModel):
    mood: str
    sun_azimuth_deg: float = 135
    sun_elevation_deg: float = 40
    exposure_ev: float = 0.0
    interior_lights: list[InteriorLight] = []   # per-room area/point lights

class CameraPlan(BaseModel):
    type: Literal["walkthrough","orbit","stills"] = "walkthrough"
    duration_seconds: int = 45
    seconds_per_room: float = 8
    keyframes: list[TourKeyframe] = []          # filled by walkthrough planner
    hero_shots: list[SavedView] = []

class Scene(...):                 # existing fields, plus:
    spec_version: str = "1.0"
    style: Optional[StyleSpec] = None
    lighting: Optional[LightingSpec] = None
    camera_plan: Optional[CameraPlan] = None

class SceneObject(...):           # existing fields, plus:
    source_strategy: Literal["local_asset","local_modified","procedural","generated"] = "procedural"
    material_overrides: dict[str, str] = {}     # slot -> material_id
```

The DPR's example SceneSpec (Z-up, degrees) is the **Blender manifest** shape, not the canonical scene. Conversion is one function: `(x, y, z) → (x, −z, y)`, `rotation_y` rad → `rotation_euler.z` deg.

### 4.2 Intelligence outputs (Pydantic, versioned, stored under `analysis/` and `planning/`)

- `DesignAnalysis` — intent, room list with dimensions or `estimated: true`, constraints, existing furniture spotted in photos, confidence.
- `StyleSpec` — as above.
- `ObjectPlan` — `[{category, semantic_type, room_id, priority, approx_dimensions, style_notes, relation}]`.
- `AssetPlan` — `[{object_id, strategy, asset_id?, material_overrides?, procedural_params?, generation_prompt?}]`.
- `ValidationReport` — errors, warnings, readiness.
- `AgentInput` / `AgentOutput` envelopes exactly as DPR §8 (`project_id, stage, status, confidence, result, warnings[], next_action`).

### 4.3 SQLite (`data/allure.db`)

Tables: `projects`, `inputs`, `analyses`, `scene_specs` (pointer rows to the JSON scene + version), `jobs`, `events`, `outputs`. Assets and materials registries stay as they are (JSON, working, tested).

### 4.4 Project storage

Exactly the DPR §20 layout under `data/projects/{project_id}/`. Checkpoint = presence of the stage's output file (`analysis/design_analysis.json`, `planning/scene_spec.json`, `blender/build_manifest.json`, `blender/scene.blend`, `previews/preview.mp4`, `renders/walkthrough.mp4`, `outputs/manifest.json`).

---

## 5. Pipeline state machine and jobs

Stage names take the diagram's numbering; statuses are the DPR's.

| # | Stage (job type) | Status while running | Checkpoint written | Worker lane |
|---|---|---|---|---|
| — | project created, inputs uploaded | `CREATED` → `INPUT_RECEIVED` | `input/` | request thread |
| 5 | `analyze` | `ANALYZING` → `DESIGN_SPEC_READY` | `analysis/design_analysis.json`, `moodboard_spec.json` | `ai` lane |
| 6–7 | `scene_plan` | `ASSET_PLANNING` | `planning/object_plan.json` | `ai` lane |
| 8 | `resolve_assets` | `ASSET_PLANNING` → `ASSETS_READY` | `planning/asset_plan.json`, `assets/` | `ai` lane |
| 9 | `compile_scene` | (part of scene_plan) | `planning/scene_spec.json` + committed `Scene` | `ai` lane |
| 9 | `build` | `SCENE_BUILDING` → `SCENE_VALIDATING` | `blender/build_manifest.json`, `scene.blend`, `validation_report.json` | `render` lane |
| 11 | `camera_plan` | `CAMERA_PLANNING` | `blender/camera_path.json` | `ai` lane |
| 11 | `preview` | `PREVIEW_RENDERING` | `previews/` | `render` lane |
| 11 | `walkthrough` | `FINAL_RENDERING` → `COMPLETED` | `renders/`, `outputs/manifest.json` | `render` lane |

Job mechanics (`app/jobs/`):

- `Job{job_id, project_id, type, status(QUEUED|RUNNING|SUCCEEDED|FAILED|RETRYING), attempt, max_attempts, checkpoint, error, started_at, finished_at, log_path}`.
- Two worker lanes as `ThreadPoolExecutor`s started in the FastAPI lifespan: `ai` (2 threads, network-bound) and `render` (1 thread, owns the GPU). Blender runs as a subprocess from the render lane with stdout/stderr teed to `logs/`.
- Retry policy per DPR §24: failures retry from the last checkpoint, never rebuild earlier stages. A render failure re-runs at `preview` profile first.
- Events: every transition writes `events(project_id, job_id, stage, status, message, ts, duration_ms)`; the UI polls `GET /projects/{id}/events?after=<id>`.
- Hosting later: the same `Job` rows can be claimed by a remote worker; nothing in the API changes. This is the diagram's box 4 without a broker.

---

## 6. API additions

Existing `/api/scenes/*`, `/api/catalog`, `/api/assets`, `/api/materials` stay untouched. New, mirroring DPR §17:

```
POST /api/projects                          (exists; add description, room hints)
POST /api/projects/{id}/inputs              multipart: description.txt, references[], dimensions json
GET  /api/projects/{id}
POST /api/projects/{id}/analyze             -> job
GET  /api/projects/{id}/analysis            DesignAnalysis + StyleSpec (+ moodboard spec)
POST /api/projects/{id}/scene-plan          -> job (plan + resolve + compile -> Scene committed)
GET  /api/projects/{id}/scene-spec          the Scene (same payload as /scenes/{scene_id})
POST /api/projects/{id}/assets/resolve      -> job (re-run resolution after user edits)
POST /api/projects/{id}/build               -> job (Blender build + scene validation)
POST /api/projects/{id}/preview             -> job (camera plan + preview render)
POST /api/projects/{id}/walkthrough         -> job (final render + package) {profile}
GET  /api/projects/{id}/outputs             manifest: video, stills, scene.blend, scene_spec, report
GET  /api/projects/{id}/events?after=       progress feed
GET  /api/jobs/{job_id}
```

Envelope unchanged (`{success, data}` / `{success:false, error:{code,message,retryable}}`).

---

## 7. Intelligence layer (`app/intelligence/`)

```python
class IntelligenceProvider(Protocol):
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis: ...
    def create_style_spec(self, analysis: DesignAnalysis) -> StyleSpec: ...
    def plan_objects(self, analysis, style, catalog_summary) -> ObjectPlan: ...
    def validate_scene(self, scene: Scene) -> ValidationReport: ...
```

- `providers/mock_provider.py` — deterministic: keyword rules from description, palette from image average colours (Pillow), rooms from dimensions or defaults. Runs with zero API keys; this is what tests and the golden project use.
- `providers/gemini_provider.py` — extends the existing `app/providers/gemini.py` with inline image parts, `responseSchema`, one stage-specific prompt per call (DPR §27), JSON repair retry once, then fall back to mock for that stage with a warning in `AgentOutput.warnings`.
- Agents never emit coordinates. `spatial_planner` and `furniture_planner` produce zones, priorities and relations; the existing `design/service.py` planner (`plan_operations`, wall-aligned and relation candidates) turns them into positions, and `commit_patch` validates. This is the DPR's "Blender must never receive raw text" rule applied one layer earlier.
- `asset_decision.py` resolution order per object:
  1. `catalog.search(semantic_type, require_model=True, max_width)` within ±15 % of planned dimensions → `local_asset`.
  2. Same asset with scale ≤ ±25 % or a material override → `local_modified`.
  3. Semantic type in the procedural set (`bed, rug, wardrobe, lamp, tv_unit, shelf, table, seat, plant, box`) → `procedural` (these are exactly today's web primitives, so both renderers agree).
  4. Otherwise `generated` only if `MESHY_API_KEY` is set and the object is flagged `unique`; the build proceeds with a procedural stand-in and swaps when the asset validates.

---

## 8. Blender automation (`blender/`)

```
blender/
  templates/base.blend        world (Nishita sky), colour management (AgX), unit=meters, collections
  scripts/
    build_scene.py            orchestrator: parse --manifest, run stages, checkpoint after each
    manifest.py               dataclasses mirroring build_manifest.json (Z-up, metres, degrees)
    build_room.py             floor/ceiling from room polygons, walls from segments with boolean openings
    procedural.py             bmesh primitives for the procedural set, dims from manifest
    import_assets.py          bpy.ops.import_scene.gltf on normalized GLBs; verify bbox vs record
    place_assets.py           location/rotation/scale from manifest; parent to room collection
    apply_materials.py        MaterialRecord maps -> Principled BSDF; tile_size_m -> mapping scale
    setup_lighting.py         sun from lighting spec, portal/area lights at windows, per-room fill, exposure
    create_camera_path.py     keyframes -> Catmull-Rom -> Bezier curve, Follow Path + Track To empty
    validate_scene.py         object count vs manifest, bbox overlaps, camera clip test, missing textures -> JSON
    render_preview.py / render_final.py   profile -> Eevee/Cycles settings, PNG sequence + H.264 MP4
```

Rules: scripts are pure functions of the manifest; no network; no business logic; each stage saves `scene.blend` so a later failure resumes from the file. `app/blender/runner.py` builds the command, sets `--python-exit-code 1`, enforces a timeout per profile, and parses a final `ALLURE_RESULT {…}` line from stdout.

Camera path reuses the existing `generate_tour()` keyframes (room order via doors, pans to the three largest objects). Blender only smooths and renders them, so the web tour, the panorama nodes and the video follow the same route.

Additional scripts for web delivery: `render_panoramas.py` (equirect camera at each keyframe, `panorama` profile), `bake_lightmaps.py` (UV2 unwrap, Cycles combined/diffuse bake per object, atlas per room), `export_web_scene.py` (glTF export of the baked scene with `KHR_texture_basisu`/KTX2 textures and Draco geometry, plus `tour.json`).

---

## 8A. Web delivery: the walkthrough the client sees

Requirement: **the client experiences the 3D walkthrough on the website**, not as a downloaded video. So Blender's job is to raise the quality of what the browser shows. Three delivery modes, all served from `data/projects/{id}/outputs/web/` through the existing `/files` mount, all using the tour route from `generate_tour()`:

| Mode | What the browser loads | Quality | Client cost | Tier |
|---|---|---|---|---|
| **Explore** (real-time) | The existing R3F viewer: normalized GLBs + PBR material maps, orbit / first-person / guided tour | Good, real-time lit | Needs a laptop-class GPU; phones struggle with 2K maps | Draft, Standard |
| **Tour** (360° nodes) | `panos/node_XX.jpg` + `tour.json`: equirect panorama per keyframe, hotspots to neighbouring nodes, auto-play along the route | Cycles quality, path-traced light and reflections | Tiny: one texture at a time, runs on any phone | Standard (Eevee panos), Premium (Cycles panos) |
| **Explore Premium** (baked real-time) | `scene_baked.glb`: one compressed GLB with Cycles lighting baked into lightmaps, loaded by the same viewer with unlit lightmapped materials | Near-Cycles look at real-time speed | Moderate: one GLB of 20–60 MB | Premium |
| Film (secondary) | `walkthrough.mp4` | Eevee | Streams anywhere | Optional export for sharing on social |

Build order inside the plan: Tour first (fastest path from Blender quality to the browser, works on every device, and the same keyframes already drive the web tour), then Explore Premium (bake + export), then Film.

Web package contract, `outputs/web/tour.json`:

```json
{
  "project_id": "proj_…",
  "scene_id": "scene_…",
  "scene_version": 12,
  "modes": ["explore", "tour", "explore_premium"],
  "explore": { "scene_url": "/api/scenes/scene_…" },
  "explore_premium": { "glb_url": "/files/projects/proj_…/outputs/web/scene_baked.glb", "size_bytes": 41230000 },
  "tour": {
    "nodes": [
      { "id": "n01", "room_id": "living_room", "label": "Entry",
        "position": [1.2, 1.6, -0.8], "yaw_deg": 90,
        "pano_url": "/files/projects/proj_…/outputs/web/panos/n01.jpg",
        "links": ["n02"] }
    ],
    "route": ["n01", "n02", "n03"],
    "autoplay_seconds_per_node": 6
  },
  "film": { "mp4_url": "…", "poster_url": "…" }
}
```

Frontend pieces: a `PanoramaTour` component (three.js sphere with an equirect texture, hotspot sprites, crossfade between nodes, gyroscope on mobile), a `BakedSceneView` that loads `scene_baked.glb` into the existing canvas with lightmapped materials and the existing camera rigs, and a public read-only route **`/w/[projectId]`** that renders the Experience view from `tour.json` alone, so the client's share link never touches editing APIs.

---

## 9. Frontend wiring (`aether-frontend`)

Studio steps map to the DPR §22 flow. Mock modules are replaced step by step; the step ids stay.

| Studio step | Today | After |
|---|---|---|
| Create Project | `aether.createProject` | same + description field |
| Upload & Describe | staged previews only | `POST inputs` with real upload progress (reuse the XHR uploader from `features/walkthrough`) |
| Generate Moodboard | mock moodboards | `analyze` job → Analysis Review: rooms, style tags, palette swatches, materials, spotted furniture; user corrects dimensions |
| Review & Refine | mock | `scene-plan` job → embedded R3F viewer as the **instant preview**; edits go through existing patches/proposals |
| Generate 3D Space (paid) | `createScene` + fake delay | `build` → `preview` jobs with a real progress panel (reuse `generation-progress`, `scene-progress`) |
| View 3D Experience | R3F viewer | mode switch: **Explore** (R3F, exists) · **Tour** (360° panorama nodes) · **Explore Premium** (baked GLB) · Film (MP4, optional) |
| Save / Share | mock | public link `/w/{projectId}` that opens the same Experience view read-only; outputs manifest: web package, stills, video, `scene.blend`, SceneSpec |
| Connect with Designer | mock | unchanged for now |

New shared pieces: `useJob(jobId)` polling hook with backoff (port of `use-walkthrough-status`), `projects-api.ts` client, `JobProgress` component driven by the events feed.

---

## 10. Milestones

Estimates assume one developer plus Claude, working days. Each milestone ends with a demonstrable check.

| M | Scope | Days | Done when |
|---|---|---|---|
| M0 ✅ 2026-09-07 | Toolchain: Blender 5.2.1 LTS portable at `D:\Blender`, `BLENDER_PATH`, `app/blender/runner.py` + `blender/scripts/smoke.py`, git baselines for both apps | 0.5 | `python -m app.blender.runner --smoke` produces a PNG (done: Cycles/OptiX 3.6 s) |
| M1 ✅ 2026-09-07 | Projects + inputs + storage layout + SQLite + jobs skeleton (two lanes, events, retry, resume) | 2 | Upload text + 3 photos; a no-op job runs, emits events, survives a restart (done: 20 tests incl. restart-resume and retry-from-checkpoint; live smoke job renders via `/files/projects`) |
| M2 ✅ 2026-09-07 (backend) | Intelligence layer: schemas, mock provider, Gemini vision provider, stage prompts, `analyze` job, `GET/PATCH /analysis` for user corrections. Analysis Review screen moves to M7 with the rest of the UI. | 3 | `DesignAnalysis` + `StyleSpec` produced from photos; mock path passes tests with no keys (done: 31 tests; Gemini path tested against a mocked transport, live key still to be added by the user) |
| M3 ✅ 2026-09-07 (backend) | Scene planning: object plan → floor-plan layout → asset decision → `Scene` committed via patches; `scene-plan` + `resolve_assets` jobs; `GET /scene-spec`. Refine-step UI moves to M7. | 3 | Every object has a strategy and a local file or procedural def; validator clean (done: 41 tests; live run places 20+ objects with zero hard violations and the existing tour endpoint works on the compiled scene) |
| M4 ✅ 2026-09-07 | Blender build: manifest compiler (Y-up→Z-up), `build_room`, `procedural`, `import_assets`, `apply_materials`, `setup_lighting`, `validate_scene`, `render_preview`, `build` job, `POST/GET /build` | 3 | `scene.blend` opens with the same layout as the web viewer (done: live project builds in 11 s with 17 GLB + 11 procedural objects, validation clean, Eevee preview still served via `/files`) |
| M5 ✅ 2026-09-07 | Materials + lighting in Blender from `MaterialRecord` maps and `LightingSpec` (box-projected metric PBR textures, physical sky, sun, per-room area lights, exposure, exterior ground) | 2 | Hero still at `hero_still` profile looks like the moodboard palette (done: Cycles 1080p, 256 samples + denoise in 53 s on the RTX 3050; warm oak / leather / plaster palette visible) |
| M6 ✅ 2026-09-07 | Web tour: `tour_nodes.py` (one node per room + a second in large rooms, door-linked), `render_panoramas.py` (Cycles equirect; `pano_preview` 2K/32 spp ≈ 16 s per node, `pano_final` 4K/128 spp), `preview` + `walkthrough` jobs, `tour.json`, `GET /projects/{id}/tour`, `PanoramaTour` + minimap + autoplay, public `/w/[projectId]` page with a 360° Tour / Explore in 3D switch | 3 | Client opens a share link and walks the apartment room by room at Cycles quality (done: six preview panoramas in 97 s, hotspots land on the doorways) |
| M6b | Baked premium scene: `bake_lightmaps.py`, `export_web_scene.py` (KTX2 + Draco), `BakedSceneView` in the existing viewer | 3 | `scene_baked.glb` under 60 MB loads in the browser and walks with the existing first-person rig |
| M6c ✅ 2026-09-07 | Film export: `film` job (`render_walkthrough.py`, keyframed camera along the tour route, Blender FFmpeg with a PNG + ffmpeg fallback), poster frame, Film tab in the Studio and on the share page | 1 | MP4 from one click (done: 27 s preview film, 327 frames in 148 s at 960×540; `standard` profile is 1080p/24 fps) |
| M7 ✅ 2026-09-07 | Frontend wiring of all Studio steps to jobs (`features/studio`: projects API client with XHR upload progress, `useJob` polling, `JobProgress`, `AnalysisReview` with room/constraint/light corrections), scene-plan preview in the viewer, build + 360° preview on the paid step, Experience mode switch (360° Tour / Explore in 3D, final-quality render), `/w/{projectId}` share link with outputs, session resume after reload | 3 | Wizard runs end to end without mocks (done: create → describe → analyze → refine → plan → build → tour → share in one sitting; only the designer step stays mock) |
| M8 ✅ 2026-09-07 | Stabilise: golden project fixture (`tests/fixtures/golden_project`) with a DPR §30 acceptance test, checkpoint-recovery and restart tests (M1), route tests for every endpoint, Blender timeout-kill test, backend README | 2 | DPR §30 acceptance criteria all green on the golden project (done: 51 tests pass with Blender; the golden project reaches COMPLETED with a tour, package and preserved preview panoramas) |

Total ≈ 25.5 working days, about five to six weeks. M2–M3 (AI lane) and M4–M6 (Blender lane) can run in parallel after M1. If time is short, M6b and M6c are the ones to defer: M6 alone already puts a Cycles-quality walkthrough in the client's browser.

---

## 11. Test strategy

- Unit: manifest conversion round-trip; asset decision ordering; state machine transitions; checkpoint resume selection.
- Provider: mock provider golden outputs; Gemini provider behind a recorded-response fixture.
- Blender: a `pytest` marker `blender` that runs `build_scene.py` on the golden manifest headless and asserts object count, bbox and a 320×180 preview frame exists. Skipped when `BLENDER_PATH` is unset.
- Route tests with FastAPI `TestClient` for every new endpoint (none exist today for routes).
- Golden project: the seed apartment plus three reference photos and a description, checked into `tests/fixtures/golden_project/`.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| 4 GB VRAM out-of-memory in Cycles | Cycles for stills only, 2K texture cap, `preview` profile always runs first |
| Blender API drift | Pin 5.2.1 LTS; scripts import-guarded; smoke test in M0 |
| Gemini JSON drift / refusals | `responseSchema`, Pydantic validation, one repair retry, mock fallback per stage with warning |
| Web viewer and Blender disagree on placement | Single normalized GLB set and single manifest conversion function; M4 exit check compares bboxes |
| Long renders wedge the API | Render lane is one background thread; subprocess timeouts; API never awaits it |
| Asset gaps (bed, rug, wardrobe, lamp, TV unit) | Procedural in Blender, matching today's web primitives; licensed source later |
| Baked GLB too heavy for phones | Panorama tour is the phone path; baked GLB targets desktop, capped at 60 MB with KTX2 + Draco, lightmap atlases 2K per room |
| Panorama nodes look disconnected | Nodes are the tour keyframes, so hotspots follow the door-connected route; crossfade plus a floor-plan minimap with the current node |
| Scope creep toward the hosted diagram | Everything hosted (auth, Postgres, Redis, CDN) is explicitly deferred; job rows are the migration seam |

---

## 13. Assumptions made (say so if any is wrong)

1. Blender **5.2.1 LTS** is the target version (the build installed on this machine).
2. Gemini stays the first real provider; the diagram's "GPT-6 Astra" is covered by the provider interface.
3. Meshy generation stays off by default and is not needed for the first end-to-end demo.
4. SQLite is introduced only for projects/inputs/jobs/events/outputs; scene and asset registries stay JSON.
5. The primary deliverable is the in-browser walkthrough (360° panorama tour, then the baked real-time scene). The 1080p Eevee MP4 is a secondary export. No Cycles video.
6. The `/cinematic` photo-to-film route stays optional and untouched.

## 14. Moodboard fidelity and AI speed (added 2026-09-07 after the first user test)

Two findings from the first hands-on run and what changed:

**Speed.** The moodboard step was not slow: every analysis finished in under 100 ms on the mock provider, and the wait the user saw was a frontend polling bug (fixed). The configured Gemini model `gemini-2.0-flash` had also been retired by Google (404), so a live run would have fallen back to the mock silently. Now:
- `GEMINI_MODEL=gemini-3.5-flash-lite` by default (analysis ≈ 3 s, style ≈ 2 s, object plan ≈ 6 s with photos), with `GEMINI_FALLBACK_MODELS` tried automatically on 404/429/503 (the overloaded 3.6 flash fell to 3.5 flash during testing).
- `INTELLIGENCE_PROVIDER=auto|anthropic|gemini|mock`. A Claude provider (`app/intelligence/anthropic_provider.py`, Anthropic SDK, structured outputs, effort low) is selected when `ANTHROPIC_API_KEY` is set. Prompts and coercion are shared (`prompts.py`, `coerce.py`), so providers are interchangeable.
- `/api/health` reports the active provider and model.

**Fidelity.** The 3D used to be "the catalog in the right places": a black leather sofa whatever the moodboard said. The moodboard now drives the scene:
- The style palette is ordered wall, floor, upholstery, accent, accent. Every object gets a colour: the planner's per-object hint first, else the palette slot for its role. Plants stay green.
- Blender tints: walls take palette[0] over the plaster scan; fabric pieces get the style fabric recoloured to the planned tone (luminance × tint); real GLB models have their largest mesh (the upholstery) re-dressed the same way, so the catalogue sofa becomes the client's linen sofa. The web viewer applies the same wall tint and upholstery colour.
- Missing things are built procedurally in Blender rather than skipped: kitchen counter runs with doors, worktop, backsplash and upper cabinets; pleated curtains centred on the window; TV screens on TV units; skirting boards; door jambs and heads; window frames. Pieces that must fit a wall (counters, wardrobes, curtains) shrink in steps instead of failing placement.
- Known gaps: kitchens still have no appliances, decor beyond plants/art is thin, and a bespoke piece still needs the (disabled) generation path. The next fidelity step is style-specific furniture families (e.g. a japandi set vs a classic set) rather than one generic catalog.

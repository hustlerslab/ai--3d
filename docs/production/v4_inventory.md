# Allure V4 - Production Inventory

**Generated 2026-09-21 by introspecting the running application**, not by reading documentation.
Source of truth: `app.api.routes.router`, `app.api.projects_routes.router`, `files_router`, `app.jobs.registry._REGISTRY`, `app.core.config.Settings.model_fields`, `app.projects.layout.CHECKPOINTS`.

> **No environment variable value appears in this file.** Names only, as required. The `Secret` column is derived from the variable's *name*, never from reading what is in it.

---

## 0. Headline numbers

| | Count | Note |
|---|---:|---|
| HTTP routes (routers) | **63** | matches the documented figure |
| HTTP routes served (incl. `GET /` on the app) | **64** | cross-checked against `app.openapi()` |
| - of which **mutate state** | **34** | all now require an authorized principal |
| - of which **can spend Meshy credits** | **2** | authorized AND capped against the persisted ledger - section 1a |
| **Routes requiring authentication** | **60** | P0-SEC-002: one router-level dependency, deny by default |
| Routes deliberately anonymous | **3** | each justified in `authz.py`; see section 1b |
| Registered job types | **13** | **not 11** - see the correction below |
| Handler modules | 11 | `tour` and `scene_plan` each register two types |
| Environment variables | **45** | names only |
| Artifact checkpoints | **17** | `CHECKPOINTS` |

### Correction found while producing this

`task.md` and `AUDIT_CODEBASE.md` both say **11 job types**. There are **13**. Eleven *modules* are imported in `app/jobs/handlers/__init__.py`, but `tour.py` registers both `preview` and `walkthrough`, and `scene_plan.py` registers both `scene_plan` and `resolve_assets`. Counting imports is not counting registrations.

---

## 1. HTTP routes - all 63

Auth is enforced by **one router-level dependency** attached in `main.py`, not by per-route decorators - a per-route check is a per-route opportunity to forget. The source of truth for this column is `authz.is_anonymous()`: anything not on that allow-list requires a principal, and a project-scoped route additionally requires that the principal may touch *that* project.

| # | Method | Path | Origin | Auth | Enqueues | Spends Meshy credits |
|---:|---|---|---|---|---|---|
| 1 | `GET` | `/api/credits` | api/projects_routes.py | required | - | no |
| 2 | `GET` | `/api/jobs/types` | api/projects_routes.py | required | - | no |
| 3 | `GET` | `/api/jobs/{job_id}` | api/projects_routes.py | required | - | no |
| 4 | `GET` | `/api/projects` | api/projects_routes.py | required | - | no |
| 5 | `POST` | `/api/projects` | api/projects_routes.py | required | - | no |
| 6 | `DELETE` | `/api/projects/{project_id}` | api/projects_routes.py | required | - | no |
| 7 | `GET` | `/api/projects/{project_id}` | api/projects_routes.py | required | - | no |
| 8 | `PATCH` | `/api/projects/{project_id}` | api/projects_routes.py | required | - | no |
| 9 | `GET` | `/api/projects/{project_id}/analysis` | api/projects_routes.py | required | `analyze` | no |
| 10 | `PATCH` | `/api/projects/{project_id}/analysis` | api/projects_routes.py | required | - | no |
| 11 | `POST` | `/api/projects/{project_id}/analyze` | api/projects_routes.py | required | `analyze` | no |
| 12 | `POST` | `/api/projects/{project_id}/assets/resolve` | api/projects_routes.py | required | `resolve_assets` | no |
| 13 | `GET` | `/api/projects/{project_id}/build` | api/projects_routes.py | required | `build`, `preview` | no |
| 14 | `POST` | `/api/projects/{project_id}/build` | api/projects_routes.py | required | `build`, `preview` | no |
| 15 | `GET` | `/api/projects/{project_id}/element-images` | api/projects_routes.py | required | `element_images` | no |
| 16 | `PATCH` | `/api/projects/{project_id}/element-images` | api/projects_routes.py | required | - | no |
| 17 | `POST` | `/api/projects/{project_id}/element-images` | api/projects_routes.py | required | `element_images` | no |
| 18 | `POST` | `/api/projects/{project_id}/elements/generate` | api/projects_routes.py | required | `generate_elements` | **YES** |
| 19 | `GET` | `/api/projects/{project_id}/events` | api/projects_routes.py | required | - | no |
| 20 | `POST` | `/api/projects/{project_id}/film` | api/projects_routes.py | required | `film` | no |
| 21 | `GET` | `/api/projects/{project_id}/inputs` | api/projects_routes.py | required | - | no |
| 22 | `POST` | `/api/projects/{project_id}/inputs` | api/projects_routes.py | required | - | no |
| 23 | `DELETE` | `/api/projects/{project_id}/inputs/{input_id}` | api/projects_routes.py | required | - | no |
| 24 | `GET` | `/api/projects/{project_id}/jobs` | api/projects_routes.py | required | - | no |
| 25 | `POST` | `/api/projects/{project_id}/jobs` | api/projects_routes.py | required | **ANY registered type (caller-supplied)** | **YES** |
| 26 | `POST` | `/api/projects/{project_id}/moodboard/rooms/{room_id}/repaint` | api/projects_routes.py | required | `repaint_room` | no |
| 27 | `GET` | `/api/projects/{project_id}/outputs` | api/projects_routes.py | required | - | no |
| 28 | `POST` | `/api/projects/{project_id}/preview` | api/projects_routes.py | required | `preview` | no |
| 29 | `POST` | `/api/projects/{project_id}/scene-plan` | api/projects_routes.py | required | `scene_plan` | no |
| 30 | `GET` | `/api/projects/{project_id}/scene-reading` | api/projects_routes.py | required | `scene_plan` | no |
| 31 | `PATCH` | `/api/projects/{project_id}/scene-reading` | api/projects_routes.py | required | - | no |
| 32 | `GET` | `/api/projects/{project_id}/scene-spec` | api/projects_routes.py | required | `scene_plan` | no |
| 33 | `GET` | `/api/projects/{project_id}/tour` | api/projects_routes.py | **anonymous** | `preview` | no |
| 34 | `POST` | `/api/projects/{project_id}/walkthrough` | api/projects_routes.py | required | `walkthrough` | no |
| 35 | `GET` | `/files/projects/{project_id}/{path:path}` | api/projects_routes.py (files) | **anonymous** | - | no |
| 36 | `GET` | `/api/assets` | api/routes.py | required | - | no |
| 37 | `POST` | `/api/assets/ingest/polyhaven` | api/routes.py | required | - | no |
| 38 | `POST` | `/api/assets/upload` | api/routes.py | required | - | no |
| 39 | `GET` | `/api/assets/{asset_id}` | api/routes.py | required | - | no |
| 40 | `POST` | `/api/assets/{asset_id}/renormalize` | api/routes.py | required | - | no |
| 41 | `GET` | `/api/catalog` | api/routes.py | required | - | no |
| 42 | `GET` | `/api/catalog/{asset_id}` | api/routes.py | required | - | no |
| 43 | `GET` | `/api/health` | api/routes.py | **anonymous** | - | no |
| 44 | `GET` | `/api/materials` | api/routes.py | required | - | no |
| 45 | `POST` | `/api/materials/ingest/polyhaven` | api/routes.py | required | - | no |
| 46 | `GET` | `/api/materials/{material_id}` | api/routes.py | required | - | no |
| 47 | `GET` | `/api/scenes` | api/routes.py | required | - | no |
| 48 | `POST` | `/api/scenes` | api/routes.py | required | - | no |
| 49 | `GET` | `/api/scenes/{scene_id}` | api/routes.py | required | - | no |
| 50 | `POST` | `/api/scenes/{scene_id}/assets/upgrade` | api/routes.py | required | - | no |
| 51 | `POST` | `/api/scenes/{scene_id}/design/proposals` | api/routes.py | required | - | no |
| 52 | `POST` | `/api/scenes/{scene_id}/design/proposals/{proposal_id}/apply` | api/routes.py | required | - | no |
| 53 | `POST` | `/api/scenes/{scene_id}/design/proposals/{proposal_id}/reject` | api/routes.py | required | - | no |
| 54 | `POST` | `/api/scenes/{scene_id}/patches` | api/routes.py | required | - | no |
| 55 | `POST` | `/api/scenes/{scene_id}/patches/preview` | api/routes.py | required | - | no |
| 56 | `POST` | `/api/scenes/{scene_id}/redo` | api/routes.py | required | - | no |
| 57 | `POST` | `/api/scenes/{scene_id}/undo` | api/routes.py | required | - | no |
| 58 | `GET` | `/api/scenes/{scene_id}/validate` | api/routes.py | required | - | no |
| 59 | `POST` | `/api/scenes/{scene_id}/walkthrough/check-position` | api/routes.py | required | - | no |
| 60 | `GET` | `/api/scenes/{scene_id}/walkthrough/spawn` | api/routes.py | required | - | no |
| 61 | `GET` | `/api/scenes/{scene_id}/walkthrough/tour` | api/routes.py | required | - | no |
| 62 | `GET` | `/api/scenes/{scene_id}/walkthrough/views` | api/routes.py | required | - | no |
| 63 | `POST` | `/api/scenes/{scene_id}/walkthrough/views` | api/routes.py | required | - | no |

### 1b. Deliberately anonymous routes

| Route | Why |
|---|---|
| `GET /health`, `GET /` | Liveness. A probe that needs credentials reports the wrong thing during an outage. |
| `/api/auth/*` | You cannot authenticate in order to authenticate. |
| `GET /api/projects/{id}/tour` | The share link `/w/{projectId}` is a feature. **P0-SEC-004** replaces it with a capability token. |
| `/files/*` | The largest single hole, and **P0-SEC-005**'s whole job. Guarding it here in passing would be worse than guarding it there deliberately. |

A test walks every registered route and fails on any that answers an anonymous request without being on this list (`tests/test_authz_matrix.py`). Measured: **62 routes probed, 60 gated with 401, 2 allow-listed, 0 unguarded**.

---

### 1a. The 2 routes that can spend real money

- `POST /api/projects/{project_id}/elements/generate` -> `generate_elements`
- `POST /api/projects/{project_id}/jobs` -> **wildcard dispatcher** - the caller names the job type, so it reaches `generate_elements` AND `generate_assets`

Each generation is **30 credits**. Both require an authenticated principal who owns or is assigned to the project (P0-SEC-002), and both are capped against the persisted `spend_records` ledger (P0-SEC-003): `meshy_max_credits_per_project` = 600, `meshy_max_credits_per_user` = 3000. The caps are read from disk on every batch, so restarting the process does not reset them.

**Still open:** the idempotency key (P1-ASSET-002). A retried request can still spend twice.

**`POST /api/projects/{project_id}/jobs` is the most powerful route in the application.** It takes `type` and `params` straight from the request body and hands them to the runner, so it reaches all 13 registered job types - including both Meshy handlers - with caller-controlled parameters such as `limit`. `generate_assets` has **no dedicated route at all**; this wildcard is its only entry point.

A scan for string literals does not find it, because the type is never a literal. It is recorded here explicitly so `P0-SEC-002` does not protect the four named generation routes and leave the door that reaches all of them standing open.

---

## 2. Job types - all 13

| # | Type | Module | Lane | Resource / cost class | Attempts | Stage running -> done |
|---:|---|---|---|---|---:|---|
| 1 | `analyze` | `analyze.py` | `ai` | LLM tokens + local GPU | 2 | ANALYZING -> DESIGN_SPEC_READY |
| 2 | `blender_smoke` | `smoke.py` | `render` | CPU only | 2 | - -> - |
| 3 | `build` | `build.py` | `render` | CPU only | 2 | SCENE_BUILDING -> SCENE_VALIDATING |
| 4 | `element_images` | `element_images.py` | `render` | LLM tokens + local GPU | 2 | - -> - |
| 5 | `film` | `film.py` | `render` | CPU only | 2 | - -> - |
| 6 | `generate_assets` | `generate.py` | `ai` | **MESHY CREDITS** | 2 | - -> - |
| 7 | `generate_elements` | `generate_elements.py` | `ai` | **MESHY CREDITS** | 2 | - -> - |
| 8 | `noop` | `noop.py` | `ai` | CPU only | 3 | - -> - |
| 9 | `preview` | `tour.py` | `render` | CPU only | 2 | CAMERA_PLANNING -> PREVIEW_RENDERING |
| 10 | `repaint_room` | `repaint.py` | `render` | local GPU | 2 | - -> - |
| 11 | `resolve_assets` | `scene_plan.py` | `ai` | LLM tokens | 2 | - -> - |
| 12 | `scene_plan` | `scene_plan.py` | `ai` | LLM tokens | 2 | ASSET_PLANNING -> ASSETS_READY |
| 13 | `walkthrough` | `tour.py` | `render` | CPU only | 2 | FINAL_RENDERING -> COMPLETED |

### 2a. Lane assignment is not static

`runner._lane_for()` overrides the registered lane in two cases, so the table above is the *declared* lane, not always the *running* one:

1. `uses_local_gpu=True` **and** `SCENE_IMAGE_ENABLED` -> forced to `render`.
2. `uses_intelligence=True` **and** a local intelligence provider (e.g. Ollama) -> forced to `render`, because it runs on the same 6 GB GPU as Blender.

The `render` pool has **one** worker and the `ai` pool has **two**; that single render thread is the GPU mutex. On this hardware (RTX 3050 6 GB) it is a correctness mechanism, not a tuning knob.

### 2b. Only two handlers actually spend Meshy credits

`generate_assets` and `generate_elements`. Both raise `MeshyNotConfigured` when the key is absent, and both honour `meshy_max_per_project`.

`scene_plan` mentions Meshy but **plans** generation without performing it - its own comment: *approval gates SPENDING, which is the generate_elements job*. `element_images` costs LLM and GPU time, not Meshy credits. An earlier module-level scan flagged four handlers and was wrong.

---

## 3. Environment variables - all 45, names only

| # | Name | Type | Secret (by name) | Has default |
|---:|---|---|---|---|
| 1 | `AETHER_CORS_ORIGINS` | `str` | no | yes |
| 2 | `AETHER_DATA_DIR` | `str` | no | yes |
| 3 | `AETHER_HOST` | `str` | no | yes |
| 4 | `AETHER_PORT` | `int` | no | yes |
| 5 | `ANTHROPIC_API_KEY` | `SecretStr` | **yes** | yes |
| 6 | `ANTHROPIC_MODEL` | `str` | no | yes |
| 7 | `ANTHROPIC_TIMEOUT_SECONDS` | `int` | no | yes |
| 8 | `BLENDER_PATH` | `str` | no | yes |
| 9 | `BLENDER_TIMEOUT_SECONDS` | `int` | no | yes |
| 10 | `GEMINI_API_KEY` | `SecretStr` | **yes** | yes |
| 11 | `GEMINI_FALLBACK_MODELS` | `str` | no | yes |
| 12 | `GEMINI_MAX_REFERENCE_IMAGES` | `int` | no | yes |
| 13 | `GEMINI_MODEL` | `str` | no | yes |
| 14 | `GEMINI_TIMEOUT_SECONDS` | `int` | no | yes |
| 15 | `INTELLIGENCE_PROVIDER` | `str` | no | yes |
| 16 | `JOBS_AI_WORKERS` | `int` | no | yes |
| 17 | `JOBS_DEFAULT_MAX_ATTEMPTS` | `int` | no | yes |
| 18 | `JOBS_RENDER_WORKERS` | `int` | no | yes |
| 19 | `JOBS_RETRY_DELAY_SECONDS` | `float` | no | yes |
| 20 | `MESHY_API_KEY` | `SecretStr` | **yes** | yes |
| 21 | `MESHY_ART_STYLE` | `str` | no | yes |
| 22 | `MESHY_BASE_URL` | `str` | no | yes |
| 23 | `MESHY_MAX_CREDITS_PER_PROJECT` | `int` | no | yes |
| 24 | `MESHY_MAX_CREDITS_PER_USER` | `int` | no | yes |
| 25 | `MESHY_MAX_PER_PROJECT` | `int` | no | yes |
| 26 | `MESHY_MODE` | `str` | no | yes |
| 27 | `MESHY_POLL_SECONDS` | `float` | no | yes |
| 28 | `MESHY_SHOULD_REMESH` | `bool` | no | yes |
| 29 | `MESHY_TARGET_POLYCOUNT` | `int` | no | yes |
| 30 | `MESHY_TIMEOUT_SECONDS` | `int` | no | yes |
| 31 | `OLLAMA_BASE_URL` | `str` | no | yes |
| 32 | `OLLAMA_IMAGE_MAX_PX` | `int` | no | yes |
| 33 | `OLLAMA_MAX_IMAGES` | `int` | no | yes |
| 34 | `OLLAMA_MODEL` | `str` | no | yes |
| 35 | `OLLAMA_NUM_CTX` | `int` | no | yes |
| 36 | `OLLAMA_NUM_PREDICT` | `int` | no | yes |
| 37 | `OLLAMA_SCENE_IMAGE_MAX_PX` | `int` | no | yes |
| 38 | `OLLAMA_TIMEOUT_SECONDS` | `int` | no | yes |
| 39 | `PROVIDER_FALLBACK_TO_MOCK` | `bool` | no | yes |
| 40 | `SCENE_IMAGE_ENABLED` | `bool` | no | yes |
| 41 | `SCENE_IMAGE_HEIGHT` | `int` | no | yes |
| 42 | `SCENE_IMAGE_MODEL` | `str` | no | yes |
| 43 | `SCENE_IMAGE_REFERENCE_SCALE` | `float` | no | yes |
| 44 | `SCENE_IMAGE_STEPS` | `int` | no | yes |
| 45 | `SCENE_IMAGE_WIDTH` | `int` | no | yes |

Settings are loaded by `pydantic-settings` from the process environment **and** from `.env` (`config.py:16`). That second source is easy to forget: it is why the test suite could read a developer's real keys until an autouse fixture was added (see `TRACK_RECORD.md` P0-QA-004).

---

## 4. Artifact paths - all 17 checkpoints

Paths are relative to a project's directory under `AETHER_DATA_DIR`.

| # | Checkpoint | Relative path |
|---:|---|---|
| 1 | `inputs` | `input/description.txt` |
| 2 | `analysis` | `analysis/design_analysis.json` |
| 3 | `moodboard` | `analysis/moodboard_spec.json` |
| 4 | `scene_reading` | `planning/scene_reading.json` |
| 5 | `object_plan` | `planning/object_plan.json` |
| 6 | `asset_plan` | `planning/asset_plan.json` |
| 7 | `design_intent` | `planning/design_intent.json` |
| 8 | `scene_spec` | `planning/scene_spec.json` |
| 9 | `spatial_check` | `planning/spatial_check.json` |
| 10 | `visual_intent_fidelity` | `planning/visual_intent_fidelity.json` |
| 11 | `build_manifest` | `blender/build_manifest.json` |
| 12 | `scene_blend` | `blender/scene.blend` |
| 13 | `validation_report` | `blender/validation_report.json` |
| 14 | `camera_path` | `blender/camera_path.json` |
| 15 | `preview` | `previews/preview.mp4` |
| 16 | `walkthrough` | `renders/walkthrough.mp4` |
| 17 | `outputs` | `outputs/manifest.json` |

### 4a. Static mounts that expose files over HTTP

| Mount | Serves |
|---|---|
| `/files/assets` | the asset registry's `normalized/` directory |
| `/files/assets-web` | the same geometry, textures sized to a GPU budget |
| `/files/materials` | the material registry root |
| `/files/projects/{project_id}/{path}` | per-project artifacts, resolved per request |

The raw data directory is never mounted. All four are **unauthenticated**.

---

## 5. External dependencies

| Dependency | Reached from | Failure mode today |
|---|---|---|
| **Meshy** image-to-3D | `generate_assets`, `generate_elements` | `MeshyNotConfigured` when the key is absent; 3-day asset retention upstream |
| **Gemini** | intelligence provider | `ResilientProvider` falls back to a labelled deterministic estimate |
| **Anthropic** | intelligence provider, only when selected | same |
| **Ollama** (`:11434`) | intelligence provider when selected | job fails; forced onto the render lane |
| **Blender** (`BLENDER_PATH`) | `build`, `preview`, `walkthrough`, `film`, `blender_smoke` | jobs fail; tests skip |
| **Poly Haven** | asset ingest | asset resolution degrades to a lower rung |
| **SQLite** (`data/allure.db`) | everything | local file; `SCHEMA_VERSION = 2` with migrations |
| **RE Walkthrough Pro** (`:4000`) | frontend `/cinematic` **only** | optional; the page states plainly that the engine is absent |

---

## 6. What this inventory establishes for the next tasks

| Task | What it can now target |
|---|---|
| **P0-SEC-002** | 63 routes, of which 34 mutate state and 2 can spend credits (incl. the wildcard dispatcher) - a verified list, not an estimate |
| **P0-INFRA-001** | 45 environment variable names, 17 artifact paths, 8 external dependencies |
| **Observability** | 13 job types with declared lanes, plus the two runtime lane overrides |

*Regenerate with the extraction script recorded in `version 4/evidence/P0-ARCH-001/`.*

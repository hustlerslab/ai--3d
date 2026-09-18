# Frontend → backend → spatial engine → Blender: connectivity audit

Read-only audit performed 2026-09-16 before any integration change, then
re-stated after the connections made in the same pass (§3). Repository is the
source of truth; every row cites the code that establishes it.

**Stack found.** Frontend: Next.js 15.5 / React 19 app router
(`aether-frontend/src/app`), pages `/` (Studio wizard), `/3d`, `/cinematic`,
`/w/[projectId]` (share). Four HTTP clients: `features/studio/api/projects-api.ts`
(project pipeline), `features/walkthrough3d/api/aether-api.ts` (`/scenes/*`),
`features/tour/api/tour-api.ts`, `features/walkthrough/api/walkthrough-api.ts`
(a separate cinematic engine on `:4000`, not the Allure backend). Backend:
FastAPI `aether-backend/app/main.py`, routers `app/api/projects_routes.py` and
`app/api/routes.py`, SQLite job store with a two-lane in-process worker
(`app/jobs/runner.py`), handlers under `app/jobs/handlers/`. Progress is
**polling only** (`GET /api/jobs/{id}` → `{job, events}`, backoff 1–3 s in
`use-job.ts`); no SSE/websocket exists. Uploads are multipart XHR to
`POST /api/projects/{id}/inputs`. No authentication. Storage: SQLite +
`data/projects/{id}/…` + `data/scenes/{scene_id}.json`.

**The photo question.** Uploaded photos are *design references*: they go to
`analyze` → `provider.analyze_input` (Gemini/Anthropic/mock) and to the
moodboard renderer. Nothing in the frontend reaches
`research/spatial_engine`, `research/spatial_architecture/scene_from_photo.py`,
`app/spatial/planes.py` or `app/vision` (grep: zero importers from `app/jobs`,
`app/api`). The RESEARCH_ONLY photo→scene reconstruction is **not exposed**,
and this pass does not expose it.

## 1. Feature map (state before this pass)

| Frontend Feature | UI Component | API Call | Endpoint | Backend Handler | Spatial Engine | Blender | Status | Missing Link |
|---|---|---|---|---|---|---|---|---|
| Create project (name, space preset, vertical) | `walkthrough-studio.tsx` step 1 | `createProject`/`updateProject` | POST/PATCH `/api/projects` | `projects_routes.py:100,134` → `ProjectStore` | — | — | CONNECTED | — |
| Project history open/delete | `project-history.tsx` | `listProjects`, `deleteProject` | GET/DELETE `/api/projects` | `projects_routes.py:95,173` | — | — | CONNECTED | — |
| Upload photos + brief + room dimensions | step 2, `RoomRows` | `uploadInputs` (multipart) | POST `/api/projects/{id}/inputs` | `projects_routes.py:230` (writes `input/*`, sets `room_hints`) | — | — | CONNECTED | photos are LLM references only (see above) |
| Design analysis + moodboard | step 3 | `analyze` → poll → `getAnalysis` | POST `/analyze`, GET `/analysis` | job `analyze` (`handlers/analyze.py`) → provider + local SD | — | — | CONNECTED (CONTROLLED_BETA path: LLM) | — |
| Repaint a room's moodboard | `analysis-review.tsx` | `repaintRoom` | POST `/moodboard/rooms/{room}/repaint` | job `repaint_room` | — | — | CONNECTED (local GPU) | — |
| Review & refine (rooms, constraints text, style, item roles) | step 4 `AnalysisReview` | `patchAnalysis` | PATCH `/analysis` | `projects_routes.py:426` | — | — | PARTIALLY_CONNECTED | `DesignAnalysis.constraints` (free text) is saved and **never read** by `plan_objects` / compiler (`prompts.py:272-315`) |
| Moodboard read-back + element approve/reject | `element-review.tsx` | `getSceneReading`, `reviewSceneReading` | GET/PATCH `/scene-reading` | inside job `scene_plan` (`_read_scene`) + route | — | — | CONNECTED (MODEL_LIMITED read-back; optional) | — |
| Generate confirmed pieces (Meshy, paid) | step 4→5 | `generateElements`, `getCredits` | POST `/elements/generate`, GET `/credits` | job `generate_elements` | — | — | CONNECTED | ADR-003 §9 product decision still open |
| Plan the space (solver) | step 4/5 | `scenePlan` → poll → `getSceneSpec` | POST `/scene-plan`, GET `/scene-spec` | job `scene_plan`: `plan_objects` → `apply_spatial_graph` → `resolve_plan` → `compile_scene` → `place_objects` → `_commit_with_retry` → `validate_scene` | `place_objects` (greedy, `_relation_candidates`), `validate_object`/`validate_scene` | — | CONNECTED (solver + validation) | repair / intent evaluation / P7 spatial scene NOT invoked (zero importers) |
| Validation results shown to the user | — | `getSceneSpec` (`violations`) | GET `/scene-spec` | `projects_routes.py:730` | `validate_scene` | — | NOT_CONNECTED | fetched, only `scene.scene_id` read; violations never rendered; job `warnings` (dropped objects) never rendered |
| Repair / re-solve | — | — | — | — | `app/spatial/repair_engine.py` (P4) | — | NOT_CONNECTED | no handler imports it |
| Independent intent evaluation | — | — | — | — | `app/planning/constraint_*` (P8) | — | NOT_CONNECTED | no handler imports it; no `ObjectPlan`→`Intent` bridge |
| Candidates (NEAR / BETWEEN metric generators) | — | — | — | — | `app/planning/candidate_generators.py` (P9) | — | NOT_CONNECTED | production `RelationType` carries no distance / between; no source exists in the plan (P9 §26 deferred) |
| Clearance (P2) | — | — | — | — | `app/spatial/clearance_engine.py` | — | NOT_CONNECTED | not in `validate_scene` by P2's own latency finding (0.4–3.5 s/scene) |
| User-authored spatial constraints ("sofa facing TV") | — | — | — | — | — | — | NOT_YET_SOLVED | no schema field on project/inputs; only free prose in the brief |
| 3D plan editing (move/rotate/delete/recolour/replace, undo/redo) | `walkthrough3d-view.tsx` | `commitPatch`, `undo`, `redo` | POST `/api/scenes/{id}/patches`, `/undo`, `/redo` | `routes.py:205,238,248` → `commit_patch` | `validate_object` gate on every patch | — | CONNECTED | — |
| Add piece / free-text instruction | `walkthrough3d-view.tsx` | `createProposal`/`applyProposal`/`rejectProposal` | POST `/scenes/{id}/design/proposals…` | `design/service.py` | `validate_object`; proposal `violations` shown | — | CONNECTED | — |
| Scene validate endpoint | — | (no client) | GET `/scenes/{id}/validate` | `routes.py:184` | `validate_scene` | — | NOT_CONNECTED | unused; equivalent data arrives via `/scene-spec` |
| Build in Blender | step 6 | `build` → poll → `getBuild` | POST/GET `/build` | job `build` → `build_manifest` → `BlenderRunner` → `validation_report.json` | — | `blender/scripts/build_scene.py`, `validate_scene.py` | CONNECTED | `report.errors/warnings` fetched, never rendered |
| 360° preview / final walkthrough / film | steps 6–7 | `preview`, `walkthrough`, `film`, `getTour` | POST `/preview`, `/walkthrough`, `/film`, GET `/tour` | jobs `preview`, `walkthrough`, `film` (`handlers/tour.py`, `film.py`) | — | panoramas, hero stills, MP4 | CONNECTED | — |
| Share page `/w/{id}` (tour / explore / film) | `share-view.tsx` | `getTour`, `/scenes/*` | GET `/tour` | `projects_routes.py:872` | — | outputs | CONNECTED | — |
| Outputs list | step 8 | `getProject` (`outputs`) | GET `/projects/{id}` | `projects_routes.py:118` | — | — | CONNECTED | — |
| Connect with a designer | step 9 | none | — | — | — | — | NOT_CONNECTED | UI over `lib/mock/designers.ts`; no backend exists (not invented) |
| Cinematic `/cinematic` | `walkthrough-view.tsx` | `walkthrough-api.ts` | `:4000/api/walkthroughs/*` | external service, not this repo | — | — | NOT_CONNECTED (separate engine) | out of scope; never touches the Allure spatial engine |
| Photo → scene reconstruction | — | — | — | — | `research/spatial_architecture/scene_from_photo.py`, `research/spatial_engine/*`, `app/spatial/planes.py` | — | RESEARCH_ONLY | correctly unreachable from the frontend; must stay so |
| Floor-plan input | — | — | — | `InputKind.floor_plan` defined, no route creates it | — | — | NOT_YET_SOLVED | — |
| Unused clients | — | `listInputs`, `resolveAssets`, `getEvents`, `listScenes`, `createScene` | — | routes exist | — | — | NOT_CONNECTED | dead code, harmless |

## 2. Trace of the real user flow (before)

create → upload (multipart) → `analyze` job (LLM/mock; local SD moodboard) →
review (`PATCH /analysis`) → `scene_plan` job (`plan_objects` → image-space
spatial graph → asset ladder → `compile_scene` → `place_objects` →
`commit_patch`/`validate_scene`) → 3D view (`/scenes/{id}` + patches) →
`build` job (Blender) → `preview` job (panoramas + `tour.json`) → share.
Every arrow above is exercised by the Studio. What the user never saw:
`validate_scene` violations, dropped-object warnings, the Blender validation
report, and the migrated repair / intent / spatial-scene stages, which nothing
invoked.

## 3. Connections made in this pass (see `research_to_production.md` for the migration itself)

| Stage in the canonical flow | Before | After | Evidence |
|---|---|---|---|
| SOLVER → VALIDATION → REPAIR / RE-SOLVE | `_commit_with_retry` dropped violators | `repair_placement` (P4 `repair_scene`, levels 1–3) runs on the solver's ops before the commit gate; only violators move, only to `validate_object`-accepted positions; commit gate unchanged | `app/planning/spatial_pipeline.py`, `scene_plan.py`; 12-brief benchmark: 547 placed (unchanged), 0 hard, `ALREADY_VALID`×12 |
| INDEPENDENT INTENT EVALUATION | not invoked | plan `facing` relations → `Intent` (MODEL_INFERRED) → `compile_intents` → `evaluate_all` on the committed scene; `against_wall` / `beside` / `in_front_of` / `around` / `under` **reported as unsupported with the reason**, never evaluated with the wrong ruler | 12 briefs: FACES 9 satisfied / 8 violated (angular error 64–150°), `against_wall` 344 reported; centre-vs-edge mismatch documented in the module docstring |
| SPATIAL SCENE | not built | `SpatialScene` with solver-decided `SUPPORTED_BY` relations (`parent_id`), `check_consistency`, canonical `p7.1` JSON → `planning/spatial_scene.json` | 0 consistency findings on 12 briefs |
| RESULT → FRONTEND | violations/report dropped | `GET /scene-spec` returns `spatial_check`; Studio step 5 renders `SpatialCheckPanel` (hard violations, repair outcome, facing verdicts, not-checked relation types); step 6 renders the Blender validation report line | `spatial-check.tsx`, `walkthrough-studio.tsx`; `tsc`/`eslint` clean |
| Job events | — | `plan.repair`, `plan.intent` events appear in the existing `JobProgress` trail | `scene_plan.py` |

Latency added per plan: median 36.5 ms, max 261 ms on the 12-brief benchmark.

Still NOT connected, on purpose (each is a documented boundary, not an omission):
P2 clearance in `validate_scene` (latency), P9 NEAR/BETWEEN generators (no
plan source), user-authored spatial constraints (no schema; NOT_YET_SOLVED),
`DesignAnalysis.constraints` free text into planning (would mean inventing
prompt behaviour), `against_wall` intent verdicts (evaluator semantics
mismatch — stop condition), photo→scene (RESEARCH_ONLY), floor-plan input
(NOT_YET_SOLVED), designer connect (no backend), cinematic engine (external).

## 4. A gap found only by driving the UI

Step 4's "next" was gated on `confirmedAnything` (≥ 1 approved moodboard
element). A brief-only project with no moodboard read-back — the
PRODUCTION_READY path — therefore planned a scene successfully and then could
not reach "Plan 3D Space" / "Generate 3D space" in the wizard (the stepper
only unlocks steps already reached). Status before: **BROKEN** for that path.
Fixed in `walkthrough-studio.tsx`: without a read-back the planned scene
unlocks the step ("Continue to the 3D plan") and `confirmAndPlan` advances
without a paid generation or a forced re-plan. Behaviour with a read-back is
unchanged.

## 5. Verification (live run, 2026-09-16)

Isolated pair — backend `:8010` (`INTELLIGENCE_PROVIDER=mock`,
`SCENE_IMAGE_ENABLED=false`, scratch data dir, Blender 5.2 configured) and
frontend `:3002` — driven in headless Chromium over CDP exactly as a user
clicks (`scratchpad/e2e_studio.py`). The user's own `:8000`/`:3001` servers
were not touched. Project `proj_b27e91a834`:

| Step | Result |
|---|---|
| Create project → Upload & describe (brief text, default room rows) | 3 s each |
| Analyze (mock provider) | job `SUCCEEDED`; analysis rendered |
| Plan the space | job `SUCCEEDED` in 2 s; events `plan.scene: 5 room(s), 20 wall(s), 10 opening(s)`, `plan.repair: ALREADY_VALID · hard 0 -> 0 · moved 0`, `plan.scene: 47 object(s) placed and validated`, `plan.intent: 1 satisfied · 1 violated · 0 unknown · 45 unsupported` |
| `GET /scene-spec` | 47 objects, 0 violations, `spatial_check.repair.terminal_state = ALREADY_VALID`, `intent = {satisfied 1, violated 1, unknown 0, unsupported {against_wall 29, beside 8, around 4, under 3, in_front_of 1}}`, `consistency []` |
| Plan 3D Space | panel text: "Spatial check · No hard violations · Repair: nothing to fix · Facing: 1 kept · 1 not met · angular error 150.0 deg (tolerance 60.0 deg) · Not checked yet: beside (8), against wall (29), under (3), in front of (1), around (4)"; 3D canvas present (`/scenes/{id}` + tour + spawn) |
| Generate 3D space (Blender) | build job `SUCCEEDED` in 16 s; page line "Blender validation: ok"; `GET /build` report `ok=True`, 0 errors, 0 warnings |
| 360° preview | preview job succeeded after 508 s; `tour.json` 7 nodes, quality `preview`; Studio advanced to "Walk through your space" |

Backend suite after the wiring: **729 passed, 7 skipped, 30 xfailed**
(725 + 4 new in `tests/test_spatial_pipeline.py`). Frontend: `tsc --noEmit`
and `eslint` clean on the changed files.

Not verified live (unchanged, out of this pass's scope): Meshy element
generation (paid), final-quality walkthrough and film (same handlers as
preview, longer renders), the `:4000` cinematic engine.

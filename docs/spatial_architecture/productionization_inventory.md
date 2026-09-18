# Productionization inventory — every researched capability, classified

Whole-repository inventory produced before any production code was changed in
the research-to-production pass (2026-09-16). The repository is the source of
truth: every Status cites the report/decision that established it. Companion
document with the migration record: `docs/production/research_to_production.md`.

Classification vocabulary (exactly one per capability):
`ALREADY_PRODUCTION` · `MIGRATE_FULL` · `MIGRATE_VALIDATED_PORTION` ·
`PARTIAL_KEEP_PARTIAL` · `CONTROLLED_BETA` · `RESEARCH_ONLY` · `MODEL_LIMITED` ·
`HARDWARE_LIMITED` · `REJECTED` · `DEFERRED` · `NOT_APPLICABLE`.

Column key: **Src** = where the capability was researched/decided · **Status** =
verdict as recorded, with evidence · **Prod** = existing production implementation
· **Res** = research implementation · **Dest** = production destination ·
**Mig?** = migration required · **Risk** · **Deps** · **Excl** = explicit
exclusions · **Decision**.

## A. Shipped pipeline (pre-spatial-architecture) — all ALREADY_PRODUCTION unless noted

| # | Capability | Src | Status | Prod | Res | Dest | Mig? | Risk | Deps | Excl | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Project inputs / stages / verticals | ADR-001, ALLURE_HYBRID_LOCAL_PLAN | Accepted, shipped (56+ tests, golden run AUDIT_2026-09-07) | `app/projects`, `app/api/projects_routes.py`, `vocab.py` per-vertical | — | — | No | — | SQLite | auth, hosted DB deferred (AUTH_PLAN) | ALREADY_PRODUCTION |
| A2 | Design analysis + style spec | analyze handler | Shipped | `handlers/analyze.py`, providers | — | — | No | — | provider | — | ALREADY_PRODUCTION |
| A3 | Moodboard render (local SD, ref scale 0.35, 704×448) | ADR-002 | Accepted (six-render trade study, 3-seed A/B) | `providers/local_image.py`, `config.py` | — | — | No | — | 6 GB GPU | per-render framing variance = human re-run | ALREADY_PRODUCTION |
| A4 | Moodboard → elements → crops → human gate | ADR-003 | Accepted with open product question §9 | `scene_reading.py`, `handlers/scene_plan.py`, review UI | — | — | No | — | provider | Meshy invents detail (founder decision pending) | ALREADY_PRODUCTION |
| A5 | Generation guard: truncation salvage, repetition abort, `GenerationStatus`, `flag_implausible` | phase 0e/0f (`phase0f_threshold.py`, `phase0f_cancel_probe.py`) | Implemented + tested (`test_generation_guard.py`); no committed 0f report (conclusions live in script docstrings) | `ollama_provider.py`, `scene_reading.py`, `vocab.ROOM_BOUND_TYPES` | scripts only | — | No | — | Ollama | — | ALREADY_PRODUCTION |
| A6 | Object plan (LLM) + image-space spatial graph | `spatial_graph.py`, tests | Shipped; graph written, `apply_spatial_graph` fills relation/support | `app/planning/spatial_graph.py` (untracked but wired: `scene_plan.py:74,257`) | — | — | No (commit it) | untracked file | provider | thresholds not exposed as settings | ALREADY_PRODUCTION |
| A7 | Asset decision ladder | plan §7 | Shipped | `asset_decision.py` | — | — | No | — | catalog/registry | Meshy off by default | ALREADY_PRODUCTION |
| A8 | Room layout (hub-and-spoke, walls, openings) | plan §9 | Shipped | `layout.py` | — | — | No | — | — | — | ALREADY_PRODUCTION |
| A9 | Greedy sequential placement (`place_objects`, `_ordered`, `_relation_candidates`, `_pick_support`) | P0/P3, scene_validity (12/12 valid, 547/559, 0 hard) | PASS — "GREEDY IS DEFAULT" | `compiler.py` | P3 harness compares against it | — | No | — | validation | no global optimizer | ALREADY_PRODUCTION |
| A10 | 2D validation H1–H5 | P0 baseline; scene_validity | PASS on what exists | `spatial/validation.py`, `geometry.py` | — | — | H2 only (P5) | low | — | — | ALREADY_PRODUCTION (+P5 extension, C5) |
| A11 | Scene store / patches / undo / redo | DPR | Shipped | `app/scene` | — | — | No | — | — | — | ALREADY_PRODUCTION |
| A12 | Asset registry, glTF measure, normalization (m, +Y, −Z), validation, web variant | asset_normalization_report (58/58 PASS as audit) | PASS | `app/assets` | `asset_audit.py` | — | No | — | — | 8 metadata warnings recorded, not silenced | ALREADY_PRODUCTION |
| A13 | Materials registry / PBR | plan | Shipped | `app/materials` | — | — | No | — | Polyhaven | — | ALREADY_PRODUCTION |
| A14 | Catalog (built-in + registry) | plan | Shipped | `app/catalog` | — | — | No | — | — | one CC0 catalog for all styles (deferred by design) | ALREADY_PRODUCTION |
| A15 | Blender manifest (Y-up→Z-up), runner, build/validate/render scripts, read-back JSON | blender_execution_report (12/12 PASS, XY p95 0.015 m) | PASS | `app/blender`, `blender/scripts` | `blender_e2e_benchmark.py` | — | No | — | Blender path | — | ALREADY_PRODUCTION |
| A16 | Walkthrough / tour / film | DPR §30 golden | Shipped | `app/walkthrough`, handlers | — | — | No | — | Blender | — | ALREADY_PRODUCTION |
| A17 | Design proposals | AUDIT B1 fix | Shipped | `app/design/service.py` | — | — | No | — | validation | — | ALREADY_PRODUCTION |
| A18 | Jobs runner (2 lanes), API, SQLite | plan | Shipped | `app/jobs`, `app/api`, `app/db` | — | — | No | — | — | — | ALREADY_PRODUCTION |
| A19 | Provider abstraction (`IntelligenceProvider` Protocol + `ResilientProvider`) | provider.py | Shipped; mock always available | `app/intelligence/provider.py` | — | — | No | — | — | — | ALREADY_PRODUCTION |
| A19a | MockProvider | — | deterministic fallback, benchmarked (brief path) | `mock_provider.py` | — | — | No | — | — | `res_studio` room mis-parse (PERCEPTION_FAILURE, open) | ALREADY_PRODUCTION |
| A19b | Gemini provider | ADR-002 era | production (auto-selected when configured) | `gemini_provider.py` | — | — | No | — | key | — | ALREADY_PRODUCTION |
| A19c | Anthropic provider | — | production (auto-selected first when configured) | `anthropic_provider.py` | — | — | No | — | key | — | ALREADY_PRODUCTION |
| A19d | Ollama local VLM provider | phase 0e/0f, 1b | explicit-opt-in only (never `auto`), 100% reads after guard | `ollama_provider.py` | phase scripts | — | No | — | 6 GB GPU | not on geometric path | CONTROLLED_BETA (explicit name only) |
| A20 | Meshy image-to-3D from crops | ADR-003 §8–9, `probe_image_to_3d.py` | Probe done; product decision required | `providers/meshy.py`, `generate_elements.py` (human-gated) | probe | — | No | — | API key | invents plausible detail | DEFERRED (founder decision) |
| A21 | ControlNet depth-conditioned styling | ADR-004 | "probe complete, not adopted" | — | `controlnet_probe.py` | — | No | — | — | — | REJECTED (not adopted) |
| A22 | Analytic depth map from planner geometry | ADR-004 | kept as reusable value, not adopted | — | `depth_from_scene.py` | — | No | — | — | — | RESEARCH_ONLY |

## B. Photo-perception research (`research/spatial_engine`, `research/phase*`, `app/spatial/planes.py`, `app/vision`)

| # | Capability | Src | Status | Prod | Res | Dest | Mig? | Risk | Deps | Excl | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | Perception model VRAM/latency feasibility | `model_benchmark.py`, spatial_engine_model_benchmark.md | evidence (6 GB is not the constraint; 7B LLM was) | — | benchmark | — | No | — | — | — | NOT_APPLICABLE (evidence only) |
| B2 | Open-vocab detector (Grounding DINO) as reader | phase 0b/0d, `app/vision` | "OPTION C — HYBRID… detector is not a better reader"; 0d report never committed | none (benchmark-only package) | `benchmark_detector.py` | — | No | — | model | must not import from app/ | RESEARCH_ONLY |
| B3 | VLM spatial relation extraction (3B/7B, one-question, binary, context) | phase 1c–1h reports | 1c FAIL, 1d FAIL, 1e PARTIAL, 1f PARTIAL, 1h PASS-on-gates "not a green light"; readiness table: "FAIL — VLM removed from the geometric path" | none | phase scripts | — | No | — | — | — | REJECTED |
| B4 | Relative-depth wall contact (RANSAC) | geometric_wall_contact_report | NO-GO (false-wall 61.5%) | — | `geometric_wall_contact.py` | — | No | — | — | — | REJECTED |
| B5 | Metric depth (MoGe-2 vitl, MIT) | metric_geometry_report | "FAIL by the gate" but hypothesis answered yes; MoGe-2 adopted for research; UniDepthV2 blocked (CC BY-NC) | — | `metric_geometry.py` | — | No | — | 2636 MiB VRAM | UniDepthV2 | MODEL_LIMITED |
| B6 | SAM 2 segmentation grounding | segmentation_grounding_report | FAIL gate / "PARTIAL — visible-surface statistic exposed" | — | `segmentation_grounding.py` | — | No | — | 920 MiB | — | MODEL_LIMITED |
| B7 | Rear extent from visible points | rear_extent_wall_contact_report | FAIL (7/8 conditions) "Do not pursue" | — | `rear_extent_wall_contact.py` | — | No | — | — | — | REJECTED |
| B8 | Oracle amodal 3D extent ceiling | oracle_3d_extent_ceiling_report | LOW CEILING (diagnostic) | — | `oracle_geometry.py` | — | No | — | — | — | NOT_APPLICABLE (diagnostic) |
| B9 | Wall quality gate + abstention (UNKNOWN) | wall_quality_abstention_report | PARTIAL PASS, frozen (false-wall 21.6→6.1%, AUC 0.84) | — | `wall_quality.py` | — | No | — | MoGe-2 | thresholds not to be lowered for coverage | MODEL_LIMITED |
| B10 | Catalogue-grounded object extent | object_extent_report | PARTIAL PASS (PCA orientation rejected) | catalogue dims already production (A12/A14) | `object_extent.py` | — | No | — | registry | PCA orientation | MODEL_LIMITED |
| B11 | Floor hypothesis scoring (countertop-as-floor rejected) | floor_reconstruction_report | PARTIAL PASS ("first fix retracted") | — | `floor_candidates.py` | — | No | — | planes | no extra floor heuristics | MODEL_LIMITED |
| B12 | Object grounding (floor+walls+extent→footprint) | object_grounding_report | PARTIAL PASS ("no-wall fallback weak"); 46/48 on frozen set | — | `object_grounding.py` | — | No | — | B5,B6,B9–B11 | — | MODEL_LIMITED |
| B13 | `app/spatial/planes.py` (Plane, PointMap, RoomGeometry, WallContact, Evidence, Decision; wall contact 77.8% precision / 25% UNKNOWN vs 90% target) | spatial_engine_production_readiness §6–7 | "NOT IMPORTED BY PRODUCTION"; RED overall | file lives in `app/` by design, zero importers | consumed by all of B | stays in place, unwired | No | — | — | must not be wired to a handler | RESEARCH_ONLY (pre-production placement, unchanged) |
| B14 | Architecture decision A/B/C (extend `Scene`, not replace) | architecture_decision.md | PASS | `Scene` | — | — | No | — | — | B, C rejected | ALREADY_PRODUCTION (decision honoured) |
| B15 | Perception→Scene bridge (`grounding_contract`, `scene_from_photo`) | P1/phase 16; production_boundary photo = RESEARCH_ONLY | PARTIAL (95.2% scene success, 20/21) | none | `scene_from_photo.py`, `grounding_contract.py` | — | No | — | B12, A9, A10 | photo path not a job handler | RESEARCH_ONLY |
| B16 | Floorplan-to-scene / mixed input | P10 §14 | NOT_YET_SOLVED (no code exists, grep-verified) | — | — | — | No | — | — | — | NOT_APPLICABLE |

## C. Spatial architecture program P1–P10 (`research/spatial_architecture`)

| # | Capability | Src | Status | Prod (before) | Res | Dest (after) | Mig? | Risk | Deps | Excl | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | P1 deterministic collision resolver (`resolve_collisions`, `find_valid_nudge`, tangent/radial/embed lattice) | decisions.md P1 | PARTIAL PASS — residual is a perception duplicate, not a solver gap | none | `collision_solver.py` | `app/spatial/collision_solver.py` | Yes (library) | low: wraps `validate_object` | A10 | duplicate-grounding residual stays PERCEPTION_FAILURE | MIGRATE_FULL |
| C2a | P2 clearance: pairwise, functional envelope, door swing, circulation (widest path) | decisions.md P2, clearance.md | PARTIAL PASS (10/10 adversarial, deterministic; 0.4–3.5 s/scene circulation) | `Violation.severity` string exists | `clearance_engine.py` | `app/spatial/clearance_engine.py` | Yes (library) | low; NOT wired into `validate_scene` (latency cost noted in P2) | A10 | see C2b | MIGRATE_VALIDATED_PORTION |
| C2b | P2 dining-chair pull-back, kitchen work aisle (wall-relative), ACCESSIBILITY evaluation, PREFERENCE category | clearance.md P2.3 | "researched… NOT implemented" / "defined, not evaluated by default" | — | policy table only | — | No | — | — | — | PARTIAL_KEEP_PARTIAL |
| C3a | P3 greedy default | decisions.md P3 | PASS "GREEDY ARCHITECTURE SUFFICIENT" | `place_objects` | `solve_greedy` (harness copy) | unchanged | No | — | — | second greedy not migrated (no second solver) | ALREADY_PRODUCTION |
| C3b | P3 bounded LOCAL backtracking (`solve_backtracking`, `PlacementTask`, `score`) | decisions.md P3/P4 (LEVEL 3, budget 400, 0–2 ms) | validated as P4 escalation | none | `scene_optimizer.py` | `app/spatial/bounded_search.py` | Yes (portion) | low | C2a, A10 | beam, whole-scene DFS default, CP-SAT/MILP (rejected); per-failure escalation *design* (deferred) | MIGRATE_VALIDATED_PORTION |
| C3c | P3 beam / DFS-as-default / greedy+repair harness | decisions.md P3 | REJECTED as defaults; comparison harness | — | `scene_optimizer.py` (kept) | — | No | — | — | — | RESEARCH_ONLY |
| C4 | P4 repair loop (DETECT→CLASSIFY→LOCALIZE→REPAIR→RE-VALIDATE→ESCALATE, 6 terminal states, LEVEL 4 opt-in) | decisions.md P4, repair.md | PASS (12/12, real 20/21 unchanged) "production-shaped" | none | `repair_engine.py` | `app/spatial/repair_engine.py` | Yes (library) | low | C1, C2a, C3b | no rotation repair; LEVEL 4 stays opt-in; never repairs UPSTREAM_REQUIRED | MIGRATE_FULL |
| C5 | P5 wall representation: `extrusion_direction`, `TiltedWall`, `object_wall_collides`, wall-local frame | decisions.md P5 (3-step production path) | PASS; "at 0°, OLD and NEW agree exactly" | `Wall` 2D-only; H2 single rectangle | `wall_geometry.py` | `app/spatial/wall_geometry.py`; `Wall.extrusion_direction`; H2 → `object_wall_collides` | Yes (steps 1+3) | low: proven identical for vertical walls (new equivalence test, 5 000+ checks) | A10 | step 2 (`scene_from_photo` reads `normal[1]`) = photo path → DEFERRED; curved/glass walls not modelled | MIGRATE_FULL |
| C6 | P6 typed frames (8 `FrameId`, `Rigid3`, `Point3/Vector3/Direction3`, `frame_graph` wrappers) | decisions.md P6 | PASS | `to_blender_xyz`, `_to_canonical`, `footprint_corners` unchanged | `coordinate_frames.py`, `transforms.py`, `frame_graph.py` | `app/spatial/{coordinate_frames,transforms,frame_graph}.py` | Yes (library) | low: wraps, never replaces call sites | C5 | SCREEN/DEPTH/FLOORPLAN/BUILDING frames; asset forward-axis correction (deferred) | MIGRATE_FULL |
| C7 | P7 `SpatialScene`, 6-kind `GeometricRelation`, sha1 `relation_id`, `recompute_relations` (staleness), `check_consistency` (diagnose only), canonical serialization `p7.1` | decisions.md P7 | PASS (22/22, 0 findings) | `Scene`, `SpatialRelation` vocab | 5 modules | `app/spatial/{relation_model,scene_model,scene_graph,scene_consistency,scene_serialization}.py` | Yes (library) | low | A11 | CONTACTS/ON_FLOOR (no evidence); undo history; observer machinery | MIGRATE_FULL |
| C8 | P8 `Intent` (5 sources, priority), `Constraint` (10 types, SOFT), compiler (`apply_constraints_to_plan` → typed `facing`), read-only evaluator (60°, 0.3 m) | decisions.md P8/P9 | PASS | `ObjectRelation`/`RelationType` | 4 modules | `app/planning/{intent_model,constraint_model,constraint_compiler,constraint_evaluator}.py` | Yes (library) | low | C7, A9 | HARD enforcement (no solver mechanism); `SOLVER_DECIDED` never constructed; job-handler wiring needs `object_key` resolution → DEFERRED | MIGRATE_FULL |
| C9 | P9 typed `Candidate`, DISTANCE ring (16) + BETWEEN grid (7×5) generators, `filter_feasible` (hard gate = `validate_object`), deterministic rankers, `regenerate_after_placement` | decisions.md P9 (40/40) | PASS | production tuple candidates + `_relation_candidates` unchanged | 4 modules | `app/planning/{candidate_model,candidate_generators,candidate_filters,candidate_ranker}.py` | Yes (library) | low | C8, A10 | no ORIENTATION generator (production's works); native `RelationType` BETWEEN/CENTERED → DEFERRED; FACES+NEAR composite in one pass (debt) | MIGRATE_FULL |
| C10 | P10 12-category `FailureCategory` | decisions.md P10 §8 | PASS | none | `failure_taxonomy.py` | `app/spatial/failures.py` (enum); historical record stays research | Yes (portion) | none | — | `HISTORICAL_FAILURES` is a record, not code | MIGRATE_VALIDATED_PORTION |
| C11 | P10 authority matrix, production boundary table, pipeline-stage contracts, provenance traces | P10 docs | PASS (audit artifacts) | — | `authority_audit.py`, `production_boundary.py`, `integration_audit.py` | — | No | — | — | — | RESEARCH_ONLY (audit) |
| C12 | Frozen benchmarks (P1–P10 + spatial_engine) | all reports | regression infrastructure | — | `*_benchmark.py` | — | No (shims keep them running) | — | — | — | RESEARCH_ONLY (kept, re-run) |
| C13 | Brief path with LLM intent extraction | P10 §14 | CONTROLLED_BETA ("staged rollout / human review") | A2, A6 | — | — | No | — | provider | — | CONTROLLED_BETA |
| C14 | Blender Cycles/OptiX render 11.4 s; Qwen2.5-VL 7B 3.47 GB + 2.70 GB spill | P10 §10 | measured on RTX 3050 6 GB / 16.8 GB RAM | — | — | — | No | — | — | one-shot only, not interactive | HARDWARE_LIMITED |

## D. Counts

ALREADY_PRODUCTION 24 · MIGRATE_FULL 7 · MIGRATE_VALIDATED_PORTION 3 ·
PARTIAL_KEEP_PARTIAL 1 · CONTROLLED_BETA 2 · RESEARCH_ONLY 7 · MODEL_LIMITED 7 ·
HARDWARE_LIMITED 1 · REJECTED 4 · DEFERRED 1 · NOT_APPLICABLE 3.

Deferred sub-items recorded inside rows (not separate capabilities): P5 step 2,
P8/P9 job-handler wiring, native `RelationType` BETWEEN/CENTERED, P3 per-failure
escalation design, asset forward-axis correction, P2 circulation wiring into
`validate_scene`.

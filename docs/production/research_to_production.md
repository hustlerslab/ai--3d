# Research → Production migration record and final report

Date: 2026-09-16. Scope: the whole repository (`app/`, `research/`, `tests/`,
`docs/`, `scripts/`, `blender/`), not only P1–P10. Inventory of every
capability with its classification: `docs/spatial_architecture/
productionization_inventory.md` (referenced below by row id, e.g. C5).

## A. Executive summary

Everything the repository had proven, finalized and decided to ship on the
brief path now lives in production code. Twenty-two validated library modules
from `research/spatial_architecture/` (P1, P2's four validated clearance checks,
P3's bounded local backtracking, P4, P5, P6, P7, P8, P9, P10's failure
taxonomy) were moved into `app/spatial/` and `app/planning/`; the research
files became re-export shims so every frozen benchmark still runs and every
historical reproduction still imports. The single behavioural production change
is the one P5 itself recorded as its production path and proved
output-identical for vertical walls: `Wall.extrusion_direction` (default
`(0,1,0)`) and a height-aware H2 collision check. The photo-perception path,
the VLM relation experiments, ControlNet, rear-extent, relative-depth wall
contact and the deep-search solvers stay exactly where their verdicts left
them: research-only, model-limited, or rejected. No job handler, API route,
provider, solver, or scene representation changed. `app/` still imports nothing
from `research/`. Full suite: 725 passed / 7 skipped / 30 xfailed (§L). Every
frozen benchmark reproduced its pre-migration content (§M). Determinism
verified over 20 runs (§N).

## B. Complete repository inventory

`docs/spatial_architecture/productionization_inventory.md` — 55 capabilities
across A (shipped pipeline, 24), B (photo-perception research, 16) and C
(spatial architecture P1–P10, 15). Counts: ALREADY_PRODUCTION 24 ·
MIGRATE_FULL 7 · MIGRATE_VALIDATED_PORTION 3 · PARTIAL_KEEP_PARTIAL 1 ·
CONTROLLED_BETA 2 · RESEARCH_ONLY 7 · MODEL_LIMITED 7 · HARDWARE_LIMITED 1 ·
REJECTED 4 · DEFERRED 1 · NOT_APPLICABLE 3.

## C. Migration matrix

| Capability | Status | Production? | Evidence | Remaining limitation |
|---|---|---|---|---|
| Greedy placement `place_objects` (A9) | PASS | Yes (unchanged) | scene_validity 12/12, P3 | none new |
| 2D validation H1–H5 (A10) | PASS | Yes; H2 height-aware | P0 baseline; P5 "0° identical"; new 5 000-check equivalence test | vertical-only walls still produced by all production paths |
| Asset registry / normalization / catalog / materials (A12–A14) | PASS | Yes (unchanged) | asset audit 58/58 | 8 metadata warnings; forward-axis unverifiable |
| Blender manifest/runner/scripts (A15) | PASS | Yes (unchanged) | 12/12 build, read-back p95 0.015 m | render 11.4 s (hardware) |
| Providers: mock / Gemini / Anthropic (A19) | shipped | Yes | tests, golden run | LLM extraction quality unbounded → CONTROLLED_BETA path |
| Ollama provider + generation guard (A5, A19d) | implemented, tested | Yes, explicit opt-in only | `test_generation_guard.py`, 0e/0f scripts | never auto-selected; not on geometric path |
| Meshy image-to-3D (A20) | probe | human-gated only | ADR-003 §8 | founder decision §9 pending |
| ControlNet styling (A21) | not adopted | No | ADR-004 | — |
| VLM relation extraction (B3) | FAIL | No | phase 1c/1d reports | removed from geometric path |
| Relative-depth wall contact (B4), rear extent (B7) | NO-GO / FAIL | No | reports | — |
| MoGe-2, SAM 2, wall quality, extent, floor, grounding (B5–B12) | PARTIAL / MODEL_LIMITED | No (research) | readiness report RED | wall contact 77.8% vs 90%; grounding 46/48 |
| `app/spatial/planes.py`, `app/vision` (B2, B13) | pre-production, unwired | No importers (unchanged) | own docstrings | remain unwired until photo path leaves RESEARCH_ONLY |
| Photo→Scene bridge (B15) | PARTIAL 20/21 | No (research) | integration_benchmark | RESEARCH_ONLY per P10 |
| P1 collision resolver (C1) | PARTIAL PASS (solver part complete) | **Yes — `app/spatial/collision_solver.py`** | 16/21→20/21 | duplicate-grounding residual is perception |
| P2 clearance, 4 checks (C2a) | PARTIAL PASS | **Yes — `app/spatial/clearance_engine.py`** (library; not in `validate_scene`) | 10/10, deterministic | circulation 0.4–3.5 s/scene; dining-chair/kitchen/accessibility/PREFERENCE not implemented (C2b) |
| P3 bounded local backtracking (C3b) | validated (P4 LEVEL 3) | **Yes — `app/spatial/bounded_search.py`** | P3/P4 | never a default; per-failure escalation design not built |
| P3 beam / DFS default / greedy harness (C3c) | rejected as default | No (research harness) | P3 | — |
| P4 repair loop (C4) | PASS | **Yes — `app/spatial/repair_engine.py`** | 12/12; real 20/21 | LEVEL 4 opt-in; no rotation repair |
| P5 wall geometry (C5) | PASS | **Yes — `app/spatial/wall_geometry.py`, `Wall.extrusion_direction`, H2** | tilt sweep; equivalence test | step 2 (photo bridge reads `normal[1]`) deferred with photo path |
| P6 frames/transforms/frame_graph (C6) | PASS | **Yes — `app/spatial/{coordinate_frames,transforms,frame_graph}.py`** | 27 tests | wrappers; production call sites unchanged by design |
| P7 SpatialScene/relations/graph/consistency/serialization (C7) | PASS | **Yes — `app/spatial/{relation_model,scene_model,scene_graph,scene_consistency,scene_serialization}.py`** | 58 tests, 22/22 | callers must call `recompute_relations` explicitly |
| P8 intent/constraint/compiler/evaluator (C8) | PASS | **Yes — `app/planning/{intent_model,constraint_model,constraint_compiler,constraint_evaluator}.py`** | 83 tests, 30/30 | all SOFT; job-handler wiring deferred (needs `object_key` resolution) |
| P9 candidates (C9) | PASS | **Yes — `app/planning/{candidate_model,candidate_generators,candidate_filters,candidate_ranker}.py`** | 73 tests, 40/40 | FACES+NEAR single-pass composite (debt); native BETWEEN/CENTERED `RelationType` deferred |
| P10 failure taxonomy enum (C10) | PASS | **Yes — `app/spatial/failures.py`** | 7 tests | historical record stays research |
| P10 audits, all benchmarks (C11, C12) | PASS | No (research, kept) | re-run this pass | — |
| Floorplan / mixed input (B16) | NOT_YET_SOLVED | No | grep-verified absence | — |

## D. Production architecture (after)

```
brief ──analyze──▶ DesignAnalysis/StyleSpec ──scene_plan──▶ ObjectPlan (+image-space spatial graph)
   ──asset_decision──▶ AssetPlan ──compile_scene──▶ Scene(rooms, Wall[+extrusion_direction], openings)
   ──place_objects (greedy, _relation_candidates, _pick_support)──▶ validate_object (H1..H5, H2 height-aware)
   ──commit_patch──▶ validate_scene ──build──▶ build_manifest ──▶ Blender ──▶ validation_report.json
```
Production-resident, callable libraries (no handler wiring; authority
unchanged): `app/spatial/{collision_solver, clearance_engine, bounded_search,
repair_engine, wall_geometry, coordinate_frames, transforms, frame_graph,
relation_model, scene_model, scene_graph, scene_consistency,
scene_serialization, failures}` and `app/planning/{intent_model,
constraint_model, constraint_compiler, constraint_evaluator, candidate_model,
candidate_generators, candidate_filters, candidate_ranker}`. Authority
hierarchy (P10 §3, 17 artifacts, zero AI override) is unchanged: only
`place_objects`, `repair_scene` and `regenerate_after_placement` write
geometry; `validate_object` is the single hard gate everywhere.

## E. Migrated capabilities

C1, C4, C5, C6, C7, C8, C9 (MIGRATE_FULL); C2a, C3b, C10 (validated portion).
Mechanics: each research module was copied into `app/`, its `sys.path`
bootstrap removed, cross-imports rewritten to `app.*`, its "Research only"
sentence replaced by a migration note; the research file became a shim that
re-exports the canonical module's namespace (`test_research_shims_reexport_the_
canonical_app_objects` asserts identity object-by-object).

## F. Partially migrated capabilities

- **P2 clearance**: pairwise / functional / door-swing / circulation migrated.
  Dining-chair pull-back, kitchen work aisle, ACCESSIBILITY evaluation and the
  PREFERENCE category are NOT implemented — the policy table records them;
  nothing was invented. Not wired into `validate_scene` (P2's own latency note).
- **P3 optimization**: `solve_backtracking`/`PlacementTask`/`score` migrated as
  `bounded_search` (P4's LEVEL 3 escalation). Greedy stays `place_objects`;
  beam/DFS-default/greedy+repair remain a research harness.
- **P5 wall representation**: steps 1 and 3 done (schema field, H2). Step 2
  (photo bridge reading `normal[1]` via `up_from_normal`) is deferred with the
  photo path; production paths still emit vertical walls only.
- **P10 failure taxonomy**: `FailureCategory` migrated; `HISTORICAL_FAILURES`
  stays a research record.

## G. Intentionally excluded capabilities

VLM relation extraction (B3, FAIL), relative-depth wall contact (B4, NO-GO),
rear extent (B7, FAIL), UniDepthV2 (license), ControlNet styling (A21, not
adopted), CP-SAT/MILP and beam/DFS as defaults (P3), global optimizer / second
solver (P8/P9/P10 non-goals), whole-scene shared-budget backtracking (P4),
constraint relaxation (P4), rotation repair (P4), a second `Scene` type
(architecture decision B/C), ROS-tf-style frame tree (P6), 7-channel
confidence, CONTACTS/ON_FLOOR relations without an evidence source, an
ORIENTATION candidate generator (P9: production's works), photo→scene job
handler wiring (RESEARCH_ONLY), `app/spatial/planes.py`/`app/vision` wiring.

## H. Model-limited capabilities

MoGe-2 metric depth, SAM 2 grounding, wall-quality gate (77.8% contact
precision, 25% UNKNOWN), catalogue-grounded extent, floor hypothesis, object
grounding (46/48), Grounding DINO detector. Interfaces preserved as research
modules; UNKNOWN/abstention preserved; no threshold lowered.

## I. Hardware-limited capabilities

Blender Cycles/OptiX render 11.4 s (one-shot only); Qwen2.5-VL 7B 3.47 GB +
2.70 GB spill (off the geometric path). Measured on RTX 3050 Laptop 6 GB /
~16.8 GB RAM; models never co-resident. No correctness path depends on more.

## J. Remaining architectural debt

1. Candidate generation for one constraint type does not consider a second,
   independent constraint type in the same pass (FACES+NEAR composite; P10 §15).
2. Repair (P4), independent intent evaluation (P8, `facing` only) and the P7
   spatial scene are now invoked by `scene_plan` via
   `app/planning/spatial_pipeline.py` (see `frontend_integration_audit.md`).
   Still open: a native `RelationType` for BETWEEN/CENTERED (P9 §26) so the
   NEAR/BETWEEN generators have a plan source; and the `against_wall`
   verifier semantics — P7/P8 measure object CENTRE to wall with the 0.25 m
   staleness tolerance, the solver places flush by footprint EDGE (76/107
   solver-placed wall objects sit 0.045 m from the wall by edge yet read
   VIOLATED by centre) — reported as unsupported until a validated
   edge-based CONTACT check exists.
3. Circulation clearance costs 0.4–3.5 s/scene (7.1 s on the P4 circulation
   case) and is therefore not part of `validate_scene`.
4. P5 step 2 (photo bridge) pending the photo path leaving RESEARCH_ONLY.
5. Random `object_id`/`room_id` from `new_id` (uuid4) in `place_objects`/
   `layout_rooms` — pre-existing, documented since P4/P9; geometry is
   deterministic, ids are not.

## K. API / schema / dependency changes

- **Schema**: `app/scene/schema.py:Wall` gains `extrusion_direction: Vec3 =
  (0.0, 1.0, 0.0)`. Backward compatible: old JSON without the key parses to
  the default (tested); new scene JSON carries the key.
- **Validation**: `app/spatial/validation.py` H2 calls
  `wall_geometry.object_wall_collides` (identical verdicts for vertical walls —
  tested across 5 000+ object/wall pairs, three rotations).
- **API routes, job handlers, providers, config settings**: unchanged.
- **Dependencies**: none added. `requirements.txt` untouched.
- **New production modules**: 22 (listed in §D). `app/planning/__init__.py`
  exports unchanged.

## L. Test results

Baseline (before any change): `718 passed, 7 skipped, 30 xfailed` (126 s).
After migration: `725 passed, 7 skipped, 30 xfailed` (109 s) — +7 from
`tests/test_productionization.py`, zero failures, nothing skipped or xfailed
that was not before.
Changes: 23 existing test files re-pointed from `research.spatial_architecture.X`
to `app.spatial.X` / `app.planning.X` for the migrated modules (they now test
production directly; assertions untouched); new `tests/test_productionization.py`
(7 tests: schema default + old-JSON parse, H2 old/new equivalence sweep,
leaning-wall H2 behaviour, shim identity, partial-migration boundaries,
`app/` never imports `research/`, all migrated modules import). No test
deleted, weakened, or marked xfail.

## M. Benchmark results (all re-run this pass, compared to pre-migration JSON)

| Benchmark | Result | Content vs. pre-migration |
|---|---|---|
| P2 clearance (10 cases) | 10/10 | identical |
| P3 optimization | unchanged verdicts | identical |
| P4 repair (12 cases) | 12/12 | identical |
| P5 wall (tilt sweep) | identical | identical |
| P6 coordinate | identical | identical except `overhead_ratio` (timing-derived) |
| P7 scene (22 adversarial) | 22/22, 0 findings | identical except `json_bytes` +88 per scene = 2 walls × `extrusion_direction` (expected, P5 step 1) |
| P8 constraint (30) | 30/30 | identical (constraint-id keys differ: random `object_id`, documented P9) |
| P9 candidate (40) | 40/40 | identical (same id caveat) |
| P10 integration (30) | 30/30, metrics physical 1.0 / intent 0.4 / evidence 1.0 / system 1.0 | byte-identical |
| scene_validity (12 briefs) | 12/12 valid | identical |
| blender_e2e (12 scenes) | 12/12 built, 0 errors | identical except stage timings and random `obj_*` read-back ids |
| integration_benchmark (21 images, GPU + Blender) | 20/21 valid, hard `{COLLIDES_WALL:1, COLLIDES_OBJECT:2}`, resolver moved 13 / unresolved 1, repair `3 -> 3`, `{ALREADY_VALID:20, UNREPAIRABLE:1}`, Blender 20/20 | identical except host RAM stats and random `room_*` ids inside Blender warning strings |

BEFORE/AFTER for the one deliberate change: canonical `SpatialScene` JSON and
scene JSON now include `"extrusion_direction": [0.0, 1.0, 0.0]` per wall. WHY:
P5's adopted representation. EXPECTED EFFECT: none on any verdict; walls
produced by `layout_rooms` are vertical.

## N. Determinism (20 runs each, post-migration)

`brief_end_to_end_demo(regenerate=True)` content (verdicts, hard count, placed)
identical; canonical serialization + sha1 relation ids byte-identical;
`repair_scene` terminal state and records identical; `validate_scene` (new H2)
identical; `p10_integration_benchmark.determinism_check(20)` True; multi-
constraint composite byte-identical ×20. Known non-deterministic values:
`object_id`/`room_id` (pre-existing `new_id`).

## O. Blender results

`blender_e2e_benchmark`: 12/12 built, 0 errors, 91.8% dims ok; 21-image
integration: 20/20 ok, XY read-back unchanged. Manifest unaffected by the
`Wall` field (manifest builds wall entries from explicit fields).

## P. Performance (post-migration, this machine)

`validate_scene` with height-aware H2: median 0.08 ms (2-object scene);
`all_clearance_violations` incl. circulation: 0.03 ms on that scene, 7.1 s on
P4's circulation case (unchanged from P4's 7–8 s); `repair_scene`: median
2.05 ms (case 1), median 2.58 ms across the 12 P4 cases; brief demo
(`place_objects` + compile + evaluate + regenerate, 5 objects): median 5.0 ms;
candidate regeneration 1.3–1.4 ms/object (benchmark). Model/Blender latencies
unchanged from P10 §10 (not re-measured; no model code touched). No
performance claim beyond "no measurable regression on the deterministic core".

## Q. Production boundary (unchanged, per P10 §14)

brief → deterministic core: PRODUCTION_READY · brief + LLM: CONTROLLED_BETA ·
photo → scene: RESEARCH_ONLY · photo perception: MODEL_LIMITED · floorplan /
mixed input: NOT_YET_SOLVED. The migration moved code, not boundaries.

## R. Final git audit

Tracked production files modified by this pass: `app/scene/schema.py` (+5 lines),
`app/spatial/validation.py` (+4/−3). New untracked production modules: 22 under
`app/spatial/` and `app/planning/`. New test: `tests/test_productionization.py`.
Docs: this file, `productionization_inventory.md`, a pointer entry in
`decisions.md`. Research: 20 files replaced by shims, `scene_optimizer.py` and
`failure_taxonomy.py` trimmed to their research-only portions; `*_results.json`
re-generated by the re-runs (timings only). No temporary files, benchmark logs
or backups inside the repository (they live in the session scratchpad).
Pre-existing modified/untracked files from earlier sessions are untouched.
**Note**: the entire spatial research body and the migrated modules are
untracked; committing them is the cheapest way to make the validated work
durable (not done here — commits are the user's call).

## S. Known remaining risks

- Any caller that adds a leaning wall must also set `extrusion_direction`;
  nothing in production does so yet, so the field is inert until the photo
  bridge is wired (P5 step 2).
- P-phase documentation still names the research paths for modules now in
  `app/`; the decisions.md pointer entry explains the move, history is not
  rewritten.
- Migrated libraries are reachable but unwired; the CONTROLLED_BETA/RESEARCH
  classifications still gate their use in handlers.
- Random ids (`new_id`) remain the only nondeterminism in the pipeline.

## Final architecture audit (§46)

Every final geometric decision traceable — yes (P10 traces, unchanged code
paths). Every placement explains its selection — yes (`_relation_candidates`
order + `validate_object`; P9 `Candidate.provenance`). Every failure names its
layer — `FailureCategory` now production. Providers replaceable without
touching geometry — yes (Protocol + no geometry in providers). Assets
replaceable without touching the solver — yes (`AssetDecision` boundary).
Blender replaceable without touching spatial reasoning — yes (`build_manifest`
is the only boundary). Constraints evaluable independently — yes
(`evaluate_all`, read-only). UNKNOWN / INFEASIBLE reportable — yes
(`ConstraintStatus`, wall-quality abstention). Repair auditable — yes
(`RepairRecord`, terminal states). User/model assertion distinguishable from
observation — yes (`IntentSource`, `SpatialSource`).

## Acceptance checklist (§51)

- [x] Entire repository inventoried
- [x] All historical finalized work identified (ADR-001..004, AUDIT, phase 0b–1h, spatial_engine 0–16, P1–P10)
- [x] All PASS/finalized work classified
- [x] All PARTIAL work classified (C2, C3, C5, C10; B5–B12)
- [x] All failed/rejected work excluded (B3, B4, B7, A21, P3/P4 rejections)
- [x] All research-only work excluded (B2, B13, B15, C3c, C11, C12, A22)
- [x] Model-limited work preserved without fake certainty
- [x] Hardware-limited work classified
- [x] Validated portions of PARTIAL systems migrated (C2a, C3b, C5 steps 1+3, C10)
- [x] P1–P10 validated architecture migrated
- [x] Earlier finalized capabilities verified already in production (A1–A19)
- [x] No duplicate canonical systems (shims re-export; identity-tested)
- [x] No second solver (greedy harness copy not migrated)
- [x] No second scene representation (`SpatialScene` wraps `Scene`)
- [x] No silent coordinate mismatch (P6 wrappers; call sites unchanged)
- [x] AI cannot override final geometry (authority audit unchanged)
- [x] Provenance, UNKNOWN, INFEASIBLE preserved
- [x] Existing production behaviour preserved (benchmarks identical)
- [x] New production behaviour tested (`test_productionization.py`)
- [x] Frozen benchmarks checked (all 12 re-run)
- [x] Determinism verified (20 runs)
- [x] Blender verified (12/12 and 20/20)
- [x] Full test suite executed (725 / 7 / 30)
- [x] Every production change inspected (`git diff`, §R)
- [x] Production boundary documented (§Q)
- [x] Remaining debt documented (§J)
- [x] No unsupported architecture invented

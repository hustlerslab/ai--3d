# P1-VALIDATOR-001 — Promote render verification to production · verification

**2026-09-26 · Hat:** 3D Engineer (+ Blender, QA) · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real) · **Meshy spend: 0**

## What was promoted, from where

`research/placement_loop.py` already measured coverage 100%, placement 91% @1.0m, orientation 100%, composite 98% (N=1), using `blender/scripts/check_visibility.py` (ray-cast, not a model) and `blender/scripts/render_viewpoints.py` (already existed, opens the saved `.blend` without rebuilding — promoted with a job in P1-BLENDER-002). Both scripts are **unchanged**. What moved is the *method* into a typed, tested, production module and the loop's local dict math into design.md §16's `VerificationEvidence` contract.

## Built

| Where | What |
|---|---|
| `app/verification/render_verifier.py` (new) | `VerificationEvidence`, `PerObjectEvidence` (Pydantic, `extra="forbid"`); `verify_scene()` — a pure function, no Blender call, no I/O; `default_viewpoints()` — the same room-corner viewpoint choice the research script used |
| `app/jobs/handlers/verify.py` (new) | `verify` job, `lane=JobLane.render`. Requires a build first. Renders corner viewpoints + ray-casts visibility via `BlenderRunner` directly (same low-level pattern as `build`/`preview`), reads the build's own validation report and the object plan, calls `verify_scene()`, writes `planning/render_verification.json` |
| `app/projects/layout.py` | `CHECKPOINTS["render_verification"]` |

## The 13-check table (design.md §16), and what each is computed from

| # | Check | Deterministic? | Computed from |
|---|---|---|---|
| 1 | Expected objects exist | yes | Blender build's own `validation_report.json` (`"no geometry"` errors) |
| 2 | Object count | yes | same report (`"placed N of M objects"`) |
| 3 | Major objects visible | yes | `check_visibility.py` ray-cast — **not a model** |
| 4 | Approximate location | yes | committed `Scene` vs the read anchor (`compiler.anchor_spot`, same as the research script) |
| 5 | Scale | yes | build report's ±25% bbox-vs-manifest note, per object |
| 6 | Orientation | yes | yaw vs `facing_dir` (`compiler._rotation_facing`, same as the research script) |
| 7 | Floating objects | yes | **new**: floor-mounted object's height vs `room.floor_height`, ±2cm |
| 8 | Severe intersections | yes | `app/spatial/validation.py::validate_scene` (`COLLIDES_WALL`/`COLLIDES_OBJECT`, hard) |
| 9 | Room architecture preserved | yes | build report (`"no floor mesh"`/`"no ceiling mesh"`/`"pivot outside room"`) |
| 10 | Doors/windows respected | yes | `validate_scene`'s `BLOCKS_DOOR` + `clearance_engine.door_swing_violations` |
| 11 | Circulation | yes, when an entrance point is known | `clearance_engine.circulation_violations` — `unknown` without an `entrance_xz` param, same as every other caller of that function in this codebase (it has always been `Optional` with no resolver) |
| 12 | Major materials match | **no — model** | never computed here; always `unknown` |
| 13 | Major colours match | **no — model** | never computed here; always `unknown` |

**11 of 13 deterministic**, matching design.md §16 and task.md's acceptance criterion exactly.

**Found while implementing (not a correction — design.md's own docstring flags it):** `check_visibility.py`'s own reasoning is the citation for *why* checks 3, 12 and 13 are separated: a vision model asked to name what it saw scored the same unchanged scene 0.556/0.778/0.556/0.556 across four reads while inventing a dining table that wasn't there. Visibility stayed ray-cast; materials/colours stayed unimplemented rather than faked with an un-wired model call.

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| 11 of 13 checks deterministic | table above; `test_check_names_match_design_doc_split` asserts the 11/2 split by name |
| Visibility decided by ray-cast, never asking a model | `verify` job calls `check_visibility.py` through `BlenderRunner`; `major_objects_visible` is derived only from its `visible`/`in_frame` counts |
| A check that could not run yields `unknown`, not a pass | `major_materials_match`/`major_colours_match` are unconditionally `"unknown"`; `approximate_location`/`orientation`/`circulation` are `"unknown"` when their inputs (a read anchor, a `facing_dir`, an entrance point) are absent — proven both on a synthetic scene (`test_a_check_that_could_not_run_is_unknown_not_a_pass`) and on the real MOCK-provider pipeline, where the synthetic plan sets neither field, so both come back `"unknown"` for all 40 objects rather than a fabricated `"pass"` (`sample_render_verification.json`) |

## Tests (`tests/test_render_verifier.py`, 8 tests)

Pure-function tests (MOCK class, no Blender, fast) exercise `verify_scene()` directly against hand-built scenes: check-name/split invariant, model checks always `unknown`, an all-`unknown` scene is not a failure, a missing-geometry build report fails `expected_objects_exist`, a visible/never-in-frame object passes/fails the visibility check, a floor object hovering 0.5m up fails `floating_objects`.

`test_verify_job_end_to_end` — the real promotion proof: analyze → scene-plan → build → **verify**, against real Blender, on the golden test brief (4 rooms, ≥12 objects). Asserts the job succeeds, `planning/render_verification.json` exists with every check name present per object, model checks are `"unknown"`, and the project's output list carries the new `render_verification` kind.

**Real sample output** (`sample_render_verification.json`, from an actual run of this session): 40 objects across 4 rooms, **coverage 69.6%** (some pieces occluded from the 4 corner shots — a real, unforced ray-cast result, not curated), `asset_bound` 1.0 (every intended piece has a mesh), `approximate_location`/`orientation`/`circulation` correctly `unknown` (the MOCK intelligence provider's synthetic plan sets no read anchors or facing directions, and no entrance point was supplied) rather than defaulting to a false pass.

**Mutation (1):** made `VerificationEvidence.ok` unconditionally return `True` (`sha1` before `c37a106e...`, restored, `sha1` after `c37a106e...` — identical) → 3 of 7 MOCK tests failed (`assert not evidence.ok`), confirming the `ok` aggregate is actually load-bearing and not just decorative.

## Full suite after the change

`class=PRODUCTION-PATH passed=18 failed=0` (up from 17 — the 1 new real-Blender end-to-end test) · `class=MOCK passed=1496 failed=1` (same pre-existing CLIP failure, unrelated; +7 new pure-function tests) — see `pytest_verbose.txt`.

**Outcome:** the render-verification chain design.md calls "the gate, not the renderer" is now callable through the job system, produces a typed, evidence-linked artifact per build, and is honest about what it doesn't know rather than silently passing it.

**Owed:** `major_materials_match`/`major_colours_match` need a live model and a labelled/benchmarked choice of which one (P1-MM-002) — not built here, correctly reported `unknown` until then. `approximate_location`/`orientation` need a real moodboard reading with anchors/`facing_dir` (works automatically once one exists — no code change needed, just real client input instead of the MOCK provider's synthetic plan). `circulation` needs an entrance point, which nothing in the codebase resolves yet.

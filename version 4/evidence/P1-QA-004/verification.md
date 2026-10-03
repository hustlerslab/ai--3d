# P1-QA-004 — Visual and 3D regression · verification

**2026-09-26 · Hat:** QA Engineer (+ Blender Engineer) · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real) · **Meshy spend: 0**

## Built

| Where | What |
|---|---|
| `tests/test_visual_3d_regression.py` (new) | Golden-image visual regression (pixel diff against a stored PNG) and 3D structural regression (position/rotation diff against a stored JSON), kept **deliberately separate** functions |
| `docs/benchmarks/regression_baselines/golden_preview.png` | Baseline render: `tests.test_blender_build._compiled_scene()` (the same fixture `test_blender_build.py` itself already uses — not a new dataset), preview profile, EEVEE, raytracing on |
| `docs/benchmarks/regression_baselines/golden_structure.json` | Baseline structure: room boundaries + every object's position/rotation/dimensions, keyed by `plan_key` (see below) |
| `docs/benchmarks/regression_baselines/meta.json` | Method, date, N for every measured number — the threshold, the noise-floor measurement it's based on, and the moved-object measurement |

**Found while implementing:** `SceneObject.object_id` is `Field(default_factory=lambda: new_id("obj"))` — a **fresh random id on every `_compiled_scene()` call**, so a baseline keyed by `object_id` can never match a later run of the same fixture (first attempt failed on exactly this: "object set differs", the whole object list). Re-keyed on `plan_key` instead, which is the plan's own stable identifier (semantic_type + index) — confirmed deterministic across two independent `_compiled_scene()` calls before relying on it.

## The threshold, measured not guessed

Rendered the same scene twice, no code change, compared pixel-for-pixel (N=2, method and date in `meta.json`):

| Engine | mean abs diff (0–255) | fraction of pixels changed >2/255 |
|---|---|---|
| Cycles, 16 samples | 0.000039 | 0% |
| EEVEE, 16 samples (raytracing on) | 0.000327 | 0% |

**Threshold adopted: mean ≤ 1.0 AND fraction of pixels changed by >10/255 ≤ 0.1%** — roughly 3,000×–25,000× the measured noise floor on the mean, and near-zero tolerance for large-magnitude change. `test_visual_regression_catches_a_real_render_change` proves this threshold isn't vacuous: rendering the same tiny scene with `use_raytracing` on vs off (a real, adopted setting change, P1-RENDER-002) produces `fraction_changed` **well above** the 0.1% cutoff — the exact measurement (`mean≈0.48`, `~1.4%` of pixels) already recorded in P1-RENDER-002's own evidence, reproduced here as the regression mechanism's own proof that it rejects real change.

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Baselines cannot be updated by a normal CI run — explicit env-gated regenerate required | `regenerate_baselines()` raises `BaselineRegenerationNotAuthorized` unless `AETHER_REGENERATE_BASELINES=1`; `test_regeneration_refuses_without_the_explicit_env_flag`; mutation-tested (below) |
| A threshold chosen to hide drift is rejected in review | the threshold is derived from a measured noise floor with the measurement itself committed (`meta.json`), not picked to make a specific run pass — and `test_visual_regression_catches_a_real_render_change` demonstrates it actually rejects a real, adopted change |
| A moved object fails 3D regression even if the render looks similar | `test_moved_object_fails_3d_regression_even_when_the_render_looks_the_same`: a 0.03m nudge on an **off-camera** floor object — real render measured `mean=0.007`, `0` pixels changed >10/255 (well inside the "looks the same" threshold) — still fails structural regression outright, because that check compares position tuples, not pixels |

## Real-Blender proof (6 tests: 4 MOCK/pure-comparison + 2 real Blender)

- `test_baselines_are_committed_and_documented` — the baseline files and their metadata exist
- `test_regeneration_refuses_without_the_explicit_env_flag`
- `test_visual_regression_passes_against_its_own_unchanged_baseline` (real Blender) — rebuilding the identical scene and re-rendering matches its own baseline
- `test_visual_regression_catches_a_real_render_change` (real Blender) — raytracing on vs off is caught
- `test_3d_regression_passes_against_its_own_unchanged_baseline`
- `test_moved_object_fails_3d_regression_even_when_the_render_looks_the_same`

**Mutation (2):** (1) disabled the env-gate check in `regenerate_baselines` — `test_regeneration_refuses_...` failed (`DID NOT RAISE`). (2) widened the structural position-diff tolerance from `1e-6` to `1.0` (past the 0.03m test nudge) — `test_moved_object_fails_3d_regression_...` failed (`assert not True`). Both restored, `sha1` before `6a52cf8d...` / after `6a52cf8d...` — identical.

## Full suite after the change

`class=PRODUCTION-PATH passed=21 failed=0` (up from 19 — the 2 new real-Blender regression tests) · `class=MOCK passed=1507 failed=1` (same pre-existing CLIP failure, unrelated; +4 new regression-logic tests) — see `pytest_verbose.txt`.

**Outcome:** a solver regression is now caught by structure, independent of whether the picture still looks plausible; a render regression is caught against a documented, measured threshold rather than an arbitrary one.

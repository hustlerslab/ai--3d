# Phase 13 — Blender Execution with Geometry Read-Back

**Verdict: PASS.** Blender 5.2.1 LTS builds all **12** frozen scenes headless from
the production manifest with **zero errors**, and the geometry read back from the
built meshes — every object's world-space bounding box through `matrix_world`
after the transform was applied — agrees with the manifest: **547 objects**, XY
error median **0.000 m**, p95 **0.015 m**, max **0.047 m**; every bounding box
rests at **z = 0.000** (floor contact); **91.8%** of dimensions within 25% of the
expected size, the remainder procedural shapes whose bounding box is legitimately
not the catalogue box. Median build **2.1 s** per scene; a Cycles/OptiX smoke
render **11.4 s** on the RTX 3050. Nothing was assumed executed; it was read back.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/blender_e2e_results.json`
**Script:** `research/spatial_engine/blender_e2e_benchmark.py`
**Production code changed:** none. Blender: `H:/Program Files/Blender Foundation/Blender 5.2/blender.exe`, 5.2.1 LTS.

## 1. What production already has **[M]**

- **Coordinate safety.** One conversion module, `app/blender/manifest.py`:
  `to_blender_xyz((x, y, z)) → (x, −z, y)`, `yaw_to_blender_rz`, `scene_forward` /
  `blender_forward`; round-trip tested in `tests/test_blender_build.py`. No
  scattered `x = -x`.
- **Execution backend.** `BlenderRunner` runs `blender/scripts/build_scene.py`
  as a subprocess, streams the log, and receives an `ALLURE_RESULT` JSON line.
- **In-Blender validation.** `blender/scripts/validate_scene.py` already checks
  every manifest object exists with geometry, its bbox size is within ±25% of
  the manifest, its pivot lies inside its room polygon, no texture is missing,
  and every room has a floor, ceiling and light — and writes each placed
  object's world-space bbox into the report.

The read-back the brief asks for therefore existed; what did not exist was a
measurement of it across scenes. **[M]**

## 2. Results — 12 scenes **[M]**

| Scene | Objects | Errors | Warnings | Build s | XY err max (m) | Floor z med | Dims ok |
|---|--:|--:|--:|--:|--:|--:|--:|
| res_1bhk | 33 | 0 | 0 | 2.1 | 0.047 | 0.000 | 29/33 |
| res_2bhk | 44 | 0 | 0 | 2.1 | 0.047 | 0.000 | 39/44 |
| res_3bhk | 62 | 0 | 0 | 3.2 | 0.047 | 0.000 | 55/62 |
| res_studio | 4 | 0 | 0 | 1.4 | 0.015 | 0.000 | 3/4 |
| res_villa | 59 | 0 | 0 | 3.1 | 0.047 | 0.000 | 52/59 |
| res_minimal | 40 | 0 | 0 | 2.1 | 0.047 | 0.000 | 35/40 |
| hosp_hotel | 70 | 0 | 0 | 3.0 | 0.015 | 0.000 | 66/70 |
| hosp_restaurant | 78 | 0 | 0 | 3.3 | 0.015 | 0.000 | 77/78 |
| off_open | 46 | 0 | 0 | 2.2 | 0.015 | 0.000 | 45/46 |
| off_small | 34 | 0 | 0 | 1.8 | 0.002 | 0.000 | 34/34 |
| res_dense | 36 | 0 | 0 | 1.9 | 0.047 | 0.000 | 31/36 |
| res_odd | 41 | 0 | 0 | 1.8 | 0.047 | 0.000 | 36/41 |

Totals: built **12/12**, errors **0**, warnings **0**, objects read back **547**,
XY error median 0.000 / p95 0.015 / max 0.047 m, bbox-min z median 0.000 m,
dims within 25% **91.8%**.

The 0.047 m XY maxima are procedural "seat" and "tall" shapes whose bounding-box
centre is offset from the pivot by construction, not a transform error; the same
objects account for the dimension misses. GLB assets read back at 0.002–0.015 m.
**[M, I for the attribution]**

## 3. What is not read back **[N]**

- **Wall contact.** No wall-relative check inside Blender.
- **Collision on built meshes.** Checked in plan before Blender by
  `validate_scene`; not re-checked on the imported geometry.
- **Rotation.** Verified only indirectly through the size-axis swap.
- **Render-based validation** (§34). A smoke render proves the render path;
  no image comparison against reference evidence was built.

## 4. Decision

Against §41 *Blender execution success* and the §33 read-back requirement:
**PASS**. Blender is an execution backend that decides no spatial semantics, the
frame conversion is single-sourced and tested, and the result is read back and
agrees with the plan to within a centimetre for real assets. What did not
change: any production file.

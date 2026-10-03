# P1-ASSET-005 — Measure and store the asset forward axis · verification

**Completed:** 2026-09-25 · **Hat:** 3D Engineer (+ Backend) · **Branch:** `ai-3d` on `92c494a` (dirty) · **Meshy spend: 0** (no vendor call; synthetic glTF fixtures through the real ingester)

## Before

`NormalizationInfo.yaw_offset` was **always 0.0** unless the sourcing manifest declared one (`sourcing/cc0_furniture.json` declares π for one Poly Haven piece and π/2 for two). The only reading of an asset's facing anywhere in the system was `blender/scripts/import_assets.py:_native_forward_yaw`, made **inside Blender on every build** and stored nowhere — so the same mesh could be corrected differently between builds, the registry could not say which way anything faced, and `frame_graph.asset_to_object_transform()` returned identity on the strength of a claim the Phase 10 audit never made (correction **C12**: its results file marks `forward_axis` "UNVERIFIED — not checkable from geometry" for 58/58, and 30 of those 58 are Meshy meshes, not catalog pieces).

## The change

| Where | What |
|---|---|
| `app/assets/orientation.py` (new) | `measure_forward_yaw(doc, semantic_type)` — the Blender reading, ported to glTF's Y-up frame with the same rules ("backrest": forward is away from the tall mass; "thin": faces along the thinner horizontal axis), thresholds (12 % share, 6 % offset, 55 % cut) and quarter-turn snap. **One deliberate difference:** the tall part is the surface area *above* the cut plane with every triangle clipped against it (`tall_part`), not "faces whose centre is above the cut" — on a coarse mesh whole-face selection takes one triangle of a quad and leaves the other, and read a 12-triangle 2×0.8×0.8 box as needing a quarter turn. Clipping is exact on planar faces and converges on dense ones |
| `app/assets/gltf.py` | `world_triangles(doc)` — every triangle of the default scene in world space; read only, same traversal as `measure`; strips and fans unrolled |
| `app/assets/schema.py` | `NormalizationInfo.yaw_source: "unmeasured" \| "declared" \| "measured"` (default `unmeasured`, so every existing registry row loads unchanged); `IngestMeta.yaw_offset: Optional[float] = None` — **None means measure**, a number (including 0.0) is a declaration |
| `app/assets/normalization.py` / `pipeline.py` | `plan(..., yaw_source)`; `ingest_file` measures when nothing is declared and bakes the result into the normalized file's root node as before; `renormalize` keeps a declared yaw and **re-measures** a measured one; the ingest log line names yaw and source |
| `app/api/routes.py`, `scripts/source_cc0.py` | upload / Poly Haven / sourcing defaults `0.0 → None` so an unspecified yaw is measured, not silently declared zero |
| `app/blender/manifest.py` | `asset.forward = {yaw_offset, source}` on every GLB entry |
| `blender/scripts/import_assets.py` | `_native_forward_yaw` runs **only when `forward.source == "unmeasured"`**; the empty records `aether_forward_source` |
| `app/spatial/frame_graph.py`, `coordinate_frames.py` | `asset_to_object_transform(asset_id \| yaw_offset, yaw_source)` → identity when the yaw is 0, otherwise a real `Rigid3(ASSET→OBJECT)`: rotation about +Y matching `normalization._rotate_y`, confidence 0.9 when measured, 1.0 when declared; docstrings corrected per C12 |
| `scripts/audit_forward_axis.py` (new) | measures every registry **original** and reports it beside the stored yaw; registry untouched — the report that says whether the library already agrees with the measurement |

## Acceptance — `tests/test_asset_forward_axis.py` (14 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| **Ingesting a deliberately rotated asset records a non-zero `yaw_offset`** | a 0.5 m chair (seat slab + backrest slab) authored facing **-Z / +Z / +X / -X** records **0 / π / π/2 / -π/2**, `yaw_source == "measured"` |
| **Placement honours it** | the normalized file, re-read with the production reader, has its backrest centroid at **z = +0.225, x = 0.000** for all four — canonical, so it measures **0** afterwards and the planner's yaw applies to a known starting angle; footprint 0.5 × 0.55 × 0.5 m on y = 0 |
| **A non-zero measured yaw produces a real `Rigid3` on ASSET → OBJECT** | `asset_to_object_transform(asset_id)` for the +X chair: `ASSET → OBJECT`, orthonormal, ≠ identity, confidence 0.9; the authored forward (1, 0, 0) maps to **(0, 0, -1)**; `inverse ∘ self = I`; equals `normalization._rotate_y` on 9 points × 3 yaws, so the graph describes exactly the rotation the file carries |
| **The 58 audited catalog assets keep identity** | a record without `yaw_source` validates as `unmeasured`, yaw 0 → identity `Rigid3` (`OBJECT → OBJECT`); no code path rewrites a stored record; the importer's heuristic still runs for those, exactly as before |
| Measured, possibly zero | a symmetric 2 × 0.8 × 0.8 block as `sofa` → **0.0 and `measured`**; a type with no facing rule → 0.0; a thin `tv` → π/2 when thin along X, 0 when thin along Z |
| Declared beats measured | `yaw_offset=0.0` on the +X chair → **0.0, `declared`**, mesh left as authored (backrest still at x = -0.225) |
| Renormalize | a measured π/2 is re-measured to π/2; a declared π survives; an explicit new yaw wins |
| The measurement reaches Blender | manifest entry `forward == {yaw_offset: π, source: "measured"}` and `{0.0, "declared"}`; the importer's gate is pinned by reading the script (bpy cannot be imported in the suite) |

## Mutation tests (scratch script; each source restored byte-identical, sha1-verified)

| Mutation | Result |
|---|---|
| M1 measurement disabled (`rule = None`) | **CAUGHT** — 7 failed |
| M2 importer gate removed (`if True:`) | **CAUGHT** — 1 failed |
| M3 frame graph always identity | **CAUGHT** — 2 failed |
| M4 renormalize re-declares a measured yaw | **CAUGHT** — 1 failed |
| M5 manifest hides the source | **CAUGHT** — 1 failed |

## Regression

Targeted (`assets_pipeline`, `asset_persistence`, `asset_rebind`, `generation_idempotency`, `meshy`, `meshy_rate_limits`, `p18_canonical_identity`, `spatial_architecture_coordinates`, `spatial_architecture_bridge`, `blender_build`, `p22_render_frame`, `scene_plan`, `manifest_identity`, `projects_api`): **180 passed, 2 skipped**. Full suite: **1254 passed · 12 skipped · 30 xfailed · 1 failed (173 s)** — the failure is `test_room_prompt.py::test_the_budget_is_measured_with_clip_not_guessed` (SD prompt template at 79 CLIP tokens > 77 on this machine's tokenizer), in `app/intelligence/prompts.py`, which imports nothing touched here and was last changed in `02ca264`. Pre-existing and unrelated; not patched in passing.

## Not done here — and owed

**The golden project's yaw values.** This checkout is a fresh clone on a different machine from the one the ledger ran on: **no `data/` directory** (no registry, none of the 58 originals, no golden project meshes), **no Blender**, no `.env`. The task's evidence line — *yaw values for the golden project's assets* — therefore could not be produced here. `scripts/audit_forward_axis.py` exists to produce it without touching the registry:

    python scripts/audit_forward_axis.py --json "version 4/evidence/P1-ASSET-005/library_forward_axis.json"

Run on the machine that holds `data/`, it reports, per asset, the stored yaw beside the measured one and how many of the 58 disagree — which is also the first real test of C12's open question (whether identity was in fact right for them). Until that file is in this folder, the "keep identity" criterion is met **structurally** (no record is rewritten) but not **empirically** (the heuristic has not been run over them). Recorded as owed, not as done.

A Blender build with a measured asset is likewise not exercised here (no Blender); the importer change is three lines behind a flag and is pinned by the source-reading test.

## Environment

Python 3.13.7, venv in the session scratchpad from `requirements.txt` (+ `numpy`, `scipy` for the research-bridge suites, which are not in `requirements.txt`). Backend not started; nothing paid.

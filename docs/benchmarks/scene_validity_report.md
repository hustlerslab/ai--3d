# Phases 11–12 — Constraint Solver and Collision / Clearance Validation (Audit)

**Verdict: PASS on what exists; scope stated.** The production placement solver
(`app/planning/compiler.py::place_objects`) and validator
(`app/spatial/validation.py::validate_scene`) were audited across a frozen set of
12 briefs spanning residential, hospitality and workplace verticals: **12 of 12
scenes valid** (zero hard violations of any code), **547 of 559** requested
objects placed (97.9%), **bit-deterministic** across two runs, **0.19 s** median
per scene. Scene success — valid *and* every requested object placed — is
**7 of 12**; the shortfalls are upstream room parsing, not placement. The
validator is two-dimensional (footprint SAT in plan view); there is no 3D OBB
and no clearance rule beyond door swing. No new solver was built, because the
existing one met the bar on measurement and the brief prefers the simpler
deterministic method when it does.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/scene_validity_results.json`
**Script:** `research/spatial_engine/scene_validity_benchmark.py`
**Production code changed:** none.

## 1. What production already has **[M]**

| Brief item | Production implementation |
|---|---|
| Candidate pose generation | `_wall_aligned_candidates`, `_surface_candidates`, `_relation_candidates`, `_wall_hang_candidates` (`compiler.py`) |
| Hard constraints | room bounds (`OUTSIDE_ROOM`), object collision (`COLLIDES_OBJECT`, convex SAT on rotated footprints), wall collision (`COLLIDES_WALL`), door clearance (`BLOCKS_DOOR`, 0.75 m swing rectangle) |
| Soft preferences | `against`/`faces` hints from the reading, relation anchors, facing-into-room ranking |
| Support | `_pick_support` for on-surface objects via `SURFACE_HEIGHT` / `SUPPORT_PREFERENCE` |
| Frame safety | `SpatialRelation.frame`; camera-frame relations never reach the plan |
| Blender conversion | `to_blender_xyz`, `yaw_to_blender_rz`, round-trip tested |

## 2. Benchmark **[M]**

Deterministic `MockProvider` (no VLM) → `compile_scene` → `resolve_plan` →
`place_objects` → `validate_scene`, on an isolated data directory. This measures
the solver and validator, not the language model.

| Brief | Vertical | Rooms | Placed / requested | Hard | Valid |
|---|---|--:|--:|--:|:--:|
| res_1bhk | residential | 3 | 33 / 33 | 0 | ✓ |
| res_2bhk | residential | 4 | 44 / 44 | 0 | ✓ |
| res_3bhk | residential | 7 | 62 / 62 | 0 | ✓ |
| res_studio | residential | 1 | 4 / 11 | 0 | ✓ |
| res_villa | residential | 7 | 59 / 60 | 0 | ✓ |
| res_minimal | residential | 4 | 40 / 41 | 0 | ✓ |
| hosp_hotel | hospitality | 4 | 70 / 70 | 0 | ✓ |
| hosp_restaurant | hospitality | 3 | 78 / 78 | 0 | ✓ |
| off_open | industrial | 4 | 46 / 46 | 0 | ✓ |
| off_small | industrial | 2 | 34 / 34 | 0 | ✓ |
| res_dense | residential | 4 | 36 / 38 | 0 | ✓ |
| res_odd | residential | 4 | 41 / 42 | 0 | ✓ |

Hard violations by code: **none**. Warnings by code: none. Deterministic: 12/12.
Latency: 0.19 s median, 1.1 s max.

**Unplaced objects.** The studio brief parsed to a single `kitchen` room, so the
bed, sofa and wardrobe had no room to be placed in — a room-analysis limitation
of the mock, upstream of the solver. The remaining five omissions are on-surface
items with no surface to rest on ("no surface in Bedroom 1 to rest on; skipped")
— the solver declining rather than floating them, which is correct.

## 3. What the validator does not check **[N]**

- **3D collision.** Footprints only; stacked or overhanging geometry is not
  tested. No AABB/OBB in three dimensions.
- **Clearance** beyond the door swing: walking, pull-out, bedside and working
  clearances are not implemented.
- **Wall penetration** is checked against wall rectangles in plan, not against
  the built mesh (Phase 13 reads meshes back but does not re-check collision).
- **Support** is asserted by the planner's `support_key`, not verified
  geometrically after placement.

## 4. Decision

Against §41: *near-zero hard collisions on solved scenes* ✓ (0 in 547 objects),
*near-zero room-bounds violations* ✓ (0), *support ≥ 95%* — asserted by
construction, not independently verified, so **[N]**. The solver is the
production one and it is deterministic and explainable. **PASS on what exists.**
The gaps are the two the brief lists as required and this audit found absent:
3D collision and configurable clearance rules.

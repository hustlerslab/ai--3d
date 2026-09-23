# P1-IDENTITY-005 — Provenance query and index · verification

**Completed:** 2026-09-22 · **Hat:** Backend Engineer (+ Data) · **Branch:** `ai-3d` on `02ca264` (dirty)

## What exists

| Piece | Where |
|---|---|
| Resolver + index | `aether-backend/app/provenance.py` (`index_project`, `index_is_stale`, `ensure_indexed`, `resolve`, `resolve_all`, `coverage`) |
| Index tables | `app/db/sqlite.py` — `SCHEMA_VERSION = 8`, migration adds `elements`, `element_instances` + 3 indexes. Derived, rebuildable, no FKs |
| Routes | `GET /api/projects/{id}/provenance` (scene-wide coverage) · `GET /api/projects/{id}/provenance/{scene_object_id}` (full chain) — `app/api/projects_routes.py:941-971` |
| Pipeline hook | `scene_plan.py:485` re-indexes after `scene_spec.json` is written; `review_scene_reading` re-resolves identity and re-indexes on every human decision |
| Delete hook | `clear_index()` on project delete |

## Acceptance criterion — every object in a golden scene resolves

`tests/test_provenance.py` builds the golden scene on disk (reading → `resolve_elements()` → plan → committed spec → Blender manifest 1.2 → moodboard → classified intent → real uploaded inputs) and asks the endpoint about **every** object.

```
./.venv/Scripts/python.exe -m pytest tests/test_provenance.py -q
9 passed in 6.84s
```

| Test | Pins |
|---|---|
| `every_object_in_the_golden_scene_resolves_end_to_end` | 7/7 objects `complete`, `gaps == {}`; coverage counts exact |
| `the_sofa_names_the_photograph_that_caused_it` | hop order `blender_object → scene_object → instance → element → scene_element → moodboard → design_intent`; `source_images[0]` = the uploaded `living.png`, `via: design_intent`, `in_inputs_table: true`, and the URL serves 200 |
| `three_identical_stools_share_one_element_and_keep_three_instances` | 1 `cel_` definition, 3 distinct instance ids, `instance_count == 3`; references offered only as `moodboard_reference` (labelled weaker, never claimed exact) |
| `a_pre_v4_scene_object_resolves_through_the_plan_key_and_says_so` | `element_id: null` object resolves via the `plan_key` join and the hop says so |
| `a_catalog_piece_is_complete_at_scene_object_not_a_broken_chain` | `origin: planner_catalog`, complete, 2 hops |
| `unknown_object_is_404_and_anonymous_is_401` | `OBJECT_NOT_FOUND`; deny-by-default holds on both routes |
| `a_missing_definition_is_a_gap_and_the_index_rebuilds_from_the_file` | removing the sofa's reading rows → `gaps == ["instance","scene_element"]`, `complete: false`; stale index detected and rebuilt on read |
| `a_rejected_element_is_not_evidence_and_review_re_resolves_it` | approving a `crowded` crop re-resolves identity (4 → 5 definitions) |
| `deleting_the_project_clears_its_index_rows` | 6 → 0 rows |

## Mutation tests (source restored after each; verified byte-identical)

| Mutation in `app/provenance.py` | Result |
|---|---|
| M1 drop the `plan_key` fallback | **CAUGHT** — 3 failed |
| M2 `complete` ignores `gaps` | **CAUGHT** — 1 failed |
| M3 `index_is_stale` always `False` | **CAUGHT** — 1 failed |

## Endpoint responses (captured from the TestClient, full JSON in this folder)

- `golden_sofa_chain.json` — the full chain for one object, down to the photograph: `terminus: source_image`, 7/7 hops resolved, `source_images: [{filename: living.png, via: design_intent, in_inputs_table: true}]`
- `golden_stool_chain.json` — one of three instances of one definition; `design_intent` unresolved with the reason ("came from the moodboard reading, not from a classified reference photo"), references offered `via: moodboard_reference`
- `golden_pre_v4_stool_chain.json` — `element_id: null` object, note `identity read from plan_key join (scene_spec predates P1-IDENTITY-002)`
- `golden_catalog_lamp_chain.json` — `origin: planner_catalog`, complete at `scene_object`
- `golden_coverage.json` — `objects 7 · complete 7 · gaps {} · reached_source_image_exact 1 · via_moodboard 5`

## Real projects on disk (`real_projects_coverage.json`) — measured, not claimed

| Project | Objects | Complete | Traced to element | Stops at | Gaps |
|---|---:|---:|---:|---|---|
| `proj_553cb09794` | 14 | **14** | **0** | 7 `source_image`, 7 `moodboard` | none — reading predates `resolve_elements()`; the `instance` hop is *unresolved*, not a *gap* |
| `proj_a25a006c88` | 11 | **9** | 9 | 11 `moodboard` | `instance: 2` — the approved-but-unresolved rug and TV unit (`obj_70dfaa853b` et al.) |

The two `proj_a25a006c88` gaps are exactly the defect the `review_scene_reading` fix addresses; the on-disk reading still predates that fix, which fires on the next review PATCH. **Real project data was not modified.**

## Regression

```
./.venv/Scripts/python.exe -m pytest -q
1209 passed · 10 skipped · 30 xfailed · 0 failed   (390.15s)
```
Baseline before this task: 1200 passed. Δ = +9 = this file.

## Notes for the record

- The backend on `:8000` was started 2026-09-21 15:44 UTC on code that predates `app/provenance.py`; it must be restarted before the routes exist there. Route behaviour was verified through the ASGI app (TestClient), which is the same code the server loads.
- `task.md` writes the chain as `instance → element`. In the shipped convention `SceneObject.element_id` is the **reading-row** id (`el_…`, as the compiler writes it from `ObjectPlanItem.element_id`) and the canonical definition (`cel_…`) is reached through the instance row. The resolver and the test follow the compiler; the first version of the test put the `cel_` id on the object and failed — recorded here rather than hidden.

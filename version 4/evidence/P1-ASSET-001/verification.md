# P1-ASSET-001 — Re-bind assets on moodboard re-read · verification

**Completed:** 2026-09-22 · **Hat:** Backend Engineer (+ GenAI) · **Branch:** `ai-3d` on `02ca264` (dirty) · **Meshy spend: 0** (vendor faked at the adapter boundary; no real submission)

## The defect, traced

`coerce_room_reading` mints `element_id = "el_" + sha1(f"{room}|{sem}|{name}|{bbox}#{n}")` — **bbox-dependent**. A forced re-read (`force_read`) rebuilds `planning/scene_reading.json` from the vision model: every box moves, every id changes, every row starts with `asset_id = ""`. `_carry_element_decisions` carried *approvals* by canonical key; nothing carried the *bindings*. Meshes bought since P18 sit under the position-free canonical name and `storage_key` still finds them; meshes bought before that sit under the position-keyed `shape_key` name, which the new boxes can no longer derive — those were re-purchasable.

## The change (3 files, ids deliberately unchanged)

| Where | What |
|---|---|
| `app/intelligence/scene_reading.py` — `carry_asset_bindings(previous, reading, valid)` | Pure. Re-binds by the position-free **canonical key**; a changed piece (other colour/material/size) gets no carry and is generated afresh; a `\|?` no-evidence key never inherits; a second pass on `room\|type\|material\|colour` only when unique on **both** sides (a re-measure across a 10 cm bucket must not re-buy); `valid()` drops assets the registry no longer resolves. **Approvals are not carried** — spend on a crop nobody has seen is what the approval gate exists to stop |
| `app/jobs/handlers/scene_plan.py` — `_read_scene` | Captures the previous reading before a forced re-read; carries before `resolve_elements()` so `canonical_asset_id` sees it; emits `plan.assets` with carried / loose / unbound counts (warning when anything is unbound) |
| `app/jobs/handlers/generate_elements.py` — `_bound_asset` | A group whose row carries a registry-resolvable `asset_id` is **reused before any file lookup**: the binding is the receipt. Attach loop uses `made.get(key) or bound.get(key)` |

## Acceptance — `tests/test_asset_rebind.py` (9 passed; `pytest_verbose.txt`)

| Criterion | Test | Evidence |
|---|---|---|
| Re-reading a project with bound assets issues **zero** new Meshy calls | `a_re_read_keeps_every_binding_and_the_next_run_submits_nothing` | `submit == 0`, `made == {}`, `credits == 0`, `reused == 3`, `attached == 3` |
| Every asset remains bound | same | `{sofa, bar_stool, side_table} → same 3 asset ids`, in memory **and** in the file; all new ids disjoint from the old ones |
| A changed piece gets a new binding | `a_changed_piece_gets_a_new_binding_and_only_it_is_bought` | stool recoloured → `submit == 1`, `reused == 2`, stool bound to a **new** id, the other two unchanged |
| The regression itself | `without_the_carry_the_legacy_mesh_would_have_been_bought_again` | bindings stripped → `submit == 3` — the old behaviour, reproduced |
| Loose match is safe | `the_loose_match_never_hands_one_mesh_to_two_pieces` | ambiguous → nothing carried, 2 reported unbound |

Submission counts are taken from a counting fake of `meshy.submit_image_to_3d`; `wait_for`, `download_glb`, `balance` and `asset_pipeline.ingest_file` are faked too. The meshes in the fixture are written under the **legacy** `shape_key` name — the hard case.

## Mutation tests (source restored, verified byte-identical)

| Mutation | Result |
|---|---|
| M1 `_bound_asset` always empty | **CAUGHT** — 2 failed |
| M2 carry keyed on `shape_key` (position) | **CAUGHT** — 4 failed |
| M3 `_read_scene` never captures the previous reading | **CAUGHT** — 2 failed |

## Regression

- Targeted (suites over the three changed modules): `test_p18_canonical_identity`, `test_scene_reading`, `test_meshy`, `test_p20_element_images`, `test_scene_plan`, `test_p17_element_inventory` → **103 passed**
- Full suite: see the TRACK_RECORD.md entry (run after the change)

## Notes

- Fixture lesson recorded: the golden reference PNGs are 96×72 px, so any box under ~17 % of the image fails `MIN_LEGIBLE_PX`; the integration fixture synthesizes an 800×600 render.
- Not done here: carrying approvals across a re-read (deliberate), and a first-class "client-owned" control (P1-ELEM-004).

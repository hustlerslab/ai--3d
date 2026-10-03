# P1-FRONTEND-004 — Design versions · verification

**2026-09-26 · Hat:** Backend Engineer (+ Frontend) · **Meshy spend: 0** (the generation criterion uses the counting fake vendor from P1-ASSET-002)

## Correction C16: the stated substrate was not safe

task.md says `app/scene/store.py` "already keeps full scene version history … which is the substrate". Read in full, it is an **undo stack**:
- `commit()` after an `undo()` truncates everything after the cursor.
- It keeps only the last `MAX_HISTORY = 200` snapshots.

An accepted design referenced only by a history position can therefore be permanently lost to ordinary editing. `test_the_undo_history_alone_would_have_lost_the_accepted_design` demonstrates this: with the cap at 3, four legitimate edits evict the accepted snapshot from the store entirely, and the version still restores it. Versions are therefore their own table. `task.md` is not edited.

## Built

| Where | What |
|---|---|
| `app/db/sqlite.py` — migration **v13** `design_versions` | A full immutable copy of the committed scene per version, plus `content_sha256`. **SQLite triggers refuse UPDATE and DELETE.** Like `events`, rows outlive a deleted project, because they are the client's work |
| `app/projects/versions.py` (new) | `save` / `list_versions` / `get` / `restore`. **"Current" is computed, not stored:** a version is current exactly when the live scene's content hash equals its own, so no pointer can go stale. `canonical()` is the design as bytes: the scene without its commit counter, commit timestamps and record id. `restore` commits the saved snapshot through the store's own optimistic lock, and makes it the `check_scene` baseline |
| `app/api/projects_routes.py` | `GET/POST /projects/{id}/versions`, `GET /projects/{id}/versions/{vid}`, `POST …/{vid}/restore`. Each has a response model (P1-FRONTEND-003), and saving or restoring emits `design.version_saved` / `design.version_restored` events |
| `aether-frontend/…/api/projects-api.ts` | `listVersions`, `saveVersion`, `restoreVersion`, **typed from the generated contract** (`@/generated/api-types`), the first consumer of P1-FRONTEND-003's types |
| `aether-frontend/…/components/design-versions.tsx` (new) | "Save this design" / "Save and accept"; each version with **Accepted** and **Current** badges; "Make current" on the others; a notice when the design has unsaved changes. Plain words only: no version id, scene id or hash on the page |
| `walkthrough-studio.tsx` | The panel sits on the plan-space step beside the trade-off notice. The 3D view is now keyed by scene **version** as well as id: a restore keeps the id and advances the version, so the viewer would otherwise have kept showing the discarded design |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| **After creating and discarding a new version, the accepted one is recoverable byte-identical** (journey 9) | `test_journey_9_…`: accept → edit → save the experiment → restore the accepted version. The live design's canonical bytes **equal** the accepted snapshot's; the content hash matches; the stored row's own bytes are unchanged (sha256 before = after); `GET` of the version returns the identical snapshot |
| At least two versions coexist; either can be made current | `test_two_versions_coexist_…`: A→B→A, and `is_current` flips exactly each time |
| Re-running after an edit issues **zero** new generations for unchanged pieces | `test_re_running_after_an_edit_…`: pieces generated once (N submissions to the counting vendor); an edit plus a new version, then generate → still N; restore the accepted version, then generate → still N |

Also covered: an edit shows as unsaved changes; restoring the current version commits nothing; versions are immutable (DB refuses UPDATE/DELETE) and survive project deletion; saving with no design → 409 `SCENE_REQUIRED`, unknown version → 404; save and restore are events.

## Found while testing

1. **A vacuous assertion.** My first check that restore rewrites `planning/scene_spec.json` could not fail. Patch edits never touch that file, so it still held the accepted design either way. A mutation that disabled the write **survived**. Replaced with the scenario where the file matters: restoring a version that deliberately removed a piece. Without the write, `check_scene` would compare it against the old plan and escalate the removal as missing furniture.
2. **A real bug, found by that stronger test.** Restoring the version that is *already* live took an early "nothing to commit" return, which also skipped setting it as the baseline. Choosing a version should always make it the baseline, so the baseline step now runs on both paths.
3. **My own test helper walked back onto the accepted design.** "Take the first legal move" moved one piece +x then −x and recreated the saved design exactly, which briefly made the eviction test look like a failure. Each edit now moves a distinct piece.

## Mutations (7/7 caught, each restored sha1-identical)

| # | Mutation | Caught by |
|---|---|---|
| 1 | restore commits the live scene, not the saved snapshot | journey 9, coexist, eviction, baseline |
| 2 | the commit counter leaks into the design hash | journey 9, coexist, eviction, baseline |
| 3 | restore stops setting the baseline | baseline test (**survived its first version**, see Found 1) |
| 4 | restoring the already-current version skips the baseline | baseline test (the bug in Found 2) |
| 5 | versions become editable (no-UPDATE trigger dropped) | 9 of 10 tests |
| 6 | UI: "Make current" offered on the current version too | `offers Make current only on …` |
| 7 | UI: the version id leaks onto the page | `never puts an internal identifier on the page` |

## The contract guards from P1-FRONTEND-003, working on a real change

Adding these 4 routes failed exactly the tests it should have, naming the routes: the endpoint walk ("never called: …versions…"), the snapshot, the generated-types check, and on the frontend the coverage test ("add these to CALLS: listVersions, saveVersion, restoreVersion"). All were resolved by registering the routes, not by weakening a check.

## Full suites

Backend `class=MOCK passed=1523 failed=1` (+10; the same pre-existing CLIP test) · `class=PRODUCTION-PATH passed=21` · generated types current · frontend `tsc` + `next lint` clean, **vitest 109 passed**.

## Owed

- **A browser screenshot / click-through** of save → experiment → make current. The studio needs a signed-in session, and this agent does not create accounts or enter passwords. The panel is covered by render tests and the flow by API tests.
- It lives on the plan-space step. P1-FRONTEND-002's review surface, once it exists, is the natural second home.

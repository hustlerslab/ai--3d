# P1-FRONTEND-001 — Element inventory, assumptions and uncertainty · verification

**2026-09-26 · Hat:** Frontend Engineer (+ Backend) · **Meshy spend: 0**

## Principle

The screen displays certainty; it never works it out. State, counts and estimates are decided once, in the backend, and the screen renders them. The earlier client-side recount (`groups.filter(...).length`) was a second copy of the rule that could disagree with the first, and it has been removed.

## Built

| Where | What |
|---|---|
| `app/intelligence/element_states.py` (new) | `element_states`: every reading row gets exactly one of **detected** (checked, awaiting the person) / **validated** (checked and confirmed) / **rejected** (a check removed it, or the person said no) / **unresolved** (kept as its own piece for lack of evidence). `inventory_counts`: the printed numbers, counted from the same definitions and instances the backend sends. `assumptions`: every estimate, in plain words, with where to change it. The estimates are room sizes marked `estimated`, positions `derived` from the picture or never read at all, and several same-kind pieces in one room kept apart for lack of evidence |
| `app/api/projects_routes.py` `_review_summary` | Adds `element_states`, `counts` and `assumptions` to both scene-reading routes |
| `app/api/contracts.py` | `ReadingSummary`, `InventoryCounts`, `Assumption`: typed in the contract, so the frontend gets them generated |
| `aether-frontend/…/element-inventory.ts` | Rewritten to **join and display only**: counts are `summary.counts` verbatim (or none if the backend is too old, never a recount); every state is `summary.element_states`; a row shows as rejected only if the backend says so |
| `…/components/element-review.tsx` | A state badge in plain words (Confirmed / Awaiting you / Identity unresolved / Not used); an "est. position" marker on the piece concerned; a **"What we assumed"** panel listing every estimate with where to change it; a **Yours** label on kept furniture ("kept, not built"); a rejection reason in words ("you left it out", or the existing plain-language check labels) instead of a raw check code; **the instance id removed from the image tooltip** |
| `…/types.ts` | Summary fields typed from `@/generated/api-types`; `client_owned` added to the hand-written `ElementDefinition` (the backend already sent it) |

## Where each estimate is changed (the "editable" criterion)

| Estimate | Changed in | Existing control |
|---|---|---|
| Room size | Review & Refine, the room-size table | `analysis-review.tsx` has editable width and length; entering a value clears its "estimated" tag |
| A piece's position | The 3D view | `/api/scenes/{id}/patches` via the viewer's move tool |
| Pieces kept apart | This screen | per-piece review |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Each element shows one of four states | backend `test_each_row_gets_one_of_the_four_states`, `test_a_piece_with_nothing_to_match_on_is_unresolved`; rendered `shows each of the four states in plain words` |
| Every inferred or estimated value carries a visible marker and is editable | `test_every_estimate_is_listed_in_plain_words` (a derived position and an estimated room are listed; a read position, a given room and a rejected piece are not); rendered: marker on exactly the one piece concerned, and the panel lists each estimate with where to change it |
| Kept furniture labelled "yours" | `labels kept furniture as yours` (logic and rendered) |
| **Displayed counts equal backend counts; a test asserts no client-side recomputation** | `prints the backend's counts even where recounting the lists would disagree`: counts deliberately inconsistent with the lists are displayed verbatim. `shows no counts rather than recounting when the backend sent none` |
| An assumptions panel lists every inference | `lists every assumption with where to change it`; backend `test_the_review_endpoint_carries_states_counts_and_assumptions` (the real endpoint: states cover every row, counts match the lists sent, and the mock analysis's estimated rooms appear) |

The P1-FRONTEND-003 guards again flagged the typed-summary change (snapshot + generated types, exactly 4 schemas). The endpoint walk **passed** unchanged, so real scene-reading responses already validated against the new types before they were regenerated.

## Mutations (7/7 caught, each restored sha1-identical)

| Mutation | Caught by |
|---|---|
| counts recounted client-side | 3 tests, including "prints the backend's counts even where recounting would disagree" |
| rejection inferred client-side (unclaimed = rejected) | "does not call a row rejected unless the backend did", legacy test |
| the instance id put back in a tooltip | "puts no internal identifier on the page" |
| assumptions panel dropped | "lists every assumption …" |
| backend: a piece awaiting the person counted as validated | `test_each_row_gets_one_of_the_four_states` |
| backend: rejected rows listed as assumptions | `test_every_estimate_is_listed_in_plain_words` |
| backend: a read position reported as an estimate | `test_every_estimate_is_listed_in_plain_words` |

## Full suites

Backend `class=MOCK passed=1529 failed=1` (+6; the same pre-existing CLIP test; 214 s. One run showed 9h41m wall time, which was the machine sleeping mid-run; the re-run's slowest test was 11 s) · `class=PRODUCTION-PATH passed=21` · generated types current · frontend `tsc` + `next lint` clean, **vitest 123 passed** (+14).

## Owed

- **Screenshots / browser test.** The studio needs a signed-in session, and this agent does not create accounts or enter passwords. Covered by rendered-HTML tests and the real endpoint.
- `element-images-review.tsx` (the element-*pictures* screen, a different view) still derives its own `canonical_count`. It is outside this task's scope and noted for follow-up.

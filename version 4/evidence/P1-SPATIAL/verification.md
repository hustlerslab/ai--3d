# Phase 11 — Spatial Engine integration (P1-SPATIAL-001 · 002) · verification

**Completed:** 2026-09-25 · **Hats:** Spatial Engineer · Product Engineer (+ Frontend) · **Meshy spend: 0** · `tests/test_spatial_integration.py` **11 passed**

## P1-SPATIAL-001 — identity through placement, with events

| Where | What |
|---|---|
| `app/scene/schema.py` | `SceneObject.identity_source` — `element` (an occurrence of an approved element, carries `element_id`) or `planner` (a catalog piece nobody pictured, `element_id` deliberately empty per P1-IDENTITY-003). Filled on validation, so every object — including every legacy row — says which; `element` without an `element_id` is refused |
| `app/planning/compiler.py` | unplaceable warnings now name the **piece**, the room and the priority: `…: no valid position for walnut bed in Living Room (priority 3)`; `…: no surface in Bedroom to rest brass lamp on; skipped`. The classifier's patterns accept both the new and the old wording |
| `app/jobs/handlers/scene_plan.py` | `spatial.solve.completed` carries **entity ids** (moved + unplaced) and **outcome counts** (`placed`, `unplaced`, `unplaced_keys`, hard before/after, moved, operations); each unplaceable warning is also a `validation.failed` event with its category |

| Criterion | Evidence |
|---|---|
| Every committed object has explicit identity **and** valid geometry | golden scene: 44 objects, **0 hard violations**, each `identity_source` stated and consistent with `element_id` (`golden_identity_validity_report.json`); a moodboard-driven scene: every reading-derived object carries `element_id` + `instance_id` |
| Repair preserves identity, dimensions and asset binding | a collision injected into the committed golden scene and repaired end to end: every object's element/instance/asset id, dimensions, **scale**, semantic type and identity source unchanged; 0 hard violations after |
| An unplaceable item is reported by name, room and priority — never silently dropped | 12 beds in one room: warnings "…for walnut bed in … (priority 3)", a `validation.failed` event naming it (`candidate_vocabulary_failure`), and the solve event counting it as unplaced with its key |
| Solve events carry entity ids and outcome counts | asserted on the real event |
| Measured constants unchanged | `PRIMARY_WALKWAY_MIN_M 0.90`, `DOOR_CLEARANCE_DEPTH 0.75`, `BOUNDARY_TOLERANCE 0.09`, `MAX_ITERATIONS 20` pinned |

**Correction C13 (recorded, not silently applied):** the criterion says "every committed `SceneObject` has `element_id`". P1-IDENTITY-003 decided — rightly — that a catalog piece the planner added is *not* an occurrence of anything the client approved and must not be given an invented `element_id`; the mock golden scene is 44 such pieces. The two cannot both hold. Implemented instead: every object states **why** it has the identity it has (`identity_source`), `element` rows always carry the id, and no object is ambiguous. `task.md` not edited.

## P1-SPATIAL-002 — trade-offs in plain language

`app/planning/tradeoffs.py` translates the compiler's own warnings deterministically (no model): pieces in the same room are named together, the constraint is stated in words ("keeping a clear walkway and space in front of the doors"), and **three** options are offered (leave it out · a smaller one · keep it and drop a less important piece; for a missing surface: add a side table · stand it on the floor · leave it out). A `FORBIDDEN` pattern (plan keys, ids, `priority`, snake_case, `C-104`-style codes) must never match. `GET /api/projects/{id}/tradeoffs`. Frontend: `TradeoffNotice` under the spatial check on the plan-space step — statements plus a **"What you can do"** list (not buttons: nothing acts on the choices yet, and a dead button would repeat the P0-FRONTEND-002 dishonesty).

| Criterion | Evidence |
|---|---|
| A conflict produces a plain statement naming the pieces and the constraint | real over-constrained room: *"The walnut bed doesn't fit in the living room alongside everything else while keeping a clear walkway and space in front of the doors."* (`tradeoffs_over_constrained_room.json`); two pieces → "The grey sofa and the velvet armchair don't fit…" |
| At least two options | 3 per trade-off |
| No internal code or identifier | the forbidden pattern finds nothing in any statement or option, including for a pre-rename warning with no name (falls back to the type word) |
| Rendered as a person reads it | `aether-frontend/src/features/studio/review-screens.test.ts`: `TradeoffList` rendered to HTML contains the statement, "What you can do" and every option, and no key |

## Mutation tests (source restored byte-identical)

| Mutation | Result |
|---|---|
| identity left implicit | **CAUGHT** (3) |
| unplaced item not named | **CAUGHT** |
| solve event omits unplaced | **CAUGHT** |
| plan key leaks into the statement | **CAUGHT** (3) |
| a single option | **CAUGHT** (3) |
| walkway constant changed | **CAUGHT** |
| repair rescales pieces | survived at first → the preservation test now checks **scale** → **CAUGHT** |

## Owed

**The browser screenshot** of the trade-off message (the task's evidence line) and the click-through of the P1-ELEM-004 keep toggle: the studio requires a signed-in session, and account creation / password entry in a browser is not something this agent does. Both screens are covered by rendered-HTML tests and API tests; the screenshot needs the owner to sign in in the browser pane.

# P1-HUMAN-001 — Review queue and decision records · verification

**Completed:** 2026-09-25 · **Hat:** Backend Engineer (+ Product) · schema **v12**

## The change

| Where | What |
|---|---|
| `app/projects/schema.py` | `ProjectStage` **gains** `REPAIRING`, `HUMAN_REVIEW`, `VERIFIED`, `CANCELLED`; the 13 existing strings are unchanged and stay first; none of the new ones is in `STAGE_ORDER` (states, not steps) |
| `review_items`, `review_decisions` (v12) | an item: issue · affected entities **by human name** · evidence refs · expected vs observed · attempts per round (from `repair_rounds`) · recommendation · explicit actions (with labels a person reads). Decisions are **append-only by trigger** — a changed mind is a new decision; a resolved item is not re-decided in place |
| `app/supervisor/review.py` | `ReviewQueue` (API) and `ReviewHandle` (Orchestrator: open only — it cannot read, decide or resolve). **Routing:** rendering, hardware, validation, geometry, solver, repair, code-defect and unknown → **operations**; perception, asset → **designer**; appearance/intent → **homeowner**. Visibility: homeowner ⊂ designer ⊂ admin; operations items reach admins only. **An override (an action other than the recommendation) requires a reason** (≥ a sentence), validated **before** anything is done |
| `app/api/projects_routes.py` | `GET /api/projects/{id}/reviews`, `POST /api/projects/{id}/reviews/{item}/decision`, `GET /api/projects/{id}/repairs` — under the same project authorization as every project route |

Actions: `accept_as_is` → `VERIFIED` · `retry_repair` → an **ordinary** `repair_scene` job (a person's action; fresh budget) · `replan` → `scene_plan force` · `cancel` → `CANCELLED`. No action deletes anything.

## Acceptance — `tests/test_orchestrator.py`

| Criterion | Evidence |
|---|---|
| New states added; existing strings unchanged; old rows load | the first 13 values asserted verbatim; migration additive |
| Item carries all fields, entities **by human name** | a real case about the two collided objects: every affected entry has a readable name (not the id, not "unnamed"); attempts show the RE_SOLVE round; recommendation, actions and action labels present |
| **A decision records who, why and what resulted; an override requires a reason** | override with no reason → **422**, item still open, nothing done; with a reason → recorded with `user_id`, `user_email`, `is_override`, the reason, and `result: {stage: VERIFIED}` (`review_item_and_decision.json`) |
| **A rendering defect goes to operations, not the homeowner** | 7 routing cases; an operations item is invisible to the homeowner role and visible to the admin through the API |
| **A user resolves a case without losing project state** | `retry_repair` through the API → an ordinary `repair_scene` job (`repair_round 0`) → the project keeps every scene id it had; the scene spec still serves |
| Decisions cannot be rewritten | `UPDATE review_decisions` refused by the database; a second decision on a resolved item → 409 |

## Mutation tests

| Mutation | Result |
|---|---|
| override needs no reason | **CAUGHT** |
| operations items shown to homeowners | **CAUGHT** |

## Limits

- The frontend review surface is P1-FRONTEND-002 (not done); this is the backend queue and API it will render.
- "Operations" is today the admin role; there is no separate ops role in `auth.ROLES`.

# P0-SEC-003 — Evidence: spend protection on paid generation

**Completed 2026-09-21.** Nobody can drain Allure's Meshy credits, and a restart cannot silently reset a spend limit.

---

## Acceptance criteria

| Criterion | Result | Proof |
|---|---|---|
| Unauthenticated generation → **401, zero spend** | ✅ | `test_an_unauthenticated_generation_request_spends_nothing` — covers the named route **and** the wildcard `POST /jobs`, then asserts the ledger is empty |
| Cap reached → halts, **project preserved**, review raised | ✅ | `test_a_reached_project_cap_halts_generation`; the handler emits `elements.capped` as a **warning** and leaves the plan and every existing asset untouched |
| **Restart does not reset accumulated spend** | ✅ | `test_accumulated_spend_survives_a_process_restart` — the restart is *performed*, not simulated |

## The design decision that matters

`meshy_max_per_project: 20` already existed. It is **not** a spend limit: it caps how many pieces **one job** attempts, is held nowhere, and resets with every new job. Ten jobs of twenty pieces cost twenty times what it implies.

So spend is now a **table**: `spend_records`, one row per confirmed charge, written the moment the provider confirms — not at the end of a batch, because a crash in between would lose money that was genuinely spent.

| New setting | Default | Meaning |
|---|---:|---|
| `meshy_max_credits_per_project` | 600 | 20 pieces at 30 — the ceiling the per-job limit *implied*, now enforced for the life of the project |
| `meshy_max_credits_per_user` | 3000 | 100 pieces: generous for one person, ruinous for none |

`0` means uncapped. That is a choice a deployment makes explicitly; it is never the default, and a test asserts the shipped defaults are both above zero.

## Measured is never mixed with estimated

`credits` is what Meshy reported consuming (`model.credits`). When a figure genuinely cannot be measured the row is marked `is_estimate=1`, and totals report the two separately — `Spend.is_exact` is False whenever any estimate is included. **An estimated total that reads as measured is how a budget quietly becomes fiction.** Estimates still count against the cap, so an unmeasurable charge cannot be used to exceed it.

## Partial allowance, not all-or-nothing

With 3 of 10 pieces affordable, the handler generates 3 and flags 7. The project moves forward and a human is told exactly what is waiting and why:

> *spend cap reached: 7 piece(s) held back. this project has spent 540 of 600 credits; 60 left, enough for 2 more piece(s) at 30 each. Nothing else about the project has changed — raise the cap or reduce the selection, then run this again.*

## Who asked — and why it is a column

The per-user cap needs to attribute each charge. `jobs.created_by` is a **column**, not a key in `params`, because `POST /projects/{id}/jobs` lets the caller supply `params` wholesale — a user id in there would be forgeable, which is the opposite of an audit trail. `test_the_caller_cannot_forge_who_asked` sends `params.created_by = "usr_somebody_else"` and asserts the stored value is the authenticated user.

### A wrong turn, and what caught it

The actor was first recorded in a `ContextVar` set inside the `authorize` **dependency**. That looks equivalent to middleware and is not: FastAPI runs a sync dependency and a sync endpoint in **two separate threadpool calls, each with its own copied context**, so the value never arrived. Jobs were created with `created_by=""` and the per-user cap had nothing to attribute a charge to.

It failed silently in every way except one — `test_a_job_records_who_asked_for_it` failed immediately. Moved to middleware, which runs in the parent context that both copies inherit. The middleware now also resolves the session once per request instead of twice, with `authorize` reusing `request.state.principal`.

## Test results

| Suite | Result |
|---|---|
| `tests/test_spend_protection.py` | **16 passed** |
| Auth suites combined | **63 passed** |
| **Full backend** | **1048 passed · 10 skipped · 30 xfailed · 0 failed** (152.11 s) |

## Teeth verified by mutation

| Mutation | Tests failed |
|---|---:|
| **A** — cache totals in memory (the in-memory counter the task forbids) | **9**, *including* `test_accumulated_spend_survives_a_process_restart` |
| **B** — the cap never holds anything back | **6** |

Mutation A is the important one: it is the plausible wrong implementation, and only the restart test distinguishes it from the correct one.

## One pre-existing test caught my prose, correctly

`test_the_only_compliance_words_in_the_backend_are_the_refusal_list` failed because a CORS comment I wrote used the phrase *"load-bearing"*, which matches the `load[ _-]?bearing` guard against building-code logic entering the product. **The test was right and the comment was wrong** — reworded to "essential". The scan was not weakened.

## What this does NOT yet do

- **Idempotency key** (P1-ASSET-002) — the fourth gate in the deliverable's "four independent spend gates". Human approval, authentication and the cap are in place; a retried request can still spend twice.
- **No real Meshy call was made.** Every figure here is from the ledger and the deterministic tests. **Meshy spend for this task: 0 credits.**

# P1-REPAIR-001 — Outer repair loop, bounded at 2 rounds · verification

**Completed:** 2026-09-25 · **Hat:** Backend Engineer (+ Spatial) · schema **v12** · **Meshy spend: 0**

## The change

- `jobs.repair_round` (migration v12); `Job.repair_round`, default 0 = an ordinary job.
- **`JobRunner.request_repair()`** — the only way an automatic repair is dispatched. The **runner** numbers the round (`repair_rounds_used() + 1`, counted since the project's last ordinary job) and **discards** any `repair_round` / `max_rounds` the caller put in `params`. Past `REPAIR_MAX_ROUNDS` (2) it refuses, records `repair.limit_reached`, and returns nothing; the Orchestrator must then escalate. The queued event reads **"repair round N of 2"**; the project stage becomes `REPAIRING`.
- A person's action (any ordinary job) starts a fresh budget; no amount of automatic activity can.
- The inner engine is untouched: `MAX_ITERATIONS = 20`.

## Acceptance

| Criterion | Evidence |
|---|---|
| **A misbehaving Orchestrator that requests repair indefinitely still halts at round 2** (§30 row 15) | `abuse_counter.json`: **25 requests, forged `repair_round: 0, max_rounds: 99` each time → 2 dispatched (rounds 1, 2), 23 refusals** "automatic repair refused: 2 of 2 round(s) already used" |
| **The counter is owned by the runner** | forged params ignored; the rounds are the runner's numbers |
| Inner `MAX_ITERATIONS = 20` unchanged and independent | asserted |
| Rounds visible as "attempt N of 2" | queued messages `repair round 1 of 2`, `repair round 2 of 2` |
| Every round persisted | `repair_rounds` via P1-ORCHESTRATOR-002 |
| Injected collision repaired within 2 rounds | repaired in **round 1** (P1-ORCHESTRATOR evidence) |
| An unrepairable scene ends in a person, not a loop | pieces stretched past the room: every path ends in **one open review item**, stage `HUMAN_REVIEW`, rounds ≤ 2, last round `escalated` |
| Rollback: cap 0 = no automatic repair, escalation still works | `REPAIR_MAX_ROUNDS=0` → 0 automatic jobs, 1 review item, round recorded `ESCALATE … limit reached` |
| **No infinite progress state** | every end-to-end case returns within the runner's idle wait; the two mutations that removed the bound **ran until the test's wait expired** (2 min each) — the bound is what stops the loop |

## Mutation tests

| Mutation | Result |
|---|---|
| runner cap ignored | **CAUGHT** (4; the loop ran to the wait limit) |
| the caller's round trusted | **CAUGHT** (3) |

## Limits

Task dependency P1-VALIDATOR-001 (render verification) is not in production (needs Blender): the loop is proven on the spatial failures the deterministic layers find. Render-level failures will enter through the same `request_repair`.

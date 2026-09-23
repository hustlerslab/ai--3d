# Allure V4 — Meshy Credit Ledger

**HARD CONSTRAINT: 500 credits total for all V4 testing. Project-wide, not per task. Never exceed.**

*Every Meshy generation must be recorded here before it is initiated.*

---

## 1. Budget status

| | Value | Source |
|---|---:|---|
| **V4 testing budget** | **500** | Directive §12, hard cap |
| **Spent so far** | **0** | No generation initiated this program |
| **Remaining** | **500** | 500 − 0 |
| Cost per piece | **30** | `CREDITS_PER_PIECE`, `generate_elements.py`; confirmed live by `GET /api/credits` |
| **Generations affordable** | **16** | ⌊500 / 30⌋ |
| Account balance (context only) | **2,295** | Live `GET /api/credits` 2026-09-21 — *not* the budget |
| Per-project cap | 20 | `meshy_max_per_project` |

> The account holds 2,295 credits. **That is irrelevant to this program.** The ceiling is 500.

---

## 2. Assets already paid for — reuse these first

**41 Meshy-generated assets already exist in the registry** and cost nothing to reuse.

| Provider | Registry entries |
|---|---:|
| **meshy** | **41** ← already paid, reusable |
| polyhaven | 28 |
| **Total** | **69** |

Normalized `.glb` files on disk: **143**.

**Before any generation, check this inventory.** A reused asset costs 0 credits and still exercises the ingest, normalization, binding and placement paths.

---

## 3. Spend plan — 16 generations, allocated

The §54 golden project (`GOLDEN-LIVING-ROOM-01`) needs **≤9 generations** by design — 10 element definitions, one of which (the TV unit) is client-owned and generates nothing.

| Purpose | Generations | Credits | Justification |
|---|---:|---:|---|
| Golden project, full run | 9 | 270 | The V4 acceptance scenario. Proves canonical reuse: 3 stools → 1 asset, 2 chairs → 1 asset |
| Multi-view A/B (P2-ASSET-007) | 4 | 120 | 2 elements × {single-view, 4-view}. **Adoption requires a measured win** |
| Idempotency / retry proof (P1-ASSET-002) | 1 | 30 | One generation, killed and restarted — must produce **zero** additional spend |
| Reserve | 2 | 60 | Unforeseen provider-integration verification |
| **Total** | **16** | **480** | 20 credits headroom |

**Not funded from this budget** — these use reuse or mocks:

- Re-read rebinding (P1-ASSET-001) — must issue **zero** new calls; that is the acceptance criterion
- Shape-gate regression — replay a stored bad mesh
- Asset validation, normalization, yaw measurement — existing assets
- All deterministic unit/integration tests — `MockProvider`
- Failure injection (timeout, 429, expired URL) — simulated, no real submission

---

## 4. Pre-generation checklist — mandatory

Before **every** Meshy call:

1. Does a canonical asset already exist for this `element_id`? → **reuse, cost 0**
2. Does an equivalent exist among the 41 paid assets? → **reuse**
3. Can this test use an existing asset? → **reuse**
4. Is this test provider-specific, or would a mock prove the same thing? → **mock if it would**
5. Can one generated asset satisfy several acceptance criteria at once? → **batch the validations**
6. Is this generation genuinely required to prove an acceptance criterion? → if not, **do not run it**
7. `expected_credits ≤ remaining`? → if not, **do not run it**; redesign, reuse, or defer with a documented reason

---

## 5. Ledger

*Append one row per generation. Record `actual_credits` from the task response — never estimate when the real figure is available.*

| # | Timestamp (UTC) | Task ID | Test case | Element ID | Operation | Expected | Actual | Cumulative | Remaining | Reason | Result | Reused? |
|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|
| — | — | — | — | — | — | — | — | **0** | **500** | *No generation initiated yet* | — | — |
| — | 2026-09-22/23 | — | P1-ASSET-001…004, P1-IDENTITY-005/006, run check | — | *none — vendor faked at the adapter boundary in every test; live balance read only* | 0 | 0 | **0** | **500** | Acceptance provable without a real submission | all passed | n/a |

---

## 6. Rules

| Rule | Detail |
|---|---|
| **Never exceed 500** | If a planned test would breach it, do not run it |
| **Record before, not after** | The row is written before the call is made |
| **Actual over estimate** | Read the consumed figure from the response; mark estimates explicitly as estimates |
| **Never fabricate usage** | An unverified figure is recorded as `UNKNOWN`, not guessed |
| **Attributable** | Every call names a task ID and a test case |
| **Reuse is the default** | Generation is the exception and must be justified in the row |
| **A failed generation still costs** | If credits were consumed on a failure, record them |

---

## 7. Verification commands

```bash
# live account balance and per-piece cost
curl -s http://127.0.0.1:8000/api/credits

# count assets already paid for (reuse candidates)
python -c "import json;r=json.load(open('aether-backend/data/assets/registry.json'));\
items=r if isinstance(r,list) else r.get('assets',list(r.values()));\
print(sum(1 for a in items if isinstance(a,dict) and (a.get('source') or {}).get('provider')=='meshy'))"
```

*Recorded 2026-09-21. Balance and constants verified live against the running backend. Re-checked 2026-09-23 from the Studio UI: **2,295**, unchanged — nothing spent.*

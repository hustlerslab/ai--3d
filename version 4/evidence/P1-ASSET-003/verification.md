# P1-ASSET-003 — Distinguish the two Meshy 429s · verification

**Completed:** 2026-09-22 · **Hat:** Backend Engineer · **Branch:** `ai-3d` on `02ca264` (dirty) · **Meshy spend: 0** (mocked transport throughout)

## Research (authoritative source)

`https://docs.meshy.ai/en/api/rate-limits`, fetched 2026-09-22:

| Plan | Requests/s | Queue tasks |
|---|---:|---:|
| Pro | 20 | 10 |
| Premium | 20 | 30 |
| Studio | 20 | 20 |
| Ultra | 20 | 100 |
| Enterprise | 100 | custom |

Both limits answer **`429 Too Many Requests`**; only the body's `message` differs — `"RateLimitExceeded"` (request rate) vs `"NoMoreConcurrentTasks"` (queue depth). Limits are **per account, across all API keys**; queue tasks include Text-to-3D, Image-to-3D, Text-to-Texture and Remesh. **No `Retry-After` header and no reset timing are documented**, so the waits below are Allure's own, and are module attributes so an operator can tune them.

## Before

`_raise_for` raised a generic `MeshyError` for every status ≥ 400. A full queue and a rate blip looked identical; there was no retry at the request level and no bound on how many tasks one job put in flight (`asyncio.gather` over the whole batch, up to `meshy_max_per_project = 20` — twice the Pro queue).

## The change

| Where | What |
|---|---|
| `app/providers/meshy.py` | `MeshyRateLimited` and `MeshyNoConcurrentSlots` (both `MeshyError`); `_raise_for` classifies 429 by message (case/space-insensitive; an unnamed 429 is treated as a rate limit — slowing down is the safe reading, waiting for a slot is not); `_send()` routes **every** request (`balance`, both submits, `submit_refine`, `get_task`) through one helper: rate limit → exponential backoff from 0.5 s with 25 % jitter, 6 attempts (~30 s); full queue → **steady 10 s slot wait**, up to 90 attempts (15 min). `_sleep` is injectable |
| `app/core/config.py` | `meshy_max_concurrent_tasks = 8` — under the Pro queue (10) with room for a task started by hand on the dashboard; raise to match the plan, never above it |
| `app/jobs/handlers/generate_elements.py::_run` | `asyncio.Semaphore(meshy_max_concurrent_tasks)` held from submission until the task is done, so the count the vendor sees is the count this bounds |

## Acceptance — `tests/test_meshy_rate_limits.py` (10 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| `NoMoreConcurrentTasks` → wait for a slot, not a rate backoff | three queue-429s then 202: sleeps `[10.0, 10.0, 10.0]`, 4 requests, success |
| `RateLimitExceeded` → back off on request rate | three rate-429s then 202: 3 sleeps, each ≥ 0.5 s, strictly increasing, all < the slot wait |
| Exhaustion raises the typed error | rate: `MeshyRateLimited` after attempts+1 requests; queue: `MeshyNoConcurrentSlots` after `SLOT_WAIT_ATTEMPTS` |
| Polling is protected too | `wait_for` survives a 429 on `get_task` |
| In-flight count never exceeds the cap | 6 pieces, cap 2 → observed maximum in flight **2**, all 6 made |
| Default cap below the Pro queue | `0 < 8 < 10` |

## Mutation tests (source restored, verified byte-identical)

| Mutation | Result |
|---|---|
| M1 queue-429 collapsed into the rate limit | **CAUGHT** — 3 failed |
| M2 no retry on a rate limit | **CAUGHT** — 4 failed |
| M3 in-flight cap removed | **CAUGHT** — 1 failed |

## Regression

`test_meshy` + `test_generation_idempotency` after routing through `_send`: 21 passed; combined asset suites: 63 passed. Full suite: see the TRACK_RECORD.md entry.

## Not done here

A load test against the live account (task text: "load test on the cap") — it would submit real tasks and spend real credits against the 500-credit ceiling for no acceptance value the semaphore test does not already give; the cap is enforced in-process and proven there.

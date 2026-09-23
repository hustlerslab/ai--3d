# P1-ASSET-002 — Meshy idempotency key · verification

**Completed:** 2026-09-22 · **Hat:** Backend Engineer · **Branch:** `ai-3d` on `02ca264` (dirty) · **Meshy spend: 0** (vendor faked at the adapter boundary; every submission counted)

## The gap

`generate_elements` had four download attempts and a per-project cap, but no idempotency key. A job killed after Meshy accepted the task — process restart, worker crash, `max_attempts=2` re-running the handler — re-submitted the same crop and paid twice. Nothing on disk said "this piece is already in flight."

## The change

| Where | What |
|---|---|
| `app/db/sqlite.py` | `SCHEMA_VERSION 8 → 9`; `_v9_generation_tasks` creates `generation_tasks` (request_id PK, project_id, job_id, item_key, element_id, image_sha256, params, provider, endpoint, task_id, status, asset_id, credits, error, created_at, updated_at) + index |
| `app/spend/tasks.py` (new) | `request_key(item_key, image, params) → (sha1(canonical key \| sha256(crop bytes) \| sorted params), sha256)`; `resumable_task`, `record_submission` (INSERT OR REPLACE), `mark_task`, `project_tasks`. Exported from `app.spend` — it is the **fourth spend gate** |
| `app/providers/meshy.py` | `MeshyTaskFailed(MeshyError)` raised only when the **vendor** ends a task (FAILED / CANCELED / EXPIRED). A timeout or a dropped connection stays a plain `MeshyError` |
| `app/jobs/handlers/generate_elements.py::_generate_one` | Look up the receipt → **poll** the existing task (`elements.resume`) or submit and **record before awaiting**; `MeshyTaskFailed` → `FAILED` (re-submittable); ingest rejection → `INGEST_FAILED` with the vendor's credits and the reason (not resumable — the vendor is non-deterministic, a fresh generation is a deliberate second purchase); success → `SUCCEEDED` with `asset_id` + credits |

**Key choice:** the task text suggests `element_id`; that id is minted from the crop box and a re-read moves every box (P1-ASSET-001), which would defeat the key exactly when it matters. The canonical group key plus the crop's SHA-256 pins the same inputs across re-reads; `element_id` is stored on the row for provenance.

## Acceptance — `tests/test_generation_idempotency.py` (4 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| **Killing and restarting a generation job produces zero additional submissions** | run 1: 3 pieces → `submit == 3`, `wait_for` dies ("All connection attempts failed") → 3 rows `SUBMITTED` with task ids; **real restart** (`_reset_singletons()`: every store, the runner and the DB handle dropped and reopened from disk) → ledger intact; run 2: `submit == 3` (**+0**), the retry polled exactly the 3 task ids run 1 submitted, 3 assets bound, `credits == 90`, `project_spend == 90` — three pieces, not six |
| An in-flight task is polled, not re-created | `set(polled[3:]) == submitted` |
| The key is deterministic for identical inputs | same inputs in any dict order → same id; different crop bytes / parameters / piece → different ids |
| Only the vendor ending a task clears the receipt | `MeshyTaskFailed` → `FAILED`, next run re-submits (3 → 6, once each); a timeout leaves rows `SUBMITTED`; the run after polls (still 6) |
| A rejected mesh is recorded, paid, not resumed | `INGEST_FAILED`, `credits == 30`, reason stored, `asset_id == ""` |

## Mutation tests (source restored, verified byte-identical)

| Mutation | Result |
|---|---|
| M1 `resumable_task` always `None` | **CAUGHT** — 2 failed |
| M2 receipt not written before the wait | **CAUGHT** — 3 failed |
| M3 any `MeshyError` clears the receipt | **CAUGHT** — 2 failed |

## Regression

- Targeted: `test_spend_protection`, `test_meshy`, `test_asset_rebind`, `test_generation_idempotency`, `test_delete_project`, `test_backup_restore`, `test_p18_canonical_identity` → **81 passed**
- Full suite after the change: see the TRACK_RECORD.md entry

## Not done here

- Distinguishing the two Meshy 429s and capping in-flight tasks — P1-ASSET-003.
- Persisting within the vendor retention window as a stated invariant — P1-ASSET-004 (the download already happens before `SUCCEEDED` is recorded; the invariant is asserted there).

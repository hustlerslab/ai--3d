# Phase 3 — Event System (P1-EVENT-001 · 002 · 003) · verification

**Completed:** 2026-09-25 · **Hat:** Backend Engineer (+ QA) · **Branch:** `ai-3d` on `92c494a` (dirty) · **Meshy spend: 0** · schema **v9 → v10**

## Before

`events(event_id, project_id, job_id, stage, status, message, duration_ms, ts)` — free-text stage/status only. Nothing typed, no entity ids, no evidence pointers, no correlation id on the row, and nothing stopped an `UPDATE` or `DELETE`; `delete_project` in fact deleted a project's whole event history.

## The change

| Where | What |
|---|---|
| `app/db/sqlite.py` `_v10_event_envelope` | **Additive** columns: `schema_version, event_type, severity, confidence, correlation_id, parent_event_id, producer, entity_ids, evidence_refs, payload` (all defaulted, so old rows read); indexes on `(correlation_id, event_id)` and `(event_type, event_id)`; **two triggers that `RAISE(ABORT)` on any `UPDATE` / `DELETE` of `events`**; `event_consumers(consumer, event_id)` idempotency ledger |
| `app/jobs/store.py` | `add_event(...)` keeps its positional signature; the envelope is keyword-only. Contract checked **before** writing (`EventContractError`): severity ∈ info/warning/error/critical, `evidence_refs` are **paths** (JSON, newlines, `data:` URLs, tags, >512 chars refused); correlation id filled from the project when the emitter omits it. `correct_event()` (a correction is a new row naming its parent), `list_run_events(correlation_id)`, `get_event`, `consume(consumer, events, handler)` |
| `app/jobs/context.py` | `ctx.emit(stage, message, status)` unchanged; optional envelope kwargs; stamps `producer=job.<type>` and the job's correlation id; **a writer failure is logged and swallowed, a contract violation is raised** |
| `app/jobs/runner.py` | `_publish()` in the single choke point: `job.queued / started / succeeded / retrying / failed / resumed`, severity set by the emitter (retrying/resumed → warning, failed → error); never fails the job |
| Handlers | `element.identity.resolved` (scene_plan reading, element_images plan) · `spatial.solve.started → spatial.solve.completed → scene.committed` chained by `parent_event_id`, commit names every object/element/instance/asset id · `asset.requested` (submit + resume) / `asset.generated` / `asset.failed` / `asset.reused` (binding or file on disk, 0 credits) · `render.generated` (build, severity from the build's own validation) |
| `app/api/projects_routes.py` | `project.created`, `input.received` typed (`analysis edited` left untyped: not a canonical type) |
| `app/projects/store.py` | `delete_project` **no longer deletes events** — the audit record of what ran and was spent outlives the project |

## Acceptance

| Criterion | Evidence |
|---|---|
| **001** Migration runs twice safely; old rows readable | `migration_output.txt`: a real v9 database with a pre-envelope row → v10, 18 columns, both triggers; marker forced to 0 and replayed → identical; the old row reads back with empty envelope fields; `UPDATE` refused both runs |
| **001** Every existing `emit()` call site behaves identically | `ctx.emit("s")`, `ctx.emit("s", "m")`, `ctx.emit("s", "m", status="warning")` record exactly the old (stage, message, status); envelope stamped, `event_type`/`severity` left empty — nothing invented. Full suite unchanged apart from the pre-existing CLIP failure |
| **001** `evidence_refs` are paths, never content | 6 content shapes refused before any write |
| **001** Severity set by the emitter | invalid level refused; a `failed` status does not make an untyped event an error |
| **002** Every job transition → exactly one event | noop: `job.queued, job.started, job.succeeded`; failing handler: `queued, started, retrying(warning), started, failed(error)` |
| **002** Canonical stage events fire | `spatial.solve.started/completed`, `scene.committed` (golden scene_plan); `element.identity.resolved` (reading with checked crops: 3 definitions, ids match); `asset.requested ×3 / failed ×1 / generated ×2`, then re-run `asset.reused ×2 (0 credits) / requested ×1`; `render.generated` (build with Blender faked at the handler boundary; evidence = preview, report, manifest; every manifest object id named) |
| **002** One project run = one `correlation_id` | golden stream: **26 events, 1 correlation id**, including the API-raised `project.created` / `input.received` (`golden_stream_summary.json`) |
| **002** Emission failure never fails the job | every `add_event` raises → job **SUCCEEDED**, drop logged |
| **003** No UPDATE/DELETE path; test asserts it | database refuses both (3 statements); source scan finds none, and proves the generic project-delete list excludes `events` |
| **003** Replay → no duplicated side effects | 5 events consumed, replayed, replayed after a real restart → 5 effects total; a second consumer is its own obligation; a handler that raises is retried, not marked done |
| **003** A correction is two rows | original untouched, correction names it, type `….corrected` |

`tests/test_event_bus.py`: **25 passed** (`pytest_verbose.txt`). Full backend on the final code: **1279 passed · 12 skipped · 30 xfailed · 1 failed** (the pre-existing, unrelated `test_room_prompt` CLIP-token test). Sample row: `sample_event_row.json` (a real `scene.committed`, parent → `spatial.solve.completed`).

## Mutation tests (each source restored byte-identical, sha1-verified)

| Mutation | Result |
|---|---|
| M1 UPDATE trigger dropped | **CAUGHT** |
| M2 `events` back in the project delete list | **CAUGHT** (5) |
| M3 runner publish stops swallowing | **CAUGHT** |
| M4 evidence-ref content check off | **CAUGHT** (7) |
| M5 correlation id not filled | **CAUGHT** (3) |
| M6 consumer ledger not written | **CAUGHT** |
| M7 `scene.committed` untyped | **CAUGHT** |

## A defect the full suite found — in this work, fixed

The drop path in `ctx.emit` logged `extra={"stage": …}`. Production's log-record factory already binds `stage`, so **logging raised and a dropped event failed the job** — precisely what P1-EVENT-002 forbids. The fault test passed alone and failed only in the full suite (the factory is installed by whichever earlier test imports `app.main`). Fixed (`event_stage`), and the test now installs the factory itself: **fails with the bug restored, passes with the fix, in isolation.**

## Honest limits

- **The golden stream has `with_identity: 0`.** On the mock provider nothing reads a moodboard, so the 44 placed objects are catalog pieces with no `element_id`. The identity events are proven on the reading fixture instead; a golden stream that carries identity end to end needs a real reading (P1-EVAL-001).
- `render.generated` is proven with Blender faked at the handler boundary (no Blender on this machine).
- **Behaviour change to note:** deleting a project now keeps its events. That is the point of P1-EVENT-003, but it means `events` grows without bound until a retention policy exists (P1-MEMORY-002 territory).

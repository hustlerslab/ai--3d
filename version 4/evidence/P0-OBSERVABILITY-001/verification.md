# P0-OBSERVABILITY-001 — Evidence: structured logging with correlation ids

**Completed 2026-09-21.** A failing project is traceable from the logs alone.

---

## Acceptance criteria

| Criterion | Result |
|---|---|
| Every line parses as JSON with the four fields | ✅ real capture: **8 lines, 0 malformed** |
| Filtering by correlation id returns the complete run | ✅ `test_filtering_by_correlation_id_returns_the_whole_run_and_nothing_else` |
| **Logs carry ids only — never a brief, an image, a prompt or a key** | ✅ scanned a real run: brief **absent**, password **absent**, email **absent** |

## The captured sample

`sample-log.jsonl` in this folder — a real register → create-project → enqueue-job cycle with `configure_logging()` active, against a throwaway temp database:

```json
{"ts":"2026-09-21T16:53:06Z","level":"INFO","logger":"aether.jobs","message":"job.start",
 "correlation_id":"cid_7f46371a902b","project_id":"proj_f26976fd4f","job_id":"job_fa189ec896","stage":""}
{"ts":"2026-09-21T16:53:06Z","level":"INFO","logger":"aether.jobs","message":"job.succeeded",
 "correlation_id":"cid_7f46371a902b","project_id":"proj_f26976fd4f","job_id":"job_fa189ec896","stage":""}
```

Scan of that capture:

```
brief in the log?     False
password in the log?  False
email in the log?     False
```

`stage` is empty on `job.start`/`job.succeeded` and populated on `ctx.emit()` lines — correct, because those two are not stage events. An id is left empty rather than guessed.

## The design decision that took three attempts

Where the ids get attached matters more than it looks, and the first two answers were wrong.

| Attempt | Why it fails |
|---|---|
| In the **formatter** | A formatter runs when a handler *writes*. Inline for a StreamHandler, but later and on another thread for a QueueHandler or anything buffered — where the contextvars are gone or belong to someone else. **The line still has ids, and they name the wrong customer.** The worst failure mode available. |
| A filter on the **root logger** | `Logger.filter()` applies to records logged on *that* logger. Records from `aether.jobs` propagate to root's *handlers* without ever passing root's *filters*. Silently stamps nothing. |
| The **record factory** ✅ | Runs once for every record, whatever logger made it and whatever handler consumes it, at the moment of creation. The ids become real record attributes, so `caplog` and any other handler can read them. |

A test pins the property directly: a record made inside a `bind()` and **formatted outside it** still carries the right ids. Reverting to the format-time version fails exactly that one test.

## Ids are ambient, not arguments

`log.info("job.start")` is already correlated. A logging call needing four extra parameters is a call somebody omits under pressure — and the line nobody bothered to enrich is the one needed at 3am.

`bind()` is a context manager, not a setter: a failed job must not leave its ids attached to whatever the worker thread picks up next.

## What carries the id

| Where | How |
|---|---|
| **Project** | minted at creation (`cid_` + 12 hex), stored on the row |
| **Job** | copied onto the job row at enqueue — denormalised so the runner can bind context *before* touching the project store; a lookup that itself fails is exactly when the ids matter |
| **Request** | one per request; an inbound `X-Correlation-Id` is honoured so a retry stays one thread, and the id is returned in the response header so a user can quote it |
| **Log line** | stamped by the record factory |

## Test results

| Suite | Result |
|---|---|
| `tests/test_structured_logging.py` | **25 passed** |
| `tests/test_p16_production_wiring.py` | **25 passed**, 2 skipped |
| **Full backend** | **1158 passed · 10 skipped · 30 xfailed · 0 failed** |

## Teeth verified by mutation

| Mutation | Tests failed |
|---|---:|
| **A** — resolve ids at format time instead of creation | **1** — and it is the only test that can catch it |
| **B** — remove redaction of secret-shaped fields | **8** |

## Two corrections to my own work

**1. I bound `project_id` in the request middleware from `request.path_params`.** That is always empty — middleware runs *before* routing — so it silently bound nothing. Removed, with the reason written in place; the runner binds `project_id` where it actually exists.

**2. I left `... or True` in a test.** Updating the pre-existing job-log test, I wrote an assertion that could not fail. It is replaced with two real ones (`project_id` matches the project, and a correlation id is present), which is what exposed correction 1.

## One pre-existing test updated, not weakened

`test_each_job_logs_the_ids_needed_to_trace_one_generation` matched substrings of a formatted message (`"type=scene_plan"`, `f"project={pid}"`). Those ids are now structured fields, so it asserts the **fields** and the **rendered JSON** instead — the same two claims checked against the real mechanism, plus `correlation_id`, which the string form could not express.

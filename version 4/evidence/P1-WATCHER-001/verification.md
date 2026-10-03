# P1-WATCHER-001 — Deterministic anomaly detectors · verification

**Completed:** 2026-09-25 · **Hat:** Backend Engineer (+ GenAI) · **Meshy spend: 0** · **model calls: 0**

## The change

| Where | What |
|---|---|
| `app/supervisor/contracts.py` | `WatcherObservation` exactly as design.md §21.1 (+ `detector`, `source_event_id` for traceability). `detection_method ∈ rule | statistic | model`. **`recommended_check` is validated**: it must start *Check / Verify / Confirm / Compare / Inspect* and its first clause may not contain an action verb (retry, regenerate, re-solve, repair, escalate, approve, continue, fail, …) — "looks correct" or "retry the build" cannot be constructed |
| `app/supervisor/watcher.py` | Nine rule detectors, each a pure function of the event stream, settings and the Watcher's own latency history. **They do not receive the provider.** Observation ids are content-addressed, so observing twice records once |
| `app/projects/store.py` | `set_stage` emits `project.stage.changed {from, to}` — the one place a stage changes — so regression is readable from events |
| `app/jobs/runner.py` | `_supervise()` runs `watch_project()` after every terminal job; never raises; `SUPERVISOR_ENABLED=false` removes it (gated twice: runner and `watch_project`) |
| `app/core/config.py` | `supervisor_enabled`, `watcher_retry_threshold` (2), `watcher_stale_job_seconds` (3600), `watcher_latency_sigma` (3.0), `watcher_latency_min_samples` (5) |

| # | Detector | Fires on | Method |
|---|---|---|---|
| 1 | `missing_terminal_event` | last runner transition is `job.started/queued` and the job has been silent > 3600 s | rule |
| 2 | `absent_output_checkpoint` | `scene_plan` succeeded and no `scene.committed` exists for the project (an earlier run's commit satisfies a checkpoint re-run); or an event's `evidence_refs` path is missing on disk | rule |
| 3 | `schema_parse_failure` | unknown event `schema_version`; a job failed/retried with `ValidationError`, `JSONDecodeError`, … | rule |
| 4 | `element_count_drift` | moodboard `element.identity.resolved.instances` ≠ `scene.committed.with_identity` | rule |
| 5 | `element_id_discontinuity` | an element id in the resolution is absent from the following commit's entity ids | rule |
| 6 | `latency_outlier` | duration > mean + 3·sd of that job type's history across projects (aggregates only), history ≥ 5 samples; each duration judged once, before it joins the history | statistic |
| 7 | `cost_above_budget` | sum of `asset.generated.credits` > `MESHY_MAX_CREDITS_PER_PROJECT` | rule |
| 8 | `retry_count_above_threshold` | > 2 `job.retrying` for one job | rule |
| 9 | `stage_moved_backwards` | `project.stage.changed` to an earlier stage (FAILED excluded) | rule |

## Acceptance

| Criterion | Evidence |
|---|---|
| **All nine detectors fire correctly on injected conditions** | `detector_matrix.txt`: each fault injected into its own fresh project fires **exactly its own detector and nothing else**; a clean project fires nothing — a perfect diagonal |
| **Zero model calls** | the matrix runs every rule pass with a provider whose every attribute access counts and raises: **0 calls**; `test_the_rule_pass_makes_zero_model_calls` |
| `detection_method` = rule or statistic on every observation | schema test over every finding of an every-fault project |
| `recommended_check` is a check, never an action | every emitted check starts Check/Verify/Compare/Inspect/Confirm; 5 action phrasings refused by the contract |
| A clean real run flags nothing | a real noop job through the runner → no finding |
| Phase 4 gate: **disabling the Watcher does not affect the pipeline** | same job with `SUPERVISOR_ENABLED` true vs false: identical status, result and event stream; the Watcher really ran in one (1 latency row) and not the other (0) |
| A broken Watcher never fails a job | `Watcher.observe` raising → the job still SUCCEEDED |

`tests/test_watcher.py`: **26 passed** (`pytest_verbose.txt`).

## Found while building it

My own contract validator rejected my own detector: the regression check read "…was a requested **re-run**…", an action verb, so the observation could not be constructed; the detector's failure was isolated (logged, other detectors unaffected) and the test caught the missing finding. Reworded. This is the validator doing its job on its author.

## Mutation tests

| Mutation | Result |
|---|---|
| a detector dropped from `RULE_DETECTORS` | **CAUGHT** (3) |
| runner gate removed alone / `watch_project` gate removed alone | survive — **by design**, the switch is checked twice |
| both gates removed | **CAUGHT** |

## Limits

- Detectors read what producers emit. The mock golden run carries no `element_id` (see P1-EVENT evidence), so detectors 4–5 are proven on injected streams that use the real producers' types and payload keys, not on a live moodboard run.
- Thresholds (3600 s, 3σ, ≥5 samples, >2 retries) are starting values, not measured ones.

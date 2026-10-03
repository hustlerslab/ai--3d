# P1-VALIDATOR-002 — The Validator agent · verification

**Completed:** 2026-09-25 · **Hat:** GenAI Engineer (+ AI Evaluation) · **Meshy spend: 0** · **no real model called**

## The change

| Where | What |
|---|---|
| `app/supervisor/contracts.py` | `ValidationResult` per design.md §21.2. **The schema refuses** a FAIL with no evidence, a FAIL with no `FailureCategory`, a PASS recommending anything but `continue`, content passed as evidence, and any category outside the **existing** 12-value enum (the field *is* `FailureCategory` — no new enum) |
| `app/supervisor/validator.py` | `Validator(memory, provider, project_root)`: refuses a provider with `allow_fallback=True` or temperature ≠ 0; accepts only its own memory. `validate(ValidatorInputs)` — **report results only**: `spatial_check`, `build_report`, `visual_fidelity`, render paths, design intents; `extra="forbid"`, so a Scene, objects or positions cannot be passed in, and passing a `Scene` itself is a `TypeError`. Deterministic verdicts consume layers 1–7's reports (hard violations after repair → cited FAIL with the repair's category; violated relationships → WARNING; missing build report → FAIL `VALIDATION_FAILURE`; missing spatial report → REVIEW_REQUIRED). The appearance verdict is the model's, **shown the renders as images**, and every non-convinced path ends REVIEW_REQUIRED |
| `app/supervisor/providers.py` | `complete_json(..., images=)`: renders sent as image blocks (Claude), `inline_data` (Gemini), `images` (Ollama); an unreadable image is an error, not a smaller evidence set |
| `app/jobs/runner.py` | `validate_project()` after every successful `scene_plan` / `build`; advisory, never raises |

## Acceptance — `tests/test_validator.py` (26 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| **Constructed with `allow_fallback=False`; provider failure → REVIEW_REQUIRED, never PASS** | 9 failure paths — no model, model raises, fallback marker, non-dict answer, unknown status, PASS below 0.7 confidence, PASS listing issues, FAIL citing an image it was not shown, non-numeric confidence — **all REVIEW_REQUIRED**; a real dead endpoint through the real transport → REVIEW_REQUIRED; **200 scripted answers across the answer space: PASS only for status PASS, confidence ≥ 0.7, no issues** |
| **Temperature 0** | role default 0.0; a provider at 1.0 is refused |
| **Every FAIL cites ≥1 evidence ref; unsupported verdict schema-invalid** | FAIL with `[]` evidence, FAIL with no category, content as evidence, a PASS recommending retry, an invented category → all `ValidationError` |
| **Receives report results, not raw geometry** | `ValidatorInputs(scene=…)` / `(objects=…)` refused; `validate(Scene)` → TypeError |
| **Cannot read `watcher_memory` or `orchestrator_memory`** | secrets planted in both are absent from its prompt; its handle is refused both tables by SQLite; a Watcher or Orchestrator store handed to it → `MemoryIsolationError` |
| **Existing 12-value `FailureCategory`, no new enum** | `failure_category` is typed `FailureCategory`; P1-VALIDATOR-003 asserts the enum unchanged |
| A convinced, supported model passes — and saw the render | PASS, `model_assisted`, evidence = the render; the provider received the render as an image and the prompt framed context as UNTRUSTED_DATA |
| End to end | the runner validated after a real golden `scene_plan`; with no Validator model configured (the default) appearance is REVIEW_REQUIRED and **no verdict is PASS** |

Sample: `sample_validation_results.json` — a deterministic FAIL (`repair_failure`, cites `planning/spatial_check.json`, `re_solve`) and a model-assisted FAIL (`asset_failure`, cites the render, `human_review`).

## Mutation tests (source restored byte-identical)

| Mutation | Result |
|---|---|
| PASS without the confidence bar | **CAUGHT** (4) |
| fallback provider accepted | **CAUGHT** |
| FAIL without evidence accepted by the schema | **CAUGHT** |
| model may cite renders it was not shown | **CAUGHT** |
| inputs accept geometry | **CAUGHT** |
| warm provider accepted | **CAUGHT** |
| **provider error becomes PASS** | **CAUGHT** (2) |

## Limits

- No live model judged a real render: the model boundary is scripted. On this machine there are no Blender renders, so a real run returns REVIEW_REQUIRED for appearance — the correct answer when there is nothing to look at.
- `MIN_PASS_CONFIDENCE = 0.7` is a starting value; P1-MM-002 is where it gets measured.
- Render verification (the deterministic 11-check layer, P1-VALIDATOR-001) is not yet in production — it needs Blender. When it lands, its report joins `ValidatorInputs` as another result the Validator consumes.

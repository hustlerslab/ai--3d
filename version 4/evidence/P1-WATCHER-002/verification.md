# P1-WATCHER-002 — Residual anomaly narration (model) · verification

**Completed:** 2026-09-25 · **Hat:** GenAI Engineer · **Meshy spend: 0** · **no real model called**

## The change

`Watcher.narrate(events, rule_findings)` (`app/supervisor/watcher.py`):

- **Residue only.** `residual_events()` keeps events flagged warning/error/failed that **no rule finding already explains** and that are not runner transitions. Empty residue or no configured model → **no model call**.
- The prompt carries the residue only through `as_untrusted_data()` (delimited, escaped). Pinned `NARRATION_SCHEMA`: `{anomalies: [{event_ids, summary, severity ∈ info|warning, recommended_check}]}`.
- Every narrated finding is `detection_method="model"`, **confidence capped at 0.5, severity capped at warning**, stored as kind **`narration`** (never `observation`), with its own id space (`obsm_…`).
- A narration is **dropped** if it cites no residue event (e.g. only rule-covered events) or if its check reads as an action — the contract refuses to construct it.
- `contracts.weigh()`: consumers rank by severity × method weight (rule 1.0 · statistic 0.8 · model 0.3) × confidence, so a model finding can never outrank a rule finding of equal severity.
- `watch_project()` narrates only when `WATCHER_PROVIDER` is set; a `RoleProviderError` is logged and **the rule findings stand**.

## Acceptance — `tests/test_supervisor_models.py`

| Criterion | Evidence |
|---|---|
| **Model output never overwrites a rule-detected observation** | a model answer claiming "nothing is wrong, the retries are fine" about rule-covered events → dropped; the rule's `retry_count_above_threshold` stored exactly once, untouched; narrations live in a different kind and id space |
| `detection_method` distinguishes them; consumers weight by it | narrated finding `model`, confidence 0.5; the model's `critical` capped to `warning`; `weigh()` ranks a rule warning above a model warning |
| **The Watcher cannot read `validator_memory` or `orchestrator_memory`** | secrets planted in both → absent from every prompt the Watcher built; a walk of the Watcher's object graph finds no Validator/Orchestrator store; its handle is refused both tables by SQLite |
| Residue only / nothing to say → nothing called | no flagged events → 0 prompts; progress events and runner transitions never reach the model |
| Model down → rules stand | `WATCHER_PROVIDER=ollama` against a 500 endpoint → `watch_project` returns the rule finding |
| Injected text stays data | an event message containing the close marker → still exactly one open and one close marker in the prompt |

## Mutation tests

| Mutation | Result |
|---|---|
| model severity not capped | **CAUGHT** |
| model may cite rule-covered events | **CAUGHT** |
| narration stored as observation | **CAUGHT** |
| residue includes everything | survived at first → an ordinary info event added to the residue test → **CAUGHT** |

## Limits

No real model narrated anything: the pass is proven with a scripted stand-in at the `complete_json` boundary. Whether narration is *useful* is an evaluation question (P1-MM-002 / P1-EVAL-001), not answered here.

# P1-ORCHESTRATOR-001 · 002 — Policy, directives and the decision audit trail · verification

**Completed:** 2026-09-25 · **Hat:** Backend Engineer (+ GenAI) · schema **v12** · **Meshy spend: 0** · **no real model called**

## The change

| Where | What |
|---|---|
| `app/supervisor/policy.py` | The design.md §21.3 table for **all 12** `FailureCategory` values (asserted at import). Perception → RE_READ (`scene_plan force`); asset → REGENERATE (`generate_elements`, bounded by the spend gates); geometry/solver → **RE_SOLVE = the Repair Engine** (`repair_scene`); the three code defects → HUMAN_REVIEW; repair → ESCALATE; validation → HUMAN_REVIEW; Blender → RETRY once, then ESCALATE; hardware → requeue the failed job (never blame the model); UNKNOWN → ESCALATE |
| `app/supervisor/contracts.py` | `Directive`: decision, target, `based_on` {observation_ids, validation_ids}, `repair_round`, rationale, `decided_by` policy/model, confidence. **Schema-refused:** any non-CONTINUE directive citing nothing; a dispatching decision naming no service |
| `app/supervisor/orchestrator.py` | `Orchestrator(memory, QueueHandle, ReviewHandle, provider=None)` — **no scene-store handle, by construction**. `QueueHandle` holds one callable (`JobRunner.request_repair`) and an allow-list of four services. A model is consulted **only for UNKNOWN**, only among RETRY/RE_SOLVE/RE_READ/ESCALATE, and only above 0.6 confidence; RE_SOLVE from the model still means the Repair Engine. A runner refusal becomes a recorded ESCALATE → review item. `appearance_unverified` (no model / nothing rendered) is a deployment state and is not escalated |
| `app/jobs/handlers/repair_scene.py` | `repair_scene` runs the **existing** Repair Engine on the committed scene and commits **only** through `commit_patch` (a partial repair is never committed); `check_scene` re-runs layers 1–7 on the committed scene and refreshes the report the Validator reads |
| `repair_rounds` (v12) + `AuditTrail` | **002:** per round — failure category + evidence, verdict, directive + rationale + decided_by, action job, scene version before/after, second validation, outcome; `GET /api/projects/{id}/repairs` |
| `app/jobs/runner.py` | after `scene_plan` / `build` / `repair_scene` / `check_scene`: Watcher → Validator → Orchestrator; advisory, never raises |

## Acceptance — `tests/test_orchestrator.py` (37 passed)

| Criterion | Evidence |
|---|---|
| **No scene-store handle — capability audit** | a walk of the live object graph from the Orchestrator (attributes, bound methods' `__self__`, closures, containers) reaches **no `SceneStore`**; `orchestrator.py`, `policy.py`, `review.py` import neither `scene.store` nor `scene.patches`, and never name `commit_patch` |
| All 12 categories have a table entry | 12 parametrized cases, each the designed decision and target |
| `decided_by` records policy or model | the table decided a solver failure with a configured model **never asked**; UNKNOWN → the model asked once, `decided_by: model` |
| Every directive cites its inputs | schema refuses the uncited and the untargeted |
| **A geometry failure invokes the Repair Engine, never a model for coordinates** | end to end: a real collision injected into a real committed golden scene → `check_scene` → Validator FAIL `solver_failure` → **RE_SOLVE → `repair_scene` round 1** → Repair Engine moved the piece → committed v3 → second validation clean → `validate_scene` finds **0** hard violations |
| **UPSTREAM_REQUIRED routes to re-read, not another repair** | a real Validator verdict on UPSTREAM_REQUIRED → RE_READ `scene_plan` |
| **002** complete record per round | `repair_record_injected_collision.json`: `solver_failure · FAIL · RE_SOLVE · policy · repair_scene · v2 → v3 · outcome resolved`, evidence `planning/spatial_check.json` |

## Mutation tests (source restored byte-identical)

| Mutation | Result |
|---|---|
| geometry sent to a model | **CAUGHT** |
| a code defect retried instead of reviewed | **CAUGHT** |
| a runner refusal not escalated | **CAUGHT** (2) |
| a round never closed | **CAUGHT** |
| the queue dispatches anything | **CAUGHT** |

## Found while building it

The first repair record showed `scene_version_before: 1` for a scene the check had examined at **v2** — the Validator took its version from `scene_spec.json`, which an out-of-band change does not update. Fixed: the version the deterministic check examined wins; the test now asserts `2`.

## Limits

- The Orchestrator's model path is proven with a scripted stand-in.
- Render verification (P1-VALIDATOR-001) is not in production (needs Blender), so a render-level mismatch cannot yet drive a directive; when it lands its FAILs flow through the same table.

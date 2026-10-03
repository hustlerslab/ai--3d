# P1-QA-003 — Failure-injection matrix · rows 5 and 12 closed · **18 of 18 passing**

**2026-09-26 · Hat:** QA Engineer (+ Backend, Blender) · **Blender:** 5.2.1 LTS (real) · **Meshy spend: 0**

Rows 1–4, 6–11 and 13–18 were already passing (`../P1-QA/verification.md`). This pass closes the last two, which had been recorded NOT PASSING. They needed Blender and the render verifier, and both now exist.

`injection_matrix.md` / `injection_matrix.json` in this folder: **18 rows, all PASS**, each with evidence.

## What was built

| Where | What |
|---|---|
| `app/supervisor/validator.py` | The Validator consumes the render verifier's evidence (`planning/render_verification.json`) **as a report**. It is still never handed geometry. Two findings escalate. **Render mismatch** (`render_matches_committed_scene` = fail, found by P1-EVAL-002) → `VALIDATION_FAILURE`, human review. **A piece built beyond ±25%** (per-object `scale` = fail) → `ASSET_FAILURE`, `regenerate_asset`. **Visibility deliberately does not escalate**: four corner cameras do not see every piece of a correct room (69.6% coverage measured on one), so "not seen" is for a person reading the report |
| `app/jobs/runner.py` | The Supervisor now also runs after a `verify` job, so layer-7 findings reach the Orchestrator through the same path as every other layer |
| `tests/test_failure_injection.py` | Rows 5 and 12 as **real-Blender** tests (PRODUCTION-PATH class), plus a fingerprinted row-file mechanism (below) |
| `tests/test_validator.py` | 4 fast unit tests of the same logic in the every-commit MOCK class: mismatch → human review; wrong size → asset failure to regenerate; unseen → no escalation; no evidence yet → no verdict |

## The two rows, injected for real

| Row | Injection | Detection | Category | Response | Person sees |
|---|---|---|---|---|---|
| **5** Alter dimensions beyond tolerance | A real GLB (0.8 × 0.9 × 0.8 m) bound to a floor piece whose recorded size is altered to 2.0 × 0.9 × 2.0 m. The importer places a mesh at its true size, so Blender's own validator measures it against the size the scene claims | Blender `validate_scene.py` ±25% → `verify` scale = fail | `asset_failure` | REGENERATE (`generate_elements` dispatched) | "Rebuilding a piece that didn't come out right" |
| **12** Render mismatch (object changed post-capture) | The room is built and rendered, then a piece is removed from the committed scene **without a rebuild** | render verifier: `render_matches_committed_scene` = fail, the piece named in `drifted_object_ids` | `validation_failure` | HUMAN_REVIEW (a review item is opened) | "One thing to look at" |

## Why a pass recorded in one run can be trusted in another

A pytest run holds exactly one test class (P1-QA-001), so the Blender rows can never share a run with the MOCK matrix that assembles all 18. Each Blender row therefore writes `row_NN_blender.json`, stamped with a **sha256 fingerprint of the code it exercised**: the Validator, policy, Orchestrator, render verifier, verify job, Blender's validate and import scripts, and the runner. The MOCK matrix accepts the record only while the fingerprint still matches the current code. Otherwise the row reads **NOT PASSING — "stale: re-run the Blender class"**.

This was exercised twice for real:
- A staleness mutation (a harmless comment in `validator.py`) turned rows 5 and 12 NOT PASSING until the code was restored.
- Adding `runner.py` to the fingerprint (a gap the mutations exposed, below) made the existing records stale: the matrix dropped to 16 PASS, then returned to 18 after a fresh Blender run.

## Mutations (3/3 + the staleness guard; each restored sha1-identical, row files restored too)

| Mutation | Caught by |
|---|---|
| render mismatch not escalated | fast Validator test **and** real-Blender row 12 |
| a wrong-size piece called a validation failure instead of an asset failure | fast Validator test **and** real-Blender row 5 |
| the Supervisor no longer runs after `verify` | real-Blender rows 5 and 12. This exposed that `runner.py` was **missing from the fingerprint**, so an edit there would not have made the records stale. Added |
| staleness: fingerprinted code changed without a new Blender run | the matrix marked rows 5 and 12 NOT PASSING |

## Full suites

Backend `class=MOCK passed=1533 failed=1` (+4; the same pre-existing CLIP test) · `class=PRODUCTION-PATH passed=23 failed=0` (+2: rows 5 and 12) · matrix **18/18**.

# Phase 19 — Testing (P1-QA-001 · 002 · 003) · verification

**2026-09-25 · Hat:** QA Engineer (+ DevOps, Backend) · **Meshy spend: 0**

## P1-QA-001 — three test classes, never summed — 🟢 DONE (locally verified; first CI run owed)

| Where | What |
|---|---|
| `aether-backend/pytest.ini` | markers `mock`, `real_provider`, `production_path` |
| `tests/support_classes.py` + `tests/conftest.py` | every test gets exactly **one** class at collection time (before `-m` filters): `tests/real/` → REAL-PROVIDER, `blender`/`production_path` → PRODUCTION-PATH, else MOCK. **A run holds one class**: no `-m` → MOCK only (the rest deselected); a `-m` selecting two classes is **refused** (exit 4). The summary prints one line per class — `class=MOCK passed=… failed=… error=… skipped=…` — never a combined number; `ALLURE_TEST_REPORT=<file>` writes the same per class as JSON. `_no_real_keys` keeps blanking every key for MOCK tests and stands aside only for REAL-PROVIDER tests |
| `.github/workflows/ci.yml` | per-commit job runs `pytest -m mock` and labels the result with the `class=MOCK` line |
| `.github/workflows/nightly-real-provider.yml` (new) | nightly `pytest -m real_provider` with repository secrets, spend caps 0, report uploaded |
| `.github/workflows/release.yml` (new) | MOCK and REAL-PROVIDER as separate jobs, then **`scripts/release_gate.py`** |
| `scripts/release_gate.py` (new) | **fails the release unless MOCK is green and at least one REAL-PROVIDER test PASSED** — a run where every provider was skipped "did not run" |

| Criterion | Evidence |
|---|---|
| Classes printed with counts | full backend run: `class=MOCK passed=1468 failed=1 error=0 skipped=35` · `class=REAL-PROVIDER did not run` · `class=PRODUCTION-PATH did not run` (the 12 Blender tests are now PRODUCTION-PATH, not MOCK skips) |
| **Release gate fails if REAL-PROVIDER did not run** | 6 gate cases: passes only for MOCK green + ≥1 live pass; fails on all-skipped, absent, a live failure, a MOCK failure, or no MOCK |
| MOCK stays green | as above (the 1 failure is the pre-existing CLIP-token test) |
| Never aggregated | a mixed selection is refused; the gate's output has no total |

`tests/test_test_classes.py`: 11 passed. **Owed:** a run of the workflows on GitHub (nothing was pushed from this session).

## P1-QA-002 — real-provider smoke tests — 🟠 BLOCKED on credentials (built, not yet run live)

`tests/real/test_provider_smoke.py`: one live call each — **Gemini**, **Anthropic**, **Qwen via Ollama**, **Meshy** (balance endpoint only: **0 credits**, and the spend ledger asserted unchanged), **Blender** (smoke cube, 4 samples). Each writes a JSON line (provider, outcome, latency, cost) to `$ALLURE_SMOKE_REPORT`; an unconfigured provider is **skipped with its name and reason**, which the release gate counts as "did not run".

On this machine every provider skipped (no keys, no Ollama, no Blender) — `class=REAL-PROVIDER passed=0 … skipped=5`, each skip naming its provider. **The acceptance ("passes nightly, cost recorded") needs the nightly workflow to run with secrets.** Not counted as done.

## P1-QA-003 — the failure-injection matrix — 🟡 16 of 18 rows passing

`tests/test_failure_injection.py` injects each §31 failure into the real pipeline; `injection_matrix.json` / `injection_matrix.md` record detection, category, response and the words the person sees. New behaviour built to make rows pass:

- `app/supervisor/messages.py` — the person-facing line for every directive ("We re-checked your room", "Correcting the layout — 1 of 2", "Taking longer than usual", "Retrying", "One thing to look at"), emitted as `repair.requested` / `human_review.required` events.
- Orchestrator: rule-measured identity breaks with no failing verdict → **RE_READ** (row 1); statistical/model hunches → **CONTINUE** (row 14); spend above budget → escalate; a model verdict contradicting clean deterministic verdicts → **HUMAN_REVIEW with both cited** (row 13); only findings **new on this pass** reach it (an old drift cannot re-trigger).
- `check_scene` object-count check against the plan's snapshot → `objects_missing` → HUMAN_REVIEW (row 8).
- `tradeoffs.explain_violations` — a blocked doorway in plain words with options (row 7).

| Row | Result |
|---|---|
| 1–4, 6–11, 13–18 | **PASS**, each with evidence (see the matrix) |
| **5** dimensions beyond tolerance | **NOT PASSING** — the ±25 % check runs inside Blender |
| **12** render mismatch | **NOT PASSING** — needs the render verifier (P1-VALIDATOR-001) |

Mutations (7): conflict detection off · identity anomalies ignored · hunches escalate · object-count check off · doorway not explained · user message lost · old findings re-trigger (survived first → a test added → caught) — **7/7 caught**.

**Correction C14:** §31 lists row 6/7 as `GEOMETRY_FAILURE` and row 10 as `REPRESENTATION_FAILURE`. A committed object in collision classifies as `SOLVER_FAILURE` (valid positions existed; same RE_SOLVE response), and invalid model output is `PERCEPTION_FAILURE` — P10 forbids relabelling a model error as an architecture error. Implemented per the taxonomy; `task.md` not edited.

# P1-MM-002: Benchmark model selection for uncorrelated error · verification

**2026-09-27 · Hat:** AI Evaluation Engineer (+ GenAI Engineer for the prompt fix) · **Spend: 0** (all models local, via Ollama)

## What was measured

The three Supervisor roles each call a model at exactly one point: Watcher narration, Orchestrator decide-on-UNKNOWN, and Validator appearance. **32 labelled cases** cover those points, with known-good AND known-bad cases in every role:

| Role | Cases | Labels |
|---|---|---|
| Watcher (does a batch of odd events hide a real pattern?) | 8 | 4 pattern · 4 no pattern |
| Orchestrator (an unclassified failure: what next?) | 16 | 4 each: RETRY · RE_SOLVE · RE_READ · ESCALATE |
| Validator (does the render match the stated design intent?) | 8 | 4 PASS · 4 FAIL, on two **real renders** from the production Blender build: the dining room, and the same scene emptied |

- **How cases run.** Each case runs through the real agent code (`Watcher.narrate`, `Orchestrator._ask_model`, `Validator._appearance`) with a real `RoleProvider` at **temperature 0**, **3 times**. The agents' own guards therefore apply exactly as in production: a PASS under 0.7 confidence becomes REVIEW_REQUIRED, an uncited FAIL is refused, and an Orchestrator answer under 0.6 confidence is not credited to the model.
- **Models.** qwen2.5:0.5b, llama3.2:1b, gemma2:2b and **qwen2.5vl:3b** (the codebase's own default and the only one that can see images), on the RTX 3050 Laptop (4 GB).
- **Hardware limit.** qwen2.5vl:3b runs 57% on the CPU on this card.
- **Where the models live.** Ollama 0.34.4 and all models sit on E:, as the user asked (C: was short of space). The download was checked against the release's published sha256.

Reports:
- `docs/benchmarks/p1_mm002_model_diversity.json` (final)
- `p1_mm002_before_prompt_fix.json`
- `p1_mm002_policy_note_wording.json`

Harness: `aether-backend/scripts/benchmark_model_diversity.py`. Fixtures: `aether-backend/docs/benchmarks/mm002_fixtures.py`.

## A benchmark bug caught before it misled

The first read of the numbers said "diversity HELPS" for the Watcher (mean φ −0.20). It was false. Two models answered "no pattern" to every case and another flagged nearly everything. An always-yes and an always-no model "disagree" by construction, and pairing them catches nothing.

The harness now:
- scores every model against the **best fixed-answer baseline** (0.5 for the binary roles, 0.25 for the 4-way Orchestrator);
- reports each model's answer distribution;
- makes **no diversity claim unless at least two models beat the baseline**;
- reports a correlation as **undefined, never 0**, when a model has no error variance.

## Found and fixed: the Orchestrator's prompt defined only one option

The production prompt told the model what RE_SOLVE means and named nothing else. **All four models answered RE_SOLVE to all 16 cases** (48 of 48 runs each), so every model was exactly at baseline.

| Orchestrator prompt | qwen2.5:0.5b | llama3.2:1b | gemma2:2b | qwen2.5vl:3b |
|---|---|---|---|---|
| Before: only RE_SOLVE defined | 4/16 | 4/16 | 4/16 | 4/16 |
| First fix: the policy table's notes, verbatim | 4/16 | 4/16 | 4/16 | 4/16 |
| **Final: plain definitions for the model** | 4/16 | 4/16 | **8/16** | **8/16** |

- **Why the first fix failed.** It built the definitions from `POLICY`'s notes to prevent drift, and **did nothing**. Those notes are written for engineers ("correctly abstained: evidence gathered, escalated - NOT 'no problem'"). It is kept as evidence of why wording matters.
- **The final fix.** It is `MODEL_OPTION_MEANINGS` in `orchestrator.py`. That wording had been written once, for a diagnostic run, and **was frozen before it was measured, not tuned afterwards**. The final run reproduces the diagnostic exactly, as it must at temperature 0.
- **Guards.** A test requires every option in the schema to have a meaning, and every option to be a decision the policy table itself makes.
- **Limitation, stated.** The wording was checked on the same 16 cases, with no held-out set, so 8/16 is not evidence that it generalises.

## Results (final run)

| Role | Model | Accuracy (baseline) | Precision / recall | Consistency (3 runs, temp 0) |
|---|---|---|---|---|
| Watcher | qwen2.5:0.5b | 0.50 (0.50) | answers "no pattern" to all | 1.00 |
| Watcher | llama3.2:1b | 0.38 (0.50) | pattern R 0.75 P 0.43 · no-pattern R 0 | 0.88 |
| Watcher | gemma2:2b | 0.38 (0.50) | pattern R 0 | 1.00 |
| Watcher | qwen2.5vl:3b | 0.38 (0.50) | pattern R 0.75 P 0.43 · no-pattern R 0 | 1.00 |
| Orchestrator | qwen2.5:0.5b · llama3.2:1b | 0.25 (0.25) | RE_SOLVE R 1.0, all others 0 | 1.00 |
| Orchestrator | gemma2:2b | **0.50** (0.25) | RE_SOLVE R 1.0 · RE_READ R 1.0 · RETRY 0 · ESCALATE 0 | 1.00 |
| Orchestrator | qwen2.5vl:3b | **0.50** (0.25) | RE_READ R 1.0 · ESCALATE R 1.0 · RETRY 0 · RE_SOLVE 0 | 1.00 |
| **Validator** | **qwen2.5vl:3b** | **1.00** (0.50) | **PASS P 1.0 R 1.0 · FAIL P 1.0 R 1.0 · 0 false PASS** | **1.00** |

On repeat-run consistency, verdicts were identical across all 3 runs for every case and model, except llama3.2:1b on the Watcher (7 of 8 cases).

## The correlation matrix (the question the task asks)

**Orchestrator.** Two models beat the baseline, gemma2:2b and qwen2.5vl:3b. **Error correlation φ = 0.00**: they fail different cases.

| | both wrong | only gemma wrong | only qwen wrong |
|---|---|---|---|
| gemma2:2b vs qwen2.5vl:3b | 4 | 4 | 4 |

- **Diversity is real here.** Together they are right somewhere on 12 of 16 cases, where either alone gets 8.
- **Neither is usable alone.** Each behaves like a two-option picker, and **neither ever chooses RETRY** (4 cases, both wrong on all 4).
- **Collecting the benefit is not possible.** It would need an arbiter that knows which model to trust per case, and none exists.

The full 4×4 matrix, including the no-skill pairs shown as such, is in the report.

**Watcher: not measurable.** No model beat the fixed-answer baseline. Correlation between models without skill says nothing about diversity, and the report says exactly that rather than a number.

**Validator: not measurable pairwise.** Only one model here can see images, and the 4 GB card runs only that one. The single model scores 8/8 with no false PASS.

## Decision (the "chosen combination", justified against the matrix)

| Role | Choice | Why |
|---|---|---|
| Watcher | **stay `none`** (rules only; the current default) | no local model beats a fixed answer |
| Orchestrator | **stay `none`** (policy table only; the current default) | best local model is 8/16 and never picks RETRY. The diversity benefit exists but cannot be collected without an arbiter |
| Validator | **opt-in `ollama:qwen2.5vl:3b`** (`VALIDATOR_PROVIDER=ollama`, `VALIDATOR_MODEL=qwen2.5vl:3b`); default left at `none` | 8/8, precision and recall 1.0, **no false PASS**, consistent. N=8 is too small to change a production default on |

The task says to record it honestly if diversity shows no measurable benefit. Here it shows a real benefit on the one role where two models have skill, but not one this system can use yet. That is the finding.

## Tests and mutations

- **Tests.**
  - `tests/test_orchestrator.py` gained 2 tests: every option is defined in the prompt, and every option is a policy decision.
  - The new `tests/test_mm002_benchmark_harness.py` has 8 tests. It runs **no model**: stand-in providers with known answers prove an oracle scores 100%, a one-answer model scores exactly its baseline, the agents' guards still apply, precision/recall, and the correlation and skill gate.
- **Mutations: 7/7 caught** (`mutations.txt`), each restored sha1-identical.
  - **Prompt fix (3):** only RE_SOLVE defined again · one option given no meaning · one option left out of the prompt.
  - **Harness (4):** a policy default credited to the model · no error variance reported as 0 · the skill gate ignored · a REVIEW_REQUIRED counted as catching a bad room.
  - **Two were missed at first:** the low-confidence test used a case whose correct answer was not the policy default, and the skill-gate test matched a different branch's prefix. Both were strengthened.
- **Full suite:** backend `class=MOCK passed=1570 failed=1`, the pre-existing `test_room_prompt.py::test_the_budget_is_measured_with_clip_not_guessed`.

## Also fixed along the way

- The harness no longer sets the data directory or opens the database at import time, and a test pins that.
- Found while probing: qwen2.5:0.5b once spotted a real pattern but wrote its check as the bare word "Check". The Watcher's own guard rejected it, which is correct, so the benchmark counts it as a miss.

## Not measured, and what would measure it

- **Keyed models** (Claude, Gemini) as candidates. The harness drives Ollama models today; `RoleProvider` already speaks `anthropic` and `gemini`, so adding them is a small change to `_provider` once keys exist. This matters most for the Orchestrator and for a **second vision model**, which would make the Validator's pairwise correlation measurable.
- **A held-out case set** to confirm the Orchestrator wording generalises beyond the 16 cases it was checked on.

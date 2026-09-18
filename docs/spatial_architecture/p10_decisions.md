# P10 — Decisions: twelve questions, answered; final scorecard

Continues `p10_production_boundary.md`. §22 (twelve final decision
questions) and §23 (final factual scorecard). This is the last P10 doc
before the P10 RESULT is appended to `decisions.md`.

## 1. §22 - twelve final decision questions

**1. Can any model directly emit final XYZ/yaw/scale/wall-contact/support/collision?**
No. Verified programmatically: `authority_audit.check_no_ai_override()`
returns zero violations across all 17 named artifacts.

**2. Is the architecture coherent end-to-end, sixteen stages, one authority model?**
Yes. `integration_audit.PIPELINE_STAGES` reconstructs all 16 stages with an
explicit contract each; only SOLVER and REPAIR_RE_SOLVE may decide
geometry, verified by `test_only_solver_and_repair_may_decide_geometry`.

**3. Can every traced decision be explained without invoking a model?**
Yes, for the 10 traces built (`trace_ten_decisions()`); every trace's
`explainable_without_llm` is `True` and its construction never calls a
model - checked by `test_every_trace_is_explainable_without_an_llm`.

**4. Does a multi-constraint composite (FACES+NEAR) fully succeed today?**
No, and this is the correct measured answer, not a bug: NEAR is satisfied,
FACES is violated, zero hard violations. Recorded as architectural debt
(`p10_production_boundary.md` §4), not silently patched.

**5. Is the 12-category failure taxonomy sufficient to classify every historical failure without ambiguity?**
Yes for all 13 named failures - each was assigned exactly one category,
with the P8 FACES bug's reclassification (`p10_failure_taxonomy.md` §3)
demonstrating the taxonomy's discriminating power, not just its coverage.

**6. Is the architecture model-independent (evidence contract vs. direct geometric coupling)?**
Yes, by construction - no code path lets a model hypothesis reach a
`SceneObject`'s final geometry without passing through a candidate, a
filter, and the solver (`p10_production_boundary.md` §2).

**7. Are hardware-caused and architecture-caused failures kept separate?**
Yes. Zero of the 13 historical failures are HARDWARE_FAILURE; the one hard
failure in this run's own 21-image benchmark is PERCEPTION_FAILURE
(grounding), confirmed against measured per-stage VRAM/latency budgets, all
within the RTX 3050's ceiling.

**8. Does the system correctly abstain rather than force success?**
Yes. `p10_integration_benchmark.py`'s composite scenario reports
`satisfied_constraints: ["NEAR"], violated_constraints: ["FACES"]` rather
than a forced pass; P4's repair benchmark reports `UNREPAIRABLE` rather than
a fabricated fix; the 21-image run reports `scene success 20/21`, not 21/21.

**9. Are the four success metrics kept separate?**
Yes. `compute_metrics()` reports physical (1.0), intent (0.4), evidence
(1.0), and system (1.0) success independently - never collapsed to one
number. The gap between physical/system=1.0 and intent=0.4 IS the finding:
geometry is always valid; not every stated intent is always satisfied.

**10. Does the full P1-P9 regression gate hold with zero silent changes?**
Yes. 718 passed / 7 skipped / 30 xfailed, and every frozen benchmark
(scene, wall, repair, coordinate, clearance, constraint, candidate, scene
validity, Blender e2e, and now the 21-image photo pipeline) reproduced
byte-identical to its own established baseline.

**11. Is the production boundary defined per path, not as one label?**
Yes - 6 distinct paths, 5 distinct readiness classes assigned
(`p10_production_boundary.md` §1); none defaulted to a single blanket
verdict.

**12. Does any architectural debt remain, and is it distinguished from model/hardware debt?**
Yes to both. One real architectural gap remains (candidate generation not
jointly satisfying two independent constraint types in one pass) -
explicitly separated from model/perception debt (wall-contact precision,
duplicate grounding, unverifiable asset axis) and hardware/compute debt
(11.4s render, too slow for interactive use) in
`p10_production_boundary.md` §4.

## 2. §23 - final scorecard

| Item | Verdict |
|---|---|
| No AI override of final geometry (17 artifacts) | PASS |
| 16-stage pipeline reconstructed with contracts | PASS |
| 10+ traced evidence->decision chains, model-free explainable | PASS |
| Multi-constraint composite (FACES+NEAR) fully satisfied | PARTIAL |
| 12-category failure taxonomy, all historical failures classified | PASS |
| Model-independence (evidence contract, no direct coupling) | PASS |
| Hardware boundary separated from architecture boundary | PASS |
| No forced success / correct abstention | PASS |
| Four success metrics kept separate | PASS |
| 30+ end-to-end adversarial scenarios | PASS |
| Frozen P1-P9 regression gate (all benchmarks incl. photo pipeline) | PASS |
| Determinism (20-repeat, benchmark + traces) | PASS |
| Production boundary defined per path (brief/photo/floorplan/mixed) | PASS |
| brief -> deterministic core | PRODUCTION_READY |
| brief -> end-to-end with LLM | CONTROLLED_BETA |
| photo -> scene | RESEARCH_ONLY |
| photo perception layer alone | MODEL_LIMITED |
| floorplan -> scene | NOT_YET_SOLVED |
| mixed-input | NOT_YET_SOLVED |
| `app/` modified this phase | NOT_APPLICABLE (zero changes - verified via `git status`) |

## 3. Architectural debt - final statement

The P1-P10 architectural program is **not** debt-free, and does not claim
to be. One concretely-scoped architectural gap remains (composite
constraint satisfaction across independent constraint types in a single
candidate-generation pass); it is understood, located, and small. All other
open items are model/perception debt or hardware/compute debt, neither of
which this program's own non-goals permit "fixing" by architecture change
(no new global optimizer, no second solver, no replacing perception models
merely to improve a benchmark number). The architecture itself - the
Evidence -> Geometry -> Constraints -> Candidates -> Solver -> Validation ->
Repair chain, with a single non-overridable authority at each geometric
decision point - is judged complete for the paths marked PRODUCTION_READY
and CONTROLLED_BETA above.

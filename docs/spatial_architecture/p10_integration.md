# P10 — Integration: the pipeline map, provenance chains, and multi-constraint audit

Continues `docs/spatial_architecture/decisions.md`'s P9 entry. Covers §2
(the reconstructed sixteen-stage pipeline), §4 (ten traced evidence ->
decision chains), and §7 (the multi-constraint candidate audit) of the P10
brief. Implemented in `research/spatial_architecture/integration_audit.py`
and `p10_integration_benchmark.py`.

## 1. The reconstructed pipeline

```
INPUT -> PERCEPTION -> EVIDENCE -> ROOM_GEOMETRY -> OBJECT_GROUNDING -> RELATIONS
      -> USER_MODEL_INTENT -> CONSTRAINTS -> CANDIDATE_GENERATION -> CANDIDATE_FILTERING
      -> CANDIDATE_RANKING -> SOLVER -> VALIDATION -> REPAIR_RE_SOLVE
      -> INDEPENDENT_INTENT_EVALUATION -> SCENE -> BLENDER -> FINAL OUTPUT
```

Sixteen named stages, each with an explicit input/output contract,
authority, evidence provenance, confidence representation, determinism
flag, failure-mode name (from `failure_taxonomy.py`), and two boolean
flags - `may_mutate_state`, `may_decide_geometry` - encoded as data in
`integration_audit.PIPELINE_STAGES`, not only prose, so a future phase can
query it. Full per-stage table in that module's own docstring/dataclass;
the load-bearing finding is:

**Only two stages may decide geometry: SOLVER and REPAIR_RE_SOLVE** (plus
ROOM_GEOMETRY/OBJECT_GROUNDING for a room/object's OWN measured shape, never
another object's placement). Every other stage - PERCEPTION, EVIDENCE,
RELATIONS, USER_MODEL_INTENT, CONSTRAINTS, CANDIDATE_GENERATION,
CANDIDATE_FILTERING, CANDIDATE_RANKING, VALIDATION,
INDEPENDENT_INTENT_EVALUATION - proposes, checks, or records, and never
writes a final position. Verified by `test_only_solver_and_repair_may_
decide_geometry`.

## 2. §4: ten traced evidence -> decision provenance chains

`integration_audit.trace_ten_decisions()` builds 10 traces from REAL,
already-tested P1/P4/P5/P7/P8/P9 output - not fabricated examples:

| # | Trace | Spans |
|---|---|---|
| 1-3 | P7's demonstration scene (AGAINST_WALL, FACES, ADJACENT_TO) | P7 |
| 4-7 | P9's brief demo (FACES, BETWEEN, NEAR satisfied, NEAR infeasible) | P8/P9 |
| 8 | Photo path - a model hypothesis independently agreeing with measured geometry | P7/P9 |
| 9 | P4 repair - a real collision-driven decision with escalation-ladder provenance | P4 |
| 10 | P5's wall-tilt representation decision | P5 |

Every trace answers "why was this object placed/claimed here" (§4's own
required test) through named fields (`evidence`, `interpretation`,
`geometric_hypothesis`, `relation`, `intent`, `constraint`, `candidate`,
`solver_decision`, `validation_result`) - all populated by READING the
already-existing provenance fields on real objects, never re-derived or
guessed. `explainable_without_llm=True` on every trace is asserted by test,
not merely claimed: no trace's construction or explanation ever calls a
model.

## 3. §7: the multi-constraint candidate audit - a genuine, honestly-reported finding

The required composite (a chair that must FACE a table, be NEAR a sofa, not
collide with either, and stay inside the room) was built and measured, not
assumed to work:

```
candidate_count_before_filter: 16
candidate_count_after_filter:  16   (none infeasible in this room)
selected_candidate:            (-3.0, -0.0)
satisfied_constraints:         [NEAR]
violated_constraints:          [FACES]
hard_violations:               0
```

**This is the correct, measured answer, not a bug fixed or hidden.**
`candidate_generators.distance_candidates`'s default rotation matches the
TARGET's own orientation (mirroring production's own `"beside"` convention,
`app/planning/compiler.py`) - it has no reason to also point at an
UNRELATED second target. The existing candidate architecture satisfies
DISTANCE and ORIENTATION independently and correctly (each alone, verified
throughout P8/P9's own 70+ tests) but does NOT automatically satisfy their
INTERSECTION on one object in a single generation pass - a real,
now-precisely-located architectural limit, not a vague "constraints
sometimes conflict" hand-wave. Recorded as architectural debt in
`decisions.md`'s P10 entry §16, not silently patched with a heuristic
(§43/non-goals: "do not add arbitrary heuristics to make benchmarks pass").

**What the finding does NOT mean**: it does not mean the architecture
cannot represent FACES+NEAR together - `Constraint`/`Intent`/`evaluate_all`
represent and independently verify both without conflict, and both ARE
individually satisfiable (`s04_faces`, `s05_near` in the adversarial suite
pass cleanly). It means CANDIDATE GENERATION for one constraint type does
not automatically consider a second, independent constraint type's own
objective - closing that gap (an orientation-aware ranking pass added to
`distance_candidates`, or a second regeneration pass chained after the
first) is a concretely scoped, smallest-possible future fix, not a
redesign.

## 4. Regression

`integration_audit.py`/`p10_integration_benchmark.py` import and call P1-P9's
own functions unchanged - confirmed by `test_p0_p9_modules_still_import_
cleanly_alongside_p10` and by every frozen P1-P9 benchmark re-running
byte-identical to its own baseline (see `decisions.md`'s P10 entry §12).

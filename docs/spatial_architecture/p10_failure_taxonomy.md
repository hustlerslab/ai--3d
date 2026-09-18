# P10 — Failure taxonomy: canonical categories, and every historical failure reclassified

Continues `p10_authority.md`. The canonical twelve-category taxonomy (§8)
and the reclassification of every named failure this program has actually
found, P0-P9. Implemented in `research/spatial_architecture/
failure_taxonomy.py`.

## 1. The twelve categories

```
PERCEPTION_FAILURE            a model's own output was wrong/absent
GEOMETRY_FAILURE              a geometric computation was wrong
REPRESENTATION_FAILURE        the DATA MODEL could not express a true fact
CONSTRAINT_FAILURE            a constraint was mis-specified or mis-compiled
CANDIDATE_VOCABULARY_FAILURE  no candidate could express a valid solution
SOLVER_FAILURE                the solver picked wrong among valid candidates
REPAIR_FAILURE                repair could not or wrongly fixed a violation
VALIDATION_FAILURE            a check was missing or incorrect
ASSET_FAILURE                 a catalogue/generated asset was wrong
BLENDER_EXECUTION_FAILURE     the build/render step itself failed
HARDWARE_FAILURE              VRAM/compute/latency, not correctness
UNKNOWN                       correctly abstained - not a defect at all
```

## 2. Every named historical failure, reclassified

| Failure | Phase | Category | Resolved? |
|---|---|---|:-:|
| VLM wall-contact refusal (78/78) | pre-P0 | PERCEPTION_FAILURE | Yes (replaced by deterministic geometry) |
| Wall-contact precision 77.8% / 25% UNKNOWN | pre-P0 | PERCEPTION_FAILURE | No (open, not blocking) |
| TV-unit duplicate grounding | P1 | PERCEPTION_FAILURE | No (upstream extent measurement, not a collision-architecture gap) |
| Collision-solver budget discard | P3 | SOLVER_FAILURE | Yes |
| Wall-candidate thickness-offset bug | P3 | GEOMETRY_FAILURE | Yes |
| Repair terminal-state misclassification | P4 | REPAIR_FAILURE | Yes |
| Random `object_id` nondeterminism | P4 | REPRESENTATION_FAILURE | Yes |
| Wall-tilt representation loss (~11 degrees) | P5 | REPRESENTATION_FAILURE | Yes (research layer; production `Scene.Wall` still 2D-only) |
| Wall-frame non-orthogonality | P5 | GEOMETRY_FAILURE | Yes |
| P8 FACES wiring bug | P8 (fixed P9) | REPRESENTATION_FAILURE | Yes |
| P8 NEAR/BETWEEN no metric vocabulary | P8 (fixed P9) | CANDIDATE_VOCABULARY_FAILURE | Yes |
| Asset forward-axis unverifiable | pre-P0, re-confirmed every phase | ASSET_FAILURE | No (open, but never blocking) |
| MockProvider room mis-parse (`res_studio`) | pre-P0 | PERCEPTION_FAILURE | No (mock-provider-specific) |

Full detail (description, exact source citation, resolved status) in
`failure_taxonomy.HISTORICAL_FAILURES` - every entry cites the phase/doc
that originally made the finding; nothing here is re-investigated, only
unified under one enum.

## 3. The most important reclassification: the P8 FACES bug

§8's own three rules exist specifically to prevent this kind of mistake,
and the P8 FACES bug is the clearest illustration of why they matter. A
first read might call it a SOLVER_FAILURE (the solver placed the sofa
facing the wrong way) or a CANDIDATE_VOCABULARY_FAILURE (matching P9's
NEAR/BETWEEN finding, which genuinely was this category). **Neither is
correct.** The solver chose correctly among the candidates it was given;
the candidate vocabulary already contained a correct, cosine-filtered
facing candidate. The actual defect was that the INTENT was encoded into a
field (`ObjectPlanItem.faces`) that `_ordered()`'s dependency graph never
reads - the DATA MODEL could not express "this constraint depends on that
object being placed first" in the channel that mattered. That is
REPRESENTATION_FAILURE, precisely, and classifying it any other way would
have pointed a future engineer at the wrong subsystem to fix.

## 4. Category counts (all HISTORICAL_FAILURES)

`failure_taxonomy.summary_counts()`: PERCEPTION_FAILURE 4, GEOMETRY_FAILURE
2, REPRESENTATION_FAILURE 3, CANDIDATE_VOCABULARY_FAILURE 1, SOLVER_FAILURE
1, REPAIR_FAILURE 1, ASSET_FAILURE 1, CONSTRAINT_FAILURE 0,
VALIDATION_FAILURE 0, BLENDER_EXECUTION_FAILURE 0, HARDWARE_FAILURE 0,
UNKNOWN 0. Zero `CONSTRAINT_FAILURE`/`VALIDATION_FAILURE`/`BLENDER_
EXECUTION_FAILURE`/`HARDWARE_FAILURE` entries is itself informative: no
phase has ever found a defect in the constraint COMPILER itself (as opposed
to what it was fed), in `validate_object`/`validate_scene`, or in the
Blender build/read-back pipeline - each of those subsystems has been wrong
zero times across ten phases of adversarial testing.

# P9 — Candidate architecture: audit, root cause, and the five-way comparison

Continues `docs/spatial_architecture/decisions.md`'s P8 entry. Covers the
live candidate-generation audit, the exact root cause of P8's FACES/NEAR
failure, and the architecture decision. `candidate_contract.md` covers the
FACES/NEAR semantic contracts in depth; `relation_to_candidate_generation.md`
covers the generator/filter/ranker pipeline and solver integration.

## 1. P8 failure reproduction

Re-running `constraint_benchmark.brief_end_to_end_demo()` (unchanged
scenario, unchanged code) at the start of this phase reproduced the exact
P8 numbers: FACES 100.1 deg error (VIOLATED), NEAR at 1.53 m / 2.66 m vs.
1.20 m requested (VIOLATED), BETWEEN 0.295 m lateral offset (SATISFIED at
the time). No discrepancy from the P8 report - confirmed before any change
was made.

## 2. Existing candidate audit

| Constraint | Existing candidate support | Candidate count | Correct candidate representable? | Selected? | Why not? |
|---|---|--:|:-:|:-:|---|
| FACES | `_relation_candidates("facing", ...)` (app/planning/compiler.py) - wall-aligned candidates filtered by `cos > 0.5`, best-aligned first | ~4-32 depending on room | **Yes** | **No** | See §3 - a WIRING bug, not a candidate-vocabulary gap |
| AGAINST_WALL | `_wall_aligned_candidates` (default floor path) | ~4-32 | Yes | Yes | (working correctly already, confirmed in P7/P8) |
| SUPPORT | `_pick_support` + `_surface_candidates` | varies | Yes | Yes | (working correctly already) |
| NEAR (explicit distance) | `_relation_candidates("beside", ...)` - THREE hardcoded gaps (0.08/0.25/0.5 m from the target's own edge) | 6 | **No** | No | No `RelationType`/`ObjectRelation` field can carry a numeric metre distance - production has no representation for "at exactly X m," only "close to this edge" |
| BETWEEN | none (P8 approximated it as `beside`) | 0 (specific to BETWEEN) | **No** | No | No `RelationType` value for "on the segment between two named targets" exists at all |

## 3. Root cause of the FACES failure (§2-4 of the P9 brief)

Traced via a standalone instrumented script (not a guess): `place_objects`'s
own `_ordered()` function sorts items by `(priority, ANCHOR_RANK, ...)`, and
separately waits for a dependency ONLY when it is expressed through
`item.relation.target_key`. P8's bridge (`constraint_compiler.
apply_constraints_to_plan`) wrote the FACES hint into `ObjectPlanItem.faces`
(free text), which `_ordered()` never reads at all. `ANCHOR_RANK["sofa"] = 0`
is lower than `ANCHOR_RANK["tv_unit"] = 1`, so the sofa was placed BEFORE
the TV - at the moment `_faces_rank` needed the TV's position to re-order
sofa's own wall-aligned candidates, the TV did not exist yet in
`placed_by_key`, so `_faces_rank` returned the same (uninformative) rank for
every candidate, and the sofa kept whatever candidate the wall-grouping
happened to list first (the south wall, facing away from the TV).

**This is Category B/D from §2's own taxonomy: candidate ranking is
insufficient BECAUSE of a sequencing/dependency gap, not because a
satisfying candidate does not exist.** A satisfying candidate existed in the
SAME list `_relation_candidates("facing", ...)` would have produced, had it
been invoked - confirmed by the critical experiment (§4).

## 4. The critical experiment (§41), exactly as required - one change, isolated

**Step 1 - FACES alone.** Changed exactly one thing: route the ORIENTATION
constraint through `ObjectRelation(type="facing", target_key=...)` instead
of `.faces` free text (`constraint_compiler.py`, `_TYPE_TO_RELATION`).
Result: FACES angular error 100.1 deg -> **0.0 deg**. Nothing else in the
scene changed except that the TV now places before the sofa (the SAME
dependency mechanism that already worked for `support_key`/other
`.relation` targets). **Zero new candidate-generation code was needed for
this fix.**

**Step 2 - NEAR alone.** Kept the FACES fix in place (it does not interact
with NEAR) and added ONLY a new candidate generator: `candidate_generators.
distance_candidates` - a 16-point ring at the constraint's own explicit
`distance_m`, filtered through `validate_object` (reused), ranked by
`|actual - ideal|` (`candidate_ranker.rank_by_ideal_distance`). Isolated
test (`test_candidate_generators.py`): a chair 5 m from a sofa, asked for
exactly 1.2 m, lands at exactly 1.2 m (`math.isclose(..., abs_tol=1e-3)`).

**Step 3 - combined**, on the real brief-demo scene: FACES 0.0 deg,
BETWEEN 0.000 m lateral (also fixed by the same-shaped `between_candidates`
generator, see `relation_to_candidate_generation.md`), one of two NEAR
constraints satisfied exactly at 1.20 m, the second genuinely infeasible at
the exact tolerance given the final room layout (reported honestly as
VIOLATED, not forced - see `candidate_contract.md`'s "no benchmark
cheating" section).

No step was skipped and no two changes were bundled before measuring.

## 5. Five architecture candidates (§40)

| Candidate | Sketch | Verdict |
|---|---|---|
| **A. Existing candidate vocabulary + minor additions** | Fix FACES wiring (zero new code); add two small, targeted NEW generators (distance ring, between region) for the two genuinely unrepresentable cases | **Chosen.** See below. |
| B. Constraint-specific candidate generators (one per `ConstraintType`) | A full generator for EVERY type, including ones (ORIENTATION, CONTACT, SUPPORT) that already work correctly | Rejected: would duplicate production logic that the critical experiment proved is already correct - exactly the "reuse, never fork" violation this program has avoided since P1 |
| C. Unified relational candidate generator (one function, dispatch internally) | A single `generate_candidates(constraint)` covering all types | Rejected: no measured benefit over two small, separately-testable, separately-provenance-carrying functions (`distance_candidates`/`between_candidates`) - a unified dispatcher would just be `candidate_generators.py`'s own module-level organisation renamed, not a different architecture |
| D. Global CSP candidate solver | Feed all candidates + all constraints into a constraint-propagation/CSP solver | Rejected: P3 already measured (and this program has never re-litigated) that global search costs far more than it returns at Allure's real object-count scale; nothing in this phase's own measurements (sub-2 ms per object even at n=20, see `candidate_contract.md`'s performance section) suggests the existing candidate-and-validate solver is insufficient once fed the right candidates |
| E. Continuous optimisation | Gradient-based or sampling-based continuous pose optimisation | Rejected: no evidence anywhere in this program that a discrete, deterministic candidate lattice (P1's own precedent, `_radial_candidates`) is insufficient; continuous optimisation would also break this program's determinism requirement (§48) without extraordinary care no measured need justifies |

**Candidate A is chosen**, and specifically the MINIMUM version of A: fix
the one real wiring bug, add exactly the two generators the audit (§2) found
were genuinely missing, add nothing else. This mirrors this program's own
established pattern (P3's "greedy is the default solver," P8's "every
constraint is SOFT") of choosing the smallest architecture the actual
measurement supports, not the most general one imaginable.

## 6. What was explicitly NOT built, and why

| Considered | Decision | Why |
|---|---|---|
| An ORIENTATION candidate generator in `candidate_generators.py` | Not built | The critical experiment (§4) proved the wiring fix alone is sufficient - production's own `_relation_candidates("facing", ...)` already generates the right candidates; building a parallel one would duplicate correct logic |
| A generic `CandidateSource.CONTACT`/`SUPPORT` in the new typed model | Not built | Both already work correctly through the existing bridge (`ObjectRelation("against_wall"/support_key)`) - no gap to close |
| Per-asset forward-axis correction (§36) | Not built | Unchanged from P6/P7/P8's own finding: identity remains measured-correct for every benchmarked asset; no P9 scenario needed a correction |
| A second, independent solver or CSP layer | Not built | §32's own explicit prohibition, and no measurement anywhere in this phase suggested the existing candidate-and-validate loop is the bottleneck |

## 7. Verdict

**PASS.** See `relation_to_candidate_generation.md` for the full pipeline,
demonstration, and benchmark results, and `decisions.md` for the complete
26-section P9 RESULT.

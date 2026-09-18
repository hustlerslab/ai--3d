# P8 — Intent model

Continues `docs/spatial_architecture/decisions.md`'s P7 entry. Covers the
`Intent` type this phase adds; `constraint_contract.md` covers what it
compiles into, `intent_to_solver.md` covers how it reaches the existing
solver, `constraint_lifecycle.md` covers the full lifecycle end to end.

## 1. Why a new type, not a rewrite of P7's `GeometricRelation`

§7 of the P8 brief asks whether intent should reuse P7's
`relation_model.GeometricRelation`, a specialised type, or a thin extension
- and explicitly forbids a second parallel graph. `Intent` is the thin
extension, not a new graph: it names the same kind of entities a
`GeometricRelation` does (`subject_id -> predicate -> target_id`) and is
passed to `constraint_compiler.compile_intents` alongside a `SpatialScene`,
as a second small argument - never a second container with its own lookup
machinery.

It needed its own dataclass for two concrete reasons:

1. **`parameters: dict`** - a want can carry a number an observation never
   needs ("keep 1.5 m away", "15 degree tolerance"). `GeometricRelation` has
   no such field, and none of P7's five call sites need one.
2. **A five-way `IntentSource`** (`USER_ASSERTED` / `MODEL_INFERRED` /
   `OBSERVED` / `DERIVED` / `SOLVER_DECIDED`) - richer than P7's four-way
   `SpatialSource`, because P8 must distinguish a user's own words from a
   model's inference in a way P7's photo bridge never had to (it never
   received free-standing user text at all).

`research/spatial_architecture/relation_model.py` (P7) is **unchanged** by
this phase - confirmed by this phase's own regression run
(`decisions.md`'s P8 entry, "Files Changed" section).

## 2. The five sources, and the one that produces no `Intent` at all

| Source | Meaning | Example |
|---|---|---|
| `USER_ASSERTED` | The user said so | "put the sofa against the north wall" |
| `MODEL_INFERRED` | A model proposed it, unasked | a moodboard reader's free-text `against`/`faces` hint |
| `OBSERVED` | Read directly off evidence (a P7 FACT) | "keep it where the photo showed it" |
| `DERIVED` | Computed from other intents by a deterministic rule | a functional template (§45) expanding into several constraints |
| `SOLVER_DECIDED` | What the solver actually chose | **produces no `Intent`** - see below |

`SOLVER_DECIDED` is named for completeness (a switch over `IntentSource`
should be exhaustive without a default case) but no constructor in this
phase ever builds an `Intent` at this source: a solver's decision is
recorded as geometry (`SceneObject.position`/`.rotation_y`) plus provenance
(`Confidence.source`), exactly as P1/P3/P4 already do - turning a decision
back into an "intent" would be inventing a want out of an outcome, which is
backwards from what an intent is.

## 3. Priority: a precedence contract, not an optimisation score

```
USER_EXPLICIT = 0        # highest precedence
USER_IMPLICIT = 1
SYSTEM_REQUIRED = 2       # reserved - see §4
GEOMETRIC_VALIDITY = 3    # reserved - see §4
MODEL_INFERRED = 4
STYLE_PREFERENCE = 5      # lowest precedence
```

Lower value always outranks higher, deterministically - never a weighted
sum, never a learned score. §12's own framing ("this is an engineering
precedence contract, not an optimization opinion") is implemented literally:
`sorted(constraints, key=lambda c: c.priority)` is the entire ranking
algorithm anywhere in this phase.

## 4. `SYSTEM_REQUIRED` and `GEOMETRIC_VALIDITY` are reserved, not populated

Allure's real hard geometric checks (collision, room-bounds, door-clearance)
already live in `app.spatial.validation`, and stay there, untouched (§41: do
not duplicate validation) - they never pass through the intent/constraint
layer, so nothing in this phase constructs an `Intent` at either reserved
priority level. They are named so a future caller that DOES need to express
"as important as a hard validity check" has a place to put it without a
breaking enum change - the same pattern P7 used for `GEOMETRIC_INVARIANT`/
`FUNCTIONAL` in its own relation taxonomy.

## 5. Deterministic ids

`intent_id(subject_id, predicate, target_id, parameters)` - `hashlib.sha1`
over the sorted-by-key parameter representation, never Python's builtin
`hash()` (salted per process unless `PYTHONHASHSEED` is fixed) and never a
counter or `uuid4()`. Verified in `tests/test_intent_model.py` (deterministic
across calls, order-independent over `parameters`, differs when parameters
differ) and in the 20-repeat determinism benchmark
(`constraint_benchmark.determinism_check`).

## 6. No `status` field, unlike the brief's own sketch

§7's sketch lists `status` on `Intent` itself. This implementation omits it:
no caller in this program ever withdraws or supersedes an intent once
created (no review/editing UI exists yet that would produce
SUPERSEDED/WITHDRAWN), so a field with only ever one real value would be
exactly the "field with no consumer" §9 warns against for `Constraint`.
Lifecycle lives entirely on the DERIVED `Constraint`
(`constraint_model.ConstraintStatus`), which real code advances. `Intent` is
an immutable fact record, like `GeometricRelation`: "this was asked for,"
full stop. A future caller that needs to retract an intent simply omits it
from the next `compile_intents` call.

## 7. Regression: nothing in P0-P7 imports this module

`intent_model.py` is consumed only by this phase's own
`constraint_compiler.py`, `constraint_evaluator.py`, and
`constraint_benchmark.py` - confirmed by grepping every P0-P7 module for the
string `intent_model`, which returns no hits outside this phase's own files.

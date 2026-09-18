# P3.1 — Formal problem definition

Continues from `optimization_baseline.md`. Defines the Allure scene
optimization problem precisely, validates the hard/soft/preference hierarchy
the brief proposes against what P1/P2 already measured (not re-derived from
scratch), and states why the natural formalization is **discrete/combinatorial**,
not continuous.

## 1. State space, read from the actual code, not invented

Every placement mechanism already inspected (`optimization_baseline.md` §1)
generates a **finite, ranked candidate list per object** — `_floor_candidates`,
`_wall_aligned_candidates`, `_surface_candidates` in `compiler.py`; the
wall-tangent/radial/perpendicular lattices in `collision_solver.py`. None of
these are continuous samplers; all enumerate a bounded set of concrete
`(position, rotation)` pairs. The optimization problem this program actually
faces is therefore:

```
Objects:      O = {o_1, ..., o_n}
Candidates:   C_i = {c_i1, ..., c_iM_i}   (finite, per object, already ranked)
Assignment:   A: O -> (⋃ C_i) ∪ {UNPLACED},  A(o_i) ∈ C_i ∪ {UNPLACED}
Scene(A):     the Scene built by committing every A(o_i)
```

This is a **discrete constraint satisfaction / weighted-CSP problem** over
`∏ M_i` possible joint assignments — not a continuous nonlinear program. That
single fact, read directly from the existing candidate generators, already
rules out continuous/nonlinear optimization (item 5/6 of the brief's research
list) as a representation mismatch: adopting one would require replacing the
finite candidate generators themselves, which no measured failure justifies
(the failure class in `optimization_baseline.md` §4 is an *ordering/search*
problem over already-discrete choices, not a *representation* problem).

## 2. Hard / soft / preference, validated against what P1 and P2 already measured

The brief proposes a hierarchy to research and validate, not assume. Checked
against every constraint P0-P2 actually implemented and measured:

| Constraint | P1/P2 evidence | Tier |
|---|---|---|
| Room containment (`OUTSIDE_ROOM`) | H1, measured 0 violations/547 objects | **HARD** |
| Object collision (`COLLIDES_OBJECT`) | H3, P1's entire subject; 0/547 (brief), 2/46 residual (photo path, diagnosed as upstream duplicate detection) | **HARD** |
| Wall collision (`COLLIDES_WALL`) | H2, same evidence | **HARD** |
| Door-block (`BLOCKS_DOOR`) | H4, existing | **HARD** |
| Support (object has a valid parent/floor) | Asserted by construction in `place_objects` (a candidate with no valid support is never generated) — not a validator check, but effectively hard already | **HARD** |
| Circulation, fully disconnected | P2.2's own taxonomy decision, re-confirmed by the P2.8 benchmark's `impossible_room`/`bed_circulation_blocked` cases | **HARD** |
| Pairwise/functional clearance | P2.2: soft by definition (comfort figures, not physical impossibilities) | **SOFT** |
| Circulation, narrow-but-passable | P2.2: soft (a measured deficit, not a broken room) | **SOFT** |
| Wall contact (`AGAINST_WALL`) | Never a validator check anywhere in `app/` — an *advisory* relation `apply_spatial_graph` uses to bias candidate ranking, not a pass/fail gate | **SOFT** (never hard) |
| Functional relationships (faces, near) | Same — `SpatialPredicate` relations bias ranking, never gate validity | **SOFT** |
| Symmetry / alignment / visual balance | P1 and P2 both found **zero evidence source** anywhere in the pipeline (no brief field, no VLM output, no photo grounding produces a symmetry signal) | **PREFERENCE — not implemented, unchanged from P1/P2's own scope-out** |

**The brief's proposed hierarchy is confirmed correct**, with one addition
the brief didn't name explicitly but P2 already measured: circulation splits
across hard/soft by its own deficit (P2.2), not uniformly soft. No new tier
is invented here — P3 inherits P1/P2's taxonomy unchanged, per the mission's
own "do not restart / do not discard conclusions" instruction.

## 2a. Two explicitly-deferred P2 coverage gaps — carried forward, not solved here

Dining-chair pull-back clearance and kitchen wall-relative clearance
(`decisions.md`'s P2 entry) remain **not implemented**. P3 is scoped to
*search/optimization architecture*, not to closing P2's own named coverage
gaps — building a wall-relative "front" convention for chairs is a P2-shaped
task (a new evidence/representation question) that would only muddy P3's own
measurement of search-strategy quality. They are re-stated here, not
silently dropped, per the mission's explicit instruction to keep tracking
them.

## 3. Objective function

```
Score(A) = (HardCount(A), SoftDeficit(A))     — lexicographic, hard dominates soft
```

`HardCount(A)` = number of hard violations in `validate_scene(Scene(A))` plus
the count of fully-disconnected-circulation `ClearanceViolation`s. `SoftDeficit(A)`
= sum of every soft violation's `deficit_m` (pairwise clearance, functional
envelope, narrow circulation) — a single unweighted sum, not a hand-tuned
multi-term blend (`w1*... + w2*...`), because **no evidence anywhere in this
program has ever measured relative weights** between e.g. a clearance deficit
and a narrow-corridor deficit; inventing weights would be reporting precision
the pipeline does not have (the same reasoning P1/P2 already applied to
reject a 7-channel confidence score and a learned CAPS-style weight). A
lexicographic ordering, not a weighted sum, is what guarantees "never let
aesthetically better beat physically invalid" mechanically, by construction,
rather than by hoping the weights happen to be tuned correctly.

Objects left `UNPLACED` contribute one hard-count unit each (an unplaced
required object is itself a scene failure, matching how `objects_placed ==
grounded` already gates `scene_success` in `integration_benchmark.py`).

## 4. Search strategies this formalization admits

Because the state space is discrete and finite per object, every strategy in
the brief's research list reduces to a well-known **CSP/weighted-CSP search
algorithm** operating over the SAME `(O, {C_i}, Score)` triple:

- **Greedy** (current architecture): visit objects in a fixed order, commit
  the first candidate with `HardCount` unchanged from the current partial
  scene, never revisit.
- **Greedy + backtracking**: on total failure for object *k*, backtrack to
  object *k-1* and retry its NEXT candidate, bounded by a backtrack budget.
- **DFS / bounded search**: explore the candidate tree more broadly than
  backtracking's single-step retry, bounded by an explored-node budget.
- **Beam search**: keep the top-*W* partial assignments by `Score` at each
  step instead of committing to one.
- **CP-SAT / MILP**: encode `(O, {C_i}, hard constraints)` as a constraint
  program directly — the P1 decision matrix already argued (and is re-argued
  in P3.3, with the added P3-specific angle) that this trades a real
  dependency and encoding cost for a search space Allure's own literature
  survey (Holodeck/RoomCraft/HSM, `collision.md` §4) shows the field does not
  reach for at this scale either.

## 5. Exit gate: met

The Allure scene optimization problem now has a precise formal definition
(§1, §3) built entirely from what the existing candidate generators already
produce, and its constraint hierarchy is validated against P1/P2's own
measurements rather than assumed from the brief's example (§2) — with the
brief's proposed structure confirmed correct, not altered.

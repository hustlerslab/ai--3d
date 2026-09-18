# P9 — Candidate contract: FACES/NEAR semantics, filtering, ranking, and honesty

Continues `candidate_architecture.md`. Defines the exact semantic contracts
every generator/evaluator pair shares, and documents this phase's explicit
compliance with §43's "no benchmark cheating" rule.

## 1. FACES: one shared semantic definition, generator and evaluator alike

§9 asks for a precise definition, used identically on both sides (§10's
invariant). This phase's definition, unchanged from what P8 already
measured and what production's own solver already implements:

> **FACES(subject, target)** holds iff the target's centre lies within a
> frontal cone of half-angle 60 degrees from the subject's own forward axis
> (`cos(half-angle) = 0.5`).

This is not a new number invented for P9: it is `app/planning/compiler.py`'s
own `_FACES_COS = 0.5`, reused as `constraint_evaluator.
DEFAULT_ORIENTATION_TOLERANCE_DEG = 60.0` (P8) and as the exact filter
`_relation_candidates("facing", ...)` already applies to its own candidates
(`cos > 0.5`). The generator (production's own, unchanged) and the evaluator
(P8's, unchanged) were ALREADY using the same threshold before P9 began -
P9's audit (§10 below) exists to confirm this consistency explicitly rather
than assume it.

**Same position (§9's "target lies within a frontal cone" edge case):** when
subject and target coincide, no direction is defined - both the generator
(no candidate produced) and the evaluator (`UNKNOWN`, not `SATISFIED` or
`VIOLATED`) treat this identically, per the `target_coincident` adversarial
scenario.

## 2. §10: candidate/evaluator consistency, proven, not assumed

The required invariant: *generate a candidate specifically to satisfy FACES,
then evaluate it - it must return SATISFIED unless something independent
prevents it.* Verified directly on the real brief-demo scene: the sofa
placed via the (now correctly-wired) `"facing"` relation evaluates to
**0.0 degrees angular error** - exactly SATISFIED, not merely "close."
Fifteen of this phase's 40 adversarial scenarios exercise ORIENTATION
directly (`sofa_faces_tv`, `chair_faces_table`, `faces_tv_rotated_room`,
`faces_tv_diagonal_wall`, `against_wall_plus_faces`, `wall_local_orientation_
near_wall`, plus the deliberately-failing ones - `target_behind_object`,
`target_beside_object`, `target_coincident` - which confirm the evaluator
correctly reports VIOLATED/UNKNOWN when a candidate genuinely does not
satisfy the contract, not just when one does).

## 3. NEAR: definition, and why no metric default exists

> **NEAR(subject, target, distance_m)** holds iff the subject's centre lies
> within `tolerance_m` (default 0.3 m, `constraint_evaluator.
> DEFAULT_DISTANCE_TOLERANCE_M`, unchanged from P8) of `distance_m` from the
> target's centre.

A bare NEAR with no explicit `distance_m` has NO generator output
(`distance_candidates` returns `[]`) and NO evaluator verdict beyond
`UNKNOWN` (P8, unchanged) - §11's own explicit instruction ("do not hardcode
NEAR=0.8m unless explicitly sourced") is honoured identically on both the
generation and evaluation sides, which is the same consistency §10 asks for
applied to a predicate whose honest answer is sometimes "we cannot judge
this," not always a number.

## 4. BETWEEN: the same consistency, for a compound constraint

`between_candidates` samples the (target_a, target_b) segment at
`t in {0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65}` with lateral offsets in
`{0, +-0.15, +-0.3}` m - the SAME unclamped-projection/perpendicular-distance
formula P8's own evaluator already uses (`constraint_evaluator.
_evaluate_between`), so a candidate this generator proposes is, by
construction, measured the same way the evaluator will re-measure it.
Verified: `between_sofa_tv` places a coffee table at the exact midpoint,
0.000 m lateral offset, `Verdict.SATISFIED`; `between_with_obstruction`
confirms the generator steps OFF the exact midpoint when it is blocked,
finding a still-`SATISFIED` (or, if none exists within tolerance,
`PARTIAL`) pose rather than reporting a false success at a colliding point.

## 5. Filtering vs. ranking (§17), and the invariant that keeps them separate

`candidate_filters.filter_feasible` is the ENTIRE hard-feasibility gate
(wraps `app.spatial.validation.validate_object`, never reimplemented) and
contains zero preference logic. `candidate_ranker.rank_by_ideal_distance`/
`rank_between` operate ONLY on candidates that already survived filtering -
verified directly by `hard_soft_conflict_never_overridden`: a candidate that
would score BEST by distance-to-ideal but collides is never even offered to
the ranker, so a soft preference can mathematically never resurrect a hard-
infeasible candidate (§29's own explicit worry).

## 6. Determinism (§48) and provenance (§25)

Ranking ties break on `candidate_key` (§24 - rounded position/rotation,
never insertion order or a random number) - `test_rank_by_ideal_distance_
tie_break_is_deterministic` feeds the SAME two equidistant candidates in
both orders and confirms identical output. Every `Candidate` carries
`source`/`constraint_id`/`provenance` (§25) - e.g. `"ring sample 3/16 at
1.2 m from sofa's object id"` - so a caller can always answer "why does this
candidate exist" without re-deriving it from the geometry alone.

## 7. §43: no benchmark cheating, checked against this phase's own changes

- **FACES tolerance** was NOT weakened - it is the same 60-degree threshold
  production already used before P9 (§1).
- **NEAR was NOT redefined after seeing results** - `DEFAULT_DISTANCE_
  TOLERANCE_M = 0.3` is P8's own unchanged constant; this phase measures
  against it, never adjusts it to make a case pass.
- **No hard constraint was removed** - `validate_object` (production) is
  called unmodified inside `candidate_filters.is_feasible`, with zero
  changes to its checks.
- **No failed constraint was discarded** - the brief demo's second NEAR
  constraint (`chair_2`) remains reported as `VIOLATED` after regeneration
  finds no feasible candidate, exactly as measured, not hidden or converted
  to `UNKNOWN`/`SATISFIED`.
- **No benchmark scene was altered** - the brief-demo scenario (room, wall,
  five items, four intents) is byte-identical to P8's own; only the code
  processing it changed.
- **No solver ordering was changed to rescue one case** - `_ordered()`
  (production) is untouched; the fix routes MORE information (a real
  `.relation`) into the ALREADY-EXISTING ordering rule, it does not special-
  case the brief-demo scenario.
- **UNKNOWN was never converted to SATISFIED** - `near_no_distance`-style
  UNKNOWN verdicts (inherited unchanged from P8) remain UNKNOWN in every P9
  scenario that produces one.

## 8. Known, honestly-reported limitation: "tilted wall" (§4/§16 of the P9 brief)

`Scene.Wall` (production) carries no 3D-tilt field - P5's `TiltedWall` is a
separate research representation `place_objects`/`validate_object` never
consume (unchanged fact from P5/P6/P7/P8). This phase's closest honest
analogue is a non-axis-aligned (diagonal) wall SEGMENT in the XZ plane
(the `faces_tv_diagonal_wall` adversarial scenario), which exercises the
ORIENTATION evaluator alongside a genuinely non-cardinal wall - not the 3D
lean P5 modelled. Named here rather than silently substituted for the real
thing.

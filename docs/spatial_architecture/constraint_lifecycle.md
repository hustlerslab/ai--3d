# P8 — Constraint lifecycle: staleness, repair integration, explanation, and invariants

Continues `intent_to_solver.md`. Closes the loop: what happens to a
constraint after the solver (and, if needed, P4's repair) has run.

## 1. The lifecycle, concretely

```
CREATED       Intent exists, not yet compiled
NORMALIZED    (folded into COMPILED - see §2 for why no separate step was built)
COMPILED      Constraint exists, `constraint_compiler.compile_intents` has run
REPAIRED      a caller invoked P4's repair_scene since this constraint was last evaluated
RE_EVALUATED  a caller invoked evaluate_all() again since a REPAIRED (or any) transition
```

Every stage is `ConstraintStatus`, a lifecycle enum. It is INDEPENDENT of
`Verdict` (SATISFIED/VIOLATED/UNKNOWN/PARTIAL), which lives on the separate
`ConstraintResult` returned by `evaluate()`. See `constraint_model.py`'s own
module docstring for why these are two enums, not one - collapsing "where is
this object in its own processing" with "what did the most recent check
find" is exactly the ambiguity P7's `RelationStatus` already avoided for
relations (CONTRADICTED and UNRESOLVED are different questions there too).

## 2. Why `NORMALIZED` has no distinct implementation

§27 lists `NORMALIZED` as its own stage between CREATED and COMPILED. In
this implementation, normalisation (resolving a predicate to its
`ConstraintType`, copying parameters, attaching provenance) happens
INSIDE `_compile_one` as one atomic step - there is no intermediate object a
caller could observe as "normalized but not yet compiled." Splitting it into
two visibly different stages was considered and rejected: no caller in this
phase, or plausibly a near-future one, needs to inspect a constraint between
those two moments, and adding a second object shape for a state nothing
reads would be exactly the "field/stage with no consumer" §9's discipline
warns against, applied to a lifecycle stage instead of a field.

## 3. Staleness (§26), extending P7's own precedent

P7 found and fixed a real bug: `resolve_collisions`/`repair_scene` consume
wall-contact relations but never re-check them after moving the object
(`scene_graph.recompute_relations`). P8 extends the SAME discipline to
constraints: a `Constraint`'s most recent `ConstraintResult` is only ever
as fresh as the last `evaluate()` call. There is no automatic re-evaluation
triggered by a `SceneObject` write (deliberately - see below); a caller that
wants a fresh answer calls `evaluate_all` again, explicitly, exactly as a
caller of P7's layer calls `recompute_relations` again explicitly.

Verified directly: the `stale_constraint` adversarial scenario builds a
constraint, evaluates it SATISFIED, moves the subject, and confirms a
second `evaluate_all` call reports VIOLATED - the verdict tracks the
CURRENT scene, never a cached answer.

**Why no automatic re-evaluation hook was added to `Scene`.** `Scene` stays
a plain pydantic model with no observer/signal machinery - adding one was
considered and rejected for the same reason P7 rejected it for relations:
every existing P1-P6 write site would need to change (or be silently
unaware of a new side effect), for a guarantee an explicit, opt-in
`evaluate_all` call already provides to any caller that wants it. The named
cost is honest: a caller that forgets to re-evaluate after a repair sees a
stale `ConstraintResult` from before the move. The benefit is that P1-P6's
frozen call sites need zero changes.

## 4. §40: repair integration, verified with a REAL `repair_scene` call

`post_repair_reevaluation` (one of the 30 adversarial scenarios) calls P4's
actual `repair_scene` (unmodified) and re-evaluates afterwards:

```
terminal_state:  ALREADY_VALID     (a real repair_scene return value)
before:          satisfied
after:           satisfied         (re-evaluated on repair_scene's own returned scene)
```

This exercises the well-defined `TerminalState.ALREADY_VALID` passthrough
contract with a genuine call, rather than only a simulated object move
(`stale_constraint`, §3 above, covers the case where geometry actually
changes). Together the two scenarios cover both halves of §40's mandate: "a
failed constraint MAY trigger P4" (not built automatically - see below) and
"after repair, constraints MUST be re-evaluated" (verified against a live
call).

**Why constraint-triggered repair was not built.** §40 says a failed
constraint MAY trigger P4's repair - not MUST. No current caller in this
phase needs a SOFT constraint violation to trigger P4 (P4 already triggers
on its own HARD-violation detection, `collect_hard_failures`, which reads
`validate_scene`'s output, never a `Constraint`). Wiring a soft preference
into P4's trigger condition would blur exactly the hard/soft line
`constraint_contract.md` §3 draws, and no evidence in this phase's own
benchmark (the brief demo, §5 of `intent_to_solver.md`) suggests P4 should
ever run because an ORIENTATION preference went unmet - the scene stayed
hard-valid throughout. This is left as a documented, deliberate
non-feature, not an oversight.

## 5. §39: constraint explanation, worked example

Every `ConstraintResult` + its `Constraint` answers all five of §39's
questions without extra machinery:

```
WHAT:          FACES(sofa, tv_unit)                    -- Constraint.constraint_type + subject/target
WHY VIOLATED:  angular error 100.1 deg (tolerance 60.0 deg)   -- ConstraintResult.message
SOURCE:        USER_ASSERTED, priority=0                -- Constraint.priority + the Intent it traces to
GEOMETRY:      sofa at (x, 0, z), rotation_y=...         -- read directly off SpatialScene.scene
REMEDIATION:   none attempted here (P4 is not auto-triggered - §4) - a
               caller could re-run place_objects with a stronger candidate
               bias, or accept the deviation and report it to the user
```

No vague diagnostic strings anywhere in `constraint_evaluator.py` - every
`message` names the actual measured quantity and the tolerance it was
compared against.

## 6. Property invariants (§50), and where each is enforced

| Invariant | Enforced by |
|---|---|
| Evidence immutability | `compile_intents`/`evaluate_all` never touch `spatial_scene.scene` or `.relations` - `test_compile_intents_never_mutates_the_scene`, `test_evaluate_all_never_mutates_the_scene` |
| Intent preservation | The solver (`place_objects`) never reads `Intent`/`Constraint` at all - only the plan-item fields the bridge fills; nothing can "rewrite" an intent because nothing downstream of it can see it |
| Geometry authority | Every geometric evaluator reads `SceneObject`/`Wall`/`Room` fields directly, never a cached or asserted value |
| Provenance | `Constraint.provenance`/`source_intent_id` chain to a real `Intent`, never empty |
| Frame safety | Constraints operate entirely in plan-view (XZ), matching P6's canonical ROOM frame - camera-frame predicates (`LEFT_OF` etc.) are never mapped to a `ConstraintType` at all (`camera_frame_predicate_unsupported`) |
| Identity | Two same-category objects (`duplicate_object_labels`, `shared_asset_distinct_constraints`) always produce distinct `constraint_id`s and independent results |
| Validation purity | `evaluate`/`evaluate_all` are read-only - see §5 above |
| Solver authority | Only `place_objects`/`repair_scene` (both unmodified) ever write `SceneObject.position`/`.rotation_y` |
| Freshness | §3/§4 above |
| Determinism | `constraint_id`/`intent_id` are sha1-based; 20-repeat check in `tests/test_constraint_determinism.py` and `constraint_benchmark.determinism_check` |

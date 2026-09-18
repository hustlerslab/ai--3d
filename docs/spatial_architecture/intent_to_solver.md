# P8 — Intent to solver: the bridge, provenance, and the two end-to-end demos

Continues `constraint_contract.md`. Covers how a `Constraint` reaches the
EXISTING solver without a second placement engine, full traceability, and
the two required demonstrations.

## 1. The full chain

```
SpatialScene (P7)  +  Intent[] (this phase)
        |
        v
constraint_compiler.compile_intents()      -- pure function, never places anything
        |
        v
ConstraintSet (constraints, unsupported, conflicts)
        |
        v
constraint_compiler.apply_constraints_to_plan()   -- §31's bridge
        |  fills ObjectPlanItem.relation / .support_key / .faces
        |  (the SAME fields app/planning/compiler.py already reads)
        v
app.planning.compiler.place_objects()      -- EXISTING SOLVER, UNMODIFIED
        |
        v
Scene (placement decisions)
        |
        v
app.spatial.validation.validate_scene()    -- EXISTING VALIDATOR, UNMODIFIED
        |
        v
constraint_evaluator.evaluate_all()        -- RE-EVALUATE against the FINAL scene
```

There is exactly one placement authority in this chain: `place_objects`.
Nothing in this phase moves an object, computes a final position, or
second-guesses a placement `validate_object` already accepted (§32 - no
second solver, checked explicitly against this exact temptation because it
is the single most likely way an intent/constraint phase silently becomes
one).

## 2. §31: how a constraint narrows the EXISTING candidate generator

`apply_constraints_to_plan` fills three fields on `ObjectPlanItem` the
compiler already consumes, per constraint type:

| `ConstraintType` | Field filled | Compiler mechanism it feeds |
|---|---|---|
| `ORIENTATION` | `.faces` | `_faces_rank` (reorders candidates that already point at the target first) |
| `SUPPORT` | `.support_key` | `_pick_support` (tries the named support before searching) |
| `CONTACT` | `.relation = ObjectRelation("against_wall")` | the default wall-aligned candidate path |
| `DISTANCE`, `POSITION` | `.relation = ObjectRelation("beside", ...)` | `_relation_candidates` - an APPROXIMATION, see §3 |

This runs BEFORE `place_objects` - the plan items have no placed geometry
yet, so the bridge resolves a constraint's target among the PLAN ITEMS (by
`object_key`), never `spatial_scene.scene` (which is still empty at this
point in the pipeline). `apply_constraints_to_plan` never overwrites a field
the caller already set, mirroring `apply_spatial_graph`'s identical rule one
stage upstream in the moodboard path.

## 3. The one honestly-named limitation

Production's `RelationType` (`in_front_of, beside, under, around, facing,
against_wall`) has no "between" or "centered" value. `POSITION`-type
constraints (BETWEEN, CENTERED_IN_ROOM) can be fully EVALUATED against the
final placed scene, but cannot bias candidate generation through this
bridge without adding a new `RelationType` to production - out of this
phase's minimal-footprint scope (§53: smallest possible change to `app/`,
and no such change was necessary to deliver the phase's actual goal). They
are approximated as `beside` the nearer target, and the approximation is
recorded in the bridge's own returned notes so nothing is silently
pretended to be a real BETWEEN placement bias. The brief demo below shows
this limitation's real, measured consequence rather than hiding it.

## 4. §13: provenance, worked example

Every constraint in this phase can answer "why did the solver try to put
the sofa there?" by chaining three fields, none synthesised after the fact:

```
Constraint.constraint_id     = constraint_9e206b5c0082c1e3
Constraint.source_intent_id  = intent_...          (the Intent it came from)
Constraint.provenance        = "intent_...: (user brief: 'accent chairs near the sofa')"
```

`Intent.provenance` in turn carries the ORIGINAL text/reason a caller
supplied (a user's sentence, a model's own claim) - the chain terminates in
human-readable text, not an opaque id, at every hop.

## 5. §57: end-to-end BRIEF demonstration (`constraint_benchmark.
brief_end_to_end_demo`)

Input: *"Create a living room with a three-seater sofa facing the TV, a
coffee table between them, and two accent chairs near the sofa."*

Traced exactly per §57's required stages; a real run's measured output
(object ids vary run to run only in the random-object-id sense already true
of production's own `place_objects` today, never the geometry/verdicts):

| Stage | What happened |
|---|---|
| USER TEXT | the sentence above |
| INTENT | 4 `Intent`s: `sofa FACES tv_unit` (USER_EXPLICIT), `coffee_table BETWEEN (sofa, tv_unit)`, `chair_1/chair_2 NEAR sofa, distance_m=1.2` |
| ENTITY RESOLUTION | 5 `ObjectPlanItem`s (`sofa, tv_unit, coffee_table, chair_1, chair_2`) |
| RELATIONS -> CONSTRAINTS | `compile_intents` -> 4 constraints, 0 unsupported, 0 conflicts |
| CANDIDATE GENERATION | `apply_constraints_to_plan` sets `sofa.faces="tv unit"`, `coffee_table/chair_1/chair_2.relation=beside(sofa)` (the §3 approximation) |
| EXISTING SOLVER | `place_objects` (unmodified) - 5/5 objects placed, 0 solver warnings |
| VALIDATION | `validate_scene` - **0 hard violations** |
| CONSTRAINT RE-EVALUATION (post-solve) | `sofa FACES tv_unit`: **VIOLATED**, 100.1 deg error; `coffee_table BETWEEN`: **SATISFIED**, 0.295 m lateral offset; `chair_1/chair_2 NEAR sofa`: **VIOLATED**, actual 1.53 m / 2.66 m vs. requested 1.2 m |

**This is reported exactly as measured, per §60's "no benchmark cheating"
rule** - the scene is hard-valid (0 violations) but does not fully satisfy
the user's stated intent, and the reason is traceable to §3's own named
limitation: `_relation_candidates("beside", ...)` orders candidates by
proximity to the target but does not specifically optimise a facing
direction or a tight distance band the way a dedicated "facing"/"near"
placement strategy would. This is a genuine, now-VISIBLE limitation of the
EXISTING solver's candidate vocabulary - not a regression this phase
introduced, and not a limitation this phase is authorised to fix by adding
new solver behaviour (§32). It is exactly the kind of finding this
architecture exists to surface: before this phase, no automated check could
have told a caller that the placed scene did not actually achieve "facing
the TV" - `validate_scene` has no opinion on orientation intent at all.

## 6. §58: end-to-end PHOTO demonstration (`constraint_benchmark.
photo_end_to_end_demo`)

Uses a synthetic grounding result in the exact shape P7's photo bridge
(`scene_from_photo.BridgeResult`) produces - no GPU/model call, matching how
P7's own `build_demonstration_scene` exercised its layer. A model hypothesis
("the mirror is against the wall," `MODEL_INFERRED`) is compiled and
evaluated independently of P7's own geometry-sourced `AGAINST_WALL`
relation on the SAME object:

```
p7_relation_status:    derived        (P7's own bridge-built relation)
p7_relation_kind:      derived_geometry
p8_constraint_verdict: satisfied      (this phase's independent check)
p8_constraint_error_m: 0.125
```

They AGREE here because the synthetic scene was built consistently - but
they are never merged into one object (§37's requirement): a future case
where a VLM's claim and the measured geometry disagree would show up as two
different, individually-inspectable results, exactly like P7's own
`stated_hint_vs_measured_geometry_disagree` scenario demonstrates for
relations one layer down.

## 7. Regression

`app/planning/compiler.py` and `app/spatial/validation.py` are read-only
imports from this phase's code (`place_objects`, `validate_scene`) -
confirmed unmodified by `git status --short` (see `decisions.md`'s P8
entry, "Files Changed"). The brief demo's `place_objects` call is the exact
same production function every brief-path project in Allure calls today.

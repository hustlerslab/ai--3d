# P9 — Relation to candidate generation: the full pipeline, and measured results

Continues `candidate_contract.md`. Shows the complete
`Constraint -> Candidate Generator -> Candidate Filter -> Candidate Ranker
-> Existing Solver` chain, the multi-constraint case, and every number this
phase measured.

## 1. The pipeline

```
Constraint (P8, unchanged)
    |
    v
constraint_compiler.apply_constraints_to_plan()   -- ORIENTATION/CONTACT/SUPPORT:
    |                                                 fills ObjectPlanItem.relation/.support_key
    |                                                 (§8's fix - zero new candidates)
    v
app.planning.compiler.place_objects()             -- EXISTING SOLVER, UNMODIFIED
    |
    v
Scene (first placement)
    |
    v
constraint_evaluator.evaluate_all()               -- P8, unchanged: independent, read-only check
    |
    v  (only for DISTANCE/POSITION constraints NOT already SATISFIED)
candidate_generators.regenerate_after_placement()
    |   1. remove the subject from a scene COPY
    |   2. distance_candidates() / between_candidates()   -- NEW, this phase
    |   3. candidate_filters.filter_feasible()             -- validate_object, reused
    |   4. candidate_ranker.rank_by_ideal_distance/between  -- deterministic
    |   5. return the best pose, or None
    v
Scene (final, after regeneration)
    |
    v
constraint_evaluator.evaluate_all()               -- re-run, authoritative
```

Two different mechanisms fix the two different root causes, and neither
introduces a second solver: ORIENTATION is fixed by giving `place_objects`'s
OWN existing machinery the input it was always able to use; DISTANCE/
POSITION are fixed by a small, explicit, opt-in regeneration step shaped
exactly like P4's own `_try_nudge` (remove, generate, validate, pick, re-add).

## 2. §21: existing solver compatibility, unchanged

`app/planning/compiler.py::place_objects` is imported and called, never
edited. `app/spatial/validation.py::validate_object`/`validate_scene` are
imported and called, never edited. P1's `resolve_collisions`, P3's solver
comparison, P4's `repair_scene` are untouched and not invoked by this
phase's own pipeline (the brief demo does not need collision resolution or
repair - `place_objects` already produces a hard-valid scene by
construction, exactly as it did before P9).

## 3. §16: the multi-constraint case, on the real brief demo

The sofa in `constraint_benchmark.brief_end_to_end_demo` carries an
ORIENTATION constraint (facing the TV) that also participates in
`_ordered()`'s dependency graph; the room additionally constrains every
object to stay inside its boundary and collision-free (`validate_object`,
always active, never bypassed). Measured result: **FACES satisfied (0.0
degrees), 0 hard violations, 5/5 objects placed** - the intersection §16
describes (`wall/orientation/room-bounds/collision-free`) is exactly what
`place_objects`'s existing per-candidate validation loop already computes;
this phase adds no new intersection logic, because none was missing for
this case.

A second multi-constraint scenario, `against_wall_plus_faces` (this
phase's adversarial suite), places a sofa that must simultaneously satisfy
`AGAINST_WALL` and `FACES` a specific TV position - both `SATISFIED`
together, confirming the two constraint types can be evaluated jointly
without interference (each constraint's evaluator reads only the fields it
needs; neither writes anything).

## 4. §15: wall-anchored + facing, integrated

`wall_local_orientation_near_wall` (adversarial scenario) confirms a sofa
placed against a wall and required to face a TV evaluates both
`CONTACT` and `ORIENTATION` as `SATISFIED` from the SAME geometry - the
CONTACT evaluator reuses P7's exact wall-distance formula
(`AGAINST_WALL_TOLERANCE_M`), the ORIENTATION evaluator reuses the
compiler's own facing-cone definition (§1 of `candidate_contract.md`);
neither needed new wall-awareness beyond what P5/P6/P7 already established.

## 5. §23: candidate budget, measured

| n (objects) | total time | mean per object |
|--:|--:|--:|
| 5 | 6.8 ms | 1.37 ms |
| 10 | 12.4 ms | 1.24 ms |
| 20 | 36.6 ms | 1.83 ms |

Each object's regeneration (16-point ring, or up to 35-point between-grid,
each filtered through one `validate_object` call and ranked) costs low
single-digit milliseconds even at n=20 - candidate growth is linear in the
number of DISTANCE/POSITION constraints needing regeneration, not the
scene's total object count, and stays orders of magnitude below the
MoGe/SAM2/Blender costs this pipeline already pays elsewhere (P1's own
prior finding, unchanged: candidate generation is not the bottleneck at
any measured scale).

## 6. Results: photo/brief/Blender, vs. the frozen P8 control

- **Brief demo** (the primary benchmark, §35): FACES 100.1 deg -> **0.0
  deg**; BETWEEN 0.295 m lateral (already satisfied, now 0.000 m exact);
  NEAR: 1 of 2 chairs now exactly satisfied (1.20 m), the second remains
  genuinely infeasible at the requested tolerance given the final room
  layout after all other placements - reported honestly as `VIOLATED`, not
  forced or hidden (§43).
- **21-image photo benchmark**: re-run, byte-identical to the P8 baseline
  (20/21 valid/success, hard violations `{COLLIDES_OBJECT:2, COLLIDES_
  WALL:1}` pre-resolution, resolver moves 13/unresolved 1, P4 repair
  `hard 3 -> 3`, terminal states `{ALREADY_VALID:20, UNREPAIRABLE:1}`) -
  this phase's changes do not touch the photo pipeline's own code path
  (`scene_from_photo.py` builds `ObjectPlanItem`-free `Scene`s directly,
  never through `place_objects`'s plan-item bridge).
- **12-scene brief-path benchmark** (`scene_validity_benchmark.py`):
  re-run, byte-identical (12/12 valid, 547/559 placed, 7/12 fully placed) -
  this benchmark's `MockProvider`-driven scenes carry no `.relation`/
  `.faces` hints, so the P9 wiring change has nothing to act on there.
- **Blender e2e**: re-run, byte-identical (12/12 built, 0 errors, 91.8%
  dims ok, XY error median 0.000 m / p95 0.015 m).
- **Full test suite**: 654 passed (581 P8 baseline + 73 new), 7 skipped, 30
  xfailed - identical skip/xfail counts to P8.
- **Determinism**: 20 repeated full-pipeline runs (`candidate_benchmark.
  determinism_check`) produce byte-identical verdicts/messages/regeneration
  outcomes - compared by CONTENT rather than `place_objects`'s own
  pre-existing random `object_id` (see that function's docstring for why
  the dict KEYS legitimately vary while every VALUE does not).
- **Adversarial**: 40/40 named scenarios pass.

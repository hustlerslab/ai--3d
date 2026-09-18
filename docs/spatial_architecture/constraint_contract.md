# P8 — Constraint contract

Continues `intent_model.md`. Covers the `Constraint` type, the ten-category
taxonomy, the hard/soft policy, and every relation-to-constraint mapping
this phase actually built - implemented in `research/spatial_architecture/
constraint_model.py`, `constraint_compiler.py`, `constraint_evaluator.py`.

## 1. The canonical constraint object

```
Constraint(
    constraint_id,       # deterministic sha1, like P7's relation_id / this phase's intent_id
    constraint_type,     # one of ten named categories - see §2
    subject_id, target_id,
    parameters,          # e.g. {"tolerance_deg": 60}, {"distance_m": 1.5}
    source_intent_id, provenance,
    priority,            # IntentPriority value - deterministic precedence, never a score
    hardness,            # HARD | SOFT - see §3
    confidence,
    status,              # lifecycle stage - see constraint_lifecycle.md
)
```

Every field answers one of §9's own questions: what/relative-to-what
(subject_id/target_id), what condition (type+parameters), where from
(source_intent_id/provenance), how important (priority), can it fail the
scene (hardness), how sure (confidence), where in its life (status). No
field was added without a consumer that reads it.

## 2. Ten categories, seven built

| `ConstraintType` | Built? | Predicate(s) | Evaluator |
|---|:-:|---|---|
| `ORIENTATION` | Yes | FACES | angular error vs. target direction |
| `DISTANCE` | Yes | NEAR (with an explicit number), user-explicit distance | \|actual - requested\| |
| `CONTACT` | Yes | AGAINST_WALL | distance to wall segment (reuses P7's own tolerance) |
| `SUPPORT` | Yes | SUPPORTED_BY, ON_TOP_OF | parent_id match + vertical gap |
| `CONTAINMENT` | Yes | INSIDE, CONTAINS | point-in-polygon |
| `CLEARANCE` | Yes | CLEAR_OF | wraps P2's `pairwise_clearance_violations` |
| `POSITION` | Yes | BETWEEN, CENTERED_IN_ROOM | segment projection / centroid distance |
| `ALIGNMENT` | No | - | no current downstream consumer (§22) |
| `RELATION` | No | - | a generic bucket with no distinct evaluator to justify |
| `CIRCULATION` | No | - | P2's `circulation_violations` already validates this on `Scene` directly (§41: do not duplicate) |

The three unbuilt categories are named, not omitted, so a future predicate
has a home without a breaking enum change - the identical pattern P7 used
for `GEOMETRIC_INVARIANT`/`FUNCTIONAL`.

## 3. Hard vs. soft: Allure's actual policy, researched and documented

**Every constraint this phase compiles is SOFT.** This was not assumed - it
follows from a concrete fact found in this phase's own audit of
`app/planning/compiler.py::place_objects`: the existing solver has exactly
ONE mechanism for consuming a relation-derived preference today -
`_relation_candidates` (which candidates get generated) and `_prefer_hint`/
`_hint_rank`/`_faces_rank` (which of the ALREADY-VALID candidates sorts
first). Neither mechanism can REJECT a scene; both only reorder a candidate
list that `validate_object` has already screened for hard validity.
Claiming `HARD` on a constraint this architecture cannot enforce would be
reporting a guarantee that does not exist - so every `Constraint`
constructed by `constraint_compiler.compile_intents` gets
`Hardness.SOFT`, unconditionally, regardless of `IntentSource`.

Allure's REAL hard constraints - collision-free, inside the room, no wall
penetration, door accessibility - remain exactly where they were before
this phase: `app.spatial.validation.validate_object`/`validate_scene`,
completely untouched. §14's own example list (collision, room-bounds, door
clearance) is Allure's hard set; the intent/constraint layer this phase adds
governs everything else, and only as preference.

**User precedence is expressed through `priority`, not through a false
`hardness`.** A `USER_ASSERTED` constraint is still `SOFT` (§34's
requirement that soft preferences never override hard geometry holds
trivially, since nothing here is HARD), but it carries
`IntentPriority.USER_EXPLICIT` (value 0, the highest-precedence integer) -
so when two constraints conflict (§13/§35), sorting by `priority` always
puts the user's own request first, deterministically, with no numeric
weighting. This is the "engineering precedence contract, not an
optimization opinion" §12 asks for.

## 4. Relation -> constraint mapping (§14), exactly as built

```
AGAINST_WALL      -> CONTACT       (§16)
FACES             -> ORIENTATION   (§15)
NEAR              -> DISTANCE      (§19)
BETWEEN           -> POSITION      (§20)
CENTERED_IN_ROOM  -> POSITION      (§21, room case only)
SUPPORTED_BY      -> SUPPORT       (§17)
ON_TOP_OF         -> SUPPORT       (§17)
INSIDE            -> CONTAINMENT   (§18)
CONTAINS          -> CONTAINMENT   (§18, mirror direction)
CLEAR_OF          -> CLEARANCE     (§14)
```

Anything else (`GROUPED_WITH`, `LEFT_OF`/`RIGHT_OF`/`ABOVE`/`BELOW`
(camera-frame - never geometric, §25/§41), `CENTERED_ON_WALL`,
`CENTERED_BETWEEN_OBJECTS`, `CENTERED_IN_OPENING`, `ALIGNED_WITH`) is
recorded in `ConstraintSet.unsupported` - kept, never silently dropped
(§14's "do not allow arbitrary text to become constraints" cuts both ways).

## 5. Per-predicate notes

**§15 FACES.** The compiler's own `_faces_rank`/`_points_at` already only
answer "does this candidate rotation point at the target" as a boolean, at
90-degree candidate granularity (wall-normal-aligned candidates). This
phase's `ORIENTATION` evaluator computes the actual angular error in
degrees, reusing the SAME "points at" tolerance the solver already uses
(`_FACES_COS = 0.5`, i.e. 60 degrees - `DEFAULT_ORIENTATION_TOLERANCE_DEG`
in `constraint_evaluator.py`), so the solver and the evaluator never
silently disagree about what counts as "facing." The evaluator NEVER
computes a yaw and hands it to anything - it only measures, after the fact,
whether the solver's OWN chosen yaw satisfies the requirement.

**§16 AGAINST_WALL.** Reuses, verbatim, P7's own distance-to-wall-segment
check and its exact tolerance constant (`scene_graph.
AGAINST_WALL_TOLERANCE_M = 0.25`) - not a second, independently-tuned
wall-contact rule. `Scene.Wall` carries no 3D-tilt field (P5's `TiltedWall`
is a separate research representation `place_objects`/`validate_object`
never consume), so this evaluator - like production itself - only knows
plan-view (XZ) wall geometry; a non-axis-aligned (diagonal) wall segment is
exercised in the adversarial suite (`against_wall_diagonal_wall`) as the
closest honest analogue to "tilted," and the limitation is named here
rather than silently assumed away.

**§17 SUPPORTED_BY vs. AGAINST_WALL vs. CONTACTS vs. ON_FLOOR.**
`AGAINST_WALL` (subject vs. a wall) and `SUPPORTED_BY` (subject vs. another
object or the room/floor) were already distinct in production's own
`SpatialPredicate` enum and in P7's classification - nothing needed adding.
`CONTACTS` and `ON_FLOOR` were considered and **not added**: `ON_FLOOR`
would be strictly redundant with `SUPPORTED_BY` targeting the room (already
producible), and `CONTACTS` would be a strictly weaker version of
`AGAINST_WALL`/`SUPPORTED_BY` with no measured evidence source anywhere in
this program. `SUPPORTED_BY`'s evaluator never infers mechanical attachment
from proximity (§17's own warning) - it checks `SceneObject.parent_id`, the
field the compiler's own `_pick_support` already sets, never a distance
heuristic.

**§18 INSIDE/CONTAINS.** Directional: `INSIDE(subject, target)` = subject's
position inside target's polygon; `CONTAINS(subject, target)` = the mirror
(target's position inside subject's polygon). Both compile to the SAME
`ConstraintType.CONTAINMENT`, disambiguated at evaluation time by the
original predicate string (kept in `parameters["_predicate"]`, since
`ConstraintType` alone cannot distinguish direction). Uses
`app.spatial.geometry.point_inside_polygon` against the room's OWN boundary
or the target object's OWN footprint (`app.spatial.validation.
object_footprint`) - never a semantic override of the actual boundary.

**§19 NEAR.** No metric default exists anywhere in this program for a bare
"near" (production's `NEAR_DISTANCE = 0.25` in `app/planning/
spatial_graph.py` is a fraction of an IMAGE, not a metre distance - reusing
it would be exactly the fabricated precision §19 forbids). A bare NEAR with
no explicit `distance_m` parameter evaluates to `UNKNOWN`, honestly. Only
when an intent supplies a real number does this become a `DISTANCE`
constraint with a real numeric error.

**§20 BETWEEN.** Segment projection: the UNCLAMPED parametric position along
the (target_a, target_b) segment decides whether the subject is even ON the
segment (§20's "order along an axis"); `app.spatial.geometry.
point_segment_distance` gives the perpendicular (lateral) offset. Three
verdicts, not two: `SATISFIED` (on the segment, within lateral tolerance),
`PARTIAL` (on the segment, but off-axis beyond tolerance - a real,
distinguishable outcome `Verdict.PARTIAL` exists specifically for), and
`VIOLATED` (beyond either endpoint). Verified stable under sofa/TV rotation
and differing sizes by construction - the projection formula does not
reference either object's own rotation or dimensions, only their positions.

**§21 CENTERED.** Only `CENTERED_IN_ROOM` is built - distance from the
subject to `polygon_centroid(room.boundary)`, the exact function production
already uses for rug placement (`app/planning/compiler.py`'s own
`_floor_candidates`). `CENTERED_ON_WALL`, `CENTERED_BETWEEN_OBJECTS`, and
`CENTERED_IN_OPENING` are recorded as `unsupported` (see the adversarial
scenario `centered_on_wall_unsupported`) rather than force-mapped onto ROOM
semantics that would silently misrepresent the request - four different
geometric definitions were never going to collapse into "one vague CENTERED
constraint" (§21's own warning), and only one had both a real evidence
source and a real production precedent to build against.

## 6. Verdict, error, and the "never a bare boolean" rule (§24)

Every geometric evaluator returns a numeric `error` with a named
`error_kind` (`angular_deg`, `distance_m`, `clearance_deficit_m`) wherever
one is measurable - `Verdict` alone is never the whole story, matching §39's
explanation requirement (see `constraint_lifecycle.md`'s worked example).

## 7. Read-only, always

No evaluator function anywhere in `constraint_evaluator.py` writes to
`spatial_scene.scene` or `spatial_scene.relations` - verified by
`test_constraint_evaluator.test_evaluate_all_never_mutates_the_scene` and,
separately, `test_constraint_compiler.test_compile_intents_never_mutates_
the_scene`.

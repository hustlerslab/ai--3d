# P7 — Relation contract: taxonomy, provenance, and the contradiction model

See `scene_model.md` for the audit and architecture decision this operates
inside. Implemented in `research/spatial_architecture/relation_model.py`.

## 1. Six categories

| `RelationKind` | Meaning | Example predicates | Re-verifiable? |
|---|---|---|---|
| `GEOMETRIC_INVARIANT` | True by construction of the geometry itself | (none reified as a relation - `Scene`'s own fields already carry these; see §2) | N/A |
| `DERIVED_GEOMETRY` | Computed FROM current geometry; stops being true if the geometry changes | `AGAINST_WALL`, `SUPPORTED_BY`, `ON_TOP_OF`, `NEAR`, `ADJACENT_TO`, `OVERLAPS`, `ABOVE`/`BELOW`/`LEFT_OF`/`RIGHT_OF`, `CONTAINS`/`INSIDE` | Yes, when a verifier exists (today: `AGAINST_WALL` only - §3) |
| `SEMANTIC_HYPOTHESIS` | A meaning claim, not itself a geometric fact | `FACES`, `FACES_ROOM`, `GROUPED_WITH` | Only by corroboration, never by direct measurement |
| `FUNCTIONAL` | A usability claim about a pair (P2's clearance domain) | reserved - P2's `ClearanceViolation` is negative-only today (§2) | N/A yet |
| `SOLVER_CONSTRAINT` | A placement DECISION the solver recorded, not evidence about the world | P4's `RepairRecord` (not re-modelled as a `GeometricRelation` - a different, already-working type) | N/A - this is an action record, not a claim to re-verify |
| `EVIDENCE_CLAIM` | A raw, unverified perception claim | any `DERIVED_GEOMETRY`-eligible predicate produced at `source="semantic"` (a stated hint, not yet checked) | Same verifier as its `DERIVED_GEOMETRY` counterpart - see §3 |

**Classification is by `(predicate, source)`, not by predicate alone**
(`classify()`): the SAME predicate can be a raw claim or a geometric fact
depending on how it was produced. Production's own `_merge` function
(`app/planning/spatial_graph.py`) already tracks exactly this distinction via
`SpatialRelation.source` one stage upstream (a semantic claim vs. one
geometry corroborated) - `classify()` reuses that signal rather than
re-deriving a second one. `source="placement"` counts as geometry-grounded:
production emits `SUPPORTED_BY`/`ON_TOP_OF` at this source when the reader
recorded an item as physically resting on something, which is a claim about
where the object already sits, not a stated preference.

## 2. Why `GEOMETRIC_INVARIANT` and `FUNCTIONAL` are named but not populated

Both categories are complete in the enum (so a future relation of either kind
has a home without a breaking enum change) but neither is populated by any
constructor today:

- **`GEOMETRIC_INVARIANT`** would model something like "this wall's own
  start/end" as a relation - but `Wall.start`/`Wall.end` already ARE that
  fact, directly, on the `Wall` object. Wrapping it as a second relation
  would create exactly the "two owners of one fact" problem `scene_model.md`
  §3 rejects candidates B/E for. No constructor populates it because no
  measured consumer needs the geometry expressed twice.
- **`FUNCTIONAL`** is P2's clearance domain (`clearance_engine.py`) - but P2
  emits `ClearanceViolation` (a NEGATIVE finding: "these two are too close"),
  never a positive "these two have adequate clearance" relation. Reifying the
  positive case as a `GeometricRelation` was considered and rejected here:
  P2 was designed, tested, and benchmarked as a validator, and wrapping its
  absence-of-violation as a relation would be inventing a use for data P2
  was never asked to produce, for no consumer that exists yet.

## 3. Directionality and re-verification

Every `GeometricRelation` is directional (`subject_id -> predicate ->
object_id`), matching `SpatialRelation`'s own shape exactly - no relation in
this program is modelled as symmetric by default, even where the underlying
fact often is (`ADJACENT_TO`, `NEAR`): the subject is whichever side the
relation was BUILT from, and a consumer that needs the inverse looks it up
via `SpatialScene.relations_for(entity_id)` rather than the model inventing
a second, reversed copy.

`CONTAINS`/`INSIDE` are the one pair with a NAMED inverse
(`INVERSE_PREDICATES`), used only by the circular-containment consistency
check (§4) - not a general inference engine. Building a general "if A relates
to B then B inverse-relates to A" rule for every predicate was considered and
rejected: no measured consumer needs it, and it would silently double the
relation count of every scene for no benefit.

**Only `AGAINST_WALL` has a geometric verifier today**
(`scene_graph._VERIFIABLE_PREDICATES`): a cheap, already-tested distance
check (`app.spatial.geometry.point_segment_distance`) against the wall
segment, gated by `AGAINST_WALL_TOLERANCE_M = 0.25` (documented in
`scene_graph.py`, sized against P1's 0.1 m nudge step and P4's measured
0.1-0.4 m repair moves). `SUPPORTED_BY`/`NEAR`/etc. have no verifier built:
extending `_VERIFIABLE_PREDICATES` needs its own geometric test (a support-
contact check, a pairwise-distance threshold) that no phase has built or
measured yet - added when one is, not spun up speculatively here. Until then,
those relations are marked `STALE` (not silently trusted) once their subject
moves - see `scene_state_lifecycle.md` §3.

## 4. The contradiction model

`RelationStatus` - deterministic, set by a rule, never sampled or scored:

| Status | Meaning | Set by |
|---|---|---|
| `SUPPORTED` | Geometry was checked against the claim and agrees | `recompute_relations`, for a `_VERIFIABLE_PREDICATES` relation found true |
| `CONTRADICTED` | Geometry was checked and disagrees, OR the relation is orphaned | `recompute_relations` |
| `UNRESOLVED` | No check has run yet (fresh construction; default) | `GeometricRelation` constructors |
| `DERIVED` | Trusted from the pipeline that produced it (e.g. the photo bridge's own wall-contact decision), not yet independently re-checked | `from_bridge_result` |
| `STALE` | Was DERIVED/SUPPORTED, but its subject moved and no verifier exists to re-check it | `recompute_relations`, for a `DERIVED_GEOMETRY` predicate outside `_VERIFIABLE_PREDICATES` |
| `ACCEPTED` | A human/upstream authority confirmed it | Reserved - no current caller sets this (no review UI consumes `GeometricRelation` yet) |

Both sides of a disagreement are always kept - never silently overwritten -
matching `SpatialConflict`'s own rule one stage upstream
(`app/intelligence/schema.py`): a `CONTRADICTED` relation is not deleted, it
is marked and left for a reader (or, out of scope here, P4's repair engine)
to act on.

## 5. Confidence: three channels, kept distinct, none invented

- **Semantic-relation confidence** — `GeometricRelation.confidence`
  (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`), unchanged from `SpatialConfidence`.
- **Grounding/evidence confidence** — `GroundingHypothesis`'s existing three
  numeric channels (`perception_confidence`, `extent_confidence`,
  `wall_confidence`), untouched by this phase.
- **Solver/placement confidence** — `SceneObject.confidence` (`Confidence`,
  a single scalar + `source` string), unchanged.

No new numeric confidence was invented for `GeometricRelation` - it reuses
the categorical `SpatialConfidence` production already has, because no new
measurement exists to justify a fourth channel; a category with no evidence
behind it is a `UNSUPPORTED_HYPOTHESIS` finding (`scene_consistency.py`), not
a number this phase would otherwise have to make up.

## 6. Distinct, non-interchangeable predicates: `AGAINST_WALL` vs. `SUPPORTED_BY`, and why `CONTACTS`/`ON_FLOOR` were not added

The brief asks to formalise `SUPPORTED_BY` / `CONTACTS` / `AGAINST_WALL` /
`ON_FLOOR` as distinct relations. `AGAINST_WALL` (subject: an object; object:
a wall) and `SUPPORTED_BY` (subject: an object; object: another object or the
room/floor) are ALREADY distinct in production's own `SpatialPredicate`
enum and in this phase's `classify()` (different verifiers, different
targets) - nothing needed adding for that pair.

`CONTACTS` and `ON_FLOOR` were considered and **not added**: `ON_FLOOR` would
be strictly redundant with `SUPPORTED_BY` targeting the room (which
`_semantic_relations` already emits), and `CONTACTS` would be a strictly
weaker version of `AGAINST_WALL`/`SUPPORTED_BY` with no measured evidence
source anywhere in this program to populate it. Adding predicates nothing
produces would be exactly the "reject sophistication chosen because it is
more general" pattern this whole program has rejected since P3's solver
comparison - documented here rather than silently omitted.

## 7. `CONTAINS`/`INSIDE`: formalised, not yet produced

Added to the taxonomy (`_GEOMETRY_SOURCED`) per the brief's explicit request,
even though no production reader emits them yet - no built container object
(a cabinet, a drawer) has a containment detector. A real implementation would
be "B's footprint lies inside A's footprint", exactly as measurable as
`AGAINST_WALL`'s distance-to-segment check is. Kept out of
`app.intelligence.schema.SpatialPredicate` (unchanged) until a real evidence
source produces one - this phase only reserves the taxonomy slot and the
circular-containment consistency check (`scene_consistency.
_circular_containment`), tested via the `circular_containment` /
`containment_non_circular` adversarial scenarios.

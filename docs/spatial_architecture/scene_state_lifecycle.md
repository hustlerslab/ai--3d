# P7 — Scene state lifecycle: ownership, mutability, and contracts

See `scene_model.md` for the model and `relation_contract.md` for the
relation taxonomy this lifecycle operates on.

## 1. Ownership: who is allowed to change what

| State | Who may write it | Who may only read it |
|---|---|---|
| `Scene` geometry (Room/Wall/Opening) | The bridge at construction time (`grounding_to_scene`) or the compiler (`place_objects`) - never after | Everything else: solvers, repair, validators, this phase's relation layer |
| `SceneObject.position` / `.rotation_y` | Solvers/repair only: `place_objects`, `resolve_collisions`, `solve_greedy`/`solve_backtracking`/`solve_beam`, `repair_scene` | Validators (`validate_scene`), consistency checks (`check_consistency`), Blender (`build_manifest`, read-only on the manifest it is given) |
| `GeometricRelation` (this phase) | `from_bridge_result`/`from_spatial_relation` at construction; `recompute_relations` for status transitions only | `check_consistency` (never writes); every other reader |
| `Confidence` / evidence fields | Whoever built the evidence (perception, the bridge) - never rewritten downstream | Solvers may READ confidence to break ties (P1's `(-confidence.value, object_id)` sort) but never WRITE it |

**Solver contract**: a solver (P1/P3/P4, any future one) may only produce
PLACEMENT decisions - `SceneObject.position`/`.rotation_y`/`.scale` - and may
never rewrite `Confidence`, evidence fields, or `GeometricRelation` content.
This is already true of every solver in this program (verified by re-reading
`collision_solver.py`, `scene_optimizer.py`, `repair_engine.py` for this
phase's audit - none writes a `Confidence` or touches a relation dict beyond
reading `_wall_by_object`); this phase makes the rule explicit rather than
implicit-by-convention.

**Validation contract**: `validate_scene` and `scene_consistency.
check_consistency` are BOTH strictly read-only - neither has ever mutated its
input (`validate_scene` was already read-only in P0's audit;
`check_consistency` is a brand-new function verified read-only by
`test_check_consistency_never_mutates_input` and
`test_recompute_never_mutates_the_input_scene_or_relations`). A validator
that could write would blur exactly the "solver decides, validation verifies"
line principle 0 of this whole program draws.

## 2. The relation -> constraint bridge

No relation in this program is EVER handed to a solver as raw geometry -
the bridge is explicit and narrow:

```
GeometricRelation(AGAINST_WALL, subject=obj, object=wall_id)
    -> collision_solver._wall_by_object(relations) -> {obj_id: wall_id}
    -> find_valid_nudge(working, obj, wall)   -- P1's own, unmodified geometry search
```

The relation only ever supplies WHICH wall to search near - the actual
placement math (candidate generation, collision testing) is P1's frozen,
tested geometry, never re-derived from the relation's `note`/`confidence`
fields. This is the same shape `apply_spatial_graph`
(`app/planning/spatial_graph.py`) already uses one stage upstream: a relation
fills a NAMED FIELD (`support_key`, `relation`) that an existing, unmodified
engine (`compiler.py`'s candidate generators) then consumes - never letting
a relation's free-text `note` or an LLM's own words become a coordinate.

A relation becomes a real constraint only through this one, audited path;
`GeometricRelation.evidence_refs`/`.provenance` are for a HUMAN or a
consistency check to read, never for a solver to parse.

## 3. Staleness: recompute, invalidate, or mark - never silently keep

**Scene snapshots** (the brief's own "only if it materially helps" question):
a full scene-history/undo system was considered and **not built** - no
consumer in this program needs to reconstruct a PAST whole-scene state, only
to know whether the CURRENT scene still matches what one relation claimed.
`GeometricRelation.verified_at_position` is exactly that minimal snapshot,
scoped to one field of one entity, per relation - not a general mechanism.
It materially helps (it is what makes staleness detection possible at all)
without paying for a capability nothing has asked for.

Every `DERIVED_GEOMETRY` relation carries `verified_at_position` - the
subject's position when the relation was last known true. `recompute_relations`
(`scene_graph.py`) is the ONE place status transitions on movement happen:

```
subject/object missing from scene  -> CONTRADICTED (orphan)
predicate has a verifier (AGAINST_WALL)
    -> check now, regardless of prior kind/status
        true  -> SUPPORTED
        false -> CONTRADICTED
predicate has NO verifier, subject moved since verified_at_position
    -> STALE
predicate has NO verifier, subject unmoved
    -> unchanged
```

Nothing computes this automatically on every `SceneObject` write - `Scene`
remains a plain pydantic model with no observer/signal machinery (adding one
was considered and rejected: no measured need, and it would make every
existing P1-P6 write site implicitly slower and harder to reason about for a
guarantee this phase's explicit, opt-in `recompute_relations` call already
gives any caller that wants it). The cost of the explicit-call design is
named honestly: a caller that forgets to call `recompute_relations` after
moving an object gets exactly today's silent-staleness behaviour. The
benefit is that P1-P6's frozen call sites need zero changes - `resolve_
collisions`/`repair_scene` still work exactly as before; a caller adds the
check as a NEW step, never a forced hook into existing code.

## 4. Observed reality vs. intent: how it already shows up, and what was not built

`GeometricRelation.source` already distinguishes an OBSERVED claim
(`"geometry"`, `"placement"` - the object's actual measured/placed state)
from an INTENT-like claim (`"semantic"` - what a reader's stated hint or a
future brief's request says SHOULD be true). The
`stated_hint_vs_measured_geometry_disagree` adversarial scenario
demonstrates the resolution rule directly: when both exist for the same
`(subject, predicate, object)`, `recompute_relations` checks the CURRENT
geometry and the claim resolves to `SUPPORTED` or `CONTRADICTED` based on
what is actually true now, not on which source asked for it. A general
`Intent` entity (a first-class "what the user asked for" object, separate
from every relation's `source` field) was considered and **not built**: no
consumer for a distinct Intent type exists yet - production's own object
plan (`ObjectPlanItem.against`/`.faces`) already carries stated preference,
and this phase's `source="semantic"` marking is the minimal addition that
lets a future brief-path caller express the same distinction without a new
top-level type. This keeps `SpatialScene` representation-agnostic to origin
(photo today, brief tomorrow) rather than building brief-path machinery
speculatively.

## 5. Serialization contract summary

See `research/spatial_architecture/scene_serialization.py` for the
implementation; summarised here as part of the lifecycle because
serialization is the one place EVERY state (Scene geometry + every relation
field) must round-trip losslessly for the model to be trustworthy across a
process boundary (a saved project, a benchmark replay). Canonical =
`json.dumps(..., sort_keys=True)` + relations pre-sorted by their
content-addressed `relation_id` - never insertion order, never a Python
`set`/`dict` iteration order. Verified by `tests/
test_spatial_architecture_scene_serialization.py` (round trip, 20-repeat
determinism) and exercised by every one of the 22 adversarial scenarios in
`scene_benchmark.py` (each one is itself round-tripped and required to
reproduce byte-identical text on the second pass).

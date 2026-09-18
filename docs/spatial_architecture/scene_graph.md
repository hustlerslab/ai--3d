# P7 — Scene graph: the bridge, the demonstration scene, and benchmark results

See `scene_model.md` (model/architecture) and `relation_contract.md`
(taxonomy) for the design; this document covers what was actually run and
measured. Implemented in `research/spatial_architecture/scene_graph.py` and
`scene_benchmark.py` (`python -u research/spatial_architecture/
scene_benchmark.py`).

## 1. The architecture bridge

```
PHOTO -> GroundingHypothesis[] (P1, frozen)
      -> scene_from_photo.grounding_to_scene()  (P1, frozen)  -> BridgeResult(scene, relations: list[dict])
      -> scene_graph.from_bridge_result(bridge.scene, bridge.relations)   [NEW, this phase]
      -> SpatialScene                                                     [NEW, this phase]
      -> scene_graph.recompute_relations(spatial_scene)                   [NEW, this phase - diagnosis only]
      -> scene_consistency.check_consistency(spatial_scene)               [NEW, this phase - diagnosis only]
      -> spatial_scene.scene  -> app.spatial.validation.validate_scene()  (unmodified)
                              -> app.blender.manifest.build_manifest()    (unmodified)
                              -> app.blender.runner.BlenderRunner         (unmodified)
```

Every arrow into an existing box is unchanged: `grounding_to_scene`,
`validate_scene`, `build_manifest`, and `BlenderRunner` all receive exactly
the types they received before this phase existed. `from_bridge_result` is a
pure, additive wrapper - it reads `BridgeResult.scene`/`.relations`, builds
classified `GeometricRelation`s, and returns a new `SpatialScene`; it does
not alter `scene_from_photo.py` in any way (confirmed: `git diff` on that
file is empty for this phase).

## 2. The required end-to-end demonstration scene

`scene_graph.build_demonstration_scene()` - synthetic, deterministic
(scene_id and every entity id fixed, no model call), covering every element
this phase's brief required:

| Requirement | Where |
|---|---|
| Room, floor | `room_demo` (living_room, 6x6 m boundary) |
| Multiple walls | `wall_a`, `wall_b` |
| Two same-category objects | `obj_chair_0`, `obj_chair_1` (both `chair`) |
| A different category | `obj_table_0` (`dining_table`) |
| One wall-anchored object | `obj_chair_1` (`AGAINST_WALL` -> `wall_a`) |
| One floor-supported object | all three objects (`mount="floor"`, the Scene default) |
| One object-object relation | `obj_chair_1` `ADJACENT_TO` `obj_table_0` |
| One derived geometric relation | the `AGAINST_WALL` relation above |
| One evidence-backed semantic relation | `obj_chair_0` `FACES` `obj_table_0`, `source="semantic"`, a stated hint |
| One solver decision | `Confidence.source="solver_decision:place_objects"` on `obj_table_0`/`obj_chair_0` |
| One validation result | `check_consistency(recomputed)` -> `[]` (clean) |

Full lineage, printed by `scene_benchmark.py` and reproduced here from a
real run:

```
objects=3 walls=2 relations=3
  obj_chair_1 AGAINST_WALL wall_a  kind=derived_geometry status=supported conf=HIGH
  obj_chair_0 FACES obj_table_0    kind=semantic_hypothesis status=unresolved conf=LOW
  obj_chair_1 ADJACENT_TO obj_table_0  kind=derived_geometry status=derived conf=MEDIUM
consistency findings: 0
```

`obj_chair_1`'s `AGAINST_WALL` relation is built at `DERIVED` status (trusted
from construction) and `recompute_relations` promotes it to `SUPPORTED`
(independently re-verified, gap 0.025 m) - the one recorded change on this
scene, confirming the recompute step actually re-checks geometry rather than
passing it through unexamined.

Blender-manifest/read-back for this exact synthetic scene was not separately
re-run in this phase (no new Blender/manifest code was written or changed);
`spatial_scene.scene` is a plain, valid `Scene` and would build through
`build_manifest`/`BlenderRunner` exactly as any other `Scene` does - this is
asserted by construction (same type, same required fields), not by an
additional Blender invocation for this synthetic demo, matching how the
photo-bridge's earlier demonstration objects were validated against
production functions rather than by running Blender on synthetic fixtures.

## 3. Determinism

20 repeated builds of the demonstration scene, each re-run through
`recompute_relations` -> `check_consistency` -> `to_canonical_json`:
**byte-identical across all 20**, including the change log and the finding
list. Verified both in `scene_benchmark.determinism_check()` and in
`tests/test_spatial_architecture_scene_serialization.
test_serialization_is_deterministic_across_20_builds`.

## 4. Adversarial scenarios

**22/22 passed** (exceeds the >=20 required). Full list, in
`scene_benchmark._scenarios()` (reused, not duplicated, by
`tests/test_spatial_architecture_scene_adversarial.py`):

against_wall_holds_unmoved, against_wall_holds_after_jitter,
against_wall_broken_after_move, against_wall_still_true_after_sliding,
orphan_subject, orphan_object_wall, duplicate_relation,
multiple_wall_claims_real_corner, stale_relation_no_rule,
unsupported_hypothesis, same_category_duplicates_distinct_relations,
repair_style_move_breaks_relation, camera_frame_relation_no_false_positive,
object_outside_room_out_of_scope, containment_non_circular,
circular_containment, conflicting_faces,
stated_hint_vs_measured_geometry_disagree,
shared_asset_distinct_object_identity, missing_asset_metadata_no_finding,
deterministic_serialization_round_trip, orphan_after_object_removed.

`repair_style_move_breaks_relation` is the direct regression test for the
measured P1/P4 staleness bug (`scene_model.md` §2): it builds a relation,
moves the subject the way P1's nudge search would, and requires
`recompute_relations` to catch it as `CONTRADICTED_RELATION` - which it does.

## 5. Performance (5/10/20/50/100 objects)

| n | recompute | consistency | serialize | findings |
|--:|--:|--:|--:|--:|
| 5 | 0.26 ms | 0.07 ms | 0.49 ms | 0 |
| 10 | 0.26 ms | 0.05 ms | 0.47 ms | 0 |
| 20 | 0.44 ms | 0.07 ms | 0.71 ms | 0 |
| 50 | 1.16 ms | 0.13 ms | 1.49 ms | 0 |
| 100 | 1.59 ms | 0.18 ms | 2.75 ms | 37 |

All three operations are sub-3 ms even at 100 objects/relations - no
optimisation was needed (every lookup is a linear scan over a small tuple;
no indexing was added because nothing measured here approaches a scale where
it would matter, matching this program's standing "prefer the simplest thing
that meets the measured bar" rule).

**The 37 findings at n=100 are real, not a bug in the checker.** The
synthetic generator (`_synthetic_scene`) places object `i` at `x = i * 0.8 m`
against a wall spanning `x in [-50, 50]`; at `n=100` the last objects reach
`x = 79.2 m`, past the wall's own end - `recompute_relations` correctly finds
their `AGAINST_WALL` claim no longer holds (they are not against ANY part of
the wall) and marks them `CONTRADICTED`. This is left as an honest artefact
of the performance fixture rather than silently "fixed" by widening the wall
to hide it - it happens to also serve as one more real-geometry confirmation
that the checker fires exactly when it should, at scale.

## 6. Regression: P1-P6 unaffected

`git status --short` for this phase shows only new files under
`research/spatial_architecture/`, `tests/`, and `docs/spatial_architecture/`
- zero lines changed in any P0-P6 file (`collision_solver.py`,
`clearance_engine.py`, `scene_optimizer.py`, `repair_engine.py`,
`wall_geometry.py`, `coordinate_frames.py`/`transforms.py`/`frame_graph.py`,
`scene_from_photo.py`, `grounding_contract.py` are all untouched). Full
`pytest -q`: 498 passed (440 baseline + 58 new), 7 skipped, 30 xfailed -
identical skip/xfail counts to the P6 baseline. See `decisions.md`'s P7
entry for the full control-gate re-run (21-image photo benchmark, brief-path
`scene_validity_benchmark.py`, Blender `blender_e2e_benchmark.py`).

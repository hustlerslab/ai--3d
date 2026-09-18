# P7 — Scene / SpatialGraph architecture: audit, research, and the canonical model

Continues `coordinate_frames.md`'s P6 entry (`decisions.md`). Covers the live
representation audit, the five-way architecture comparison, and the canonical
`SpatialScene` model this phase adds. `relation_contract.md` covers the
relation taxonomy and contradiction model in depth; `scene_state_lifecycle.md`
covers mutability, ownership, and the solver/validation contracts;
`scene_graph.md` covers the bridge, the demonstration scene, and the
benchmark results.

## 1. Live representation audit

| Layer | Type | Where | What it holds | Relations? | Persisted alongside geometry? |
|---|---|---|---|---|---|
| Geometry (canonical) | `app.scene.schema.Scene` | production | Room/Wall/Opening/SceneObject/Material | No | N/A - this IS the geometry |
| Pre-metric arrangement | `app.intelligence.schema.SpatialGraph` | production | `SpatialNode`/`SpatialRelation`/`SpatialGroup`/`SpatialConflict`/`UnmatchedDetection` | Yes | **No** - built once at the moodboard stage (no `Scene` exists yet), folded into `ObjectPlanItem.relation`/`support_key` by `apply_spatial_graph`, then discarded |
| Photo evidence/hypothesis | `research.spatial_architecture.grounding_contract.GroundingHypothesis` | research (P1) | FACT (footprint, room_position, depth_m, evidence) / HYPOTHESIS (orientation_candidates) / DECISION (wall_contact) per object | No (per-object only) | Consumed once by `grounding_to_scene`, then discarded |
| Photo-bridge relations | `research.spatial_architecture.scene_from_photo.BridgeResult.relations` | research (P1) | `list[dict]` (`subject_id, predicate, object_id, confidence, source, frame, note`) | Yes, but untyped | **No** - passed once to `resolve_collisions`/`repair_scene` as a read-only lookup, never re-derived or invalidated after either moves an object (see §2, the measured bug) |
| Solver decisions | `SceneObject` fields written by `place_objects`/`resolve_collisions`/`solve_greedy`/`repair_scene` | production + P1/P3/P4 | position, rotation_y, `Confidence` | No | Geometry itself - the DECISION layer, already the single source of truth for placement |

**Reused, not re-derived, in this phase:** `Scene`'s geometry (P0-P6 already
proved every conversion into/out of it correct); `GroundingHypothesis`'s
FACT/HYPOTHESIS/DECISION split (the first working instance of the pattern
this phase generalises); `SpatialPredicate`'s existing vocabulary (not
replaced - classified, in `relation_contract.md`); every P1-P6 geometry/
collision/clearance/optimizer/repair/coordinate function (called, never
reimplemented).

## 2. The measured gap this phase closes

Traced directly in the live code (not hypothesised): `resolve_collisions`
(P1, `collision_solver.py:172`) and `repair_scene` (P4, `repair_engine.py:366`)
both accept `relations: list[dict]` and read it via each module's own private
`_wall_by_object` to find which wall an object claims to be against - and
**neither function, nor `integration_benchmark.py` which calls them in
sequence with the SAME list, ever recomputes or invalidates that claim after
moving the object.** An object nudged off a wall to resolve a collision (P1)
or repaired away from one (P4) keeps its `AGAINST_WALL` relation, unexamined,
for the rest of the pipeline's life. This is not an adversarial hypothetical;
it is what the frozen, tested, currently-running P1/P4 pipeline does on every
benchmark run today. It is exactly the "derived relations must never silently
go stale" failure mode named in this phase's brief, found by reading the real
call sites rather than assumed from the brief's own framing.

It also explains why no earlier phase noticed it: P1-P6 each benchmarked
their OWN layer (collision resolution correctness, repair correctness,
coordinate correctness) - none of them had a reason to ask "and is the
relation that was true when this pipeline started still true when it
finishes?", because no persistent, typed relation layer existed to ask the
question of. `scene_graph.recompute_relations` (see `scene_graph.md`) is the
first place in this program that asks it.

## 3. Five architecture candidates

| Candidate | Sketch | Verdict |
|---|---|---|
| **A. Extend Scene/SpatialGraph into one canonical `SpatialScene`** | `Scene` (unchanged) + a typed, classified relation layer alongside it; existing validators/solvers/Blender code unmodified | **Chosen.** See below. |
| B. Unified typed `SpatialScene` replacing `Scene` | One new pydantic model absorbing Room/Wall/Object/Relation | Rejected: forks the type every P1-P6 function, `validate_scene`, `build_manifest`, and `BlenderRunner` already accept; would require rewriting or wrapping all of them, for no capability A does not already provide |
| C. Entity-component system | Objects as bags of components (Position, Semantic, Relation, ...) queried by system | Rejected: no measured need for heterogeneous component sets per entity - every entity in this program (Room/Wall/SceneObject) has a small, fixed, well-understood field set; ECS earns its cost when entities vary widely in shape, which none do here |
| D. USD-like hierarchical composition (layers, prims, references) | Full scene-graph-of-prims with override/reference semantics | Rejected: this program's own P6 research (`coordinate_frames.md`) already found Allure's data volumes and hierarchy depth (room -> object, occasionally -> supported item) do not need composition/layering; a runtime dependency this heavy was explicitly rejected there for the same reason and nothing has changed |
| E. Separate semantic and geometric databases | Two stores (a geometry DB, a relation/semantic DB) joined by id | Rejected: this is what today's ACCIDENTAL architecture already does (Scene geometry vs. discarded relation dicts) and is the source of the measured bug in §2 - two owners of overlapping facts is the failure mode, not a fix for it |

**Candidate A is chosen** for the same reason this program's very first
architecture decision (`architecture_candidates.md`/`architecture_decision.md`,
pre-P1) chose it for the photo bridge: `Scene` already IS the correct,
tested, minimal geometry representation; the only real gap is a persistent,
typed relation layer with a staleness/consistency operation, which is
additive. This phase's own audit (§1) confirms the same conclusion still
holds five phases later - no new evidence favours B-E.

## 4. The canonical model: `SpatialScene`

```
research/spatial_architecture/scene_model.py
    SpatialScene(scene: Scene, relations: tuple[GeometricRelation, ...])
        .object_ids() / .wall_ids() / .known_entity_ids()
        .relations_for(entity_id) / .relations_by_kind(...) / .relations_by_status(...)
        .with_relations(...)   -- the only way to get a new relation set (frozen dataclass)
```

`scene` is the SAME `app.scene.schema.Scene` instance production code
expects - not a copy, not a re-derivation. Everything downstream
(`validate_scene`, `build_manifest`, `BlenderRunner`, `resolve_collisions`,
`repair_scene`) receives `spatial_scene.scene` unchanged and behaves
identically to today, per the reuse-not-fork rule this whole program follows.

## 5. Five-layer separation, and where each lives

| Layer | Concrete type | Owner |
|---|---|---|
| Evidence | `GroundingHypothesis`'s FACT fields; `SceneElement`/`SpottedObject` | Perception (P1, `app.intelligence`) |
| Hypothesis | `GroundingHypothesis.orientation_candidates`; `GeometricRelation` with `status in (UNRESOLVED, EVIDENCE_CLAIM kind)` | Perception + this phase |
| Geometry | `Scene` (Room/Wall/Opening/SceneObject) | Production, unchanged |
| Semantic Relation | `GeometricRelation` (this phase) | This phase, wraps `SpatialRelation`/bridge dicts |
| Solver Decision | `SceneObject.position/rotation_y` + `Confidence.source`; P4 `RepairRecord` | P1/P3/P4, unchanged |

## 6. FACT / HYPOTHESIS / DECISION, generalised

Operationalises the pattern P1's `GroundingHypothesis` established for one
object into a scene-wide, relation-aware rule (see `scene_model.py`'s module
docstring for the exact mapping):

- **FACT** = `Scene` geometry once placed, and `GeometricRelation.status ==
  SUPPORTED` (independently re-verified by `recompute_relations` against
  CURRENT geometry - not merely asserted by whoever built it).
- **HYPOTHESIS** = `GeometricRelation.status in (UNRESOLVED, DERIVED)` -
  believed, but DERIVED specifically means "trusted from the pipeline that
  produced it, not yet independently re-checked" (see `relation_contract.md`'s
  status definitions).
- **DECISION** = every `SceneObject` field a solver/repair function wrote
  (P1/P3/P4, unchanged); `RelationStatus.ACCEPTED` is reserved for a future
  human/upstream confirmation step no current caller produces.

## 7. Five questions, per relation and per object

1. **What is it?** `GeometricRelation.predicate` / `SceneObject.semantic_type`
2. **Where is it?** `SceneObject.position` / `Wall.start,end`
3. **Which frame?** `Scene.coordinate_system` (P6); relations are plan-view
   (XZ), matching the geometry they sit over - no new frame was needed
4. **Why do we believe it?** `GeometricRelation.provenance` + `evidence_refs`
   (never empty - the evidence-restriction principle)
5. **Who can change it?** see `scene_state_lifecycle.md`'s ownership table

## 8. What was explicitly scoped out, and why

| Asked | Decision | Why |
|---|---|---|
| N-level hierarchy (Room/Surface/Wall/Floor as a deep tree) | Not built | `Scene.rooms`/`.walls`/`SceneObject.parent_id` already express the one real support level (P0-P6's own prior finding, re-confirmed - Phase 9 measured zero on-surface groundings needing a second level) |
| Openings as their own semantic entity type | Not built | `Opening` already exists in `Scene` as geometry; no consumer in this program needs an `Opening` to carry a relation the geometry field doesn't already carry |
| 7+ numeric confidence channels | 3 channels (unchanged from the pre-P1 bridge decision) + the existing categorical `SpatialConfidence` for relations | No system studied (this phase or the original bridge decision) reports more than a handful of independently measured channels; inventing more would report precision nothing measures |
| A probabilistic contradiction model | Deterministic enum (`RelationStatus`) | The brief itself asks for "deterministic, not probabilistic"; no scoring model exists anywhere else in this program to make one consistent with |
| Full brief/text-path scene generation | Not built | No text-brief-driven scene-graph consumer exists yet; `SpatialScene` is representation-agnostic to origin (photo vs. brief) by construction - `from_bridge_result` is the photo-specific adapter, nothing in `scene_model.py`/`scene_consistency.py` assumes a photo origin |

## 9. Verdict

**PASS.** See `scene_graph.md` for the bridge, demonstration scene, and
benchmark results, and `decisions.md` for the full 24-section P7 RESULT.

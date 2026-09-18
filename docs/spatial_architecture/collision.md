# P1 — Multi-object collision solving

## 1. Objective

Close the measured gap: 10 `COLLIDES_OBJECT` violations across 4 of 21
photo-grounded scenes (`baseline.md` §2, §4), caused by objects being grounded
and placed independently, with no pairwise awareness, unlike the brief path's
`place_objects` (0 violations / 547 objects).

## 2. Research questions

1. What collision *representation* is appropriate for furniture-scale indoor
   layout — full 3D mesh, OBB, AABB, capsule, or 2D footprint polygon?
2. What collision *algorithm* is appropriate at this object count (≤20/room)
   — broad-phase spatial structures (BVH/hashing), or brute-force pairwise?
3. What *architecture* turns a detected collision into a corrected placement —
   a global solver (MILP/CP-SAT), or a sequential/local search, and how do
   state-of-the-art furniture-layout systems actually do it (not what they
   could in principle do)?
4. Can Allure's *existing* representation, algorithm, and placement mechanism
   (§baseline.md) be extended, or does evidence require replacing any of them?

## 3. Search strategy and sources

Search strategies used (WebSearch, cross-checked against ≥2 results each):
`"furniture arrangement optimization constraint satisfaction indoor scene
layout collision 2025"`, `"greedy sequential placement 3D scene generation
constraint furniture robotics"`, `"OR-Tools CP-SAT 2D rectangle packing layout
no-overlap constraint"`, `"separating axis theorem SAT vs GJK 2D convex
polygon collision detection comparison"`, `"Holodeck RoomCraft HSM furniture
layout constraint solver collision avoidance algorithm"`, `"Shapely trimesh
license commercial use Windows python 2D polygon collision performance"`.

**Primary sources read/cross-checked:**

- Holodeck, CVPR 2024, [arXiv:2312.09067](https://arxiv.org/pdf/2312.09067) — object placement solver.
- RoomCraft, [arXiv:2506.22291](https://arxiv.org/html/2506.22291) — HDFS ordering + CAPS repositioning, fetched in full.
- HSM, 3DV 2026, [arXiv:2503.16848](https://ar5iv.labs.arxiv.org/html/2503.16848) — grid-based DFS solver.
- "Make It Home" (Yu et al., ACM TOG 2011, [doi:10.1145/2010324.1964981](https://dl.acm.org/doi/10.1145/2010324.1964981)) — the classical furniture-arrangement-as-energy-minimization reference every later paper cites.
- SAT vs. GJK: [dyn4j.org/2010/01/sat](https://dyn4j.org/2010/01/sat/), [cs.sjsu.edu GJK notes](https://www.cs.sjsu.edu/faculty/pollett/masters/Semesters/Spring12/josh/GJK.html).
- OR-Tools CP-SAT `NoOverlap2D`: [official primer](https://d-krupke.github.io/cpsat-primer/advanced_modelling.html), [GitHub discussion #3107](https://github.com/google/or-tools/discussions/3107).
- `app/planning/compiler.py:place_objects` — Allure's own production placement mechanism (the strongest available production reference: already measures 0/547 collisions).

## 4. Findings, cross-checked

**Every system that actually ships furniture placement uses a sequential /
depth-first constraint-satisfaction search, not a global optimizer, as its
primary mechanism** — confirmed independently across three papers:

| System | Mechanism (as published) |
|---|---|
| Holodeck | DFS solver primary; MILP solver offered as a slower alternative mode, not the default path |
| RoomCraft | Heuristic-ordered DFS (**HDFS**): task list sorted by `f(Vᵢ) = Σ wⱼ·𝕀ⱼ(Vᵢ,Vⱼ,Eᵢⱼ)` — objects with *stronger spatial constraints placed first* — then a **Conflict-Aware Positioning Strategy (CAPS)** that reacts to a detected conflict with a weighted objective `ℒ = α·ℒdist + β·ℒobj, α+β=1`, α raised on wall collisions, β raised on object collisions |
| HSM | Grid-based DFS, largest-footprint motif placed first, "no overlap between scene motifs" is one of the enforced constraints during that same DFS |

This is independent, converging evidence — not one paper's opinion — that
**Allure's existing `place_objects` (greedy, ordered, incremental
candidate-and-validate) is already in the same algorithmic family the field
converges on**, not an ad hoc shortcut needing replacement. RoomCraft's own
ordering principle ("stronger constraints first") is exactly analogous to
ordering by placement confidence, which §6 adopts.

**Collision representation**: SAT on 2D convex polygons is confirmed
appropriate for exactly this regime — "SAT is fast and suitable for
applications with simple shapes and few contacts" (dyn4j.org), "SAT can
replace GJK entirely [in 2D]... doesn't scale to 3D... less commonly used
[there]" (cs.sjsu.edu). Allure's furniture footprints are simple convex
quadrilaterals and per-room object counts are ≤20 — squarely "few contacts,
simple shapes." GJK/EPA, full 3D mesh collision (FCL/Bullet/PhysX), and BVH/
spatial-hashing broad-phase all solve a harder, unneeded problem: they exist
for hundreds-to-thousands of arbitrary meshes in robotics/physics, not ~10-20
furniture footprints in a room. Brute-force O(n²) pairwise SAT is the correct
choice at this scale — it is what Allure's own `validate_object` already does
(H3 loops every other object), and it is what every candidate this document
considered would fall back to at n≤20 regardless.

## 5. Decision matrix

| Candidate | Research evidence | Determinism | Complexity | License/commercial | Python/Windows | Allure fit | Decision |
|---|---|---|---|---|---|---|---|
| **Reuse SAT footprint + extend `place_objects`'s DFS pattern to the photo bridge** | 3 independent papers converge on DFS-family; Allure's own 0/547 result | 100% (fixed ordering, fixed candidate lattice, no RNG) | Low — new orchestration only, zero new geometry code | N/A (in-house) | Already proven | **Exact match** | **CHOSEN** |
| OR-Tools CP-SAT `NoOverlap2D` global solver | Confirmed to exist and work for axis-aligned rectangle packing; rotated OBBs need linearization (not natively supported) | High, but adds a new dependency + solver-version pin | High — new modeling layer, new dependency, a different scene per object count would need re-encoding | Apache 2.0, commercial-fine | New dependency (`ortools`, ~100MB wheel) | No measured need beats a proven 0-violation existing mechanism | **Rejected — no evidence extension is insufficient** |
| Shapely/trimesh for polygon ops | BSD license, mature, but redundant with a working, tested in-house kernel | Same as in-house (deterministic ops) | Adds a dependency for something 60 lines already does correctly | BSD (Shapely), commercial-fine | Fine | Zero added accuracy over the existing, production-shared SAT kernel | **Rejected — "do not add a dependency for what a few lines can do"** |
| Full 3D mesh collision (FCL/Bullet/PhysX) | Built for robotics/physics-scale contact resolution, not furniture footprints | High, but per-frame solver tuning risk | Very high — new physics engine, GPU/CPU cost, mesh prep pipeline | Mixed (PhysX proprietary terms) | Heavy, Blender-only overlap | Solves a harder problem than the measured one (footprint overlap, not mesh penetration) | **Rejected — wrong representation for the failure** |
| Simulated annealing / genetic search over full scene | Used in some older furniture-layout literature (Make It Home) | Low unless seeded and reported as exploration-only (contradicts P10) | Medium-high | N/A | Fine | No measured failure needs a global re-optimization; only 4/21 scenes are affected, each by 1-3 specific pairwise conflicts | **Rejected — disproportionate to the measured failure** |

## 6. Design

**Representation**: unchanged — the object's existing oriented-rectangle
footprint (`footprint_corners`), tested with the existing
`convex_polygons_overlap` (SAT). No new geometry primitive.

**Algorithm — broad phase**: none needed. Brute-force pairwise, exactly as
`validate_object`'s H3 already does; O(n²) at n≤20 is sub-millisecond.

**Algorithm — narrow phase**: unchanged — `convex_polygons_overlap`.

**Placement architecture — a DFS-family sequential resolver, new orchestration
only**, `research/spatial_architecture/collision_solver.py`:

1. **Ordering** (matches RoomCraft's "stronger constraints first"): sort
   `scene.objects` by **descending `Confidence.value`** — the grounding's own
   measured trust — ties broken by `object_id` (deterministic, not
   insertion-order-dependent).
2. **Sequential commit**: insert objects into a `working` scene one at a time
   in that order. Before each insertion, call the existing
   `app.spatial.validation.validate_object(working, obj)` (reused, not
   reimplemented). If it returns no violation, commit as-is.
3. **Conflict repair — a deterministic candidate lattice, not a learned
   weight** (RoomCraft's CAPS score `α·ℒdist + β·ℒobj` is not reproducible
   without knowing its trained weights; this replaces it with the simplest
   thing that is fully deterministic and explainable — a direct
   "minimize deviation from the photo evidence" rule, still a real
   engineering translation of the same principle CAPS names):
   - Rotation is **never** perturbed — it is evidence-derived from the wall
     normal (Phase 7-9), out of scope for a positional repair.
   - If the object carries an `AGAINST_WALL` relation, candidates slide along
     the **wall tangent** through the original position, at fixed offsets
     `0, ±0.1, ±0.2, ..., ±1.0 m`, tried in increasing `|offset|` — preserves
     the photographic wall-contact evidence while resolving the conflict.
   - Otherwise, candidates form a fixed radial lattice: 8 angles ×
     `0.1, 0.2, ..., 1.0 m` radii, tried in increasing radius.
   - The **first candidate that validates clean** (checked with the same
     `validate_object`) is accepted — nearest-to-evidence, not
     furthest-from-conflict, matching the standing "geometry decides, minimal
     deviation from evidence" principle. If none validates within the bound,
     the object is left at its original position and the conflict is recorded
     as **unresolved** — never silently hidden, never fabricated as fixed.
4. Output: the corrected `Scene` plus a `CollisionResolution` record per
   moved/unresolved object (`object_id`, `status`, `distance_moved_m`,
   `candidates_tried`).

This is a **small, reversible extension**: one new file, calls three existing
functions (`validate_object`, `footprint_corners`, `convex_polygons_overlap`)
and one existing type (`Confidence`), touches nothing in `app/`.

## 7. Implementation

`research/spatial_architecture/collision_solver.py` — `resolve_collisions(scene, wall_by_object) -> (Scene, list[CollisionResolution])`.

## 8. Tests

`tests/test_spatial_architecture_collision.py` — deterministic, synthetic,
no GPU: two overlapping footprints resolve without violation; a wall-anchored
object slides along the wall tangent, not off it; equal-confidence ties break
by `object_id`; an unresolvable case (object boxed in on all sides) is left in
place and reported, not silently dropped; repeated runs (10×) on the same
input produce byte-identical output (determinism).

## 9. Benchmark

Re-run `integration_benchmark.py`'s 21-image fixture with the resolver applied
as a post-pass on each built scene, before `validate_scene`/Blender. Compare
`COLLIDES_OBJECT` count and scene-success rate before/after; confirm the
frozen Phase 9 control still reproduces exactly (nothing upstream of the
resolver changed); confirm `pytest -q` does not regress.

## 10. Failure cases anticipated (stated before running, so a result cannot be
quietly redefined as success afterward)

- `COLLIDES_WALL` on the known 11°-tilt scene is **expected to remain
  unresolved by this phase** — it is a representation-loss failure (§P5), not
  a placement-order failure; a positional nudge cannot fix a geometry the flat
  `Wall` schema cannot represent.
- A scene where 3+ objects mutually block every candidate in the lattice will
  report unresolved, not a fabricated placement.

## 11. Acceptance criteria / exit gate

No hard `COLLIDES_OBJECT` violation remains in the frozen benchmark **except**
cases this document names in advance as out of scope (§10), determinism is
100% (10 repeated runs, byte-identical scene state), and `pytest -q` does not
regress.

## 12. Measured result

`integration_benchmark.py`, full 21-image fixture, before/after
`resolve_collisions`:

| | Before (§baseline.md) | After |
|---|--:|--:|
| Scene success | 16/21 (76.2%) | **20/21 (95.2%)** |
| `COLLIDES_OBJECT` | 10 | **2** (both in one scene) |
| `COLLIDES_WALL` | 6 | **1** |
| `pytest -q` | 371 passed | **377 passed** (+6 new, 0 regressions) |
| Determinism | — | 6/6 new unit tests pass, including a dedicated 10-repeat-run check |

**One extension made mid-phase, evidence-driven, not speculative.** The
first full run (tangent-slide only) reached 19/21 (90.5%), leaving 5
violations across 2 scenes. Inspecting them showed the tangent-only search
was structurally unable to fix them: both scenes had `AGAINST_WALL` objects
whose footprint-reconstruction residual embeds them a few centimetres into
the wall rectangle — a slide *parallel* to the wall can never reduce
*perpendicular* penetration. This is a smaller, more general instance of the
§10-predicted representation-loss case, not limited to one 11°-tilt scene. A
second, much smaller (`EMBED_MAX_M = 0.2 m`, `0.01 m` steps) candidate tier —
move straight away from the wall, same spot along it, tried only after every
tangent offset fails — was added, still fully deterministic, still calling
only `validate_object`. This closed 4 of the 5 remaining violations,
bringing the result to 20/21.

**The one remaining case is out of P1's scope, and here is why, concretely.**
`data/archive/.../moodboard_room_living_room.png` grounds `tv_unit.0` and
`tv_unit.1` as two separate objects at the same wall position (gap 0.0 m
each, matching residuals of 0.0816 m) — almost certainly two SAM detections
of the *same physical TV unit*. The resolver correctly cannot "fix" this: no
positional nudge makes two duplicate groundings of one object into two
non-overlapping objects without either fabricating a second TV unit's worth
of space or silently discarding one — both violate the standing "UNKNOWN over
confidently wrong" principle. This is a **Phase 9 perception-level
duplicate-detection problem**, not a P1 collision-architecture problem, and is
recorded here as the honest boundary of what this phase can fix.

**Verdict: PARTIAL PASS.** 20/21 scenes (95.2%) collision-free, up from
16/21 (76.2%); the sole remaining failure is diagnosed to a different
subsystem (perception-level duplicate grounding) with a specific pointer for
whoever picks it up, not left unexplained. Determinism and the existing test
suite both hold. See `docs/benchmarks/spatial_architecture_report.md` for the
full before/after report.

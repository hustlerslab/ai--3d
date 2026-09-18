# Phase 0 — Baseline freeze

Frozen before any architectural change in this program. Everything below was
read from the live tree on 2026-09-15, not from memory of earlier sessions.

## Frozen baseline test command

```
cd aether-backend && ./.venv/Scripts/python.exe -m pytest -q
```

**Result at freeze time: 371 passed, 7 skipped, 30 xfailed, 65.02 s.**
Every phase below re-runs this exact command and must reproduce these counts
(or grow them with new, passing tests) before its exit gate is met.

## 1. Current architecture, as code — not as remembered

### Scene state (`app/scene/schema.py`)

Single source of truth. Units = metres, `up=+Y, right=+X, forward=-Z`, plan
geometry in the XZ plane, rotation = yaw around +Y in radians.

```
Scene
 ├── rooms: list[Room]        — boundary: closed CCW polygon, XZ, Confidence
 ├── walls: list[Wall]        — start/end: Vec2, thickness, height
 ├── openings: list[Opening]  — door/window, wall_id, position along wall
 ├── objects: list[SceneObject]
 ├── materials, saved_views, calibration, metadata
 └── spec_version, style, lighting, camera_plan (optional SceneSpec fields)

SceneObject
 ├── position: Vec3 (bottom-center pivot)
 ├── rotation_y: float (yaw, radians)
 ├── scale: Vec3, dimensions: Vec3 (w,h,d at scale 1)
 ├── mount: "floor" | "ceiling" | "wall" | "surface"
 ├── parent_id: Optional[str]   — the surface-mount host, if any
 ├── confidence: Confidence(value, source)
 └── source_strategy: "local_asset" | "local_modified" | "procedural" | "generated"
```

There is **no first-class `Constraint` entity, no `ConstraintGraph`, and no
`CollisionEngine`.** Collision-freedom is a *consequence* of how objects get
into `scene.objects`, not a property checked by a dedicated subsystem — see §3.

### Geometry kernel (`app/spatial/geometry.py`)

Pure functions, XZ plane, no scene knowledge:
`footprint_corners` (oriented rectangle from center/width/depth/yaw),
`convex_polygons_overlap` (Separating Axis Theorem, touching edges do NOT
count as overlap), `point_inside_polygon` (ray-cast + boundary tolerance),
`wall_rectangle`, `polygon_area`/`polygon_centroid`, segment utilities. This
is the **only** collision-representation primitive in the codebase: an
oriented 2D rectangle (the object's plan-view footprint) tested by SAT. There
is no AABB tree, no BVH, no 3D mesh collision, no external geometry library.

### Validation (`app/spatial/validation.py`)

`validate_scene(scene) -> list[Violation]`. Five hard checks, each already a
`Violation(code, severity, message, object_id, related_id)`:

| Code | Check |
|---|---|
| `OUTSIDE_ROOM` (H1) | every footprint corner inside `room.boundary` (0.09 m tolerance for flush-against-wall) |
| `COLLIDES_WALL` (H2) | footprint vs. every `wall_rectangle` |
| `COLLIDES_OBJECT` (H3) | footprint vs. every other floor-mounted object's footprint (flat objects ≤5cm tall, e.g. rugs, are exempt) |
| `BLOCKS_DOOR` (H4) | footprint vs. door clearance rectangles (0.75 m depth either side) |
| `ROOM_NOT_FOUND` / `ORPHAN_OPENING` / `INVALID_ROOM_POLYGON` (H5, topology) | referential integrity |

This is a **verifier, not a solver.** It is called after placement, not during
it, and it returns a list — it never repairs anything itself.

### Placement (`app/planning/compiler.py:place_objects`)

**This is the part every later phase must understand precisely, because it is
the reason the brief path already measures 0 collisions across 547 objects.**
`place_objects` iterates the object plan **sequentially**, one item at a time.
For each item it:

1. Generates a ranked list of `Candidate` positions (wall-aligned, relation-
   derived, surface-derived, or hint-derived — `_floor_candidates`,
   `_wall_hang_candidates`, `_surface_candidates`).
2. Builds each candidate as a real `SceneObject` inside a `working` copy of
   the scene that already contains every object placed so far in this pass.
3. Calls `validate_object(working, candidate)` (the same function §validation
   uses) and accepts the **first candidate that returns zero violations**.
4. Commits the accepted candidate into `working` before moving to the next
   plan item, so every subsequent item's candidates are checked against it.

This is a **greedy, order-dependent, incremental constraint-satisfaction
placement** — not a global optimizer, not a formal CSP/MILP solver, and not
labelled as either in the code. It has no backtracking across items: if item
*N* finds no valid candidate, item *N-1*'s placement is never revisited.

### Spatial relations (`app/intelligence/schema.py`, `app/planning/spatial_graph.py`)

`SpatialPredicate` enum already includes `AGAINST`, `AGAINST_WALL`, `FACES`,
`FACES_ROOM`, `NEAR`, `ADJACENT_TO`, `OVERLAPS`, `SUPPORTED_BY`/`ON_TOP_OF`,
`LEFT_OF`, `RIGHT_OF`, `ABOVE`, `BELOW`. `apply_spatial_graph` in
`app/planning/spatial_graph.py` consumes a `SpatialGraph` of these relations
(from VLM/perception) and turns them into placement hints for `compiler.py`'s
candidate generation — relations are *advisory input to candidate ranking*,
never a directly-emitted final position.

### Blender (`app/blender/manifest.py`, `app/blender/runner.py`)

`build_manifest(scene, project_root)` → `write_manifest` → `BlenderRunner`
executes a headless build and reads geometry back through `matrix_world`.
`scene_forward(rotation_y) = (-sin(rotation_y), -cos(rotation_y))` is the one
place a coordinate transform is spelled out explicitly and round-trip tested.

### The research bridge (`research/spatial_architecture/`, not imported by `app/`)

`grounding_contract.py` (`GroundingHypothesis`, FACT/HYPOTHESIS/DECISION,
3-channel confidence) and `scene_from_photo.py` (`grounding_to_scene`) convert
photo-perception output (Phase 6-9's `ObjectGrounding`) into a real `Scene`,
calling `validate_scene`/`build_manifest`/`BlenderRunner` unmodified. Objects
are appended to `scene.objects` in the order `hypotheses` arrives in — **no
collision-awareness at insertion time**, unlike `place_objects` above. This is
the exact architectural gap P1 targets.

## 2. Current metrics (all reproduced, not recalled, this session)

| Benchmark | Fixture | Result |
|---|---|---|
| `pytest -q` | whole repo | 371 passed, 7 skipped, 30 xfailed |
| Brief → Scene → Blender (`scene_validity_benchmark.py`, `blender_e2e_benchmark.py`) | 12 briefs, 559 objects | 12/12 valid, 547/559 placed, 0 hard violations, 12/12 Blender builds, XY p95 0.015 m |
| Wall contact (photo path) | 48 cases / 21 images | 7 TP / 24 TN / 2 FP / 3 FN, 12 UNKNOWN — 77.8% precision |
| Photo → Scene bridge integration (`integration_benchmark.py`) | 21 images, 46 grounded objects | 46/46 placed, 16/21 (76.2%) scene success, 20/20 Blender builds ok |
| Photo-path hard-violation breakdown | same 21 images | **`COLLIDES_OBJECT`: 10** (4 dense scenes) · **`COLLIDES_WALL`: 6** (1 tilted-wall scene) |

## 3. Known invariants (must not regress)

1. `validate_object`/`validate_scene` are pure functions of `Scene`; calling
   them twice on the same scene returns identical violations.
2. `place_objects` is deterministic given the same plan, room, and asset
   catalogue — no RNG, no wall-clock dependence, candidate order is a fixed
   sort.
3. `footprint_corners`/`convex_polygons_overlap` are the only two functions
   anything in the codebase uses to decide "do these two footprints overlap."
   Nothing else (no library, no Blender-side check) makes that decision before
   Blender executes.
4. Every scene object's `Confidence.value`/`source` is set at construction and
   never silently overwritten.
5. `AETHER_DATA_DIR` must not be set by any research script that also expects
   `resolve_asset_metadata`/`CATALOG` to see the real registry (root-caused
   and fixed in the previous session — see `spatial_architecture_report.md`
   §3; recorded here so it is not rediscovered).

## 4. Known failure cases (already measured, not new)

- **`COLLIDES_OBJECT` (10 instances, 4 scenes):** independent per-object
  photo-grounding has no pairwise awareness — this is P1's target.
- **`COLLIDES_WALL` (6 instances, 1 scene):** traced to an 11° real wall tilt
  that the flat `Wall`/`Room.boundary` schema cannot represent — this is a
  representation-loss finding for **P5** (wall representation), not a
  collision-solving bug; P1 is not expected to fix it, and this document
  records that expectation now so a later "it didn't work" is not mistaken for
  a new failure.
- **Room boundary is fabricated** (padded convex hull) whenever a photo shows
  fewer than four walls — a `Room.confidence` already names this; relevant to
  **P7** (Scene/SpatialGraph architecture) if a stronger representation is
  ever justified by evidence.
- Solver `place_objects` has no backtracking across already-placed items —
  relevant to **P3/P4** (global optimization / repair) if a measured failure
  ever traces to it. No such failure is on record yet in the brief path (0
  hard violations across 547 objects).

## 5. What this baseline rules out already

Because `place_objects` already achieves 0 measured collisions across 547
objects using a **greedy sequential candidate-and-validate** approach with no
formal solver framework, any P1-P4 design that proposes replacing this
mechanism outright carries the burden of proof that extension is
insufficient — per the standing rule "do not rewrite unless evidence
demonstrates extension is insufficient." The measured failure (10
`COLLIDES_OBJECT` in the photo path) is that this mechanism is *never run* on
photo-grounded objects, not that the mechanism itself is wrong. This framing
is carried into P1's research below.

**Exit gate: met.** The baseline is reproducible (`pytest -q` re-run, exact
match), every current API/data structure above was read from the live file,
not recalled, and no architectural change has been made yet.

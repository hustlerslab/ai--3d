# Architecture decision: the perception → scene bridge

Decision: **Candidate A** (`architecture_candidates.md`). This document fixes
the exact scope — what gets built, what gets explicitly rejected and why, and
what the coordinate-frame and provenance rules are — before any code is
written.

## 1. The canonical spatial state, concretely

```
research/spatial_architecture/grounding_contract.py
    GroundingHypothesis          -- FACT/HYPOTHESIS layer, one per object
        object_id, room_image, semantic_type, asset_id
        footprint: 4 corners, canonical frame            [FACT: measured]
        room_position, depth_m                           [FACT: derived]
        orientation_candidates: list[OrientationCandidate] -- NOT collapsed
        support: "floor" | "wall" | "unknown"
        wall_contact: {decision, wall_index, distance_m}  [DECISION: geometry]
        perception_confidence   -- SAM/MoGe coverage of the mask
        extent_confidence       -- catalogue source (registry/builtin/family/none)
        wall_confidence         -- Phase 6 gate quality of the selected wall
        evidence: list[str]
        failure_reason / failure_category

research/spatial_architecture/scene_from_photo.py
    grounding_to_scene(image, room_geometry, groundings, project_id) -> Scene
    grounding_to_spatial_graph(scene, groundings) -> list[SpatialRelation]
```

Everything downstream of `Scene` is **unmodified production code**:
`validate_scene`, `build_manifest`, `BlenderRunner`, the Blender scripts. This
is what makes Candidate A's "zero adapter cost" claim checkable rather than
asserted: the integration benchmark (`integration_benchmark.py`) calls these
exact production functions on the bridge's output.

## 2. Confidence: three channels, not seven

§13 asks whether confidence should decompose into up to seven numeric
channels. Checked against all six systems read for this decision: **none of
them report seven independent numeric confidences.** RoomCraft's constraints
carry a single scalar weight; Holodeck's constraints are hard or soft with no
weight at all; production's own `SpatialConfidence` is a three-value category
(LOW/MEDIUM/HIGH). Inventing seven numbers here would be inventing precision
the pipeline cannot measure — every earlier phase report in this program was
explicit that a number should not be reported unless it is measured.

What **is** independently measured, and is kept separate rather than averaged
into `Confidence.value`, are the three sources that actually produced distinct
evidence in Phases 6–9:

| Channel | What it measures | Comes from |
|---|---|---|
| `perception_confidence` | fraction of the mask with valid depth | SAM 2 mask ∩ MoGe-2 valid points |
| `extent_confidence` | how the object's dimensions were known | `AssetSpatialMetadata.confidence` (registry 0.9 / built-in 0.7 / family 0.4 / unknown 0) |
| `wall_confidence` | quality of the selected wall | Phase 6 `enclosure_fraction` of the gated wall |

`Confidence.value` on the resulting `SceneObject` is their product, and
`Confidence.source` names which of the three is lowest — so a caller inspecting
one field still gets a usable answer, and a caller who wants the breakdown can
read the three. This is additive to the existing `Confidence` model; no field
was removed or repurposed.

## 3. Relations: only what has evidence

§15 lists twenty relation predicates. Production's `SpatialPredicate` enum
already has a working set (`AGAINST`, `AGAINST_WALL`, `FACES`, `FACES_ROOM`,
`NEAR`, `ADJACENT_TO`, `OVERLAPS`, `SUPPORTED_BY`/`ON_TOP_OF`, `LEFT_OF`,
`RIGHT_OF`, `ABOVE`, `BELOW`). The photo pipeline built in Phases 6–9 produces
evidence for exactly **two** of these for a grounded object:

- `AGAINST_WALL` — directly from `wall_contact.decision == "YES"`, with
  `frame="floor_plan"`, `source="geometry"`, `confidence` from the categorical
  mapping of `wall_confidence`.
- `SUPPORTED_BY` — from `placement_class`/`support` (`floor` → the room itself;
  a future `SUPPORTED_ON_SURFACE` grounding would target its host object, but
  Phase 9 measured zero such cases, so this path is written but untested here
  and flagged as such).

`NEAR`/`ADJACENT_TO`/`OVERLAPS` between two grounded objects are **not**
emitted by the bridge in this phase: they would require pairwise geometry the
bridge does not yet compute, and fabricating them would be reporting a
relation with no measured evidence behind it — exactly what §51 forbids.
`ALIGNED_WITH`, `PERPENDICULAR_TO`, `BETWEEN`, `CENTERED_ON`, `VISIBLE_FROM`
and the rest of §15's list have no evidence source anywhere in the built
pipeline and are not added.

## 4. Room boundary: the one place a shape must be approximated, and how

A single photograph almost never shows a closed room perimeter — the fitted
wall set from Phase 6 is 1–4 walls, not four walls meeting at four corners.
Production's `Room.boundary` and `validate_scene`'s `OUTSIDE_ROOM` check both
assume a closed polygon, because in the brief path the room shape is invented
by a floor-plan generator, not observed.

Two options were considered:

- **(a)** Approximate the boundary as a padded convex hull of the reconstructed
  floor's valid extent, marked with a low, explicit `Room.confidence`.
- **(b)** Skip `OUTSIDE_ROOM` for photo-grounded scenes and rely only on the
  wall-relative checks Phases 6–9 already compute more precisely than a
  point-in-polygon test would.

**(a) is used**, because `validate_scene` needs *some* boundary to run at all,
and a generous padded hull (evidence: the floor's own valid points, not
invented from nothing) is preferable to disabling a whole validator. It is
explicitly the one fabricated shape in the whole bridge, it is labelled as
such (`Room.confidence.source = "reconstructed_partial_view"`), and it is
deliberately padded outward, never inward — so it can only make `OUTSIDE_ROOM`
under-strict, never falsely flag a real object as outside.

## 5. Coordinate frames: measured, not assumed

Phase 2 built `_to_canonical` specifically to convert MoGe's OpenCV output into
"+X right, +Y up, −Z forward" — and that is *also* Allure's documented `Scene`
convention (`app/scene/schema.py`'s own docstring: `up = +Y, right = +X,
forward = -Z`). Checked directly against a real `object_grounding_results.json`
row before relying on it: a footprint corner reads
`(-0.838, -0.941, -3.768)` — negative Y (below the camera, i.e. the floor),
negative Z (into the room) — consistent with the camera sitting at the frame
origin. **No further transform is needed**; the bridge places the room at the
camera's own origin, which `Scene`'s coordinate system permits (it fixes axes,
not an origin).

What the bridge does compute, and self-tests before trusting: the object's
`rotation_y` from its grounding's wall-normal orientation, via the existing
`scene_forward(yaw) = (-sin(yaw), -cos(yaw))` relationship (already defined
and round-trip-tested in `tests/test_blender_build.py`), solved as
`yaw = atan2(-forward_x, -forward_z)`. The bridge's own test rebuilds each
object's footprint from the derived `position`/`rotation_y`/`dimensions` using
production's own `object_footprint()` and checks it against the grounding's
independently-computed corners — a testable transform per §10, not an assumed
one.

## 6. What was explicitly scoped out, and why

| §  | Requested | Decision | Why |
|---|---|---|---|
| 16 | N-level `WORLD→BUILDING→ROOM→ZONE→ANCHOR→OBJECT→SURFACE→SUBOBJECT` hierarchy | **Not built** | HSM's own hierarchy is exactly two support levels for this scale (floor-furniture, furniture-surface-decor); production's `parent_id` + `SURFACE_HEIGHT` already express that. Phase 9 measured zero on-surface groundings, so a third level has no evidence to validate against yet. |
| 20–21 | First-class `Constraint` entities, MILP/DFS/simulated-annealing solver | **Not built** | Phase 11–12 measured the existing greedy candidate-generate → filter → score → validate solver at 0 hard violations across 547 objects, deterministic. No measured failure traces to "the solver lacks a formal constraint graph" — every measured photo-path failure (Phase 9 report) is a grounding-quality failure, not a solver-architecture one. Building a new solver here would be solving a problem not yet measured, which every earlier phase in this program was told not to do. |
| 13 | 7-channel numeric confidence | **3 channels, see §2** | No studied system reports more than one weight per fact; 3 is what Phases 6–9 actually measure independently. |
| 15 | ~20 relation predicates | **2 emitted (`AGAINST_WALL`, `SUPPORTED_BY`)** | See §3 — only these have evidence. |
| 23 | General repair taxonomy (collision/support/floor/door repair) | **One repair rule, tested against a measured failure** | See `integration_benchmark.py` — implemented only for the collision case the integration run actually produces, per §51 ("do not hide failure... test alternative, compare, continue" — not "build every repair rule in advance of a failure"). |
| 28 | Per-pixel `geometry_confidence(pixel)`, glass/mirror detection | **Not built** | No glass/mirror detector exists in the stack; Phase 6's `moodboard_room_bathroom` mirror case is flagged in its own report as a known, unfixed limitation, carried forward, not silently re-solved here. |
| 37 | Reusable furniture motifs | **Not built** | No text-brief-driven photo scene exists yet to make a motif meaningful; motifs are a brief-path feature (Holodeck/HSM's domain), not a photo-grounding one. |

## 7. What this phase measures

`integration_benchmark.py` builds a real `Scene` from real `GroundingHypothesis`
output (no synthetic geometry) for every one of the 21 benchmark images with at
least one grounded object, runs it through **unmodified** `validate_scene`,
`build_manifest`, and a headless Blender build with read-back — exactly the
Phase 13 procedure, but on photo-derived scenes instead of brief-derived ones.
This is the first true end-to-end test the production readiness review named
as the exact next blocker.

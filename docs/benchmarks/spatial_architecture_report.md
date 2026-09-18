# Spatial architecture: the photo → Scene bridge, and the first end-to-end test

**Verdict: the architecture question is answered, the bridge is built, and the
first true end-to-end integration is measured — and, after a dedicated P1
collision-solving phase (below), the dense-scene collision gap this report
originally found is now mostly closed.** Real `GroundingHypothesis` output
(46 of 48 benchmark objects) was converted, image by image, into real
`app.scene.schema.Scene` objects and run — unmodified — through production
`validate_scene`, `build_manifest`, and a headless Blender build with
world-space read-back. **20 of 21 scenes (95.2%, up from an initial 76.2%) are
fully valid; all 20 attempted Blender builds succeeded with zero errors; all
46 grounded objects were placed.** §5 below is kept as originally written
(diagnosing the dense-scene collision gap) with a follow-up note showing what
closed it and what one case remains; see
`docs/spatial_architecture/collision.md` for the full P1 phase.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_architecture/integration_results.json`
**Scripts:** `research/spatial_architecture/{grounding_contract,scene_from_photo,integration_benchmark}.py`
**Docs:** `architecture_candidates.md`, `architecture_decision.md` (read first — this
report assumes their conclusions)
**Production code changed:** none — `validate_scene`, `build_manifest`,
`BlenderRunner`, `catalog.search`, `object_footprint`/`footprint_corners` are
called, not modified. Dependencies added: none.
`pytest -q` → **371 passed** (367 + 4 new bridge tests), 7 skipped, 30 xfailed.

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**.

---

## 1. The architecture decision, in one paragraph

Six real systems were read (Holodeck, RoomCraft, HSM, DirectLayout, two scene-
graph papers — full citations in `architecture_candidates.md`) before writing
any code. Every one that actually places furniture converges on the shape
production already had: a flat object list, a separate relation set, hard/soft
constraints, an ordered placement search. RoomCraft — the closest analogue,
since it also turns real photographs into 3D scenes — maps `⟨R, V, E⟩`
field-for-field onto `SceneObject`/`SpatialRelation`. So the decision was
**Candidate A**: extend, not replace. The one real gap was a typed home for the
FACT/HYPOTHESIS layer between perception and the object list, filled by
`GroundingHypothesis` (wrapping Phase 9's `ObjectGrounding`, not rewriting it)
and a bridge function, `grounding_to_scene`.

## 2. What the bridge does, precisely

| Step | Source | Production code called |
|---|---|---|
| Room boundary | padded convex hull of the floor's own measured extent | `point_inside_polygon` |
| Walls | Phase 6 gated planes, oriented "into the room" by `orient_to_room`, positioned so their fitted plane is the **inner face**, not the centerline | `Wall`, `wall_rectangle` (via `validate_scene`) |
| Object pose | yaw solved from the grounding's own wall-normal axis, **verified** by rebuilding the footprint with `footprint_corners` and keeping whichever of the two 180°-apart solutions matches closer | `footprint_corners`, `object_footprint` |
| Asset selection | `catalog.search(query=canonical_type, target_dimensions=...)` — the SAME dimension-fit ranking production already uses | `app.catalog.catalog` |
| Confidence | product of three separately-measured channels (perception/extent/wall), never averaged silently | `Confidence(value, source)` |
| Relations | `AGAINST_WALL` only — the one predicate the pipeline has evidence for | `SpatialRelation`-shaped dict |
| Validation | unmodified | `validate_scene` |
| Repair | one rule: nudge the lower-confidence colliding object, re-validate once | new, in the benchmark only |
| Build | unmodified | `build_manifest`, `BlenderRunner` |

## 3. A real bug, found and fixed before it could contaminate the result **[M]**

The first full run failed its own control gate: reproducing the frozen Phase 9
confusion matrix (7/24/2/3) gave 7/26/1/3 instead. Two cases had flipped. Before
accepting that as "cross-process GPU nondeterminism" — the easy, wrong
explanation — it was checked directly: MoGe-2 and SAM 2 were each re-run twice,
in separate process launches, and reproduced bit-identical outputs both times.
The real cause was `integration_benchmark.py` setting `AETHER_DATA_DIR` to an
isolated scratch directory (copied uncritically from Phase 13's pattern,
without checking that it also redirects `get_registry()`), so
`resolve_asset_metadata` was silently reading an **empty registry** and
producing wrong dimensions for exactly the two cases whose wall gap sat closest
to the 0.12 m threshold. Removed; the control now reproduces exactly, every
run. This is recorded because it is exactly the failure mode the whole program
has repeatedly warned about — an unexplained number that looked plausible until
it was checked against a frozen baseline.

## 4. Results, end to end **[M]**

| | |
|---|--:|
| Images | 21 |
| Objects grounded | 46 / 48 (2 UNKNOWN — floor itself UNKNOWN, correctly) |
| Objects placed in a Scene | **46 / 46 (100%)** |
| Scenes with zero hard `validate_scene` violations | 16 / 21 (76.2%) → **20 / 21 (95.2%) after P1** |
| Scene success (valid + fully placed + Blender ok) | 16 / 21 (76.2%) → **20 / 21 (95.2%) after P1** |
| Blender builds attempted / succeeded | **20 / 20 (100%)**, zero errors |
| Blender build time | 1.3–4.7 s, median ~1.5 s |
| Relations emitted | 9, all `AGAINST_WALL` (the only predicate with evidence) |
| Repairs attempted / cleared | 7 / 4 |
| Footprint reconstruction residual | median 0.124 m, p95 0.285 m, max 0.887 m |

## 5. The five invalid scenes, diagnosed **[M]**

| Cause | Count | Scenes |
|---|--:|---|
| `COLLIDES_OBJECT` between two independently-grounded objects | 10 | `s06_kitchen`, both `moodboard_room_living_room`, `moodboard_room_kitchen`, `moodboard_room_master_bedroom` |
| `COLLIDES_WALL` | 6 | 3 of the same 5 scenes |

**Finding 1 — dense multi-object scenes collide, because each object is
grounded independently.** Every colliding scene has 3–4 grounded objects
(stools at an island, a sofa+side-table+ottoman cluster, a sofa+TV-unit+coffee-
table cluster). Each `GroundingHypothesis` is built from its own mask alone,
with no knowledge of any other object in the frame — exactly the limitation
`architecture_decision.md` §6 predicted would need *measured* evidence before
building a constraint graph to fix it. That evidence now exists: **this is the
first phase in the whole program with a real, measured multi-object collision
rate to point at.** It does not, on its own, justify building RoomCraft's full
CAPS re-weighting machinery — the one crude repair rule tried here (nudge the
lower-confidence object 0.3 m away, re-validate once) already clears **4 of 7**
collisions in one pass, which is useful signal about how much a *cheap* fix
buys before reaching for a heavier one.

**Finding 2 — a genuine representation loss, not a bug.** The remaining
`COLLIDES_WALL` cases are on exactly the two highest-value recovered
positives from Phase 7 (a bed, a sofa) — objects whose largest residuals were
already visible (0.68 m and 0.89 m). Traced to the source: `moodboard_room_
master_bedroom`'s wall 0 has a fitted normal of `(0.060, 0.189, −0.980)` — an
**11° tilt from vertical** — which Phase 6's own tolerance (`WALL_VERTICALITY_
TOLERANCE_DEG = 25°`) correctly accepts as a usable wall. Production's `Wall`
and `Room.boundary` are strictly planar, XZ-only, with no tilt field at all.
Projecting a 3D footprint built against an 11°-tilted wall onto a flat XZ
rectangle folds that tilt into positional error proportional to the object's
size — small for a 0.4 m stool, large for a 2 m bed or sofa. **This is exactly
the kind of "does the representation lose information the photo path
produces" failure §42 asked this phase to find**, and it is a limitation of
production's `Wall` schema (never designed to hold a tilted wall, because a
brief-generated room is never tilted), not of the bridge or of Phase 6-9's
geometry.

The wall-centerline offset (§2's second row) was fixed as part of this run —
verified correct by the unit tests in `tests/test_spatial_architecture_bridge.py`
— and, taken alone, removes zero of these six violations, because the residual
from Finding 2 is an order of magnitude larger than the ~7.5 cm the offset
corrects. Both findings are reported because only one of them was fixable
without inventing a wall-tilt representation production does not have.

## 6. What this measures against §43/§45

| §43 metric | Result |
|---|---|
| Scene construction rate | 21 / 21 images produced a `Scene` |
| Fully placed rate | 46 / 46 (100%) |
| Wall-contact precision | unchanged from Phase 9 (control reproduced exactly): 77.8% |
| Floor correctness | unchanged from Phase 8: 2 UNKNOWN, 0 countertop-as-floor |
| Room-boundary correctness | approximate by construction (§4 of `architecture_decision.md`), not measurable against truth — no ground truth exists |
| Support | 46/46 `SUPPORTED_BY floor` implicit (mount="floor"); no on-surface case exists to test the untested path |
| Collision | **76.2% collision-free**, cause diagnosed per scene above |
| Clearance | not tested — no door/window openings exist in a single-photo scene |
| Blender success | **20 / 20 (100%)** |
| Read-back correctness | not re-measured here; Phase 13 already measured it at XY p95 0.015 m on brief-driven scenes using the same `build_manifest`/read-back code path |

Against §45's twelve architectural success criteria: 1 (no information loss) —
**mostly**, with Finding 2 as the one measured exception; 2 (provenance) —
**yes**, every object's `Confidence.source` names its weakest channel; 3
(explicit frames) — **yes**, unchanged from Phase 2; 4 (UNKNOWN survives) —
**yes**, floor UNKNOWN correctly propagates to 2 skipped objects; 5 (multiple
hypotheses coexist) — **yes**, `orientation_candidates` is never collapsed
until `best_orientation` is read; 6–10 (constraints/solver/validation/Blender/
read-back on one state) — **yes**, demonstrated by this run using unmodified
production code at every one of those steps; 11 (local repair) — **partially**,
one rule, 4/7 measured effective; 12 (serializable/replayable) — **yes**,
inherited from `Scene`'s existing `spec_version`/stable IDs.

## 7. Decision

**PARTIAL PASS**, and — unlike earlier phases — the "partial" is now the
*integration's* result, not an upstream primitive's. What changed: photograph-
derived scenes can be built, validated, and rendered by production code today,
now at **95.2% scene success** (up from 76.2% at this report's first
measurement, after the P1 collision-solving phase below), zero Blender
failures. What did not change: `Scene`, `validate_scene`, `build_manifest`,
Blender, the frozen Phase 6-9 geometry, labels, cases.

## 7a. Follow-up: P1 closed most of §5's dense-scene gap (2026-09-16)

`docs/spatial_architecture/collision.md` researched and implemented a
deterministic DFS-family collision resolver (`collision_solver.py`), matching
the algorithm family Holodeck/RoomCraft/HSM all converge on. Result: scene
success 16/21 → **20/21**; `COLLIDES_OBJECT` 10 → 2 (both in one scene);
`COLLIDES_WALL` 6 → 1. The one remaining failure was traced precisely: two
`tv_unit` groundings at the same wall position, residual and gap both
near-identical — a **duplicate perception-level detection**, not a placement
or collision-architecture failure; no positional resolution can be correct for
two groundings of what is very likely one physical object. §8's item 1 below
is resolved by this follow-up; item 2 (wall representation) remains open and
is now scoped as **P5** in the wider architecture program
(`docs/spatial_architecture/`).

## 8. Next step

One item from the original two remains open, plus one newly surfaced by P1:

1. ~~A collision-aware second pass for dense scenes~~ — **done, see §7a.**
2. **A wall-tilt field on `Wall`**, or an explicit decision that production
   walls are defined to be vertical and any photo-reconstructed wall beyond
   some small tilt should itself be UNKNOWN rather than silently flattened.
   This is a genuine architecture question for whoever owns `app/scene/schema.py`,
   not a research-code fix — surfaced here, not resolved here. Tracked as
   **P5** in `docs/spatial_architecture/`.
3. **Duplicate-object grounding** (new, from §7a): Phase 9's `ground_object`
   has no mechanism to notice that two groundings in the same image describe
   the same physical object. Not yet scoped into a numbered phase; noted here
   so it is not lost.

# Allure Spatial Engine — Executive Decision

**Date:** 2026-09-15 · **Status:** decision proposed, nothing implemented
**Full analysis:** `docs/research/spatial_engine_architecture_research.md`

---

## The decision in one paragraph

Build a **geometry-first, room-before-objects** spatial engine. Reconstruct the room's
metric structure from the reference image, fit the floor and wall planes, fuse with the
floor plan we already collect for true scale, then ground objects into that frame. Learned
models supply **perception and semantics only**. Every spatial decision — wall contact,
support, adjacency, collision, clearance, final pose — is **deterministic**. This is
Architecture B in the research document.

---

## Why, in one number each

We spent Phases 1c–1h trying to get geometric relations out of a vision-language model, in
every formulation we could construct. Our own measurements:

| Finding | Number |
|---|---|
| Forced-choice queries where the model named an object instead of `wall`/`unknown` | **78 / 78** |
| `AGAINST` relation accuracy | **0 / 30** |
| Binary wall gate on 3B — a constant function | **`true` 16 / 16** |
| Deterministic rules vs the model's binary chain, end-to-end | **57.1% vs 48.6%** |
| `SUPPORTED_BY`: rules vs model | **88.9% vs 33.3%**, model added value **0** times, destroyed it **5** |
| Best wall result ever achieved (7B, 32 objects, 16 scenes) | **14.1% false-wall** — 1 error in 7 |
| Queries where the deterministic engine is wrong — the only ones worth asking | model got **20%** right |

The conclusion is not "use a bigger model". It is that **"is this against a wall" is
arithmetic, not judgement** — once a wall plane exists. We never gave the system a wall.

---

## What we should build

1. **Room reconstruction first.** Metric point map → RANSAC floor plane → gravity alignment
   → RANSAC wall planes under a Manhattan prior → room polygon.
2. **Floor-plan fusion for metric scale.** We already collect floor plans and room
   dimensions. They resolve monocular scale ambiguity *exactly*. This is free accuracy
   sitting in the intake form and nobody publishing single-image work can use it.
3. **Object grounding by projection**, not by monocular 3D detection. Mask footprint →
   floor plane → `(x, z)`. With the floor known and mount type from our existing vocabulary,
   6-DoF pose collapses to **3 parameters**.
4. **A geometrically-grounded scene graph** where every edge carries **provenance** (was it
   computed, asserted or assumed?) and a **coordinate frame**, and where `against_wall`,
   `supported_by`, `near` and `overlaps` are **derived from geometry, never stored as
   opinions**.
5. **A constraint solver that owns final pose** — the existing compiler, extended with a
   constraint DSL and annealing refinement, seeded from observed poses.
6. **Asset normalisation** (`AssetSpatialMetadata`) — unglamorous, cheap, and the fix for a
   bug we already have on record.

## What we should NOT build

- ❌ **Any path where a model emits XYZ, rotation or scale.** The governing principle.
- ❌ **A bigger VLM for spatial relations.** Tested to exhaustion across four phases.
- ❌ **An end-to-end monocular 3D detector as the backbone.** Cube R-CNN reaches ~34.7%
  AP3D on SUN RGB-D — an objects-first architecture inherits that ceiling on every object.
- ❌ **Rigid-body physics simulation.** Non-deterministic; a design tool must reproduce.
- ❌ **A learned layout prior — yet.** Published work *generates* plausible rooms; we are
  *reconstructing a specific* room from a photo the client approved. Different problem.
- ❌ **Anything assuming a 24–80 GB GPU.**

---

## Models: initial, optional, rejected

### Use initially — all Apache-2.0, all self-hostable

| Model | Role | Licence |
|---|---|---|
| **Grounding DINO** | open-vocab 2D detection — our own best measured (IoU 0.680, centre error 1.29%) | Apache-2.0 ✔ |
| **Depth Anything V2 — Small (24.8M)** | relative depth for the MVP | Apache-2.0 ✔ |
| **SAM 2 (Hiera-B+, ~80M)** or MobileSAM | instance + architecture masks | Apache-2.0 ✔ |
| **qwen2.5vl:3b** | **semantics only** — type, material, colour, style, one `FACES` hint | keep, demoted |

### Optional / evaluate next

- **MoGe-2** or **UniDepthV2** — metric point maps. The upgrade that removes the need for
  stated dimensions. Licence check required.
- **SAM 3D Objects** (Meta, Nov 2025) — single image + mask → shape, pose, layout. The one
  recent result that could change the grounding design. **Meta "SAM License" — legal review
  before any use.**
- **VGGT** — multi-view future. **Base checkpoint is research-only**; commercial by
  application.

### Rejected, with reason

| Rejected | Reason |
|---|---|
| **Depth Anything V2 Base / Large / Giant** | **CC-BY-NC-4.0 — non-commercial.** Only Small is Apache-2.0. A plan that assumed DAv2-L cannot ship. |
| Grounding DINO 1.5 | API-only, no self-hosted path |
| RT-DETR | closed vocabulary |
| qwen2.5vl:7b in production | **2.70 GB CPU spill, 56.3% GPU residency** — cannot coexist with Blender on our hardware |

---

## Components that must be deterministic

**Non-negotiable.** Every one of these was measured failing when a model owned it, or is
already working because rules own it.

Floor plane · wall planes · room polygon · metric scale · object `(x, z)` · height and mount
· **`against_wall`** · **`supported_by`** · near / adjacent / overlaps · collision ·
clearance and accessibility · scale · **final pose** · asset normalisation.

**Learned, legitimately:** detection, segmentation, depth, camera intrinsics, object
identity, material/colour/style, asset retrieval, text intent — and **yaw as a *hint* only**,
since `FACES` was the single relation where the model beat the rules (+2 net).

The rule: **models perceive; geometry decides.**

---

## The first experiment

**Compute wall contact geometrically on the exact Phase 1g/1h dataset and compare head-to-head
against the measured 14.1% false-wall rate.**

- The benchmark **already exists**: 43 cases, 32 negatives, 16 scenes, hand-verified ground
  truth, Category A/B labels, and a VLM baseline with confidence intervals.
- **No training, no new annotation, no production change. About one day.**
- **Decisive either way.** Geometric false-wall near 0–5% validates the whole thesis on our
  own data. Near 14% means monocular depth is not accurate enough at 704×448 and floor-plan
  fusion must come first.
- It also settles the open Phase 1h question — whether 14.1% was capability or easy imagery
  — by running the geometric method on the historical negatives too.

**Gate to proceed with Architecture B: false-wall < 10%.**

---

## Why this architecture wins

1. **It removes the failure instead of mitigating it.** Wall contact stops being an opinion.
2. **The hard relation gets easier, not harder.** Room-first fits a few large planes to
   dense geometry — the best-conditioned estimate available. Objects-first inherits a ~35%
   AP3D ceiling on every object.
3. **It uses an advantage no competitor has** — the floor plan in our intake form.
4. **It upgrades the compiler rather than replacing it.** `_ordered`, `_pick_support`,
   `_relation_candidates`, `_wall_aligned_candidates`, SAT collision and door clearance all
   survive. We strengthen the side that was already winning 57.1% to 48.6%.
5. **It fails loudly.** Plane fits report inlier fraction; grounding reports depth coverage.
   Contrast the VLM, which reported `"high"` confidence on 56 of 78 answers including most
   of the wrong ones.
6. **Every initial component is Apache-2.0 and runs on 6 GB.** Licence traps avoided by
   construction.
7. **The moat is downstream of it.** Every completed project yields a (reference image,
   floor plan, **approved 3D scene**) tuple — the exact training signal for Architecture C's
   learned prior, generated as a by-product of doing business.

---

## Known gaps in this research

Stated plainly so they are not mistaken for settled:

- **VRAM and latency figures for MoGe-2, UniDepthV2, VGGT and SAM 3D are not published.**
  I could not verify them. 6 GB feasibility depends on exactly these numbers, so measuring
  them is **Step 0** of the roadmap — half a day, and it de-risks everything after.
- **Whether monocular depth is accurate enough at our 704×448 resolution is unknown.** It
  is the central open risk, and the first experiment is designed to answer it directly.
- Several 2026 papers surfaced during the search that postdate my reliable knowledge. They
  are listed in the research document as **leads to read, not as evidence**.

---

**Recommendation: adopt Architecture B. Run the first experiment before building anything
else. Do not train anything yet.**

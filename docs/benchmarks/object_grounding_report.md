# Phase 9 — Object Grounding

**Verdict: PARTIAL PASS.** Composing the frozen pieces — Phase 8 floor hypothesis,
Phase 6 wall gate, Phase 7 catalogue extent — into a candidate `ObjectGrounding`
produces a footprint for **46 of 48** objects (2 UNKNOWN, both because their floor
is UNKNOWN), **95.7%** of footprints lie inside the gated room, the pipeline is
**bit-deterministic** across two runs, and it costs **50 ms per object** on CPU.
Where a wall orients the footprint (31 of 46) it covers a median **95%** of the
object's own visible points; where no wall survives and orientation falls back
to a principal axis (15 of 46) it covers a median **24%**, which is not a
grounding anyone should place from. No ground-truth 3D positions exist, so
position, rotation and footprint-IoU error against truth are **not tested**.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/object_grounding_results.json`
**Scripts:** `research/spatial_engine/object_grounding.py`, `object_grounding_benchmark.py`
**Production code changed:** none. Dependencies changed: none.
`pytest -q` → 367 passed, 7 skipped, 30 xfailed.

Claims: **[M] measured**, **[I] inferred**, **[Q] qualitative**, **[N] not tested**.

## 1. Objective

Turn a mask, metric points, a floor hypothesis, a gated wall set and the asset's
physical size into a *candidate* grounding — footprint, support plane, room
position, depth, ranked orientation hypotheses, confidence, evidence — for the
constraint solver to consume. Not a placement.

## 2. What was built

`ObjectGrounding` with explicit placement classes. `FLOOR_STANDING` is fully
implemented: the footprint is a rectangle on the floor whose axis along the
selected wall's normal spans `[physical rear, physical rear + dimension]` — the
extent Phase 7 already computed — and whose axis along the wall is the
catalogue's other dimension, centred on the visible points. `WALL_MOUNTED`
computes wall-local coordinates. `CEILING_MOUNTED`, `SUPPORTED_ON_SURFACE`,
`BUILT_IN`, `FREE_HANGING` return UNKNOWN with the reason: no such object exists
in the benchmark to validate them against, and untested code is not pretended.

The floor is chosen by the Phase 8 **do-no-harm** rule; when the fitter's floor
is implausible and nothing replaces it, the floor is UNKNOWN and so is every
grounding on it (§37 of the brief).

## 3. Results — 48 cases **[M]**

| | |
|---|--:|
| Grounded (footprint produced) | **46 / 48** (95.8%) |
| UNKNOWN | 2 — `s07.bar_stool.0/1`, `FLOOR_FAILURE` (floor UNKNOWN) |
| Placement classes seen | 48 `FLOOR_STANDING` (the benchmark's vocab types are all floor-standing, including the TV annotated as `tv_unit`) |
| Support consistent (lowest visible points within [−0.15, 0.30] m of the floor) | 36 / 46 (78.3%) |
| Base occluded (lowest visible point > 0.30 m up) | 2 |
| Footprint inside the gated room | **44 / 46 (95.7%)** |
| Orientation known (a wall survived the gate) | 31 / 46 |
| Visible points covered by the footprint — orientation known | median **0.951**, p25 0.681 |
| Visible points covered — principal-axis fallback | median **0.243**, p25 0.154 |
| Wall contact | 7 / 24 / 2 / 3, 12 UNKNOWN — the Phase 7 primary on the Phase 8 floor policy |
| Determinism | 48 / 48 identical positions on a second run |
| Latency | **50 ms** median per object, CPU; no VRAM |
| Position / rotation / footprint IoU vs truth | **[N]** no ground truth exists |

## 4. Failure analysis **[M]**

The fallback path is the weak point, and it is confined to one condition: **no
wall survived the Phase 6 gate**. Those 15 groundings (all generated scenes:
s08, s10, s11, s15, s17 chairs and tables) anchor a rectangle to the visible near
edge along an arbitrary principal axis, and the rectangle misses most of the
evidence. Their confidence is already scaled to 0.4× and their orientation is
reported UNKNOWN; the honest product behaviour is to treat them as *position
only, orientation unknown*, or to abstain. Historical (real-photo) groundings
cover a median 0.968 of their points.

Support consistency at 78% reflects two things: masks that include the object's
upper surface only (stools tucked under counters), and the vanity in the mirror
scene at −0.30 m. Neither is a grounding fault; both are flagged.

## 5. Decision

The brief's §41 target — *high-confidence placement on representative catalogue
assets* — is met for wall-oriented floor-standing objects on real photographs
and not met for the no-wall fallback. **PARTIAL PASS.** What changed: a candidate
grounding exists with provenance, frames (canonical camera frame throughout),
confidence and evidence. What did not change: production code, labels, the
frozen upstream phases.

## 6. Next step

The fallback needs an orientation source that is not a wall: the room's
Manhattan axes from the *floor and any* fitted wall, or the object's own asset
forward axis fitted to the mask silhouette. Until then a no-wall grounding
should be handed to the solver as a position with UNKNOWN orientation.

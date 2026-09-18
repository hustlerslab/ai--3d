# Phase 8 — Floor Reconstruction as a Scored Hypothesis

**Verdict: PARTIAL PASS.** Countertop-as-floor on the frozen benchmark goes from
**2 of 2 to 0 of 2** — both kitchen "floors" are now rejected — but neither is
*replaced*: in both images no plausible floor is visible, and the honest answer
is UNKNOWN. Coverage is 17 of 21. Object contact on the chosen floors rises from
0.762 to 0.897. Downstream, Phase 7's wall contact is unchanged on the floor
benchmark's own control (7/25/3/3), and the Phase 9 pipeline — which treats an
implausible fitter floor with no replacement as UNKNOWN — abstains on the two
s07 stools and reads 7/24/2/3 (precision 77.8%, false-wall 7.7%).

**A retraction, recorded rather than hidden.** An earlier version of this report
claimed s07's floor was *fixed* at 1.31 m and credited it with the downstream
gain. A synthetic unit test then showed the candidate orientation rule was wrong:
it oriented a plane by the side the scene's median point lay on, and for an
elevated surface most of the scene is *below* it. Under gravity orientation the
"1.31 m floor" in s07 is the **ceiling** (normal up, 69% of the scene beneath it,
camera 1.31 m under it). The fix was an artefact and is withdrawn; the numbers
below are from the corrected rule.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/floor_results.json`
**Scripts:** `research/spatial_engine/floor_candidates.py`, `floor_benchmark.py`
**Production code changed:** none. Dependencies changed: none.
`pytest -q` → 367 passed, 7 skipped, 30 xfailed (12 new research tests).

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**,
**[N] not tested**.

---

## 1. Objective and baseline

`fit_room` takes the floor as the largest horizontal RANSAC plane in the lower
45% of the image. Phase 6 found that plane to be the **countertop** in both
kitchens (camera 0.33 m and 0.63 m above it), and Phase 7 traced two of its
three false walls and two of its three misses to those images. Baseline, frozen:
that floor and Phase 7's result on it — **7/25/3/3, 10 UNKNOWN**, reproduced
exactly at the start of every run. **[M]**

## 2. Method

Sequential horizontal RANSAC over the **whole** image, up to five candidates,
each oriented **along gravity (+Y up)** and measured against independent
evidence with weights written down once from what each means physically:

| Evidence | Weight | What it encodes |
|---|--:|---|
| gravity alignment | 1.0 | normal close to +Y |
| spatial extent | 1.0 | support as a fraction of the scene |
| lower-image support | 1.0 | floors are at the bottom of a photograph |
| camera height plausibility | 1.5 | 1–2 m above a floor; soft range 0.6–2.6 m |
| object contact | 1.5 | floor-standing objects' lowest points within [−0.15, 0.30] m |
| continuity | 0.5 | one connected region |
| **below fraction** (penalty) | 2.0 | **a floor has nothing beneath it; a countertop has cabinet fronts and the real floor** |
| elevation (penalty) | 1.5 | height above the lowest *plausible* floor candidate |

Categories: `ROOM_FLOOR`, `ELEVATED_ARCHITECTURAL_SURFACE`, `FURNITURE_SURFACE`,
`IMPLAUSIBLE_DEPTH` (camera height outside the soft range — depth through glass,
or a ceiling), `UNKNOWN`. Selection is UNKNOWN when no candidate is a floor, when
the best implies an implausible camera height, or when the top two floors are
within 0.08.

### Two corrections, both from candidate features, neither from labels **[M]**

1. The first pass abstained on 15 of 21 images because the elevation reference
   was the lowest plane of any height — in 13 images a plane 3–5 m below the
   camera, MoGe reading depth **through a window**. The reference must now be a
   plausible floor itself.
2. The second pass oriented normals by the scene median and mistook s07's
   ceiling for a floor (above). Normals are now oriented along +Y; the scene
   median is consulted only for near-horizontal-normal planes where +Y says
   nothing. A synthetic test (`tests/test_spatial_engine_research.py`) now pins
   both behaviours: a countertop with a cabinet beneath it is classed elevated,
   and a scene whose only horizontal plane is 5 m below the camera is UNKNOWN.

## 3. Results — 21 images **[M]**

| | Baseline fitter | Scored hypothesis |
|---|--:|--:|
| Floor decided | 21 | **17** (4 UNKNOWN) |
| Object contact, mean fraction | 0.762 | **0.897** |
| Countertop selected as floor (eye-verified kitchens) | **2 / 2** | **0 / 2** |
| Countertop replaced by a plausible floor | — | 0 / 2 |
| Fitter's plane ranked first among candidates | — | 15 / 21 (third in s07; absent in 5) |
| Latency per image (5 RANSAC fits, CPU) | — | 4.8 s median, 6.7 s p95 |

**The four abstentions.** `s07_kitchen` and `moodboard_room_kitchen`: the
countertop is rejected (`IMPLAUSIBLE_DEPTH` at 0.47 m and 0.63 m — the camera
cannot be that close to a floor) and every other candidate is either the
ceiling, a surface with the scene beneath it, or through-the-window depth. The
real floor is a strip under the stools too small to fit. `s08` and `s16`: grand
rooms with floor-to-ceiling glazing; every horizontal candidate is through-glass
depth. All four are correct abstentions. **[M, with Q from the Phase 6 overlays]**

**Three floors differ from the fitter's** (s01 1.25 → 1.38 m, s13 0.69 → 0.84 m,
s15 1.22 → 2.38 m at 26° tilt). None is accepted by the **do-no-harm** rule —
replace the fitter's floor only when the fitter's is implausible or the
candidate strictly wins on object contact — because none wins and none of the
three fitter floors is implausible. The s11 regression the earlier orientation
produced (2.25 m, contact 0) no longer occurs: s11 keeps 1.57 m, contact 0.75.

**On the plausibility band.** Five correct floors sit at 0.88–0.98 m with object
contact 1.0 — real floors, low camera. The [1.0, 2.0] m band under-reports them;
the soft band admits them. Recorded, not tuned. **[M]**

## 4. Downstream **[M]**

| Phase 7 primary on… | TP/TN/FP/FN | UNKNOWN | false-wall | precision | AUC |
|---|--:|--:|--:|--:|--:|
| baseline floor (control) | 7/25/3/3 | 10 | 10.7% | 70.0% | 0.8929 |
| do-no-harm (accepts nothing) | 7/25/3/3 | 10 | 10.7% | 70.0% | 0.8929 |
| **Phase 9 pipeline: implausible fitter floor + no replacement → floor UNKNOWN** | **7/24/2/3** | **12** | **7.7%** | **77.8%** | — |

The floor benchmark's own control keeps the fitter's room when nothing is
accepted, so it shows no change. The grounding pipeline applies the policy the
brief asks for — an implausible floor with no replacement is UNKNOWN — and the
two s07 stools abstain: the false wall disappears and one correct NO becomes an
abstention. That is the legitimate downstream effect of this phase, and it is
smaller than first claimed.

## 5. Decision

| Target (§15 / §41) | Result |
|---|:--|
| Countertop false-floor 0% on the frozen benchmark | ✓ **0 of 2** selected — by rejection, not replacement |
| Useful coverage | ✓ 17 / 21; all 4 abstentions genuinely floorless fits |
| Table false-floor rate | **[N]** no table-as-floor case in the benchmark |
| Angular / offset / camera-height error vs truth | **[N]** no ground-truth floor exists |

**PARTIAL PASS.** The defect is contained (a countertop can no longer be the
floor) but not repaired (no floor is found where the fitter failed), and the
first claimed repair was an error. What changed: the floor is a scored,
gravity-oriented hypothesis with UNKNOWN. What did not change: `fit_room`, walls,
gate, threshold, extent, labels, cases, production code.

## 6. Next step

Where the floor is UNKNOWN the whole grounding is UNKNOWN, correctly. Recovering
a floor in s07-type shots — camera above a counter, floor visible only as a
strip — needs evidence the point cloud does not carry: a room-height prior or a
second view. Not a scoring problem. The through-glass depth that caused the first
failure will recur in every downstream consumer of MoGe points until glazing is
masked or flagged.

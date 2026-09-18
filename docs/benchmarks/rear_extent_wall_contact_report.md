# Phase 4 — Rear-Extent Wall Contact

**Verdict: FAIL.** Rear extent is worse than the nearest visible surface on every
headline metric, and the reason is not a bug. It is that **the rear extent of a
piece of furniture is not observable in a single-view point cloud of visible
surfaces.** In 32 of 48 cases the new statistic returned a value *identical to the
old one*, because for an object lying entirely on one side of a wall the
extremal point toward that wall and the nearest point to it are the same point.
The object's back is occluded; it is not in the data; no statistic over the data
can recover it.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/rear_extent_benchmark.json`
**Scripts:** `research/spatial_engine/rear_extent_wall_contact.py`,
`research/spatial_engine/rear_extent_benchmark.py`
**Production code changed:** none. Dependencies changed: none.
`pytest -q` → 355 passed, 7 skipped, 30 xfailed, before and after.

Each claim below is tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**
or **[N] not tested**.

---

## 1. Objective

Phase 3 established that the wall-contact primitive measures the wrong quantity:
the object's nearest visible surface rather than its extent toward the wall. This
phase tests the single hypothesis that follows —

> Wall contact should be determined using the object's rear extent along the wall
> normal rather than its nearest visible surface.

— and nothing else.

---

## 2. Phase 3 baseline reproduction **[M]**

Variants A and B re-run the two previous phases inside this harness. Both
reproduced exactly; the run is written to abort and report a reproducibility
failure rather than a result if they do not.

| | Stored | Re-run here | |
|---|--:|--:|:--|
| Phase 2 false-wall | 24.3% | **24.3%** | ✓ |
| Phase 2 NO recall | 75.7% | **75.7%** | ✓ |
| Phase 2 AUC | 0.7174 | **0.7174** | ✓ |
| Phase 3 false-wall | 21.6% | **21.6%** | ✓ |
| Phase 3 NO recall | 78.4% | **78.4%** | ✓ |
| Phase 3 AUC | 0.7445 | **0.7445** | ✓ |
| Per-case decision drift vs stored Phase 3 | — | **0 of 48** | ✓ |

The control arm is intact, so any movement between arms is attributable to the
statistic.

---

## 3. Frozen variables

| | |
|---|---|
| Cases / labels | the same 48, unchanged |
| Geometry | MoGe-2 `Ruicheng/moge-2-vitl`, unchanged |
| Segmentation | SAM 2.1 Hiera base-plus, unchanged, same selection rule |
| Wall fitting | RANSAC seed 20260915, 400 iters, box-based exclusion |
| Threshold | 0.12 m, unchanged, used for the gate |
| Percentile | **10**, reused from Phase 3 |
| Production code | untouched |

All four variants share **one** MoGe-2 pass and **one** room fit per image, so the
wall planes are not merely equal across arms — they are the same objects. This is
stricter than Phase 3, which ran the geometry per-arm and relied on determinism.

**Percentile choice, declared before the run.** The brief's instruction was to
prefer reusing Phase 3's convention over inventing a hyperparameter, so the
primary arm uses the 10th percentile of the *signed, room-oriented* projection —
the same 10, with the projection reversed rather than absolute. A percentile
sensitivity sweep (§15) is reported as a diagnostic and decides nothing.

---

## 4. Geometric definition

For wall plane `n · p + offset = 0` and an orientation sign `s` chosen so that
positive points from the wall into the room:

```
q_i          = s * (n · p_i + offset)        projection onto the wall normal
rear extent  = percentile(q, 10)             extremal object surface toward the wall
gap          = max(0, rear extent)           a negative rear extent means the object
                                             reaches past the plane — contact, not a gap
```

Camera Z is not used. Image-space extremes are not used. Bounding-box dimensions
are not used.

### A documentation defect found in production-candidate code **[M]**

`app/spatial/planes.py:571` documents its return value as *"the distance from the
object's REAR surface to the nearest usable wall plane"*. The code computes
`percentile(np.abs(signed), 10)` — the nearest surface on **either** side. The
docstring describes Phase 4's intent; the code implements Phase 3's. Recorded
here, not fixed: the module is frozen for this phase. Worth correcting before
that function is ever integrated, because the comment would otherwise certify
behaviour the code does not have.

---

## 5. Wall-normal convention **[M]**

A RANSAC plane's normal may point either way. The interior direction is taken
from **room geometry**: the side of the plane on which the room's own median
surface point lies. The camera position is not used — it is not part of the
frozen Phase 2 geometry definition, and "the side the camera is on" is a
different question from "the side the room is on".

Where the room centroid lies within 1% of the scene's extent of the plane, the
sign is a coin toss; orientation is reported UNKNOWN and the wall is skipped
rather than guessed. **No case in the 48 hit that path** — every evaluated plane
was orientable. The sign convention is unit-checked against a synthetic room
where the answer is known by construction (`rear_extent_wall_contact.py`
`_self_check`), which also demonstrates the failure it exists to prevent: an
object pushed 0.6 m *through* a wall reports `signed = −0.450` correctly, while
the absolute statistic folds it to a plausible-looking `+0.049`.

---

## 6. Rear-extent algorithm

Structurally a copy of the frozen path. Identical coverage floor, identical
32-point minimum, identical one-sided rejection of planes that cut through the
object, identical nearest-wall selection, identical threshold routing. **One line
differs**: `percentile(|signed|, 10)` becomes `percentile(s · signed, 10)`,
clamped at zero.

---

## 7. Variant comparison **[M]**

| | A bbox + nearest | B SAM + nearest | **C SAM + rear** | D bbox + rear |
|---|--:|--:|--:|--:|
| | *Phase 2* | *Phase 3* | ***Phase 4*** | *diagnostic* |
| **False-wall** | 24.3% [13.4, 40.1] | 21.6% [11.4, 37.2] | **37.8% [24.1, 53.9]** | 37.8% [24.1, 53.9] |
| NO recall | 75.7% | 78.4% | **62.2%** | 62.2% |
| Positive recall | 54.5% | 18.2% | **18.2%** | 63.6% |
| Precision | 40.0% | 20.0% | **12.5%** | 36.8% |
| F1 | 46.2% | 19.0% | **14.8%** | 43.8% |
| **Balanced accuracy** | 65.1% | 48.3% | **40.2%** | 62.9% |
| **Separation AUC** | 0.7174 | 0.7445 | **0.6118** | 0.5885 |
| UNKNOWN | 0% | 0% | **0%** | 0% |
| TP / TN / FP / FN | 6 / 28 / 9 / 5 | 2 / 29 / 8 / 9 | **2 / 23 / 14 / 9** | 7 / 23 / 14 / 4 |

C is worse than B on false-wall (+16.2 points), NO recall (−16.2), precision,
F1, balanced accuracy and AUC, at identical positive recall. The hypothesis is
**not supported**.

Separating the two effects, as variant D exists to do:

- **C vs B** (statistic alone, SAM grounding): false-wall 21.6 → 37.8%. Worse.
- **D vs A** (statistic alone, bbox grounding): false-wall 24.3 → 37.8%. Worse,
  by a similar margin. **[M]**
- The statistic damages negatives by roughly the same amount under either
  grounding, so the effect is the statistic's, not an interaction with
  segmentation. **[I]**

One genuine finding hides in D: **bbox + rear extent has the best positive recall
of any arm (63.6%)** and the best solid-object recall (60.0% vs A's 50.0%, B's
10.0%). Diagnostic only, never a production candidate — it inherits every
bounding-box defect Phase 3 documented. **[M]**

---

## 8. Why it fails: the rear extent is not observable **[M]**

**In 32 of 48 cases the Phase 4 distance equals the Phase 3 distance exactly** —
not approximately, to the stored digit. Examples from the tracked nine:
`s05.armchair.0` 1.148 → 1.148; `s02.ottoman.0` 1.209 → 1.209;
`preserved.master_bedroom.bed.0` 0.451 → 0.451.

The reason is arithmetic. If every object point lies on one side of the plane,
then `s · signed = |signed|` for every point, so the two percentiles are the same
number. Reversing the projection is a **no-op wherever the geometry is
well-posed**. **[M]**

And that is the whole problem. MoGe-2 returns *visible surfaces*. A sofa against a
wall presents its front, its seat and the top of its back; its rear face is
occluded by the sofa itself and is simply absent from the point cloud. There is
no set of points behind the visible surface for a percentile to find. **The
quantity the hypothesis asks for does not exist in the input.** **[I, from the
32/48 exact identity]**

### Where the two statistics *do* differ, the difference is spurious **[M]**

All 16 changed cases changed for one reason: the raw rear extent went **negative**
and was clamped to a zero gap.

| | |
|---|--:|
| Cases with negative rear extent | **13 / 48** |
| of which labelled *not* against a wall | **12** |
| forced to decide YES by the clamp | **13** |
| and thereby **wrong** | **12** |

Those 12 are the entire regression (FP 8 → 14). And the magnitudes show these are
not near-misses:

| Case | rear extent | projection range | Phase 3 nearest |
|---|--:|--:|--:|
| `s10.chair.2` | **−4.500 m** | [−5.62, −1.95] | 2.127 m |
| `s10.chair.1` | **−3.780 m** | [−4.60, −2.39] | 2.329 m |
| `s06.bar_stool.0` | **−1.729 m** | [−1.82, −0.15] | 0.640 m |

A chair is not 4.5 m behind a wall. The projection range is *entirely negative*:
the object lies wholly on the opposite side of that plane from the room's own
centroid. Such a plane is not a wall behind the object at all. **[M]**

The formulation then makes it worse in two compounding steps: clamping a negative
to zero converts "impossible geometry" into "perfect contact", and selecting the
minimum gap across candidate walls makes the algorithm actively *prefer* whichever
plane the object most implausibly penetrates. **[I]**

The existing `MIN_ONE_SIDED_FRACTION` check does not catch this — it rejects
planes that cut *through* an object, and these planes do not; the object is
cleanly on one side, just the wrong one. **[M]**

---

## 9. Generated vs historical **[M]**

| | A | B | **C** |
|---|--:|--:|--:|
| Generated negatives (32), false-wall | 28.1% | 15.6% | **40.6%** |
| Historical negatives (5), false-wall | 0.0% | 60.0% | **60.0%** |

The generated scenes carry the regression. The historical negatives were already
broken by Phase 3 and rear extent neither helps nor worsens them. n = 5 on the
historical side carries almost no statistical weight. **[M]**

---

## 10. Category A / B **[M]**

| | A | B | **C** |
|---|--:|--:|--:|
| Category A false-wall | 21.1% | 10.5% | **31.6%** |
| Category B false-wall | 27.8% | 33.3% | **44.4%** |

Category B (wall-backed context) remains the harder category under every method,
consistent with Phases 1h and 3. **[M]**

---

## 11. Object-type analysis **[M]**

Variant C. All bar stools, chairs, armchairs and ottomans in this benchmark are
labelled *not* against a wall, so for those rows only false-wall is defined.

| Type | n | neg | pos | false-wall | pos recall | median distance |
|---|--:|--:|--:|--:|--:|--:|
| **bar stool** | 9 | 9 | 0 | **88.9%** | — | **0.000 m** |
| **chair** | 10 | 10 | 0 | **60.0%** | — | 0.038 m |
| armchair | 8 | 8 | 0 | 0.0% | — | 1.519 m |
| ottoman | 3 | 3 | 0 | 0.0% | — | 1.674 m |
| table | 8 | 5 | 3 | 0.0% | 33.3% | 0.625 m |
| cabinet | 4 | 0 | 4 | — | 25.0% | 0.125 m |
| sofa | 3 | 0 | 3 | — | 0.0% | 0.624 m |
| other | 3 | 2 | 1 | 0.0% | 0.0% | 0.490 m |

**Bar stools collapse to a median distance of exactly 0.000 m** — eight of nine
clamped. Chairs follow at 60%. Armchairs and ottomans, whose masks are compact
and whose geometry is unambiguous, are unaffected at 0%. The damage is
concentrated in exactly the object types whose point clouds are thin, scattered
and near other structure. **[M]**

---

## 12. The nine Phase 2 false-wall cases **[M]**

All nine are labelled *not* against a wall.

| Case | Object | P2 bbox nearest | P3 SAM nearest | **P4 SAM rear** | raw rear | P2 / P3 / P4 | Verdict |
|---|---|--:|--:|--:|--:|---|---|
| `s05.armchair.0` | armchair | 0.013 | 1.148 | **1.148** | +1.148 | YES/NO/NO | unchanged correct |
| `s02.ottoman.0` | ottoman | 0.015 | 1.209 | **1.209** | +1.209 | YES/NO/NO | unchanged correct |
| `s09.chair.0` | chair | 0.047 | 1.096 | **1.096** | +1.096 | YES/NO/NO | unchanged correct |
| `s01.armchair.0` | armchair | 0.057 | 1.104 | **1.104** | +1.104 | YES/NO/NO | unchanged correct |
| `s16.chair.0` | chair | 0.014 | 0.012 | **0.009** | +0.009 | YES/YES/YES | persistent |
| `s07.bar_stool.0` | bar stool | 0.009 | 0.065 | **0.000** | −0.354 | YES/YES/YES | persistent |
| `s07.bar_stool.1` | bar stool | 0.028 | 0.016 | **0.000** | −0.367 | YES/YES/YES | persistent |
| `s17.chair.0` | chair | 0.045 | 0.038 | **0.000** | −0.539 | YES/YES/YES | persistent |
| `s17.chair.2` | chair | 0.080 | 0.222 | **0.000** | −0.567 | YES/NO/**YES** | **newly broken** |

**Repaired 0 · persistent 4 · newly broken 1 · unchanged correct 4.**

Not one case was repaired. The four Phase 3 repaired (positive rear extents) carry
through unchanged, which is the identity of §8 in action. The one case Phase 3 had
fixed, `s17.chair.2`, is broken again by a −0.567 m clamp. The nine-case analysis
does not support the hypothesis. **[M]**

---

## 13. The cases Phase 3 newly broke **[M]**

The brief asks for the four new false walls. The run identifies newly-broken
cases at runtime as "Phase 2 correct → Phase 3 wrong", which finds **nine**: the
four false walls Phase 3 reported, plus five missed positives Phase 3 also
created. Both are reported; the four are the brief's set.

| Case | Kind | P2 | P3 | **P4** | P2/P3/P4 | Verdict |
|---|---|--:|--:|--:|---|---|
| `hist_neg.kitchen.bar_stool.0` | false wall | 0.927 | 0.079 | **0.000** | NO/YES/YES | persistent |
| `hist_neg.kitchen.bar_stool.1` | false wall | 0.876 | 0.047 | **0.000** | NO/YES/YES | persistent |
| `hist_neg.kitchen.bar_stool.2` | false wall | 0.776 | 0.015 | **0.000** | NO/YES/YES | persistent |
| `s17.chair.1` | false wall | 1.069 | 0.079 | **0.066** | NO/YES/YES | persistent |
| `preserved.living_room_a.sofa.1` | missed positive | 0.044 | 0.285 | **0.285** | YES/NO/NO | persistent |
| `preserved.living_room_b.tv_unit.0` | missed positive | 0.010 | 0.122 | **0.122** | YES/NO/NO | persistent |
| `preserved.master_bedroom.bed.0` | missed positive | 0.035 | 0.451 | **0.451** | YES/NO/NO | persistent |
| `preserved.master_bedroom.bedside_table.0` | missed positive | 0.045 | 0.252 | **0.252** | YES/NO/NO | persistent |
| `preserved.master_bedroom.bedside_table.1` | missed positive | 0.061 | 0.196 | **0.196** | YES/NO/NO | persistent |

**Restored by rear extent: 0 of 9 (0 of the 4 false walls).** Every one of the
five missed positives is byte-identical between P3 and P4 — these are exactly the
solid objects whose backs are occluded, and they are the cases the hypothesis was
designed to rescue. It cannot: the data needed is not there. **[M]**

---

## 14. Distance distributions **[M]**

| Variant | | median | p25 | p75 |
|---|---|--:|--:|--:|
| A bbox + nearest | positives | 0.097 | 0.044 | 0.318 |
| | negatives | 0.640 | 0.143 | 1.666 |
| B SAM + nearest | positives | 0.252 | 0.129 | 0.453 |
| | negatives | 0.883 | 0.398 | 1.889 |
| **C SAM + rear** | positives | **0.252** | 0.125 | 0.453 |
| | negatives | **0.584** | **0.000** | 1.674 |

Rear extent leaves positives essentially untouched (0.252 = 0.252) and drags
negatives *toward* the wall (0.883 → 0.584 median, p25 → 0.000). Separation gets
worse from both directions at once, which is the AUC drop 0.7445 → 0.6118.
Phase 3's question — whether rear extent creates stronger separation — is answered
**no**, measured, with the direction not assumed in advance. **[M]**

---

## 15. Threshold and percentile diagnostics **[M]**

*Both are diagnostic. The gate used the frozen 0.12 m and the frozen 10th
percentile. No production threshold was changed.*

**Threshold sweep, arm C.** Best balanced accuracy **69.3% at 0.50 m**, where
false-wall is 43.2%. False-wall never falls below **35.1%** at any threshold.
Compare the ceilings: Phase 2 74.7%, Phase 3 74.7%, Phase 4 **69.3%**. Rear extent
lowers the ceiling. **<20% false-wall is not achievable at any threshold.**

**Percentile sensitivity.**

| Percentile | false-wall | NO recall | pos recall | bal. accuracy |
|--:|--:|--:|--:|--:|
| 1 | 40.5% | 59.5% | 54.5% | **57.0%** |
| 2 | 37.8% | 62.2% | 36.4% | 49.3% |
| 5 | 37.8% | 62.2% | 36.4% | 49.3% |
| **10 (frozen)** | **37.8%** | **62.2%** | **18.2%** | **40.2%** |
| 25 | 35.1% | 64.9% | 9.1% | 37.0% |

No percentile rescues the method — every one is worse than Phase 3's 48.3%
balanced accuracy, and false-wall stays above 35% throughout. The frozen choice
was not an unlucky one: it sits mid-range, and the sweep's spread (37.0–57.0%)
never reaches the baseline. **[M]**

---

## 16. Stability **[M]**

Two complete independent passes — SAM re-run, MoGe re-run, rooms re-fitted,
all variants recomputed.

| | |
|---|--:|
| Mask pixel disagreements | **0 / 48** |
| Wall-plane max absolute difference | **0.0** |
| Rear-extent max absolute difference | **0.0** |
| Decision disagreements | **0 / 48** |
| **Deterministic** | **yes** |

The pipeline is bit-deterministic end to end. The Phase 4 result is not noise.
**[M]**

---

## 17. Failure analysis

Against the brief's list:

| | Cause | Verdict |
|---|---|---|
| **D** | **Rear-surface visibility** | **PRIMARY.** The rear extent is not present in a visible-surface point cloud. Proven by 32/48 exact identity with Phase 3. **[M]** |
| **E** | **Occlusion** | **PRIMARY, same mechanism.** The back of a solid object against a wall is self-occluded — the five missed positives are byte-identical across P3/P4. **[M]** |
| **A** | Wall-normal orientation | **SECONDARY.** No plane failed to orient, but 13 cases produced objects lying wholly on the far side of a candidate plane from the room centroid, at up to −4.5 m. The orientation is computed correctly; those planes are not walls behind those objects, and nothing rejects them. **[M]** |
| **G** | Wall-distance definition | Still wrong, as Phase 3 concluded — but **not fixable this way**. Phase 4 changes the definition and makes it worse. **[M]** |
| **B** | Sparse MoGe points | Not the cause. Depth coverage was above the floor in all 48 cases and 0 cases were UNKNOWN. **[M]** |
| **C** | Segmentation geometry | Not the cause. The C-vs-B and D-vs-A deltas are comparable, so the statistic damages negatives independently of grounding. **[M]** |
| **F** | Furniture topology | A **correlate, not a cause**. Bar stools 88.9% and chairs 60.0% carry the damage while armchairs and ottomans sit at 0.0%; the difference tracks how scattered the point cloud is, not the statistic's validity. **[M]** |

**The single sentence.** Phase 3's diagnosis was right that the measured quantity
is wrong, and wrong to assume the right quantity was available. Wall contact
depends on where the object's *back* is; a single view records only what faces
the camera; so the decisive quantity is unobservable, and every statistic over
visible points — nearest, rear, or otherwise — is estimating something else.
**[I]**

---

## 18. Decision gate

**FAIL**, on seven of eight conditions.

| Condition | Result |
|---|:--|
| 1. False-wall < 20% at the frozen threshold | ✗ **37.8%** |
| 2. No major regression in positive recall | ✗ 18.2%, equal to Phase 3, far below Phase 2's 54.5% |
| 3. UNKNOWN 0 or negligible | ✓ **0%** |
| 4. Improvement reproducible | ✗ there is no improvement; the *result* is reproducible — bit-identical across two passes |
| 5. Improvement attributable to rear extent | ✗ the *regression* is: 12 of 13 clamped negatives are wrong |
| 6. The nine original cases materially improve | ✗ **0 repaired, 4 persistent, 1 newly broken** |
| 7. The four Phase 3 breakages not worsened | ✗ 0 of 4 restored; all persistent |
| 8. No major new object-type failure | ✗ **bar stools 88.9%**, chairs 60.0% |

Not integrated. No threshold tuned, no case removed, no synthetic case added, no
label changed, no model retrained, no new model introduced, no production file
modified.

---

## 19. Recommendation

**Do not pursue rear extent from single-view depth.** The experiment did not fail
on tuning; it failed on observability, and no percentile, threshold or grounding
fixes an absent measurement.

The finding reframes Phase 3's. Phase 3 called the bounding box's wall pixels a
crutch. They were a crude *amodal cue*: the box spanned object-to-wall, so a box
touching the wall meant the object plausibly did. Removing it removed the only
thing in the pipeline that knew anything about the occluded region. That is why
variant D — bbox + rear extent — still has the best solid-object recall of any
arm (60.0%). **[I]**

What the decision actually needs is the object's **amodal 3D extent**: an oriented
3D box including the unobserved back. That keeps `MODELS PERCEIVE, GEOMETRY
DECIDES` intact — perception supplies the object's extent, geometry still computes
the distance and makes the call.

**Before building that, establish the ceiling.** Three phases have now improved
the inputs and left the decision at roughly chance. The next experiment should be
cheap and diagnostic: hand-measure an oracle 3D extent for a subset of the 48 and
compute the wall decision from it. That answers "is this benchmark winnable with
perfect object extent?" before any model is chosen. If the oracle cannot do it,
the fault is in the benchmark or the wall planes, and no amount of perception will
help. **[N — not tested; proposed]**

Two secondary items, both measured here and worth fixing whenever this primitive
is next touched:

- **Reject planes the object lies behind.** A candidate wall whose object
  projection is entirely negative is not a wall behind that object. 13 cases hit
  this; the current code accepts them and the min-gap rule prefers them. **[M]**
- **The `planes.py:571` docstring** describes rear-surface behaviour the function
  does not implement (§4). **[M]**

---

## 20. Production readiness

Not claimed, and not tested. This phase validates one primitive and it did not
pass. Object grounding, coordinate placement, the spatial graph, asset
normalisation, constraint solving, collision validation and Blender integration
are all untouched and unevaluated. **[N]**

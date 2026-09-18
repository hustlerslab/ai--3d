# Phase 3 — segmentation object grounding

**Question:** does replacing the bounding box with a SAM 2 segmentation mask fix
the wall-contact failure Phase 2 left behind?

**Answer:** no. It fixes five of the nine failures, breaks four others, and in
the process exposes a *second* fault that the bounding box had been accidentally
concealing. The phase **fails its gate**, and it is the most informative failure
so far.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/segmentation_benchmark.json`
**Scripts:** `research/spatial_engine/segmentation_grounding.py`,
`research/spatial_engine/segmentation_benchmark.py`
**Production code changed:** none. `pytest -q` → 355 passed, 7 skipped, 30 xfailed,
before and after.

---

## 1. What was held constant

The only intended experimental change was the object footprint.

| | Variant A | Variant B |
|---|---|---|
| **Object footprint** | **annotated bounding box** | **SAM 2 mask** |
| Cases | the same 48 | the same 48 |
| Labels | unchanged | unchanged |
| Geometry model | MoGe-2 `Ruicheng/moge-2-vitl` | same |
| Coordinate conversion | Phase 2's `_to_canonical` | same |
| Wall fitting | RANSAC seed 20260915, 400 iters | same |
| Pixels excluded from wall fitting | the annotated **boxes** | the annotated **boxes** |
| Wall-contact threshold | 0.12 m absolute | same |
| Metric definitions | `summarise`/`auc` from the Phase 2 harness | same |

`load_cases`, `summarise` and `auc` are **imported** from
`metric_geometry_benchmark.py` rather than re-typed, so the dataset and the
arithmetic are literally the same code in both phases.

Wall fitting still excludes *boxes* in both variants. Switching that to masks as
well would have been a second variable and would have made the comparison
unreadable. It is deliberately left alone.

### The comparison is valid — variant A reproduces Phase 2 exactly

| | Phase 2 | Variant A, re-run |
|---|--:|--:|
| False-wall rate | 24.3% | **24.3%** |
| NO recall | 75.7% | **75.7%** |
| UNKNOWN | 0% | **0%** |
| Separation AUC | 0.7174 | **0.7174** |

Identical to the last digit. Whatever moves between A and B is the footprint and
nothing else.

---

## 2. SAM 2 — model, licence, cost

| | |
|---|---|
| Model | SAM 2.1 Hiera base-plus, `facebook/sam2.1-hiera-base-plus` |
| Implementation | `transformers.Sam2Model` — **already installed** (4.57.6) |
| Code licence | **Apache-2.0** |
| Checkpoint licence | **Apache-2.0** |
| Commercial use | **PERMITTED** |
| Source | github.com/facebookresearch/sam2 — *"The SAM 2 model checkpoints, SAM 2 demo code (front-end and back-end), and SAM 2 training code are licensed under Apache 2.0."* |

**No environment change.** The Meta `sam2` pip package needs WSL and a compiled
CUDA kernel on Windows; the transformers port needs neither, so it was not
installed. `torch 2.14.0+cu126` is untouched. No new dependency was added at all.

| Cost, measured | |
|---|--:|
| Load | 16.2 s |
| Cold inference | 2.10 s |
| **Warm median** | **0.519 s** |
| Warm p95 | 0.526 s |
| 48 cases | 26.5 s total |
| **Peak VRAM** | **920 MiB** |
| VRAM after unload | 244 MiB |
| Segmentation failures | **0 / 48** |

SAM ran alone on the card, all 48 masks were held in RAM (~15 MB), SAM was
unloaded, and only then did MoGe-2 load. On a 6 GB laptop card the two models
never competed. Combined cost per image is about 1.2 s (SAM 0.52 + MoGe 0.71).

### Mask selection — fixed before any result was read

SAM returns three candidates per prompt with predicted-IoU scores. The rule is
**highest predicted IoU, ties to the lower index**. It uses only SAM's own
confidence — never the label, never the annotation prose, never the resulting
wall distance. All three candidates and all three scores are recorded for every
case in the raw JSON.

The rule is not a rubber stamp: it chose candidate 2 in 22 cases, candidate 0 in
16, candidate 1 in 10, and the median spread between best and worst candidate
score was 0.093. It was making a real choice, blind.

The box was used as SAM's **prompt**, which the brief permits. What is under test
is the box as the geometric **footprint**.

---

## 3. Mask quality — no ground truth, so no invented IoU

**The benchmark contains no ground-truth segmentation masks.** It carries boxes
and wall-contact labels. Drawing masks now would mean annotating the same images
whose answers I already know, which is not ground truth. **Variant C (GT masks)
is recorded as NOT RUNNABLE. No IoU against GT is reported, because none can be
computed honestly.**

What *can* be measured is how much of each box the mask fills:

| | n | min | p25 | median | p75 | max |
|---|--:|--:|--:|--:|--:|--:|
| All | 48 | 0.193 | 0.425 | **0.518** | 0.619 | 0.964 |
| Open-structure | 38 | 0.306 | 0.419 | 0.509 | 0.617 | 0.956 |
| Solid | 10 | 0.193 | 0.461 | 0.567 | 0.718 | 0.964 |

**The median object fills barely half its own bounding box.** Median footprint
fell from 19,950 px to 8,293 px. The premise of the phase — that a box is a poor
stand-in for an object — is confirmed outright.

What it does *not* confirm is the hypothesis that followed from it. The
open-structure/solid split is 0.509 vs 0.567 — a real difference in the predicted
direction, but far smaller than the argument needed. A sofa photographed at an
angle wastes nearly as much of its box as a chair does.

No degenerate masks (none under 5% of its box). Two near-full masks
(`s02.coffee_table.0` 0.956, `preserved.bathroom.vanity.0` 0.964) are objects
photographed square-on, where the box really is the object.

---

## 4. Headline result

| | Variant A (bbox) | Variant B (SAM mask) |
|---|--:|--:|
| **False-wall rate** | 24.3% [13.4, 40.1] | **21.6% [11.4, 37.2]** |
| NO recall | 75.7% | 78.4% |
| **Positive recall** | **54.5%** | **18.2%** |
| Precision | 40.0% | 20.0% |
| **Balanced accuracy** | **65.1%** | **48.3%** |
| **Separation AUC** | 0.7174 | **0.7445** |
| UNKNOWN | 0% | 0% |
| TN / FP / TP / FN | 28 / 9 / 6 / 5 | 29 / 8 / 2 / 9 |

Three things are happening at once, and only the third matters.

1. **False-wall barely moved** — 24.3% → 21.6%, one case. The confidence
   intervals are almost coincident.
2. **Positive recall collapsed** — 54.5% → 18.2%. Balanced accuracy fell to
   **48.3%, below chance**.
3. **The underlying signal improved** — AUC 0.7174 → 0.7445. The ranking got
   *better* while the decisions got *worse*.

That combination is diagnostic, and section 6 explains it.

---

## 5. The nine Phase 2 false walls, tracked individually

| Case | Type | bbox → mask | Δ | mask/bbox | Decision | Repaired |
|---|---|--:|--:|--:|---|:--:|
| `s05.armchair.0` | armchair | 0.013 → **1.148** | +1.135 | 0.50 | YES→NO | ✅ |
| `s02.ottoman.0` | ottoman | 0.015 → **1.209** | +1.194 | 0.78 | YES→NO | ✅ |
| `s09.chair.0` | chair | 0.047 → **1.096** | +1.049 | 0.52 | YES→NO | ✅ |
| `s01.armchair.0` | armchair | 0.057 → **1.104** | +1.047 | 0.50 | YES→NO | ✅ |
| `s17.chair.2` | chair | 0.080 → **0.222** | +0.142 | 0.47 | YES→NO | ✅ |
| `s07.bar_stool.0` | bar stool | 0.009 → 0.065 | +0.056 | 0.62 | YES→YES | ❌ |
| `s16.chair.0` | chair | 0.014 → 0.012 | −0.002 | 0.56 | YES→YES | ❌ |
| `s07.bar_stool.1` | bar stool | 0.028 → 0.016 | −0.013 | 0.51 | YES→YES | ❌ |
| `s17.chair.0` | chair | 0.045 → 0.038 | −0.007 | 0.47 | YES→YES | ❌ |

**Five repaired, four not.** The five that moved did not edge over the threshold
— four of them jumped **more than a metre**. Where the box was straddling a wall,
removing the wall pixels was decisive.

The four that did not move are the more interesting half. Their masks are
perfectly good (0.47–0.62 of box, right at the dataset median). Their distances
changed by **less than 15 mm in either direction**. For these, the object's own
visible pixels genuinely sit within 12 cm of the fitted wall plane. **Grounding
was never their problem**, so better grounding did nothing for them.

### And four new false walls appeared

| Case | bbox → mask | Was | Became |
|---|--:|---|---|
| `hist_neg.kitchen.bar_stool.0` | 0.927 → **0.079** | correct NO | **false YES** |
| `hist_neg.kitchen.bar_stool.1` | 0.876 → **0.047** | correct NO | **false YES** |
| `hist_neg.kitchen.bar_stool.2` | 0.776 → **0.015** | correct NO | **false YES** |
| `s17.chair.1` | 1.069 → **0.079** | correct NO | **false YES** |

9 − 5 + 4 = 8. **The entire "improvement" from 9 false walls to 8 is churn.** It
would be dishonest to present 24.3% → 21.6% as progress: the rate is unchanged
within noise and the individual cases moved violently in both directions.

Note what these four have in common with the four unrepaired: they are bar stools
and chairs. Shrinking the footprint changed not only the measured distance but
*which wall is nearest*, and for objects near a counter or a corner that choice
is unstable.

---

## 6. Root cause — two faults were cancelling each other out

Look at the distance distributions. Masks pushed **everything** away from the
walls, not just the false positives:

| Variant | | n | min | p25 | median | p75 | max |
|---|---|--:|--:|--:|--:|--:|--:|
| A bbox | positives | 11 | 0.010 | 0.044 | **0.097** | 0.318 | 1.895 |
| A bbox | negatives | 37 | 0.009 | 0.143 | **0.640** | 1.666 | 4.812 |
| B mask | positives | 11 | 0.011 | 0.129 | **0.252** | 0.453 | 1.009 |
| B mask | negatives | 37 | 0.012 | 0.398 | **0.883** | 1.889 | 4.696 |

Positives +0.155 m, negatives +0.243 m. A near-uniform outward shift.

**The mechanism.** Wall distance is the 10th percentile of the object pixels'
absolute distance to the wall plane — the object's *nearest visible surface*. A
bounding box drawn around a sofa that is against a wall contains actual wall
pixels, at distance ≈ 0. The box therefore scored ≈ 0 **for free**, and scored it
correctly, for entirely the wrong reason. Take the wall pixels away and what
remains is the sofa's *front* face, one sofa-depth from the wall.

So the ten solid positives behaved exactly as that predicts:

| | bbox | mask |
|---|--:|--:|
| **Solid objects** (10 positives: sofas, beds, tv units, vanity) recall | **50.0%** | **10.0%** |
| **Open-structure objects** (37 negatives + 1) false-wall | 24.3% | **21.6%** |
| Open-structure balanced accuracy | 87.8% | **89.2%** |

**Masks helped open-structure objects and destroyed solid ones.** A bed at
0.035 m became 0.451 m; a tv unit at 0.010 m became 0.122 m; a sofa at 0.044 m
became 0.285 m. Each is now measured from its visible front, and each is now
wrong.

The threshold sweep confirms the mechanism independently:

| Threshold | bbox false-wall / pos-recall / **bal-acc** | mask false-wall / pos-recall / **bal-acc** |
|--:|--:|--:|
| 0.12 (shipped) | 24.3 / 54.5 / **65.1** | 21.6 / 18.2 / **48.3** |
| 0.20 | 29.7 / 63.6 / **67.0** | 21.6 / 45.5 / **61.9** |
| 0.30 | 32.4 / 72.7 / **70.1** | 24.3 / 63.6 / **69.7** |
| **0.40** | 32.4 / 81.8 / **74.7** | 27.0 / 63.6 / 68.3 |
| **0.50** | 40.5 / 81.8 / 70.6 | 32.4 / 81.8 / **74.7** |

Both variants peak at **balanced accuracy 74.7%** — the same ceiling. The mask
variant simply needs a threshold one notch larger (0.50 m vs 0.40 m) to get
there, which is roughly one object depth. That is the signature of measuring the
wrong surface, and it is why no amount of threshold tuning rescues either arm.
*(Diagnostic only. `WALL_CONTACT_DISTANCE_M` remains 0.12 m and was not changed.)*

**The conclusion.** Phase 2's diagnosis — "the box contains the wall, so the box
is near the wall" — was correct as far as it went, and five repaired cases prove
it. What it missed is that the same defect was *also* supplying the right answer
for every solid object against a wall. Fixing the grounding removed a crutch the
distance heuristic had been leaning on. The remaining fault is not perception at
all: **it is that "distance from the object's nearest visible surface to the wall
plane" is the wrong definition of wall contact.**

---

## 7. Breakdown by domain and category

| | | bbox | mask |
|---|---|--:|--:|
| **Generated negatives** (32) | false-wall | 28.1% | **15.6%** |
| **Historical negatives** (5) | false-wall | **0.0%** | **60.0%** |
| Category A | false-wall | 21.1% | **10.5%** |
| Category B | false-wall | 27.8% | **33.3%** |

Masks helped materially on the generated scenes and on Category A, and broke the
historical negatives outright — all three of those failures are the kitchen bar
stools. With n = 5 the historical figure carries almost no statistical weight,
but the mechanism behind it is visible in section 5 and is not noise.

Category B (wall-backed context) is now the worse category under both grounding
methods, consistent with Phase 1h. The Phase 1f claim that Category B was the
harder case, which the Phase 1g balanced dataset appeared to overturn, is back —
but at 33.3% vs 10.5% on n = 18 / 19, so it remains suggestive rather than
established.

---

## 8. Gate

**FAIL.**

| Condition | Result |
|---|:--|
| False-wall rate below 20% | ✗ 21.6% |
| Improvement beyond noise | ✗ CIs [13.4, 40.1] and [11.4, 37.2] overlap almost entirely; 9 → 8 errors is churn (5 fixed, 4 created) |
| No regression elsewhere | ✗ positive recall 54.5% → 18.2%; balanced accuracy 65.1% → **48.3%, below chance** |
| Hypothesis supported | **partly** — 5 of 9 repaired, four by more than a metre |
| Signal improved | ✓ AUC 0.7174 → 0.7445 |

Not integrated into production. Nothing in `app/` was modified, no threshold was
tuned, no case was removed, no synthetic case was added.

---

## 9. What this bought

Not the fix. A correct diagnosis, which the previous two phases did not have.

- **Grounding is genuinely defective** and SAM genuinely repairs it: the median
  object occupies 52% of its own box, and five metre-scale corrections followed
  from fixing that.
- **Grounding was never the whole story.** Four failures are untouched by perfect
  masks, and ten solid objects got worse.
- **The wall-distance formulation is now the prime suspect**, on three
  independent pieces of evidence: the uniform outward shift of every distance,
  the solid/open-structure split, and the identical 74.7% ceiling reached by both
  variants one threshold-notch apart.

Phase 2 predicted this in advance and it is worth honouring the prediction as
stated: *"If they persist with masks, the fault is the 10th-percentile
rear-surface heuristic instead."* Four of them persisted. It is.

---

## 10. What to test next

The measurement, not the perception. Wall contact should be decided from the
object's **rear extent along the wall normal** — the far side of the object's
point cloud — not the nearest visible surface. The object's own points already
give a signed extent along that normal; the back of a sofa is behind its front by
one sofa-depth, and that is precisely the quantity the current heuristic throws
away.

That change is testable on this same 48-case benchmark with the same masks, the
same geometry and the same threshold, as a single controlled variable — which is
the cleanest possible next experiment.

Two secondary questions worth separating out, but only after the primary one:

- **Wall selection instability.** Four cases flipped because shrinking the
  footprint changed which wall was nearest. Nearest-wall selection may need to
  consider the object's orientation, not only its distance.
- **The four stubborn cases.** `s16.chair.0`, `s07.bar_stool.0/1`, `s17.chair.0`
  sit within 12 cm of a fitted wall plane by their own pixels. Worth checking
  whether that plane is a wall at all, or a counter or backsplash fitted as one.

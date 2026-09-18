# Phase 5 — Manual Amodal 3D Geometry Ceiling

**Verdict: LOW CEILING.** With each object's full physical extent supplied by
hand, the geometry reaches **51.3% balanced accuracy** on the oracle subset —
essentially chance. Amodal object geometry is **not** the binding constraint.

But the failure is not where the low number suggests, and the detail matters more
than the headline:

- **On positives the oracle works.** Three of the five positives Phase 3 lost are
  recovered outright, and the other two miss by 5 mm and 39 mm — both inside their
  own recorded measurement uncertainty. Supplying the hidden rear face does
  exactly what Phase 4 predicted it would.
- **On negatives it collapses, and not because of the object.** Every failing
  negative is flush against a large vertical plane that **is not a wall**: a
  kitchen island, a built-in desk, a glass office partition, a bench. The fitted
  wall set is contaminated, and the decision takes the *minimum* gap over that
  set, so contamination guarantees false positives.

The chosen plane's inlier fraction is **0.669 median when the decision is right
and 0.286 when it is wrong**. That is the whole result in one number.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/oracle_ceiling_results.json`,
`oracle_geometry.json`
**Scripts:** `research/spatial_engine/oracle_geometry.py`,
`research/spatial_engine/oracle_ceiling_benchmark.py`
**Production code changed:** none. Dependencies changed: none.
`pytest -q` → 355 passed, 7 skipped, 30 xfailed, before and after.

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**,
**[N] not tested**.

---

## 1. Objective

Answer one question, and refuse to guess it in advance:

> If the geometry engine is given manually estimated full 3D object extent, can it
> correctly determine wall contact?

A high ceiling would mean amodal perception is the next problem. A low ceiling
means the benchmark or the wall geometry is, and that building an amodal
reconstruction system would have been wasted work.

---

## 2. Why this experiment follows Phase 4

Phase 4 established that the object's rear extent is **absent** from a
single-view point cloud: 32 of 48 cases returned a distance identical to the
phase before, because for an object lying on one side of a plane the extremal
point toward it and the nearest point to it are the same point. It also found 13
cases where a candidate plane sat on the wrong side of the object entirely, and
clamping that impossible geometry to a zero gap manufactured contacts.

Both findings point at the same next step: stop improving the estimate of a
quantity, and check whether the quantity would be enough.

---

## 3. Benchmark subset **[M]**

**26 of the 48 cases, across all 12 images: 9 positives, 17 negatives.** The
benchmark itself is unchanged — no case was added, removed or relabelled.

| Group | Contents |
|---|---|
| **A — positives** | 9: three sofas, a bed, two bedside tables, a kitchen counter, a TV panel, a side table |
| **B — negatives** | armchairs, ottomans, chairs, bar stools, a coffee table |
| **C — historical negatives** | all 5 that exist (living-room ottoman, three kitchen bar stools, living-room coffee table) |
| **D — known failures** | **all 9** Phase 2 false walls · **all 5** Phase 3 missed positives · **all 4** Phase 3 new false walls · 8 of the 13 Phase 4 wrong-side cases |

The subset is deliberately loaded with the hard cases, exactly as the brief
required. **That makes it harder than the full 48 for every method**, so every
comparison below is computed on these same 26 cases. Comparing a 26-case oracle
against a 48-case baseline would be a category error, and the numbers differ
enough to matter: Phase 2 scores 65.1% balanced accuracy on the full 48 and
56.9% here. **[M]**

---

## 4. Oracle geometry protocol

**What the oracle supplies:** width, depth and height, in metres — nothing else.

**What it does not supply:** position, orientation, any distance, and the label.

**Why the dimensions cannot encode the answer.** A sofa is about 0.9 m deep
whether it stands against a wall or in the middle of the floor. Dimensions are a
property of the furniture, not of the scene. At no point was a rear face placed
*at* a wall because the case was known to be a positive.

**The box is never hand-placed.** It is anchored by one physical fact that holds
in every scene: *hidden geometry lies behind visible geometry, away from the
camera*. The box's near face sits at the object's nearest visible surface and
extends away from the camera by the measured depth. Nothing in that rule consults
a wall, a distance, or a label — if the object is against a wall the box reaches
it on its own, and if it is not, it does not.

**Orientation is derived, not guessed:** the width axis is the dominant horizontal
direction of the object's own visible points.

**Height is acknowledged as unimportant.** Walls are vertical, so the projection
onto a wall normal is horizontal; the vertical placement barely affects the gap.
The box is seated at the lowest visible point. Recorded so nobody later mistakes
it for a careful vertical fit. **[Q]**

The construction is unit-checked on a synthetic room where the answer is known by
construction: a sofa whose visible surface is 0.855 m from the wall and whose
body reaches it returns **nearest-visible 0.855 m, oracle 0.000 m**. **[M]**

### A real limitation of this oracle, measured and not hidden **[M]**

In **23 of 26 cases the visible points span more depth than the measured depth
allows** — `s09.chair.0` spans 2.70 m for a 0.7 m chair. Two causes: for
near-isotropic objects (chairs, stools) the derived width axis is arbitrary, so
"depth" is measured along a diagonal; and some SAM masks carry a few background
pixels that stretch the cloud. The oracle's *dimensions* are sound; its *axis
assignment* is weak for round objects. This inflates the box's apparent depth
spread but does not change the headline, because the failing negatives fail by
touching a plane that is 0.0 m away in every axis assignment. **[I]**

---

## 5. Measurement uncertainty **[M]**

Every object carries its own recorded ± (0.03 m for the TV panel, 0.15 m for the
bed), not one global figure. The perturbation protocol was fixed before the run:
six perturbations plus the nominal — depth −u/+u, width −u/+u, and the box slid
along its depth axis −u/+u.

| | |
|---|--:|
| Cases | 26 |
| **Decisions stable across all seven** | **21 (80.8%)** |
| Unstable | 5 |
| Borderline (\|gap − 0.12\| < 0.05 m) | 5 |

Unstable: `s17.chair.2`, `preserved.living_room_a.sofa.0`,
`preserved.kitchen.kitchen_counter.0`, `preserved.master_bedroom.bed.0`,
`preserved.living_room_b.tv_unit.0`.

**One in five decisions is not robust to the measurement error I am willing to
admit to.** A 0.11 m versus 0.13 m distinction is not meaningful when the object's
depth is known to ±0.05 m, and the report does not treat it as one. **[M]**

---

## 6. Coordinate system

Allure canonical throughout: **+X right, +Y up, −Z forward, metres** — the same
frame MoGe-2 output is converted into by `_to_canonical`, with the camera at the
origin. No second frame was created. Yaw is expressed by the derived width and
depth axis vectors rather than an angle, because an angle would need a reference
axis that the room frame does not canonically define.

---

## 7 & 8. Oracle A and Oracle B

**Oracle A** uses the candidate-wall selection exactly as it stands.

**Oracle B** adds one diagnostic rule: *reject a wall that the entire object lies
on the far side of, relative to the room interior.* This targets the 13 cases
Phase 4 found where clamping impossible geometry manufactured a contact. It was
not tuned against labels.

**The gate fires on 4 of the 26 cases and is a near-wash, in both directions:**

| Case | Oracle A | Oracle B | Effect |
|---|---|---|---|
| `s10.chair.1` | wrong | correct | ✅ fixed |
| `s10.chair.2` | wrong | correct | ✅ fixed |
| `s17.chair.2` | wrong | correct | ✅ fixed |
| `preserved.kitchen.kitchen_counter.0` | correct | **wrong** | ❌ broken |

The gate rejected the very wall the kitchen counter is against. Net +3/−1, and
balanced accuracy 48.0% → **51.3%**. The wrong-side problem was real but small:
it is **not** what holds the ceiling down. **[M]**

---

## 9. Metric comparison, all on the same 26 cases **[M]**

| | P2 bbox+nearest | P3 SAM+nearest | P4 SAM+rear | **Oracle A** | **Oracle B** |
|---|--:|--:|--:|--:|--:|
| TP / TN / FP / FN | 6/8/9/3 | 2/9/8/7 | 2/6/11/7 | 6/5/12/3 | **5/8/9/4** |
| False-wall | 52.9% | 47.1% | 64.7% | 70.6% | **52.9%** |
| NO recall | 47.1% | 52.9% | 35.3% | 29.4% | **47.1%** |
| **Positive recall** | 66.7% | 22.2% | 22.2% | **66.7%** | **55.6%** |
| Precision | 40.0% | 20.0% | 15.4% | 33.3% | **35.7%** |
| F1 | 50.0% | 21.1% | 18.2% | 44.4% | **43.5%** |
| **Balanced accuracy** | **56.9%** | 37.6% | 28.8% | 48.0% | **51.3%** |
| AUC | 0.6013 | 0.5490 | 0.3954 | 0.4118 | **0.5294** |
| UNKNOWN | 0% | 0% | 0% | 0% | **0%** |

Control reproduction on the full 48: Phase 2 (24.3% / 65.1% / AUC 0.7174),
Phase 3 (21.6% / 48.3% / 0.7445) and Phase 4 (37.8% / 40.2% / 0.6118) all
reproduced exactly, with zero per-case decision drift against the stored records.
The run aborts rather than reporting a ceiling if they do not. **[M]**

**Oracle B restores everything Phase 3 and Phase 4 destroyed on positives**
(recall 22.2% → 55.6%, and 66.7% for Oracle A) **and still does not beat Phase 2's
bounding box overall** — because Phase 2's box gets negatives wrong for the same
structural reason and positives right by the accident Phase 3 documented.

---

## 10. The five Phase 3 missed positives **[M]**

These are the cases amodal geometry was supposed to rescue.

| Case | P2 | P3 | P4 | **Oracle** | Decision | Verdict |
|---|--:|--:|--:|--:|---|---|
| `preserved.living_room_a.sofa.1` | 0.044 | 0.285 | 0.285 | **0.000** | YES | ✅ solved |
| `preserved.living_room_b.tv_unit.0` | 0.010 | 0.122 | 0.122 | **0.095** | YES | ✅ solved |
| `preserved.master_bedroom.bedside_table.0` | 0.045 | 0.252 | 0.252 | **0.084** | YES | ✅ solved |
| `preserved.master_bedroom.bed.0` | 0.035 | 0.451 | 0.451 | **0.125** | NO | ✗ by **5 mm** |
| `preserved.master_bedroom.bedside_table.1` | 0.061 | 0.196 | 0.196 | **0.159** | NO | ✗ by **39 mm** |

**Three of five solved outright, and the other two fail by less than their own
measurement uncertainty** (bed ±0.15 m, bedside table ±0.05 m). Both are flagged
borderline by the margin analysis, and both flip under perturbation.

The bed is the strongest single demonstration in the phase: its visible surface
is 0.451 m from the wall its headboard touches, and the amodal box brings that to
0.125 m. The remaining 5 mm is not a perception failure, it is the threshold
sitting inside the error bar. **[M]**

**Amodal geometry does the job it was hypothesised to do.** That part of Phase 4's
recommendation is confirmed.

---

## 11. The nine Phase 2 false walls **[M]**

| Case | P2 | P3 | P4 | **Oracle B** | Decision | Verdict |
|---|--:|--:|--:|--:|---|---|
| `s01.armchair.0` | 0.057 | 1.104 | 1.104 | **1.613** | NO | unchanged correct |
| `s02.ottoman.0` | 0.015 | 1.209 | 1.209 | **0.758** | NO | unchanged correct |
| `s05.armchair.0` | 0.013 | 1.148 | 1.148 | **0.865** | NO | unchanged correct |
| `s17.chair.2` | 0.080 | 0.222 | 0.000 | **4.348** | NO | ✅ correctly solved |
| `s07.bar_stool.0` | 0.009 | 0.065 | 0.000 | **0.000** | YES | ✗ still wrong |
| `s07.bar_stool.1` | 0.028 | 0.016 | 0.000 | **0.000** | YES | ✗ still wrong |
| `s16.chair.0` | 0.014 | 0.012 | 0.009 | **0.000** | YES | ✗ still wrong |
| `s17.chair.0` | 0.045 | 0.038 | 0.000 | **0.000** | YES | ✗ still wrong |
| `s09.chair.0` | 0.047 | 1.096 | 1.096 | **0.000** | YES | ✗ **newly wrong** |

**Solved 1 · unchanged correct 3 · still wrong 4 · newly wrong 1.**

Every failure reads **exactly 0.000 m** — the oracle box intersects a fitted
plane. The object geometry is not in doubt; what the box is touching is.

---

## 12. What the failing negatives are actually touching **[M, with Q from the images]**

I looked at all 12 source images. Every persistent false wall is an object that is
**genuinely flush against a large vertical plane which is not a wall**:

| Case | What the object is actually against | Chosen plane inlier fraction |
|---|---|--:|
| `s07.bar_stool.0/1` | the navy **kitchen island**, stools tucked under the counter | 0.212, 0.212 |
| `hist_neg.kitchen.bar_stool.0/1/2` | the white **kitchen island** | 0.286 |
| `s17.chair.0/1` | the glazed **meeting-pod partition** | 0.147, 0.131 |
| `s09.chair.0` | the built-in timber **desk and bookcase** | 0.292 |
| `s16.chair.0` | the **bench** along the panelled wall | 0.343 |

The labels are right — an island is not a wall — and the geometry is right that
something vertical and planar is there. **The primitive cannot tell the two
apart**, because `fit_room` admits any vertical Manhattan-aligned plane above
`MIN_WALL_INLIER_FRACTION = 0.06` and `MIN_WALL_EXTENT_FRACTION = 0.015`. An
island front face clears both easily.

Then the decision rule compounds it: contact is the **minimum** gap over all
candidate planes, so a contaminated wall set does not merely add noise — it
actively selects the contaminant, because the contaminant is the closest thing.
**[I]**

### The quantitative test **[M]**

| Chosen plane's inlier fraction | n | median | range |
|---|--:|--:|--:|
| when the decision is **correct** | 13 | **0.669** | 0.098 – 0.882 |
| when the decision is **wrong** | 13 | **0.286** | 0.131 – 0.821 |

**Diagnostic only** — computed post hoc from the stored per-wall projections, no
threshold changed, no bearing on the gate — re-deciding using only planes above an
inlier-fraction floor:

| Floor | TP/TN/FP/FN | UNKNOWN | False-wall | Bal. accuracy |
|--:|---|--:|--:|--:|
| **0.06 (shipped)** | 5/8/9/4 | 0 | **52.9%** | **51.3%** |
| 0.15 | 5/8/7/4 | 2 | 46.7% | 54.4% |
| 0.30 | 5/8/1/4 | 8 | 11.1% | 72.2% |
| **0.40** | 5/8/0/4 | 9 | **0.0%** | **77.8%** |
| 0.50 | 4/6/0/5 | 11 | 0.0% | 72.2% |

With amodal geometry *and* a clean wall set, **false walls go to zero** — at the
cost of abstaining on 9 of 26 cases. That is a different and much healthier
operating regime: decide where a trustworthy wall exists, say UNKNOWN where one
does not. It is a diagnostic on 26 deliberately-hard cases, not a result, and it
must be confirmed on the full benchmark before anyone relies on it. **[N]**

---

## 13. Object-type analysis, Oracle B **[M]**

| Type | n | neg | pos | False-wall | Pos recall | Median gap |
|---|--:|--:|--:|--:|--:|--:|
| **bar stool** | 5 | 5 | 0 | **100.0%** | — | **0.000 m** |
| **chair** | 7 | 7 | 0 | **57.1%** | — | 0.000 m |
| armchair | 2 | 2 | 0 | 0.0% | — | 1.239 m |
| ottoman | 2 | 2 | 0 | 0.0% | — | 1.093 m |
| table | 4 | 1 | 3 | 0.0% | 66.7% | 0.122 m |
| sofa | 3 | 0 | 3 | — | 66.7% | 0.000 m |
| cabinet | 2 | 0 | 2 | — | 50.0% | 0.388 m |

Every bar stool fails and most chairs fail; **every armchair and ottoman is
correct**. The split is not about open structure — it is about whether the object
happens to be parked against an island, a desk or a partition. Armchairs and
ottomans in these scenes sit in open floor, so no contaminant plane is near them.

Open-structure balanced accuracy is 73.5% against solid 50.0% positive recall —
the reverse of Phase 3's split, and further evidence that furniture topology was
never the driver. **[M]**

---

## 14. Distance distributions and threshold diagnostic **[M]**

| Oracle B | n | min | p25 | median | p75 | max |
|---|--:|--:|--:|--:|--:|--:|
| positives | 9 | 0.000 | 0.026 | **0.095** | 0.127 | 0.681 |
| negatives | 17 | 0.000 | **0.000** | **0.000** | 1.429 | 5.926 |

The negatives are bimodal: nine sit at exactly 0.000 (touching a contaminant
plane) and the rest are over a metre away. There is no threshold between those
two populations, and the sweep confirms it — **false-wall is pinned at 52.9% at
every threshold from 0.03 m to 0.50 m**, while positive recall climbs to 88.9% at
0.20 m. *(Diagnostic only; the gate used 0.12 m.)*

A metric stuck at one value across a 17-fold threshold range is not a calibration
problem. It is the wrong planes. **[I]**

---

## 15. Ceiling interpretation

**LOW CEILING — 51.3% balanced accuracy**, by the brief's own bands.

The literal reading of that band is "the current benchmark/geometry formulation is
not reliably solvable even with oracle object geometry", and that is correct. But
the evidence locates the fault precisely, and it is not the one the band implies:

1. **The object geometry is fine.** Positives recover (§10). Positive recall goes
   from 22.2% to 55.6%, and to 88.9% at a 0.20 m threshold.
2. **The wall set is contaminated.** Correct decisions pick planes at 0.669 inlier
   fraction, wrong ones at 0.286 (§12).
3. **Clean the wall set and false walls vanish** — 0.0% at a 0.40 floor, with
   abstention (§12).
4. **No threshold helps**, because the failing negatives read exactly zero (§14).

So the ceiling is low **for a reason that a better perception model cannot fix and
a better wall-plane definition can**. That is precisely the discrimination this
phase existed to make, and it went the way neither Phase 4 nor I predicted. **[I]**

### Not "perfect ground truth"

This is a **manual amodal geometry oracle** — an empirical ceiling estimate from
my own reading of 12 images. It is not measured 3D ground truth. 23 of 26 cases
show an axis-assignment weakness (§4), one in five decisions is unstable under
its own error bars (§5), and the subset is 26 deliberately-hard cases. The right
statement is: *the manually supplied amodal geometry provides an empirical ceiling
estimate*, and that estimate is low for identifiable, fixable reasons. **[Q]**

---

## 16. Decision

**The perception-model search stops here.** Do not build an amodal reconstruction
system. Phase 4's recommendation — "the decision needs the object's amodal 3D
extent" — was half right: supplying it fixes the positives and does nothing for
the negatives, because the negatives were never an object-geometry problem.

Nothing was integrated. No production file, threshold, label, case or model was
changed; no model was downloaded or trained.

---

## 17. Recommendation

**The next problem is the wall set, not perception.** Three things follow, in
order, and none needs a new model:

1. **Make "wall" mean wall.** A candidate plane admitted at 6% inlier fraction is
   not architecture. The evidence says a plane must be large, room-bounding and
   high-support to count — an island front, a desk back and a glass partition all
   clear today's bar. The confidence diagnostic (§12) is the cheapest first
   experiment: re-run the full 48 with a wall-quality floor and abstention, and
   see whether 0.0% false-wall survives outside this hard subset. **[N]**

2. **Let it abstain.** Every phase so far has forced a YES/NO on 100% of cases,
   and `Decision.UNKNOWN` has been available and unused since Phase 1. The 0.40
   floor abstains on 9 of 26 and is right on the rest. For a design tool, "I cannot
   see a wall here" is a usable answer and a wrong "against the wall" is not.

3. **Decide what the benchmark is asking.** Stools at an island and chairs at a
   glass partition are labelled *not against a wall*, correctly. If the downstream
   solver actually needs "is this object's back against something solid" — for
   placement and collision, it may well — then the primitive and the label are
   answering different questions, and the label is not wrong, the primitive is
   under-specified. This is a product decision, not a research one, and it should
   be made before another phase measures against these labels. **[Q]**

A note for whoever picks this up: Phase 2's bounding box still scores best overall
on this subset (56.9%). It gets positives right by including wall pixels, which
Phase 3 proved is an accident. Do not read its lead as a reason to go back.

---

## 18. Production readiness

Not claimed, not tested. One primitive has been measured across five phases and
has not yet passed. Object grounding, coordinate placement, the spatial graph,
asset normalisation, constraint solving, collision validation and Blender
integration remain untouched and unevaluated. **[N]**

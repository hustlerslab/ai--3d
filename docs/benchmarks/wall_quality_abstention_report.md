# Phase 6 — Wall Quality + Abstention

**Verdict: PARTIAL PASS.** A deterministic wall-quality gate built from two
geometric features — *does the plane enclose the room* and *is its support
above floor level* — cuts the full-48 false-wall rate from **21.6% to 6.1%**
while deciding **44 of 48 cases** (91.7% coverage), and abstains on exactly the
four cases where no wall was ever fitted. Separation AUC rises from 0.7445 to
**0.8402**. Seven of the eight Phase 3 false walls are removed; the eighth is a
chair that genuinely stands 1.2 cm from a real wall.

What it does **not** do is repair positives. Positive recall stays collapsed
(18.2% → 9.1%), and every one of those ten misses now selects the *correct*
high-quality wall — the distance to it is simply wrong, because the object side
still measures the nearest visible surface. That fault was diagnosed in Phases 4
and 5 and is frozen in this phase by design. The wall problem is solved to the
brief's "particularly strong" standard; the object problem is untouched.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/wall_quality_results.json`,
`wall_quality_features.json`, `wall_plane_classes.json`
**Scripts:** `research/spatial_engine/wall_quality.py`, `wall_quality_benchmark.py`
**Production code changed:** none. Dependencies changed: none (scipy and PIL were
already installed).
`pytest -q` → 355 passed, 7 skipped, 30 xfailed, before and after.

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**,
**[N] not tested**.

---

## 1. Objective

> Can deterministic geometric evidence distinguish room-bounding walls from
> contaminant vertical planes well enough to make wall-contact decisions useful,
> while honestly abstaining when it cannot?

The output space is YES / NO / UNKNOWN. The object side is frozen at Phase 3
(SAM mask, production `wall_contact` statistic). The **only** change is which
fitted planes are allowed to count as walls.

---

## 2. Phase 2–5 control reproduction **[M]**

| Control | Stored | Re-run | |
|---|--:|--:|:--|
| Phase 2 false-wall / NO recall / AUC | 24.3 / 75.7 / 0.7174 | **identical** | ✓ |
| Phase 3 false-wall / NO recall / AUC | 21.6 / 78.4 / 0.7445 | **identical** | ✓ |
| Phase 4 false-wall / NO recall / AUC | 37.8 / 62.2 / 0.6118 | **identical** | ✓ |
| Phase 5 oracle B bal-acc / false-wall / AUC (26) | 51.3 / 52.9 / 0.5294 | **identical** | ✓ |
| Per-case decision drift vs stored Phase 4, Phase 5 | — | **0, 0** | ✓ |

The run is written to abort if any control drifts. None did.

---

## 3. Candidate wall feature definitions

The frozen fitter produced **84 planes** over 21 images, **64** of which passed
its own checks. For every plane, the fitter's pixel accounting was replayed
exactly — same valid pixels, same off-floor test, each pixel assigned to the
*first* plane in fit order within that plane's threshold — and the following
were measured:

| Feature | Definition |
|---|---|
| `inlier_fraction`, `extent_fraction`, `manhattan_residual_deg`, `residual_median` | from the fitter, verbatim |
| `inlier_pixels`, `inlier_pixel_fraction` | recovered pixel support |
| `horizontal_extent_frac`, `vertical_extent_frac`, `touches_image_edge` | pixel bounding box |
| `connected_components`, `largest_component_fraction` | `scipy.ndimage.label` on the support |
| `width_m`, `height_m`, `area_m2` | p5–p95 along the in-plane horizontal and of height above the floor plane |
| `min/max_height_above_floor_m`, `reaches_floor` | vertical placement relative to the fitted floor |
| `floor_band_fraction` | fraction of inliers below 0.25 m above the floor |
| `upper_band_fraction` | fraction of inliers above 1.5 m |
| `centroid_distance_m`, `camera_distance_m` | plane to room centroid; plane to camera |
| **`enclosure_fraction`** | fraction of *all* scene points on the room-centroid side of the plane |
| `terminates_at_room_envelope` | **unavailable** — not reliably computable from one view. Recorded as such, not substituted. |

---

## 4. Feature distributions **[M]**

Features of the plane each Phase 3 decision selected, split by outcome. FP is
the contaminant question; FN is a different failure and is shown separately.

| Feature | FP (8) | TN (29) | TP (2) | FN (9) |
|---|--:|--:|--:|--:|
| `inlier_fraction` | 0.249 | 0.241 | 0.553 | 0.669 |
| **`floor_band_fraction`** | **0.810** | **0.000** | 0.502 | 0.000 |
| **`enclosure_fraction`** | 0.902 | 0.904 | 0.961 | 1.000 |
| `upper_band_fraction` | 0.135 | 0.498 | 0.000 | 0.014 |
| `max_height_above_floor_m` | 1.60 | 2.51 | 0.51 | 1.46 |
| `height_m` | 1.59 | 1.83 | 0.61 | 0.78 |
| `width_m` | 2.78 | 4.74 | 2.78 | 3.05 |
| `area_m2` | 6.76 | 8.12 | 1.67 | 1.66 |

Four things this table settles:

1. **`inlier_fraction` does not separate false walls from true negatives on
   the full 48** (0.249 vs 0.241). Phase 5's 0.669-vs-0.286 was the oracle
   subset, where "wrong" was dominated by missed positives whose walls are
   high-support. It is a real correlate of *wall quality* but not of
   *contamination*.
2. **`floor_band_fraction` separates cleanly** — FP median 0.81, TN median 0.00
   with p75 0.004. Island fronts and plinths live at floor level; walls in a
   furnished room are seen above the furniture.
3. **`enclosure_fraction` does not separate in aggregate** (0.90 vs 0.90) but
   catches one specific contaminant absolutely: the s17 partition at 0.60.
4. **Height and upper-band separate for the wrong reason.** The positives' walls
   (TP/FN) are 0.5–0.8 m tall with near-zero upper band — not because they are
   furniture, but because the wall behind a sofa is only *visible* above the
   sofa, and the sofa's box is excluded from fitting. Height measures occlusion.
   **[I, confirmed by the eye pass, §5]** A height floor would reject the true
   wall behind every positive; the sweep in §15 shows exactly that.

---

## 5. Manual wall-type analysis **[Q → M]**

Every plane in **14 of the 21 images (56 planes)** was classified by eye from an
overlay of its pixel support painted over the source image. The object labels
were not consulted; the only question asked was *what surface is this support
lying on?* Misfits — ceiling stripes, depth read through glass, slivers — are
UNKNOWN.

| Class | n | `enclosure` median [min, max] | `floor_band` median [max] | `inlier` median | `height_m` median |
|---|--:|--:|--:|--:|--:|
| **ROOM_BOUNDING_WALL** | 25 | **0.989** [0.694, 1.000] | 0.003 [0.218] | 0.358 | 1.36 |
| FURNITURE_FIXTURE_PLANE | 10 | 0.833 [0.689, 0.970] | 0.008 [**1.000**] | 0.297 | 1.40 |
| INTERIOR_ARCHITECTURAL_PARTITION | 2 | **0.601** [0.596, 0.605] | 0.000 | 0.139 | 1.66 |
| UNKNOWN (misfit) | 19 | 0.879 [0.561, 1.000] | 0.000 [0.880] | 0.147 | 1.50 |

**Does geometry separate the classes?** Partly, and interpretably:

- **Enclosure** puts the two partition planes at 0.60, below every wall and every
  furniture plane. Walls sit at 0.99 median; the one wall at 0.69 is in the
  bathroom, where the mirror sends depth through the glass. **[M]**
- **Floor band** is bimodal for furniture: the two kitchen islands sit at 1.0,
  the rest near 0. Walls never exceed 0.22. **[M]**
- **Height does not separate walls from furniture at all** — 1.36 m vs 1.40 m.
  **[M]** This is the occlusion confound made explicit.
- **Width** is a partition signature: the pod partition measures 16–20 m because
  it is a long corridor line, against 3 m for a wall. Not used in the gate;
  noted for later. **[M]**

**What the eye pass found in the false-wall scenes.** In *both* kitchens the
plane the stools "touch" is the **island's front face**, rendered squarely
between the stool legs. In s17 the plane is the **glazed meeting-pod partition**
— tall, enormous, and with 40% of the scene beyond it. In s16 the plane is the
**panelled right-hand wall itself**, and the chair beside the bench really is
centimetres from it. In s10 and s11 **no wall was fitted at all**: every plane is
a vertical plane seen edge-on, slicing the ceiling in diagonal stripes. **[Q]**

**A room-fitting failure found on the way.** The camera sits **0.33 m** above
s07's fitted "floor" and **0.63 m** above the historical kitchen's; every other
scene puts it at 1.0–1.5 m. Both kitchens fitted the **countertop as the floor**,
which is why their island faces measure "below floor". The floor search looks in
the lower 45% of the image for a horizontal plane, and in a kitchen photographed
across an island that plane is the counter. Recorded; not fixed. **[M]**

---

## 6. Wall-quality gate definition

A plane must clear every declared floor to count as a wall; otherwise it is
marked uncertain and the production `wall_contact` never sees it. When no plane
survives, that function returns UNKNOWN — behaviour it has had since Phase 1 and
never exercised.

Two features carry the gate, chosen because they are the two that separated the
planes behind wrong decisions from the planes behind right ones (§4) **and**
match what the eye saw (§5):

- **`enclosure_fraction ≥ E`** — a room-bounding wall has (nearly) the whole scene
  on its room side.
- **`floor_band_fraction ≤ F`** — a wall's support in a furnished room sits above
  the furniture; a plinth or island front is all at floor level.

Explicitly **not** used: height and upper-band (occlusion confound, §4);
`inlier_fraction` as a primary feature (no FP/TN separation), carried only as a
low floor on the conservative point to refuse the thinnest fits.

---

## 7. Predeclared operating points

Declared after the feature pass was read and before any of them was evaluated.
The numbers were read off the distributions — E brackets the TN enclosure median
of 0.904 from below; F brackets the gap between FP floor-band median 0.81 and TN
p75 0.004 — not off what scored best.

| Point | `enclosure ≥` | `floor_band ≤` | `inlier ≥` |
|---|--:|--:|--:|
| permissive | 0.80 | 0.75 | — |
| moderate | 0.90 | 0.50 | — |
| conservative | 0.95 | 0.25 | 0.15 |

Plus, run unaltered and labelled as what it is: **the Phase 5 diagnostic 0.40
inlier-fraction gate** — a pre-existing candidate from a 26-case post-hoc sweep,
not a discovery of this phase.

---

## 8. Full 48-case results **[M]**

| | Phase 3 base | **permissive** | moderate | conservative | P5 diag 0.40 |
|---|--:|--:|--:|--:|--:|
| TP / TN / FP / FN | 2/29/8/9 | **1/31/2/10** | 1/24/2/9 | 1/18/1/9 | 1/13/0/9 |
| **UNKNOWN** | 0 | **4** | 12 | 19 | 25 |
| **Coverage** | 100% | **91.7%** | 75.0% | 60.4% | 47.9% |
| **False-wall (decided)** | 21.6% | **6.1%** | 7.7% | 5.3% | **0.0%** |
| False-wall (of all 37 negatives) | 21.6% | **5.4%** | 5.4% | 2.7% | 0.0% |
| NO recall (decided) | 78.4% | **93.9%** | 92.3% | 94.7% | 100% |
| Positive recall (decided) | 18.2% | **9.1%** | 10.0% | 10.0% | 10.0% |
| Precision | 20.0% | 33.3% | 33.3% | 50.0% | 100% |
| F1 | 19.0% | 14.3% | 15.4% | 16.7% | 18.2% |
| Balanced accuracy (decided) | 48.3% | 51.5% | 51.2% | 52.4% | 55.0% |
| **AUC** | 0.7445 | **0.8402** | 0.8385 | 0.8579 | 0.9385 |
| Accuracy over all 48, UNKNOWN counted wrong | 64.6% | **66.7%** | 52.1% | 39.6% | 29.2% |

The permissive point is the one to read. It **removes six of eight false walls
at a cost of four abstentions**, lifts NO recall from 78% to 94%, and is the only
operating point whose whole-dataset accuracy beats the baseline. Everything
stricter buys a lower false-wall rate with coverage, not with correctness.

Balanced accuracy barely moves because it is held down entirely by the positive
side, which this phase does not touch (§16).

---

## 9. UNKNOWN / coverage analysis **[M]**

**Permissive abstains on 4 cases, all in one scene: s11, the open-plan lounge.**
Its four fitted planes have enclosure 0.62–0.68, three of the four were already
marked uncertain by the fitter, and the overlay shows all four are ceiling
stripes and window-edge misfits. No wall exists in the fit. Abstaining is the
correct answer, and it is the *only* place the permissive point abstains.

Moderate adds s10 (same failure), the kitchen stools and counter (the island
plane rejected, nothing else survives), and s07's second stool — 12 in all.
Conservative adds s06 and s08 (19). The 0.40 diagnostic abstains on 25, including
correctly-decided easy negatives like `s01.armchair.0` and `s04.chair.0`. **Every
abstention at the permissive point is on genuinely ambiguous geometry; at the
stricter points abstention starts consuming cases that were decidable.**

Historical positives: **0 of 11 abstained** at permissive. The gate does not
remove the walls the positives need.

---

## 10. The Phase 5 0.40 diagnostic on the full 48 **[M]**

Re-run exactly: `inlier_fraction ≥ 0.40`, nothing else changed.

| | Phase 5 (26 cases) | **Full 48** |
|---|--:|--:|
| False-wall | 0.0% | **0.0%** |
| Balanced accuracy | 77.8% (oracle geometry) | 55.0% (SAM geometry) |
| UNKNOWN | 9 / 26 (35%) | **25 / 48 (52%)** |
| Coverage | 65% | **47.9%** |

The promise survives on the false-wall side — zero, on all 37 negatives — and
**collapses on coverage**: it decides fewer than half the cases, and the sweep
(§15) shows the inlier feature has a cliff, not a slope: false-wall drops from
17.4% at 0.25 to 4.3% at 0.30, then trades only coverage below that. Inlier
fraction is a proxy for the two features that actually carry the signal, and a
lossy one. **[I]**

---

## 11. Contaminant-plane analysis **[M]**

Every Phase 3 false wall, its old plane, and what the permissive gate did.

| Case | Object | Old plane | Old `if` | Class (eye) | Rejected? | New decision |
|---|---|:--:|--:|---|:--:|---|
| `s07.bar_stool.0` | bar stool | w1 | 0.212 | **island front** | ✓ | **YES** — fell to w3, a ceiling-strip misfit (if 0.10), gap 0.087 |
| `s07.bar_stool.1` | bar stool | w1 | 0.212 | **island front** | ✓ | NO ✓ (w0, the cabinet wall, 2.68 m) |
| `hist_neg.kitchen.bar_stool.0` | bar stool | w2 | 0.286 | **island front** | ✓ | NO ✓ (w0, back wall, 1.11 m) |
| `hist_neg.kitchen.bar_stool.1` | bar stool | w2 | 0.286 | **island front** | ✓ | NO ✓ (1.14 m) |
| `hist_neg.kitchen.bar_stool.2` | bar stool | w2 | 0.286 | **island front** | ✓ | NO ✓ (1.18 m) |
| `s17.chair.0` | chair | w2 | 0.131 | **glazed partition** | ✓ | NO ✓ (w0, exterior wall, 2.53 m) |
| `s17.chair.1` | chair | w2 | 0.131 | **glazed partition** | ✓ | NO ✓ (1.81 m) |
| `s16.chair.0` | chair | w3 | 0.343 | **real wall** | ✗ | YES — 0.012 m from the panelled wall |

**Seven of eight contaminant planes rejected; six of eight cases corrected.**
The two residual false walls are different in kind and worth keeping apart:

- `s07.bar_stool.0` — the gate removed the island, and the object fell through to
  a *second* contaminant, a low-support ceiling misfit that clears enclosure 0.90
  and has no floor-band support. A plane-support floor catches it (the
  conservative point does, at a coverage cost). **[M]**
- `s16.chair.0` — **not a contaminant.** The plane is the wall, classed so by eye
  before any result was read, and the chair's back is 1.2 cm from it. The label
  says *not against a wall* and, watching the scene, that is defensible: it is
  beside a bench, not placed against the wall. Geometrically it is against the
  wall. This is the benchmark's definitional question from Phase 5 §17, now
  reduced to one concrete case. **[Q]**

---

## 12. Wrong-side-wall analysis **[M]**

Phase 4 found 13 cases with a candidate plane the object lay entirely beyond.
Under every operating point — permissive, moderate, conservative and the 0.40
diagnostic — the number of such planes surviving the gate is **zero**. The
wall-quality filter eliminates the wrong-side problem as a side effect; a
plane an object sits entirely beyond is, in this benchmark, always a plane that
fails enclosure. No separate rule is needed, and none was implemented.

---

## 13. Generated vs historical **[M]**

| Permissive | Negatives | False-wall | UNKNOWN (neg) | Positives | Pos recall | UNKNOWN (pos) |
|---|--:|--:|--:|--:|--:|--:|
| Generated | 32 | **7.1%** (2/28) | 4 | 0 | — | — |
| Historical | 5 | **0.0%** (0/5) | 0 | 11 | 9.1% | **0** |

The same operating point behaves sensibly on both sources. On historical
imagery it removes all three kitchen false walls, abstains on nothing, and
leaves every positive's wall available. On generated imagery the two residual
false walls are the two cases in §11 and the four abstentions are one scene.

---

## 14. Category A / B **[M]**

| Permissive | False-wall |
|---|--:|
| Category A (free-standing context) | **0.0%** |
| Category B (wall-backed context) | **11.1%** |

Both residual false walls are Category B — the object *is* near a vertical
plane; the disagreement is about whether it is a wall. The category effect that
has tracked through Phases 1h, 3 and 5 is now fully explained by contaminant
planes and one borderline label.

---

## 15. Threshold diagnostic **[M]**

*Diagnostic only. One feature at a time, reported as curves. Nothing here was
selected as a result.*

| `enclosure ≥` | coverage | false-wall | pos recall | AUC |
|--:|--:|--:|--:|--:|
| 0.80 | 91.7% | 18.2% | 18.2% | 0.763 |
| 0.90 | 83.3% | 17.2% | 18.2% | 0.774 |
| **0.95** | 68.8% | **4.3%** | 10.0% | 0.870 |
| 0.99 | 60.4% | 5.3% | 10.0% | 0.895 |

| `floor_band ≤` | coverage | false-wall | pos recall | AUC |
|--:|--:|--:|--:|--:|
| 1.00 (off) | 100% | 21.6% | 18.2% | 0.745 |
| **0.75 / 0.50 / 0.25** | **100%** | **10.8%** | 9.1% | 0.808 |
| 0.10 | 93.8% | 8.6% | 10.0% | 0.820 |

| `inlier ≥` | coverage | false-wall | pos recall | AUC |
|--:|--:|--:|--:|--:|
| 0.25 | 70.8% | 17.4% | 18.2% | 0.783 |
| **0.30** | 68.8% | **4.3%** | 10.0% | 0.896 |
| 0.40 | 47.9% | 0.0% | 10.0% | 0.939 |

| `height ≥` / `upper_band ≥` | coverage | false-wall | **pos recall** |
|--:|--:|--:|--:|
| height 1.0 m | 91.7% | 13.9% | **0.0%** |
| upper band 0.05 | 75.0% | 15.2% | **0.0%** |

Three readings. **Floor-band alone halves false walls at zero coverage cost** — it
removes the islands and nothing else. **Enclosure alone needs 0.95 to bite**,
and pays 31% coverage for it; combined with floor-band at only 0.80 it reaches
6.1% at 8% coverage cost, which is why the permissive point is the frontier.
**Any height-based floor drives positive recall to zero** — the occlusion
confound, measured. There *is* a useful precision/coverage frontier, and it runs
through the two enclosure/floor-band features, not through inlier fraction or
height.

**Oracle geometry with a gated wall set** (26-case subset, amodal boxes from
Phase 5): conservative → false-wall **10.0%**, balanced accuracy **70.0%**, AUC
**0.9125**; the 0.40 diagnostic → 0.0% / 77.8% / 0.9167, reproducing Phase 5.
With both the object side and the wall side repaired, the ceiling is in the
70–78% band. **[M]**

---

## 16. Failure analysis

**What remains wrong at the permissive point, and where it lives.**

| Residual | Count | Side | Evidence |
|---|--:|---|---|
| Missed positives | 10 | **object** | Every one selects a wall classed ROOM_BOUNDING_WALL by eye, with inlier fraction 0.63–0.83 — the *right* plane. Gaps are 0.12–1.01 m: the nearest visible surface of a sofa, bed or bedside unit whose back is occluded. Phases 4–5 diagnosed this exactly; it is frozen here. |
| False wall, second contaminant | 1 | wall | `s07.bar_stool.0` fell to a misfit the gate did not catch. |
| False wall, borderline label | 1 | benchmark | `s16.chair.0`, 1.2 cm from a real wall. |
| Abstentions | 4 | geometry | s11: no wall fitted. Correct to abstain. |

The selection analysis makes the migration explicit. Under the gate, the
selected plane's inlier fraction is **0.31 median when the decision is right and
0.65 when it is wrong** — the inverse of Phase 5. "Wrong" is now the missed
positives, and their walls are the *best*-supported planes in the set. The
error has moved from the wall side to the object side, which is what a
successful wall gate should do. **[M]**

Two upstream defects surfaced and are recorded, not fixed: **both kitchens fit
the countertop as the floor** (§5), and **two scenes fit no wall at all** (s10,
s11 — every plane a ceiling stripe). The gate handles the second gracefully by
abstaining. The first distorts every height-based feature in those images and
is one more reason height was kept out of the gate.

---

## 17. Decision

**PARTIAL PASS**, against the brief's eight criteria:

| | Criterion | Result |
|--:|---|:--|
| 1 | Full-48 false-wall materially below Phase 3/4 | ✓ **21.6% → 6.1%** (37.8% in Phase 4) |
| 2 | Island / desk / bench / partition false walls substantially reduced | ✓ 7 of 8 contaminant planes rejected, 6 of 8 cases corrected |
| 3 | UNKNOWN concentrated on genuinely ambiguous geometry | ✓ all 4 in one scene with no fitted wall |
| 4 | Positive recall does not collapse | ✗ **already collapsed on entry** (18.2%), 9.1% on exit; the gate selects the correct wall for every positive it decides — the miss is the frozen object statistic |
| 5 | Coverage remains useful | ✓ **91.7%** |
| 6 | Reproducible | ✓ four controls exact, zero per-case drift |
| 7 | Same operating point reasonable on generated and historical | ✓ 7.1% / 0.0%, no historical abstention |
| 8 | Interpretable feature separation | ✓ enclosure and floor-band, with the height confound named |

The "particularly strong" bar — **<10% false-wall with meaningful coverage** —
is met at 6.1% / 91.7%. The bar's third clause, *no catastrophic positive-recall
regression*, is met only in the narrow sense that recall was already at the
floor; it would be dishonest to call 9.1% anything but broken, whatever caused
it. Hence partial, not full.

Nothing integrated. `app/spatial/planes.py` untouched; no `wall_quality.py`
under `app/`; UNKNOWN not surfaced to production; no threshold tuned against
labels; no case added, removed or relabelled.

---

## 18. Recommendation

**Conclusion, in the brief's terms: the spatial engine needs a room-boundary /
wall-quality layer, and monocular geometry can supply it.** Two interpretable
features do the work; a learned classifier is not needed to reach this
frontier and should not be built to reach it.

**What to do next, in order:**

1. **Repair the object side.** Every remaining miss is a positive whose *correct*
   wall is now selected and whose distance is measured from the wrong surface.
   Phase 5 showed manual amodal extent recovers those cases, and §15 shows
   oracle geometry plus this gate reaches 70–78% balanced accuracy. Amodal
   extent is now the binding constraint — the thing Phase 5 said not to build
   *yet* is what the evidence now points at. Whether to *estimate* it (a
   perception model) or *supply* it (asset dimensions from the catalogue, which
   Allure already has for every placed object) is the next decision, and the
   second option is free. **[I]**

2. **Fix the floor search before trusting height.** Two kitchens fit the
   countertop. Until the floor is right, no height-based feature is safe and
   `enclosure` + `floor_band` should carry the gate alone. **[M]**

3. **Settle `s16.chair.0`.** One case now embodies the question Phase 5 raised:
   is "against a wall" a placement intent or a geometric fact? A chair 1.2 cm
   from a wall is one under the geometric reading and not under the intent
   reading. The label is defensible either way; the primitive needs to know
   which it is answering. Product decision, before any further scoring.

4. **Keep abstention.** Four of four abstentions were on scenes with no wall.
   That is the behaviour a design tool wants, and `Decision.UNKNOWN` has waited
   five phases to be used.

**What not to do:** do not add a height floor (kills positives), do not use
inlier fraction as the primary gate (a cliff, not a slope, and half the
coverage), and do not read Phase 2's bounding-box positive recall as a target —
it was the wall pixels inside the box, and Phase 3 proved it.

---

## 19. Production readiness

Not claimed, not tested. One primitive has been measured across six phases. Its
wall side now has a viable, interpretable filter; its object side is diagnosed
and unrepaired. Object grounding, coordinate placement, the spatial graph, asset
normalisation, constraint solving, collision validation and Blender integration
remain untouched and unevaluated. **[N]**

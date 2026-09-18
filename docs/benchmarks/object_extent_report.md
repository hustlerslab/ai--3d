# Phase 7 — Object → Wall Distance from Catalogue-Grounded Extent

**Verdict: PARTIAL PASS.** Replacing the nearest-visible-surface distance with a
physical extent grounded in the asset catalogue lifts **positive recall from 9.1%
to 70.0%**, F1 from 14.3% to 70.0%, balanced accuracy from 51.5% to 79.6% and AUC
from 0.8402 to 0.8929 — on the same 48 cases, the same frozen Phase 6 wall gate,
the same 0.12 m threshold, with no label consulted anywhere. Four of the five
positives Phase 3 lost are recovered. The cost is one additional false wall
(2 → 3) and six additional abstentions, every one of them a mask whose extent no
catalogue dimension could explain.

It does not meet the production targets: decided-case precision is **70%**
against ≥90%, and false-wall is **10.7%** against <10% — by one case. Two of the
three false walls and two of the three misses are in the images whose fitted
floor is the countertop. **The floor is now the gating defect**, exactly as the
brief anticipated, and Phase 8 follows from measurement rather than plan.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/object_extent_results.json`
**Scripts:** `research/spatial_engine/object_extent.py`, `object_extent_benchmark.py`
**Production code changed:** none. Dependencies changed: none.
`pytest -q` → 355 passed, 7 skipped, 30 xfailed, before and after.

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**,
**[N] not tested**.

---

## 1. Objective

Fix the object side of wall contact. Phase 6 showed every missed positive selects
the *correct* wall and measures the wrong distance to it, because a single view
sees a sofa's front and not its back. Phase 5 showed that hand-supplied physical
extent repairs those cases. This phase supplies the extent from data Allure
already holds — the asset registry and catalogue — before considering any
learned amodal model.

## 2. Baseline (frozen)

Phase 6 permissive gate (`enclosure ≥ 0.80`, `floor_band ≤ 0.75`), nearest
visible surface, 0.12 m: **1 / 31 / 2 / 10, 4 UNKNOWN**. Reproduced exactly at the
start of the run, zero per-case drift; the harness aborts otherwise. **[M]**

## 3. Hypothesis

> distance(object physical extent, wall) separates wall contact better than
> distance(visible surface, wall), and the physical extent can be built from
> catalogue dimensions plus a geometrically scored orientation hypothesis.

## 4. `AssetSpatialMetadata` — what the catalogue actually holds **[M]**

| Source | Records | What it is | Confidence assigned |
|---|--:|---|--:|
| **Registry** | 58 assets, 25 types | dimensions measured from the normalised mesh: metres, +Y up, −Z forward, bottom-centre pivot | 0.9 |
| **Built-in catalogue** | 25 items | designed dimensions | 0.7 |
| **Family default** | 12 families | generic size per family | 0.4 |

Resolution is deterministic: registry median for the canonical type (spread
across records recorded as uncertainty) → built-in → family default → UNKNOWN.
On the 48 benchmark cases: **45 registry, 2 built-in, 1 family default, 0
unknown**. Mount and placement class come from the vocab (`FLOOR_STANDING` for
every case here).

Dimensions were validated against the only independent source available — the
Phase 5 hand estimates on 26 cases: median depth difference **−0.01 m**, median
absolute difference **0.074 m**, 13 of 26 within the hand estimate's own
uncertainty. The largest disagreement is the TV: the registry's `tv_unit` is a
0.52 m-deep cabinet, the benchmark's box is an 8 cm panel. **[M]** That is a
semantic-type mismatch between annotation and asset, not a measurement error, and
it is the case the benchmark should catch (§9).

## 5. Methods tested

All four use the same SAM mask, the same MoGe-2 points, the same gated walls.

| Method | Orientation | Dimensions | Role |
|---|---|---|---|
| `visible` | — | — | frozen baseline |
| **`catalogue_wallnormal`** | hypotheses along the wall normal; feasible dimension **closest** to the visible span wins | catalogue | **primary, pre-declared** |
| `catalogue_depthfirst` | prefer depth along the normal when feasible (the asset's forward axis) | catalogue | post-hoc physical prior |
| `catalogue_pca` | Phase 5's construction: principal axis of the visible points | catalogue | secondary |
| `family_default` | as primary | generic | diagnostic |

Physical rear extent = `min(nearest visible point, farthest visible point −
dimension)`: the object can never be further from the wall than something already
seen. UNKNOWN when no wall survives the gate, when no metadata exists, or when the
visible span exceeds every catalogue dimension by more than 0.5 m — the mask, the
geometry or the asset disagree, and hidden geometry is not fabricated.

## 6. Results — full 48 **[M]**

| | visible (frozen) | **catalogue_wallnormal** | depthfirst (post hoc) | pca | family_default |
|---|--:|--:|--:|--:|--:|
| TP / TN / FP / FN | 1/31/2/10 | **7/25/3/3** | 7/24/4/3 | 6/25/8/5 | 5/28/2/4 |
| UNKNOWN | 4 | **10** | 10 | 4 | 9 |
| Coverage | 91.7% | **79.2%** | 79.2% | 91.7% | 81.2% |
| False-wall (decided) | 6.1% | **10.7%** | 14.3% | 24.2% | 6.7% |
| False-wall (of all 37 neg.) | 5.4% | **8.1%** | 10.8% | 21.6% | 5.4% |
| NO recall | 93.9% | **89.3%** | 85.7% | 75.8% | 93.3% |
| **Positive recall** | 9.1% | **70.0%** | 70.0% | 54.5% | 55.6% |
| Precision | 33.3% | **70.0%** | 63.6% | 42.9% | 71.4% |
| **F1** | 14.3% | **70.0%** | 66.7% | 48.0% | 62.5% |
| **Balanced accuracy** | 51.5% | **79.6%** | 77.9% | 65.2% | 74.4% |
| **AUC** | 0.8402 | **0.8929** | 0.8804 | 0.7231 | 0.8815 |
| Accuracy, all 48 (UNKNOWN = wrong) | 66.7% | 66.7% | 64.6% | 64.6% | 68.8% |

Three readings the table gives directly:

- **Orientation is the lever, not just dimensions.** The PCA construction with
  the *same* catalogue dimensions produces 24.2% false-wall; hypothesising along
  the wall normal produces 10.7%. A round object's principal axis is arbitrary;
  the wall's normal is not. **[M]**
- **Specific dimensions matter, but less than orientation.** Generic family sizes
  recover 55.6% of positives against 70.0% for the specific asset — and with one
  fewer false wall. The catalogue's contribution is real (+14 points of recall)
  but the method does not collapse without it. **[M]**
- **The post-hoc prior is worse.** `depthfirst` repairs nothing the primary
  missed (the bed moves 0.36 → 0.18 m, still NO) and creates one false wall
  (`s03.armchair.1`, 0.29 → 0.12 m). It is recorded as tested and rejected; the
  pre-declared rule stands. **[M]**

### Distances **[M]**

| primary | n | min | p25 | median | p75 | max |
|---|--:|--:|--:|--:|--:|--:|
| positives | 10 | 0.000 | 0.004 | **0.037** | 0.236 | 0.551 |
| negatives | 28 | 0.000 | 0.483 | **1.068** | 1.647 | 3.678 |

Phase 6's positives sat at a median of 0.25 m; they now sit at 0.037 m. The
threshold sweep is **flat from 0.08 m to 0.25 m** — identical confusion matrix
across that whole range — so the 0.12 m threshold is not doing delicate work.
*(Diagnostic; the gate used 0.12 m.)*

## 7. The tracked cases **[M]**

**Five Phase 3 missed positives — 4 of 5 repaired.**

| Case | visible | **catalogue** | rear | orientation | asset depth | verdict |
|---|--:|--:|--:|---|--:|---|
| `living_room_a.sofa.1` | 0.285 NO | **0.058 YES** | 0.058 | depth | 0.91 | ✅ repaired |
| `living_room_b.tv_unit.0` | 0.122 NO | **0.000 YES** | −0.362 | depth | 0.52 | ✅ repaired, 0.36 m penetration (asset mismatch, §9) |
| `master_bedroom.bedside_table.0` | 0.252 NO | **0.017 YES** | 0.017 | depth | 0.44 | ✅ repaired |
| `master_bedroom.bedside_table.1` | 0.196 NO | **0.041 YES** | 0.041 | depth | 0.44 | ✅ repaired |
| `master_bedroom.bed.0` | 0.451 NO | 0.362 NO | 0.362 | **width** | 2.04 | ✗ persistent |

The bed is the informative miss. The rule chose *width* (1.78 m) because the
visible mattress span was closer to it than to the 2.04 m depth; the post-hoc
depth rule gives 0.18 m — still NO — because the photographed platform extends
past the registry's mattress. The catalogue describes the asset that *will be
placed*, not the object in the photograph, and on this one case the two differ by
~0.2 m. **[I]**

**Nine Phase 2 false walls — 7 unchanged correct, 2 persistent.** `s07.bar_stool.0`
(kitchen; the fitted floor is the countertop; physical rear −0.52 m, an impossible
penetration) and `s16.chair.0` (1 mm from a genuine wall; the label-borderline
case carried since Phase 5).

## 8. UNKNOWN and coverage **[M]**

| Reason | Cases | Label |
|---|--:|---|
| No wall survived the Phase 6 gate | 4 (`s11.*`) | all negative |
| Visible span exceeds every catalogue dimension by > 0.5 m | 6 | 5 negative, 1 positive |

The six span abstentions are chairs and tables whose mask-plus-depth spans
1.3–3.8 m along the wall normal — `s10.chair.2` spans 3.81 m for a 0.65 m chair.
Four of them exceed *double* any dimension and are classed **PERCEPTION_FAILURE**:
the mask is bleeding into the scene. The visible-surface baseline got all five
negatives right, by their large distances; the catalogue method declines to
decide instead. That is the trade the brief asks for — "I don't know" over a
number that happens to be right. The one positive (`bathroom.vanity.0`, span
1.97 m) is the mirror scene Phase 6 flagged.

Historical positives: **1 of 11 abstained, 0 wrong walls.** The gate and the
extent together leave every historical positive's wall available.

## 9. Failure analysis **[M]**

| Category | n | Cases |
|---|--:|---|
| **FLOOR_FAILURE** | 4 | `s07.bar_stool.0` FP · `s13.armchair.0` FP · `kitchen_counter.0` FN · `living_room_b.sofa.0` FN — all in images where the camera sits < 0.9 m above the fitted "floor" |
| **PERCEPTION_FAILURE** | 4 | mask span > 2× any dimension → UNKNOWN |
| **WALL_FAILURE** | 4 | `s11.*`: no wall fitted → UNKNOWN (correct behaviour) |
| **OBJECT_EXTENT_FAILURE** | 3 | `bed.0` FN (orientation/asset mismatch) · `vanity.0`, `s15.dining_table.0` UNKNOWN |
| GROUNDING_FAILURE | 1 | `s16.chair.0` — label-borderline |

**Two of three false walls and two of three misses are floor failures.** In the
kitchens the "floor" is the countertop, so every height-relative quantity is
offset by ~0.9 m and the island front sits "below floor"; `s13`'s camera is 0.69 m
above its floor, which is suspect for the same reason. The extent method cannot
be judged on those images until the floor is right. **[I]**

**Asset mismatch, made visible.** `tv_unit.0` is decided YES *correctly* but with
a 0.36 m penetration of the wall, because the catalogue offered a cabinet for a
panel. The method flags it (`penetration_m`, confidence 0.45) rather than hiding
it. Where the annotation's type and the asset's type disagree, the benchmark
should say so; it does.

**Decision confidence is not calibrated.** Abstaining below `decision_confidence
≥ 0.5` drops coverage to 60% and *lowers* precision to 50%, because the field is
dominated by source and wall-quality factors, not by correctness (diagnostic in
the raw JSON). It is not usable as an UNKNOWN threshold yet and is not used as
one. **[M]**

## 10. Splits **[M]**

| primary | FP/TN | false-wall | pos recall | bal. acc |
|---|--:|--:|--:|--:|
| Historical | 0/5 | **0.0%** | 70.0% | **85.0%** |
| Generated | 3/20 | 13.0% | — (no positives) | — |
| Category A / B | 1/10 · 2/15 | 9.1% · 11.8% | — | — |
| Open-structure / solid | 3/25 · 0/0 | 10.7% · — | 100% (1) · 66.7% (9) | 94.6% · — |

The method is clean on the real photographs and every residual false wall is on
generated imagery — two of them in the floor-failed kitchen and lounge.

## 11. Hardware, latency, licence **[M]**

| | |
|---|--:|
| Extent computation | **37 ms / case median, 45 ms p95**, CPU numpy |
| Metadata resolution | 2.5 ms / case |
| VRAM | **none** — no model |
| Perception it depends on (SAM 2 + MoGe-2, already measured) | 113 s for 21 images / 48 cases, ~2.6 GB peak |
| New dependencies | none · New models | none · Licence | n/a |

## 12. Decision

**PARTIAL PASS**, against the §41 targets:

| Target | Result |
|---|:--|
| Critical wall contact ≥ 90% precision on decided cases | ✗ **70.0%** (7 of 10) |
| False-wall < 10% at useful coverage | ✗ **10.7%** at 79.2% — one case over |
| UNKNOWN allowed and measurable | ✓ 10, every one with a stated reason |
| Positives recovered (the phase's own objective) | ✓ 9.1% → 70.0% |
| No regression on the wall side | ✓ NO recall 93.9% → 89.3%, one case |

**What changed:** the object side. Every positive that is decided now measures a
physical rear extent, and 7 of 10 decided positives are correct.
**What did not change:** the wall gate, the threshold, the masks, the geometry,
the labels, the cases, production code.
**What was rejected:** the PCA orientation (24.2% false-wall) and the post-hoc
depth-first prior (worse on both sides). No learned amodal model was tried,
because the deterministic method reached 70% recall without one and its residuals
are not extent errors.

## 13. Next step

**Phase 8, floor reconstruction, before anything else on this primitive.** The
dependency is measured: 4 of the 7 wrong-or-missed decided cases are in
floor-failed images. Until the floor is right, no height-relative feature can be
trusted, and the two kitchens' wall contact cannot be scored at all. After that,
re-run this benchmark unchanged and read precision again.

Two items carried forward, not fixed here: the `tv_unit` annotation/asset
mismatch (a benchmark hygiene issue: the annotated object is a TV, the catalogue
type is a cabinet), and `s16.chair.0`, which needs the product decision Phase 5
raised.

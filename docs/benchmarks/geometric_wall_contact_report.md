# Spatial engine Phase 1 — deterministic geometric wall contact

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/geometric_wall_contact_results.json`
**Code:** `app/spatial/planes.py` (zero production imports) · `research/spatial_engine/geometric_wall_contact.py`

# 1. Executive result

**NO-GO.** Geometric wall contact from **relative** monocular depth scores
**61.5% false-wall** on decided cases against the VLM's measured **14.1%**. It is
worse than the system it was meant to replace.

The diagnosis is more valuable than the score. **Separation AUC is 0.55** — the
measurement carries almost no information about wall contact, and no threshold
rescues it. The cause is visible in the plane fits: the dominant rejection reason
across ~80 fitted planes is **"Manhattan residual 20–30°"**, meaning walls that
should be perpendicular to the floor come out systematically ~25° off. Scene scale
varies **8.4×** between rooms (1.77 → 14.89).

Both are signatures of one thing: **unprojecting affine-invariant depth with a
guessed camera does not produce Euclidean geometry.** The module docstring
predicted this failure mode before the experiment ran; the experiment confirms it
is fatal rather than tolerable.

**This does not falsify the architecture.** It falsifies the cheapest possible
substitute for one of its components. Architecture B specifies a *metric* geometry
model (MoGe-2 / UniDepthV2); Phase 0 recorded both as blocked on a missing
dependency, so this experiment used the Apache-2.0 relative model that was already
reachable. The result is that metric geometry is a **prerequisite, not a preference**.

---

# 2. Exact dataset

Used as annotated. No label changed, no case dropped, no image cherry-picked.

| | count |
|---|--:|
| Cases | **48** |
| Negatives / Positives | 37 / 11 |
| Generated (Phase 1g) | 32 (all negatives) |
| Historical | 16 (11 positives + 5 negatives) |
| Distinct images / scenes | 21 |

**One addition, flagged.** The Phase 1g dataset's negatives are *all* generated and
its positives are *all* historical, so it alone cannot answer the "historical vs
generated" question. The **5 historical negatives** from
`tests/fixtures/relationship_benchmark.json` — the same hand-verified negatives
Phases 1c–1f scored against, unchanged — are included so both halves have negatives.
That restores exactly the 16-case historical set Phase 1e/1f/1h measured.

---

# 3. Method

```
image (704×448)
  → Depth Anything V2 Small  (Apache-2.0; relative inverse depth)
  → interpolate 518×812 → 448×704   [required; the processor resizes internally]
  → unproject under an ASSUMED 60° horizontal FoV      → point map, UNSCALED
  → mask out all annotated object boxes                 [so walls aren't fitted to sofas]
  → RANSAC floor plane (normal filter |n_y| > 0.55)
  → gravity-aligned up vector from the floor normal
  → RANSAC wall planes ⟂ floor, one at a time, inliers removed between fits
  → Manhattan snap; record raw normal, snapped normal, angular residual
  → reject planes on extent / inlier fraction / Manhattan residual
  → object footprint = annotated box ∩ valid depth
  → reject planes that CUT THROUGH the object rather than sitting behind it
  → distance = 10th percentile |signed distance| to the nearest surviving plane
  → YES / NO / UNKNOWN
```

No model is asked any question. `metric_source = "unscaled"` throughout, so the
**relative** threshold applies and every result is labelled relative.

**Two corrections made during development**, both from observed failures rather than
tuning: excluding annotated object pixels from the wall fit (the first run fitted
"walls" through sofas and scored 100% false-wall), and rejecting planes that split
an object rather than sitting behind it.

---

# 4. Thresholds

| Constant | Value |
|---|--:|
| `WALL_CONTACT_RELATIVE_TOLERANCE` | 0.04 of room extent |
| `WALL_CONTACT_DISTANCE_M` | 0.12 m (unused — scene is unscaled) |
| `MIN_WALL_INLIER_FRACTION` | 0.06 |
| `MIN_OBJECT_GEOMETRIC_CONFIDENCE` | 0.35 |
| `MIN_WALL_EXTENT_FRACTION` | 0.015 |
| `WALL_VERTICALITY_TOLERANCE_DEG` | 25.0 |
| `MANHATTAN_SNAP_TOLERANCE_DEG` | 20.0 |
| `MIN_ONE_SIDED_FRACTION` | 0.85 |
| RANSAC | 400 iterations, seed 20260915 (deterministic) |

Frozen before the full run. The sweep in §12 is diagnosis, not selection.

---

# 5–9. Results

| Subset | n | neg | TN | FP | TP | FN | UNK(neg) | **false-wall (decided)** | **false-wall (all)** | unknown | coverage |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **All** | 48 | 37 | 10 | 16 | 4 | 2 | 11 | **61.5%** [42.5, 77.6] | **43.2%** | 29.7% | 66.7% |
| **Generated** | 32 | 32 | 9 | 16 | — | — | 7 | **64.0%** [44.5, 79.8] | 50.0% | 21.9% | 78.1% |
| **Historical** | 16 | 5 | 1 | 0 | 4 | 2 | 4 | **0.0%** [0.0, 79.3] | 0.0% | **80.0%** | 43.8% |
| Category A | 19 | 19 | 4 | 8 | — | — | 7 | 66.7% [39.1, 86.2] | 42.1% | 36.8% | 63.2% |
| Category B | 18 | 18 | 6 | 8 | — | — | 4 | 57.1% [32.6, 78.6] | 44.4% | 22.2% | 77.8% |

**The historical 0.0% is not a success.** It rests on **one** decided negative out of
five; the other four were UNKNOWN. Its confidence interval runs to 79.3%. Reported
because the brief asks for the split, but it carries no weight.

**Two false-wall rates, as required.** 61.5% counts only negatives that got an
answer. 43.2% counts UNKNOWN against us. Neither is near the 10% gate.

---

# 10. Confidence intervals

All Wilson 95%, in the table above. The aggregate false-wall interval
**[42.5, 77.6]** does not come close to overlapping the VLM baseline's
**[7.6, 24.6]**. The two methods are separated by far more than their uncertainty.

---

# 11. Per-scene

Full per-scene breakdown is in the raw JSON. The headline structural facts:

- **Floor fitting succeeded on 21 of 21 images.** The floor is findable.
- **5 of 21 images produced ZERO usable wall planes** — `s10_office`, `s11_lounge`,
  and three historical moodboards (`living_room`, `kitchen`, `bathroom`). Every
  UNKNOWN in the run (16 of them) has the same cause: *"no wall plane passed its
  checks"*.
- Of ~80 fitted planes, **43 were accepted and ~37 rejected**, and the rejections
  are overwhelmingly Manhattan residuals of 20–30°.

---

# 12. Failure analysis — where it actually breaks

### The decisive number: separation AUC = 0.55

| | n | median relative distance |
|---|--:|--:|
| Positives (genuinely against a wall) | 6 | **0.0363** |
| Negatives (free-standing) | 26 | **0.0240** |

**Objects that are against a wall measure *further* from the fitted wall than
objects that are not.** The signal is not merely mis-calibrated — it is absent, and
mildly inverted. AUC 0.55 against 0.50 for a coin.

### Threshold sweep — confirms no cut helps

| Relative threshold | false-wall | NO-recall | positive recall | balanced accuracy |
|--:|--:|--:|--:|--:|
| 0.01 | 23.1% | 76.9% | 33.3% | 55.1% |
| 0.02 | 50.0% | 50.0% | 33.3% | 41.7% |
| **0.04** (frozen) | **61.5%** | 38.5% | 66.7% | 52.6% |
| 0.07 | 73.1% | 26.9% | 100% | **63.5%** |
| 0.10 | 76.9% | 23.1% | 100% | 61.5% |
| 0.30 | 100% | 0% | 100% | 50.0% |

Best balanced accuracy anywhere is **63.5%**, and it buys that by saying YES to
almost everything. No operating point reaches the gate.

### Root cause, attributed

Against the brief's six candidates:

| Candidate | Verdict |
|---|---|
| **A. Depth** | **Contributing.** Relative depth is the input to the failing step. |
| B. Object localisation | **Excluded.** Boxes are hand-verified ground truth. |
| C. Room-plane fitting | **Partly excluded.** Floor fit 21/21. The *algorithm* works; its input does not. |
| **D. Scale** | **PRIMARY.** Scene scale spans 8.4× (1.77 → 14.89) across rooms, and walls come out 20–30° from vertical. Both are the signature of unprojecting affine-invariant depth (d = a/Z + b, b unknown) through a guessed 60° FoV: the unknown shift bends the cloud so planarity and perpendicularity both fail. |
| E. Architecture masking | **Contributing, secondary.** Excluding object boxes moved false-wall 100% → 62.5% on the pilot, so masking matters — but curtains, cabinetry and unannotated furniture still pollute the fits. |
| F. Benchmark / image quality | **Excluded.** Same images and labels on which the VLM scored 14.1%. |

**The order matters.** Segmenting architecture on a geometrically distorted point
cloud does not undistort it. Fix the geometry first; masking is the second-order
correction on top.

---

# 13. Comparison with Phase 1H

| | Phase 1h — qwen2.5vl:7b | **Phase 1 — geometry (relative depth)** |
|---|--:|--:|
| False-wall (decided) | **14.1%** [7.6, 24.6] | **61.5%** [42.5, 77.6] |
| False-wall (all negatives) | 14.1% | 43.2% |
| NO-recall | **85.9%** | 38.5% |
| UNKNOWN | 0% (it always answered) | **29.7%** |
| Determinism | flips on 9.4% of cases between runs | **fully deterministic** (seeded RANSAC) |
| Cost | 2.70 GB CPU spill, cannot share the card | **796 MiB, 0.12 s/image** |
| Auditability | `"high"` confidence on most wrong answers | inlier fractions, residuals, named failure reasons |

Geometry loses on accuracy, and wins decisively on **determinism, cost and
auditability**. Every property the architecture wanted is present; the measurement
underneath them is not yet good enough.

---

# 14. Interpretation

The experiment tested a *substitute* for Architecture B's geometry stage, not the
stage itself. Architecture B specifies a metric geometry model. Phase 0 found both
candidates blocked on a missing pip package, so the pipeline was built on the
Apache-2.0 relative model already reachable through `transformers`, with the
affine-ambiguity risk documented in advance.

That risk materialised, and the evidence is specific rather than vague: walls tilted
20–30°, scale varying 8.4× between rooms, separation AUC 0.55. Those are not
symptoms of a bad threshold or a weak heuristic — they are what a non-Euclidean
point cloud looks like when you measure angles and distances in it.

So the honest conclusion is narrow and useful: **relative depth plus an assumed
camera is not a viable foundation for wall contact.** Whether *metric* geometry is
remains untested, and is now the single question worth answering.

Three things did work and should be kept: floor fitting (21/21), determinism
(identical results on re-run, unlike the VLM's 9.4% flip rate), and honest
abstention (16 UNKNOWNs, every one with a named reason — a capability the VLM never
demonstrated in 78 attempts).

---

# 15. GO / NO-GO

## **NO-GO** — against the stated gate

| Gate | Threshold | Measured | |
|---|---|--:|:--|
| PASS | false-wall < 10% | 61.5% | ✗ |
| PARTIAL | 10–20% | — | ✗ |
| **FAIL** | **> 20%** | **61.5%** | **← here** |

Not integrated. Production behaviour unchanged. `app/spatial/planes.py` has zero
production imports.

### Smallest correction — exactly one

**Install a metric geometry model (MoGe-2 preferred, UniDepthV2 as fallback) and
re-run this identical benchmark unchanged.**

Why this one and not architecture segmentation:

- It targets the **primary** root cause (D/A). Segmentation targets the secondary
  one (E), and cannot repair a distorted cloud.
- It is **falsifiable on the same 48 cases with the same labels and the same
  thresholds** — a direct before/after with nothing else moving.
- It produces two immediate diagnostics that say whether it worked *before* any
  accuracy number is read: **Manhattan residuals should collapse from 20–30° to
  single digits**, and **scene-scale spread should fall from 8.4× toward 1×**.
  If those two do not move, metric depth is not the answer either and the next
  suspect is the depth model's absolute accuracy at 704×448.
- It costs one dependency — the one Phase 0 already flagged as blocking — and about
  a day.

**It also changes `metric_source` from `unscaled` to `metric_model`**, which
activates the absolute 0.12 m threshold instead of the relative one and removes the
per-scene normalisation that the 8.4× spread makes unreliable.

If metric geometry also fails to move the Manhattan residuals, the correct
conclusion is that monocular geometry is insufficient at this resolution, and the
next step is the floor-plan fusion the architecture already specifies — which
supplies true scale and wall topology from data we already collect, rather than
inferring either from pixels.

**STOP. Do not proceed to Phase 2 without approval.**

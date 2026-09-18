# Phase 1h — frozen qwen2.5vl:7b wall-contact benchmark

**Model:** `qwen2.5vl:7b` Q4_K_M · **Date:** 2026-09-15 · **Queries:** 86 (43 cases × 2 runs)
**Raw:** `aether-backend/research/phase1h/raw.json` · **Results:** `research/phase1h/results.json`
**Dataset:** `research/phase1g/dataset.json`, unmodified · **Script:** `research/phase1h/run_1h.py`

Phase 1e, 1f and 1g artefacts untouched. No production file modified.

**Decision: PASS on the stated gates — but read §"What actually changed" before
acting on it.**

---

## Headline

| | Phase 1e | Phase 1f | **Phase 1h** |
|---|--:|--:|--:|
| Negative objects | 5 | 5 | **32** |
| Negative observations | 10 | 20 | **64** |
| **False-wall rate** | 50.0% | 35.0% | **14.1%** |
| 95% CI | ±26 pts | [18.1, 56.7] | **[7.6, 24.6]** |
| **NO recall** | 50.0% | 65.0% | **85.9%** [75.4, 92.4] |
| Case stability | 87.5% | 62.5% | **90.6%** (negatives) |

Per the brief, these are **not pooled** — the 1h dataset is substantially
different and is the primary benchmark.

---

## What actually changed — the caveat that governs everything below

Between Phase 1f and Phase 1h the model, prompt, schema, temperature, image
pipeline and parsing were all frozen and imported, not copied. **The only thing
that changed was the imagery.** False-wall went 35.0% → 14.1%.

That is not automatically evidence the model got better at anything. It is
equally consistent with the Phase 1g negatives being **easier to see**:

* The Phase 1g scenes were generated with prompts biased toward open-plan
  layouts, seating islands and wide floors, because that is how you get
  free-standing furniture out of SD 1.5 at all. Wide floors make separation from
  a wall visually obvious.
* The Phase 1f negatives came from cramped historical moodboards, where the
  free-standing pieces were three bar stools tucked at a counter.

So the honest reading of 14.1% is **"the frozen gate's false-wall rate on Phase
1g imagery"**, not "the frozen gate's false-wall rate". Phase 1f measured 35% on
historical imagery with the same model and prompt, and nothing here overturns
that measurement.

**Two further confounds, both stated rather than corrected:**

1. **Source domain.** The 32 negatives are generated SD 1.5 images; the 11
   positives are historical. Positive-vs-negative numbers are descriptive only.
2. **Description asymmetry.** The frozen prompt renders `{desc} (a {type})`, and
   the Phase 1g cases carry no `desc`. `annotations.json` has prose for every
   case — *"stands on the rug in open floor"*, *"the bed behind it is against the
   wall"* — and using it would have put the answer in the prompt. **It was not
   used.** Each negative was instead described by frame position computed from
   its bounding box alone (`"third from the left, in the foreground"`), while the
   11 positives kept their original fixture strings. Every string sent is
   recorded in `raw.json`.
   One inherited positive description reads *"the television itself, on the
   timber wall"* — it mentions a wall. It was sent identically in 1e and 1f, so
   it is frozen here for comparability, but it is a hint on a positive case and
   is noted.

---

## Environment

| | |
|---|---|
| GPU | RTX 3050 6GB Laptop, 6144 MiB → 4752 used / 1250 free after load |
| System RAM | 16.8 GB — 3.1 GB free (81%) before, 2.4 GB free (85%) after |
| Model | `qwen2.5vl:7b`, Q4_K_M, 6.17 GB |
| Residency | VRAM **3.47 GB** · CPU **2.70 GB** · **56.3% on GPU** |
| Load | 16.7 s · cold first query 21.6 s |
| Machine stability | stable throughout; RAM never below 2.4 GB free |
| Blender | not run |

**The Phase 1e/1f hardware constraint reproduces exactly** — 3.47 GB VRAM,
2.70 GB CPU, 56.3% GPU residency, to the decimal. RAM pressure was lower this
time (85% vs 93–95%), because no other model was resident.

---

## Dataset

Used exactly as annotated — no case dropped, added, re-categorised or re-boxed.

| | count |
|---|--:|
| Total cases | 43 |
| Negatives | **32** (Category A 17, Category B 15) across 16 scenes |
| Positives (preserved, unchanged) | 11 |
| Runs | 2, identical deterministic ordering |
| Inference failures | **0** |

---

## Primary result — the negative side

**Pooled over both runs, n = 64 observations on 32 objects:**

| | value |
|---|--:|
| TN | 55 |
| FP | **9** |
| Negative accuracy | 85.9% |
| **NO recall** | **85.9%** [75.4, 92.4] |
| **False-wall rate** | **14.1%** [7.6, 24.6] |

### Per run, not averaged away

| | Run 1 | Run 2 |
|---|--:|--:|
| TN / FP | 29 / 3 | 26 / 6 |
| NO recall | **90.6%** | 81.2% |
| False-wall rate | **9.4%** | 18.8% |

The runs still differ by a factor of two on the false-wall rate. Both sit at or
under the 20% gate, but a single run would have reported either 9.4% or 18.8%,
and the gate would have read very differently.

---

## Category A vs Category B — the 1f effect did not reproduce

| | n (obs) | objects | TN | FP | NO recall (95% CI) | False-wall (95% CI) |
|---|--:|--:|--:|--:|--:|--:|
| **Category A** | 34 | 17 | 30 | 4 | 88.2% [73.4, 95.3] | **11.8% [4.7, 26.6]** |
| **Category B** | 30 | 15 | 25 | 5 | 83.3% [66.4, 92.7] | **16.7% [7.3, 33.6]** |

Absolute difference: **4.9 points**. The confidence intervals overlap across
almost their entire range.

For comparison, Phase 1f on the confounded 5-object set: **A 0%, B 58.3%** — a
58-point gap. On 32 objects across 16 scenes, with category no longer meaning
scene, **that gap collapses to 4.9 points and is not distinguishable from noise.**

Phase 1f classified the failure mode as CONTEXT CONFUSION and explicitly labelled
it *"the leading hypothesis rather than a finding"*, noting the categories were
confounded with scene. **That hedge was correct, and this phase is the reason
it mattered.** On a properly balanced dataset the effect is not there.

### One real pattern inside the errors

Six distinct objects produced a false wall:

| Case | Cat | Type | Run 1 | Run 2 | Wall-backed mass behind |
|---|:--|---|:--|:--|:--|
| `s02.coffee_table.0` | A | coffee_table | **True** | **True** | no |
| `s13.armchair.0` | A | armchair | **True** | **True** | no |
| `s16.chair.0` | B | chair | **True** | **True** | yes |
| `s07.bar_stool.0` | B | bar_stool | False | **True** | yes |
| `s07.bar_stool.1` | B | bar_stool | False | **True** | yes |
| `s10.chair.0` | B | chair | False | **True** | yes |

The two Category A errors are **stable** — wrong in both runs, a consistent
misread of a drum table and a lounge chair. Three of the four Category B errors
are **unstable** — right once, wrong once. So what little category signal exists
here is about *error type* (consistent vs stochastic), not error *rate*. With
2 and 3 objects in those buckets, that observation is a lead for a future
experiment, not a result.

---

## Stability

| Subset | Cases | Stable | Flipped | Agreement |
|---|--:|--:|--:|--:|
| **Category A negatives** | 17 | 17 | **0** | **100%** |
| Category B negatives | 15 | 12 | 3 | 80.0% |
| **All negatives** | 32 | 29 | 3 | **90.6%** |
| Positives | 11 | 9 | 2 | 81.8% |
| All cases | 43 | 38 | 5 | 88.4% |

Against Phase 1f's 62.5% overall stability this is a clear improvement, and
Category A being perfectly stable across 34 observations is the single most
solid number in the phase. The instability that remains sits in Category B and
in the positives.

---

## Positive side — descriptive only, source-domain confounded

| | value |
|---|--:|
| TP / FN | 20 / 2 |
| Positive recall | 90.9% |
| Precision | 100% |

**All cases together** (86 observations): accuracy 87.2%, precision 69.0%,
recall 90.9%, F1 78.5.

These are **not** a go/no-go criterion. The positives are historical images with
richer prose descriptions; the negatives are generated images with computed
positional ones. Any difference between the classes is confounded twice over.

---

## Reliability and latency

| | value |
|---|--:|
| Valid JSON | **86 / 86 (100%)** |
| Inference failures | 0 |
| `GenerationStatus` | `complete` × 86 |
| Median latency | 0.90 s |
| p95 | 4.43 s |
| Worst | 21.6 s (cold first query) |
| Model load | 16.7 s |

Reliability has now been 100% in every phase from 1c onward. Latency remains a
non-issue: ~2 wall queries per scene at 0.9 s median is far inside any budget.

---

## Decision gates

| Gate | Threshold | Measured | |
|---|---|--:|:--|
| NO recall | ≥70% | **85.9%** | PASS |
| False-wall rate | ≤20% | **14.1%** | PASS (point estimate) |
| Accuracy | ≥75% | 85.9% negative / 87.2% all | PASS |
| Run-to-run stability | "reasonable" | 90.6% negatives, 88.4% all | PASS |

**All four gates pass on point estimates.** Two qualifications belong on the
same line as that sentence:

* The false-wall **95% CI is [7.6, 24.6]** — the upper bound is above the 20%
  gate. The data are consistent with the gate being met and with it being missed.
* Run 2 alone measured **18.8%**, which passes by 1.2 points.

---

## DECISION:
**PASS** — on the stated gates, on this dataset. Not a green light; see the
source-domain caveat, which is the dominant uncertainty and is unresolved.

## PRIMARY WALL RESULT:
**False-wall rate 14.1% [7.6, 24.6]; NO recall 85.9% [75.4, 92.4]** — 32 objects,
16 scenes, 64 observations, 9 false walls.

## CATEGORY A:
**11.8% false-wall [4.7, 26.6]**, 17 objects, **100% run-to-run stable**. Both
errors were consistent misreads rather than flips.

## CATEGORY B:
**16.7% false-wall [7.3, 33.6]**, 15 objects, 80% stable. **The Phase 1f
Category B effect (58.3%) did not reproduce** — the gap fell from 58 points to
4.9 and the intervals overlap. On a scene-balanced dataset, A and B are not
distinguishable.

## STABILITY:
**Improved but not resolved.** 90.6% of negatives stable (up from 62.5% in 1f),
Category A perfect at 100%; but the two runs still gave false-wall rates of 9.4%
and 18.8%, and 5 of 43 cases flipped.

## PRODUCTION INTEGRATION:
**NO.** Unchanged and independent of the result: 7B needs **2.70 GB of CPU
spill** at 56.3% GPU residency on this 6 GB card and cannot coexist with a
Blender render.

## NEXT EXPERIMENT:
**Build a source-balanced negative set — annotate ~30 negatives from historical
/ real interior photography and run the same frozen gate on them — so the
generated-vs-historical confound can be separated from model capability.**

This is now the dominant uncertainty and it is cheap to resolve. The same frozen
model and prompt scored **35% false-wall on historical imagery (1f)** and
**14.1% on generated imagery (1h)**. Until those are compared at matched sample
sizes, it cannot be said which number describes production, where the input is a
generated moodboard but of the project's own composition rather than one prompted
for wide open floors. If the historical rate stays near 35% at n≈30, the Phase 1h
pass is an artefact of easy imagery; if it falls toward 14%, the gate is genuinely
usable and the remaining blocker is purely the 6 GB card.

**STOP.**

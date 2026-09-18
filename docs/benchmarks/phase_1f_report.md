# Phase 1f — expanded negative wall-gate benchmark

**Model:** `qwen2.5vl:7b` Q4_K_M · **Date:** 2026-09-15 · **Queries:** 32 this phase, pooled to 64 with Phase 1e
**Raw data:** `phase_1f_raw.json` · **Script:** `aether-backend/research/phase1f/run_1f.py`
**Annotation:** `aether-backend/research/phase1f/case_categories.json`

**Decision: PARTIAL PASS · Failure mode: CONTEXT CONFUSION (suggested, not established).**
No production code changed. Phase 1e report and raw data untouched.

---

## 0. The expansion is blocked — read this first

The phase's method was to reach ≥25 negatives so the false-wall rate could be
measured with a usable interval. **The available imagery supports 5.**

Every source was examined: all 11 moodboard renders, all 8 reference photos.

| render | floor furniture | negatives |
|---|---|---|
| 553 living_room | sofa ×2 (wall), side_table (wall), ottoman | **ottoman** [A] |
| 553 kitchen | counter ×3 (wall / unknown), bar_stool ×3 | **bar_stool ×3** [B] |
| 553 bathroom | vanity (wall) | — |
| 553 master_bedroom | bed (wall), bedside ×2 (wall) | — |
| 553 primary_bedroom | console (wall), bed (wall), side_table (reads wall), floor lamp (ill-posed), white form (cut off, unidentifiable) | — |
| 553 second_bedroom | bed (wall), bench (wall) | — |
| archive living_room | sofa (wall), tv (wall), console (wall), coffee_table | **coffee_table** [A] |
| archive master_bedroom | bed (wall), bedside ×2 (wall) | — |
| archive kitchen | tall unit (wall), oven tower (wall), counter (wall), hob run (unknown) | — |
| archive second_bedroom | bed (wall), bedside (wall) | — |
| archive bathroom | vanity (wall), bathtub (alcove — UNKNOWN since 1c) | — |
| ref_04 … ref_12 | product shots of sofas and mattresses — warehouse, showroom, or white background; **two have no wall in frame at all** | — out of domain |

**Total: 5 negatives (Category A: 2, Category B: 3).**

The reason is structural, not an annotation failure: interiors are photographed
with the furniture against the walls. Free-standing pieces are rare in this
corpus and rarer still in any corpus of finished-room photography.

Several candidates were considered and **rejected rather than annotated to reach
a count** — the primary-bedroom side table (reads as against the wall), its floor
lamp ("is a pole lamp's back against a wall" is ill-posed), the unidentifiable
cut-off form beside it, the alcove bathtub and the ambiguous hob run (both
already UNKNOWN since Phase 1c), and all rugs. Each is listed with its reason in
`case_categories.json`.

### What this does and does not block

* **Objective A — what is the false-wall rate really? BLOCKED.** With 5 distinct
  objects, the sampling error lives in *which objects were chosen*. Repeating the
  benchmark reduces measurement noise; it does not narrow that. Pooling four runs
  gives 20 negative observations and a 95% interval of **[18.1, 56.7]** — still
  wide enough to contain both "meets the 20% gate" and "nowhere near it".
* **Objective B — general inability or wall-backed context confusion? ANSWERED,
  provisionally.** This is the phase's primary diagnostic question and it needs
  per-object *reliability*, which repetition does address.

The benchmark was therefore run as specified (2 runs, frozen conditions) and
reported for what it can support.

---

## Environment

| | |
|---|---|
| GPU | RTX 3050 6GB Laptop, 6144 MiB · after load: 4752 MiB used, 1250 MiB free |
| System RAM | 16.8 GB — 2.7 GB free (84%) before, **0.8 GB free (95%) after** |
| Model | `qwen2.5vl:7b`, Q4_K_M, 6.17 GB |
| Residency | VRAM 3.47 GB · **CPU 2.70 GB** · **56.3% on GPU** |
| Load time | 17.0 s |
| Frozen | temperature 0.2, `num_ctx`, `num_predict`, image px, prompt (`_wall_a`, imported), schema `{"answer": boolean}` |
| Blender | not run |

Only the dataset composition was intended to change. It could not, so in effect
**this phase changed nothing but the run count** — which is itself what produced
the finding below.

---

## Dataset

Identical to Phase 1d/1e. Nothing added, removed or re-annotated.

| | count |
|---|---|
| Positives | 11 |
| Negatives | 5 — Category A: 2, Category B: 3 |
| Total | 16 |

---

## Run-level results, not averaged away

| | 1f run 1 | 1f run 2 | 1e run 1 | 1e run 2 |
|---|--:|--:|--:|--:|
| Accuracy | **93.8%** | 68.8% | 81.2% | 81.2% |
| NO recall | **100%** | 60.0% | 60.0% | 40.0% |
| False-wall rate | **0.0%** | 40.0% | 40.0% | 60.0% |
| TP / TN / FP / FN | 10/5/0/1 | 8/3/2/3 | 10/3/2/1 | 11/2/3/0 |
| Valid JSON | 16/16 | 16/16 | 16/16 | 16/16 |

**The same model, prompt, dataset and settings produced NO-recall of 100%, 60%,
60% and 40% on four runs.** Phase 1f run 1 got every negative right and would
have passed every gate; run 2, minutes later, got 40% of them wrong.

This variance — not the mean — is the most important measurement in the phase.

---

## Pooled metrics (4 runs, 64 observations)

| Subset | n | TP | TN | FP | FN | Accuracy | NO recall (95% CI) | False-wall (95% CI) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| All cases | 64 | 39 | 13 | 7 | 5 | 81.2% | 65.0% [43.3, 81.9] | 35.0% [18.1, 56.7] |
| Negatives only | 20 | — | 13 | 7 | — | 65.0% | 65.0% [43.3, 81.9] | 35.0% [18.1, 56.7] |
| **Category A** | 8 | — | **8** | **0** | — | **100%** | **100% [67.6, 100]** | **0.0% [0.0, 32.4]** |
| **Category B** | 12 | — | 5 | **7** | — | **41.7%** | 41.7% [19.3, 68.0] | **58.3% [32.0, 80.7]** |

Intervals are Wilson (the normal approximation runs outside 0–100 at this n).

---

## Per-case confusion analysis (§7)

Four answers per case, in order `1f_run1, 1f_run2, 1e_run1, 1e_run2`.

| Object | Cat | Answers | Stable | Wall behind? | Wall-backed mass immediately behind? | Touching wall? | Occlusion |
|---|:--|:--|:--|:--|:--|:--|---|
| `living_room_a.ottoman.0` | A | F F F F | **yes** | yes | **no** | no | none |
| `living_room_b.coffee_table.0` | A | F F F F | **yes** | yes | **no** | no | none |
| `kitchen.bar_stool.0` | B | F F **T T** | no | yes | **yes** | no | counter occludes base |
| `kitchen.bar_stool.1` | B | F **T** F **T** | no | yes | **yes** | no | counter occludes base |
| `kitchen.bar_stool.2` | B | F **T T T** | no | yes | **yes** | no | counter occludes base |

Positives also flip: `master_bedroom.bed.0` (T F T T), `master_bedroom.bedside_table.1`
(T F T T), `living_room_b.sofa.0` (F F F T). **6 of 16 cases are unstable across
runs — 62.5% stability overall.**

Note that a wall exists behind *every* negative, including both Category A cases.
The field that separates A from B is whether a **wall-backed mass sits immediately
behind the object and overlaps it in the image**.

---

## A correction to the Phase 1e report

Phase 1e's report said of the bar stools: *"This is not noise; it is a capability
boundary… 7B is reliably right on the two large pieces standing in open floor and
reliably wrong on the bar stools."*

**The second half of that was wrong.** With two runs the bar stools looked
consistently wrong. With four they flip — `F F T T`, `F T F T`, `F T T T`. They
are not reliably wrong; they are unstable. The first half holds: the two Category
A pieces are 8 for 8 across every run.

That matters for the mechanism. If the model were simply answering "is there a
wall behind this?", it would answer `true` on the bar stools *consistently*.
It does not. It sits near its decision boundary on them and falls either way.

The Phase 1e report is left unmodified, as instructed; this is the correction of
record.

---

## Comparison to Phase 1e

| Metric | Phase 1e 7B (2 runs) | Phase 1f 7B (2 runs) | Pooled (4 runs) |
|---|--:|--:|--:|
| Negative count | 5 | 5 | 5 |
| TP / TN / FP / FN | 21/5/5/1 | 18/8/2/4 | 39/13/7/5 |
| Accuracy | 81.2% | 81.2% | 81.2% |
| Precision | 80.8% | 90.0% | 84.8% |
| Recall | 95.5% | 81.8% | 88.6% |
| F1 | 87.5 | 85.7 | 86.7 |
| **NO recall** | 50.0% | **80.0%** | **65.0%** |
| **False-wall rate** | 50.0% | **20.0%** | **35.0%** |
| Run agreement | 87.5% | 75.0% | 62.5% stable across all 4 |
| Median latency | 0.94 s | 0.91 s | 0.93 s |
| p95 latency | 4.45 s | 4.40 s | — |

| | Category A | Category B |
|---|--:|--:|
| Phase 1e false-wall | 0% (0/4) | 83.3% (5/6) |
| Phase 1f false-wall | 0% (0/4) | 33.3% (2/6) |
| **Pooled false-wall** | **0% (0/8)** | **58.3% (7/12)** |

Category A is 0% in both phases. Category B swings from 83.3% to 33.3% between
phases — the same instability seen at case level.

---

## Performance

| | value |
|---|--:|
| Model load | 17.0 s |
| Cold first query | 22.3 s |
| Median | 0.91 s |
| p95 | 4.40 s |
| Worst | 22.3 s |
| Projected room latency (wall only, 3.2 queries/room) | ~2.9 s |
| Valid JSON | **32/32 (100%)**, zero failures |

Latency and reliability are not the problem and never have been. Memory is:
2.70 GB spilled to CPU, system RAM at 95% after load.

---

## Decision gates

| Gate | Threshold | Pooled measured | |
|---|---|--:|:--|
| NO recall | ≥70% | 65.0% | ✗ |
| False-wall rate | ≤20% | 35.0% | ✗ |
| Accuracy | ≥75% | 81.2% | ✓ |
| Run-to-run stability | "reasonable" | 62.5% of cases stable; NO-recall spanned 40–100% | ✗ |

Not FAIL (that needs NO recall <50% **and** false-wall >40%; 65.0% is not <50%).

---

## Does the evidence support "Qwen is primarily confusing wall-backed context with the queried object's own wall contact"?

**Partially. It is the best-supported explanation available, and it is not
established.**

For it:

* Category A false-wall is **0% over 8 observations**, Category B **58.3% over
  12** — every false wall in the entire pooled set is a Category B case.
* Both Category A objects are perfectly stable across all four runs; all three
  Category B objects are unstable.
* A wall is visible behind every negative, so "a wall is present" alone does not
  predict the error; "a wall-backed mass immediately behind and overlapping"
  does.

Against it, and these are not small:

* **2 distinct objects in Category A and 3 in Category B.** The categories are
  each essentially one scene — Category A is two living rooms, Category B is three
  stools at one counter in one kitchen. Any per-scene quirk is perfectly
  confounded with the category.
* The 95% intervals **touch**: A [0.0, 32.4] against B [32.0, 80.7]. At 95%
  confidence this is not a clean separation.
* The mechanism does not fit cleanly. A model answering "is there a wall behind
  this?" would say `true` on the stools every time. It flips instead, which looks
  more like low confidence near a boundary than a systematically substituted
  question.
* Three **positives** also flip, which no context-confusion account explains.

So: the A/B contrast is real in the data and worth pursuing, but with two scenes
and five objects it cannot carry the weight of a design decision.

---

## DECISION:
**PARTIAL PASS**

## FAILURE MODE:
**CONTEXT CONFUSION** — Category A 0% false-wall, Category B 58.3%; every false
wall in the pooled set is a Category B case. Classified on point estimates; the
confidence intervals touch and the categories are confounded with scene, so treat
this as the leading hypothesis rather than a finding.

## PRIMARY FINDING:
Across four identical runs the 7B wall gate scored NO-recall of 100%, 60%, 60%
and 40% on the same five objects — the classifier is not stable enough for its
mean to be the interesting number, and every error it made was on an object with
a wall-backed mass directly behind it.

## PRODUCTION INTEGRATION:
**NO.** Nothing was integrated. Independently of accuracy, §10 stands: 7B
requires 2.70 GB of CPU spill on this 6 GB card and cannot coexist with Blender.

## NEXT EXPERIMENT:
**Acquire room imagery with free-standing furniture, from a source beyond this
project's 11 renders, and build a negative set of ≥25 objects spanning at least
8 distinct scenes — with Category A and Category B balanced and never confounded
with scene.**

This is a data-acquisition task, not a model task, and it is the single thing
blocking every downstream decision: the geometric-wall-detector question, the
7B-vs-3B question and the integration question all reduce to a false-wall rate
that currently carries a 38-point-wide interval. The cheapest in-domain route is
the project's own moodboard generator — it already produces renders of this kind,
and prompting it for rooms with islands, mid-floor seating groups, and chairs
pulled away from wall-backed desks and counters would yield both categories
deliberately rather than by luck. Budget the annotation, not the GPU: the
benchmark itself costs about ten minutes.

**Do not run 14B/32B, and do not start the geometric pipeline, until that
measurement exists.**

**STOP.**

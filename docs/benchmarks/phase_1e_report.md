# Phase 1e — qwen2.5vl:7b wall-gate benchmark

**Date:** 2026-09-15 · **Queries:** 64 (2 models × 2 runs × 16 cases)
**Raw data:** `phase_1e_raw.json` · **Script:** `aether-backend/research/phase1e_qwen7b_wall.py`
**Ground truth:** `aether-backend/tests/fixtures/relationship_benchmark.json` (wall rows, identical to Phase 1d)

**Decision: PARTIAL PASS** — on the gate boundary, not clear of it. No production
code changed.

---

## Environment

| | |
|---|---|
| GPU | NVIDIA RTX 3050 6GB Laptop, 6144 MiB, driver 592.82 |
| System RAM | 16.8 GB — **0.1 GB available (99% load) before the 7B load** |
| Blender | not running (checked; 7B cannot be co-resident) |
| Temperature | 0.2 (unchanged) · `num_ctx`, `num_predict`, image px — unchanged |
| Prompt | Phase 1d `_wall_a`, **imported** from the 1d module, not copied |
| Schema | `{"answer": boolean}`, unchanged |

| Model | Quantisation | Total | VRAM | CPU | On GPU | Load |
|---|---|--:|--:|--:|--:|--:|
| `qwen2.5vl:3b` | Q4_K_M | 2.90 GB | 2.90 GB | 0.00 GB | **100%** | 9.4 s |
| `qwen2.5vl:7b` | Q4_K_M | 6.17 GB | 3.47 GB | **2.70 GB** | **56.3%** | 15.9 s |

**The 7B model does not fit.** Ollama silently placed 43.7% of it in system RAM,
which then sat at 93% load with 1.1 GB free. It ran, and it did not destabilise
the machine, but it ran with no headroom and cannot share this GPU with a render.

Exactly one variable changed between arms: `provider.model`. The prompt is the
same Python function object in both — verified, not assumed — so this cannot be a
prompt experiment wearing a model experiment's name.

---

## Dataset

Identical to Phase 1d. No case added, removed, or re-annotated.

| | count |
|---|---|
| Positives (against a wall) | 11 |
| Negatives (open floor) | 5 |
| **Total** | **16** |

Each model ran the full 16 twice, so 32 observations per model and **10 negative
observations per model**.

---

## 3B vs 7B

Pooled over both runs (n = 32 per model). 3B figures are **measured here**, not
quoted — the model was re-run in the same session so both arms have identical
sample sizes.

| Metric | qwen2.5vl:3b | qwen2.5vl:7b |
|---|--:|--:|
| TP | 22 | 21 |
| **TN** | **0** | **5** |
| FP | 10 | 5 |
| FN | 0 | 1 |
| Accuracy | 68.8% | **81.2%** |
| Precision | 68.8% | **80.8%** |
| Recall | 100% | 95.5% |
| F1 | 81.5 | **87.5** |
| **NO recall** | **0.0%** | **50.0%** |
| **False wall rate** | **100%** | **50.0%** |
| Run-to-run agreement | 100% | 87.5% |
| Median latency | 0.23 s | 0.94 s |
| p95 latency | 2.49 s | 4.45 s |
| VRAM | 2.90 GB | 3.47 GB (+2.70 GB CPU) |
| CPU fallback | none | **43.7% of weights** |

### A correction to the table in the brief

The brief's 3B column listed TP 16, precision 76.2%, F1 86.5%. Those conflate
"16 YES answers" with true positives. The measured Phase 1d values — confirmed
again here — are **TP 11, TN 0, FP 5, FN 0 per run; precision 68.8%, F1 81.5**.
Accuracy 68.8%, recall 100% and NO-recall 0% in the brief were correct. Using
the measured values, as instructed.

### The 3B result reproduced exactly

Both 3B runs returned `true` on all 16 cases — 100% run agreement, and
byte-identical to the Phase 1d figures stored in `phase_1d_raw.json`. Phase 1d's
constant function was not a bad draw.

---

## Per-run detail — not averaged away

| | Run 1 | Run 2 | Pooled |
|---|--:|--:|--:|
| 7B accuracy | 81.2% | 81.2% | 81.2% |
| **7B NO recall** | **60.0%** | **40.0%** | **50.0%** |
| **7B false wall** | **40.0%** | **60.0%** | **50.0%** |
| 7B `false` answers | 4 / 16 | 2 / 16 | 6 / 32 |
| 3B NO recall | 0.0% | 0.0% | 0.0% |

The two 7B runs straddle the gate. **Run 1 alone classifies PARTIAL PASS; run 2
alone classifies FAIL.** Only the pooled figure lands on PARTIAL PASS, and it
lands exactly on the threshold — 5 of 10, where the rule is "≥50%". One answer
different in either direction and the classification changes. Running twice was
the right instruction.

---

## What 7B actually learned — the most useful result here

Per-case behaviour on the five open-floor pieces, both runs, both models:

| Piece | 7B run 1 | 7B run 2 | 3B run 1 | 3B run 2 |
|---|:--|:--|:--|:--|
| ottoman, mid-room between two sofas | **false ✓** | **false ✓** | true ✗ | true ✗ |
| coffee table, mid-rug | **false ✓** | **false ✓** | true ✗ | true ✗ |
| bar stool 0 | true ✗ | true ✗ | true ✗ | true ✗ |
| bar stool 1 | false ✓ | true ✗ | true ✗ | true ✗ |
| bar stool 2 | true ✗ | true ✗ | true ✗ | true ✗ |

**This is not noise; it is a capability boundary.** 7B is reliably right on the
two large pieces standing in open floor and reliably wrong on the bar stools —
and the bar-stool error is explicable rather than random: all three are pulled up
to a counter run that *is* against a wall, so in the image they sit against a
large wall-adjacent mass. The model is answering a slightly different question
("is there a wall behind this?") that happens to be true for them.

3B does not show the pattern because 3B has no pattern — it says `true` to
everything.

---

## Performance

| | 3B | 7B |
|---|--:|--:|
| Model load | 9.4 s | 15.9 s |
| First query (cold vision tower) | 10.3 s | **23.4 s** |
| Median query | 0.23 s | 0.94 s |
| p95 | 2.49 s | 4.45 s |
| Worst | 10.3 s | 23.4 s |
| Wall queries per room | 3.2 | 3.2 |
| **Projected room latency (wall only)** | **0.7 s** | **3.0 s** |

Plus a one-time ~39 s cost on 7B (load + cold first query) per model swap. The
worst case is the first query, not the steady state.

Latency is not the constraint — 3.0 s/room against a 60 s budget is 20× headroom
even at 4× the per-query cost. **Memory is the constraint**: 43.7% CPU spill, and
no possibility of holding 7B and a Blender render on the same card.

---

## Decision: **PARTIAL PASS**

| Gate | Threshold | Measured | |
|---|---|--:|:--|
| NO recall | ≥70% | 50.0% | ✗ |
| False wall rate | ≤20% | 50.0% | ✗ |
| Accuracy | ≥75% | 81.2% | ✓ |
| **PASS** | all three | | **no** |
| **PARTIAL PASS** | NO recall ≥50% **or** false wall ≤40% | NO recall = 50.0% | **yes, exactly at the line** |
| FAIL | NO recall <50% **and** false wall >40% | 50.0% is not <50% | no |

Per §12 and §14: **7B improves the capability but is not production-ready, and
nothing is integrated.**

---

## Interpretation

> **Did increasing from 3B to 7B materially improve wall discrimination?**

**Yes — materially, and not nearly enough.**

The material part is real and should not be understated. Across 32 observations
the 3B model produced **TN = 0**: it never once said a piece was not against a
wall, in this phase or the last. The 7B model produced **TN = 5**, correctly
identified two specific pieces in both runs, and lifted accuracy 68.8% → 81.2%,
precision 68.8% → 80.8%, false-wall 100% → 50%. A capability that did not exist
at 3B exists at 7B.

The "not enough" part is equally real. It still gets half the open-floor pieces
wrong, it disagrees with itself on 12.5% of cases, it introduced a false negative
3B never made, and it needs 43.7% CPU spill on this hardware. Half the negatives
wrong means half the furniture that should stand free would be pushed to a wall.

---

## Recommendation — exactly one, not started

**Expand the negative set to ≥25 open-floor pieces and re-run 7B twice with the
frozen prompt.**

Not another model, and not the geometric pipeline yet — because **this dataset
cannot resolve the gate it is being measured against.** With 5 negatives the
false-wall rate can only take the values 0, 20, 40, 60, 80 or 100%. A gate of
"≤20%" is one observation wide. The measured 50% (5 of 10) carries a 95%
confidence interval of roughly **24%–76%** — which spans "clearly unusable" and
"nearly good enough" without distinguishing them. Deciding to build a geometric
wall detector, or to integrate 7B, on a ±26-point interval would be spending real
work on a number that has not been measured yet.

The expansion also tests a specific hypothesis this run produced, rather than
just adding rows: **7B appears to answer "is there a wall behind this?" instead
of "is this against a wall?"** — right on the mid-room ottoman and coffee table,
wrong on all three bar stools standing in front of a wall-backed counter. A
larger negative set should contain both kinds deliberately: pieces in genuinely
open floor, and pieces standing free but with a wall behind them. If the second
group is where the failures concentrate, the problem is a specific and possibly
addressable confusion rather than general incapacity.

Cost: a few hours of annotation, ~20 minutes of GPU, no new model, no new
architecture.

**If that expanded measurement confirms false-wall stays above ~40%**, the §15
route is the right one — geometric wall detection from segmentation and room
boundary rather than a still larger language model. But that is the phase after
this one, and it needs a number worth acting on first.

**Stopping here. Nothing started automatically.**

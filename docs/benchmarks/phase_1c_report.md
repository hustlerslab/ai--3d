# Phase 1c — Narrow relation extraction benchmark

**Model:** `ollama:qwen2.5vl:3b` · **Date:** 2026-09-14 · **Queries:** 78 (26 × 3 variants)
**Raw data:** `phase_1c_raw.json` · **Script:** `aether-backend/research/phase1c_relations.py`
**Ground truth:** `aether-backend/tests/fixtures/relationship_benchmark.json`

**Verdict: FAIL — Scenario B (latency good, accuracy bad).** No production code changed.
No Blender A/B run, because §10 gates it on a pass that did not happen.

---

## The one-sentence result

In 78 narrow, isolated, closed-list questions the model **never once chose a
non-object answer** — `wall`, `window`, `open_room` and `unknown` were in the
schema enum and named in the prompt on every single query, and it returned a
piece of furniture 78 times out of 78, at "high" confidence on 56 of them.

That is not a failure to see. It is a failure to decline.

---

## 1. Dataset quality

Hand-annotated from the five renders before any model was run.

| | count |
|---|---|
| Rooms / objects | 5 / 36 |
| Annotated relationships | 26 |
| **TRUE** (scoreable) | **24** |
| **FALSE** | **0** |
| **UNKNOWN** (excluded from accuracy) | **2** |
| Eligible after vocab filtering | 26 / 26 — none skipped |

FACES 7 · AGAINST 8 (+2 UNKNOWN) · SUPPORTED_BY 9.

Three of the 24 are **negative controls** whose correct answer names no object:
the bed faces `open_room` (nothing stands opposite it), the hanging plant is
supported by `unknown` (it hangs on a wall), and the freestanding island was
marked UNKNOWN rather than forced, because its far end leaves the frame.

No FALSE rows exist because every query was written by looking at the render
first and asking what is actually there. Inventing false relations would have
measured nothing real.

**Known limitation:** 24 scoreable examples is a small sample. A 4-percentage-point
difference between variants here is one query, and should not be read as a
difference at all. The gaps that matter below are 30+ points.

---

## 2. Variant comparison

| | A — full image | B — crop | C — crop + context |
|---|---|---|---|
| Accuracy (strict) | **29.2%** | 29.2% | 25.0% |
| Accuracy (lenient) | **33.3%** | 29.2% | 29.2% |
| Hallucination | **66.7%** | 70.8% | 70.8% |
| JSON success | 100% | 100% | 100% |
| Off-list answers | 0 | 0 | 0 |
| Abstentions | **0** | **0** | **0** |
| Median latency | **0.78 s** | 2.79 s | 3.00 s |
| Useful relations | 4 | 3 | 4 |

**The variants do not separate.** The pre-registered expectation was that C would
win — the crop says *which* piece, the full image says *what it relates to*. It
did not: C is the slowest and no more accurate, and every variant fails the same
way for the same reason. Isolation was not the missing ingredient.

Variant A's 0.78 s median is partly Ollama's KV cache: consecutive queries share
one image, so only the first query in a room pays full price (worst 3.33 s).
Production would batch a room's queries the same way, so this is a fair number.

---

## 3. Relation accuracy — reported separately, never merged

| Relation | n | A strict | B strict | C strict | Best lenient |
|---|--:|--:|--:|--:|--:|
| FACES | 7 | 28.6% | 28.6% | 28.6% | 42.9% (A, C) |
| **AGAINST** | 8 | **0.0%** | **0.0%** | **0.0%** | **0.0%** |
| SUPPORTED_BY | 9 | 55.6% | 55.6% | 44.4% | 55.6% (A, B) |

**AGAINST is 0 for 30 queries across all three variants.** In every one of those
30 the correct answer was `wall`, and in every one of those 30 the model named a
piece of furniture instead. It is not that the model is bad at walls — it never
attempted a wall.

SUPPORTED_BY at 55.6% is the strongest result and the only one in sight of a
gate. FACES is the most interesting: it got `sofa → television` right in the
room where a television exists, and got all three bar stools wrong by pointing
them at each other rather than at the island they are pulled up to.

---

## 4. Hallucination rate

| | A | B | C |
|---|--:|--:|--:|
| Hallucinated target selections | 66.7% | 70.8% | 70.8% |
| Negative controls answered correctly | 0 / 2 | 0 / 2 | 0 / 2 |
| Answers outside the candidate list | **0** | **0** | **0** |

Two definitions, kept apart:

* **Off-list answers: zero, by construction.** The JSON Schema `enum` made an
  invented id unrepresentable. This part of the candidate-ID contract works
  perfectly and is worth keeping whatever happens next — the fuzzy-matching,
  duplicate-label and invented-furniture problems are simply gone.
* **Hallucinated relations: 66.7–70.8%.** The model named a real object where
  the truth was a different object or no object at all. This is the number that
  matters for Blender: a sofa rotated toward the wrong piece is as broken as a
  sofa rotated toward something imaginary.

The negative controls are the sharpest evidence. Asked what supports foliage
hanging on a wall, the model answered `master_bedroom.bed.0`. Asked what a
bathroom vanity is against — offered exactly four choices, `mirror`, `wall`,
`window`, `unknown`, with the instruction "answer wall if its back is flat
against a wall" — it answered `mirror`.

---

## 5. JSON and repetition reliability

| | result |
|---|---|
| Successful structured responses | **78 / 78 (100%)** |
| JSON failures | 0 |
| Truncated responses | 0 |
| Generation-guard triggers | 0 |
| Repetition detected | 0 |
| `GenerationStatus` | `complete` × 78 |

**The narrow-query hypothesis is fully confirmed on reliability.** Against the
Phase 0e/1b baseline for the bulk read — 1 read in 3 looping to the token cap,
187–191 s spent generating repeats, recovery only through salvage — the narrow
form produced 78 clean first-attempt answers with the guard never firing.

Asking one small question at a time fixes the generation pathology completely.
It just does not fix the answer.

---

## 6. Latency

| | A | B | C |
|---|--:|--:|--:|
| Mean | 1.17 s | 2.33 s | 2.70 s |
| Median | 0.78 s | 2.79 s | 3.00 s |
| p95 | 2.87 s | 2.92 s | 3.18 s |
| Worst | 3.33 s | 3.14 s | 3.22 s |

Per relation (median): FACES 2.79–3.04 s · AGAINST 0.80–2.96 s · SUPPORTED_BY
0.72–3.00 s. The sub-second cases are KV-cache hits within a room.

**Projected room cost** = queries per room × median query time:

| Variant | Queries/room | Projected room latency | Gate (≤60 s) |
|---|--:|--:|:--|
| A | 5.2 | **4.1 s** | PASS (15×) |
| B | 5.2 | 14.5 s | PASS (4×) |
| C | 5.2 | 15.6 s | PASS (4×) |

This was the risk flagged before the run — that latency would fail before
accuracy got a chance. It did not. There is 4–15× headroom, which is the one
result that makes a more expensive architecture affordable.

---

## 7. Query budget comparison

B and C are subsets of the queries A already ran, so they cost no extra GPU time
and are compared on identical model behaviour.

| Budget | Queries/room | Accuracy (variant A) | Useful relations | Est. room latency |
|---|--:|--:|--:|--:|
| A — every eligible object | 5.2 | 33.3% | 4 | 4.1 s |
| B — major anchors only | 2.8 | 25.0% | 3 | 2.4 s |
| C — only where the default is wrong | 2.0 | **50.0%** | **4** | **1.6 s** |

Budget C looks best and the expectation that it would be the production
architecture is directionally supported — it keeps every useful relation at 38%
of the queries. **But this number is not shippable.** Budget C is selected using
the ground truth (it asks only where the free default is known to be wrong), so
50% is an upper bound on what a real pre-filter could reach, not a measured
result. Reported as the ceiling it is, not as a finding.

---

## 8. Architectural value

"Useful" = acting on this answer changes a placement the system would not
already have made for free. The free defaults were read out of the compiler, not
assumed: `_floor_candidates` falls through to `_wall_aligned_candidates` for
every floor piece — which both backs it onto a wall *and* turns it into the room
— and `_pick_support` already ranks hosts by `SUPPORT_PREFERENCE`.

| Relation | Correct (best variant) | Can affect placement | % of correct that is useful |
|---|--:|--:|--:|
| FACES | 3 | **3** | 100% |
| AGAINST | 0 | 0 | — |
| SUPPORTED_BY | 5 | 1 | 20% |
| **Total** | **8 / 24** | **4** | **50%** |

Two things this table says that raw accuracy hides:

* **Every correct FACES answer is worth having.** The compiler has no orientation
  prior beyond "turn into the room", so each of the three is a rotation it could
  not have found.
* **Most correct SUPPORTED_BY answers are worth nothing.** `pillows → sofa` and
  `vase → coffee table` are exactly what `SUPPORT_PREFERENCE` already picks. The
  single useful one is `plant → kitchen counter`, which moves a plant off the
  floor and onto a worktop.

So the best variant produces **4 useful relations across 5 rooms** — 0.8 per
room — for 26 queries. And it produces 16 wrong ones alongside them, with no
signal to tell them apart: the model reported "high" confidence on 56 of 78
answers, including most of the wrong ones, so its own confidence field cannot
be used as a filter.

---

## 9. Production gate

| Gate | Threshold | Best measured | Result |
|---|---|---|:--|
| A — accuracy | ≥70% (≥80% supported_by) | 55.6% supported_by · 42.9% faces · **0% against** | **FAIL** |
| B — hallucination | ≤10% | 66.7% | **FAIL** |
| C — JSON reliability | ≥95% | **100%** | **PASS** |
| D — latency | ≤60 s/room | **4.1 s** | **PASS** |

**Overall: FAIL.** No variant passes. Nothing goes to production, no schema
value is added, no provider method is written.

**Scenario B — latency good, accuracy bad.**

---

## 10. Blender A/B validation

**Not run.** §10 gates it on a variant passing all four gates. Two failed. A
side-by-side render would show a difference, but it would be a difference made
out of 66% wrong relations, and presenting that as validation would be
dishonest.

---

## 11. Recommended next experiment — exactly one

The pre-registered response to Scenario B is "benchmark qwen2.5vl:7b". **The
measurement argues against that being the first thing to try**, and the argument
is worth putting on the record before the decision is made:

* The model is **not failing to see**. It found `sofa → television` in the room
  that has one, `vase → coffee table`, `plant → kitchen counter`. Its perception
  produced 8 correct answers out of 24.
* It is failing to **decline**. 78 of 78 answers named an object when four
  non-object answers were on offer every time. A refusal-to-abstain bias is a
  well-documented small-VLM behaviour, and capacity is not obviously the lever —
  a 7B model that is also unwilling to say "wall" scores 0% on AGAINST too.
* Cost is real: `qwen2.5vl:7b` at Q4 is ~6 GB against a 6 GB card that Blender
  also uses. That is a contention problem, not just a slower model.

**The single experiment I recommend instead: decompose each relation into a
binary question that has no abstention to refuse.**

Rather than "which candidate is this against?", ask "is this piece's back flat
against a wall — yes or no?", and only on `no` ask which piece it touches. Same
for supports: "is this object resting on another piece of furniture — yes or
no?" before "which one".

Why this and not another prompt revision — this is a **schema and control-flow**
change, not wording. It removes the failing act (choosing a null option from a
list of objects) rather than asking more politely for it. And the two results
that passed make it affordable: 100% JSON reliability means a two-step chain
does not compound failure, and 4–15× latency headroom means a room can afford
two questions where one was budgeted.

It also targets where all the value is. AGAINST is 0-for-30 and is the signal
that picks which wall a piece goes on — the single most valuable thing the
compiler could be told.

If binary decomposition also fails to move AGAINST off zero, then the failure is
capacity after all, and `qwen2.5vl:7b` becomes the right next step with the
question properly narrowed to it.

**Stopping here for a decision. Nothing further will be started automatically.**

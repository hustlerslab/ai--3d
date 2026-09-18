# Phase 1d — Binary spatial relation benchmark

**Model:** `ollama:qwen2.5vl:3b` · **Date:** 2026-09-15 · **Queries:** 136 (82 pilot + 54 benchmark)
**Raw data:** `phase_1d_raw.json` · **Script:** `aether-backend/research/phase1d_binary_relations.py`
**Ground truth:** `aether-backend/tests/fixtures/relationship_benchmark.json` (`binary_relations`)

**Verdict: FAIL — RESULT D.** No production code changed. No Blender run.

---

## The one-sentence result

Decomposition worked where it was cheap and failed where it mattered: the
orientation gate produced this model's **first non-zero abstention in two
phases** (66.7% NO-recall, 2 of 3 "this piece has no front" cases correctly
declined), while the wall gate — the single most valuable signal for Blender —
answered **`true` 16 times out of 16**, a constant function.

---

## 0. Dataset — additive, nothing replaced

Phase 1C annotations were **carried through byte-identical**, verified by diff
against a copy taken before the edit:

| | old | new | reason |
|---|---|---|---|
| `relations` entries | 26 | 26 | unchanged — no annotation altered, reordered or removed |
| `objects` | 36 | 36 | unchanged |
| `binary_relations` | — | **37 added** | new key; the yes/no decomposition of the same relations |

**No annotation changed value.** The one candidate for a change — the kitchen's
hob counter, UNKNOWN in 1C — was re-examined against the render and **kept
UNKNOWN**: it reads as a run against the back wall with a breakfast-bar
overhang rather than a free-standing island, so converting it into a NO control
would have been a convenient annotation, not an honest one.

| | count |
|---|---|
| Binary chains | 37 |
| Scoreable | **35** |
| UNKNOWN (excluded) | 2 |
| **Negative controls** | **10** (brief required ≥5) |

Negative controls by step: wall 5 · orientation_visible 3 · faces_object 1 ·
supported 1. Every true target survived candidate filtering — checked before the
run, because a filter that drops the answer looks exactly like a model failure.

---

## 1. Prompt pilot — A vs B, then frozen

Two wordings per question, 10 examples each, NO-cases loaded in first so the
pilot could not be won by whichever wording says yes more.

| Question | A (plain) | B (names the negative case) | Chosen |
|---|--:|--:|:--|
| wall | **70.0%** (NO-rec 40.0%) | 50.0% (NO-rec 0.0%) | A |
| adjacent | **100.0%** | 80.0% | A |
| orientation | 50.0% (NO-rec **100.0%**) | 50.0% (NO-rec 0.0%) | A |
| faces_object | **85.7%** | 28.6% | A |
| supported | 88.9% | 88.9% | A |

**My hypothesis for prompt B was wrong, and worth recording.** B spelled out the
negative world-state before asking ("furniture is placed in one of two ways, and
both are common…"), on the theory that 1C's model never considered "not against a
wall" to be available. It made things **worse everywhere** — most sharply on
`faces_object`, 85.7% → 28.6%. Naming the alternative appears to have pushed this
model toward it indiscriminately rather than toward discrimination. A was frozen
for all five questions; no C or D was written.

---

## 2. Binary decision accuracy

| Stage | n | yes/no | TP | TN | FP | FN | Accuracy | F1 | NO-precision | NO-recall |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **wall** | 16 | 11/5 | 11 | **0** | 5 | 0 | 68.8% | 81.5 | — | **0.0%** |
| **orientation** | 10 | 7/3 | 4 | **2** | 1 | 3 | 60.0% | 66.6 | 40.0% | **66.7%** |
| faces_object | 4 | 4/0 | 4 | 0 | 0 | 0 | 100.0% | 100.0 | — | n/a |
| supported | 9 | 8/1 | 8 | **0** | 1 | 0 | 88.9% | 94.1 | — | **0.0%** |

Read the TN column, not the accuracy column. `wall` at 68.8% and `supported` at
88.9% look respectable and are worthless: both scored entirely by saying yes to
a dataset that is mostly yes. **TN = 0 means the gate never once declined.**
`faces_object` at 100% is n=4 with no negative cases reaching it at all — the
one negative (the bed) never got there, because the orientation gate wrongly
closed its chain first.

Only `orientation` has a real TN count, and it is the one genuine advance in
this phase.

### The pilot/benchmark discrepancy on `wall` — reported, not buried

The pilot measured **NO-recall 40%** (TN=2, FP=3) on the same five negative
cases, with the same frozen prompt A. The benchmark measured **0%** (TN=0,
FP=5). Same wording, same images, same schema, temperature 0.2.

That is run-to-run nondeterminism on n=5, and it means the honest statement is
not "the wall gate never declines" but **"the wall gate declines somewhere
between 0% and 40% of the time, measured 2/10 across both runs, and returned a
constant `true` in the definitive run."** Either figure fails the gate by a wide
margin. The headline number quoted below is the benchmark's, not the pilot's.

---

## 3. AGAINST_WALL — the main metric

| | result |
|---|---|
| Accuracy | **68.8%** (gate: ≥75%) |
| Wall present → correctly YES | 11 / 11 |
| Wall absent → correctly NO | **0 / 5** |
| False wall detections | **5 / 5 negatives (100%)** (gate: ≤15%) |
| Missed walls | 0 |
| Answer distribution | `{true: 16}` |

The five false walls are the ottoman standing between two sofas, the three bar
stools on open floor, and the coffee table mid-rug. Each is unambiguously in the
open, and each was called "against a wall".

**FAIL on both halves of the gate.**

---

## 4. FACES

| Step | result |
|---|---|
| Orientation detectable (Step A) | 60.0% accuracy, NO-recall **66.7%** |
| Faces an object (Step B) | 100% (n=4, no negatives reached it) |
| Target accuracy (Step C) | **20.0%** (1 of 5) |
| **End-to-end** | **30.0%** (gate: ≥65%) |

The orientation gate cuts both ways. It correctly declined on the side table and
the coffee table — pieces with no front, where a rotation would be meaningless —
which is exactly the behaviour Phase 1C could not produce. But it also declined
on **both living-room sofas and the bed**, three pieces whose fronts are plain,
and each of those false negatives closed a chain that would otherwise have had a
real answer to give.

One end-to-end success is worth naming because it is the whole architecture
working: `living_room_b.sofa.0` → orientation visible → faces an object →
`tv_unit.0`, the television rather than the console beneath it or the coffee
table in front of it.

**FAIL**, but this is the only relation where the model beats the rules.

---

## 5. SUPPORTED_BY

| | result |
|---|---|
| Binary gate (Step A) | 88.9% accuracy, NO-recall **0.0%** |
| Target accuracy (Step B) | **33.3%** (3 of 9) |
| **End-to-end** | **33.3%** (gate: ≥80%) |
| Value beyond `SUPPORT_PREFERENCE` | **negative — 0 better, 5 worse** |

The single negative control — foliage hanging on a wall — was called "resting on
furniture" and assigned to a bedside table (Type D). And with the gate open, the
target step put cushions on the coffee table and a vase on the sofa.

**FAIL, decisively, and this one is settled**: §6 asked whether Qwen adds
anything beyond the deterministic vocabulary here, and the answer is that it
actively subtracts.

---

## 6. Hallucination taxonomy

| Type | meaning | count |
|---|---|--:|
| **A** | claims a wall where there is none | **5** |
| B | claims an object relationship where none exists | **0** |
| **C** | wrong target after a correctly-opened gate | **8** |
| **D** | incorrect physical support | **1** |

Type B is zero only because so few negatives reached those gates — with n=1 for
`faces_object` negatives and the bed's chain closed early, it is an untested
cell, not a clean one. Types A and C carry the damage: A puts furniture on the
wrong wall, C rotates or stacks it onto the wrong neighbour.

---

## 7. Deterministic vs AI — the mandatory table

Deterministic answers are read out of the existing engine, not guessed:
`_floor_candidates` falls through to `_wall_aligned_candidates` for every floor
piece (so the rules always say "against a wall" and always turn it into the
room), and `_pick_support` ranks hosts by `SUPPORT_PREFERENCE`.

| Relation | Deterministic correct | Qwen end-to-end | Qwen adds value | Qwen worse |
|---|--:|--:|--:|--:|
| AGAINST_WALL | 11 / 16 (68.8%) | 11 / 16 (**68.8%**) | **0** | **0** |
| FACES | 1 / 10 (10.0%) | 3 / 10 (**30.0%**) | **3** | 1 |
| SUPPORTED_BY | 8 / 9 (88.9%) | 3 / 9 (**33.3%**) | **0** | **5** |
| **Total** | **20 / 35 (57.1%)** | **17 / 35 (48.6%)** | **3** | **6** |

**Across the whole benchmark the binary chain is worse than the rules it would
replace — 48.6% against 57.1%, with twice as many regressions as improvements.**

* **AGAINST_WALL: identical, and identical for a reason.** The model always says
  "wall"; the rule always says "wall". Two different systems producing the same
  constant. There is nothing to integrate.
* **FACES: the only net gain, +2.** The rules have no orientation prior at all,
  so anything correct is new. Both wins came from *declining* — correctly saying
  a side table and a coffee table have no front — plus the one sofa→television.
* **SUPPORTED_BY: a clear regression.** Five placements the vocabulary already
  had right, the model moved to the wrong host.

---

## 8. Query cost

| | value |
|---|--:|
| Queries per room | 10.8 |
| Seconds per room | **3.3 s** |
| Worst room | **5.3 s** |
| Binary query median / p95 | 0.23 s / 0.33 s |
| Target query median / p95 | 0.46 s / 0.50 s |

Well inside the 60 s gate — 11× headroom even on the worst room. These figures
benefit from Ollama's KV cache: a room's queries share one image, so only the
first pays full price. Production would batch identically, so the number is fair,
but it is a per-room figure and should not be read as a cold single-query cost.

### Budget strategies

| Strategy | Chains | Queries/room | End-to-end | AI better than rules | s/room |
|---|--:|--:|--:|--:|--:|
| A — all eligible | 35 | 10.8 | 48.6% | 3 | 3.3 |
| B — major anchors + supports | 21 | 6.4 | **57.1%** | 1 | 2.1 |
| C — only where the rules are wrong (oracle) | 15 | 5.2 | **20.0%** | 3 | 1.5 |

**Strategy C is the result you were most interested in, and it is the most
damaging one.** Selecting exactly the cases where the deterministic engine is
wrong — the only queries worth spending anything on — the model gets **20%** of
them right. The questions the architecture cannot already answer are precisely
the questions this model cannot answer either. Strategy B scores highest only
because it is filtered toward the easy majority the rules already handle.

---

## 9. Production gate

| Gate | Threshold | Measured | Result |
|---|---|---|:--|
| AGAINST_WALL accuracy | ≥75% | 68.8% | **FAIL** |
| AGAINST_WALL false walls | ≤15% | 100% of negatives | **FAIL** |
| FACES end-to-end | ≥65% | 30.0% | **FAIL** |
| SUPPORTED_BY end-to-end | ≥80% | 33.3% | **FAIL** |
| SUPPORTED_BY value beyond rules | must demonstrate | 0 better / 5 worse | **FAIL** |
| Reliability | ≥95% JSON, 0 silent failures | **100%** (54/54, all `complete`) | **PASS** |
| Latency | ≤60 s/room | **3.3 s** | **PASS** |

**Overall: FAIL.** Nothing integrates. No schema value added, no provider method
written, no Blender run (§19 forbids it even on a pass).

### Decision: **RESULT D — binary decline still fails**

Not RESULT E. Reliability and latency pass outright, the orientation gate
produced genuine abstention for the first time, and FACES beat the rules. But
the capability the phase was built to test — declining where declining is the
right answer — reached 0% on the two gates that carry the volume, and the wall
gate in particular is still a constant.

---

## 10. Exactly one next recommendation — not started

**Benchmark `qwen2.5vl:7b` on the wall gate alone.**

This is the pre-registered RESULT D action and the evidence now supports it,
where in Phase 1C it did not. The argument has changed:

* In 1C I argued against 7B because the failure looked like task formulation,
  not capacity. **That argument has now been tested and spent.** Decomposition
  is the strongest reformulation available — one question, two words of answer,
  no competing object list — and the wall gate still returned a constant.
* The orientation gate proves abstention is not architecturally impossible for
  this model; it managed 66.7% NO-recall on the same run. So the wall failure is
  specific, and capacity is the remaining untested variable.

**Scope it narrowly:** the wall question only, the 16 annotated cases, one
prompt (frozen A), no chain, no target step. That is ~16 queries. It answers one
question — does a larger model decline on walls — for a few minutes of GPU
rather than a full matrix.

Two constraints to decide before running it: `qwen2.5vl:7b` at Q4 is ~6 GB
against a 6 GB card Blender also uses, so it cannot be resident alongside a
render; and the ~11× latency headroom measured here is what makes a slower model
affordable at all.

**And one finding that does not need 7B**, from §7: **SUPPORTED_BY should not use
a model at all.** The deterministic vocabulary scores 88.9% against the chain's
33.3%, and every one of the five regressions was a placement the rules already
had right. Whatever happens with 7B, that relation belongs to the rules.

**Stopping here. Nothing started automatically.**

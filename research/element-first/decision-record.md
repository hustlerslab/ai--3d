# Element-First Architecture — Decision Record

## DECISION: ADOPT WITH MODIFICATIONS

Adopt the **instance-count contract** and the **canonical-element identity** that
element-first is built on. Do **not** adopt the part that has the model invent a
room's inventory from a vague brief, and do **not** remove the moodboard reading.

The evidence below is measured, and two of the measurements contradict the case
for element-first as originally proposed. Both are reported.

---

## 1. What the research actually found

### 1a. The current system CAN count. The claim that it cannot is wrong.

The proposal assumes the pipeline does not know how many of each piece a room
should hold. Measured by calling the shipped `merge_reading_into_plan` on eight
inventories with known ground truth (`inventory_benchmark.py`):

| Route | Correct overall | Correct on repeated elements |
|---|---|---|
| A — design intent (the P11–P15 channel) | 2 of 8 | **0 of 6** |
| B — moodboard reading (what production uses) | **8 of 8** | **6 of 6** |

Route B carries multiplicity correctly, as N separate plan items each with
`count = 1`, which sums to the right number. There is no `count` field, but the
inventory is right.

Route A is the broken one. `merge_intents` groups by `(object_category,
room_hint)`, so a client who photographs two armchairs gets one. That is by
design — P11 introduced it to stop a client's own sofa becoming two sofas — but
it means the typed intent channel cannot express a repeated piece at all.

### 1b. Where the current system really fails: it pays three times for one stool.

`shape_key` is `room | semantic_type | centre rounded to 0.1`. Its own comment
states the goal: *"Three 'black bar stool' boxes in a kitchen are three
placements of one stool; generating each would buy the same mesh three times at
30 credits each."*

The key defeats that goal whenever the stools are actually apart, which is the
normal case for stools along a counter. In this project's real data:

```
kitchen  bar_stool  x3   all named "black bar stool", all check=ok
  el_3cb09794_kitchen_bar_stool_0_5x0_8
  el_3cb09794_kitchen_bar_stool_0_6x0_8
  el_3cb09794_kitchen_bar_stool_0_9x0_8
```

Three centres, three keys, **three Meshy purchases of the same stool — 90
credits where 30 would do.** The dedupe only fires when the boxes overlap.

### 1c. Inventory is silently lost exactly where the codebase says it is.

Running the real `mark_duplicates` and `merge_reading_into_plan` on three bar
stools:

| Read quality | Flagged duplicate | Reaches the plan |
|---|---|---|
| Clean, separated boxes | 0 | 3 of 3 |
| Boxes running to the image edge (the documented failure) | 2 | **1 of 3** |
| Same, after a human approves all three | 2 | 3 of 3 |

Two of three stools vanish before anyone sees them, and the only thing that
recovers them is a human approving elements the UI has labelled "duplicate,
already claimed". Nothing anywhere records that three were expected.

### 1d. Qwen:3B transcribes an inventory well and invents one badly.

`qwen_capability.py`, 8 scenarios × 5 runs = 40 generations, briefs that state
their inventory in words:

| Measure | Value |
|---|---|
| Valid structured JSON | 40 of 40 |
| Element recall | 0.962 |
| Instance-count accuracy | **0.962** |
| Fully correct generations | 36 of 40 |
| Hallucinated elements | 0 |
| Repeatable scenarios | 7 of 8 |
| Invalid relation predicates | 0 of 22 |
| Median latency | 2.8 s |

Then the red-team run, on briefs that do **not** state counts — which is what
real clients write:

| Brief | Distinct inventories over 3 runs |
|---|---|
| "A cozy living room for a family who entertains occasionally." | 2 of 3 |
| "A calm restful primary bedroom in warm neutral tones." | 2 of 3 |
| "A small modern kitchen for a couple." | **3 of 3**, plus one hard failure at the 8192-token cap |

It also invented `kitchen_chandelier`, `kitchen_pantry` and `kitchen_bench`,
none of which are in the vocabulary, and produced both `side_table` and
`nightstand` for the same bedside role.

**This is the finding that decides the architecture.** Element-first asks the
model to own the inventory. A 3B model can be trusted to *transcribe* a stated
inventory and cannot be trusted to *author* one.

---

## 2. Implementation gate

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Improves element identity? | Partly | `element_id` hashes free text plus bbox, so it is not stable across re-reads; a canonical element id would be. A re-read discards approvals (`scene_plan.py:262-267`). |
| 2 | Improves count reliability? | **Yes, for the failure cases** | 1c: 1 of 3 survive a bad read today, with no record of the shortfall. |
| 3 | Reduces duplicate/missing elements? | **Yes for duplicates** | 1b: three purchases of one stool. |
| 4 | Improves asset linkage? | **Yes** | One canonical element, one asset, N placements. |
| 5 | Improves provenance? | Marginally | P11 provenance already reaches the manifest; P16 measured the full chain. |
| 6 | Improves attribute preservation? | **No** | P13–P15 already carry 7 of 7 to the manifest. Element-first adds nothing here. |
| 7 | Improves relationship preservation? | Not measured | The graph exists and never reaches HIGH confidence because `detections` is hard-coded `None`. Unchanged either way. |
| 8 | **Can Qwen:3B produce the scene specification?** | **NO for real briefs** | 1d. Two to three distinct inventories per three runs, one token-cap failure in nine. |
| 9 | Can canonical element images be generated reliably? | **NOT MEASURED** | Would require building the generator first. Deliberately not done. |
| 10 | Can the moodboard be composed from those elements? | **NOT MEASURED** | The current moodboard is one SD render per room, not a composition. Making it compositional is a large new subsystem. |
| 11 | Can Meshy consume those images? | Yes, mechanically | It already consumes crops; a clean element image is strictly easier. |
| 12 | Can the Spatial Engine resolve placement? | **Yes, unchanged** | It already does, from plan items. Instance counts feed it more items, not different ones. |
| 13 | Is the added cost acceptable? | **No, as proposed** | One image generation per canonical element plus a composition stage, on top of the existing SD render. |
| 14 | Testable? | Yes | |
| 15 | Backward compatible? | Yes for counts; **no** for replacing the moodboard | |
| 16 | Materially improves known P11–P15 failures? | **Partly** | It addresses the baseline audit's gaps 35–37 (no count, no duplicate rate, moodboard as inventory truth). It does not touch the attribute gaps, which are the majority. |

Questions 8, 9, 10 and 13 are critical and are NO or NOT MEASURED. Per the
gate's own rule, full implementation is refused.

---

## 3. What to adopt

**Adopt now — the instance-count contract.** Record, per room and semantic type,
how many instances the reading found, carry it as data, and make a shortfall
visible instead of silent. This is the part that has evidence behind it, it does
not depend on the model authoring anything, and it is the prerequisite for every
later element-first step.

**Adopt next, if the count contract proves out — canonical element identity.**
One element, N instances, one asset. This is what turns 90 credits of bar stools
back into 30. It needs a way to decide that two same-type pieces in one room are
the same piece, which `shape_key` currently answers with position alone.

**Do not adopt — model-authored inventories.** Gate question 8 fails. If a
future larger model changes that, re-run `qwen_capability.py` against it; the
harness and the ground truth are already written.

**Do not adopt — replacing the moodboard reading.** It is the only thing that
measured 8 of 8 on inventory, and `generate_elements` spends real money against
its crops.

---

## 4. What was deliberately not built

The prompt lists 24 research documents. Writing 24 thin files would misrepresent
how much was actually measured, so this record and the two benchmark artifacts
carry the findings instead. The unmeasured areas are named NOT MEASURED in the
gate table above rather than filled with plausible prose.

Specifically not attempted: element image generation, compositional moodboard
rendering, a new coordinate model, and a migration of the relationship graph.
Each depends on gate questions that did not pass.

---

## 5. Artifacts

- `research/element-first/qwen_capability.py` and `qwen-capability.json`
- `research/element-first/inventory_benchmark.py` and `benchmark-results.json`
- Real-project evidence: `data/projects/proj_553cb09794/planning/scene_reading.json`

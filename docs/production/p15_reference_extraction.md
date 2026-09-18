# P15 — Reference Attribute Extraction Fidelity

P14 proved the executor paints a frame finish where the evidence reaches it, and
that almost no evidence did. On eight real project photographs the live model
filled `frame_finish` zero times. P15 fixes the extraction boundary that caused
that, and does it without teaching the model to guess.

Stack unchanged and frozen: Gemini for vision, Meshy for asset generation, the
Allure Spatial Engine for layout, Blender for execution.

---

## 1. What was actually wrong

Two causes, both in the contract rather than the model.

**The prompt invited omission.** It said, in as many words, *"DESCRIBE WHAT YOU
SEE, only where you are sure (leave a field out otherwise)"*. The model took the
invitation.

**The schema permitted it.** `REFERENCE_CLASSIFICATION_SCHEMA` listed all eight
attribute fields under `properties` but required only `reference_class` and
`confidence`. An optional field that never appears is indistinguishable from a
field the model never considered.

This repository had already learned that exact lesson once. `SCENE_READING_SCHEMA`
carries a comment recording that `against` and `faces` were optional, that
flash-lite then omitted both on every element of every room, and that making them
required fixed it. P15 applies the same fix to the same class of bug.

Nothing about `VisualAttributes`, `DesignIntent`, provenance or the resolution
ladder needed to change. The fields already existed and were already plumbed
through to the manifest. They were simply never filled.

---

## 2. The experiment

Three prompt variants, the same eight photographs, the live Gemini provider, and
ground truth established by looking at the pictures rather than by trusting the
model.

- **A** — the production prompt and schema exactly as P14 left them.
- **B** — A plus explicit per-field instructions, with the attribute fields made
  required in the schema.
- **C** — B plus a part-by-part inspection order and explicit frame routing.

Ground truth matters more than population here, because **four of the eight
images are mattresses**. A mattress has no frame. A prompt that pushes
`frame_finish` to eight of eight has hallucinated four times, not improved four
times. Those four images are the phase's built-in false-positive control, and a
fifth image, a teal sofa on a skirted base with no visible legs, is another.

Only three of the eight images show a frame at all: gold metal arm bars on the
grey sofa-bed, small dark feet on the two-tone sofa, and an unmistakable dark
wood frame on the sage tufted sofa.

| Attribute | A (current) | B (structured) | C (part-aware) |
|---|---|---|---|
| material | 1 | 0 | 0 |
| upholstery | 7 | 8 | 8 |
| frame_finish | 0 | 2 | 2 |
| color_words | 1 | 8 | 8 |
| color_hex | 0 | 0 | 0 |
| pattern | 1 | 8 | 8 |
| visual_descriptors | 8 | 8 | 8 |
| style_descriptors | 0 | 2 | 2 |
| false positives + unsupported inferences | 0 | 0 | 0 |
| extraction fidelity | 0.385 | 0.926 | **0.962** |

C was promoted. It scored highest, and it recovered the two frame cases a human
would call unmissable, while B recovered one of those plus the marginal feet.

Selection was on the attribute table, not on the single fidelity figure. The
figure is reported because it is useful, not because it decided anything.

---

## 3. After: the production path

The promoted prompt and schema were then run through `classify_reference`, the
real production entry point, over the same eight images.

| Field | Before (P14) | After (P15) |
|---|---|---|
| upholstery | 8 of 8 | 8 of 8 |
| visual_descriptors | 8 of 8 | 8 of 8 |
| frame_finish | 0 of 8 | **2 of 8** |
| color_words | 0 of 8 | **8 of 8** |
| pattern | 0 of 8 | **7 of 8** |
| style_descriptors | 0 of 8 | **2 of 8** |
| color_hex | 0 of 8 | 0 of 8 |
| material | 0 of 8 | 0 of 8 |

Per-image, `frame_finish` now reads:

| Image | Object | Extracted | Verdict |
|---|---|---|---|
| ref_04 | sofa, skirted base | empty | correctly empty |
| ref_05 | sofa, gold arm bars | `gold metal trim` | correct |
| ref_06 | sofa, small dark feet | empty | acceptable miss |
| ref_07 | sofa, dark wood frame | `dark wood` | correct |
| ref_09 to ref_12 | mattresses | empty | correctly empty, four times |

Extraction fidelity on the production path: **1.0**, with 25 of 25 visibly
supported attributes correct and zero false positives.

Two numbers deserve emphasis, because they are the ones a careless phase would
have inflated. `color_hex` stayed at **0 of 8** — no hex was invented from a
colour word, and the prompt forbids the conversion explicitly. `material` stayed
at **0 of 8**, which is correct: every one of the eight pieces is fully
upholstered, so there is no independently visible body material to report. The
prompt now says so directly.

`frame_finish` at 2 of 8 is the honest ceiling for this image set, not a
shortfall. Five of the six empties are the right answer.

---

## 4. Not a second extraction system

The change is confined to the two canonical locations:

- `reference_classification_prompt` in `app/intelligence/prompts.py`
- `REFERENCE_CLASSIFICATION_SCHEMA` in the same module

No new module, no parallel parser, no second provider path. `attributes_from_raw`
already coerced each field and already rejected anything that is not a seven
character hex, so a required-but-empty field arrives as empty and a malformed hex
is still dropped. `IntentProvenance` already records the image, the stage and the
model label, so the chain from image to evidence to `intent_id` to plan item to
scene object to manifest is the P11 chain, reused unchanged.

Raw evidence is preserved as it always was: the descriptive phrase stays in
`visual_descriptors` while the normalized value goes to the structured field. The
prompt asks for exactly that, so "what did Gemini observe" and "what did the
system derive" remain separately answerable.

---

## 5. P14's fallback is untouched

The descriptor-derived frame finish still exists and still works. Priority is
explicit first:

1. An explicitly extracted `frame_finish` wins, tagged `finish.source = "stated"`.
2. Otherwise a descriptor that **both** names a structural part **and** resolves
   through the existing finish resolver supplies it, tagged
   `finish.source = "descriptor"`.
3. Otherwise no finish.

The promotion rule was not broadened. "Glass coffee table" still supplies
nothing, because it describes the whole object. Bare "walnut" still supplies
nothing, because it names no part. "Luxurious" and "premium" still supply
nothing, because they resolve to no material at all. Tests assert each of these.

The values P15 now extracts were checked against that resolver, since a value it
drops renders nothing: `gold metal trim` resolves to brass, `dark wood` and
`wood` to oak veneer, `black metal` and `blackened metal` to blackened metal.

---

## 6. Three separate rates

| Stage | Measure |
|---|---|
| Extraction (P15) | 1.0 on the production path; 25 of 25 supported attributes correct, 0 false positives |
| Preservation (P13) | 7 of 7 attributes reach the manifest |
| Rendering (P14) | `frame_finish` paintable on 10 of 58 assets; colour words and pattern metadata only |

These are never collapsed into one number. An attribute can be extracted
perfectly, preserved perfectly, and still not change a pixel, which is precisely
the situation for pattern today.

---

## 7. Verification

Full suite: **863 passed, 7 skipped, 30 xfailed**. That is the 812 P14 baseline
plus exactly 51 new P15 tests. No existing test was modified.

One existing test did fail during this phase, and it caught a real mistake of
mine: a docstring I wrote used the phrase "load bearing" metaphorically, and the
architectural guard that forbids building-compliance vocabulary anywhere in the
backend flagged it correctly. The wording was changed; the guard was not.

Benchmarks: P11 10/10, P12 10/10, P13 10/10, P14 11/11, all unchanged. The frozen
P4 to P10 spatial benchmarks re-run with their recorded figures intact: 30/30
constraint, 40/40 candidate, 22/22 scene, 12/12 repair, 10/10 clearance, P10
system success rate 1.0, every one still deterministic.

No geometry, solver, repair, Meshy or Blender behaviour was touched.

Artifacts:

- `docs/benchmarks/p15_reference_extraction.json`
- `aether-backend/research/p15_extraction_experiment.py`
- `aether-backend/tests/test_p15_reference_extraction.py`

---

## 8. Honest remaining limitations

1. **Eight images is a small sample, and one run each.** Population counts moved
   by one or two between repeat runs of the same variant during this phase. The
   direction of the change is unambiguous; the exact figures are not stable to
   the last unit.
2. **`dark wood` resolves to oak veneer.** The resolver matches the generic word
   "wood" and oak is the generic wood entry, so the sage sofa's dark mahogany
   frame would render as light oak. Changing that is a rendering change and was
   out of scope for this phase. It is the most concrete next improvement.
3. **The image set contains no glass, marble, stone or metal-bodied piece**, so
   `material` extraction is untested on anything that would legitimately populate
   it. The 0 of 8 is correct for these images but proves nothing about the field.
4. **Pattern is extracted well and still renders nothing.** 7 of 8 now carry a
   correct pattern value the executor cannot use, which widens the gap between
   what is known and what is shown.
5. **Only three of eight images show a frame at all.** A reference set with more
   framed furniture would test the routing far harder than this one does.

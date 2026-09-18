# Phase 1g — controlled negative wall-contact dataset

**Date:** 2026-09-15 · **Data only — no model was run.**
**Dataset:** `aether-backend/research/phase1g/dataset.json`
**Annotations:** `aether-backend/research/phase1g/annotations.json`
**Scenes:** `aether-backend/research/phase1g/scenes/` · **Manifest:** `scene_manifest.json`
**Scripts:** `research/phase1g/generate_scenes.py`, `research/phase1g/build_dataset.py`

Phase 1e and 1f artefacts untouched. No production file modified.

---

## What was blocking, and what unblocked it

Phase 1f could not measure a false-wall rate because the corpus held **5**
negatives across 2 scenes, with Category B confined to a single kitchen. The
sampling error lived in *which objects were chosen*, so no amount of re-running
could narrow it.

This phase fixes the input rather than the measurement: **18 new interior scenes
generated with the project's own image provider**, then annotated by eye.

### Source: the project's own generator, not the internet

`app.providers.local_image` — the same module the moodboard stage calls, the
same `runwayml/stable-diffusion-v1-5`, the same 704×448 and 28 steps from
`Settings`. The benchmark imagery is therefore the imagery production makes.

| | |
|---|---|
| Scenes requested | 18 |
| Generated without error | **18 / 18** |
| Time | ~15 s per scene warm, 27 s cold, **≈5 minutes total** |
| GPU | RTX 3050 6GB; Ollama evicted first so SD had the card |

**No internet images were used.** The 8 reference photos already in the project
were re-checked and remain out of domain — they are product shots of sofas and
mattresses, two on white backgrounds with no wall in frame.

### The prompts bias; they do not label

A probe established that SD 1.5 **does not obey spatial instructions**: asked for
"an ottoman alone in the middle of the floor" it returned a sectional and a rug;
asked for "stools pulled back from the island" it tucked them under it. So the
prompts only steer the sampler toward layouts where free-standing furniture is
likely. The requested bias is recorded in `scene_manifest.json` as `intent_bias`
and was **deliberately ignored at annotation time** — every label here came from
looking at the rendered image. Two scenes prove the point: they were asked for
lounges and returned vaulted stone halls, and both were rejected outright.

---

## Dataset quality check

| | count |
|---|--:|
| Total scenes generated | 18 |
| Scenes contributing cases | **16** |
| Scenes rejected whole | 2 |
| Total candidate negatives | 43 |
| **Valid negatives** | **32** |
| UNKNOWN / rejected | 11 |
| **Category A** | **17** |
| **Category B** | **15** |
| Preserved positives (Phase 1d/1e/1f) | **11**, unchanged |
| **Total cases** | **43** |

| Check | Required | Actual | |
|---|---|--:|:--|
| Independent scenes | ≥8 | **16** | PASS |
| Valid negatives | ≥25 | **32** | PASS |
| A/B balance | within 60/40 | 53% / 47% | PASS |
| Neither category in one scene only | — | A in 10 scenes, B in 11 | PASS |
| Scene does not determine category | ≥4 scenes with both | **5** | PASS |

The preferred target (32 negatives, ≥8 scenes) is met. The preferred 16/16 split
came out 17/15 — no case was moved between categories to even it up.

---

## Cases per scene

| Scene | Room | Negatives | A | B |
|---|---|--:|--:|--:|
| s01 | living_room | 1 | 0 | 1 |
| s02 | living_room | 2 | 2 | 0 |
| **s03** | living_room | 2 | **1** | **1** |
| s04 | bedroom | 1 | 0 | 1 |
| **s05** | bedroom | 2 | **1** | **1** |
| s06 | kitchen | 4 | 0 | 4 |
| s07 | kitchen | 2 | 0 | 2 |
| **s08** | dining_room | 2 | **1** | **1** |
| s09 | office | 1 | 0 | 1 |
| **s10** | office | 3 | **2** | **1** |
| s11 | lounge | 4 | 4 | 0 |
| s13 | living_room | 1 | 1 | 0 |
| s14 | bedroom | 1 | 0 | 1 |
| s15 | kitchen | 1 | 1 | 0 |
| **s16** | dining_room | 2 | **1** | **1** |
| s17 | office | 3 | 3 | 0 |

Bold rows carry **both** categories — 5 scenes, which is what breaks the Phase 1f
confound where Category B *was* the kitchen.

No scene contributes more than 4 negatives (12.5% of the set); Phase 1f's kitchen
carried 3 of 5, or 60%.

**Spread:** 6 room types — kitchen 7, office 7, living_room 6, bedroom 4,
dining_room 4, lounge 4. **Object types:** chair 10, armchair 8, bar_stool 6,
dining_table 3, ottoman 2, bench 2, coffee_table 1.

---

## Ground truth rule, applied to all 43 cases

```
POSITIVE   the queried object itself physically contacts a wall
NEGATIVE   it does not
```

A wall being visible behind the object is **not** part of the rule — it is
recorded separately as `wall_visible`, because whether the model keys on it is
the hypothesis the next phase tests. `wall_visible` is true for **every** negative
in this set, including all 17 Category A cases, so the field cannot by itself
explain any error.

```
CATEGORY A   no wall-backed mass immediately behind at similar depth; floor
             visible around the object
CATEGORY B   free-standing, but a wall-backed object or surface sits immediately
             behind it and overlaps it in frame
```

Every Category B case is a real instance of the target confound: a desk chair at
a wall-built desk (s09), stools at wall-backed counter runs (s06, s07), benches
at the foot of wall-backed beds (s05, s14), a chair in front of a wall sideboard
(s08), a chair at a wall bench (s16), an armchair in front of a fixed media unit
(s01, s03).

---

## What was excluded, and why

11 rejections, none of them to hit or avoid a number:

| Scene | Object | Reason |
|---|---|---|
| s12 | **whole scene** | generator returned a vaulted stone hall, not a lounge; no readable furniture |
| s18 | **whole scene** | vaulted hall with pews; pieces small, low-contrast, cropped |
| s01 | left armchair | back sits against the timber wall, gap not visible — wall contact unsettleable |
| s02 | round white table | leaves the right frame edge |
| s02 | pale bench | occluded by the drum table |
| s04 | bench at foot of bed | leaves the right frame edge |
| s07 | leftmost bar stool | leaves the left frame edge |
| s08 | foreground chairs | legs run off the lower frame edge and overlap |
| s13 | coffee table | leaves the left frame edge |
| s13 | side table | leaves the right frame edge |
| all | rugs | a rug meets walls at its edges; the question is degenerate |

Six negatives (the s06 and s07 bar stools) carry `visual_occlusion: "feet reach
the lower frame edge"` and were **kept**. The crop is at the floor, not at the
object's rear, so the wall judgement is unaffected — the whole counter mass sits
visibly between each stool and the back wall. The two s10 mid-floor chairs carry
`"small in frame"` and were kept for the same reason: they stand metres from any
wall in an open floor plate, which is unambiguous at any size. Both criteria are
stated so a reviewer can disagree and drop them.

---

## Preserved positives

All **11** historical positives are carried across unchanged, read straight from
`tests/fixtures/relationship_benchmark.json` and marked
`origin: "preserved_phase1d"` with `scene_id: "hist_<room>"`. Their annotations
were not edited, and the fixture itself was not written to. They span the five
original rooms (living_room_a, living_room_b, kitchen, bathroom, master_bedroom).

New positives were **not** added. The positive base rate is deliberately held at
the historical 11 so that any change in the next phase's positive-side numbers is
attributable to the model, not to the dataset.

Note the resulting class balance: **11 positives to 32 negatives**. That inverts
Phase 1f (11 : 5) and is intentional — the quantity that could not be measured
was the negative-side rate, and precision on the positive side will need reading
against this new base rate rather than compared raw to 1f.

---

## Regression

`pytest -q` before and after: **355 passed, 7 skipped, 30 xfailed** — unchanged.
No production source file was modified; `git status` shows only
`research/phase1g/` and this report as additions.

---

## DATASET STATUS:
**READY**

## SCENES:
**16** contributing (18 generated, 2 rejected whole)

## VALID NEGATIVES:
**32**

## CATEGORY A:
**17**

## CATEGORY B:
**15**

## UNKNOWN/REJECTED:
**11** (including 2 whole scenes)

## SCENE BALANCE:
**PASS** — A appears in 10 scenes, B in 11, both together in 5; no scene
contributes more than 4 of the 32, and scene no longer determines category.

## PRODUCTION CHANGES:
**NONE**

## NEXT EXPERIMENT:
Run the frozen `qwen2.5vl:7b` wall benchmark twice on this dataset — same
imported `_wall_a` prompt, same `{"answer": boolean}` schema, temperature 0.2,
Q4_K_M, no prompt changes. With 32 negatives the 95% Wilson interval on the
false-wall rate narrows from the ±26 points Phase 1f carried to roughly ±17, and
for the first time Category A and Category B can be compared without scene
confounding.

One thing to decide before that run: the negatives are **generated** images and
the positives are **historical** ones, so a difference between the two classes
could in principle be a difference between the two image sources. The cheap
control is to also annotate positives from the new scenes and re-run; it is not
needed to get a false-wall rate, but it is needed before that rate is compared
across classes.

**STOP.**

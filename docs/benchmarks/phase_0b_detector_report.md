# Phase 0b - object detection benchmark gate

Does an open-vocabulary detector identify objects in a moodboard render
better than the scene reader does? Measurement only: no production code
was changed and nothing here is wired into the pipeline.

## Environment

- GPU: NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6.0 GB
- CUDA available: True
- torch: 2.14.0+cu126
- detector: `IDEA-Research/grounding-dino-tiny`
- thresholds: box 0.3, text 0.25 - one pair for every image

## Dataset

- 5 real moodboard renders, 704x448, from two real projects
- room types: bathroom, kitchen, living_room, master_bedroom
- ground truth: `tests/fixtures/detection_benchmark.json`, labelled by eye

**Limitations.** No hospitality or industrial room has ever been run through
this pipeline, so every image is residential and the label list is the
residential one. Windows, doors, walls, floors and ceilings are excluded from
both the detector's prompt and the scoring, because `scene_reading_prompt()`
forbids the reader from boxing them. Both systems are normalised with
`vocab.canonical_type()`, which folds a television and a media console onto
the single type `tv_unit` - a coarseness of the existing vocabulary that
costs both systems equally.

## Results

Micro-averaged over all images: true/false positives pooled, so a
three-object bathroom does not weigh as much as a seven-object living room.

| Metric | Scene reader (qwen2.5vl:3b) | Grounding DINO | Hybrid (union) | Confirm (both agree) |
|---|---|---|---|---|
| Precision | 0.71 | 0.49 | 0.47 | 0.87 |
| Recall | 0.60 | 0.76 | 0.84 | 0.52 |
| F1 | 0.65 | 0.59 | 0.60 | 0.65 |
| False positives | 6 | 20 | 24 | 2 |
| False negatives | 10 | 6 | 4 | 12 |
| Avg time / image | 12.06s | 2.17s | 0.0s | 0.0s |

## Per image

### living_room - `moodboard_room_living_room.png`
*proj_553cb09794*

- expected: `curtains`, `ottoman`, `pillows`, `rug`, `side_table`, `sofa`
- **reader** P=1.00 R=0.67 F1=0.80 - found `ottoman`, `rug`, `side_table`, `sofa`
  - missed: `curtains`, `pillows`
- **DINO** P=0.62 R=0.83 F1=0.71 - found `armchair`, `bedside_table`, `curtains`, `ottoman`, `pillows`, `plant`, `side_table`, `sofa`
  - missed: `rug`
  - spurious: `armchair`, `bedside_table`, `plant`
- **hybrid union** P=0.67 R=1.00 F1=0.80 - found `armchair`, `bedside_table`, `curtains`, `ottoman`, `pillows`, `plant`, `rug`, `side_table`, `sofa`
  - spurious: `armchair`, `bedside_table`, `plant`
- **confirm (both)** P=1.00 R=0.50 F1=0.67 - found `ottoman`, `side_table`, `sofa`
  - missed: `curtains`, `pillows`, `rug`

### kitchen - `moodboard_room_kitchen.png`
*proj_553cb09794*

- expected: `bar_stool`, `kitchen_counter`, `plant`, `wall_shelf`
- **reader** P=0.50 R=0.50 F1=0.50 - found `bar_stool`, `kitchen_counter`, `kitchen_island`, `sideboard`
  - missed: `plant`, `wall_shelf`
  - spurious: `kitchen_island`, `sideboard`
- **DINO** P=0.33 R=0.75 F1=0.46 - found `armchair`, `bar_stool`, `desk`, `kitchen_counter`, `mirror`, `plant`, `sideboard`, `tv_unit`, `vase`
  - missed: `wall_shelf`
  - spurious: `armchair`, `desk`, `mirror`, `sideboard`, `tv_unit`, `vase`
- **hybrid union** P=0.30 R=0.75 F1=0.43 - found `armchair`, `bar_stool`, `desk`, `kitchen_counter`, `kitchen_island`, `mirror`, `plant`, `sideboard`, `tv_unit`, `vase`
  - missed: `wall_shelf`
  - spurious: `armchair`, `desk`, `kitchen_island`, `mirror`, `sideboard`, `tv_unit`, `vase`
- **confirm (both)** P=0.67 R=0.50 F1=0.57 - found `bar_stool`, `kitchen_counter`, `sideboard`
  - missed: `plant`, `wall_shelf`
  - spurious: `sideboard`

### bathroom - `moodboard_room_bathroom.png`
*proj_553cb09794*

- expected: `mirror`, `vanity`
- **reader** P=0.67 R=1.00 F1=0.80 - found `bathtub`, `mirror`, `vanity`
  - spurious: `bathtub`
- **DINO** P=0.20 R=0.50 F1=0.29 - found `bathtub`, `curtains`, `kitchen_counter`, `mirror`, `wardrobe`
  - missed: `vanity`
  - spurious: `bathtub`, `curtains`, `kitchen_counter`, `wardrobe`
- **hybrid union** P=0.33 R=1.00 F1=0.50 - found `bathtub`, `curtains`, `kitchen_counter`, `mirror`, `vanity`, `wardrobe`
  - spurious: `bathtub`, `curtains`, `kitchen_counter`, `wardrobe`
- **confirm (both)** P=0.50 R=0.50 F1=0.50 - found `bathtub`, `mirror`
  - missed: `vanity`
  - spurious: `bathtub`

### master_bedroom - `moodboard_room_master_bedroom.png`
*proj_5db681f48c (archived)*

- expected: `bed`, `bedside_table`, `pillows`, `plant`, `rug`, `wall_art`
- **reader** P=0.60 R=0.50 F1=0.55 - found `bed`, `bedside_table`, `rug`, `side_table`, `sideboard`
  - missed: `pillows`, `plant`, `wall_art`
  - spurious: `side_table`, `sideboard`
- **DINO** P=0.44 R=0.67 F1=0.53 - found `bed`, `bedside_table`, `curtains`, `kitchen_counter`, `mirror`, `ottoman`, `pillows`, `rug`, `table_lamp`
  - missed: `plant`, `wall_art`
  - spurious: `curtains`, `kitchen_counter`, `mirror`, `ottoman`, `table_lamp`
- **hybrid union** P=0.36 R=0.67 F1=0.47 - found `bed`, `bedside_table`, `curtains`, `kitchen_counter`, `mirror`, `ottoman`, `pillows`, `rug`, `side_table`, `sideboard`, `table_lamp`
  - missed: `plant`, `wall_art`
  - spurious: `curtains`, `kitchen_counter`, `mirror`, `ottoman`, `side_table`, `sideboard`, `table_lamp`
- **confirm (both)** P=1.00 R=0.50 F1=0.67 - found `bed`, `bedside_table`, `rug`
  - missed: `pillows`, `plant`, `wall_art`

### living_room - `moodboard_room_living_room.png`
*proj_5db681f48c (archived)*

- expected: `coffee_table`, `pillows`, `rug`, `sofa`, `tv_unit`, `vase`, `wall_art`
- **reader** P=0.80 R=0.57 F1=0.67 - found `rug`, `sideboard`, `sofa`, `tv_unit`, `wall_art`
  - missed: `coffee_table`, `pillows`, `vase`
  - spurious: `sideboard`
- **DINO** P=0.75 R=0.86 F1=0.80 - found `kitchen_counter`, `ottoman`, `pillows`, `rug`, `sofa`, `tv_unit`, `vase`, `wall_art`
  - missed: `coffee_table`
  - spurious: `kitchen_counter`, `ottoman`
- **hybrid union** P=0.67 R=0.86 F1=0.75 - found `kitchen_counter`, `ottoman`, `pillows`, `rug`, `sideboard`, `sofa`, `tv_unit`, `vase`, `wall_art`
  - missed: `coffee_table`
  - spurious: `kitchen_counter`, `ottoman`, `sideboard`
- **confirm (both)** P=1.00 R=0.57 F1=0.73 - found `rug`, `sofa`, `tv_unit`, `wall_art`
  - missed: `coffee_table`, `pillows`, `vase`

## Hardware performance

- detector: 2.17s per image on GPU, peak 2027.2 MB VRAM
- reader: 12.06s per image (qwen2.5vl:3b, local)
- batch size 1, inference only, no CPU fallback needed

- detector label set (28 prompts): `sofa`, `armchair`, `chair`, `bar stool`, `ottoman`, `bed`, `pillow`, `coffee table`, `side table`, `dining table`, `desk`, `bedside table`, `cabinet`, `wardrobe`, `shelf`, `television`, `tv stand`, `lamp`, `plant`, `rug`, `curtain`, `mirror`, `painting`, `vase`, `towel`, `kitchen counter`, `bathtub`, `vanity`

---

# Decision

*Everything above is generated by `research/phase0b_benchmark.py` and is
overwritten on every run. This section is hand-written, is a judgement rather
than a computation, and must be re-attached if the benchmark is re-run.*

## Verdict: **OPTION C — HYBRID**, but not the hybrid that was proposed

The detector is **not** a better reader. Adopting it wholesale (Option A) is
refused by the numbers, and so is the union-shaped hybrid the Phase 1 plan
assumed.

What survives is a narrower claim: **Grounding DINO is a good verifier and a poor
detector.** Keep the scene reader as the source of elements; use the detector to
vote on what it found.

## Why

Run twice. The detector is deterministic and scored identically both times; the
reader is not.

| Rule | P (run 1 / 2) | R | F1 | FP | FN |
|---|---|---|---|---|---|
| reader alone | 0.64 / 0.71 | 0.56 / 0.60 | 0.60 / 0.65 | 8 / 6 | 11 / 10 |
| DINO alone | 0.49 / 0.49 | 0.76 / 0.76 | 0.59 / 0.59 | 20 / 20 | 6 / 6 |
| hybrid union | 0.42 / 0.47 | 0.76 / 0.84 | 0.54 / 0.60 | 26 / 24 | 6 / 4 |
| **confirm (intersection)** | **0.88 / 0.87** | 0.56 / 0.52 | 0.68 / 0.65 | **2 / 2** | 11 / 12 |

1. **DINO alone loses on F1** (0.59 against 0.60–0.65). It finds more — recall
   0.76 against 0.56–0.60 — but is wrong far more often: 20 false positives every
   run against the reader's 6–8. Chief offenders: `kitchen_counter` ×3, and
   `armchair`, `mirror`, `curtains`, `ottoman` ×2 each.
2. **Union is the worst of the four rules.** It inherits both systems' recall and
   both systems' false positives; precision falls to 0.42–0.47. The Phase 1 plan
   assumed union-shaped reconciliation would help. It does not.
3. **Intersection is the only rule that beats the reader**, and it wins on the
   metric that maps to money: false positives fall from 6–8 to **2**, precision
   rises to 0.87–0.88, stable across both runs. In run 1, every true positive the
   reader found was also found by DINO — the detector rejected the reader's
   mistakes without discarding its correct answers.

A false positive that survives human review costs 30 credits of mesh for
something that was never in the picture. A false negative costs a reviewer
noticing a missing sofa, which is the failure mode humans are good at catching.
Precision is worth more than recall at this point in the pipeline.

## What this benchmark did NOT measure

**Bounding-box quality is untested.** Ground truth deliberately carries no boxes
(Phase 0b scope), so the claim that motivated Phase 1 — "the detector supplies
better geometry than the reader" — has no evidence either way. It must be
measured separately before any geometry is taken from the detector.

**N = 25 objects across 5 images.** Every image is residential; no hospitality or
industrial room has ever been through this pipeline. The F1 differences between
reader, DINO and confirm are within noise at this sample size. Only the precision
effect — 6–8 false positives down to 2 — is large enough to read through it.

## Blocking finding, unrelated to the detector

`OllamaProvider` does **not** implement `read_scene_elements`. Only
`GeminiProvider` does. `scene_plan.py:82` looks the method up with `getattr` and,
when it is absent, emits `"<provider> cannot read renders"` and returns an empty
`SceneReading`.

So a local-only install reads **zero** elements from its moodboards: no crops, no
review, no meshes. Steps 4–6 of the Studio are empty. This benchmark reached
qwen2.5vl by calling `OllamaProvider._generate` directly, which is the only
reason a local baseline exists at all.

Whatever is decided about the detector, `OllamaProvider.read_scene_elements()`
has to be written before the pipeline can run without Gemini.

## Recommended next phase

Not the original Phase 1. In order:

1. **Write `OllamaProvider.read_scene_elements()`** — without it, local operation
   is broken, and that is a bigger problem than detector adoption.
2. **Re-run this benchmark on 15–20 images** once more projects exist, to see
   whether the precision effect holds. The harness and fixture already exist.
3. **Then** wire the detector as a confirmation signal only: an element the
   detector does not corroborate is flagged in review, never auto-dropped. The
   human gate stays the decision-maker; this changes only what it is shown first.
4. Measure box quality separately before taking any geometry from the detector.


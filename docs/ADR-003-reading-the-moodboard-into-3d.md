# ADR-003 — Reading the approved moodboard into 3D

**Status:** accepted, with one open product question · 2026-09-13 · supersedes nothing
**Applies to:** `app/intelligence/{scene_reading,prompts,schema,provider,gemini_provider}.py`,
`app/api/projects_routes.py` (`/scene-reading`), `app/jobs/handlers/scene_plan.py`,
`aether-frontend/src/features/studio/components/element-review.tsx`,
`blender/scripts/render_asset_sheet.py`

> **Which stage is this?** Everything between the client approving the moodboard
> (Step 3) and anything being generated in 3D. The approved render is read back
> into elements, each element is cut out as a crop, each crop is checked on its
> own, and a human confirms every crop before a single credit is spent. ADR-002
> covers how the moodboard was painted; this covers how it is read.

The client agrees to a picture. From that moment the picture is the brief, and
the job is to turn it into meshes without quietly turning it into something
else. Nearly every decision below exists because a step *looked* like it had
worked and had not.

---

## 1. A bounding box is rejected out loud or not used at all

### Decision

`_bbox()` decides one coordinate convention per box and then demands the box be
self-consistent in it. A box that mixes conventions, reverses its corners, or
covers the whole image is rejected with a named warning. It is never repaired.

### Why

Gemini returned `[402, 237, 1.0, 712]` for a *large teal and striped sofa*.
Three coordinates are 0–1000; the `1.0` is the right-hand edge written as a
fraction. The old rule — "if anything exceeds 1.5, divide the lot by 1000" —
turned that `1.0` into `0.001`, and a `sorted()` call then swapped the now-
inverted pair so nothing looked wrong. The crop came from the left 40 % of the
image instead of the right 60 %: a clean, plausible picture of the wrong thing,
which is worse than no picture, because nothing downstream can tell.

A second real case, same render: `[0.702, 0.0, 1.0, 4.49]` for curtains.

`tests/test_scene_reading.py` pins both boxes verbatim so this exact failure
cannot return quietly.

### What the fix then revealed

With the guard live, **10 of 31 boxes were rejected — 32 %**. The old code had
been silently converting all of them into wrong crops. The rejections were also
structured rather than random: the model mixed conventions *per axis*, x as
fractions beside y as 0–1000 (`[0.0, 483, 1.0, 936]`).

Inferring per-axis would have been exactly the plausible-looking guess the
guard exists to prevent, so the *ask* changed instead: whole numbers out of
1000, and `"type": "integer"` in the response schema so the API refuses a
decimal before our guard has to catch it. Rejections fell from 10/31 to
**1/24**, and kept elements rose from 21 to 23.

---

## 2. A crop is judged by area and short side, then by neither

### Decision, and its reversal

First `MIN_SIDE = 64` on both dimensions → replaced by `MIN_AREA_PX = 6_000`
plus `MIN_SHORT_PX = 30` → **retired entirely** in favour of
`MIN_LEGIBLE_PX = 16`, a floor meaning "there is no shape here at all".

### Why it changed twice

Requiring 64 px on both sides discarded a rug measured 538 × 59. A rug seen
edge-on is legitimately thin — the same shape of mistake as the bed whose
photographed height was once treated as its real one: a rule that assumes
objects are roughly cubic.

Area-plus-short-side fixed that and was still wrong, just less obviously. It
discarded a towel rail at 59 × 88 whose silhouette is plainly legible, while
three stools boxed as one "bar stool" and a bed boxed as a "rug" sailed through
on size alone. Section 6 measured why, and section 8 tested it for real: **size
does not predict whether a crop is usable.** Judging that is the check's job,
then a person's.

---

## 3. The bathroom under-read was a prose rule, not a model limitation

### What was wrong, and what I got wrong first

The bathroom returned 2 elements where 4 were visible, and I reported it as
"2 of 6+ visible fixtures", slowest room at 9.7 s — implying truncation or a
model limit. Investigating:

- The raw JSON was **complete**; `surfaces` came after `elements`, intact. Not
  truncation.
- Re-running took **2.0 s** (five runs, 1.6–2.3 s). The 9.7 s was first-call
  latency. "Slowest room returned fewest elements" was a correlation I invented.
- **"6+ visible fixtures" was wrong.** I counted what a 2BHK bathroom *should*
  have. The render contains no toilet and no bath. The model invented nothing;
  it obeyed "do not invent pieces that are not visible".
- Asked plainly, the model *does* see the missing pieces:
  `['mirror','sink','faucet','vanity','towel rail','towel','shower']`. So it was
  suppression, not recognition.
- Ablating the prompt rules one at a time: removing *"skip anything smaller than
  roughly a book"* recovered the towel rail. The doorway rule was innocent.

### Decision

That size rule was **section 2's bug written in prose** — one-dimensional
language applied to a long, thin object. It now reads: skip specks, but "a piece
that is long but thin — a rail, a shelf, a rug seen edge-on — is NOT small."

### What this did not fix

The walk-in shower was never returned, under any prompt variant. It is
architecture with no free-standing object, and the reading schema has only
`elements` and `surfaces` (materials). See section 9.

---

## 4. Every crop is shown back to the model alone, without its label

### Decision

`check_element_crop()` sends one crop, with no scene around it and **without
naming what it is supposed to be**, and asks what it shows. The answer is
compared to the label in code. Verdicts: `ok`, `mismatch`, `crowded`,
`duplicate`, `unreadable`, `unchecked`.

### Why the label is withheld

Asked "is this a table lamp?" a vision model agrees. Asked "what is this?" it
does not. The same reason the scene read is not allowed to grade its own work.

### Why it exists at all

A box can be structurally perfect and around the wrong thing. Real cases from
one run: a box of floorboards returned as "table lamp", a bed returned as
"rug", the whole kitchen returned as "kitchen counter". Nothing about the
geometry is wrong, so no geometric guard can see it.

On the five approved renders it flagged **12 of 20 crops**, catching every case
above plus two I had scored as fine by eye — an "extractor hood" that is a dark
panel and a "kitchen island" that is a diagonal slab. Roughly two flags were
marginal. That error runs in the right direction: a false flag costs review
attention, a missed one costs a credit and ships a wrong mesh.

`fills_frame: false` is what catches a whole-room box. A failed or unsure check
is `unreadable` — **never a pass** — which routes the crop to a human.

### Duplicates are found without a model call

Same room, same semantic type, and either IoU ≥ 0.6 **or** ≥ 0.8 of the smaller
box inside the larger. Both are needed: three "black bar stool" boxes each ran
from their stool to the right edge of the kitchen, so each contained the next —
100 % containment but only 0.42 IoU. Gating on semantic type stops a throw
pillow inside a sofa's box counting as the sofa.

**A mistake recorded on purpose:** I reported a "duplicate sofa under a second
name" in the living room. There are genuinely two sofas in that render, with
non-overlapping boxes. I judged it from thumbnails. A test pins that case so the
opposite error cannot be introduced while fixing the first.

### Cost

25 vision calls per project instead of 5. No Meshy spend. It exceeds the free
tier's per-minute rate — a single project does, not just concurrent ones — so
runs throw HTTP 429 and churn through fallback models: read 12.6 s, check
59.5 s. **This is a launch blocker, not a scaling one.** It needs solving before
real users, not before more pipeline work.

---

## 5. Nothing generates until a human says yes

### Decision

`SceneElement.approved` is `None` until a person decides.
`approved_for_generation()` returns only elements where it is `True`, plus a
list of what is being held and why. `None` is **not consent.**

`GET`/`PATCH /projects/{id}/scene-reading` back `element-review.tsx`, which
shows each crop beside its label, sorted so flagged ones come first. Nothing is
pre-ticked: a default of yes is not a decision. A decision naming an element
absent from the current reading returns **409 `UNKNOWN_ELEMENT`** rather than
applying quietly — a decision landing on nothing means the client is looking at
a reading that has since been re-read, and silently dropping it would approve
crops nobody looked at.

`SceneElement.crop_px` records each crop's size **before** upscaling, so a
61 × 56 towel rail and a 586 × 420 bed cannot look identical to the reviewer.

### This is the permanent safeguard

**Stage 3 cannot fire accidentally — for as long as this is paused, however long
that is, and for whoever picks it up later.** The automatic check narrows how
much needs reviewing; it never stands in for the reviewing. Verified after the
bounded test: 0 elements ready, 24 held. The five elements approved for that
test were reset to `None` afterwards precisely so a re-run cannot re-spend.

---

## 6. Resolution and generative upscaling were both tested and both rejected

Measured on the 6 GB RTX 3050, against the 1024 × 452 (463k px²) crop that
produced the one validated mesh.

### Render resolution — rejected

| render size | per room | 5 rooms | median crop | vs validated input |
|---|---|---|---|---|
| 704 × 448 (kept) | 14.7 s | 1.2 min | 48k px² | 0.10× |
| 960 × 640 | 38.9 s | 3.2 min | 93k px² | 0.20× |
| 1088 × 704 | 51.4 s | 4.3 min | 116k px² | 0.25× |
| 1216 × 768 | — | — | — | **duplicated subjects, melted furniture** |
| 1536 × 960 | — | — | — | **OOM** |

2.7× the render time buys 1.9× the pixels and still leaves crops at a fifth of
the validated input. Above ~1088 × 704 SD 1.5 breaks down structurally — a model
limit, not a VRAM one, so better hardware would not move it.

*(An earlier reading that 960 × 640 was "free" was wrong: the 704 × 448 baseline
had included model load. Re-measured with a warm pipeline and a repeated
control.)*

### Generative upscaling (SD ×4) — rejected

| | LANCZOS | SD ×4 |
|---|---|---|
| median crop | 29.9 dB, 43 % detail, 6 ms | 27.8 dB, 42 % detail, **8.9 s** |
| towel rail | 25.3 dB, 28 % detail, 5 ms | 22.2 dB, 35 % detail, **2.1 s** |

On the median crop, strictly worse — it drifted from the truth and returned
nothing for it. On the small crop it *did* add detail, which is the bad case:
+7 % detail for −3 dB fidelity is the signature of plausible-and-wrong. Visibly,
it redrew the sofa's arms, cushion divisions and pattern band. **A changed
silhouette is worse than a soft one when the mesh is built from the silhouette.**
Run at `guidance_scale=0`, the setting that hallucinates least — the charitable
configuration, and it still lost.

---

## 7. LANCZOS upscaling is the standard crop treatment

### Decision

Every crop is enlarged toward the validated input scale: `UPSCALE_SHORT_PX = 512`,
long side capped at 1536 so a 522 × 90 rug does not become a 3,000 px strip whose
base64 body is most of the request, and skipped below `UPSCALE_MIN_GAIN = 1.2`
because resampling costs a little sharpness.

### Why, given it adds no information

Because what small crops lose is **texture, not shape**, and image-to-3D reads
the shape. Retention by spatial scale, measured by shrinking the validated crop
to each of our sizes and upscaling it back:

| scale | towel rail | median crop | striped sofa |
|---|---|---|---|
| fabric weave (~1 px) | 1 % | 18 % | 36 % |
| seams, piping (~2 px) | 14 % | 47 % | 64 % |
| cushion edges (~4 px) | 37 % | 70 % | 79 % |
| arms, back (~8 px) | 66 % | 84 % | 89 % |
| **silhouette (~16 px)** | **83 %** | **93 %** | **95 %** |

So this is a formatting step, not a quality lever, kept because it is free
(5–10 ms) and because the alternative was measured making the input less
faithful.

---

## 8. The bounded Stage 3 test — 5 items, 150 credits

Five elements approved by hand, spanning 3,416 → 246,120 px² native (a 72×
range), selected through `approved_for_generation()` rather than hardcoded, with
the harness refusing to run on more than five.

**Result: 5/5 succeeded. 150 credits (30 each), 237 s wall clock, 26.6k–31.2k
triangles, all within the ingester's limit.**

| element | native crop | check | outcome |
|---|---|---|---|
| towel rail | 61 × 56 (3,416 px²) | `unreadable` | **coherent towel over a wall rail with mounting brackets** |
| small wooden side table | 87 × 91 | `ok`, partial crop | complete table — **invented a lower shelf** |
| bedside table left | 109 × 124 | `ok` | closest match of the five |
| large tufted ottoman | 349 × 262 | `ok` | accurate silhouette; tufting smoothed away |
| bed | 586 × 420 | `ok` | right geometry, **legs thin and spindly** where the source is a solid base |

### The headline finding

**Crop size did not predict mesh quality.** The smallest input — the one the
check called `unreadable` and the old size gate discarded — produced one of the
cleanest meshes. The largest produced the most questionable geometry. This
corroborates section 7 from the other end and is why section 2's gate was
retired: pixel count was ranking crops by the wrong property.

---

## 9. Open questions — not resolved here

### ⚠ Product decision required: Meshy invents plausible detail

**This needs a founder-level decision before Stage 3 is used in anything
client-facing. It is not a technical detail to accept because the meshes look
good.**

The side table's lower shelf does not exist in the source crop. Meshy added it
while completing an occluded view — by design, that is what single-image
reconstruction does. It is the same class of behaviour as the SD ×4 upscaler
redrawing the sofa's arms, which was rejected in section 6; the difference is
that here it produces attractive furniture rather than an obvious artefact,
which makes it *harder* to notice, not less real.

The tension is direct: the product promises a client sees **their actual space**,
and the approval gate in section 5 asks a human to confirm each piece — but what
is generated may not be the piece that was confirmed. A reviewer ticking a crop
of a table is not knowingly approving a table with a shelf.

Options, none chosen:

- accept it, and describe the output as an interpretation rather than a likeness;
- constrain it (`should_remesh`, symmetry settings, tighter crops) and re-measure
  how much invention remains;
- show the generated mesh back to the client for a second approval, which moves
  the gate after the spend rather than before it;
- restrict image-to-3D to pieces whose crops are unoccluded, and use the catalog
  for the rest.

The right answer depends on what the promise is meant to mean, which is not an
engineering call.

### Genuinely untested

- **Crowded and mislabelled crops.** The bounded test used five single objects.
  The crops most likely to fail — three stools in one box, a bed boxed as a
  "rug", the whole kitchen boxed as "kitchen counter" — were all *held back* by
  the gate and never generated. That failure mode is unmeasured.
- **Relative scale between independently generated meshes.** Each was generated
  in isolation and rendered alone. Whether a bed, a bedside table and an ottoman
  come out correctly sized *relative to each other* once placed in a room is not
  something this test could see. The planner still decides metres, and the
  spatial validator still has to prove the result — but no one has checked that
  the meshes agree.
- **The walk-in shower, and architectural features generally** (section 3).
  Adding the category is small: `OpeningType.ALCOVE`, a third branch in
  `_pieces()`, and generalising `door_clearance_rects` — roughly 60 additive
  lines. The invasive part is that **nothing downstream consumes `SceneReading`
  today**: `compile_scene(project_id, analysis, style)` and
  `place_objects(scene, plan, assets)` do not take it. Recording a shower without
  that wiring buys nothing.

---

## Consequences

- The reading enriches the plan; it is not a precondition for one. A provider
  without `read_scene_elements` or `check_element_crop` yields an empty reading
  and the plan proceeds exactly as before. Both are optional capabilities
  discovered by `hasattr`, so the three-method `IntelligenceProvider` Protocol
  pinned by ADR-001 is unchanged.
- Walls and floors stay **materials**, never generated geometry. Room geometry
  is built procedurally by Blender from the room boundary, which is what keeps
  corners square, doors aligned, and lets the validator prove nothing blocks a
  doorway. Generating wall meshes from crops would replace geometry that is
  correct by construction with geometry that is correct by luck.
- Element positions are **words** (`against`, `faces`), never metres. A render
  has no depth and does not obey the room's real size: a 2.5 × 2.0 m bathroom
  renders as a long spa. They are arrangement intent for the planner.
- Vision output is non-deterministic. The same five renders yield 20–24 elements
  run to run, so element counts are not a regression signal; the verdict mix and
  the warnings are.
- `blender/scripts/render_asset_sheet.py` renders any GLB on a plain ground for
  review. It exists because every visual claim in this build has had to be shown:
  a "sparse rooms" report was a stale `.blend`, and an "unresolved stand-in" was
  a real sofa seen in a distorted equirect. Pass it an **absolute** output path —
  Blender resolves relative paths against its own working directory.
- Meshy balance at the time of writing: **3,555 credits**, after 150 spent on the
  bounded test.

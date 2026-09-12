# ADR-002 — What the client's photo contributes to the moodboard render

**Status:** accepted · 2026-09-12 · supersedes nothing
**Applies to:** `app/providers/local_image.py`, `app/jobs/handlers/analyze.py`,
`app/intelligence/{schema,coerce,crops,prompts}.py`, every `Settings.scene_image_*`

> **Which stage is this?** The Studio's **Step 3, "Generate Moodboard"** — the
> `analyze` job. Every `scene_image_*` setting and the whole Stable Diffusion /
> IP-Adapter path is referenced by `app/jobs/handlers/analyze.py` and nowhere
> else. Step 5, "Generate 3D Space", runs the `build` and `preview` jobs on the
> render lane and is Blender rendering the actual `SceneSpec`; it never touches
> Stable Diffusion. `reference_scale` has always been a moodboard parameter.

Two decisions, recorded together because they answer the same question from
different ends: *how does one of the client's own photographs reach the
generated scene, and how much of the render should it own?*

---

## 1. `reference_scale` is 0.35, and fidelity is what that costs

### Decision

`Settings.scene_image_reference_scale = 0.35` (was 0.6).

### Why

IP-Adapter conditioning is a dial between two failure modes, not a quality
knob. Near 0 the client's photo is ignored and the render is stock. Near 1 the
photo dominates and the render becomes a *product shot of the reference item* —
the sofa is faithful, but it is floating against a wall with no room around it.

The product's core promise is a **navigable room**: the moodboard scene is the
first frame of a walkthrough, and it has to establish a space the client can
imagine standing in. A beautifully faithful sofa in a non-room fails that
promise more completely than a room containing a sofa that is only
approximately theirs. So when the two cannot both be had, the room wins.

0.35 is where the room reliably survives.

### Evidence

Six renders, 512 px, 28 steps, scale 0.35 — two references (`ref_04.jpeg`, a
blue upholstered sofa; `ref_09.jpeg`, a white-and-grey patterned mattress)
across seeds 7, 42 and 123.

- **Reads as a room: 6 of 6.** Five unambiguously — furniture, floor, walls,
  window, rug, mid-distance framing. One (sofa/seed 123) is tighter, with the
  sofa filling most of the frame, but still sits in a room rather than against
  a backdrop. It was not a seed-lucky result in the original single-sample
  comparison.
- **Item fidelity does not hold, and varies by seed.** Across the three sofa
  seeds the reference's blue appears strongly (7), not at all — the sofa comes
  out cream (42) — and only in the cushions (123). Shape is generic throughout.
- The bed row looks consistent, but that consistency proves little: a plain
  white bed is close to what SD 1.5 produces unprompted, so it cannot be
  distinguished from the adapter having no effect.

So the accepted cost is **larger and less predictable** than "the shape stays
generic". It is closer to: *the room is reliable, the item is a suggestion, and
even its colour may not carry.* That is the trade being made knowingly, not a
defect to be tuned away — raising the scale trades it straight back for
product shots.

### The real backstop is the human review step, not this number

No value of `reference_scale` makes the render resemble a specific piece
reliably enough to show a client unchecked, and picking one is not an attempt
to. The product already routes the moodboard through a **human quality review**
before it reaches the client, and that step — not the parameter — is what
catches "this doesn't look like their sofa". A reviewer can re-run with another
seed, choose a different reference photo, or drop the scene image entirely; the
moodboard is designed to work without it.

Recorded here so that a future reader tuning this number knows what it is and
is not responsible for. If shape fidelity ever has to be guaranteed rather than
reviewed, the answer is a different mechanism (ControlNet on the item's
silhouette, or compositing the actual asset), not a higher scale.

### Revisit if

The model changes (SD 1.5 → SDXL or a fine-tune), the render stops being the
first frame of a walkthrough, or the human review step is removed.

---

## 2. A photo is named by its upload id, never by its position

### Decision

`SpottedObject.image_ref` holds the **upload's `input_id`**, and every consumer
resolves through `InputBundle.photo_for(item)`. `SpottedObject.image_index` is
retained only to read analyses written before this change, and
`ObjectPlanItem.spotted_index` is not to be resolved against a stored analysis
at all.

### Why

The model can only answer in positions — "the sofa is in photo 3" — so the
reading arrives positional. The mistake was *storing* it that way. An index into
a mutable collection is correct at the instant it is taken and wrong forever
afterwards: delete one upload and every later index slides down one.

This is not hypothetical. It was found live in `proj_553cb09794`, where four
uploads had been removed through the (new) delete-photo UI after the analysis
ran. Verified afterwards by re-cutting each stored crop's bounding box from the
photo its recorded index now points at: **all six items resolved to a different
photograph** than the one they were actually read from. The correct mapping was
recovered by matching each stored crop against every upload (exact, mean pixel
difference 0.0) and backfilled onto that project's analysis.

Two consumers were affected, and both failed silently, which is the part that
mattered:

| Consumer | Silent failure |
|---|---|
| `crops.write_crops` | cuts the texture for an object out of an unrelated photo; that crop then textures the object and seeds image-to-3D |
| `analyze._scene_reference` | conditions the moodboard render on the wrong photo — or, when the index falls out of range, on **nothing at all**, because `_open_references` skipped unreadable paths and generation carried on unconditioned |

The second is the same shape as the mock-provider fallback this codebase
already ruled against: a degraded result that is indistinguishable from a good
one. An unconditioned render is a perfectly attractive photograph of somebody
else's room, reported as success.

### What changed

- `ReferenceImage.input_id` carries the upload's own id into the bundle.
- `coerce_analysis` converts position → id **at coercion time**, while the
  bundle the model was shown is still the one in hand. This is the only place
  the position is trusted.
- `InputBundle.photo_for()` is the single resolver. It returns `None` when the
  photo is gone; callers must treat that as a condition, not a fallback.
- `MoodboardSpec.reference_resolved` / `.reference_note` record whether the
  scene actually saw one of the client's photos. Shown in the analysis review
  UI, stored on the `moodboard_scene` output, and logged at warning level. A
  render still happens — a generic room beats no moodboard — it just stops
  claiming to be theirs.
- `local_image._open_references` raises when references were requested and none
  could be read, instead of dropping through to plain text-to-image.
- `tests/test_reference_stability.py` simulates deleting a photo after the
  reading and asserts the correct photo is still resolved, or the failure is
  visible.

### Known remaining instance, deliberately left

`ObjectPlanItem.spotted_index` is a position into `analysis.spotted_objects`
with the same staleness property. It is left alone because **nothing reads it
back**: it is written, carried through the planner prompt so items are not
dropped, and then discarded. Fixing it properly means giving `SpottedObject` a
stable id, which is worth doing the day something needs to resolve it — and not
before. The field carries a comment saying so.

### Revisit if

Anything starts resolving `spotted_index` against a stored analysis, or uploads
gain a replace-in-place operation (which changes a photo's content under a
stable id — an id survives that, so `photo_for` would return the *new* image for
an old reading; the reading would need re-running).

---

## 3. The moodboard frame is landscape, and the prompt names the furniture

### Decision

`scene_image_width = 704`, `scene_image_height = 448` (replacing a single square
`scene_image_px = 512`), and `scene_prompt_sd` now names the room's expected
furniture and pushes explicitly against close-up framing.

### Why

Section 1 got the render to *read as a room*, but "a room" was still often one
sofa with a wall behind it. A moodboard has to show the **space** — seating,
table, rug, light, two walls — because that is what the client is being asked
to approve before anything is built.

Three causes, in order of how much they mattered:

1. **The frame was square.** This was the biggest single factor and the least
   obvious. A 1:1 canvas invites the model to centre one object and fill it.
   Measured across three seeds with the prompt and seed held constant, every
   512x512 render came back sofa-dominant, while 704x448 gave a furnished room
   — seating, coffee table, rug, curtains, two walls — in all three. Interior
   photography is landscape; the frame had been fighting the prompt.
2. **The prompt named no furniture at all.** It described style, materials,
   light and framing, and left what was *in* the room entirely to the model.
   It now names the room's essentials, taken from `ROOM_SETS` — the same
   per-room, per-vertical set the rule-based planner lays out — so the
   moodboard promises a room the later stages can actually build. Pieces the
   reading actually saw are listed first. Capped at five: CLIP truncates at 77
   tokens, and a longer list costs the framing words at the end of the prompt.
   Measured at 70/77 (living room) and 69/77 (bedroom).
3. **The negative prompt did not name the failure.** `close-up, product photo,
   single piece of furniture, furniture catalogue shot` push from the other
   side while the furniture list pulls.

The underlying tension is worth stating: IP-Adapter carries the reference
photo's *composition* as well as its object, and the references are usually
close-up shots of a single piece. Everything above is a counterweight to that.
It is the same tradeoff as section 1, applied to framing rather than fidelity.

### Evidence

Three moodboards generated through `_add_scene_image` on the shipped settings:
all three show multiple pieces in a real space — sofa with armchair or second
sofa, coffee table or ottoman, rug, media unit or floor lamp, windows,
curtains, two walls. Before the change, the same project's board was a
frame-filling close-up of one sofa with a sliver of wall.

Not every render is equally wide — one of the three sits low, with the rug
taking a third of the frame. The human review step (section 1) covers that:
re-running is cheap and free.

### Cost

704x448 is ~20% more pixels than 512x512 and still renders in ~28 s on a 6 GB
card alongside Blender and Ollama. Both dimensions must stay multiples of 64.

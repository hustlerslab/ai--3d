# ADR-004 — Styling known geometry: position solved, appearance not

**Status:** probe complete, not adopted · 2026-09-14 · extends ADR-003 §9
**Applies to:** nothing in `app/`. The code lives in `aether-backend/research/`
and the shipped pipeline is unchanged.

> **The question.** Every attempt to get object *positions* out of a generated
> moodboard had failed, because a render has no fixed orientation against the
> floor plan: the reader answers "back wall", "left wall", and those name no
> real wall (ADR-003 §9). So invert it — take the layout from the planner,
> which is already validated and collision-checked, render that geometry, and
> let generation style it. Position would then be correct *by construction*
> rather than something to recover afterwards.

This records what the probe measured, and why it was not adopted.

---

## 1. What was built, and what it cost

### Analytic depth, from the planner rather than from a renderer

Conditioning needs a depth map. Two usual routes were rejected on evidence:

* **Blender's Z pass.** Blender 5.2 removed `CompositorNodeComposite`, moved
  the compositor to `scene.compositing_node_group`, and its `OutputFile` writes
  EXR only. A whole-scene material override — proven to apply, with a
  red-emission test — rendered flat white through both `View Z Depth` and
  `View Distance`. Four attempts, no usable depth. Abandoned rather than
  debugged further, deliberately: it was consuming a probe's whole budget.
* **A depth estimator (MiDaS/DPT) over a render.** Another model to download,
  and it would only be *guessing* at depth that is already known exactly.

Instead, `research/depth_from_scene.py` projects the planner's own geometry —
the room boundary, and every object's position, size and yaw — through a known
camera by ray/box intersection. **0.9 s end to end**, no renderer, no estimator,
using the most trustworthy data in the pipeline.

### Camera framing, computed and then checked

The first run of this probe used a hand-picked look-at, framed a blank corner,
and spent a render proving nothing. The camera is now derived from the subject
(largest piece in the room, standoff from the lens' field of view, clamped
inside the room) and then **verified before anything is spent**: all eight
corners of the subject's bounding box are projected, and the probe refuses
unless all eight are in frame and the piece fills at least 10 %.

On the sample living room: `8/8 corners in frame, fills 14%`.

### Measured cost

6 GB RTX 3050, 704 × 448, 28 steps:

| | time | per step | peak VRAM |
|---|---|---|---|
| plain SD (today's moodboard) | 14.7 s | 525 ms | 2,599 MB |
| **ControlNet, scale 1.0** | **21.0 s** | **751 ms** | **3,539 MB** |
| ControlNet, scale 0.6 | 19.3 s | 690 ms | 3,539 MB |
| analytic depth | 0.9 s | — | — |

**+43 % wall clock**, ~3.5 GB of 6 GB. No new library — the installed diffusers
already carries the pipeline classes; only 1.4 GB of weights. Attention slicing
works here, unlike the IP-Adapter path this would replace.

---

## 2. What it settles

**Position and structure transfer, convincingly.** The generated image put the
wall corner where the geometry put it, the floor plane and horizon where the
camera put them, and the sofa at the right place, the right size, in the right
part of the frame. The premise held: conditioning on known geometry takes
position off the list of things that must be recovered from a picture.

**Appearance does not transfer, and that is architectural.** The approved
moodboard shows a striped green-and-blue sofa with a blue seat cushion. The
generated image put a plain teal upholstered block in exactly the right spot. A
depth map carries *volume*, not *identity*: the model is told where mass sits
and paints something plausible filling it. `controlnet_conditioning_scale`
trades one failure for another rather than fixing it — at 0.6 the model drifts
further and invents a rug and curtains, at 1.0 it hugs the box and renders it as
a featureless slab.

**This is the same wall as ADR-003 §9, reached from the opposite direction.**
There, Meshy's image-to-3D produced a side table with a lower shelf that does
not exist in the source crop — geometry completed plausibly, not faithfully.
Here, generation completes appearance plausibly, not faithfully. Two
independent methods, one finding: **the room can be made structurally correct,
and the furniture cannot yet be made to be the client's furniture.** These are
not two problems to solve separately, and neither is a tuning issue.

---

## 3. Considered and not pursued: mesh silhouettes instead of boxes

The depth map rasterises oriented bounding *boxes*, so ControlNet sees a cuboid
and paints a cuboid. Conditioning on real mesh silhouettes would hand it a
sofa-shaped signal instead.

Not pursued, because it aims at the wrong target. Silhouettes would sharpen
**shape fidelity**, which already works — the box is in the right place at the
right size, and the output honours it. They would not touch **appearance
fidelity** — the fabric, the colour, the specific piece — which is the actual
ceiling. It would buy a better answer to a question that is not the one
blocking this.

---

## Consequences

- **The pipeline is unchanged.** Nothing in `app/` uses ControlNet, and the
  moodboard step works exactly as ADR-002 describes.
- The analytic depth map is kept in `research/` because it is real, reusable
  value on its own: no renderer, no estimator, no model, derived from data the
  planner already proves. Anything that later needs to know what a camera sees
  of a planned room starts there.
- **The product question is now cross-validated, not hypothetical.** Whether a
  room that is correctly laid out but furnished with plausible strangers'
  furniture satisfies "see your actual space" is a founder decision. ADR-003 §9
  and this probe point at the same one, reached twice by different routes.
- If it is ever taken up, the honest framing is a **styling pass over a built
  room**, not a moodboard: the client would approve the layout first and the
  finish second, which inverts today's flow where they approve a picture and
  the room is built from it.

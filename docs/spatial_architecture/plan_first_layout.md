# Plan-first layout: can the model design the room?

*Research report · 2026-09-19 · ~45 sources across two parallel searches*

Written for: whoever decides the next architecture phase on this repo.

## The proposal

Invert the pipeline. Instead of generating a moodboard **image** and reading
furniture positions back out of it, have the model **plan** the layout first -
which pieces, where, facing which way - iterate until it is good, and only then
generate imagery. The plan then drives asset allocation and orientation.

## Verdict

| Part of the proposal | Verdict |
|---|---|
| Plan first, derive imagery from the plan | **Strongly supported.** Every SOTA system does this. |
| Plan drives asset selection and orientation | **Supported.** Orientation is the weakest link everywhere (~73%). |
| Model emits final metric coordinates | **Broken.** 72% out-of-bounds, measured. |
| **N iterations "until it looks good to the model"** | **Contradicted by measurement.** The gate must be code. |
| Generate the moodboard image from the plan | **Supported, partially.** Structural agreement, not pixel agreement. |

The architecture is right. Two of its five parts need a different mechanism
than the one proposed, and both replacements are things this repo already owns.

---

## 1. Why plan-first is the right inversion

Everything this session spent its time fixing exists **only because coordinates
are inferred from a picture**: the render-frame convention, the anchor
estimation, the wall-line half-depth inset, the `_prefer_hint` tie-break
ladder, the 0.53 m median offset. Author the plan instead and that entire error
class disappears - positions and orientations become **exact by construction**.

The literature agrees, and the single closest published match to this proposal
is **FlairGPT** ([2501.04648](https://arxiv.org/pdf/2501.04648)): an LLM emits
zones and constraints, an SLSQP optimiser places furniture.

| | FlairGPT | LayoutGPT | Holodeck |
|---|---|---|---|
| Out-of-bounds | **0.047** | 2.385 | 1.584 |
| Overlap | **0.186** | 5.036 | 0.891 |
| Pathway cost | **1.736** | 6.388 | 6.372 |

Human preference: over LayoutGPT **88.9%**, over ATISS **79.4%**, and over
**novice human designers 63.2%** (p < 10⁻⁶). Cost: 1.17 min LLM +
**11.29 min optimisation**.

---

## 2. The model must not be the last thing to touch the numbers

The cleanest controlled experiment is **LayoutVLM** (CVPR 2025) Table 6 - same
base model, same data, only the *output format* differs:

| Fine-tuned to emit | PSA | In-boundary |
|---|---|---|
| **Relations** | **39.5** | **70.4%** |
| Direct numeric poses | 6.8 | 18.5% |

A 32.7-point gap from representation alone. Their ablation is blunter still:
remove the optimiser's spatial constraints and in-boundary collapses
94.9% → **14.1%**. The model's raw numbers are near-useless; the solver carries
the result.

**SceneEval** ([2503.14756](https://arxiv.org/html/2503.14756v3)), independent
third-party benchmark, 500 prompts:

| Method | Collision | Support | Accessibility | Out-of-bounds |
|---|---|---|---|---|
| LayoutGPT (direct coords) | 11.46% | 30.13% | 47.26% | **72.25%** |
| LayoutVLM (constraints+solver) | 32.13% | 76.90% | 85.19% | 4.89% |
| Holodeck (constraints+solver) | 15.91% | 63.21% | 89.65% | **1.44%** |

**Design rule:** the model emits *relations, zones and a rough anchor*; a solver
produces metres.

### The counter-evidence worth knowing

*Imperative vs. Declarative Programming Paradigms for Open-Universe Scene
Generation* ([2504.05482](https://arxiv.org/abs/2504.05482)) argues the solver
need not be a solver: having the LLM write **imperative placement code** (each
pose computed from already-placed objects) plus a **programmatic
error-correction pass** beat the declarative baseline 82.86% and Holodeck
94.29%. Overlap errors 10.76 → **0.56** with error correction; coordination
errors 17.57 → **2.10**.

Read both results the same way: *whether* the fixer is SLSQP, MILP, gradient
descent, or a deterministic correction pass matters less than *that it exists
and is programmatic*.

---

## 3. "Iterate until the model likes it" is the one part that fails

This is the part of the proposal that measurement contradicts, and the numbers
are severe.

**Self-correction degrades reasoning.** *LLMs Cannot Self-Correct Reasoning Yet*
(ICLR 2024, [2310.01798](https://arxiv.org/pdf/2310.01798)): GPT-4 on GSM8K
**95.5% → 91.5% → 89.0%** across two rounds of intrinsic self-critique. The
model flips correct→incorrect more often than the reverse.

**For spatial layout specifically it is worse.** *SceneCritic*
([2604.13035](https://arxiv.org/html/2604.13035)), against 594 human judgments
from 16 annotators:

| Critic | Easy scenes | Complex scenes |
|---|---|---|
| Symbolic checker | **94.44%** | **83.33%** |
| VLM judge (Gemini) | 58.82% | **47.06%** |

At 47% the judge is a coin flip. Re-scoring the **identical top-view image**
varied by **12.46-19.32 points**; per-view overlap score varied by up to **28.1
points**, and mirrored left/right views scored asymmetrically - the evaluator is
"reacting to 2D visual appearance rather than extracting 3D spatial
relationships". Most damning: symbolic overlap detection achieves **100% human
agreement**, while the VLM's *largest* disagreements are on overlap - the most
visually obvious error there is. **It cannot see collisions in a render.**

**This repo measured the same thing independently.** The first version of
`research/placement_loop.py` asked Gemini to name what it saw in four corner
renders. The same unchanged scene scored **0.556, 0.778, 0.556, 0.556** - a
22-point spread - while reporting a dining table in all four views of a living
room that has none. That is SceneCritic's finding, reproduced here before the
paper was read.

### What the working systems gate on instead

1. **Symbolic geometric checks.** *Agentic Designer* returns a 4-bit boolean
   vector (boundary intrusion / boundary violation / collision / orientation
   misalignment), never prose. Violation rate **16.85% @1 round → 10.04% @2 →
   8.43% @4** - converges fast, **saturates by round 2**, no oscillation.
2. **Physics simulation.** *SceneWeaver* reaches collisions 0.0 / OOB 0.0 by
   simulating, using VLM scores only for *aesthetic* dimensions on top of a
   physical gate.
3. **Numeric solvers.** LayoutVLM, FlairGPT, Co-Layout (Gurobi IP: overlap
   0.00%, OOB 0.00%).

*Scenethesis* isolates exactly what the gate is worth, same LLM plan throughout:

| | collision | instability |
|---|---|---|
| raw LLM layout | 22.7% | 87.3% |
| + pose alignment | 10.6% | 74.2% |
| + collision constraint | 3.6% | 69.8% |
| + stability constraint | **0.8%** | **3.2%** |

**One narrow exception.** For **orientation** specifically, image-based critique
does help: SceneCritic measured 43.70 (heuristic) → 50.7 (LLM text) → **55.8
(image-based)**. So a render-based critic has one legitimate job - "is the sofa
facing the wrong way" - and no business judging collision, clearance or metric
fit.

**Concrete rule: budget 2 rounds, hard-cap 4, terminate on the checker.**

---

## 4. This repo already owns the checker

The literature's non-negotiable component is a symbolic gate. `app/spatial/`
already contains `clearance_engine.py`, `collision_solver.py`,
`repair_engine.py`, `validation.py` and `scene_consistency.py`, with real
encoded constants:

```python
PRIMARY_WALKWAY_MIN_M   = 0.90     # clearance_engine.py
SECONDARY_WALKWAY_MIN_M = 0.65
PEDESTRIAN_INFLATION_M  = 0.275
DOOR_CLEARANCE_DEPTH    = 0.75     # validation.py
```

`PRIMARY_WALKWAY_MIN_M = 0.90` matches the sourced trade and code standard
almost exactly - IRC R311.6 hallway minimum is **0.914 m**, and Merrell's person
disk is **radius 0.457 m**, i.e. a 0.914 m diameter. `PEDESTRIAN_INFLATION_M =
0.275` is within a centimetre of half of Neufert's standing body width
(0.625 m).

**So this is a rewiring, not a rebuild.** The gate exists and already runs on
every plan. What changes is where coordinates come from: today they are inferred
from a picture and the validator cleans up afterwards; in the new shape they are
authored as relations, solved into metres, and the same validator becomes the
loop's termination signal.

---

## 5. The rules worth encoding

### Merrell et al. SIGGRAPH 2011, Table 1 — the spine
The only published table that is both attributed to real anthropometrics
(Panero & Repetto 1975) and already in clearance-direction + distance form.

| Constraint | Distance | Direction |
|---|---|---|
| Bedside | **0.914 m** | to the side |
| Seat | **0.762 m** | in front |
| Cabinets / shelving | **0.610 m** | in front |
| Dining table | **0.914 m** | all around |
| Coffee table to seat | **0.406-0.457 m** | in front of seat |
| End table to seat | **0-0.305 m** | back or side |
| Nightstand to bed | **0-0.305 m** | to the side |

### Other sourced constants

- **Person disk for navigability: radius 0.457 m.** Free space
  `C_free = ∩(g ⊕ P)ᶜ`; circulation score = **number of connected components**
  of `C_free`, minimum 1. That is the correct formulation of "you can walk
  everywhere" - a topology test, not a heuristic.
- **Neufert passage widths:** one person walking **0.875 m**; two passing
  **1.375 m**; three abreast **1.75 m**; +10% for moving persons.
- **Code floors:** hallway ≥ **0.914 m** (IRC R311.6); egress door clear width
  ≥ **0.813 m** (IRC R311.2).
- **ADA:** clear floor space **0.76 × 1.22 m**; turning circle **1.524 m**.
- **NKBA kitchen:** work-triangle legs **1.22-2.74 m**, sum ≤ **7.92 m**; work
  aisle **1.067 m** one cook / **1.219 m** multiple; walk behind a seated diner
  **1.118 m**.
- **TV viewing distance** (a genuine standard, trivially encodable). 16:9
  width = 0.872 × diagonal. **SMPTE 30°: d ≈ 1.60 × diagonal. THX 36°:
  d ≈ 1.20 × diagonal.**
- **Conversation distance: 1.22-2.44 m pairwise seat separation** (Panero, via
  Merrell). Encode pairwise distance, *not* a "conversation circle" - no
  published circle diameter exists.
- **`against_wall` 0.3 m ± 0.1; `on_wall` 0.01 m** (SceneEval thresholds).

### Computable soft terms (all from published cost functions)

- **Conversation angle:** `−Σ q_fg (cos θ_fg + 1)(cos θ_gf + 1)` - maximised
  when seats face each other.
- **Alignment:** `−Σ cos(4(θ(f) − θ(g)))`. The `cos(4Δθ)` form peaks at 0/90/
  180/270° with no extra logic - use it for wall alignment too.
- **Visual balance:** distance from the area-weighted furniture centroid to the
  room centroid. OID-PPO improves on it by adding a second-moment term so even
  *spread* is rewarded, not just a centred mean.
- **Focal point:** `−Σ cos θ_gp` where p is the fireplace/TV/window.
- **Visibility / accessibility (Yu et al.):** attach a viewing frustum or an
  accessible-space rectangle set, penalise intrusion
  `Σ max(0, 1 − ‖p_i − v_jk‖ / (b_i + v^d_jk))`.

### The finding that matters most here

**Yu et al. "Make it Home" publishes its weights**, and they are lopsided:

```
w_a (accessibility) = 0.1      w_v (visibility) = 0.01
w_path = 0.1                   w_pdr = w^d_pair = 1.0-5.0
w_pθr = w^θ_pair = 10.0        <- orientation terms
```

**Orientation is weighted 100x accessibility and 1000x visibility.** Getting
pieces pointing the right way matters far more to perceived realism than
clearance does. That is empirically derived, and it is exactly what the client
has been reporting about this build for three rounds. Their complaint was
correct and well-calibrated.

---

## 6. Generating the image from the plan

Supported, but agreement is structural rather than exact.

**ControlNet++** measures how far output actually matches its conditioning:
segmentation **mIoU 32.55** for stock ControlNet (43.64 for ControlNet++), vs
50.7 on real datasets. Sofas move, merge and get reinterpreted.

**Do not condition on primitive boxes.** *When ControlNet Meets Inexplicit
Masks* ([2403.00467](https://arxiv.org/pdf/2403.00467)) shows ControlNet has a
strong contour-following prior: feed it a crude box and it **renders the box as
an object** - a rectangle becomes a door or a board - faithfully reproducing the
wrong contour (Contour-Recall stays >60% while CLIP −1.35, FID +8.62).

**Recommended shape:** place real assets from the plan → render **depth +
semantic segmentation + a clay pass** from the same camera → multi-ControlNet
(depth + seg) with img2img over the clay at **denoise ≈ 0.3**. The 3D render is
the source of truth; diffusion is restyling, not generation.

Interior-specific precedents: **Ctrl-Room** (ICCV 2025) generates a 3D box
layout then projects it to a semantic panorama for ControlNet (FID 21.02);
**Top2Pano** goes top-down floor plan → panorama, FID **30.84 / 28.68** vs
85.78 / 85.74 for baselines - a ~65% improvement, and literally the plan → image
step proposed here.

---

## 7. Reality checks before anyone promises anything

- **Matching a human designer on plain rooms has been solved since 2011.**
  Henderson et al. ([1711.10939](https://arxiv.org/pdf/1711.10939)), 1400 image
  pairs: overhead views **48.1 ± 6.6%** preference - statistically
  indistinguishable from human-designed. First-person views **58.1 ± 6.0%** -
  users mildly *preferred* the generated layouts.
- **The gap is exactly where this build already hurts.** In the same study,
  once **door and window positions are fixed**, preference drops to
  **35.2 ± 5.4%** - humans clearly win. That is precisely the failure diagnosed
  this session: `layout.py` invented a window on the wall the moodboard had
  given to the television. Constrained, real floor plans are where automatic
  layout is still weak, and where hard door-swing, circulation and
  window-occlusion constraints earn their keep.
- **Even the leaders are bad at honouring a brief.** Holodeck, the SceneEval
  leader, satisfies **11.52%** of stated object-object spatial relations and
  **28.49%** of attribute requirements. OptiScene's usability success is **30%
  for kitchens**. Do not promise that a client's detailed spatial brief will be
  respected.
- **Never report collision rate alone.** LayoutGPT posts the *best* collision
  number (11.46%) precisely because it throws **72.25%** of objects out of the
  room. Any scorer must publish collision *jointly* with out-of-bounds, or an
  optimiser will find the same degenerate escape.
- **Do not target zero overlap.** Ground-truth 3D-FRONT bedrooms have pairwise
  box IoU **0.43** - real human layouts have chairs tucked under tables and
  nightstands touching beds. Target the GT value for distribution terms; reserve
  hard zero for true interpenetration.

---

## Suggested shape, if this is built

1. **Model emits a constraint program**, not coordinates: zones, ranked
   objects, pairwise relations, a focal point per group, a rough anchor.
2. **Solver produces metres.** Start with the existing repair/collision engines
   over Merrell's term list; the FlairGPT phase order (primary → secondary per
   zone → tertiary) is a good default.
3. **Score with `app/spatial/`**, extended with the Merrell/Yu terms above.
   Report per-rule scores normalised to [−1, 1] (OID-PPO's contribution) so a
   client can be shown *which* rule a layout fails.
4. **Loop on the checker. 2 rounds, cap 4.** A render-based critic may vote on
   facing and style only.
5. **Weight orientation heavily** - Yu's 10.0 vs 0.1 is the measured guidance.
6. **Render the plan, then restyle it** with depth+seg ControlNet at low
   denoise. Never generate from boxes.
7. **Regression-test with SceneEval's metric suite** (COL / SUP / NAV / ACC /
   OOB), reporting collision and OOB together.

## Sources

Layout generation: [FlairGPT](https://arxiv.org/pdf/2501.04648) ·
[LayoutVLM](https://arxiv.org/abs/2412.02193) ·
[Holodeck](https://arxiv.org/pdf/2312.09067) ·
[LayoutGPT](https://proceedings.neurips.cc/paper_files/paper/2023/file/3a7f9e485845dac27423375c934cb4db-Paper-Conference.pdf) ·
[I-Design](https://arxiv.org/abs/2404.02838) ·
[SceneCraft](https://arxiv.org/abs/2403.01248) ·
[DirectLayout](https://arxiv.org/abs/2506.05341) ·
[OptiScene](https://arxiv.org/pdf/2506.07570) ·
[Scenethesis](https://arxiv.org/pdf/2505.02836) ·
[SceneWeaver](https://arxiv.org/pdf/2509.20414) ·
[Co-Layout](https://arxiv.org/pdf/2511.12474) ·
[Imperative vs Declarative](https://arxiv.org/abs/2504.05482)

Self-critique: [LLMs Cannot Self-Correct Reasoning Yet](https://arxiv.org/pdf/2310.01798) ·
[SceneCritic](https://arxiv.org/html/2604.13035) ·
[JudgeGPT](https://arxiv.org/html/2503.23707) ·
[MetaSpatial](https://arxiv.org/pdf/2503.18470)

Design rules: [Merrell et al. 2011](http://graphics.berkeley.edu/papers/Merrell-IFL-2011-08/Merrell-IFL-2011-08.pdf) ·
[Yu et al. Make it Home](https://www.saikit.org/static/projects/furniture/pdf/furniture.pdf) ·
[OID-PPO](https://arxiv.org/html/2508.00364v1) ·
[Neufert Architects' Data](https://www.uceb.eu/DATA/CivBook/03.%20Architect_s%20Data.pdf) ·
[US Access Board Ch.3](https://www.access-board.gov/ada/guides/chapter-3-clear-floor-or-ground-space-and-turning-space/) ·
[IRC R311.2](https://codes.iccsafe.org/s/IRC2021P2/chapter-3-building-planning/IRC2021P2-Pt03-Ch03-SecR311.2) ·
[SMPTE/THX viewing distance](https://theatercalc.com/guides/screen-size-by-viewing-distance)

Evaluation: [SceneEval](https://arxiv.org/html/2503.14756v3) ·
[DiffuScene](https://arxiv.org/pdf/2303.14207) ·
[PhyScene](https://arxiv.org/pdf/2404.09465) ·
[Henderson et al.](https://arxiv.org/pdf/1711.10939)

Image conditioning: [ControlNet++](https://arxiv.org/pdf/2404.07987) ·
[Inexplicit Masks](https://arxiv.org/pdf/2403.00467) ·
[Ctrl-Room](https://arxiv.org/html/2310.03602v1) ·
[Top2Pano](https://arxiv.org/pdf/2507.21371)

## Rules with no authority behind them

Do not present these as standards; encode them as tunable preferences.
The 18-inch rug border; "front legs on the rug"; artwork centre at 57 in
(institutions actually use 57-60 in, no primary museum document found); TV
centre at 42 in (SMPTE publishes viewing *angles*, not mounting heights -
compute from seat height instead); any "conversation circle diameter";
secondary walkways at 24-30 in; and "float your furniture", which the
literature encodes the *opposite* of - Yu et al. learn a per-category
distance-to-nearest-wall prior from real examples.

## Not measured

Nothing here has been built or run against this repo. Every number is from the
cited work. The one measurement that *is* local is the VLM-judge instability
reproduced in §3, from this session's own `placement_loop.py` runs.

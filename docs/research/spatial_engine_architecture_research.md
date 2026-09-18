# Allure Spatial Engine — Architecture Research

**Status:** research and architecture selection. No production code changed, no model trained,
no dependency installed.
**Date:** 2026-09-15
**Companion:** `docs/research/spatial_engine_decision.md` (short executive version)

### Provenance convention, used throughout

Every factual claim carries one of these markers. This document is a basis for spending
engineering months; the difference between "we measured this" and "I recall this" has to be
visible on every line.

| Marker | Meaning |
|---|---|
| **[M]** | **Measured by us**, in `docs/benchmarks/phase_*`. Reproducible from this repo. |
| **[V]** | **Verified this session** against a primary source or repository, cited in §25. |
| **[B]** | **Background knowledge, not re-verified.** Treat as a lead, not a number to plan against. |

Where a number would change a decision and I could not verify it, it is absent rather than
estimated. There are several such gaps and they are named.

---

## 1. Executive summary

Allure's spatial problem is not a perception problem. It is a **representation and
delegation** problem, and we have eight phases of our own measurements proving it.

Across Phases 1c–1h we asked a vision-language model to supply geometric relations —
"is this against a wall", "what does it face", "what supports it" — in every formulation
available: bulk reading, isolated queries, closed candidate lists, schema-enumerated
answers, binary decomposition, and a 2.3× larger model. The results **[M]**:

- Forced-choice relation selection: the model returned an object **78 times out of 78**
  when `wall`, `window`, `open_room` and `unknown` were all on offer. `AGAINST` scored
  **0 / 30**.
- Binary decomposition: the wall gate returned `true` **16 / 16** — a constant function.
- Against the existing deterministic rules, the whole binary chain scored **48.6% vs 57.1%**
  — the model was *worse than the rules it would replace*, with twice as many regressions
  as improvements.
- `SUPPORTED_BY`: deterministic vocabulary **88.9%**, model **33.3%**, with **zero** cases
  where the model added value and **five** where it destroyed value.
- 7B on a properly balanced 32-object dataset: false-wall **14.1% [7.6, 24.6]** — the best
  number we have, still a 1-in-7 error rate on the single most consequential spatial fact,
  and measured on generated imagery that is probably easier than production input.

Meanwhile the same model is *excellent* at the thing it is actually for: semantic identity,
material, colour, style — and **100% JSON reliability across every phase since 1c** **[M]**.

The conclusion is not "use a bigger VLM". It is: **stop asking a language model questions
that are arithmetic.** "Is the sofa against a wall" is not a judgement call once you have a
floor plane, wall planes and an object footprint in metric space — it is a distance
comparison, deterministic and auditable.

**The recommended architecture is therefore geometry-first:** reconstruct the room's metric
structure from the image with a feed-forward geometry model, fit floor and wall planes,
ground detected objects into that frame, express everything in a geometrically-grounded 3D
scene graph, and let a constraint solver — not a model — decide final pose. The VLM is
demoted to what it is good at: naming things and describing style.

This is **Architecture B**, specified in §16 and selected in §17.

The single highest-value next experiment is defined in §20 and is unusually cheap: we
already own a 43-case wall-contact benchmark with hand-verified ground truth (Phase 1g/1h).
Computing wall contact *geometrically* on that exact dataset and comparing against the
measured 14.1% is a direct, same-data, same-ground-truth head-to-head. It needs no
training, no new annotation, and about a day.

---

## 2. Problem definition

From a reference image (plus, increasingly, a floor plan, dimensions and text), the system
must produce a **physically coherent Blender scene**. Concretely it must determine:

| Quantity | Nature | Currently from |
|---|---|---|
| What objects exist | semantic | VLM **[M]** — works |
| Object identity, material, colour, style | semantic | VLM **[M]** — works |
| Where they are in the image | 2D geometric | Grounding DINO **[M]** — works, benchmark-only |
| Approximate size | metric | vocab defaults — crude |
| Orientation | geometric | VLM **[M]** — **fails** |
| Depth | metric | nothing |
| Room boundaries | metric | assumed rectangle from brief |
| Wall relationships | geometric | VLM **[M]** — **fails** |
| Floor / support | geometric | deterministic vocab **[M]** — **works well** |
| Object–object relations | geometric | VLM **[M]** — **fails** |
| Collision, clearance | geometric | compiler SAT polygons — works |
| Grouping, functional plausibility | mixed | partial |
| Final XYZ, rotation, scale | geometric | compiler — works, but starved of evidence |

**The governing principle, restated because every decision below follows from it:**

> The AI model provides **evidence**. The geometry system determines **placement**.
> No model is ever asked to emit XYZ.

The failure mode we are designing against is not "the model is wrong sometimes". It is
"the model is confidently wrong in a way nothing downstream can detect". Phase 1c measured
exactly this: the model reported `"high"` confidence on **56 of 78** answers, including most
of the wrong ones **[M]**. A model's own confidence is not a usable filter. Geometry, by
contrast, fails loudly — a plane fit either converges with acceptable inlier support or it
does not.

---

## 3. What we learned from the existing Allure experiments

This section is the most reliable evidence in the document, because we generated it.

### 3.1 Semantic vs geometric competence is cleanly separated **[M]**

Phase 0b/0d measured Grounding DINO against Qwen on the same images:

| | Grounding DINO | qwen2.5vl:3b |
|---|---|---|
| Recall | ~0.75 | lower |
| Matched IoU | ~0.680 | substantially weaker |
| Detection × geometry | ~0.510 | — |
| Median centre error | **1.29% of image diagonal** | — |
| Failure modes | misses small/thin objects | **boxes outside valid image range**, repetition, truncation |

Qwen was *better at semantics* — naming an unusual piece, reading material and colour.
DINO was decisively better at *where*. The hybrid intersection beat either alone.

**Implication:** the split is not a compromise, it is the correct factorisation.

### 3.2 The VLM cannot decline **[M]**

This is the deepest finding of the whole programme and it recurs at every model size.

- Phase 1c: 78/78 forced-choice answers named an object. `wall`, `window`, `open_room`,
  `unknown` were in the schema enum *and* the prompt text, every time. Never chosen once.
- Phase 1d: the binary wall gate answered `true` on all 16 cases — TN = 0.
- Phase 1e: 3B produced **TN = 0 across 32 observations**. 7B produced TN = 5 — the first
  non-zero abstention in the programme.
- Phase 1d's orientation gate reached **66.7% NO-recall** — the only gate where the model
  reliably declined, and notably the only one asking about the *object itself* rather than
  its relation to the room.

**Implication:** any architecture that requires the model to answer "no relation exists
here" is building on the model's weakest axis. Geometry answers that question for free: no
plane within threshold means no wall contact, with no willingness required.

### 3.3 Deterministic rules already beat the model **[M]**

Phase 1d compared the binary chain against the existing engine on the same cases:

| Relation | Deterministic | Qwen chain | AI adds value | AI worse |
|---|--:|--:|--:|--:|
| AGAINST_WALL | 68.8% | 68.8% | **0** | **0** |
| FACES | 10.0% | **30.0%** | **3** | 1 |
| SUPPORTED_BY | **88.9%** | 33.3% | **0** | **5** |
| **Total** | **57.1%** | 48.6% | **3** | **6** |

Three things to read off this table:

1. **AGAINST_WALL is identical because both are the same constant.** The rules always say
   "against a wall"; the model always says "against a wall". Two systems producing one
   constant. There is nothing to integrate and nothing gained.
2. **FACES is the only place a model beats the rules** (+2 net), and it does so because the
   compiler has no orientation prior at all — anything correct is new information. Notably,
   two of the three wins came from the model *declining* (correctly saying a side table and
   a coffee table have no front).
3. **SUPPORTED_BY belongs to the rules, permanently.** `SUPPORT_PREFERENCE` /
   `SURFACE_HEIGHT` / `PLACEMENT_BY_TYPE` already encode it, and the model actively
   destroyed five correct placements.

### 3.4 Query budget: the queries worth asking are the ones it gets wrong **[M]**

Phase 1d Strategy C selected exactly the chains where the deterministic engine is wrong —
the only queries worth paying for. The model got **20%** of them right. The questions the
architecture cannot already answer are precisely the questions this model cannot answer
either. This is the single most damning result for the "VLM as spatial oracle" design.

### 3.5 Reliability and latency were never the problem **[M]**

100% valid JSON in every phase from 1c onward (78, 54, 64, 32, 86 queries respectively).
Zero generation-guard triggers after the Phase 0f work. Median latency 0.23 s (3B) to
0.94 s (7B). Projected room cost 0.7–3.3 s against a 60 s budget.

**Implication:** we have spare inference budget. An architecture that runs *several* models
per room is affordable. What we lack is not throughput, it is correct evidence.

### 3.6 The hardware ceiling is real and measured **[M]**

| Model | Total | VRAM | CPU spill | On GPU |
|---|--:|--:|--:|--:|
| `qwen2.5vl:3b` Q4_K_M | 2.90 GB | 2.90 GB | 0 | **100%** |
| `qwen2.5vl:7b` Q4_K_M | 6.17 GB | 3.47 GB | **2.70 GB** | **56.3%** |

Reproduced to the decimal across Phases 1e, 1f and 1h. With 7B resident, system RAM ran at
93–95%. **7B cannot coexist with a Blender render on this machine.** Any architecture that
needs 7B in the loop is a cloud architecture, not a laptop one.

Note also **[M]**: SD 1.5 at 704×448 generates in ~15 s warm on the same card, so the
*existing* moodboard generator is affordable locally. The budget is spent on diffusion, not
on language models.

### 3.7 A methodological lesson worth institutionalising **[M]**

Phase 1f reported Category A 0% vs Category B 58.3% and classified the failure as CONTEXT
CONFUSION — explicitly hedged as "the leading hypothesis rather than a finding" because
category was confounded with scene. Phase 1h, on 32 objects across 16 scenes with the
confound broken, measured **A 11.8% vs B 16.7%** — the 58-point gap collapsed to 4.9 and
the effect vanished.

**Implication for this programme:** single-scene or single-source evidence has repeatedly
misled us. Every benchmark in §20 is specified with scene-level independence and source
balance as first-class requirements, not afterthoughts.

---

## 4. Literature review — scope and method

I reviewed work across detection, segmentation, monocular depth and geometry, room layout,
monocular 3D grounding, 3D scene graphs, learned layout priors, and constraint-based scene
synthesis. Where a claim drives a recommendation I verified it against the primary
repository or paper this session **[V]**; those are cited in §25.

**What I could not verify and am therefore not planning against:**

- Per-model VRAM figures for VGGT, MoGe and SAM 3D Objects. None of the repositories state
  them **[V]**. §21 specifies measuring them as the first task, because 6 GB feasibility
  turns on exactly these numbers.
- Indoor-specific benchmark numbers for the newest (2026) geometry models. Several 2026
  arXiv entries surfaced in search that postdate my reliable knowledge; they are listed in
  §25 as leads to read, not as evidence.

---

## 5. Vision model comparison (detection / localisation)

| Model | Task | Open vocab | Geometric accuracy | Speed | License | Allure role |
|---|---|:--|---|---|---|---|
| **Grounding DINO** | text-prompted 2D detection | yes | **best measured for us**: matched IoU 0.680, centre error 1.29% **[M]** | transformer, slower | **Apache-2.0, commercial OK [V]** | **Primary detector** |
| Grounding DINO 1.5 | same, stronger | yes | — | — | **API-only [V]** — not self-hostable | Rejected: no local path |
| YOLO-World | real-time open-vocab | yes | comparable accuracy to GLIP/G-DINO at ~20× speed, ~5× smaller **[V]** | fastest | Ultralytics — **AGPL, check** **[B]** | Fallback if DINO too slow |
| RT-DETR / v2 / v3 | real-time closed-set | no | R50: 53.1% AP @ 108 FPS on T4 **[V]** | very fast | Apache-2.0 **[B]** | Rejected: closed vocabulary |
| DINOv2 / DINOv3 | self-supervised features | n/a | features, not boxes | — | DINOv3 license contested **[V]** | Feature backbone for matching/retrieval |
| qwen2.5vl | semantics | yes | **weak — boxes out of image range [M]** | fast | Apache-2.0 **[B]** | **Semantics only, never geometry** |

**Interior-specific concern:** thin and small objects. Our Phase 0d ground truth includes a
14-pixel-tall floating shelf; DINO recall ~0.75 **[M]** means roughly a quarter of pieces
are missed. Curtains, rugs and wall art are systematically hard. This is a known gap, not a
solved one, and §20 benchmarks it explicitly.

**Recommendation:** Grounding DINO for detection. It is the only option that is
simultaneously open-vocabulary, self-hostable, Apache-2.0 and *measured good on our own
data*.

---

## 6. Depth model comparison

This is the pivotal capability, because depth is what converts 2D evidence into 3D evidence.

| Model | Output | Metric? | Key result | License | Allure fit |
|---|---|:--|---|---|---|
| **Depth Anything V2 — Small (24.8M)** | relative depth | no | family: NYUv2 δ₁ 0.984, AbsRel 0.056 when metric-finetuned **[V]** | **Apache-2.0 [V]** | **Only commercially usable DAv2 size** |
| DAv2 Base / Large / Giant (97.5M / 335M / 1.3B) | relative | no | stronger | **CC-BY-NC-4.0 — non-commercial [V]** | **Rejected for production** |
| **UniDepth / UniDepthV2** | **metric** depth + camera | **yes** | predicts dense camera representation, no metadata needed **[V]** | check **[B]** | Strong candidate for metric scale |
| Depth Pro | metric depth + FoV | yes | sharp metric depth < 1 s **[V]** | check **[B]** | Candidate |
| **MoGe** | **affine-invariant point map** | no (scale/shift free) | CVPR'25 Oral; outperforms SOTA on point map, depth, FoV **[V]** | check **[B]** | **Strong: gives geometry, not just depth** |
| **MoGe-2** | **metric point map** | **yes** | adds metric scale + sharp detail **[V]** | check **[B]** | **Best single-image candidate** |
| VGGT-1B | cameras + depth + point maps, 1–N views | — | **CVPR 2025 Best Paper**; <1 s; works single-view though untrained for it **[V]** | **base = research-only; commercial by application [V]** | Multi-view future; licence blocks default use |

**The licensing finding is decisive and easy to miss.** The obvious choice — Depth Anything
V2 Large — is **non-commercial**. Only the 24.8M Small model is Apache-2.0 **[V]**. Any plan
that assumed DAv2-L is a commercial plan that cannot ship. Similarly VGGT's default
checkpoint is research-only **[V]**.

### Known limitations of monocular depth, and what they mean for us **[B]**

| Limitation | Consequence for Allure | Mitigation in the design |
|---|---|---|
| Scale ambiguity (relative models) | cannot place in metres | metric model (MoGe-2/UniDepth) **or** fuse the floor plan / stated room dimensions we already collect |
| Mirrors | depth reads *through* the mirror | mirrors are a `wall` placement type in our vocab — exclude from plane fitting |
| Windows / glazing | depth reads the garden | same: exclude by semantic class before fitting |
| Reflective floors | plane fit noise | RANSAC with inlier threshold; report inlier fraction as confidence |
| Occlusion | partial footprints | segmentation masks (§7) + amodal completion is out of scope; flag low-support objects |
| Long rooms, perspective | error grows with distance | weight evidence by depth; report per-object geometric confidence |

**Crucially, every one of these fails *detectably*** — a plane fit reports its inlier
fraction, a depth model reports nothing but we can measure its disagreement with the
Manhattan assumption. That is the property the VLM lacked.

---

## 7. Segmentation — is it actually necessary?

**Short answer: yes, but not at first, and not SAM-2-Large.**

| Model | Size | Speed | License | Verdict |
|---|--:|---|---|---|
| SAM 2 (Hiera-B+) | ~80M encoder **[V]** | — | **Apache-2.0 [V]** | Production choice |
| SAM 2.1-L | ~226M encoder / 235M total **[V]** | — | Apache-2.0 | Too heavy for 6 GB alongside others |
| MobileSAM | tiny | ~10 ms/img **[V]** | Apache-2.0 **[B]** | MVP choice |
| EdgeSAM | tiny | >37× SAM on 2080 Ti; >7× MobileSAM on iPhone 14 **[V]** | **[B]** | Strong edge option |
| EfficientViT-SAM | small | accelerated without accuracy loss **[V]** | **[B]** | Candidate |

**Why segmentation earns its place:** a bounding box is a poor footprint. For a chair, the
box contains floor, and the depth statistics inside it are contaminated by whatever is
behind the legs. The object's *footprint polygon* — which is what the compiler's SAT
collision already consumes — needs the mask, not the box. Our Phase 0d ground truth
illustrates it: an L-shaped sectional's box covers a large region of empty floor.

**Why it is not first:** for large, boxy furniture (bed, sofa, counter, wardrobe) the box is
an adequate footprint, and those are exactly the pieces that anchor a room. Architecture A
ships without segmentation and adds it in B.

**Wall/floor segmentation is a different and more valuable use.** Semantic segmentation of
*architecture* (floor, wall, ceiling, window, door) lets us mask those pixels before plane
fitting, which directly addresses the mirror and window failure modes in §6. This is worth
more to us than precise furniture masks.

---

## 8. Room reconstruction — the central architectural question

The brief asks directly: `image → objects → room`, or `image → room → objects`?

**The evidence says room first, decisively, and our own data is the strongest part of it.**

### The argument

1. **The relation we most need is the one we most fail at, and it is defined relative to the
   room.** "Against a wall" is meaningless without a wall. We spent Phases 1c–1h trying to
   get it from a model and reached 14.1% false-wall at best **[M]**. With a fitted wall
   plane and an object footprint, it is `distance(footprint, plane) < threshold` — exact,
   cheap, explainable, and it degrades gracefully (report the distance, let the caller
   threshold it).

2. **Monocular 3D object detection is not strong enough to be the backbone.** Cube R-CNN on
   SUN RGB-D: **AP3D 34.7%**, versus ImVoxelNet 30.6% **[V]**. That is the mature,
   well-benchmarked indoor number. An objects-first architecture inherits that ceiling for
   *every* object. A room-first architecture inherits it for none, because the room is
   fitted from dense geometry rather than detected.

3. **The room is the easier target.** Interiors are overwhelmingly Manhattan-world: three
   mutually perpendicular dominant directions. Floors are large, planar, textured and
   unoccluded in the lower image. Walls are large and planar. Fitting a few planes to a
   dense point map with RANSAC is a classical, robust, *deterministic* operation with
   decades of literature — not a learned guess.

4. **Metric scale has an external anchor for us that nobody else gets.** Allure already
   collects room dimensions and floor plans in the brief. A floor plan gives true metric
   scale and true wall topology. Fusing it with a reconstructed room converts a
   scale-ambiguous point cloud into a metric one — see §15. Objects-first cannot exploit
   this; room-first is built for it.

5. **It matches the pipeline we already have.** The compiler already reasons in a room
   frame with a boundary polygon, wall-aligned candidates and clearance. Room-first feeds it
   *measured* walls instead of an assumed rectangle from the brief. That is a drop-in
   upgrade to an existing, working component rather than a replacement.

### Methods

| Approach | Input | Note |
|---|---|---|
| RANSAC plane fitting + Manhattan assumption | point map | **[B]** classical, deterministic, our recommendation |
| RoomFormer (CVPR 2023), PolyRoom (2024) | 3D scans | **[V]** two-level queries for floorplan reconstruction; input is scans, not single images |
| Feed-forward point maps: MoGe / MoGe-2 / VGGT | 1–N images | **[V]** the enabling technology — dense geometry without SfM |
| Diorama — zero-shot single-view indoor modelling | single image | **[V]** lead worth reading (arXiv 2411.19492) |

**Recommended:** MoGe-2 (or UniDepth) → dense point map → semantic mask to remove
windows/mirrors → RANSAC floor plane → gravity alignment → RANSAC wall planes under a
Manhattan prior → room polygon. Deterministic from the point map onward.

---

## 9. 2D → 3D object grounding

Once the room frame exists, grounding an object is far simpler than general monocular 3D
detection, because the hard degrees of freedom are already pinned.

**The room-frame shortcut:** given the floor plane and a detected object that our vocabulary
says is floor-standing (`PLACEMENT_BY_TYPE` already encodes this **[M]**), the object's
vertical position is *determined* — it sits on the floor. Yaw is the only free rotation in
practice; interiors do not have tilted sofas. So a "6-DoF pose" problem collapses to
**(x, z, yaw)** plus a scale check. That is a 3-parameter estimate, and the compiler's
existing machinery already solves exactly that shape of problem.

| Method | Year | Result / note | Allure relevance |
|---|---|---|---|
| Cube R-CNN / Omni3D | CVPR 2023 | SUN RGB-D AP3D **34.7%** **[V]** | Baseline; too weak to rely on alone |
| V-MIND | 2024 | versatile monocular indoor 3D detector **[V]** | Lead (arXiv 2412.11412) |
| 3D-MOOD | 2025 | lifting 2D→3D, monocular **open-set** detection **[V]** | Strong lead (arXiv 2507.23567) — open-set matters for us |
| **SAM 3D Objects** | Nov 2025 | single image + mask → **shape, texture, pose, layout**; robust to occlusion and unusual poses **[V]** | **Very high relevance**; licence is Meta's "SAM License" — **must be reviewed before any use [V]** |
| DINOv2-based matching / CAD retrieval | — | feature correspondence for asset alignment **[B]** | Asset retrieval, §14 |

**Recommendation:** do *not* adopt an end-to-end monocular 3D detector as the backbone.
Derive (x, z) from the object's mask footprint projected onto the fitted floor plane, and
treat yaw as the one quantity where a learned prior or a VLM hint is genuinely useful —
which is exactly what Phase 1d found (FACES was the only relation where the model beat the
rules **[M]**).

SAM 3D Objects is the one recent result that could change this picture, and it should be
evaluated — after a licence review, and against our own benchmark rather than its own.

---

## 10. 3D scene graphs

Our `SpatialGraph` is currently a relation dictionary with typed edges (`NEAR`,
`ADJACENT_TO`, `SUPPORTED_BY`, `FACES`, `AGAINST_WALL`, `GROUPED_WITH`, …) plus groups,
conflicts, unmatched detections and warnings, with camera-frame relations (`LEFT_OF` etc.)
deliberately quarantined **[M]**. That quarantine was correct and should be preserved — a
render has no fixed "left" relative to the floor plan.

**ConceptGraphs (ICRA 2024)** is the reference design **[V]**: each object is a node
carrying *both* geometric and semantic features; relations live on edges; the map is built
from class-agnostic instance masks fused into 3D, tagged by a VLM, with an LLM supplying
relational priors. That is remarkably close to the factorisation our own measurements
forced on us, arrived at independently.

**What should change in ours:**

1. **Every node gets geometry.** Today a node can exist with only a semantic label. In the
   new representation a node carries a 3D footprint, an oriented bounding box and a
   support surface — or it is explicitly marked as *ungrounded* and cannot drive placement.
2. **Every edge gets provenance and a frame.** An edge must record whether it was
   *computed* from geometry, *asserted* by a model, or *assumed* from vocabulary defaults —
   and which coordinate frame it lives in. Phase 1d showed we cannot tell a model's
   confident guess from a measurement unless we record it at write time.
3. **Relations become derived, not stored, wherever they are computable.** `AGAINST_WALL`,
   `SUPPORTED_BY`, `NEAR`, `ADJACENT_TO` and `OVERLAPS` are all functions of geometry. They
   should be *computed on demand* from the grounded scene, not carried as independent facts
   that can contradict the geometry. Only `FACES` and grouping intent are genuinely
   model-supplied.

---

## 11. Spatial relationship models — should we learn a prior?

The brief poses it well: `P(chair_position | table, sofa, room)` instead of `LLM → XYZ`.

The literature here is mature **[V]**: ATISS (autoregressive transformer over object
properties), DiffuScene (CVPR 2024, diffusion over unordered object attributes), LEGO-Net
(CVPR 2023, learning regular rearrangement), InstructScene (ICLR 2024 spotlight, semantic
graph prior), PhyScene (physically interactable synthesis for embodied AI), Forest2Seq
(ECCV 2024, order priors).

**These solve a different problem from ours, and the distinction matters.** They *generate*
plausible rooms from scratch or from text. Allure is doing **scene reconstruction from a
reference image**: the arrangement is already determined by the photograph the client
approved. We do not want a plausible sofa position; we want *that* sofa's position.

**Where a learned prior genuinely helps us:**

- **Disambiguating yaw** when the image is uninformative — a chair whose front is occluded.
- **Filling unobserved regions** — the part of the room the camera never saw, which we must
  still furnish for a walkthrough.
- **Regularisation** — LEGO-Net's insight that real rooms are *regular* (aligned, evenly
  spaced) is a good prior for cleaning up noisy reconstructed poses **[V]**.

**Recommendation:** not in Architecture A or B. This is Architecture C, and it is where the
proprietary moat is (§23) — because we will own something nobody else has: thousands of
(reference image → human-approved final 3D scene) pairs from real projects.

---

## 12. Constraint solvers

**Infinigen Indoors (CVPR 2024) is the closest published system to what Allure needs** and
validates the approach we already partly have **[V]**:

- A **domain-specific language** for expressing scene constraints.
- A **simulated annealing solver** that maximally satisfies them.
- **Hierarchical optimisation**: floor plan → large furniture → small decor, so fundamental
  spatial relationships are fixed before detail is added.
- Explicit **physics constraints** (no intersection, objects rest on real support) and
  **accessibility constraints** (a chair needs clearance to sit down; a drawer needs room to
  open).
- Reported mean error frequency **0.175**, with the solver eliminating flying and
  overlapping furniture **[V]**.

By contrast **Holodeck is limited to rectangular boundaries and produces fragmented layouts
lacking realistic architectural connectivity** **[V]** — which is precisely the limitation
our current "assume a rectangle from the brief" approach has.

**Our existing compiler is already a primitive version of this** **[M]**: `_ordered()`
sequences placement by dependency, `_pick_support()` resolves hosts, `_relation_candidates()`
generates positions from relations, `_wall_aligned_candidates()` provides the default, SAT
polygon overlap rejects collisions, and `DOOR_CLEARANCE_DEPTH` encodes one accessibility
rule. It is a greedy, ordered, constraint-checking placer.

**Recommendation:** evolve it rather than replace it — add a constraint DSL, keep the greedy
pass as initialisation, and add simulated-annealing refinement only where the greedy result
violates constraints. Crucially, in *our* problem the solver is **seeded from observed
poses**, so it is doing local refinement against evidence, not global search from nothing.
That is a much easier optimisation than Infinigen's and should converge far faster.

---

## 13. Collision, physics and validation

The compiler already does SAT polygon overlap and door clearance **[M]**. The question is
what to add and what is computationally practical.

| Technique | Cost | Use | Verdict |
|---|---|---|---|
| AABB | trivial | broad phase | **Yes** — first pass |
| **OBB (oriented bounding box)** | cheap | furniture is rectangular and rotated | **Yes** — the right primitive for us |
| Convex hull + SAT | cheap | already in use | **Yes** — keep |
| Spatial hashing / uniform grid | cheap | broad phase at scale | Yes if object counts grow |
| Blender BVH (`BVHTree`) | moderate | exact mesh-level checks | **Yes, at validation only** — we are already in Blender |
| Ray casting | cheap | floor contact, wall distance, walkway occlusion | **Yes** — cheap and directly answers our questions |
| Signed distance fields | expensive to build | fine clearance queries | Not yet |
| Voxel occupancy | moderate | coarse free-space, walkway analysis | Maybe — good for circulation checks |
| Full rigid-body simulation | expensive, non-deterministic | settling objects | **No** — non-reproducible results are a poor fit for a design tool |

**Recommended validation battery**, all deterministic and all reporting *which* rule failed:

1. Floor contact — ray cast down from object base; must hit floor or a declared support.
2. Support validity — the on-surface item's base within the host's top surface polygon.
3. Wall penetration — OBB vs wall plane signed distance.
4. Object–object penetration — AABB broad phase → OBB → BVH exact on survivors.
5. Clearance — required free polygon in front of seating, drawers, doors.
6. Door swing and walkway — ray/voxel occupancy test on circulation polygons.
7. Orientation sanity — object up-axis parallel to room up; no tilted sofas.

**Deliberately avoiding physics simulation** is a considered choice: a design tool must
produce the same scene twice from the same input, and our Phase 1f/1h experience with
stochastic results **[M]** is a strong argument for determinism wherever it is available.

---

## 14. Asset normalisation

This is Allure-specific, unglamorous, and probably the highest ratio of value to difficulty
in the entire document. A perfect spatial engine placing a badly-normalised asset produces a
broken scene — and we already have the mirror-orientation bug on record (three meshes with
the longest axis wrong) as proof **[M]**.

Provider assets arrive with arbitrary scale, arbitrary origin, arbitrary orientation,
inconsistent axes, unreliable bounding boxes, no defined ground contact and stray geometry.

### Proposed `AssetSpatialMetadata`

```python
@dataclass(frozen=True)
class AssetSpatialMetadata:
    asset_id: str
    semantic_type: str                 # vocab type

    # Canonical frame: +Y up, +Z forward (the object's "front"), metres.
    dimensions_m: tuple[float, float, float]   # w, h, d in canonical frame
    aabb_min: tuple[float, float, float]
    aabb_max: tuple[float, float, float]
    obb: OrientedBox                   # centre, half-extents, rotation

    pivot_offset: tuple[float, float, float]   # source origin -> canonical origin
    up_axis_source: str                # the axis the file actually used
    forward_axis_source: str
    scale_to_metres: float             # source units -> metres

    ground_contact_y: float            # lowest point of the footprint, canonical
    footprint_polygon: list[tuple[float, float]]   # convex hull on the floor plane
    support_surfaces: list[SupportSurface]        # top surfaces that can host

    mount: str                         # floor | wall | ceiling | on_surface
    wall_mountable: bool
    floor_placeable: bool
    back_is_flat: bool                 # can it go against a wall at all?

    articulated: bool                  # doors/drawers
    swing_volumes: list[Volume]        # space needed to open

    confidence: float
    normalisation_method: str          # measured | provider_metadata | assumed
    warnings: list[str]
```

**`back_is_flat` deserves note.** It is the asset-side counterpart of the wall question we
spent six phases on: a drum table *cannot* be against a wall in any meaningful sense, and an
asset that knows this rules out a whole class of error before any perception runs.

**Normalisation is deterministic**: compute the mesh AABB, detect the up axis from the
dominant footprint, snap to the nearest canonical orientation, translate the origin to the
footprint centre at ground contact, scale by a known-dimension prior from the vocabulary.
Every step is measurable and every step can report a warning.

---

## 15. Multi-modal input

Allure is not image-only, and this is a genuine advantage that most published work cannot
exploit.

| Input | Contributes | How it enters |
|---|---|---|
| Reference image | appearance, arrangement, object identity | perception stack |
| **Floor plan** | **true metric scale, wall topology, door/window positions** | **the metric anchor — see below** |
| Stated room dimensions | metric scale | scale constraint on the reconstruction |
| Text brief | intent, style, counts (`2BHK`), vertical | already parsed **[M]** |
| Moodboard | style, material, palette | already used **[M]** |
| Product references | specific client furniture | IP-Adapter already wired **[M]** |
| Multiple images | multi-view consistency | §16 Architecture C |

**The floor plan is the highest-value under-used input we already collect.** Monocular
reconstruction is scale-ambiguous; a floor plan resolves it exactly. The fusion is a
constrained fit: reconstruct the room's shape from the image up to scale, then solve for the
similarity transform aligning it to the plan's wall topology. Once aligned, **every object
position inherits true metric scale** — and the mirrors/windows/long-room depth failures of
§6 are largely bounded, because the room's extent is known independently.

This is the cheapest large accuracy win available and it requires no new model.

---

## 16. Three candidate architectures

### Architecture A — MVP, runs on the RTX 3050 6 GB alongside Blender

```
Reference image
   │
   ├─► Grounding DINO ──────────► 2D boxes + labels          [Apache-2.0]
   │
   ├─► Depth Anything V2-Small ─► relative depth map         [Apache-2.0, 24.8M]
   │
   └─► qwen2.5vl:3b ───────────► semantics only: type, material, colour, style
                                  (NEVER geometry, NEVER relations)
                    │
                    ▼
        Point cloud (relative) ──► scale from stated room dimensions
                    │
                    ▼
        RANSAC floor plane → gravity align → RANSAC wall planes (Manhattan)
                    │
                    ▼
        Room polygon + wall planes (metric, approximate)
                    │
                    ▼
        Object footprint = box ∩ depth, projected to floor plane → (x, z)
                    │
                    ▼
        SpatialGraph v2 — relations COMPUTED from geometry, not asserted
                    │
                    ▼
        Existing compiler (greedy + SAT collision + clearance)
                    │
                    ▼
        Blender ──► validation battery (§13) ──► warnings to review UI
```

**Memory:** DINO-tiny ~0.7 GB + DAv2-S ~0.1 GB, run sequentially and unloaded; Qwen-3B
2.9 GB. Fits, and Blender can have the card back. **[B]** on exact figures — §21 measures
them first.

**What it buys:** wall contact, support and adjacency become *computed* facts. Based on our
own measurements that replaces a 14–35% error rate **[M]** with a geometric test whose error
we can characterise.

**What it lacks:** true metric scale without stated dimensions; no masks so footprints are
crude; no orientation beyond the VLM's `FACES` hint.

---

### Architecture B — Recommended production

```
Reference image  +  Floor plan  +  Dimensions  +  Text brief
   │                    │
   │                    └──────────────────────────┐
   ▼                                               │
PERCEPTION (parallel, cloud GPU or local small)    │
   ├─ Grounding DINO ─────────► boxes + labels     │
   ├─ SAM 2 (Hiera-B+) ──────► instance masks      │  [Apache-2.0]
   ├─ architecture segmentation ► floor/wall/window/door/mirror masks
   ├─ MoGe-2 or UniDepthV2 ──► METRIC point map    │
   └─ VLM (semantics only) ──► type, material, colour, style, FACES hint
   │                                               │
   ▼                                               │
ROOM RECONSTRUCTION (deterministic)                │
   ├─ mask out windows/mirrors before fitting      │
   ├─ RANSAC floor plane, gravity alignment        │
   ├─ RANSAC wall planes under Manhattan prior     │
   └─ room polygon + openings ◄────────────────────┘  FLOOR-PLAN FUSION
                                                       (similarity transform
   │                                                    → TRUE metric scale)
   ▼
OBJECT GROUNDING (deterministic given the room)
   ├─ mask ∩ point map → 3D footprint → (x, z) on the floor plane
   ├─ height from floor plane; mount type from vocab
   ├─ yaw from: observed footprint principal axis → VLM FACES hint → wall normal
   └─ per-object geometric confidence = inlier support
   │
   ▼
3D SCENE GRAPH (geometrically grounded; every edge carries provenance + frame)
   ├─ nodes: grounded objects, walls, floor, openings
   ├─ relations COMPUTED: against_wall, supported_by, near, adjacent, overlaps
   ├─ relations ASSERTED (model): faces, grouping intent
   └─ camera-frame relations quarantined, never used for placement
   │
   ▼
CONSTRAINT SOLVER  (seeded from observed poses — local refinement, not search)
   ├─ constraint DSL: support, non-penetration, clearance, accessibility, alignment
   ├─ greedy pass = current compiler (initialisation)
   └─ simulated-annealing refinement ONLY on constraint violations
   │
   ▼
ASSET RETRIEVAL ──► AssetSpatialMetadata (§14) ──► POSE SOLVER (fit asset OBB to
   │                                                slot; scale within vocab bounds)
   ▼
BLENDER assembly ──► VALIDATION battery (§13) ──► REPAIR loop (bounded retries)
   │
   ▼
Final scene + per-object evidence trail + reviewer warnings
```

**Every geometric decision in this diagram is deterministic.** Models appear only at
perception (boxes, masks, depth) and at two clearly-bounded semantic points (identity/style,
and the `FACES` hint that Phase 1d showed is the one relation where a model adds value
**[M]**).

---

### Architecture C — Future Allure proprietary

Architecture B, plus:

1. **Multi-view / video.** 2–4 images or a phone sweep through VGGT-class feed-forward
   reconstruction **[V]**, removing most monocular ambiguity. Licence must be resolved
   (base checkpoint is research-only **[V]**).
2. **Allure layout prior**, trained on our own (reference image → human-approved scene)
   pairs. Used as a *residual* on the solver — proposing yaw and filling unobserved regions
   — never as a coordinate generator.
3. **Learned asset-to-observation matching** via DINOv2-class features, so the retrieved
   asset actually resembles the photographed piece.
4. **Learned repair policy** — which constraint to relax when the solver cannot satisfy all
   of them, trained on designer edits.

---

## 17. Recommended architecture

# **The best architecture for Allure is Architecture B.**

### Why

**1. It fixes the measured failure at its root rather than mitigating it.** Eight phases
established that the VLM cannot supply geometric relations **[M]**. B does not ask it to.
Wall contact stops being an opinion and becomes a distance.

**2. It is the only option where the hardest relation gets easier rather than harder.**
Objects-first inherits Cube R-CNN's ~34.7% AP3D ceiling **[V]** on every object.
Room-first fits a handful of large planes to dense geometry — the easiest possible target —
and every object placement then rides on that single well-conditioned estimate.

**3. It exploits an advantage nobody else has.** The floor plan and stated dimensions we
already collect resolve monocular scale ambiguity exactly (§15). Published single-image
work cannot use this. It is free metric accuracy sitting in our existing intake form.

**4. It upgrades the compiler instead of replacing it.** `_ordered`, `_pick_support`,
`_relation_candidates`, `_wall_aligned_candidates`, SAT collision and door clearance all
survive **[M]**. We are feeding measured walls into a working placer, not rewriting it.
Phase 1d showed the deterministic engine already *beats* the model overall (57.1% vs 48.6%)
— B strengthens the side that was already winning.

**5. Every component is Apache-2.0 and self-hostable.** Grounding DINO **[V]**, SAM 2
**[V]**, DAv2-Small **[V]**. The licence traps — DAv2-Large's CC-BY-NC-4.0, VGGT's
research-only default **[V]** — are avoided by construction, not discovered in due diligence.

**6. It degrades honestly.** Plane fitting reports inlier support; depth reports
disagreement with the Manhattan prior; grounding reports how much of a mask had valid depth.
Every number is a *measurable* confidence, unlike the VLM's self-reported `"high"` that was
wrong most of the time it mattered **[M]**.

**7. It scales the way the business does.** Small models on the 3050 for development,
larger ones in the cloud for production, with the same interfaces. No component assumes a
24–80 GB GPU.

### Scoring against the brief's twelve criteria

| Criterion | A | **B** | C |
|---|:--|:--|:--|
| 1 Spatial accuracy | medium | **high** | highest |
| 2 Physical validity | high | **high** | highest |
| 3 Interior-design relevance | high | **high** | highest |
| 4 Generalisation | medium | **high** | high |
| 5 Open-world objects | high | **high** | high |
| 6 Multimodal support | low | **high** | highest |
| 7 Local feasibility | highest | **high** | low |
| 8 6 GB dev feasibility | **yes** | **yes** (small variants) | no |
| 9 Production scalability | medium | **high** | high |
| 10 Engineering complexity | low | **medium** | high |
| 11 Proprietary moat | none | **some** | **highest** |
| 12 Objective validation | **yes** | **yes** | yes |

A is B with components removed; C is B with components added. **B is the architecture; A is
its first milestone and C is its roadmap.** That is deliberate — it means no work is thrown
away.

---

## 18. Canonical Allure spatial representation

```python
# ─── Geometry primitives ────────────────────────────────────────────────
Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]

@dataclass(frozen=True)
class Plane:
    normal: Vec3
    offset: float
    inlier_count: int
    inlier_fraction: float          # the fit's own honesty measure
    source: Literal["fitted", "floorplan", "assumed"]

@dataclass(frozen=True)
class OrientedBox:
    centre: Vec3
    half_extents: Vec3
    yaw: float                      # rotation about up axis; interiors need no more

# ─── Evidence: the spine of the whole design ────────────────────────────
@dataclass(frozen=True)
class Evidence:
    """Why we believe something, recorded where it is believed.

    Phase 1d proved we cannot distinguish a model's confident guess from a
    measurement unless provenance is written at the moment of assertion.
    """
    source: Literal["geometry", "detector", "vlm", "vocab_default",
                    "floorplan", "user", "solver"]
    method: str                     # "ransac_plane" | "grounding_dino" | ...
    confidence: float               # 0-1; for geometry this is measurable
    frame: Literal["world", "room", "camera"]
    note: str = ""

# ─── Architecture ───────────────────────────────────────────────────────
@dataclass
class RoomGeometry:
    room_id: str
    floor: Plane
    ceiling: Plane | None
    walls: list[Plane]
    boundary: list[Vec2]            # room polygon, metric, floor frame
    openings: list["Opening"]       # doors, windows, with wall index
    height_m: float
    up_axis: Vec3
    metric_source: Literal["floorplan", "stated_dims", "metric_model", "unscaled"]
    evidence: Evidence

# ─── Objects ────────────────────────────────────────────────────────────
@dataclass
class SceneObject:
    object_id: str
    semantic_type: str              # vocab
    name: str                       # open description from the VLM

    # Observation (what the image says)
    bbox_2d: tuple[int, int, int, int] | None
    mask_ref: str | None
    footprint: list[Vec2] | None    # on the floor plane, metric
    obb: OrientedBox | None
    grounded: bool                  # False => cannot drive placement, full stop
    geometric_confidence: float     # fraction of mask with valid depth

    # Semantics (what the VLM says)
    material: str
    colour: str
    style_tags: list[str]

    # Placement intent (what the solver must honour)
    mount: Literal["floor", "wall", "ceiling", "on_surface"]
    support_id: str | None
    constraints: list["Constraint"]

    # Resolution (what the pipeline decided)
    asset_id: str | None
    pose: OrientedBox | None        # FINAL, solver-owned. No model writes this.
    evidence: list[Evidence]

# ─── Relations ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Relation:
    subject_id: str
    predicate: Literal["against_wall", "supported_by", "faces", "near",
                       "adjacent_to", "overlaps", "grouped_with", "in_front_of"]
    object_id: str | None           # None for wall/room-directed relations
    wall_index: int | None
    value: float | None             # the measurement: distance, angle, gap
    derived: bool                   # True => recomputed from geometry, not stored
    evidence: Evidence

# ─── The scene ──────────────────────────────────────────────────────────
@dataclass
class SpatialScene:
    scene_id: str
    room: RoomGeometry
    objects: list[SceneObject]
    relations: list[Relation]       # derived ones are a cache, never a source
    groups: list["Group"]
    conflicts: list["Conflict"]
    unmatched_detections: list[dict]
    occupancy: "OccupancyGrid | None"
    clearances: list["ClearanceZone"]
    warnings: list[str]
    schema_version: int
```

**Four invariants this schema enforces, each traceable to a measured failure:**

1. **`pose` is written only by the solver.** No model, ever. (The governing principle.)
2. **`grounded=False` objects cannot drive placement.** An object with a name but no
   geometry is a suggestion, not a fact.
3. **`derived=True` relations are a cache.** They are recomputed from geometry and may never
   contradict it. This is what prevents the Phase 1c situation where an asserted relation
   and the picture disagreed and nothing could adjudicate.
4. **`frame` is mandatory on every Evidence.** Camera-frame facts can be stored but can
   never reach placement — the quarantine we already established **[M]**, now enforced by
   the type.

---

## 19. Learned vs deterministic

| Component | Learned | Deterministic | Why |
|---|:--:|:--:|---|
| Object detection (2D) | **✔** | | Open-vocabulary recognition is irreducibly learned. Measured best-in-class for us **[M]** |
| Instance segmentation | **✔** | | Same |
| Architecture segmentation (floor/wall/window) | **✔** | | Same |
| Depth / point map | **✔** | | Same |
| Camera intrinsics / FoV | **✔** | | Modern metric models predict it **[V]** |
| **Floor plane** | | **✔** | RANSAC on the point map. Reports inlier support |
| **Wall planes** | | **✔** | RANSAC + Manhattan prior |
| **Room polygon** | | **✔** | Plane intersection, or from floor plan |
| **Metric scale** | | **✔** | Floor plan / stated dimensions — exact, not estimated |
| Object identity & type | **✔** | | VLM's genuine strength **[M]** |
| Material, colour, style | **✔** | | Same |
| **Object (x, z)** | | **✔** | Mask footprint projected to the fitted floor |
| **Object height / mount** | | **✔** | Floor plane + `PLACEMENT_BY_TYPE` **[M]** |
| **Object yaw** | **✔ hint** | **✔ decide** | Footprint principal axis first; VLM `FACES` as tiebreak — the one relation where the model beat the rules (+2) **[M]**; solver owns the final value |
| **Scale** | | **✔** | Asset dimensions + vocab bounds, clamped |
| **against_wall** | | **✔** | Distance to wall plane. **Never a model — 0/30 measured [M]** |
| **supported_by** | | **✔** | `SUPPORT_PREFERENCE`/`SURFACE_HEIGHT` + geometry. **Rules 88.9% vs model 33.3% [M]** |
| **near / adjacent / overlaps** | | **✔** | Distance and polygon tests |
| **Collision** | | **✔** | AABB → OBB → BVH |
| **Clearance & accessibility** | | **✔** | Polygon tests from asset metadata |
| **Placement / final pose** | | **✔** | Constraint solver. The core principle |
| **Asset normalisation** | | **✔** | Mesh measurement |
| Asset retrieval / matching | **✔** | | Embedding similarity |
| User intent from text | **✔** | | LLM parsing — already works **[M]** |
| Unobserved-region layout | **✔** (future) | | Architecture C only |

**The rule this table encodes:** *models perceive; geometry decides.* Every row where we
violated that rule is a row where we measured a failure.

---

## 20. Benchmark plan

A new architecture must be proved better than the current system on evidence at least as
good as the evidence that condemned the current one. Two design rules carried forward from
Phase 1f's mistake **[M]**: **scene-level independence** (no metric dominated by one room)
and **source balance** (generated and historical imagery measured separately, never pooled).

| # | Task | Metric | Why this metric | Baseline to beat |
|---|---|---|---|---|
| 1 | 2D detection | precision, recall, mAP; **small-object recall separately** | recall ~0.75 means a quarter of pieces missing; small objects are our known weak class **[M]** | DINO recall 0.75, IoU 0.680 **[M]** |
| 2 | Segmentation | mask IoU; **footprint IoU on the floor plane** | footprint is what the solver consumes; mask IoU alone can look good with a bad footprint | box-as-footprint |
| 3 | Room geometry | wall-plane normal error (°), wall distance error (m), room-area error (%) | direct, physical, independently checkable against the floor plan | assumed rectangle |
| 4 | **Wall contact** | **false-wall rate, NO-recall, 95% CI** | **the flagship comparison — identical metric, identical 43-case dataset** | **7B: false-wall 14.1% [7.6, 24.6], NO-recall 85.9% [M]** |
| 5 | Support | support accuracy; invalid-support rate | support errors produce visibly floating objects | **deterministic 88.9% [M]** |
| 6 | Facing | yaw error (°); % within 45° | 45° is the threshold at which a sofa visibly faces the wrong way | **VLM chain 30% end-to-end [M]** |
| 7 | Relative position | pairwise relation accuracy, floor-plan frame only | camera-frame relations are meaningless for placement **[M]** | Phase 1b/1c |
| 8 | Depth ordering | pairwise ordinal accuracy | scale-free; isolates ordering from metric error | none |
| 9 | 3D grounding | centre error (m and % of room diagonal), 3D IoU | % of diagonal makes rooms comparable, as in Phase 0d **[M]** | none |
| 10 | Collision-free placement | collision rate, penetration depth, clearance violations, floating objects | direct physical validity | current compiler |
| 11 | Scene-level success | **% of scenes with zero critical violations**; designer A/B preference | the only metric that matches the product's actual bar | current pipeline |
| — | Cost | latency per room, peak VRAM, CPU spill | 6 GB feasibility is a hard constraint **[M]** | 3B 0.7 s/room; 7B 2.9 s/room **[M]** |

### The first experiment, and why it is the right one

**Compute wall contact geometrically on the exact Phase 1g/1h dataset and compare head to
head against the measured 14.1% false-wall.**

It is the right first experiment because:

- **The benchmark already exists** — 43 cases, 32 negatives, 16 scenes, hand-verified
  ground truth, Category A/B labels, and a measured VLM baseline with confidence intervals
  **[M]**. No annotation work.
- **It tests the architecture's central claim** — that geometry beats the VLM on the
  relation we have failed at six times.
- **It is decisive either way.** If geometric wall contact lands near 0–5% false-wall, the
  whole room-first thesis is validated on our own data and Architecture B proceeds. If it
  lands near 14%, monocular depth is not accurate enough at our image resolution and we need
  the floor-plan fusion (§15) before anything else.
- **It costs about a day** and needs no training, no new dataset, and no production change.
- It also resolves the outstanding Phase 1h question — whether 14.1% was real capability or
  easy imagery — because a geometric method can be run on *both* the historical and the
  generated negatives and the gap measured directly.

---

## 21. Hardware plan

| Stage | Where | Constraint |
|---|---|---|
| Development | RTX 3050 6 GB | small variants only; models loaded sequentially and unloaded; **never concurrent with Blender** |
| Perception (production) | cloud GPU, 16–24 GB | full-size DINO, SAM 2, metric depth |
| Solver | CPU | deterministic, parallelisable, no GPU |
| Blender assembly/render | GPU | needs the card to itself — measured **[M]** |

**Immediate measurement task, before any architecture work:** peak VRAM and latency for
Grounding DINO, SAM 2 / MobileSAM, DAv2-Small, MoGe-2 and UniDepthV2 on this 3050, loaded
individually. None of these are published **[V]** and 6 GB feasibility depends entirely on
them. This is a half-day of measurement that de-risks the whole plan.

**A known constraint to design around** **[M]**: SD 1.5 moodboard generation already uses
~3 GB and 15 s/scene on this card. Perception and generation must be scheduled on the
existing two-lane runner, not run concurrently.

---

## 22. MVP implementation roadmap

Sequenced so that each step is independently verifiable and each de-risks the next.

| Step | Work | Proves | Gate |
|---|---|---|---|
| 0 | Measure VRAM/latency of the candidate models (§21) | 6 GB feasibility | all fit under 4 GB individually |
| **1** | **Geometric wall contact on the Phase 1h dataset** | **the central thesis** | **false-wall < 10%, beating 14.1% [M]** |
| 2 | Floor + wall plane fitting with inlier reporting | room reconstruction viable | wall normal error < 5° |
| 3 | Floor-plan fusion for metric scale | metric accuracy | room-area error < 10% |
| 4 | `SpatialScene` schema + provenance plumbing | representation | round-trips; camera-frame quarantine enforced by type |
| 5 | Object grounding: mask → footprint → (x, z) | 3D grounding | centre error < 5% of room diagonal |
| 6 | Relations computed from geometry, VLM demoted to semantics | delegation | matches or beats deterministic 57.1% **[M]** |
| 7 | Asset normalisation + `AssetSpatialMetadata` | asset correctness | zero mirrored/mis-scaled assets (fixes a known bug **[M]**) |
| 8 | Validation battery + repair loop | physical validity | zero critical violations on the sample set |
| 9 | Constraint DSL + annealing refinement | solver | scene-level success rate up vs current |

**Steps 1–3 are the decision point.** If geometric wall contact and plane fitting work, the
architecture is proved and the rest is engineering. If they do not, we have spent a week and
learned something that changes the plan — which is exactly the shape of every phase in this
programme so far.

---

## 23. Future proprietary moat

The models are commodities. Three things will not be:

1. **The data flywheel.** Every completed Allure project is a (reference image, floor plan,
   brief, **human-approved final 3D scene**) tuple. That is the exact supervision signal for
   a learned layout prior, and it is generated as a by-product of doing business. No
   competitor has it for Indian residential interiors. This is the moat; everything else is
   a moat-digging implement.
2. **Asset-normalised catalogue.** A library of provider assets with verified
   `AssetSpatialMetadata` is expensive to build, boring to build, and immediately valuable.
3. **The constraint library.** Encoded design rules — Indian apartment circulation norms,
   vertical-specific clearances, hospitality standards — accumulated from designer
   corrections. This is domain knowledge that generalises across every model generation.

**What will not be a moat:** any particular VLM, detector or depth model. Design for
replacement (§19's factorisation does this) and swap freely.

---

## 24. Risks and failure modes

| Risk | Severity | Evidence | Mitigation |
|---|---|---|---|
| **Monocular depth not accurate enough at 704×448** | **high** | none yet — this is the open question | Step 1 measures it directly; floor-plan fusion as the fallback |
| Licence traps | **high** | DAv2-L is CC-BY-NC; VGGT base research-only; SAM 3D uses Meta's own licence **[V]** | Apache-2.0 only in A and B; legal review before any SAM 3D use |
| Mirrors/windows corrupting plane fits | medium | **[B]** | semantic masking before fitting; both are already vocab types **[M]** |
| Detection recall ~0.75 | medium | **[M]** | missing objects are visible to reviewers; measure small-object recall separately |
| Complexity creep | medium | — | A ships first; every stage independently gated |
| Over-trusting geometric confidence | medium | — | calibrate inlier-fraction against ground truth in Step 2 |
| Repeating the Phase 1f confound | medium | **[M]** | scene independence and source balance are benchmark requirements, not options |
| 6 GB proving infeasible for B | medium | **[M]** 7B already spills | A is the local tier; B's perception moves to cloud |
| SD-generated benchmark imagery being unrepresentative | **high** | **[M]** 1f 35% vs 1h 14.1% on the same model | always report generated and historical separately |

---

## 25. References

Verified this session **[V]**:

- Wang et al., **VGGT: Visual Geometry Grounded Transformer**, CVPR 2025 (Best Paper).
  1B params, feed-forward cameras/depth/point maps, <1 s, single-view capable.
  Base checkpoint research-only; commercial checkpoint by application.
  [CVF](https://openaccess.thecvf.com/content/CVPR2025/html/Wang_VGGT_Visual_Geometry_Grounded_Transformer_CVPR_2025_paper.html) ·
  [GitHub](https://github.com/facebookresearch/vggt)
- Wang et al., **MoGe**, CVPR 2025 Oral. Affine-invariant point maps from open-domain
  images. [arXiv:2410.19115](https://arxiv.org/abs/2410.19115) ·
  [GitHub](https://github.com/microsoft/moge)
- **MoGe-2: Accurate Monocular Geometry with Metric Scale and Sharp Details**, 2025.
  [arXiv:2507.02546](https://arxiv.org/pdf/2507.02546)
- **Depth Anything V2**, 2024. NYUv2 δ₁ 0.984 / AbsRel 0.056 (metric-finetuned).
  **Small 24.8M Apache-2.0; Base/Large/Giant CC-BY-NC-4.0.**
  [arXiv](https://arxiv.org/html/2406.09414v2) ·
  [GitHub](https://github.com/DepthAnything/Depth-Anything-V2)
- Piccinelli et al., **UniDepth**, CVPR 2024; **UniDepthV2**, 2025. Universal monocular
  metric depth with learned camera representation.
  [CVF](https://openaccess.thecvf.com/content/CVPR2024/papers/Piccinelli_UniDepth_Universal_Monocular_Metric_Depth_Estimation_CVPR_2024_paper.pdf) ·
  [arXiv:2502.20110](https://arxiv.org/abs/2502.20110)
- **Depth Pro: Sharp Monocular Metric Depth in Less Than a Second**, 2024.
  [arXiv:2410.02073](https://arxiv.org/pdf/2410.02073)
- Brazil et al., **Omni3D / Cube R-CNN**, CVPR 2023. SUN RGB-D AP3D 34.7% vs ImVoxelNet
  30.6%.
  [CVF](https://openaccess.thecvf.com/content/CVPR2023/papers/Brazil_Omni3D_A_Large_Benchmark_and_Model_for_3D_Object_Detection_CVPR_2023_paper.pdf)
- **3D-MOOD: Lifting 2D to 3D for Monocular Open-Set Object Detection**, 2025.
  [arXiv:2507.23567](https://arxiv.org/pdf/2507.23567)
- **V-MIND: Versatile Monocular Indoor 3D Detector**, 2024.
  [arXiv:2412.11412](https://arxiv.org/pdf/2412.11412)
- **Grounding DINO**, IDEA Research, Apache-2.0, commercial use permitted.
  [Roboflow licence summary](https://roboflow.com/model-licenses/grounding-dino) ·
  **Grounding DINO 1.5** is API-only:
  [arXiv:2405.10300](https://arxiv.org/pdf/2405.10300) ·
  [API repo](https://github.com/idea-research/grounding-dino-1.5-api)
- **YOLO-World**, CVPR 2024. ~20× faster, ~5× smaller than GLIP/Grounding DINO.
  [GitHub](https://github.com/ailab-cvc/yolo-world)
- **SAM 2**, Meta, July 2024, Apache-2.0. Hiera-B+ ~80M; SAM 2.1-L ~226M/235M.
  [Roboflow licence summary](https://roboflow.com/model-licenses/segment-anything-2)
- **EdgeSAM**, 2023/24. >37× SAM on 2080 Ti; >7× MobileSAM/EfficientSAM on iPhone 14.
  [arXiv:2312.06660](https://arxiv.org/pdf/2312.06660) ·
  **EfficientViT-SAM** [arXiv:2402.05008](https://arxiv.org/pdf/2402.05008v2)
- Gu et al., **ConceptGraphs: Open-Vocabulary 3D Scene Graphs for Perception and Planning**,
  ICRA 2024. [arXiv:2309.16650](https://arxiv.org/pdf/2309.16650) ·
  [project](https://concept-graphs.github.io/)
- **Infinigen Indoors**, CVPR 2024. Constraint DSL + simulated annealing; hierarchical
  floor-plan → furniture → decor; physics and accessibility constraints; mean error
  frequency 0.175. [alphaXiv](https://www.alphaxiv.org/abs/2406.11824v1)
- **RoomFormer**, CVPR 2023 (two-level queries, floorplan reconstruction); **PolyRoom**,
  2024. [summary](https://www.emergentmind.com/topics/roomformer)
- **DiffuScene**, CVPR 2024 [GitHub](https://github.com/tangjiapeng/DiffuScene) ·
  **InstructScene**, ICLR 2024 spotlight
  [GitHub](https://github.com/chenguolin/InstructScene) ·
  **Forest2Seq**, ECCV 2024
  [ECVA](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/03638.pdf) ·
  **PhyScene** [summary](https://www.researchgate.net/publication/384211979_PhyScene_Physically_Interactable_3D_Scene_Synthesis_for_Embodied_AI)
- **SAM 3D: 3Dfy Anything in Images**, Meta, Nov 2025. Single image + mask → shape, texture,
  pose, layout. Released under Meta's "SAM License" — **requires review**.
  [arXiv:2511.16624](https://arxiv.org/abs/2511.16624) ·
  [GitHub](https://github.com/facebookresearch/sam-3d-objects) ·
  [Meta announcement](https://about.fb.com/news/2025/11/new-sam-models-detect-objects-create-3d-reconstructions/)
- **Diorama: Zero-shot Single-view 3D Indoor Scene Modeling**, 2024 — lead, unread.
  [arXiv:2411.19492](https://arxiv.org/pdf/2411.19492)
- **RoomCraft**, 2025 [arXiv:2506.22291](https://arxiv.org/pdf/2506.22291) ·
  **CasaGPT**, 2025 [arXiv:2504.19478](https://arxiv.org/pdf/2504.19478) ·
  **HSM**, 2025 [arXiv:2503.16848](https://arxiv.org/pdf/2503.16848) — leads, unread.

Allure internal **[M]** — all reproducible from this repository:

- `docs/benchmarks/phase_0b_detector_report.md` — DINO vs Qwen detection gate
- `docs/benchmarks/phase_0d_raw.json`, `phase_0d_centre_error.json` — box geometry
- `docs/benchmarks/phase_1b_before.json`, `phase_1b_after.json` — reading quality
- `docs/benchmarks/phase_1c_report.md` — forced-choice relation extraction (78 queries)
- `docs/benchmarks/phase_1d_report.md` — binary decomposition; deterministic baseline
- `docs/benchmarks/phase_1e_report.md` — 3B vs 7B wall gate
- `docs/benchmarks/phase_1f_report.md` — category analysis; the scene confound
- `docs/benchmarks/phase_1g_dataset_report.md` — controlled dataset construction
- `docs/benchmarks/phase_1h_report.md` — frozen 7B on 32 negatives / 16 scenes

---

## Final question

> *"If we had to build Allure's spatial engine today with the goal of producing physically
> coherent Blender scenes from interior reference images, while starting on an RTX 3050 6 GB
> and eventually scaling to cloud GPUs, what exact architecture would you choose and why?"*

**I would build a geometry-first, room-before-objects pipeline in which learned models
supply only perception and semantics, and every spatial decision is deterministic.**

Concretely: Grounding DINO for open-vocabulary detection, SAM 2 for instance and
architecture masks, a metric monocular geometry model (MoGe-2 or UniDepthV2) for a dense
point map, and a VLM restricted to identity, material, style and a single orientation hint.
From the point map, fit the floor and wall planes by RANSAC under a Manhattan prior, fuse
with the floor plan and stated dimensions we already collect to obtain true metric scale,
and reconstruct the room **before** placing anything in it. Ground each detected object by
projecting its mask footprint onto the fitted floor, which reduces pose to (x, z, yaw).
Express the result as a geometrically-grounded 3D scene graph in which every edge carries
provenance and a coordinate frame, and in which relations like `against_wall` and
`supported_by` are **computed from geometry rather than stored as opinions**. Hand that to a
constraint solver — the existing compiler, extended with a constraint DSL and
simulated-annealing refinement seeded from the observed poses — which alone writes final
pose. Retrieve assets carrying verified `AssetSpatialMetadata`, assemble in Blender,
validate with a deterministic battery (OBB and BVH collision, floor contact, support
validity, clearance, door swing), and repair within bounded retries.

**Why:** because we have measured, across eight phases and roughly 300 model queries, that a
VLM cannot supply geometric relations at any size or in any formulation we could devise —
78/78 refusals to abstain, `AGAINST` 0/30, a wall gate that was literally a constant
function, and a deterministic baseline that already beats the model 57.1% to 48.6% **[M]**.
The one thing that would make those questions easy is the one thing we never gave the
system: an actual room. Fit the walls, and "is the sofa against a wall" stops being a
question a model can get wrong and becomes a distance we can compute, log and defend.

Everything else in the design follows from protecting that single inversion.

**STOP — research phase complete. Nothing implemented.**

# P12 — Design intent, live in the paid path

Date 2026-09-16. P11 built the representation and proved it in isolation; its
own closing debt said the thing that mattered was still missing — *"the handler
does not call it yet."* P12 closes that. Everything below is measured against
the shipped HTTP routes, job runner and `scene_plan` handler.

## 1. The live path, and the exact integration points

```
USER ── POST /api/projects/{id}/inputs ─▶ InputRecord + input/references/ref_NN.jpg
                                              │
POST /api/projects/{id}/scene-plan ─▶ job `scene_plan` (app/jobs/handlers/scene_plan.py)
                                              │
  ①  build_input_bundle ─▶ _classify_references ─▶ classify_references(bundle, provider)
        one focused vision call PER reference          └▶ planning/design_intent.json
                                              │
      provider.plan_objects            (planner inference)
      merge_reading_into_plan          (moodboard render reading — still replaces)
      apply_spatial_graph              (spatial evidence fills gaps)
  ②  apply_intents_to_plan             ◀── the client's own photos, applied LAST
                                              └▶ planning/object_plan.json
                                              │
      resolve_plan ─▶ decide_asset      (existing ladder, unchanged)
      compile_scene ─▶ place_objects    ◀── THE SOLVER decides every coordinate
      repair_placement ─▶ commit_patch ─▶ validate_scene
                                              │
  ③  resolve_all + visual_intent_fidelity      └▶ planning/visual_intent_fidelity.json
                                              │
      GET /scene-spec ─▶ design_intent + visual_intent_fidelity ─▶ Studio step 5
      build_manifest ─▶ Blender
```

| # | Integration point | File | What it does |
|---|---|---|---|
| ① | `_classify_references` | `scene_plan.py` (before `_read_scene`) | Every uploaded reference → typed intent; checkpointed, and **re-run when the reference set changes** so a newly uploaded photo is never ignored |
| ② | `apply_intents_to_plan` | `scene_plan.py` (after `apply_spatial_graph`) | Reference intent reconciles with the plan |
| ③ | `resolve_all` + `visual_intent_fidelity` | `scene_plan.py` (after commit) | Ladder + four-rate measurement against the **committed** scene |
| — | `ResilientProvider.classify_reference` | `provider.py` | The forwarder that makes the capability reachable in production |
| — | `GET /scene-spec` | `projects_routes.py` | Hands `design_intent` + `visual_intent_fidelity` to the frontend |

Two new production artifacts and checkpoints: `planning/design_intent.json`,
`planning/visual_intent_fidelity.json`.

## 2. The provenance break — fixed by ordering, not by deletion

P11 named the fatal hop: `merge_reading_into_plan` **replaces** a room's planner
items with what a VLM read out of a Stable Diffusion render, destroying any link
to the client's uploads.

The moodboard round-trip is still required — it is how an *approved render*
becomes the brief, and `generate_elements` spends real money against the crops
it produces. So it was not removed. Instead intent is applied **after** it, and
the order becomes:

> planner inference → render reading → spatial evidence → **the client's own photograph**

A derived VLM reading can no longer erase direct user evidence, because the
direct evidence is applied last. Precedence inside the merge is deliberate: an
attribute the reference **stated** wins over a planner guess (measured: the
planner had written `material_hint="fabric"` while the photo said `linen`), and
an attribute the reference did not mention leaves the planner's value alone.
Every replacement is recorded in the job feed as `material_hint='linen' (was 'fabric')`.

## 3. Field-flow matrix

Source → destination → consumer → survives? Measured, not inferred.

| Reference field | DesignIntent | Plan item | Asset resolution | Scene / manifest | Status |
|---|---|---|---|---|---|
| colour words | `attributes.color_words` | `name`, matched in `_asset_attribute_match` | scored + in `GenerationRequest.prompt` | via asset choice / tint | **PARTIAL** — reaches resolution and the generator; the manifest carries one hex tint, not words |
| colour hex | `attributes.color_hex` | `color_hint` | `decide_asset`, `_object_color` | `SceneObject.color` → manifest | **PASS** |
| material | `attributes.material` | `material_hint` | role → `material_overrides` | manifest material entry | **PASS** (to one of four style roles) |
| upholstery | `attributes.upholstery` | `material_hint` (preferred over material) | same | same | **PASS** |
| pattern | `attributes.pattern` | — | `GenerationRequest.prompt`, attribute match | — | **PARTIAL** — reaches resolution/generator, not `SceneObject` |
| frame / finish | `attributes.frame_finish` | — | `GenerationRequest.prompt`, attribute match | — | **PARTIAL** — same |
| style descriptors | `attributes.style_descriptors` | `style_notes` | `_candidates` tokens, generator prompt | — | **PARTIAL** — influences selection, absent from `SceneObject` |
| visual descriptors | `attributes.visual_descriptors` | `style_notes` | generator prompt | — | **PARTIAL** — same |
| reference provenance | `provenance.*` | — | `source_intent_ids` | `fidelity.rows[].traced_object_ids` | **PASS** — queryable, see §4 |
| confidence | `confidence` | — | gates UNCERTAIN | — | **PASS** as a gate |

**Intentionally dropped, and why:** `pattern`, `frame_finish` and the descriptor
lists have no field on `SceneObject` and adding them is a production schema
change to the type the solver, patches, store and Blender manifest all share.
They are preserved in `design_intent.json` and in the `GenerationRequest`, so
nothing is lost — it simply does not reach the executor row yet. That is debt
(§8), stated rather than hidden.

## 4. Provenance flow

`scene object → intent → reference → source image` is answerable today:

```
SceneObject.object_id
  └─ visual_intent_fidelity.rows[].traced_object_ids   → intent_id
       └─ design_intent.intents[].intent_id            → provenance.input_id
            └─ InputRecord.input_id                    → input/references/ref_NN.jpg
```

An object with no such row is planner/model-derived, and is not claimed
otherwise. Nothing is back-filled after the fact: `intent_id` is a sha1 of
`(input_id, class, category, room_hint)`, minted at classification time.

## 5. Benchmark results — the real path

`research/p12_design_intent_benchmark.py` → `docs/benchmarks/p12_live_design_intent.json`.
**10/10 cases pass.** Cases 1–9 run the real routes and handler on the
deterministic mock provider; case 10 uses real client photographs and the real
Gemini model.

| Case | Result |
|---|---|
| 1 exact object | `exact_object` ×1, **one** sofa in scene, provenance `input_id`/`filename`/`stage` intact |
| 2 design reference | `design_reference` ×1, one sofa, `material_hint="velvet"` on the planner's own item, **no** intent-added item |
| 3 style reference | `style_reference` ×1, zero intent-added items, zero generation requests |
| 4 inspiration only | `inspiration_only` ×1, zero chandeliers, `non_instantiation_compliance` 1.0 |
| 5 multiple references | 3 intents, 3 distinct provenances, **one** sofa |
| 6 conflict | `"2 references disagree on material for sofa: leather, linen"`, unresolved surfaced as needs-input, no silent pick |
| 7 missing asset | resolved `unresolved` with a reason (no generator configured in the harness) — never a silent box |
| 8 determinism | 20 forced re-plans of one project → **1** distinct signature (ids, classes, hints, rungs) |
| 9 reference limit | 6/8/10/12 uploaded → 6/8/10/12 classified, **0 unread**, `reference_ids` matches every time |
| 10 **real photos, real model** | **8 of 8 classified, 0 unread** → 5 `design_reference` + 3 `exact_object` |

Case 10 detail — attributes the old pipeline destroyed entirely, now captured
from the client's actual photographs:

```
ref_04  design_reference  sofa  upholstery "textured fabric"
                                descriptors: geometric pattern strip on backrest,
                                             segmented back cushion, rounded arms
ref_06  design_reference  sofa  upholstery "fabric"
                                descriptors: quilted pattern, two-tone, tufted buttons
ref_07  design_reference  sofa  upholstery "tufted fabric"
                                descriptors: wooden armrests with cross design
```

### Before / after

| | Before P12 | After P12 |
|---|---|---|
| References reaching classification in the live job | **0** (handler never called it) | **all of them** (8/8 real photos) |
| Reference cap | hardcoded 6 of 8, warning only | measured setting 12; 0 dropped at 6/8/10/12 |
| Reference provenance in the plan | none after `merge_reading_into_plan` | `input_id` → `intent_id` → object, queryable |
| Generator prompt from an intent | `''` | `sofa, sage, linen` |
| Conflicting references | silent single pick | recorded + `needs_input` |
| Duplicate from an exact reference | planner sofa + reference sofa | **one** sofa, enriched |

### Two defects the live benchmark caught that the P11 component benchmark could not

1. **The capability was unreachable in production.** `get_provider()` returns
   `ResilientProvider`, which forwards optional capabilities explicitly;
   `classify_reference` was not in that list, so every reference came back
   `unread`. The component benchmark called `MockProvider` directly and passed.
2. **A DESIGN_REFERENCE influenced nothing.** `apply_intents_to_plan` gated on
   `instantiate`, which only EXACT_OBJECT earns — so "a sofa like this" was
   dropped. Now appearance-influencing intents enrich an existing item while
   still being forbidden from creating one.

## 6. Authority — unchanged

`DesignIntent` has no position, rotation, scale or wall field
(`test_intents_never_carry_geometry`). `apply_intents_to_plan` emits
`ObjectPlanItem`s with **no coordinates**; `place_objects` decides every metre,
`repair_placement` may move objects, `validate_object` remains the single hard
gate. Intent changes *what is wanted and what it looks like* — never *where it
goes*. No second solver, no second selector: rung 2 calls `decide_asset`.

## 7. Regression

Full suite and every frozen benchmark re-run; results in the closing report.
`app/spatial/*`, `compiler.py` and `asset_decision.py` logic are untouched.

## 8. Remaining debt

1. **`pattern`, `frame_finish` and descriptor lists stop at the plan.** They
   live in `design_intent.json` and the `GenerationRequest` but have no
   `SceneObject` field, so they do not reach the manifest. Fix is a production
   schema change shared by store/patches/Blender — deliberately not bundled here.
2. **The generator still receives the image only.** Meshy image-to-3D
   (`openapi/v1/image-to-3d`) takes `image_url`/`enable_pbr`/`should_remesh`/
   `symmetry_mode`. The structured `GenerationRequest` is built and persisted,
   but **provider-side attribute propagation is pending** — inventing a vendor
   parameter would be worse than saying so. The text path's prompt is now
   attribute-derived.
3. **The moodboard round-trip still replaces planner items.** Neutralised by
   ordering, not removed.
4. **Room matching is by name/type, else the first room.** A reference whose
   `room_hint` matches nothing lands in the default room rather than being held
   for input; conflicting/uncertain intents already are.
5. **Mock classification is filename-derived.** Cases 1–9 therefore prove
   plumbing, not visual accuracy; case 10 is the real-model evidence.

## 9. Production readiness

| # | Question | Verdict |
|---|---|---|
| 1 | Live uploaded reference reaches DesignIntent | **PASS** — 8/8 real photos |
| 2 | DesignIntent reaches scene_plan | **PASS** — `_classify_references` + `apply_intents_to_plan` |
| 3 | Visual intent reaches asset resolution | **PASS** — hints + `resolve_all` |
| 4 | It reaches the final scene | **PARTIAL** — colour/material yes; pattern/frame/descriptors stop at the plan |
| 5 | Exact objects traceable | **PASS** |
| 6 | Visual attributes traceable | **PARTIAL** — see §3 |
| 7 | Style/inspiration prevented from instantiating | **PASS** |
| 8 | Conflicts explicit | **PASS** |
| 9 | Unresolved assets explicit | **PASS** |
| 10 | Solver still authoritative | **PASS** |
| 11 | Flow deterministic | **PASS** — 20 re-plans, 1 signature |
| 12 | Frontend receives the true terminal state | **PASS** — API + panel + job events |
| 13 | Real generator receives structured intent | **FAIL (pending)** — image only; see §8.2 |
| 14 | Current generator is Meshy | **PASS** — factual |
| 15 | Unreal integrated | **NO** — no such code exists |
| 16 | Hunyuan3D integrated | **NO** — no such code exists |

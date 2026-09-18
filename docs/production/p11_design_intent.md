# P11 — Design intent → 3D scene fidelity: audit and implementation

Date 2026-09-16. Audit first, then the change. Everything below cites code or a
measurement; nothing is inferred from the recording, which was not available to
me — the repository was the only source of truth.

## 0. Two premises in the brief that this repository does not match

| Brief says | Repository has | Consequence |
|---|---|---|
| "Unreal scene" / "Unreal asset/material assignments" | **No Unreal integration** — zero matches for `unreal` in any `.py/.ts/.tsx/.md`. The executor is Blender: `app/blender/manifest.py` is the single `Scene →` executor boundary, `blender/scripts/*` build and validate | Fidelity is measured **into the manifest rows that cross that boundary**. That is the same measurement for whatever renders them; an Unreal exporter placed behind `build_manifest` would inherit it unchanged |
| "Hunyuan3D-2.1 generation" | **No Hunyuan3D** anywhere. Image-to-3D is Meshy (`app/providers/meshy.py`, `openapi/v1/image-to-3d`, cloud, credit-metered) | The generation rung produces a **structured `GenerationRequest`** in our own domain (category + attributes + reference evidence) rather than a vendor-specific call. Meshy consumes it today; a local generator consumes the same object |

Confirmed with you before building. No Unreal or Hunyuan3D code was invented.

## 1. Where visual attributes were lost

Traced field by field from upload to Blender. Two losses are structural; the
rest follow from them.

| # | Hop | What is lost | Evidence |
|---|---|---|---|
| 1 | reference upload | **Nothing classifies a reference.** `ReferenceImage` is a file handle (`input_id`, `path`, `filename`, `content_type`) with no class, caption, room or weight. "The sofa I own" and "a mood I like" are indistinguishable | `app/intelligence/schema.py:23-44` |
| 2 | `analyze_input` → `SpottedObject` | `color` accepts **only a 7-char hex**, so every colour named in words ("sage green", "brushed brass") becomes `""`. No field exists for upholstery, pattern or frame/finish — they land in `notes`, which **has no downstream consumer at all**, and `ObjectPlanItem` has no `notes` field to receive it | `coerce.py:167-175,286,291`; `schema.py:106-145` |
| 3 | analysis → moodboard | The **only** channel from reference to plan is a generated image: a 34-word CLIP prompt with *hex deliberately stripped* ("CLIP cannot read hex codes") plus **one** IP-Adapter photo at strength 0.35, chosen from a fixed anchor list | `prompts.py:373,380,430`; `analyze.py:335-380`; `config.py:99` |
| 4 | **moodboard → plan (the fatal hop)** | A VLM reads the **render** back into `SceneElement`s — which carry **no link to any uploaded file** — and `merge_reading_into_plan` then **replaces the planner's items for that room outright**. After this line no object in the pipeline has any connection to anything the client uploaded | `scene_reading.py:400-402`; `schema.py:288-336` |
| 5 | plan → asset | Selection key is **`semantic_type` + dimensions**. `_score = fit × name_overlap × style_tags` — **no colour or material term exists anywhere in the ranker**; `material_tags` is never read by it. `color_hint` is used on the generated rung only; `material_hint` collapses to one of **four project-wide** materials; `style_notes` never affects which model is picked | `asset_decision.py:219-226,247-273,276-290` |
| 6 | asset → generator | Meshy image-to-3D receives **the crop image only** — name, colour and material never reach the vendor. The text path's `generation_prompt` omits `color_hint`/`material_hint`; measured on a real intent it was the **empty string** | `meshy.py:151-185`; `asset_decision.py:365` |
| 7 | scene → Blender | Per object the manifest carries `semantic_type`, dimensions, **one hex tint**, and one of four shared style materials. `style_notes`, `material_hint`, `family`, `element_id` do not exist on `SceneObject` | `manifest.py:48-105,209-228`; `compiler.py:297-315` |

**Where fidelity dies:** hop 4. Everything upstream is recoverable; once the
plan is replaced by a reading of a Stable Diffusion render, provenance is gone
by construction. The first *irreversible* field loss is hop 2.

## 2. The "first 6 of 8 references" behaviour — answered

**Verdict: neither intentional nor a token limit. An unmeasured cap, and a real
defect.**

- Source: `gemini_provider.py:136`, `_image_parts(self, bundle, limit: int = 6)` — a hardcoded default **no caller ever overrode**, while uploads allow 12 (`projects_routes.py:38 MAX_REFERENCES`). Unlike every other tuned constant in `config.py`, it carried no measurement comment and was not a setting.
- Measured (`research/p11_reference_capacity.py` → `docs/benchmarks/p11_reference_capacity.json`), real API, the live project's own references:

| images | HTTP | valid JSON | prompt tokens | total tokens | latency |
|---|---|---|---|---|---|
| 6 | 200 | yes | 7,814 | 9,598 | 9.8 s |
| 8 | 200 | yes | 9,967 | 12,132 | 11.3 s |
| 10 | 200 | yes | 12,160 | 13,740 | 6.4 s |
| 12 | 200 | yes | 14,338 | 15,139 | 4.3 s |

  All succeed. ~1.1 k prompt tokens per image; 15.1 k at twelve — nowhere near
  the model's context. **The cap was never a token limit.**
- One honest caveat: `spotted_objects` fell as images accumulated (6→6, 8→8, 10→5, 12→1). The 10 and 12 runs had to **repeat** images (the project has only 8), so that decline is confounded by duplicates and is *not* evidence about twelve distinct references. It is, however, a real reason not to trust one giant batch call.
- **Fix:** the cap is now the measured setting `gemini_max_reference_images = 12` (= `MAX_REFERENCES`, so no upload is ever dropped), with the measurement cited in `config.py`. More importantly, classification no longer depends on that batch at all — each reference is read on its own (§3), which removes the dilution risk instead of tuning around it.

## 3. What was built

All production code; nothing research-only entered the runtime path.

| Module | Role |
|---|---|
| `app/intelligence/design_intent.py` | `ReferenceClass` (the five classes), `POLICY` table, `VisualAttributes` (colour **words** + hex, material, upholstery, pattern, frame/finish, style + visual descriptors), `IntentProvenance`, `DesignIntent`, `IntentConflict`, `DesignIntentSet`, `merge_intents` |
| `app/intelligence/reference_reader.py` | One focused call **per reference** → typed intent; fail-safe coercion; nothing dropped silently |
| `app/intelligence/prompts.py` | `REFERENCE_CLASSIFICATION_SCHEMA` + `reference_classification_prompt` (class is `required`, so a model must commit) |
| `app/planning/intent_resolution.py` | The four-rung ladder, `GenerationRequest`, `apply_intents_to_plan` |
| `app/planning/intent_fidelity.py` | `visual_intent_fidelity` — four separate rates |
| providers | `classify_reference` on Gemini (real) and Mock (deterministic, filename-driven) |

**Class semantics** live in exactly one table (`POLICY`), so no consumer
re-derives them:

| class | instantiate | influences appearance | influences style | needs input |
|---|:-:|:-:|:-:|:-:|
| EXACT_OBJECT | **yes** | yes | yes | no |
| DESIGN_REFERENCE | no | **yes** | yes | no |
| STYLE_REFERENCE | no | no | **yes** | no |
| INSPIRATION_ONLY | no | no | no | no |
| UNCERTAIN | no | no | no | **yes** |

**The resolution ladder**, exactly as specified, with the bottom rung that did
not previously exist:

1. `EXACT_ASSET` — an asset already generated from this very reference (deterministic id, so a re-run never re-buys a mesh)
2. `COMPATIBLE_ASSET` — best registry asset **carrying the intent's own colour/material**. If it satisfies *none* of the stated attributes it loses to generation; with no generator it is returned with `needs_input=True`
3. `GENERATE` — a structured `GenerationRequest` (category + attributes + reference image + source intent ids). Prompt is *derived* from the attributes so it cannot drift from them
4. `UNRESOLVED` — said out loud, with a reason

`AssetDecision.strategy` still has no `unresolved` value; that is why rung 4
lives here rather than in `asset_decision.py`, which is called unchanged for
rung 2 — **no second selector was built**.

**Two behaviours the benchmark forced during development**, both real bugs in
the first implementation:

- Intent items were *appended* to the planner's list, so a client who uploaded their own sofa got **two sofas**. Now `apply_intents_to_plan` reconciles: the client's piece **becomes** the room's piece.
- Enrichment initially refused to overwrite (copying `apply_spatial_graph`'s rule) — so the planner's guess `material_hint="fabric"` silently beat the reference's `linen`. A reference is direct evidence about the actual piece and a planner hint is an inference from prose, so a **stated** attribute now wins and the note records `material_hint='linen' (was 'fabric')`. Unstated attributes are still left alone.

## 4. Authority — unchanged

AI classifies evidence; `DesignIntent` states intent; resolution picks an
asset; **the solver alone decides geometry**. `DesignIntent` has no position,
rotation or scale field, asserted by `test_intents_never_carry_geometry`.
`intent_plan_items`/`apply_intents_to_plan` emit `ObjectPlanItem`s with **no
coordinates**; `place_objects` still decides whether each piece fits and where.
No moodboard image can bypass the typed representation — classification reads
the *uploaded reference*, not the render. Nothing here produces construction
specifications, BOQ or execution dimensions.

## 5. Results

`research/p11_intent_benchmark.py` — **10/10 scenarios pass**, one per clause of
the brief, running the real production chain on the deterministic mock provider.

| Scenario | Result |
|---|---|
| exact reference → object in 3D | 1 sofa (not 2), plan item carries `material_hint='linen'` |
| colour/material reference → asset reflects it | prompt `sofa, sage, linen` (was `''`) |
| style-only → no extra object | 0 plan changes, style words `['japandi']` |
| inspiration-only → nothing instantiated | 0 plan changes, no merged category |
| multiple references → deterministic merge | order-independent; linen + tufted union |
| conflicting references | material blanked, conflict recorded, `UNRESOLVED` + `needs_input` |
| missing asset → generation fallback | `GENERATE` with attributes; without a generator → `needs_input` |
| generated asset → metadata + placement | request carries category/attributes/sources/reference; placed by `place_objects` |
| refresh/retry | 20 runs, 1 distinct result |
| traceable into the executor | `non_instantiation_compliance` 1.0, no violations |

Measured `visual_intent_fidelity` on the traceability scenario:
`instantiation_fidelity 1.0`, `appearance_fidelity 1.0`,
`non_instantiation_compliance 1.0`, `traceability 0.0217`. The last number is
honest and its denominator matters: **all 47 scene objects**, of which only the
reference-derived ones can trace to a photo — with three references in a
five-room flat, that is the correct figure, not a defect. It is the number that
should rise as more of the design is reference-driven.

## 6. Regression

Full backend suite and all frozen benchmarks re-run after the change —
results recorded in the final summary. `app/spatial/*` and the solver were not
touched; `decide_asset`'s own logic is unchanged (it is *called*, not edited).

## 7. Remaining debt, stated plainly

1. **The lossy moodboard round-trip still exists.** P11 adds a typed channel beside it; it does not remove `merge_reading_into_plan`'s replacement of planner items (`scene_reading.py:400`). Both paths now feed the plan. Removing the round-trip is a larger change with its own regression surface.
2. **Not yet wired into `scene_plan`.** The chain is production code with tests and a benchmark, but the handler does not call it yet, so a live project's references are not classified until that wiring lands. That is deliberate — it is a behaviour change to a paid, user-visible path and belongs in its own reviewed step.
3. **Catalogue assets carry no colour/material vocabulary a client would use**, so rung 2 frequently measures `attribute_fidelity = 0` and escalates to generation. Tagging the registry would let more intents be satisfied without paying a generator.
4. **`SpottedObject.color` still accepts hex only** — the words now survive on `VisualAttributes`, but the older analysis path is unchanged.
5. **Meshy image-to-3D still receives the image alone.** The structured request exists; sending its attributes needs a vendor parameter I could not verify against the v1 API, so I did not invent one.

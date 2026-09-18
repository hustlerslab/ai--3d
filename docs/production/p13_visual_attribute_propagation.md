# P13 — Visual attributes reach the executor

Date 2026-09-16. P12 left exactly one gap: colour words, pattern, frame finish
and descriptors survived into `DesignIntent` and the plan, then stopped, because
`SceneObject` had nowhere to put them. P13 closes that and nothing else.

## 1. Audit — where each field stopped (before)

Read from the code, not inferred.

| Field | DesignIntent | ObjectPlanItem | SceneObject | Manifest | Stopped at |
|---|---|---|---|---|---|
| `color_hex` | `attributes.color_hex` | `color_hint` | `color` (`_object_color`, compiler.py:297) | `"color"` | — reached |
| `material` | `attributes.material` | `material_hint` → role | `material_overrides["primary"]` | `"material_overrides"` | — reached (as a registry id) |
| `upholstery` | `attributes.upholstery` | `material_hint` (preferred) | same channel | same | — reached |
| `color_words` | `attributes.color_words` | folded into `name` only | **absent** | **absent** | **ObjectPlanItem** |
| `pattern` | `attributes.pattern` | **absent** | **absent** | **absent** | **intent_to_plan_item** |
| `frame_finish` | `attributes.frame_finish` | **absent** | **absent** | **absent** | **intent_to_plan_item** |
| `descriptors` | `style_descriptors` + `visual_descriptors` | flattened into `style_notes` (a string) | **absent** | **absent** | **ObjectPlanItem** |

The three hint fields (`color_hint`, `material_hint`, `style_notes`) are a
*lossy projection* built for the asset ladder: one hex, one material bucket, one
prose blob. Four attributes had no destination beyond it.

## 2. Schema change — the minimum

**`app/scene/schema.py`** gains `ObjectVisual` and `SceneObject.visual`:

```python
class ObjectVisual(BaseModel):
    color_words: list[str] = []
    material: str = ""          # the WORD ("linen"), not the registry id
    upholstery: str = ""
    pattern: str = ""
    frame_finish: str = ""
    descriptors: list[str] = []
    source_intent_ids: list[str] = []
```

Deliberately **parallel to** `intelligence.design_intent.VisualAttributes`
rather than importing it: `app/scene/schema.py` imports nothing from `app/`, and
the canonical, executor-facing `Scene` must not start depending on the
intelligence package — a provider change could then alter the scene type.

`style_descriptors` and `visual_descriptors` merge into one `descriptors` list:
the distinction is about *classifying a reference*, not about describing the
object it produced.

No geometry enters the block — asserted by
`test_visual_attributes_carry_no_geometry`. No construction or procurement
figure either; these are descriptive words the client used.

**`app/intelligence/schema.py`**: `ObjectPlanItem` gains
`visual: VisualAttributes` and `source_intent_ids: list[str]`. The three hint
fields stay exactly as they were, so the asset ladder is untouched.

## 3. Population — from the correct upstream source

`intent_to_plan_item` now carries the whole attribute block plus the intent ids;
`apply_intents_to_plan` merges it under the P12 rule, unchanged:

> an attribute the reference **stated** wins over a planner guess; one it never
> mentioned leaves the planner's value alone.

Measured on the real path: `material_hint='linen' (was 'fabric'), visual.material='linen'`
appears in the job feed, so every replacement stays auditable.

`compiler._object_visual(item)` maps plan item → `ObjectVisual` at the single
place `SceneObject` is constructed. A planner-only item produces an empty block.

## 4. Persistence, patches, retry

| Path | Result |
|---|---|
| Scene JSON save/reload (`app/scene/store.py`) | preserved — pydantic round-trip, tested |
| `UpdateObjectOp` | **structurally safe**: the op patches named fields (`object_id`, `color`, `locked`, `semantic_type`) and never replaces the object, so `visual` cannot be clobbered. Tested with a real colour patch |
| Checkpoint / `force` re-plan | preserved, one object, identical block over 20 runs |
| Pre-P13 stored scenes | load unchanged — `default_factory=ObjectVisual`, tested explicitly |
| Canonical P7 serialization | unaffected (it serializes `Scene` wholesale) |

## 5. Manifest

The object row gains `"visual"` **only when non-empty**:

```python
**({"visual": o.visual.model_dump()} if not o.visual.is_empty() else {}),
```

So a scene with no reference-derived objects produces a **byte-identical**
manifest to pre-P13 — asserted by
`test_a_planner_only_object_adds_nothing_to_the_manifest`. `color`,
`material_overrides`, `dimensions` and every existing consumer are untouched.

## 6. Executor behaviour — what Blender can actually do

Derived by reading `blender/scripts/apply_materials.py`, not assumed.
`for_object` consumes exactly two things: `material_overrides["primary"]` (a
registry material with real PBR maps) and `color` (a hex tinted in at strength
0.85). There is **one material slot per object** and **no pattern synthesis**.

| Reference attribute | Scene attribute | Executor behaviour |
|---|---|---|
| `color_hex` | `color` | **PRESERVED_AND_RENDERED** — tinted at 0.85 |
| `material` | `visual.material` | **PRESERVED_AND_RENDERED** — via the registry material id |
| `upholstery` | `visual.upholstery` | **PRESERVED_AND_RENDERED** — same channel, preferred over material |
| `color_words` | `visual.color_words` | **PRESERVED_METADATA_ONLY** — no colour-word→hex resolution exists in the repository; resolving against the material registry's own `base_color`s is a scoped future step, **not invented here** |
| `pattern` | `visual.pattern` | **PRESERVED_METADATA_ONLY** — "quilted" cannot become geometry or a map |
| `frame_finish` | `visual.frame_finish` | **PRESERVED_METADATA_ONLY** — one material slot, so a frame distinct from the upholstery has nowhere to land |
| `descriptors` | `visual.descriptors` | **PRESERVED_METADATA_ONLY** — influences asset *selection* upstream; the executor consumes no words |

This table lives in code as `VISUAL_ATTRIBUTE_CONTRACT`
(`app/planning/intent_fidelity.py`) so the benchmark, the fidelity report and
this document cannot drift apart, and
`test_the_executor_contract_never_claims_more_than_blender_does` pins it.

**Nothing is faked.** Four attributes cross the boundary as semantic metadata
and are reported as such. Calling that "rendered" would be the fabricated
success this programme keeps refusing.

## 7. Benchmark — the real path

`research/p13_attribute_propagation_benchmark.py` →
`docs/benchmarks/p13_visual_attribute_propagation.json`. **10/10 pass**, driving
the real HTTP routes, job runner and `scene_plan` handler.

| Case | Result |
|---|---|
| 1 colour word | `["sage"]` on the object and in the manifest; `color` still rendered |
| 2 pattern | `"quilted"` on object + manifest; reported `preserved_metadata_only` |
| 3 frame finish | `"…walnut"` on object + manifest |
| 4 descriptors | present on object + manifest |
| 5 combined | all five survive **independently**; manifest mirrors the scene exactly |
| 6 explicit vs inferred | `linen` beats planner `fabric`, **one** sofa, audit trail recorded |
| 7 conflict | conflict recorded, unresolved surfaced, contradicted material left blank |
| 8 save/reload | identical block |
| 9 patch | colour patched to `#123456`, `visual` untouched |
| 10 retry ×20 | 1 distinct block, 1 sofa every run |

## 8. Fidelity

`FidelityReport.survival` now breaks reference-to-scene survival down per
attribute — never averaged into `metrics`:

```
attribute      stated  reached  rate   executor
color_words       1       1     1.0    preserved_metadata_only
color_hex         1       1     1.0    preserved_and_rendered
material          1       1     1.0    preserved_and_rendered
upholstery        1       1     1.0    preserved_and_rendered
pattern           1       1     1.0    preserved_metadata_only
frame_finish      1       1     1.0    preserved_metadata_only
descriptors       1       1     1.0    preserved_metadata_only
```

The P11/P12 four rates are unchanged in definition and still reported
separately. **Semantic preservation 7/7; executor-rendered 3/7** — two numbers,
never one.

## 9. Real-project evidence

P12's case 10 already classified the live project's 8 real photographs with the
real Gemini model (8/8, 0 unread) and captured attributes the old pipeline
destroyed — `upholstery "tufted fabric"`, descriptors `["quilted pattern",
"two-tone", "tufted buttons"]`, `"wooden armrests with cross design"`. Those are
exactly the fields P13 now carries to `SceneObject` and the manifest. The live
project's own scene was **not** rebuilt: you deliberately rolled it back to its
moodboard state, and re-planning it would undo that and spend Gemini quota, so
the propagation is proven on the real code path with real attributes rather than
by overwriting your project.

## 10. Remaining limitations

1. **Four attributes are metadata, not pixels.** Rendering `pattern` needs
   texture synthesis; `frame_finish` needs a second material slot in
   `apply_materials`; `color_words` needs a word→hex resolution. All three are
   executor changes with their own regression surface.
2. **Provider-side generation attribute propagation remains pending** (P12's
   finding, untouched here by instruction): the structured `GenerationRequest`
   is persisted and traceable, but Meshy's `openapi/v1/image-to-3d` accepts
   `image_url`/`enable_pbr`/`should_remesh`/`symmetry_mode` only. No vendor
   parameter was invented.
3. **Mock classification is filename-derived**, so benchmark attribute *values*
   are crude (`frame_finish` came out as `"sage linen dark walnut"` from a long
   filename). That measures propagation, not classification quality; P12's case
   10 is the real-model evidence.
4. **`material` appears twice** — as a word in `visual.material` and as a
   resolved registry id in `material_overrides`. Deliberate: the client's word
   and the thing Blender paints are different facts.

## 11. Boundary — unchanged

vision **Gemini** · asset generation **Meshy** · executor **Blender**. No
Hunyuan3D and no Unreal integration exists in this repository, and P13 did not
begin either. The solver remains the sole geometry authority; `ObjectVisual`
carries no coordinate.

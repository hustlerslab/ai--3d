# P14 — Visual Attribute Rendering

P13 proved seven visual attributes reach the executor boundary intact. P14 asks
the harder question: **which of them actually change pixels in Blender**, and
can any of the four that did not be promoted without inventing behaviour.

The answer is two of the four, one of them only sometimes, and the reason the
other two stay put is measured rather than asserted.

Stack for this phase is frozen: Gemini for vision, Meshy for asset generation,
the Allure Spatial Engine for layout, Blender for execution. Nothing was added,
replaced or migrated.
replaced or migrated.
replaced or migrated.

---

## 1. Result in one table

| Attribute | Before P14 | After P14 | What actually happens in Blender |
|---|---|---|---|
| `color_hex` | rendered | rendered | tinted into the object's material at strength 0.85 |
| `material` | rendered | rendered | resolved to a registry material with its PBR maps |
| `upholstery` | rendered | rendered | same channel, preferred over `material` when both are stated |
| **`frame_finish`** | metadata only | **conditionally rendered** | painted onto the trim meshes, on assets that have a second material region |
| **`descriptors`** | metadata only | **conditionally rendered** | a part-naming descriptor supplies the frame finish above |
| `color_words` | metadata only | metadata only | unchanged, and deliberately so |
| `pattern` | metadata only | metadata only | unchanged, and deliberately so |

Two attributes moved. Two did not. The `CONDITIONALLY_RENDERED` tier is new in
this phase and exists precisely so that "sometimes" is not reported as "yes".

---

## 2. The mechanism

Nothing here is a new subsystem. Each piece reuses something the codebase
already had.

**Resolve the word.** `finish_material_for` in the planning compiler mirrors the
existing `material_for` surface-word resolver. It maps a finish phrase onto a
material that is already in the registry and already declares
`applies_to = furniture`: walnut, oak, brass, blackened metal, clear glass. A
phrase with no registry match resolves to the empty string. "Hand-carved teak
inlay" gets nothing, and getting nothing is the correct answer, because
repainting a piece the wrong species is worse than leaving the catalogue's own
look alone.

**Check the geometry can take it.** `material_slots` in the glTF reader reports
the distinct materials the mesh primitives actually use. It reads the file
rather than trusting the material list, so a declared-but-unreferenced material
cannot fake a frame region. The manifest calls this per asset, cached by path.

**Decide honestly, per object.** `_finish_entry` in the manifest builder emits a
`finish` block carrying the resolved material, the region count, and a `state`
of `rendered`, `metadata_only`, `unsupported` or `none`, with a `reason` string
whenever it is a limit rather than a success. A single-region asset says so, in
words, in the manifest.

**Paint only the trim.** `_apply_frame_finish` in the Blender import script is
the deliberate mirror of `_apply_upholstery`. That function re-skins every mesh
at or above 12% of the piece's area and leaves the rest alone, because "legs,
feet and trims keep their own look". Those skipped small meshes are exactly what
a frame finish describes, so the new function paints them and never touches the
body. It runs only when the manifest already said `rendered`.

Isolation matches the existing function exactly: `m.data.copy()` before any
assignment, because Blender shares mesh data between linked duplicates and
shares material datablocks by name. The material library's cache is read, never
mutated.

---

## 3. What the real asset library allows

Every one of the 58 registry assets was parsed. No sampling.

| Measure | Count |
|---|---|
| Assets read successfully | 58 of 58 |
| Assets with more than one material region | 10 |
| Assets whose region names include a frame, leg or base word | 5 |
| Assets with a single material region | 48 |
| Assets with UV coordinates | 58 |
| Assets that could carry a synthesised pattern | 0 |

So a frame finish is paintable on 10 of 58 pieces. On the other 48 the manifest
reports `metadata_only` and states why. That 17% is the honest ceiling the asset
library imposes today, and it is a library property, not a bug in the resolver.

Worth noting for anyone extending this: of the 10 multi-region assets, several
split into glass, foliage or artwork rather than a frame. The 12% area guard
keeps the finish on genuinely small trim meshes, but an asset library authored
with named frame regions would raise both the count and the precision.

---

## 4. The finding that matters most

The executor mechanism works. It is also, today, barely reachable, and the
reason sits upstream of everything P14 touched.

Eight real project photographs were classified through the live Gemini provider,
not the mock. The provider was called directly so that a fallback could not
quietly turn the measurement into fiction.

| Field | Populated on |
|---|---|
| `upholstery` | 8 of 8 |
| `visual_descriptors` | 8 of 8 |
| `frame_finish` | 0 of 8 |
| `color_words` | 0 of 8 |
| `color_hex` | 0 of 8 |
| `material` | 0 of 8 |
| `pattern` | 0 of 8 |
| `style_descriptors` | 0 of 8 |

The model never fills `frame_finish`. It does describe the frame, it simply puts
the words somewhere else. One reference says "wooden frame", another "gold
accent trim", a third "wooden armrests". The evidence is present and
well-formed; it is landing in the wrong field.

That is why `descriptors` was promoted. A descriptor that **both** names a
structural part and resolves to an existing registry material supplies the frame
finish, through the identical resolver and the identical region guard. Two of
the eight real references carry frame evidence this way.

The part requirement is what keeps this defensible. We paint only trim meshes,
so we only act on evidence about trim. "Wooden frame" fires. "Glass coffee
table" does not, because it describes the whole object. Bare "walnut" does not,
because it names no part. "Luxurious" does not, because it resolves to no
material at all. A stated `frame_finish` always beats a descriptor, and a
descriptor-derived finish is recorded as `finish.source == "descriptor"` so the
fidelity report never counts it as a stated attribute surviving.

---

## 5. What was deliberately not promoted

**Colour words.** There is no authoritative word-to-hex mapping anywhere in the
repository. Turning "sage green" into a hex value would mean inventing one. The
rendered colour channel remains `color_hex`, which the model populates 0 times
out of 8 anyway. Resolving colour words against the material registry's own
`base_colors` is a real future step and is deliberately not attempted here.

**Pattern.** There is no procedural pattern or texture synthesis in the Blender
path, and no asset in the registry can carry one. "Quilted" cannot become
geometry or a map. Emitting a noise texture to make the number look better would
be exactly the inflation this phase was told not to perform.

**Surface quality descriptors.** `matte`, `satin` and `glossy` are resolved into
`finish.roughness` in the manifest, and **no Blender script reads that key**.
The value is carried, not applied. An earlier draft of this phase's contract
claimed it as a rendering mechanism; that claim was wrong and has been removed,
which lowers the number this phase reports. A regression test now scans the
executor scripts and fails if any of them starts reading `roughness` without the
contract being updated to match.

Those words also appear in 0 of the 8 measured references, so wiring them would
have been a mechanism with no demonstrated demand.

---

## 6. Two rates, never one number

| Rate | Value |
|---|---|
| Preservation (P13) | 7 of 7 attributes reach the manifest |
| Rendered, `color_hex` | 1.00 |
| Rendered, `material` | 1.00 |
| Rendered, `upholstery` | 1.00 |
| Rendered, `frame_finish` | 0.17 (10 of 58 assets) |
| Rendered, `color_words` | 0.00 |
| Rendered, `pattern` | 0.00 |
| Rendered, `descriptors` | not a fixed rate; depends on the words a reference used |

There is no single "visual similarity" score, and there should not be. A number
that averages "the colour is right" with "the pattern is imaginary" tells a
reader less than the two facts stated separately.

---

## 7. Compatibility

- A scene with no `visual` block produces a manifest with no `finish` key, so
  every pre-P13 scene still renders byte-identically.
- `material_overrides["primary"]`, the upholstery channel, is untouched. A linen
  sofa with a walnut frame stays a linen sofa.
- The frame finish travels in its own manifest key and cannot displace the body
  material or the hex colour.
- `finish` gained one field in this phase, `source`. Nothing was removed.

---

## 8. Verification

Full suite: 812 passed, 7 skipped, 30 xfailed. That is the 768-test baseline
plus the 44 new P14 regression tests and nothing else; no existing test changed
result. The P13 executor-contract test was updated in this phase to expect the
new three-tier model, which is the intended consequence of adding the tier.

Benchmarks: P11 10/10, P12 10/10, P13 10/10, P14 11/11. The frozen P4 to P10
spatial architecture benchmarks were re-run and report their recorded figures
unchanged: 30/30 constraint, 40/40 candidate, 22/22 scene, 12/12 repair, 10/10
clearance, and a P10 system success rate of 1.0, all still deterministic.

Artifacts:

- `docs/benchmarks/p14_visual_attribute_rendering.json`
- `docs/benchmarks/p14_reference_extraction.json`
- `aether-backend/tests/test_p14_visual_rendering.py`

---

## 9. Honest remaining limitations

1. **Extraction, not rendering, is the binding constraint.** The reference
   classification prompt never asks Gemini for a frame finish in a way that gets
   one. Fixing that prompt would do more for visual fidelity than any further
   executor work.
2. **48 of 58 assets cannot take a frame finish at all.** Authoring or
   regenerating assets with separated, named frame regions raises the ceiling.
3. **Pattern remains unreachable** without texture synthesis, which is a far
   larger piece of work than this phase.
4. **Colour words remain unmapped**, pending a resolution against the material
   registry's own base colours.
5. **The 12% area heuristic is a proxy for "this is trim".** It works on the
   measured library. It is not a semantic understanding of the model.

# P2-RENDER-001 — PBR materials from the registry · verification

**2026-09-26 · Hat:** Blender Engineer (+ 3D Engineer) · **Blender:** 5.2.1 LTS (real) · **Meshy spend: 0**

## The gap, found by reading the chain end to end

The registry's `roughness` and `metalness` already reached Blender (`manifest._material_entry` → `apply_materials.MaterialLibrary.get` sets them on the Principled BSDF). So for the 23 built-in materials, none of which has maps, the registry value already drives the render. The inconsistency task.md describes was elsewhere: **when a material has a roughness texture map, the map was wired straight into the Roughness input and the registry value was ignored entirely.** Changing it changed nothing. Scanned (Poly Haven) materials, the photoreal ones, are exactly the ones with maps.

## Built

| Where | What |
|---|---|
| `blender/scripts/apply_materials.py` | **glTF metallic-roughness semantics.** A roughness map now passes through a multiply node: rendered roughness = the map × the registry's roughness (clamped). With no map, the registry value is the roughness, as before. One field, one meaning |
| `app/materials/pipeline.py` `attach_maps` | A **new** material that arrives with a roughness map and no explicit value gets factor **1.0** (glTF's default when a texture is present), so it renders exactly as scanned. Existing records are never rewritten |
| `app/materials/schema.py` | The field's meaning is documented where it's defined |
| `app/assets/validation.py` `material_workflow` | **Every asset must be glTF metallic-roughness.** An asset declaring the specular-glossiness extension is a **hard** issue (kept out of the catalog); a material with no metallic-roughness values is **warned**, by name, because glTF defaults would render it as bare metal |
| `scripts/audit_material_workflow.py` (new) | Audits the library already on disk: each asset's normalized file against the same rule, and every mapped material whose factor is not 1.0 (a scan registered before this change) listed for a person to review |

## Found while building it: a real leak in the material registry

`MaterialRegistry.__init__` held the **module-level seed objects** for the built-in materials. `get()` hands those out, and callers mutate them (`attach_maps`, a roughness edit), so every such edit leaked into **every registry built later in the process**, persisted or not. It surfaced as `wood_oak` appearing "mapped" in a test that never touched it. Fixed by giving each registry its own copies; `test_editing_a_built_in_material_does_not_leak_into_the_next_registry` pins it. It could have silently changed renders across projects handled by one server process.

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| **Changing a registry roughness value changes the render** | Real Blender, the same room. Built-in `wood_oak` (no map) at 0.9 vs 0.05: **2.2%** of pixels change. A mapped scan at factor 1.0 vs 0.1: **6.3%**, and the node graph Blender actually built shows the map feeding a multiply node whose factor equals the registry value. Threshold: 0.1% (P1-QA-004). The renders show a matte floor at 1.0 and a glossy, reflective floor at 0.1 |
| **Every registry asset is valid GLB with metallic-roughness materials** | Enforced at ingest (`material_workflow`, unit-tested). A specular-glossiness upload through the real ingest pipeline is kept out (`record.valid` is false) |

Renders are in this folder: `scalar_wood_oak_roughness_*.png`, `mapped_scan_floor_factor_*.png`, plus `measurement.json`.

## Mutations (6/6 caught, each restored sha1-identical)

| Mutation | Caught by |
|---|---|
| **the original behaviour** (map wired straight into Roughness) | real-Blender mapped test, which fails on the old code, proving the gap was real |
| the factor ignores the registry value | real-Blender mapped test |
| new scans keep the 0.8 scalar default | ingest-rule test, audit test |
| the registry shares the seed objects again | leak regression test, audit test |
| specular-glossiness not refused | unit test and the real-ingest test |
| bare materials not warned | unit test |

## Full suites

Backend `class=MOCK passed=1550 failed=1` (+10; the same pre-existing CLIP test) · `class=PRODUCTION-PATH passed=30` (+2) · the visual regression baseline (P1-QA-004) still matches, so the default render did not move · failure-injection matrix 18/18.

## Owed (not claimed)

- **Run the audit on the machine that holds the real library:** `python scripts/audit_material_workflow.py --json "version 4/evidence/P2-RENDER-001/library_audit.json"`. Scans registered before this change keep factor 0.8 and now render slightly glossier than their scan. The audit lists them; setting each to 1.0 (or its intended value) is a person's decision, not a silent migration. Assets using specular-glossiness would be listed as failures.
- Metalness has no map path (no scanned metallic maps are ingested), so it stays a scalar. That is consistent, not a gap.
- The workflow rule checks declared materials. A primitive with **no** material at all falls back to the importer's default and is not flagged.

# Phase 10 — Asset Normalisation Audit

**Verdict: PASS, as an audit.** Every one of the **58** registry assets re-measures
from its normalised mesh to within **2 cm per axis** of its recorded dimensions,
sits on a **bottom-centre pivot** (min-y and x/z-centre within 2 cm of zero), and
is furniture-sized in metres. Nothing was rejected. Eight assets carry a metadata
inconsistency — on-surface objects recorded as `floor` mount — that the placement
engine must resolve from the vocab rather than from the record. The forward axis
(−Z = front) cannot be verified from geometry and is recorded as unverified.

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/asset_audit_results.json`
**Script:** `research/spatial_engine/asset_audit.py`
**Production code changed:** none. Registry changed: none.

## 1. Objective

Every asset entering the spatial engine must have normalised geometry — metres,
+Y up, −Z forward, bottom-centre pivot — and the record must agree with the mesh.
Verify it rather than assume it.

## 2. What already exists

`app/assets/normalization.py` computes a single root TRS (unit scale, optional
yaw, bottom-centre translation) at ingest; `app/assets/validation.py` rejects
empty, NaN, over-large and over-heavy meshes. `AssetRecord.dimensions` is
post-normalisation. This audit re-measures the *normalised* file with the same
`gltf.measure` and compares. **[M]**

## 3. Results **[M]**

| | |
|---|--:|
| Assets in the registry | 58 |
| Accepted (no hard issue) | **58** |
| Dimensions within 2 cm per axis of the record | 58 / 58 |
| Bottom-centre pivot within 2 cm | 58 / 58 |
| Scale plausible (0.03–8 m) | 58 / 58 |
| Providers | Meshy 30 · Poly Haven 28 |
| Licences | `CC0-1.0` (Poly Haven) · `meshy-commercial` |
| Mounts | floor 43 · wall 8 · surface 5 · ceiling 2 |
| Warnings | 8 × `MOUNT_DISAGREES_WITH_VOCAB` |

**The eight warnings** — `ph_diya_lantern`, `ph_vase_01`, `ph_wooden_elephant`,
`ph_marble_bust`, `ph_throw_pillows`, two `other` elements, one `tv_unit` — are
objects the vocab places `on_surface` (or, for the TV element, whose type is
ambiguous) recorded with `mount: floor`. The solver's `PLACEMENT_BY_TYPE` already
routes these by vocab, so placement is unaffected today; the records are wrong
and should be corrected at ingest. **[M]**

**Not verifiable from geometry:** the forward axis. Whether −Z is the front of a
sofa is a semantic fact; the normaliser applies a `yaw_offset` supplied at ingest
and nothing can check it against the mesh. Recorded per asset as unverified.
**[N]**

## 4. Decision

The registry's spatial metadata is trustworthy for dimensions, pivot and scale —
which is what Phases 7 and 9 relied on, and why the catalogue-grounded extent
could use registry medians at 0.9 confidence. Two items to fix at the source:
the eight mount records, and a forward-axis check at ingest (a rendered
thumbnail from −Z, reviewed once).

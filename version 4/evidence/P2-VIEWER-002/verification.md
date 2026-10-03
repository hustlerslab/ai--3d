# P2-VIEWER-002 — Compressed web assets · verification

**2026-09-26 · Hat:** 3D Web Engineer (+ Backend Engineer, DevOps for the CI step) · **Meshy spend: 0**

## Why this was not blocked after all

The ledger listed this as waiting on "Draco/KTX2 tooling installed". Checked rather than assumed: the Draco half needs no system install. It needs gltf-transform (npm, the standard tool for the job, used here as a pinned subprocess) and, for independent checks, DracoPy (pip, ships a Windows wheel). Both installed in seconds. **KTX2 does need a native install** (KTX-Software's `toktx`), so it is not done; the task asks for "Draco **and/or** KTX2" (see correction below).

## Built

| Where | What |
|---|---|
| `aether-backend/tools/package.json` (+ lock) | gltf-transform **pinned exactly** at 4.5.0; `npm ci` there. A test fails if the pin becomes a range |
| `app/assets/web_variant.py` | After the texture resize, `compress_geometry` Draco-compresses the **web copy only** (`KHR_draco_mesh_compression`, declared *required*). Quantization is set explicitly: position 14 bits (0.12 mm across a 2 m sofa), normal 10, UV 12. **Never fatal, never bigger:** with no tool, a failed or killed run, or a result that is not smaller, the copy ships uncompressed with the reason logged, and no temp file is left |
| `app/assets/pipeline.py` | The web copy is kept when it helps in **any** way (`worth_keeping`). Before, it existed only when textures were resized, so a model with small textures sent its full uncompressed geometry |
| `scripts/backfill_web_variants.py` | Rebuilds pre-existing web copies that are not yet Draco; skips ones that are |
| `app/core/config.py` | `gltf_transform_path` (empty = the pinned copy, then PATH) |
| `aether-frontend/public/draco/` + `scene-meshes.tsx` | **Found:** drei's `useGLTF` fetches its Draco decoder from **Google's CDN (gstatic.com)** by default. Once the models are Draco, that would mean a third-party request on every first 3D load, and no 3D at all wherever it is blocked. The decoder is now three.js's own copy, served by the app from `/draco/`, and passed to the loader as `DRACO_DECODER_PATH` |
| `.github/workflows/ci.yml` | `npm ci` in `aether-backend/tools`, so CI runs the compression tests (they fail, never skip, without the tool) |
| `requirements.txt` | DracoPy, used only by tests to decode independently of the encoder |

**Blender continues reading the uncompressed normalized copy:** `app/blender/manifest.py` reads only `normalized/`, and a test pins that the manifest hands Blender the uncompressed file.

## Measured: a model shaped like an image-to-3D result

32,768 triangles (position + normal + UV), two 2048 px maps:

| | bytes |
|---|---|
| Full model (Blender's copy) | 3,567,264 |
| Web copy, textures resized, before P2-VIEWER-002 | 2,092,020 |
| **Web copy now, + Draco** | **1,220,044** |

The Draco step removes **94%** of the geometry bytes (871,976 of 925,728) and **42%** of the whole web copy. Textures pass through **byte-identical**. Draco shrinks the download, not GPU memory: the browser decodes back to the same triangles.

## Acceptance

| Required | Evidence |
|---|---|
| Draco and/or KTX2 applied to the web variant | the web copy carries `KHR_draco_mesh_compression` in `extensionsUsed` **and** `extensionsRequired`; decoded geometry has every triangle with area (Draco drops only zero-area ones, 125 of the sphere's 256 pole triangles), total surface area within 0.0004%, and every vertex within one 14-bit grid step of a real source vertex. Decoded by **DracoPy**, a separate binding from the encoder |
| Blender keeps the uncompressed normalized copy | the ingest test checks the normalized file has no Draco and is what `_asset_entry` hands Blender (mutation: manifest pointed at `web/` was caught) |
| Measurably smaller web payloads | table above; the test requires the Draco step to remove more than 60% of geometry bytes, and the web copy to be under half the full model |
| Valid glTF | the Khronos glTF validator (bundled in gltf-transform): **0 errors** |
| The viewer can decode it | vitest: the decoder served from `public/draco/` is byte-identical to three.js's shipped copy and decodes a genuine backend-compressed fixture (every visible triangle, bounds within one quantization step). **In the browser** (dev server, `localhost:3001`, no sign-in needed): all three decoder files are served 200 (`application/wasm` for the wasm), the **WASM** decoder starts, and it decoded the same fixture: 1,131 of 1,152 triangles (the rest are zero-area), bounds 0.8 × 0.9 × 0.5 m to within 0.04 mm |

## Mutations (9/9 caught, each restored sha1-identical) — `mutations.txt`

| Mutation | Caught by |
|---|---|
| build no longer compresses | the compressed-and-smaller test |
| a bigger "compressed" file is kept | the never-bigger test |
| web copy kept only when textures shrink (the old rule) | small-textures test |
| positions quantized to 8 bits | the decoded-geometry test |
| a failed run leaves its temp file | failing-tool test. **This one was missed at first**: the stand-in tool exited without writing anything, so there was no temp file to leave. The stand-in now dies half-way through writing, as a crashed run does |
| decoder fetched from the CDN again | frontend: never-a-CDN test |
| loader not given the app's decoder | frontend: loader-path test |
| served decoder drifts from three's | frontend: byte-identical test |
| Blender handed the web copy | ingest test |

**Found while testing:** Python decoded gltf-transform's UTF-8 output as cp1252 on Windows and crashed its reader thread. Fixed in the app (`encoding="utf-8", errors="replace"`), not only in the test.

## Correction (C18)

task.md frames the whole task as waiting on tooling; the Draco half needed only `npm ci` and `pip`. KTX2 (texture compression, which would cut GPU memory as well as download) does need KTX-Software's native `toktx` and is **not done**. It stays a follow-up; the texture resize from before already caps GPU memory at 1024 px.

## Owed

- **Real-library measurement:** run `python scripts/backfill_web_variants.py` on the machine that holds the real `data/` asset library, and record before/after bytes. There is no library here.
- **Signed-in check:** a real generated piece loading in the studio's 3D view, with the network panel showing `/draco/` and no gstatic request. This needs a signed-in session, which this agent does not create.
- **KTX2**, as above.

**Full:** backend `class=MOCK passed=1560 failed=1` (pre-existing `test_room_prompt.py::test_the_budget_is_measured_with_clip_not_guessed`) · `class=PRODUCTION-PATH passed=30` · frontend vitest 146 passed, tsc + lint clean, generated types current.

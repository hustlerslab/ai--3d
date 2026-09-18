# Spatial engine Phase 2, Step 1 — metric geometry model cost

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/metric_geometry_benchmark.json`
**Script:** `research/spatial_engine/metric_geometry_benchmark.py` · No production code changed.

## Step 0 — licences, from primary sources

| Model | Code licence | Checkpoint licence | Commercial | Source |
|---|---|---|:--|---|
| **MoGe-2** (`Ruicheng/moge-2-vitl`) | **MIT** (vendored DINOv2 Apache-2.0) | **MIT** (stated on the HF model card) | **PERMITTED** | [repo](https://github.com/microsoft/MoGe), [card](https://huggingface.co/Ruicheng/moge-2-vitl) |
| **UniDepthV2** | **CC BY-NC 4.0** | not separately stated | **PROHIBITED** | [repo](https://github.com/lpiccinelli-eth/UniDepth) |
| Depth Anything V2 Small | Apache-2.0 | Apache-2.0 (Small only) | PERMITTED | [repo](https://github.com/DepthAnything/Depth-Anything-V2) |

**UniDepthV2 was not run, for two independent reasons**, both recorded rather than
worked around:

1. **Licence.** CC BY-NC 4.0 forbids commercial use. Allure is a commercial
   product, so even an excellent score would not be usable. This is disqualifying
   on its own.
2. **Platform.** The repository requires Linux and compiles custom CUDA ops; this
   host is Windows.

No numbers were invented for it.

## Step 1 — measured on the RTX 3050 6 GB, 704×448, loaded one at a time

| | **MoGe-2 (vitl)** | Depth Anything V2 Small (control) |
|---|--:|--:|
| Load | 11.5 s | 7.18 s |
| Cold inference | 3.66 s | 0.60 s |
| **Warm median** | **0.707 s** | 0.217 s |
| Warm p95 | 0.749 s | 0.238 s |
| **Peak VRAM** | **2636 MiB** | 404 MiB |
| CPU RAM delta | 1.4 GB | ~0 |
| Output resolution | 704×448 | 704×448 |
| Output type | **point map + depth + intrinsics** | point map only |
| **Metric?** | **YES, metres** | no, relative |
| Intrinsics predicted? | **YES** | no — assumed |
| Field of view | **58.67° predicted** | 60° assumed |
| Valid pixel fraction | **1.000** | 0.995 |
| **Determinism** | **max abs diff 0.0** | max abs diff 0.0 |

**MoGe-2 fits comfortably.** 2636 MiB peak on a 6144 MiB card, 0.707 s per image.
For scale, the 7B language model this architecture removes needed 3.47 GB of VRAM
*plus* 2.70 GB of CPU spill.

**Two properties worth noting beyond cost:**

- **It predicts the camera.** 58.67° against the 60° Phase 1 guessed — close, but
  now measured per image instead of assumed for all of them. Intrinsics come back
  normalised (cx = cy = 0.5) and are converted to pixel units inside the adapter,
  because a normalised K that looks like a pixel K is exactly the class of silent
  error Phase 1 was built on.
- **It is bit-deterministic.** Two runs on the same image differ by 0.0. The VLM
  it replaces flipped on 9.4% of cases between identical runs.

### Coordinate convention — measured, not assumed

MoGe returns **OpenCV convention: +X right, +Y down, +Z forward**. Probed on a
real benchmark image before the adapter was written:

```
mean Y, top rows    -0.930     mean Y, bottom rows   +0.826   -> +Y is DOWN
mean X, left cols   -1.612     mean X, right cols    +2.319   -> +X is RIGHT
mean Z              +4.509                                     -> +Z is FORWARD
```

Allure's canonical frame is +Y **up**, −Z forward, so the conversion is a negation
of Y and Z — a 180° rotation about X, which preserves handedness, distances and
angles. It is applied in `_to_canonical` and nowhere else.

## Dependencies added

Required by the experiment, all installed with `--no-deps` so the existing
`torch 2.14.0+cu126` could not be downgraded (verified unchanged before and after):

| Package | Why |
|---|---|
| `moge` 3.0.0 | the model, from `github.com/microsoft/MoGe` |
| `utils3d_moge` 1.7 | MoGe's pinned geometry helper (the PyPI `utils3d` is a different, 3.7 kB package and does **not** work) |
| `opencv-python-headless` | MoGe import dependency |
| `scipy` | MoGe import dependency |

Test baseline re-run after installation: **355 passed, 7 skipped, 30 xfailed** —
unchanged.

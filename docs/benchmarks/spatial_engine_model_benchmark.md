# Spatial engine Phase 0 — model cost on the RTX 3050 6 GB

**Date:** 2026-09-15 · **Raw:** `aether-backend/research/spatial_engine/model_benchmark.json`
**Script:** `research/spatial_engine/model_benchmark.py` · No production code changed.

The architecture research recommended a detector, a segmenter and a metric geometry
model, and could not verify the VRAM or latency of any of them — none of the
repositories publish those figures. This measures the ones that can be measured
without adding a dependency, and records the rest as blocked rather than guessing.

## Host

| | |
|---|---|
| GPU | NVIDIA RTX 3050 6GB Laptop, 6144 MiB |
| torch / transformers | 2.14.0+cu126 / 4.57.6, CUDA available |
| Image | `research/phase1g/scenes/s01_living_room.png` at **704×448** (production resolution) |
| Protocol | one model at a time, unloaded between runs; 5 warm iterations |

## Measured

| Model | Role | Load | Cold | **Warm median** | **Peak VRAM** | CPU RAM | Output |
|---|---|--:|--:|--:|--:|--:|---|
| **Grounding DINO (tiny)** | open-vocab 2D detection | 12.48 s | 3.26 s | **0.905 s** | **2424 MiB** | 0.9 GB | 5 boxes |
| **Depth Anything V2 Small** | relative depth, Apache-2.0 size | 15.51 s | 0.87 s | **0.122 s** | **796 MiB** | 0.3 GB | depth (1, 518, 812) |

Both are practical at 704×448 by a wide margin. Run sequentially their peaks sum to
**3220 MiB**, comfortably inside 6144 MiB — and they are not run concurrently anyway.

**Two details that matter for integration:**

- **Depth Anything resizes internally.** A 704×448 input comes back 518×812. Any
  consumer must interpolate the prediction back onto the image grid before
  indexing it with pixel coordinates. The Phase 1 experiment does this; a naive
  integration would silently mis-register every box.
- **VRAM does not return to zero after unload.** DINO released 1732 of 2424 MiB;
  DAv2 released 680 of 796. The remainder is the process's CUDA context, which
  lives until the process exits. `coexists_with_blender` reads `False` for DINO on
  that basis, but the fair conclusion is narrower: **peak VRAM is what matters for
  scheduling, and perception should run in a process that exits** — which is what
  the existing two-lane job runner already provides.

## Blocked — recorded, not estimated

| Model | Blocker |
|---|---|
| SAM 2 (Hiera-B+) | needs the `sam2` package; not installed. Phase 1 does not need masks and the brief says not to make SAM a prerequisite, so no dependency was added. |
| MobileSAM | needs `mobile_sam`; same reason. |
| **MoGe-2** | needs the `moge` package. **This is the model the architecture wants for metric geometry, and Phase 1 has now shown it is required rather than preferred — see `geometric_wall_contact_report.md`.** |
| **UniDepthV2** | needs `unidepth` with custom CUDA ops. Same status. |

`transformers` already ships Grounding DINO, Depth Anything and SAM support, so those
cost a checkpoint download and **no new Python dependency**. The metric geometry models
do not, and unblocking one of them is the first task of the next phase.

## Conclusion

Six-gigabyte feasibility is **not** the constraint anyone feared. The perception
models are small and fast; a detector and a depth model together cost about 3.2 GB
peak and roughly one second per image, against a 60-second-per-room budget. The
binding constraint measured in Phases 1e–1h was the 7B language model
(3.47 GB VRAM + 2.70 GB CPU spill), and the recommended architecture removes it
from the spatial path entirely.

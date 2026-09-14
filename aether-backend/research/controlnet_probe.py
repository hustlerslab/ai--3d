"""Depth-conditioned generation: does it hold the layout, and what does it cost?

    python research/controlnet_probe.py <depth.png> <out_dir> ["prompt"]

Written up in docs/ADR-004. Reference only: nothing in `app/` imports this, and
nothing in the shipped pipeline uses ControlNet.

Needs `lllyasviel/control_v11f1p_sd15_depth` (1.4 GB, fp16). The installed
diffusers already carries the pipeline classes, so no new library.

Measured on a 6 GB RTX 3050, 704 x 448, 28 steps:

    scale 1.0   751 ms/step   21.0 s   peak 3,539 MB
    scale 0.6   690 ms/step   19.3 s   peak 3,539 MB
    plain SD                  14.7 s             (today's moodboard path)

about +43 % wall clock, comfortably inside the card. Attention slicing works
here, unlike the IP-Adapter path this would replace.

The conclusion is in the ADR and is not about speed: structure transfers,
appearance does not.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import torch
from PIL import Image

DEFAULT_PROMPT = (
    "warm modern living room, striped green and blue sofa, tufted ottoman, wooden "
    "side table, woven rug, oak floor, painted walls, interior photograph, daylight"
)
NEGATIVE = "lowres, blurry, distorted, text, watermark"
STEPS = 28
SEED = 4242
# Both ends of the useful range: 1.0 hugs the geometry, 0.6 lets the model
# furnish more freely. Below about 0.5 the layout stops holding at all.
SCALES = (1.0, 0.6)


def main() -> int:
    if len(sys.argv) < 3:
        print('usage: python research/controlnet_probe.py <depth.png> <out_dir> ["prompt"]')
        return 2
    depth_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    prompt = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PROMPT
    out_dir.mkdir(parents=True, exist_ok=True)

    from diffusers import (ControlNetModel, StableDiffusionControlNetPipeline,
                           UniPCMultistepScheduler)

    control = Image.open(depth_path).convert("RGB")
    print(f"conditioning on {depth_path.name} {control.size}", flush=True)

    t = time.monotonic()
    controlnet = ControlNetModel.from_pretrained(
        "lllyasviel/control_v11f1p_sd15_depth", torch_dtype=torch.float16, variant="fp16")
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5", controlnet=controlnet,
        torch_dtype=torch.float16, safety_checker=None)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe = pipe.to("cuda")
    pipe.enable_attention_slicing()
    pipe.set_progress_bar_config(disable=True)
    print(f"pipeline load: {time.monotonic() - t:.1f}s", flush=True)

    torch.cuda.reset_peak_memory_stats()
    for scale in SCALES:
        t = time.monotonic()
        image = pipe(prompt, image=control, negative_prompt=NEGATIVE,
                     num_inference_steps=STEPS, controlnet_conditioning_scale=scale,
                     generator=torch.Generator("cuda").manual_seed(SEED)).images[0]
        secs = time.monotonic() - t
        dest = out_dir / f"controlnet_scale{scale}.png"
        image.save(dest)
        print(f"  scale {scale}: {secs:5.1f}s  ({secs / STEPS * 1000:.0f} ms/step)  "
              f"peak {torch.cuda.max_memory_allocated() / 2**20:.0f} MB -> {dest.name}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

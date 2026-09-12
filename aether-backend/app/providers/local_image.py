"""Local Stable Diffusion — the moodboard scene without a vendor.

Mirrors the shape of gemini_image.py (generate → GeneratedImage → write) so the
analyze handler can pick either at runtime and the call site does not care.
Swapping the local model means replacing this file.

Why it is built the way it is, on a 6 GB card:

* torch must be the CUDA build. `pip install diffusers` pulls `torch` from
  PyPI, which is CPU-only, and will silently replace a CUDA install — the
  symptom is `torch.__version__` ending in `+cpu` and generation taking
  minutes instead of seconds. `describe()` reports this so it stays visible.
* The pipeline is loaded once and cached. A cold load is tens of seconds; the
  job would otherwise pay that on every project.
* Attention slicing and VAE tiling are on. They trade a little speed for a lot
  of headroom, which is what keeps a 512 px render inside 6 GB alongside
  everything else this machine runs.

It does NOT take the user's reference photos. Plain text-to-image cannot place
a specific sofa in a room; that needs IP-Adapter or ControlNet conditioning,
which is separate work. What it paints is the *style* the reading described,
not the client's own furniture — an honest limitation versus the Gemini path,
which took the photos natively.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aether.providers.local_image")

# Kept small and 512-native: SD 1.5 is ~2.1 GB in fp16, leaving room for the
# text encoder, the VAE and a Blender process that wants the same card.
DEFAULT_MODEL = "runwayml/stable-diffusion-v1-5"

# IP-Adapter is what lets the client's own furniture appear in the render. Plain
# text-to-image cannot do it: SD's text encoder tops out at 77 tokens and has no
# way to be shown a specific sofa. The adapter conditions on the reference image
# directly, alongside the prompt.
IP_ADAPTER_REPO = "h94/IP-Adapter"
IP_ADAPTER_SUBFOLDER = "models"
IP_ADAPTER_WEIGHT = "ip-adapter_sd15.bin"

_pipeline: Any = None
_pipeline_key: tuple[str, str, bool] | None = None
_lock = threading.Lock()


class LocalImageError(RuntimeError):
    """Any non-recoverable local-generation failure."""


class LocalImageUnavailable(LocalImageError):
    """torch/diffusers missing, or no usable device. Distinct so the caller can
    degrade quietly rather than treat it as a bug."""


@dataclass
class GeneratedImage:
    """Same shape gemini_image returns, so callers stay identical."""

    data: bytes
    mime_type: str
    model: str


def describe() -> dict[str, Any]:
    """What is actually installed. Used by health and by the setup check —
    `torch_cuda: false` with a `+cpu` version is the common misinstall."""
    out: dict[str, Any] = {"torch": None, "diffusers": None, "torch_cuda": False, "device": "none"}
    try:
        import torch

        out["torch"] = torch.__version__
        out["torch_cuda"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            out["device"] = torch.cuda.get_device_name(0)
            out["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
        else:
            out["device"] = "cpu"
    except Exception as exc:                       # not installed at all
        out["error"] = f"{type(exc).__name__}: {exc}"
    try:
        import diffusers

        out["diffusers"] = diffusers.__version__
    except Exception:
        pass
    return out


def available() -> bool:
    d = describe()
    return bool(d["torch"] and d["diffusers"])


def _load(model: str, device: str, with_ip_adapter: bool = False) -> Any:
    """Load once, reuse. Guarded so two job threads cannot load twice into a
    card that only has room for one. The adapter is part of the cache key: a
    pipeline loaded without it cannot condition on images."""
    global _pipeline, _pipeline_key
    with _lock:
        if _pipeline is not None and _pipeline_key == (model, device, with_ip_adapter):
            return _pipeline
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as exc:
            raise LocalImageUnavailable(
                "torch/diffusers are not installed; run: pip install "
                "--index-url https://download.pytorch.org/whl/cu126 torch, then "
                "pip install diffusers transformers accelerate safetensors"
            ) from exc

        dtype = torch.float16 if device == "cuda" else torch.float32
        log.info("loading %s onto %s (%s)", model, device, dtype)
        try:
            pipe = StableDiffusionPipeline.from_pretrained(
                model, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False
            )
        except Exception as exc:
            raise LocalImageError(f"could not load {model}: {exc}") from exc

        pipe = pipe.to(device)

        # BEFORE the memory optimisations, not after: loading the adapter swaps
        # the UNet's attention processors, and it cannot swap a sliced processor
        # that attention slicing has already installed — the failure is a bare
        # "SlicedAttnProcessor.__init__() missing 1 required positional argument".
        if with_ip_adapter:
            # ~44 MB adapter plus a ~2.5 GB CLIP image encoder, both cached
            # after the first run. Without this the client's own pieces cannot
            # reach the image at all.
            try:
                pipe.load_ip_adapter(
                    IP_ADAPTER_REPO, subfolder=IP_ADAPTER_SUBFOLDER, weight_name=IP_ADAPTER_WEIGHT
                )
            except Exception as exc:
                raise LocalImageError(
                    f"could not load IP-Adapter ({IP_ADAPTER_REPO}/{IP_ADAPTER_WEIGHT}): {exc}"
                ) from exc

        if device == "cuda":
            # VRAM headroom, which is the whole game on a 6 GB card shared with
            # Blender. These helpers move between diffusers releases (vae tiling
            # left the pipeline for the VAE itself), so probe rather than assume
            # — a missing optimisation costs headroom, not correctness.
            savers = [lambda: pipe.vae.enable_tiling(), lambda: pipe.vae.enable_slicing()]

            # Attention slicing is INCOMPATIBLE with IP-Adapter and the failure
            # is obscure both ways round. It replaces every UNet attention
            # processor: enabled first, loading the adapter dies on
            # "SlicedAttnProcessor.__init__() missing 1 required positional
            # argument"; enabled after, it silently overwrites the adapter's
            # processors and generation dies on "'tuple' object has no
            # attribute 'shape'", because IP-Adapter passes
            # (text_embeds, image_embeds) that a sliced processor cannot read.
            # The VAE savers above touch no attention, so they are always safe.
            if not with_ip_adapter:
                savers.insert(0, lambda: pipe.enable_attention_slicing())

            for enable in savers:
                try:
                    enable()
                except Exception as exc:                     # noqa: BLE001
                    log.debug("VRAM optimisation unavailable in this diffusers build: %s", exc)
        pipe.set_progress_bar_config(disable=True)

        _pipeline, _pipeline_key = pipe, (model, device, with_ip_adapter)
        return pipe


def _open_references(paths: list[Path]) -> list[Any]:
    """Load reference photos for IP-Adapter.

    A single adapter conditions on one embedding, so passing several images
    averages them — with unrelated pieces (four mattresses and a sofa) that
    average is mush. Sending the first is a sharper signal than blending all
    of them, so the caller is expected to have chosen the order.

    Asking for references and getting none is an error, not a fallback. It used
    to drop through to plain text-to-image, which returns a perfectly good
    picture of somebody else's room and reports success — the caller cannot
    tell that apart from a conditioned render, so it has to be raised.
    """
    out: list[Any] = []
    if not paths:
        return out
    try:
        from PIL import Image
    except ImportError as exc:                       # Pillow ships with the app
        raise LocalImageUnavailable("Pillow is not installed") from exc

    failed: list[str] = []
    for p in paths:
        try:
            with Image.open(p) as im:
                out.append(im.convert("RGB").copy())
        except (OSError, ValueError) as exc:
            failed.append(f"{p}: {exc}")
            log.warning("unreadable reference %s: %s", p, exc)
    if not out:
        raise LocalImageError(
            "none of the reference photos could be read, so the render would "
            "silently be unconditioned: " + "; ".join(failed)
        )
    return out


def unload() -> None:
    """Drop the pipeline and free the VRAM — the render lane wants this card."""
    global _pipeline, _pipeline_key
    with _lock:
        if _pipeline is None:
            return
        _pipeline = None
        _pipeline_key = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    negative_prompt: str = "",
    steps: int = 28,
    guidance: float = 7.0,
    width: int = 512,
    height: int = 512,
    seed: Optional[int] = None,
    references: Optional[list[Path]] = None,
    reference_scale: float = 0.6,
) -> GeneratedImage:
    """One image from a prompt, optionally conditioned on reference photos.

    `references` are the client's own pieces. They go through IP-Adapter, which
    is the only way a specific sofa reaches the render — SD's text encoder caps
    at 77 tokens and cannot describe one. `reference_scale` balances the two:
    0 ignores the photos, 1 copies them so hard the prompt stops mattering.
    Around 0.6 keeps the room the prompt asked for while the furniture stays
    recognisably the client's.
    """
    if not prompt.strip():
        raise LocalImageError("generate: prompt is required")
    try:
        import torch
    except ImportError as exc:
        raise LocalImageUnavailable("torch is not installed") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        # Not fatal, but the caller deserves to know before waiting minutes.
        log.warning("no CUDA device: generating on CPU, which is very slow")

    ip_images = _open_references(references or [])
    pipe = _load(model, device, with_ip_adapter=bool(ip_images))
    if ip_images:
        pipe.set_ip_adapter_scale(reference_scale)

    generator = torch.Generator(device=device).manual_seed(seed) if seed is not None else None
    try:
        result = pipe(
            prompt=prompt.strip(),
            negative_prompt=negative_prompt or None,
            num_inference_steps=steps,
            guidance_scale=guidance,
            width=width,
            height=height,
            generator=generator,
            **({"ip_adapter_image": ip_images} if ip_images else {}),
        )
    except Exception as exc:
        if "out of memory" in str(exc).lower():
            raise LocalImageError(
                f"out of VRAM generating {width}x{height}. Free the GPU (Blender or "
                "Ollama may hold it) or lower the resolution."
            ) from exc
        raise LocalImageError(f"generation failed: {exc}") from exc

    import io

    buf = io.BytesIO()
    result.images[0].save(buf, format="PNG")
    return GeneratedImage(data=buf.getvalue(), mime_type="image/png", model=model)


def write(image: GeneratedImage, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image.data)
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise LocalImageError("wrote an empty image")
    return dest

"""Open-vocabulary object detection, for the Phase 0b benchmark only.

One entry point, `detect_objects(image_path, candidate_labels)`, returning plain
dicts. Raw model output never leaves this file: the point of the benchmark is to
compare two systems on equal terms, and that is only possible if both answer in
the same shape.

Grounding DINO takes a prompt, not a fixed class list, so the label set is an
argument rather than a constant baked into the weights. Keep it short - the
model scores every phrase against every region, so a hundred labels buys noise
and latency, not recall.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

# Kept deliberately small (Phase 0b is a measurement, not a taxonomy). These are
# detector PROMPTS in plain English, not vocab semantic_types - the benchmark
# normalises them onto semantic_types with vocab.canonical_type() afterwards,
# the same function the reader's own output goes through.
RESIDENTIAL_LABELS: list[str] = [
    "sofa", "armchair", "chair", "bar stool", "ottoman", "bed", "pillow",
    "coffee table", "side table", "dining table", "desk", "bedside table",
    "cabinet", "wardrobe", "shelf", "television", "tv stand", "lamp",
    "plant", "rug", "curtain", "mirror", "painting", "vase", "towel",
    "kitchen counter", "bathtub", "vanity",
]

COMMERCIAL_LABELS: list[str] = [
    "reception desk", "lounge chair", "dining table", "bar stool", "bar counter",
    "banquette", "pendant light", "luggage rack", "console table", "planter",
]

INDUSTRIAL_LABELS: list[str] = [
    "desk", "office chair", "conference table", "reception desk",
    "storage cabinet", "workstation", "whiteboard", "shelving unit",
]

# Never prompted for and never scored. `scene_reading_prompt()` forbids the
# reader from boxing these - they are rebuilt as geometry - so detecting them
# would hand the detector points the reader is not allowed to compete for.
ARCHITECTURAL_LABELS: list[str] = ["window", "door", "wall", "floor", "ceiling"]

_MODEL_ID = "IDEA-Research/grounding-dino-tiny"
_cache: dict[str, Any] = {}


def available() -> tuple[bool, str]:
    """Can this run at all? Reason when not, never an exception."""
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForZeroShotObjectDetection  # noqa: F401
    except Exception as exc:                                   # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


def describe() -> dict[str, Any]:
    import torch

    d: dict[str, Any] = {"model": _MODEL_ID, "torch": torch.__version__,
                         "cuda": torch.cuda.is_available()}
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        d["gpu"], d["vram_gb"] = p.name, round(p.total_memory / 1024 ** 3, 1)
    return d


def _load(device: str):
    if "model" not in _cache:
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        _cache["processor"] = AutoProcessor.from_pretrained(_MODEL_ID)
        _cache["model"] = AutoModelForZeroShotObjectDetection.from_pretrained(
            _MODEL_ID).to(device).eval()
    return _cache["processor"], _cache["model"]


def unload() -> None:
    """Give the card back. The benchmark runs beside nothing, but the habit is
    the one `local_image.unload()` already established and the next phase needs."""
    import torch

    _cache.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def detect_objects(
    image_path: str | Path,
    candidate_labels: list[str],
    *,
    box_threshold: float = 0.30,
    text_threshold: float = 0.25,
    device: Optional[str] = None,
) -> dict[str, Any]:
    """Detect `candidate_labels` in one image.

    One threshold for the whole benchmark, never tuned per image - a per-image
    threshold measures the person choosing it, not the model.

    Returns
    -------
    {"objects": [{"label", "confidence", "bbox": {"x","y","width","height"}}],
     "elapsed_s", "peak_vram_mb", "device", "image_size"}
    """
    import torch
    from PIL import Image

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    processor, model = _load(device)
    image = Image.open(image_path).convert("RGB")

    # Grounding DINO wants one lowercase phrase per class, full stop separated.
    prompt = ". ".join(label.lower().strip() for label in candidate_labels) + "."

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    results = processor.post_process_grounded_object_detection(
        outputs,
        inputs["input_ids"],
        threshold=box_threshold,
        text_threshold=text_threshold,
        target_sizes=[image.size[::-1]],           # (height, width)
    )[0]
    elapsed = time.perf_counter() - started
    peak_mb = (torch.cuda.max_memory_allocated() / 1024 ** 2) if device == "cuda" else 0.0

    objects = []
    labels = results.get("text_labels", results.get("labels", []))
    for score, label, box in zip(results["scores"], labels, results["boxes"]):
        x0, y0, x1, y1 = (round(float(v)) for v in box.tolist())
        objects.append({
            "label": str(label).strip(),
            "confidence": round(float(score), 4),
            "bbox": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
        })
    objects.sort(key=lambda o: -o["confidence"])
    return {
        "objects": objects,
        "elapsed_s": round(elapsed, 3),
        "peak_vram_mb": round(peak_mb, 1),
        "device": device,
        "image_size": {"width": image.size[0], "height": image.size[1]},
    }

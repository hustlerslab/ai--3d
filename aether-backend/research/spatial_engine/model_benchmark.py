"""Spatial engine Phase 0: what do the candidate models actually cost on this card?

    python -u research/spatial_engine/model_benchmark.py

Research only. Imports production code, writes nothing into it.

The architecture research recommended Grounding DINO, a segmenter and a metric
geometry model, and could not verify the VRAM or latency of any of them - none of
the repositories publish those figures. Six-gigabyte feasibility turns entirely on
numbers nobody has written down, so they get measured here before anything is
designed around them.

MODELS ARE LOADED ONE AT A TIME AND UNLOADED BETWEEN RUNS. That is not tidiness,
it is the deployment constraint: Blender needs this card back, and Phase 1e/1f/1h
measured qwen2.5vl:7b spilling 2.70 GB to CPU because it could not have the card
to itself. Each entry therefore also records how much VRAM came back after
unload, which is the number that decides whether a model can sit in the same
pipeline as a render.

WHAT IS NOT MEASURED, AND WHY. `sam2`, `moge` and `unidepth` are separate pip
packages and none is installed. The engineering principle for this phase is not
to add a dependency the experiment does not require, and Phase 1 requires depth
and boxes only. So those three are recorded as BLOCKED with the exact reason
rather than estimated. `transformers` already ships Grounding DINO, Depth
Anything and SAM support, so those cost a checkpoint download and no new
dependency at all.
"""
from __future__ import annotations

import ctypes
import gc
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

OUT_JSON = HERE / "model_benchmark.json"

#: A real benchmark image at the resolution production actually uses.
IMAGE = ROOT / "research" / "phase1g" / "scenes" / "s01_living_room.png"
WIDTH, HEIGHT = 704, 448
WARM_ITERS = 5

#: Models that need a pip package we have not installed. Recorded, never guessed.
BLOCKED = [
    {"name": "SAM 2 (Hiera-B+)", "role": "instance + architecture masks",
     "blocker": "requires the `sam2` package (github.com/facebookresearch/sam2); "
                "not installed. Phase 1 does not need masks - the brief says not to "
                "make SAM2 a prerequisite unless boxes prove insufficient - so no "
                "dependency was added."},
    {"name": "MobileSAM", "role": "lightweight masks",
     "blocker": "requires the `mobile_sam` package; not installed, same reason."},
    {"name": "MoGe-2", "role": "metric point map",
     "blocker": "requires the `moge` package (github.com/microsoft/MoGe); not "
                "installed. This is the model the architecture wants for metric "
                "geometry and it SHOULD be measured before Phase 2 - flagged."},
    {"name": "UniDepthV2", "role": "metric depth + camera",
     "blocker": "requires the `unidepth` package with custom CUDA ops; not "
                "installed. Same status as MoGe-2."},
]


def gpu_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        name, total, used = [p.strip() for p in out.stdout.strip().split(",")]
        return {"name": name, "vram_total_mib": int(total), "vram_used_mib": int(used)}
    except Exception as exc:                                       # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def vram_used_mib() -> int:
    return gpu_info().get("vram_used_mib", -1)


def system_ram() -> dict:
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        stat = MS()
        stat.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return {"total_gb": round(stat.ullTotalPhys / 1e9, 1),
                "available_gb": round(stat.ullAvailPhys / 1e9, 1),
                "load_pct": stat.dwMemoryLoad}
    except Exception:                                              # noqa: BLE001
        return {}


def _release(*objects) -> None:
    """Drop the model and give the card back. Measured, not assumed."""
    import torch

    for obj in objects:
        del obj
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    gc.collect()


def measure(name: str, role: str, build, infer, repo: str) -> dict:
    """Load one model, time it cold and warm, record peak VRAM, then unload."""
    import torch
    from PIL import Image

    row = {"name": name, "role": role, "repo": repo, "status": "ok",
           "resolution": f"{WIDTH}x{HEIGHT}"}
    ram_before = system_ram().get("available_gb")
    vram_before = vram_used_mib()

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        model, extra = build()
    except Exception as exc:                                       # noqa: BLE001
        row.update(status="FAILED", blocker=f"{type(exc).__name__}: {exc}"[:300])
        return row
    row["load_s"] = round(time.perf_counter() - started, 2)

    image = Image.open(IMAGE).convert("RGB").resize((WIDTH, HEIGHT))

    started = time.perf_counter()
    try:
        out = infer(model, extra, image)
    except Exception as exc:                                       # noqa: BLE001
        row.update(status="FAILED", blocker=f"inference: {type(exc).__name__}: {exc}"[:300])
        _release(model, extra)
        return row
    row["cold_inference_s"] = round(time.perf_counter() - started, 2)
    row["output"] = str(out)[:120]

    timings = []
    for _ in range(WARM_ITERS):
        started = time.perf_counter()
        infer(model, extra, image)
        timings.append(time.perf_counter() - started)
    row["warm_median_s"] = round(statistics.median(timings), 3)
    row["warm_worst_s"] = round(max(timings), 3)

    row["peak_vram_torch_mib"] = round(torch.cuda.max_memory_allocated() / 1024**2)
    row["peak_vram_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 1024**2)
    row["vram_used_while_loaded_mib"] = vram_used_mib()
    ram_during = system_ram().get("available_gb")
    row["cpu_ram_delta_gb"] = (round(ram_before - ram_during, 2)
                               if ram_before and ram_during else None)

    _release(model, extra)
    time.sleep(2.0)
    row["vram_after_unload_mib"] = vram_used_mib()
    row["vram_released_mib"] = row["vram_used_while_loaded_mib"] - row["vram_after_unload_mib"]
    # The deployment question: does the card come back for Blender?
    row["coexists_with_blender"] = bool(row["vram_after_unload_mib"] <= vram_before + 200)
    row["practical_at_704x448"] = bool(row.get("warm_median_s", 99) < 5.0)
    return row


# ── the models transformers already supports ────────────────────────────

def build_grounding_dino():
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    repo = "IDEA-Research/grounding-dino-tiny"
    processor = AutoProcessor.from_pretrained(repo)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(repo).to("cuda").eval()
    return model, processor


def infer_grounding_dino(model, processor, image):
    import torch

    prompt = "a sofa. a chair. a table. a cabinet. a lamp. a rug."
    inputs = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        outputs = model(**inputs)
    results = processor.post_process_grounded_object_detection(
        outputs, inputs.input_ids, threshold=0.3, text_threshold=0.3,
        target_sizes=[(image.height, image.width)])
    return f"{len(results[0]['boxes'])} boxes"


def build_depth_anything_v2_small():
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    # Small is the ONLY Apache-2.0 size. Base/Large/Giant are CC-BY-NC-4.0 and
    # cannot ship in a commercial product - verified in the architecture research.
    repo = "depth-anything/Depth-Anything-V2-Small-hf"
    processor = AutoImageProcessor.from_pretrained(repo)
    model = AutoModelForDepthEstimation.from_pretrained(repo).to("cuda").eval()
    return model, processor


def infer_depth_anything(model, processor, image):
    import torch

    inputs = processor(images=image, return_tensors="pt").to("cuda")
    with torch.no_grad():
        outputs = model(**inputs)
    return f"depth {tuple(outputs.predicted_depth.shape)}"


def main() -> int:
    import torch
    import transformers

    if not IMAGE.is_file():
        print(f"benchmark image missing: {IMAGE}")
        return 1

    host = {"gpu": gpu_info(), "ram": system_ram(),
            "torch": torch.__version__, "transformers": transformers.__version__,
            "cuda": torch.cuda.is_available(),
            "image": str(IMAGE.relative_to(ROOT)).replace("\\", "/"),
            "resolution": f"{WIDTH}x{HEIGHT}", "warm_iters": WARM_ITERS}
    print(f"host: {host['gpu']}  torch {host['torch']}  "
          f"transformers {host['transformers']}")
    print(f"image: {host['image']} at {WIDTH}x{HEIGHT}\n", flush=True)

    candidates = [
        ("Grounding DINO (tiny)", "open-vocab 2D detection",
         build_grounding_dino, infer_grounding_dino,
         "IDEA-Research/grounding-dino-tiny"),
        ("Depth Anything V2 Small", "relative depth (Apache-2.0 size)",
         build_depth_anything_v2_small, infer_depth_anything,
         "depth-anything/Depth-Anything-V2-Small-hf"),
    ]

    rows = []
    for name, role, build, infer, repo in candidates:
        print(f"-- {name} ...", flush=True)
        row = measure(name, role, build, infer, repo)
        rows.append(row)
        if row["status"] == "ok":
            print(f"   load {row['load_s']}s  cold {row['cold_inference_s']}s  "
                  f"warm {row['warm_median_s']}s  peak VRAM "
                  f"{row['peak_vram_reserved_mib']} MiB  released "
                  f"{row['vram_released_mib']} MiB  -> {row['output']}", flush=True)
        else:
            print(f"   {row['status']}: {row.get('blocker')}", flush=True)

    for entry in BLOCKED:
        rows.append({**entry, "status": "BLOCKED"})
        print(f"-- {entry['name']}: BLOCKED - {entry['blocker'][:90]}...", flush=True)

    report = {"_about": "Spatial engine Phase 0. Models measured one at a time and "
                        "unloaded between runs, because Blender needs the card back. "
                        "BLOCKED entries are recorded, never estimated.",
              "host": host, "models": rows}
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    ok = [r for r in rows if r["status"] == "ok"]
    for r in ok:
        print(f"  {r['name']:26} warm {r['warm_median_s']:>6}s  peak "
              f"{r['peak_vram_reserved_mib']:>5} MiB  coexists={r['coexists_with_blender']}")
    total = sum(r["peak_vram_reserved_mib"] for r in ok)
    print(f"\n  measured: {len(ok)}   blocked: {len(rows) - len(ok)}")
    print(f"  sum of peaks if run SEQUENTIALLY (not concurrently): {total} MiB")
    print(f"\n  wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

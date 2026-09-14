"""BOUNDED Stage 3 test: image-to-3D on exactly the elements a human approved.

Deliberately small. The selection is not made here - it comes from
`approved_for_generation`, so the gate is what decides, and anything nobody
ticked stays out even if this script is run again.
"""
import asyncio, json, sys, time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.intelligence.schema import SceneReading
from app.intelligence.scene_reading import approved_for_generation
from app.providers import meshy

ROOT = Path("data/projects/proj_553cb09794")
OUT = ROOT / "planning/stage3_meshes"
HARD_CAP = 5          # this test, and no more, whatever the file says


async def main() -> int:
    s = get_settings()
    reading = SceneReading.model_validate(json.loads((ROOT/"planning/scene_reading.json").read_text(encoding="utf-8")))
    ready, held = approved_for_generation(reading)
    print(f"gate: {len(ready)} approved, {len(held)} held back")
    if not ready:
        print("nothing approved; nothing to do"); return 0
    if len(ready) > HARD_CAP:
        print(f"REFUSING: {len(ready)} approved exceeds this test's cap of {HARD_CAP}")
        return 1
    for e in ready:
        print(f"   {e.name:34} native {e.crop_px[0]}x{e.crop_px[1]}  check={e.check}")

    headers = {"Authorization": f"Bearer {s.meshy_api_key.get_secret_value()}"}
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    async with httpx.AsyncClient(base_url=s.meshy_base_url, headers=headers, timeout=120) as c:
        before = (await c.get("/openapi/v1/balance")).json().get("balance")
        print(f"\ncredit balance before: {before}\n")

        # Submit all, then wait: the queue runs them in parallel, and serial
        # submit-and-wait was what made the earlier estimate 70 minutes.
        tasks = []
        for e in ready:
            crop = ROOT / e.crop_ref
            tid = await meshy.submit_image_to_3d(c, crop, target_polycount=s.meshy_target_polycount)
            tasks.append((e, tid))
            print(f"  queued {e.name[:30]:32} task {tid}", flush=True)

        t0 = time.monotonic()
        for e, tid in tasks:
            try:
                model = await meshy.wait_for(c, tid, timeout_seconds=900, poll_seconds=10,
                                             endpoint=meshy.IMAGE_TO_3D)
                dest = OUT / f"{e.element_id}.glb"
                await meshy.download_glb(c, model.glb_url, dest)
                mb = dest.stat().st_size / 2**20
                results.append((e, model, dest))
                print(f"  OK  {e.name[:30]:32} {model.credits:3} credits  {mb:5.1f} MB", flush=True)
            except Exception as exc:
                results.append((e, None, None))
                print(f"  FAIL {e.name[:30]:32} {exc}", flush=True)

        after = (await c.get("/openapi/v1/balance")).json().get("balance")

    print(f"\nwall clock: {time.monotonic()-t0:.0f}s")
    print(f"credits: {before} -> {after}  (spent {before - after})")
    (OUT/"_index.json").write_text(json.dumps(
        [{"element_id": e.element_id, "name": e.name, "room_id": e.room_id,
          "crop_ref": e.crop_ref, "crop_px": list(e.crop_px), "check": e.check,
          "glb": str(d.relative_to(ROOT)) if d else None,
          "credits": m.credits if m else 0} for e, m, d in results], indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

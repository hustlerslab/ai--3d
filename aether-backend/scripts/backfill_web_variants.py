"""Build the viewer copy for models ingested before the variant existed."""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.assets import web_variant
from app.assets.registry import get_registry
from app.core.config import get_settings

reg, settings = get_registry(), get_settings()
done = skipped = failed = 0
d_before = d_after = v_before = v_after = 0
t0 = time.monotonic()
for rec in reg.list():
    if not rec.files.normalized or rec.status == "failed":
        continue
    src = settings.data_dir / rec.files.normalized
    if not src.is_file():
        continue
    if rec.files.web and (settings.data_dir / rec.files.web).is_file():
        skipped += 1
        continue
    dest = reg.web_path(rec.asset_id)
    try:
        st = web_variant.build(src, dest)
    except Exception as exc:                              # noqa: BLE001
        print(f"  FAILED {rec.asset_id}: {exc}"); failed += 1; continue
    if st["images_resized"]:
        rec.files.web = str(dest.relative_to(settings.data_dir)).replace("\\", "/")
        reg.upsert(rec)
        done += 1
        d_before += st["source_bytes"]; d_after += st["dest_bytes"]
        v_before += st["vram_before"]; v_after += st["vram_after"]
    else:
        dest.unlink(missing_ok=True); skipped += 1

print(f"\n{done} built, {skipped} needed none, {failed} failed  ({time.monotonic()-t0:.1f}s)")
if done:
    print(f"  disk  {d_before/2**20:8,.1f} MB -> {d_after/2**20:8,.1f} MB")
    print(f"  VRAM  {v_before/2**20:8,.0f} MB -> {v_after/2**20:8,.0f} MB")

"""Stage 2 validation: read the five approved renders, instrumented."""
import json, os, time
from pathlib import Path
os.environ.setdefault("AETHER_DATA_DIR", "./data")
from app.intelligence import get_provider
from app.intelligence.scene_reading import coerce_room_reading, write_element_crops
from app.intelligence.schema import DesignAnalysis, SceneReading, StyleSpec
from app.projects import get_project_store
from app.projects.layout import project_dir

pid = "proj_553cb09794"
root = project_dir(pid)
analysis = DesignAnalysis.model_validate(json.load(open(root/"analysis/design_analysis.json", encoding="utf-8")))
style = StyleSpec.model_validate(json.load(open(root/"analysis/style_spec.json", encoding="utf-8")))
board = json.load(open(root/"analysis/moodboard_spec.json", encoding="utf-8"))
vertical = get_project_store().get(pid).vertical
provider = get_provider()
print("provider:", provider.label, "| capability:", hasattr(provider, "read_scene_elements"), flush=True)

images = {}
for s in board["room_scenes"]:
    if s["url"]:
        images[s["room_id"]] = root / s["url"].split(f"{pid}/", 1)[-1]

raw_dump, elements, surfaces, warnings = {}, [], [], []
t0 = time.monotonic()
for room in analysis.rooms:
    img = images.get(room.room_id)
    if img is None:
        continue
    t = time.monotonic()
    raw = provider.read_scene_elements(img, room, style, vertical) or {}
    secs = time.monotonic() - t
    raw_dump[room.room_id] = raw
    els, surf = coerce_room_reading(raw, room, vertical, warnings)
    elements.extend(els)
    if surf: surfaces.append(surf)
    print(f"  {room.room_id:16} {secs:5.1f}s  raw={len(raw.get('elements') or [])}  kept={len(els)}", flush=True)
total = time.monotonic() - t0

reading = SceneReading(elements=elements, surfaces=surfaces, provider=provider.label, warnings=warnings)
reading.warnings += write_element_crops(reading, images, root, force=True)

from app.intelligence.scene_reading import check_element_crops
room_types = {r.room_id: r.type for r in analysis.rooms}
t = time.monotonic()
tally = check_element_crops(reading, room_types, vertical, root, provider)
print(f"\ncheck pass: {time.monotonic()-t:.1f}s  {tally}", flush=True)
for e in reading.elements:
    if e.check != "ok":
        print(f"   {e.check:10} {e.room_id[:12]:13} {e.name[:26]:28} {e.check_note[:60]}", flush=True)
(root/"planning").mkdir(parents=True, exist_ok=True)
(root/"planning/scene_reading.json").write_text(reading.model_dump_json(indent=2), encoding="utf-8")
(root/"planning/_raw_reading.json").write_text(json.dumps(raw_dump, indent=2), encoding="utf-8")
print(f"\nTOTAL {total:.1f}s for {len(images)} rooms; {len(reading.elements)} elements, "
      f"{sum(1 for e in reading.elements if e.crop_ref)} crops, {len(reading.surfaces)} surface sets", flush=True)

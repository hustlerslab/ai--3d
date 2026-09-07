"""Source the curated CC0 library from Poly Haven and ingest it.

    python scripts/source_cc0.py --dry-run          # list every file + size, download nothing
    python scripts/source_cc0.py --run              # download + ingest everything
    python scripts/source_cc0.py --run --only models
    python scripts/source_cc0.py --run --only materials
    python scripts/source_cc0.py --run --ids sofa_02,herringbone_parquet

Run from aether-backend/ with the venv python. Downloads are resumable —
files already present at the right size are skipped, so re-running after a
partial failure only fetches what is missing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.assets import pipeline as asset_pipeline  # noqa: E402
from app.assets.registry import get_registry  # noqa: E402
from app.assets.schema import AssetSource, IngestMeta  # noqa: E402
from app.materials import pipeline as material_pipeline  # noqa: E402
from app.materials.registry import get_material_registry  # noqa: E402
from app.providers import polyhaven  # noqa: E402

FURNITURE = json.loads((ROOT / "sourcing" / "cc0_furniture.json").read_text("utf-8"))
MATERIALS = json.loads((ROOT / "sourcing" / "cc0_materials.json").read_text("utf-8"))


def _source(source_id: str) -> AssetSource:
    return AssetSource(
        provider="polyhaven",
        source_id=source_id,
        url=polyhaven.page_url(source_id),
        license=polyhaven.LICENSE,
        license_url=polyhaven.LICENSE_URL,
        creator="Poly Haven contributors",
        thumbnail_url=polyhaven.thumbnail_url(source_id),
    )


def _fmt(n: int) -> str:
    return f"{n / 1e6:6.1f} MB"


async def plan(only: str, ids: set[str] | None):
    """Resolve every remote file (metadata only, no downloads)."""
    async with polyhaven.make_client() as client:
        models = []
        materials = []
        if only in ("all", "models"):
            for item in FURNITURE["items"]:
                if ids and item["source_id"] not in ids:
                    continue
                res = item.get("resolution", FURNITURE.get("default_resolution", "1k"))
                try:
                    files = await polyhaven.model_files(client, item["source_id"], res)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {item['source_id']}: {exc}")
                    continue
                models.append((item, res, files))
        if only in ("all", "materials"):
            for item in MATERIALS["items"]:
                if ids and item["source_id"] not in ids:
                    continue
                res = item.get("resolution", "1k")
                try:
                    files = await polyhaven.texture_files(client, item["source_id"], res)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {item['source_id']}: {exc}")
                    continue
                materials.append((item, res, files))
    return models, materials


def report(models, materials) -> int:
    total = 0
    print("\nMODELS (Poly Haven, CC0 1.0)")
    for item, res, files in models:
        size = sum(f.size for f in files)
        total += size
        print(f"  {item['source_id']:<32} {res:>3}  {_fmt(size)}  -> {item['asset_id']} ({item['semantic_type']})")
    print("\nMATERIALS (Poly Haven, CC0 1.0)")
    for item, res, files in materials:
        size = sum(f.size for f in files.values())
        total += size
        print(f"  {item['source_id']:<32} {res:>3}  {_fmt(size)}  -> {item['material_id']} [{', '.join(files.keys())}]")
    print(f"\nTOTAL {len(models)} models + {len(materials)} texture sets = {_fmt(total)}")
    return total


async def run(models, materials) -> None:
    registry = get_registry()
    mat_registry = get_material_registry()
    async with polyhaven.make_client() as client:
        for item, res, files in models:
            dest = registry.source_dir(item["asset_id"])
            print(f"DL {item['source_id']} ({res}) …", end=" ", flush=True)
            written = await polyhaven.download(client, files, dest)
            gltf_path = next(p for p in written if p.suffix == ".gltf")
            meta = IngestMeta(
                asset_id=item["asset_id"],
                name=item["name"],
                semantic_type=item["semantic_type"],
                expected_dimensions=tuple(item["expected_dimensions"]) if item.get("expected_dimensions") else None,
                yaw_offset=item.get("yaw_offset", 0.0),
                mount=item.get("mount", "floor"),
                style_tags=item.get("style_tags", []),
                material_tags=item.get("material_tags", []),
                room_types=item.get("room_types", []),
                price_inr=item.get("price_inr", 0),
                color=item.get("color", "#8a7862"),
                source=_source(item["source_id"]),
            )
            record = asset_pipeline.ingest_file(gltf_path, meta)
            dims = "x".join(f"{d:.2f}" for d in record.dimensions)
            flag = "OK " if record.valid else "FAILED"
            warns = [v.code for v in record.validation if v.severity != "info"]
            print(f"{flag} {dims} m, {record.polycount:,} tris{(' ' + str(warns)) if warns else ''}")

        for item, res, files in materials:
            dest = mat_registry.material_dir(item["material_id"])
            print(f"DL {item['source_id']} ({res}) …", end=" ", flush=True)
            written = await polyhaven.download(client, list(files.values()), dest)
            local = dict(zip(files.keys(), written))
            material_pipeline.attach_maps(
                item["material_id"],
                local,
                _source(item["source_id"]),
                tile_size_m=item.get("tile_size_m"),
                name=item.get("name"),
                category=item.get("category"),
                base_color=item.get("base_color"),
                roughness=item.get("roughness"),
                style_tags=item.get("style_tags"),
                applies_to=item.get("applies_to"),
            )
            print(f"OK [{', '.join(local.keys())}]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="list files and sizes only")
    mode.add_argument("--run", action="store_true", help="download and ingest")
    parser.add_argument("--only", choices=["all", "models", "materials"], default="all")
    parser.add_argument("--ids", default="", help="comma-separated source ids to restrict to")
    args = parser.parse_args()

    ids = {s.strip() for s in args.ids.split(",") if s.strip()} or None
    models, materials = asyncio.run(plan(args.only, ids))
    report(models, materials)
    if args.run:
        asyncio.run(run(models, materials))
        print("\nDone. Restart the backend (or it picks the registry up on next request).")


if __name__ == "__main__":
    main()

"""Poly Haven adapter — CC0 models and PBR texture sets.

Poly Haven publishes everything under CC0 1.0 (public domain), which is
exactly the provenance-clean starting library the plan calls for (§16).
This adapter only *lists* and *downloads*; ingestion is the shared
pipeline. Nothing here is Poly Haven-specific beyond URL shapes.

API shape (verified):
  GET /assets?t=models        → {id: {name, categories, tags, ...}}
  GET /files/{id}             → models: {"gltf": {"1k": {"gltf": {url,size,
                                  "include": {"path": {url,size}}}}}}
                                 textures: {"Diffuse": {"2k": {"jpg": {url,size}}}}
  thumbnail: https://cdn.polyhaven.com/asset_img/thumbs/{id}.png?width=256
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

API = "https://api.polyhaven.com"
LICENSE = "CC0-1.0"
LICENSE_URL = "https://polyhaven.com/license"
TEXTURE_MAPS = {"Diffuse": "color", "nor_gl": "normal", "Rough": "roughness", "AO": "ao"}


@dataclass
class RemoteFile:
    url: str
    relative_path: str
    size: int


def thumbnail_url(asset_id: str) -> str:
    return f"https://cdn.polyhaven.com/asset_img/thumbs/{asset_id}.png?width=256"


def page_url(asset_id: str) -> str:
    return f"https://polyhaven.com/a/{asset_id}"


async def asset_info(client: httpx.AsyncClient, asset_id: str) -> dict:
    r = await client.get(f"{API}/info/{asset_id}")
    r.raise_for_status()
    return r.json()


async def model_files(client: httpx.AsyncClient, asset_id: str, resolution: str = "1k") -> list[RemoteFile]:
    r = await client.get(f"{API}/files/{asset_id}")
    r.raise_for_status()
    data = r.json()
    gltf = data.get("gltf", {})
    if resolution not in gltf:
        available = sorted(gltf.keys())
        if not available:
            raise ValueError(f"{asset_id}: no glTF distribution")
        resolution = available[0] if resolution not in available else resolution
    entry = gltf[resolution]["gltf"]
    files = [RemoteFile(entry["url"], f"{asset_id}_{resolution}.gltf", entry.get("size", 0))]
    for rel, item in entry.get("include", {}).items():
        files.append(RemoteFile(item["url"], rel, item.get("size", 0)))
    return files


async def texture_files(client: httpx.AsyncClient, asset_id: str, resolution: str = "1k") -> dict[str, RemoteFile]:
    r = await client.get(f"{API}/files/{asset_id}")
    r.raise_for_status()
    data = r.json()
    out: dict[str, RemoteFile] = {}
    for ph_key, our_key in TEXTURE_MAPS.items():
        entry = data.get(ph_key, {}).get(resolution, {}).get("jpg")
        if entry:
            out[our_key] = RemoteFile(entry["url"], f"{our_key}.jpg", entry.get("size", 0))
    return out


async def download(client: httpx.AsyncClient, files: list[RemoteFile], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for f in files:
        target = dest / f.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and f.size and target.stat().st_size == f.size:
            written.append(target)
            continue
        async with client.stream("GET", f.url) as resp:
            resp.raise_for_status()
            with target.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
        written.append(target)
    return written


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=True, headers={"User-Agent": "aether-asset-pipeline/0.1"})

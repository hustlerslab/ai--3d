"""Asset registry — JSON-backed until the PostgreSQL phase.

Files live under <data_dir>/assets/{source,normalized}; the registry is
<data_dir>/assets/registry.json. Same persistence model as scenes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.config import get_settings
from .schema import AssetRecord


class AssetRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "source").mkdir(exist_ok=True)
        (self.root / "normalized").mkdir(exist_ok=True)
        self.path = self.root / "registry.json"
        self._records: dict[str, AssetRecord] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text("utf-8"))
            self._records = {k: AssetRecord.model_validate(v) for k, v in data.items()}

    def _save(self) -> None:
        payload = {k: v.model_dump() for k, v in self._records.items()}
        self.path.write_text(json.dumps(payload, indent=2), "utf-8")

    def list(self) -> list[AssetRecord]:
        return list(self._records.values())

    def get(self, asset_id: str) -> Optional[AssetRecord]:
        return self._records.get(asset_id)

    def upsert(self, record: AssetRecord) -> AssetRecord:
        self._records[record.asset_id] = record
        self._save()
        return record

    def delete(self, asset_id: str) -> bool:
        if asset_id in self._records:
            del self._records[asset_id]
            self._save()
            return True
        return False

    def source_dir(self, asset_id: str) -> Path:
        path = self.root / "source" / asset_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def normalized_path(self, asset_id: str) -> Path:
        return self.root / "normalized" / f"{asset_id}.glb"

    def web_path(self, asset_id: str) -> Path:
        """The viewer's copy: same geometry, textures sized to a GPU budget.

        Beside the full-size model rather than replacing it. Blender renders
        once and wants every pixel; the browser holds fifteen of these at a
        time and cannot afford them.
        """
        return self.root / "web" / f"{asset_id}.glb"


_registry: Optional[AssetRegistry] = None


def get_registry() -> AssetRegistry:
    global _registry
    if _registry is None:
        _registry = AssetRegistry(get_settings().data_dir / "assets")
    return _registry

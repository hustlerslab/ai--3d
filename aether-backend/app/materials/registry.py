"""Material registry — JSON-backed, files under <data_dir>/materials/{id}/."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.config import get_settings
from .schema import MaterialRecord
from .seed import BUILTIN_MATERIALS


class MaterialRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"
        self._records: dict[str, MaterialRecord] = {m.material_id: m for m in BUILTIN_MATERIALS}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text("utf-8"))
            for k, v in data.items():
                self._records[k] = MaterialRecord.model_validate(v)

    def _save(self) -> None:
        builtin = {m.material_id for m in BUILTIN_MATERIALS}
        payload = {
            k: v.model_dump()
            for k, v in self._records.items()
            if k not in builtin or v.has_maps  # persist built-ins only once they gain maps
        }
        self.path.write_text(json.dumps(payload, indent=2), "utf-8")

    def list(self) -> list[MaterialRecord]:
        return list(self._records.values())

    def get(self, material_id: str) -> Optional[MaterialRecord]:
        return self._records.get(material_id)

    def upsert(self, record: MaterialRecord) -> MaterialRecord:
        self._records[record.material_id] = record
        self._save()
        return record

    def material_dir(self, material_id: str) -> Path:
        path = self.root / material_id
        path.mkdir(parents=True, exist_ok=True)
        return path


_registry: Optional[MaterialRegistry] = None


def get_material_registry() -> MaterialRegistry:
    global _registry
    if _registry is None:
        _registry = MaterialRegistry(get_settings().data_dir / "materials")
    return _registry

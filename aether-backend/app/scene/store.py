"""Scene persistence — JSON files with full version history.

Layout under AETHER_DATA_DIR:
  projects.json                      all projects
  scenes/{scene_id}.json             {"cursor": N, "history": [snapshot, ...]}

Every commit appends a snapshot and moves the cursor; undo/redo move the
cursor without discarding history (a new commit truncates the redo tail).
The scene survives server restart — PostgreSQL can replace this layer later
without touching callers.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..core.config import get_settings
from .schema import Project, Scene

MAX_HISTORY = 200


class SceneNotFound(Exception):
    pass


class VersionConflict(Exception):
    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"base_version {expected} != current version {actual}")


class SceneStore:
    def __init__(self, data_dir: Optional[Path] = None):
        self._dir = data_dir or get_settings().data_dir
        self._scenes_dir = self._dir / "scenes"
        self._scenes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ── Projects ───────────────────────────────────────────────
    @property
    def _projects_path(self) -> Path:
        return self._dir / "projects.json"

    def list_projects(self) -> list[Project]:
        with self._lock:
            if not self._projects_path.exists():
                return []
            raw = json.loads(self._projects_path.read_text(encoding="utf-8"))
            return [Project.model_validate(p) for p in raw]

    def save_projects(self, projects: list[Project]) -> None:
        with self._lock:
            self._projects_path.write_text(
                json.dumps([p.model_dump() for p in projects], indent=2),
                encoding="utf-8",
            )

    def get_project(self, project_id: str) -> Optional[Project]:
        return next(
            (p for p in self.list_projects() if p.project_id == project_id), None
        )

    def add_project(self, project: Project) -> Project:
        with self._lock:
            projects = self.list_projects()
            projects.append(project)
            self.save_projects(projects)
            return project

    def attach_scene(self, project_id: str, scene_id: str) -> None:
        with self._lock:
            projects = self.list_projects()
            for p in projects:
                if p.project_id == project_id and scene_id not in p.scene_ids:
                    p.scene_ids.append(scene_id)
            self.save_projects(projects)

    # ── Scenes ─────────────────────────────────────────────────
    def _scene_path(self, scene_id: str) -> Path:
        safe = "".join(c for c in scene_id if c.isalnum() or c in "_-")
        return self._scenes_dir / f"{safe}.json"

    def _load_record(self, scene_id: str) -> dict:
        path = self._scene_path(scene_id)
        if not path.exists():
            raise SceneNotFound(scene_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_record(self, scene_id: str, record: dict) -> None:
        self._scene_path(scene_id).write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )

    def list_scene_ids(self) -> list[str]:
        return sorted(p.stem for p in self._scenes_dir.glob("*.json"))

    def exists(self, scene_id: str) -> bool:
        return self._scene_path(scene_id).exists()

    def create(self, scene: Scene) -> Scene:
        with self._lock:
            scene.version = 0
            scene.metadata["created_at"] = _now()
            record = {"cursor": 0, "history": [scene.model_dump(mode="json")]}
            self._save_record(scene.scene_id, record)
            return scene

    def load(self, scene_id: str) -> Scene:
        with self._lock:
            record = self._load_record(scene_id)
            snapshot = record["history"][record["cursor"]]
            return Scene.model_validate(snapshot)

    def commit(self, scene: Scene, base_version: int) -> Scene:
        """Append a new snapshot. `base_version` must match the current
        version at the cursor (optimistic locking)."""
        with self._lock:
            record = self._load_record(scene.scene_id)
            current = Scene.model_validate(record["history"][record["cursor"]])
            if current.version != base_version:
                raise VersionConflict(base_version, current.version)
            scene.version = current.version + 1
            scene.metadata["updated_at"] = _now()
            history = record["history"][: record["cursor"] + 1]
            history.append(scene.model_dump(mode="json"))
            if len(history) > MAX_HISTORY:
                history = history[-MAX_HISTORY:]
            self._save_record(
                scene.scene_id, {"cursor": len(history) - 1, "history": history}
            )
            return scene

    def undo(self, scene_id: str) -> Scene:
        with self._lock:
            record = self._load_record(scene_id)
            if record["cursor"] == 0:
                return Scene.model_validate(record["history"][0])
            record["cursor"] -= 1
            self._save_record(scene_id, record)
            return Scene.model_validate(record["history"][record["cursor"]])

    def redo(self, scene_id: str) -> Scene:
        with self._lock:
            record = self._load_record(scene_id)
            if record["cursor"] >= len(record["history"]) - 1:
                return Scene.model_validate(record["history"][record["cursor"]])
            record["cursor"] += 1
            self._save_record(scene_id, record)
            return Scene.model_validate(record["history"][record["cursor"]])

    def history_info(self, scene_id: str) -> dict:
        with self._lock:
            record = self._load_record(scene_id)
            return {
                "cursor": record["cursor"],
                "length": len(record["history"]),
                "can_undo": record["cursor"] > 0,
                "can_redo": record["cursor"] < len(record["history"]) - 1,
            }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_store: Optional[SceneStore] = None


def get_store() -> SceneStore:
    global _store
    if _store is None:
        _store = SceneStore()
    return _store

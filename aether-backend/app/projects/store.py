"""SQLite-backed project and input store."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..db import Database, get_db
from .layout import ensure_layout
from .schema import InputKind, InputRecord, ProjectRecord, ProjectStage, RoomHint


class ProjectNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_project(row) -> ProjectRecord:
    return ProjectRecord(
        project_id=row["project_id"],
        name=row["name"],
        description=row["description"],
        stage=ProjectStage(row["stage"]),
        scene_ids=json.loads(row["scene_ids"]),
        room_hints=[RoomHint.model_validate(h) for h in json.loads(row["room_hints"])],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_input(row) -> InputRecord:
    return InputRecord(
        input_id=row["input_id"],
        project_id=row["project_id"],
        kind=InputKind(row["kind"]),
        filename=row["filename"],
        path=row["path"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        meta=json.loads(row["meta"]),
        created_at=row["created_at"],
    )


class ProjectStore:
    def __init__(self, db: Optional[Database] = None):
        self._db = db or get_db()

    # ── projects ─────────────────────────────────────────────────
    def create(
        self,
        name: str,
        description: str = "",
        room_hints: Optional[list[RoomHint]] = None,
        project_id: Optional[str] = None,
        scene_ids: Optional[list[str]] = None,
        created_at: Optional[str] = None,
    ) -> ProjectRecord:
        now = _now()
        project = ProjectRecord(
            name=name,
            description=description,
            room_hints=room_hints or [],
            scene_ids=scene_ids or [],
            created_at=created_at or now,
            updated_at=now,
            **({"project_id": project_id} if project_id else {}),
        )
        self._db.execute(
            """INSERT INTO projects(project_id, name, description, stage, scene_ids,
                                    room_hints, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                project.project_id,
                project.name,
                project.description,
                project.stage.value,
                json.dumps(project.scene_ids),
                json.dumps([h.model_dump() for h in project.room_hints]),
                project.created_at,
                project.updated_at,
            ),
        )
        ensure_layout(project.project_id)
        return project

    def get(self, project_id: str) -> ProjectRecord:
        row = self._db.one("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        if row is None:
            raise ProjectNotFound(project_id)
        return _row_to_project(row)

    def find(self, project_id: str) -> Optional[ProjectRecord]:
        try:
            return self.get(project_id)
        except ProjectNotFound:
            return None

    def list(self) -> list[ProjectRecord]:
        rows = self._db.query("SELECT * FROM projects ORDER BY created_at ASC")
        return [_row_to_project(r) for r in rows]

    def set_stage(self, project_id: str, stage: ProjectStage) -> ProjectRecord:
        self._db.execute(
            "UPDATE projects SET stage = ?, updated_at = ? WHERE project_id = ?",
            (stage.value, _now(), project_id),
        )
        return self.get(project_id)

    def update(
        self,
        project_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        room_hints: Optional[list[RoomHint]] = None,
    ) -> ProjectRecord:
        current = self.get(project_id)
        self._db.execute(
            """UPDATE projects SET name = ?, description = ?, room_hints = ?, updated_at = ?
               WHERE project_id = ?""",
            (
                name if name is not None else current.name,
                description if description is not None else current.description,
                json.dumps(
                    [h.model_dump() for h in (room_hints if room_hints is not None else current.room_hints)]
                ),
                _now(),
                project_id,
            ),
        )
        return self.get(project_id)

    def attach_scene(self, project_id: str, scene_id: str) -> ProjectRecord:
        with self._db.tx() as c:
            row = c.execute("SELECT scene_ids FROM projects WHERE project_id = ?", (project_id,)).fetchone()
            if row is None:
                raise ProjectNotFound(project_id)
            ids = json.loads(row["scene_ids"])
            if scene_id not in ids:
                ids.append(scene_id)
            c.execute(
                "UPDATE projects SET scene_ids = ?, updated_at = ? WHERE project_id = ?",
                (json.dumps(ids), _now(), project_id),
            )
        return self.get(project_id)

    # ── inputs ───────────────────────────────────────────────────
    def add_input(self, record: InputRecord) -> InputRecord:
        self._db.execute(
            """INSERT INTO inputs(input_id, project_id, kind, filename, path, content_type,
                                  size_bytes, meta, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                record.input_id,
                record.project_id,
                record.kind.value,
                record.filename,
                record.path,
                record.content_type,
                record.size_bytes,
                json.dumps(record.meta),
                record.created_at,
            ),
        )
        return record

    def list_inputs(self, project_id: str, kind: Optional[InputKind] = None) -> list[InputRecord]:
        if kind is None:
            rows = self._db.query(
                "SELECT * FROM inputs WHERE project_id = ? ORDER BY created_at ASC", (project_id,)
            )
        else:
            rows = self._db.query(
                "SELECT * FROM inputs WHERE project_id = ? AND kind = ? ORDER BY created_at ASC",
                (project_id, kind.value),
            )
        return [_row_to_input(r) for r in rows]

    # ── analyses ─────────────────────────────────────────────────
    def next_analysis_version(self, project_id: str, kind: str) -> int:
        current = self._db.scalar(
            "SELECT MAX(version) FROM analyses WHERE project_id = ? AND kind = ?", (project_id, kind)
        )
        return int(current or 0) + 1

    def add_analysis(self, project_id: str, kind: str, path: str, version: Optional[int] = None) -> dict:
        from ..scene.schema import new_id

        version = version or self.next_analysis_version(project_id, kind)
        record = {
            "analysis_id": new_id("an"),
            "project_id": project_id,
            "kind": kind,
            "version": version,
            "path": path,
            "created_at": _now(),
        }
        self._db.execute(
            "INSERT INTO analyses(analysis_id, project_id, kind, version, path, created_at) VALUES (?,?,?,?,?,?)",
            (record["analysis_id"], project_id, kind, version, path, record["created_at"]),
        )
        return record

    def list_analyses(self, project_id: str) -> list[dict]:
        rows = self._db.query(
            "SELECT * FROM analyses WHERE project_id = ? ORDER BY kind, version", (project_id,)
        )
        return [dict(r) for r in rows]

    # ── scene specs ──────────────────────────────────────────────
    def add_scene_spec(self, project_id: str, scene_id: str, version: int, path: str) -> dict:
        from ..scene.schema import new_id

        record = {
            "spec_id": new_id("spec"),
            "project_id": project_id,
            "scene_id": scene_id,
            "version": version,
            "path": path,
            "created_at": _now(),
        }
        self._db.execute(
            "INSERT INTO scene_specs(spec_id, project_id, scene_id, version, path, created_at) VALUES (?,?,?,?,?,?)",
            (record["spec_id"], project_id, scene_id, version, path, record["created_at"]),
        )
        return record

    def list_scene_specs(self, project_id: str) -> list[dict]:
        rows = self._db.query(
            "SELECT * FROM scene_specs WHERE project_id = ? ORDER BY created_at", (project_id,)
        )
        return [dict(r) for r in rows]

    # ── outputs ──────────────────────────────────────────────────
    def add_output(self, project_id: str, kind: str, path: str, url: str = "", meta: Optional[dict] = None) -> dict:
        from ..scene.schema import new_id

        record = {
            "output_id": new_id("out"),
            "project_id": project_id,
            "kind": kind,
            "path": path,
            "url": url,
            "meta": meta or {},
            "created_at": _now(),
        }
        self._db.execute(
            "INSERT INTO outputs(output_id, project_id, kind, path, url, meta, created_at) VALUES (?,?,?,?,?,?,?)",
            (record["output_id"], project_id, kind, path, url, json.dumps(record["meta"]), record["created_at"]),
        )
        return record

    def list_outputs(self, project_id: str) -> list[dict]:
        rows = self._db.query(
            "SELECT * FROM outputs WHERE project_id = ? ORDER BY created_at ASC", (project_id,)
        )
        return [
            {
                "output_id": r["output_id"],
                "project_id": r["project_id"],
                "kind": r["kind"],
                "path": r["path"],
                "url": r["url"],
                "meta": json.loads(r["meta"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── migration from the old projects.json ─────────────────────
    def migrate_legacy(self, legacy_path: Path) -> int:
        """Import projects from the pre-SQLite projects.json (idempotent).
        The file is left in place, renamed with a .migrated suffix."""
        if not legacy_path.exists():
            return 0
        try:
            raw = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        imported = 0
        for item in raw:
            pid = item.get("project_id")
            if not pid or self.find(pid) is not None:
                continue
            self.create(
                name=item.get("name", pid),
                project_id=pid,
                scene_ids=list(item.get("scene_ids", [])),
                created_at=item.get("created_at"),
            )
            imported += 1
        legacy_path.rename(legacy_path.with_suffix(".json.migrated"))
        return imported


_store: Optional[ProjectStore] = None
_lock = threading.Lock()


def get_project_store() -> ProjectStore:
    global _store
    with _lock:
        if _store is None:
            _store = ProjectStore()
        return _store


def reset_project_store() -> None:
    global _store
    with _lock:
        _store = None

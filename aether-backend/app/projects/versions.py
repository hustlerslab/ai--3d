"""P1-FRONTEND-004: design versions - protect an accepted design from a later
experiment.

A version is an immutable copy of the committed scene (`design_versions`,
schema v13), never a pointer into the scene store's history: that history is
an undo stack which truncates on commit-after-undo and keeps only
MAX_HISTORY snapshots, so an accepted design stored there can be lost to
ordinary editing.

"Current" is computed, not stored: a version is current exactly when the live
scene's content hash equals the version's. A stored pointer would go stale the
moment someone moved a chair; the hash cannot.

Restoring commits the saved snapshot as the scene's new head, through the
store's own optimistic lock. Nothing is rewritten: the experiment being left
behind stays in the undo history and, if it was saved, stays a version.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from ..db import get_db
from ..scene.schema import Scene, new_id
from ..scene.store import get_store

#: Fields that change on every commit without changing the design itself.
_VOLATILE_METADATA = ("created_at", "updated_at")


class DesignVersion(BaseModel):
    version_id: str
    number: int
    label: str
    accepted: bool
    scene_id: str
    scene_version: int
    content_sha256: str
    created_by: str
    created_at: str
    is_current: bool = False


class VersionNotFound(LookupError):
    pass


class NoScene(LookupError):
    pass


def canonical(scene: Scene | dict[str, Any]) -> str:
    """The design, as bytes: the scene without its commit counter, its commit
    timestamps and the id of the scene record holding it (a design restored
    into a re-planned project's newer scene is still that design). Two scenes
    with the same canonical text are the same design."""
    data = scene.model_dump(mode="json") if isinstance(scene, Scene) else dict(scene)
    data.pop("version", None)
    data.pop("scene_id", None)
    meta = {k: v for k, v in (data.get("metadata") or {}).items() if k not in _VOLATILE_METADATA}
    data["metadata"] = meta
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def content_hash(scene: Scene | dict[str, Any]) -> str:
    return hashlib.sha256(canonical(scene).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r, live_hash: Optional[str]) -> DesignVersion:
    return DesignVersion(
        version_id=r["version_id"], number=r["number"], label=r["label"], accepted=bool(r["accepted"]),
        scene_id=r["scene_id"], scene_version=r["scene_version"], content_sha256=r["content_sha256"],
        created_by=r["created_by"], created_at=r["created_at"], is_current=r["content_sha256"] == live_hash,
    )


def _live(project_id: str) -> Scene:
    from . import get_project_store

    project = get_project_store().get(project_id)
    if not project.scene_ids:
        raise NoScene(project_id)
    return get_store().load(project.scene_ids[-1])


def list_versions(project_id: str) -> tuple[list[DesignVersion], bool]:
    """Every saved version, oldest first, and whether the live scene has
    changes no version holds."""
    try:
        live_hash = content_hash(_live(project_id))
    except NoScene:
        live_hash = None
    rows = get_db().query("SELECT * FROM design_versions WHERE project_id = ? ORDER BY number", (project_id,))
    versions = [_row(r, live_hash) for r in rows]
    unsaved = live_hash is not None and not any(v.is_current for v in versions)
    return versions, unsaved


def save(project_id: str, *, label: str = "", accept: bool = False, created_by: str = "") -> DesignVersion:
    scene = _live(project_id)
    db = get_db()
    last = db.query("SELECT MAX(number) AS n FROM design_versions WHERE project_id = ?", (project_id,))
    number = int(last[0]["n"] or 0) + 1
    snapshot = scene.model_dump(mode="json")
    digest = content_hash(snapshot)
    vid = new_id("ver")
    db.execute(
        "INSERT INTO design_versions(version_id, project_id, number, label, accepted, scene_id, scene_version, "
        "content_sha256, snapshot, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (vid, project_id, number, label.strip()[:80] or f"Version {number}", int(accept), scene.scene_id,
         scene.version, digest, json.dumps(snapshot, sort_keys=True), created_by, _now()),
    )
    return get(project_id, vid)[0]


def get(project_id: str, version_id: str) -> tuple[DesignVersion, str]:
    """The version and its stored snapshot text, exactly as saved."""
    rows = get_db().query("SELECT * FROM design_versions WHERE project_id = ? AND version_id = ?",
                          (project_id, version_id))
    if not rows:
        raise VersionNotFound(version_id)
    try:
        live_hash = content_hash(_live(project_id))
    except NoScene:
        live_hash = None
    return _row(rows[0], live_hash), rows[0]["snapshot"]


SCENE_SPEC = "planning/scene_spec.json"


def _set_baseline(project_id: str, scene: Scene) -> bool:
    """Make `scene` the plan snapshot `check_scene` compares against (it
    reports pieces missing from the committed scene relative to this file).
    A version the person chose is the baseline, or restoring one without a
    piece they removed on purpose would be escalated as missing furniture.
    Returns True when the file changed."""
    from .layout import project_dir

    path = project_dir(project_id) / SCENE_SPEC
    if path.exists():
        try:
            if content_hash(json.loads(path.read_text(encoding="utf-8"))) == content_hash(scene):
                return False
        except (ValueError, TypeError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene.model_dump(mode="json"), indent=2), encoding="utf-8")
    return True


def restore(project_id: str, version_id: str) -> tuple[DesignVersion, Scene]:
    """Make a saved version the live design: commit its snapshot as the new
    head, and make it the baseline. A version that is already the live design
    commits nothing - but still becomes the baseline, because choosing it is
    the point."""
    from . import get_project_store

    version, text = get(project_id, version_id)
    store = get_store()
    live = _live(project_id)
    if version.is_current:
        _set_baseline(project_id, live)
        return version, live
    saved = Scene.model_validate(json.loads(text))
    if saved.scene_id != live.scene_id:
        # The project was re-planned into a new scene since this was saved.
        # Restore into the live scene id so every stage reading the project's
        # latest scene sees it; the design content is unchanged.
        saved = saved.model_copy(update={"scene_id": live.scene_id})
    committed = store.commit(saved, base_version=live.version)
    _set_baseline(project_id, committed)
    get_project_store().add_scene_spec(project_id, committed.scene_id, committed.version, SCENE_SPEC)
    return get(project_id, version_id)[0], committed


__all__ = ["DesignVersion", "NoScene", "VersionNotFound", "canonical", "content_hash", "get", "list_versions",
           "restore", "save"]

"""On-disk project layout (DPR §20).

data/projects/{project_id}/
  input/          description.txt, dimensions.json, references/
  analysis/       design_analysis.json, moodboard_spec.json
  planning/       object_plan.json, asset_plan.json, scene_spec.json
  assets/         reused/, generated/
  blender/        build_manifest.json, scene.blend, validation_report.json
  previews/
  renders/
  outputs/        manifest.json, web/
  logs/

A stage checkpoint is simply the presence of its output file, so resume
logic never needs a second source of truth.
"""
from __future__ import annotations

from pathlib import Path

from ..core.config import get_settings

SUBDIRS = [
    "input/references",
    "analysis",
    "planning",
    "assets/reused",
    "assets/generated",
    "blender",
    "previews",
    "renders",
    "outputs/web",
    "logs",
]

# Canonical checkpoint files per pipeline stage (relative to the project dir).
CHECKPOINTS = {
    "inputs": "input/description.txt",
    "analysis": "analysis/design_analysis.json",
    "moodboard": "analysis/moodboard_spec.json",
    # The crops read back out of the approved moodboard, awaiting review.
    # Listed here so the Studio can show the review panel for a project it is
    # merely opening, not only for one whose plan it just ran.
    "scene_reading": "planning/scene_reading.json",
    "object_plan": "planning/object_plan.json",
    "asset_plan": "planning/asset_plan.json",
    # The client's own reference photos, classified into typed design intent.
    "design_intent": "planning/design_intent.json",
    "scene_spec": "planning/scene_spec.json",
    # Repair / intent-evaluation / consistency summary of the committed scene.
    "spatial_check": "planning/spatial_check.json",
    # Did the references' visual attributes survive into the committed scene?
    "visual_intent_fidelity": "planning/visual_intent_fidelity.json",
    "build_manifest": "blender/build_manifest.json",
    "scene_blend": "blender/scene.blend",
    "validation_report": "blender/validation_report.json",
    "camera_path": "blender/camera_path.json",
    "preview": "previews/preview.mp4",
    "walkthrough": "renders/walkthrough.mp4",
    "outputs": "outputs/manifest.json",
}


def safe_id(project_id: str) -> str:
    safe = "".join(c for c in project_id if c.isalnum() or c in "_-")
    if not safe:
        raise ValueError("invalid project id")
    return safe


def project_dir(project_id: str, create: bool = False) -> Path:
    path = get_settings().projects_dir / safe_id(project_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_layout(project_id: str) -> Path:
    root = project_dir(project_id, create=True)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def archive_project(project_id: str, *, name: str = "", description: str = "",
                    vertical: str = "") -> dict:
    """Keep what a deleted project produced; report exactly what was kept.

    Three things outlive the project record they hang off:

      * the reference photographs the user uploaded, which are theirs and
        cannot be regenerated from anything,
      * the moodboard renders, which the client approved and which are the
        brief for everything downstream, and
      * the meshes generated from them, at 30 credits each.

    The meshes already live outside the project folder, in the shared asset
    store keyed by `project_id`, so deleting the project never touched them —
    but afterwards nothing would point at them. This manifest is that pointer.

    Copies, never moves: the delete that follows removes the project folder
    wholesale, and an archive built by moving files would be left half empty
    if it failed midway.
    """
    import json
    import shutil
    from datetime import datetime, timezone

    src = project_dir(project_id)
    dest = get_settings().data_dir / "archive" / safe_id(project_id)
    dest.mkdir(parents=True, exist_ok=True)

    kept: dict = {}

    # Every moodboard image, not only the per-room split: older projects hold a
    # single `moodboard_scene.png`, and keeping only `moodboard_room_*.png`
    # archived those projects as an empty folder.
    rooms = sorted((src / "analysis").glob("moodboard_*.png")) if src.is_dir() else []
    if rooms:
        (dest / "moodboard").mkdir(exist_ok=True)
        for png in rooms:
            shutil.copy2(png, dest / "moodboard" / png.name)
    kept["moodboard_rooms"] = len(rooms)

    # The uploads are the one thing here that no amount of credits or GPU time
    # can produce again: they are the user's own photographs of their own room.
    refs = sorted(p for p in (src / "input" / "references").glob("*") if p.is_file())
    if refs:
        (dest / "references").mkdir(exist_ok=True)
        for ref in refs:
            shutil.copy2(ref, dest / "references" / ref.name)
    kept["references"] = len(refs)
    for rel in ("input/description.txt", "input/dimensions.json"):
        found = src / rel
        if found.is_file():
            shutil.copy2(found, dest / found.name)

    for rel in ("analysis/moodboard_spec.json", "analysis/design_analysis.json",
                "analysis/style_spec.json", "planning/scene_reading.json"):
        found = src / rel
        if found.is_file():
            shutil.copy2(found, dest / found.name)

    crops = src / "planning" / "scene_crops"
    if crops.is_dir():
        shutil.copytree(crops, dest / "scene_crops", dirs_exist_ok=True)
        kept["scene_crops"] = sum(1 for _ in (dest / "scene_crops").rglob("*.png"))

    # The generated meshes survive on their own; only this list records which
    # of them were this project's.
    try:
        from ..assets.registry import get_registry

        kept["asset_ids"] = sorted(r.asset_id for r in get_registry().list()
                                   if r.project_id == project_id)
    except Exception:                                      # noqa: BLE001
        kept["asset_ids"] = []

    manifest = {
        "project_id": project_id,
        "name": name,
        "vertical": vertical,
        "description": description,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "kept": kept,
        "note": "Uploaded references, moodboard renders and generated meshes are "
                "kept for reuse. The meshes live in the shared asset store under "
                "these ids.",
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def file_url(project_id: str, relative: str) -> str:
    """Public URL for a file inside the project dir (served at /files/projects)."""
    rel = relative.replace("\\", "/").lstrip("/")
    return f"/files/projects/{safe_id(project_id)}/{rel}"

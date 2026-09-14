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
    "scene_spec": "planning/scene_spec.json",
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


def file_url(project_id: str, relative: str) -> str:
    """Public URL for a file inside the project dir (served at /files/projects)."""
    rel = relative.replace("\\", "/").lstrip("/")
    return f"/files/projects/{safe_id(project_id)}/{rel}"

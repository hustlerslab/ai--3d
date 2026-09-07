"""Assemble the InputBundle for a project from the store and the input folder."""
from __future__ import annotations

from ..projects import InputKind, get_project_store
from ..projects.layout import file_url, project_dir
from .schema import InputBundle, ReferenceImage


def build_input_bundle(project_id: str) -> InputBundle:
    store = get_project_store()
    project = store.get(project_id)
    root = project_dir(project_id)

    description = project.description
    desc_file = root / "input" / "description.txt"
    if desc_file.exists():
        description = desc_file.read_text(encoding="utf-8").strip() or description

    references: list[ReferenceImage] = []
    for rec in store.list_inputs(project_id, InputKind.reference):
        path = root / rec.path
        if path.exists():
            references.append(
                ReferenceImage(
                    path=str(path),
                    url=file_url(project_id, rec.path),
                    filename=rec.filename,
                    content_type=rec.content_type or "image/jpeg",
                )
            )

    return InputBundle(
        project_id=project_id,
        project_name=project.name,
        description=description,
        room_hints=list(project.room_hints),
        references=references,
    )

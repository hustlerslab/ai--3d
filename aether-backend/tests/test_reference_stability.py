"""A photo deleted after the reading must never re-point it at another photo.

`image_index` is the position the model answered with ("the sofa is in photo
3"). It is correct at the moment the reading is made and wrong forever after
the bundle changes shape: delete one upload and every later index slides down
one, so the sofa's index lands on somebody else's photo. Two consumers used it
directly — the crops that texture objects and seed image-to-3D, and the photo
the moodboard render is conditioned on — and both went wrong quietly, which is
the part that matters: an unconditioned render is a perfectly good picture of a
room that is not the client's.

These tests pin the two halves of the fix: resolution happens on the upload's
stable id, and a reference that cannot be resolved is visible.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from app.intelligence import build_input_bundle
from app.intelligence.coerce import coerce_analysis
from app.intelligence.crops import write_crops
from app.intelligence.mock_provider import build_moodboard
from app.intelligence.schema import StyleSpec
from app.jobs.handlers.analyze import _add_scene_image, _scene_reference
from app.projects import InputKind, get_project_store
from app.projects.layout import project_dir
from app.projects.schema import InputRecord
from app.providers import local_image

# Three uploads in flat, unmistakable colours; the reading finds the sofa in
# the third. Deleting an earlier one slides the sofa down a position, so
# anything still reading position 2 gets the wrong photo — the live bug.
COLORS = {"a.png": (10, 10, 200), "b.png": (10, 200, 10), "sofa.png": (200, 10, 10)}

RAW = {
    "intent": "Living room refresh",
    "rooms": [{"name": "Living Room", "type": "living_room", "width_m": 5.0, "length_m": 4.0}],
    "spotted_objects": [
        {"name": "navy velvet sofa", "semantic_type": "sofa", "family": "seating", "placement": "floor",
         "room_name": "Living Room", "image_index": 2, "bbox": [0.1, 0.1, 0.9, 0.9], "confidence": 0.9},
    ],
}


def _project_with_photos(names: list[str]) -> tuple[str, dict[str, str]]:
    """A project holding `names` as reference uploads. Returns its id and a
    filename → input_id map, so a test can delete a specific one."""
    store = get_project_store()
    project = store.create("ref-stability", description="Living room refresh")
    root = project_dir(project.project_id)
    ids: dict[str, str] = {}
    for name in names:
        rel = f"input/{name}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (400, 300), COLORS[name]).save(root / rel)
        rec = store.add_input(
            InputRecord(
                project_id=project.project_id, kind=InputKind.reference, filename=name,
                path=rel, content_type="image/png", size_bytes=(root / rel).stat().st_size,
                created_at="2026-09-12T00:00:00Z",
            )
        )
        ids[name] = rec.input_id
    return project.project_id, ids


def _drop(project_id: str, name: str, input_id: str) -> None:
    get_project_store().delete_input(project_id, input_id)
    (project_dir(project_id) / f"input/{name}").unlink()


def test_deleting_a_photo_does_not_re_point_the_reading_at_another_photo(env):
    project_id, ids = _project_with_photos(["a.png", "b.png", "sofa.png"])
    analysis = coerce_analysis(RAW, build_input_bundle(project_id), [], provider="test")
    sofa = analysis.spotted_objects[0]
    assert sofa.image_ref == ids["sofa.png"], "the position must be pinned to the upload id at coercion time"

    _drop(project_id, "a.png", ids["a.png"])
    shifted = build_input_bundle(project_id)
    assert len(shifted.references) == 2

    # The stale index (2) is now out of range; a positional lookup would have
    # fallen through to "any upload" and quietly conditioned on b.png.
    photo = shifted.photo_for(sofa)
    assert photo is not None and photo.filename == "sofa.png"

    reference, note = _scene_reference(analysis, shifted)
    assert reference is not None and reference.name == "sofa.png"
    assert "sofa" in note.lower()


def test_crops_follow_the_photo_not_the_position(env):
    project_id, ids = _project_with_photos(["a.png", "b.png", "sofa.png"])
    analysis = coerce_analysis(RAW, build_input_bundle(project_id), [], provider="test")
    root = project_dir(project_id)

    _drop(project_id, "b.png", ids["b.png"])
    write_crops(analysis, build_input_bundle(project_id), root, force=True)

    crop = analysis.spotted_objects[0].crop_ref
    assert crop, "the sofa's photo is still in the project, so its crop must still be cut"
    with Image.open(root / crop) as im:
        r, g, b = im.getpixel((im.size[0] // 2, im.size[1] // 2))
    assert r > 150 and g < 60, f"crop came from the wrong photo: {(r, g, b)}"


def test_a_deleted_photo_is_reported_never_silently_dropped(env):
    project_id, ids = _project_with_photos(["a.png", "sofa.png"])
    analysis = coerce_analysis(RAW, build_input_bundle(project_id), [], provider="test")
    root = project_dir(project_id)

    for name in ("a.png", "sofa.png"):                 # every upload gone
        _drop(project_id, name, ids[name])
    empty = build_input_bundle(project_id)

    reference, note = _scene_reference(analysis, empty)
    assert reference is None
    assert "gone from the project" in note and "sofa" in note.lower()

    warnings = write_crops(analysis, empty, root, force=True)
    assert any("no longer in the project" in w for w in warnings)
    assert analysis.spotted_objects[0].crop_ref == ""


def test_generation_flags_an_unconditioned_render_instead_of_passing_it_off(env, monkeypatch, caplog):
    """The point of the whole fix: the render still happens, but nothing
    reports success on a scene that never saw the client's furniture."""
    project_id, ids = _project_with_photos(["sofa.png"])
    analysis = coerce_analysis(RAW, build_input_bundle(project_id), [], provider="test")
    _drop(project_id, "sofa.png", ids["sofa.png"])

    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "true")
    from app.core import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(local_image, "available", lambda: True)
    monkeypatch.setattr(local_image, "unload", lambda: None)
    seen: dict = {}

    def fake_generate(prompt, **kw):
        seen["references"] = kw.get("references")
        return local_image.GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                                          mime_type="image/png", model="sd15")

    monkeypatch.setattr(local_image, "generate", fake_generate)

    ctx = _StubContext(project_id)
    bundle = build_input_bundle(project_id)
    style = StyleSpec(name="warm_minimal")
    moodboard = build_moodboard(analysis, style, bundle)
    with caplog.at_level(logging.WARNING):
        _add_scene_image(ctx, moodboard, analysis, style, bundle)

    assert seen["references"] is None                       # nothing to condition on
    assert moodboard.scene_url                              # the board still gets its image
    assert moodboard.reference_resolved is False            # ...and the record says so
    assert "gone from the project" in moodboard.reference_note
    assert any(e["status"] == "warning" for e in ctx.events)
    assert ctx.outputs[-1][2]["reference_resolved"] is False


def test_unreadable_references_raise_rather_than_render_unconditioned(env, tmp_path):
    """A path that will not open used to be skipped, dropping straight through
    to plain text-to-image with nothing to tell the caller apart from success."""
    with pytest.raises(local_image.LocalImageError):
        local_image._open_references([tmp_path / "not-a-photo.png"])


class _StubContext:
    """Just enough JobContext for _add_scene_image: it writes one file under
    the project, emits events and records an output."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.projects = get_project_store()
        self.dir = project_dir(project_id)
        self.log = logging.getLogger("test.scene")
        self.events: list[dict] = []
        self.outputs: list[tuple] = []

    def path(self, relative: str) -> Path:
        p = self.dir / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def emit(self, stage: str, message: str = "", status: str = "progress") -> None:
        self.events.append({"stage": stage, "message": message, "status": status})

    def add_output(self, kind: str, path: str, meta: dict) -> None:
        self.outputs.append((kind, path, meta))

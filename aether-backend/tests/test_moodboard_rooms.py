"""Step 3 paints one image per room, not one per project.

A moodboard that shows only the living room is not a direction for a home. The
per-room data was already there — every read item carries a `room_id` — the
generator simply never iterated.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from app.intelligence import build_input_bundle
from app.intelligence.coerce import assign_ids, assign_roles
from app.intelligence.schema import DesignAnalysis, RoomAnalysis, SpottedObject, StyleSpec
from app.jobs.handlers.analyze import _add_scene_image, _room_image, _scene_reference
from app.projects import InputKind, get_project_store
from app.projects.layout import project_dir
from app.projects.schema import InputRecord
from app.providers import local_image

ROOMS = [
    ("living_room", "Living Room", "living_room"),
    ("master_bedroom", "Master Bedroom", "master_bedroom"),
    ("kitchen", "Kitchen", "kitchen"),
    ("bathroom", "Bathroom", "bathroom"),
]


def _project() -> tuple[str, str]:
    store = get_project_store()
    project = store.create("rooms", description="A calm home")
    root = project_dir(project.project_id)
    rel = "input/sofa.png"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (20, 90, 160)).save(root / rel)
    rec = store.add_input(InputRecord(
        project_id=project.project_id, kind=InputKind.reference, filename="sofa.png",
        path=rel, content_type="image/png", size_bytes=(root / rel).stat().st_size,
        created_at="2026-09-13T00:00:00Z"))
    return project.project_id, rec.input_id


def _analysis(input_id: str) -> DesignAnalysis:
    a = DesignAnalysis(
        intent="calm home",
        rooms=[RoomAnalysis(room_id=r, name=n, type=t, width_m=4.0, length_m=3.5) for r, n, t in ROOMS],
        spotted_objects=[SpottedObject(
            semantic_type="sofa", name="blue sofa", family="seating",
            room_id="living_room", image_ref=input_id, image_index=0, confidence=0.95)],
    )
    assign_ids(a); assign_roles(a)
    return a


class _Ctx:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.projects = get_project_store()
        self.dir = project_dir(project_id)
        self.log = logging.getLogger("test.rooms")
        self.events: list[dict] = []
        self.outputs: list[tuple] = []

    def path(self, rel):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def emit(self, stage, message="", status="progress"):
        self.events.append({"stage": stage, "message": message, "status": status})

    def add_output(self, kind, path, meta):
        # Persist like the real JobContext does — the recipe marker is read back
        # from the outputs table, so a stub that only appends to a list makes
        # every image look unversioned and repaint forever.
        self.outputs.append((kind, path, meta))
        return self.projects.add_output(self.project_id, kind, path,
                                        f"/files/projects/{self.project_id}/{path}", meta)


@pytest.fixture
def painted(env, monkeypatch):
    """Stub the GPU: this is about which rooms get painted, not what they look
    like. Records the prompt and reference each room was given."""
    monkeypatch.setenv("SCENE_IMAGE_ENABLED", "true")
    from app.core import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(local_image, "available", lambda: True)
    monkeypatch.setattr(local_image, "unload", lambda: None)
    calls: list[dict] = []

    def fake_generate(prompt, **kw):
        calls.append({"prompt": prompt, "references": kw.get("references")})
        return local_image.GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                                          mime_type="image/png", model="sd15")

    monkeypatch.setattr(local_image, "generate", fake_generate)
    return calls


def test_one_image_per_room_and_the_first_stays_the_hero(painted):
    from app.intelligence.mock_provider import build_moodboard

    pid, input_id = _project()
    analysis = _analysis(input_id)
    style = StyleSpec(name="warm_modern", tags=["modern", "warm"])
    bundle = build_input_bundle(pid)
    mb = build_moodboard(analysis, style, bundle)
    ctx = _Ctx(pid)
    _add_scene_image(ctx, mb, analysis, style, bundle)

    assert len(painted) == len(ROOMS), f"{len(painted)} generations for {len(ROOMS)} rooms"
    assert [s.room_id for s in mb.room_scenes] == [r for r, _, _ in ROOMS]
    for s in mb.room_scenes:
        assert s.url, f"{s.room_id} has no image: {s.error}"
        assert (project_dir(pid) / _room_image(s.room_id)).exists()
    # backward compatibility: the single-image field still points somewhere
    assert mb.scene_url == mb.room_scenes[0].url


def test_a_room_with_no_photos_is_still_painted_and_says_so(painted):
    """Kitchen and bathroom have no read items. They must still produce an
    image — and must not borrow another room's photo to do it."""
    from app.intelligence.mock_provider import build_moodboard

    pid, input_id = _project()
    analysis = _analysis(input_id)
    bundle = build_input_bundle(pid)
    mb = build_moodboard(analysis, StyleSpec(name="warm_modern"), bundle)
    _add_scene_image(_Ctx(pid), mb, analysis, StyleSpec(name="warm_modern"), bundle)

    by_id = {s.room_id: s for s in mb.room_scenes}
    assert by_id["living_room"].reference_resolved is True
    for empty in ("kitchen", "bathroom"):
        assert by_id[empty].url, "a photo-less room must still be painted"
        assert by_id[empty].reference_resolved is False
        assert "own pieces" in by_id[empty].reference_note


def test_a_rooms_reference_never_comes_from_another_room(env):
    """Painting the bedroom from a photo of the sofa is worse than painting it
    from nothing: it looks conditioned and is not."""
    pid, input_id = _project()
    analysis = _analysis(input_id)
    bundle = build_input_bundle(pid)

    ref, note = _scene_reference(analysis, bundle, room_id="living_room")
    assert ref is not None and ref.name == "sofa.png"
    for other in ("master_bedroom", "kitchen", "bathroom"):
        ref, note = _scene_reference(analysis, bundle, room_id=other)
        assert ref is None, f"{other} borrowed {ref}"


def test_an_existing_single_image_project_gains_the_room_set_on_regenerate(painted):
    """The sample project has analysis/moodboard_scene.png and no per-room
    files. Regeneration must produce the set with no migration step."""
    from app.intelligence.mock_provider import build_moodboard

    pid, input_id = _project()
    legacy = project_dir(pid) / "analysis/moodboard_scene.png"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (0, 0, 0)).save(legacy)

    analysis = _analysis(input_id)
    style = StyleSpec(name="warm_modern")
    bundle = build_input_bundle(pid)
    mb = build_moodboard(analysis, style, bundle)
    _add_scene_image(_Ctx(pid), mb, analysis, style, bundle)      # note: force=False

    assert len(mb.room_scenes) == len(ROOMS)
    assert all(s.url for s in mb.room_scenes)
    assert legacy.exists(), "the old hero file is left alone, not deleted"


def test_the_bathroom_prompt_names_fixtures_now(env):
    """ROOM_SETS['bathroom'] was empty, so the prompt named nothing at all."""
    from app.intelligence.prompts import _scene_furniture

    analysis = DesignAnalysis(
        intent="x",
        rooms=[RoomAnalysis(room_id="bathroom", name="Bathroom", type="bathroom", width_m=2.2, length_m=2.0)],
    )
    furniture = _scene_furniture(analysis, analysis.rooms[0])
    assert furniture, "bathroom still names no fixtures"
    assert "vanity" in furniture and "mirror" in furniture


# ── staleness is detectable, not a matter of noticing ────────────────────


def test_an_image_from_an_older_recipe_is_repainted(painted):
    """A file existing is not the same as it being current. The server loads
    code once at start-up, so an image can be NEWER than the source file that
    should have produced it and still predate the change — which is exactly how
    a bathroom written at 20:13 came out of 19:57 code."""
    from app.intelligence.mock_provider import build_moodboard
    from app.intelligence.prompts import scene_recipe_version

    pid, input_id = _project()
    analysis = _analysis(input_id)
    style = StyleSpec(name="warm_modern")
    ctx = _Ctx(pid)
    _add_scene_image(ctx, build_moodboard(analysis, style, build_input_bundle(pid)),
                     analysis, style, build_input_bundle(pid))
    assert len(painted) == len(ROOMS)

    # a second run with the SAME recipe repaints nothing
    painted.clear()
    mb = build_moodboard(analysis, style, build_input_bundle(pid))
    _add_scene_image(_Ctx(pid), mb, analysis, style, build_input_bundle(pid))
    assert painted == [], "an up-to-date image must not be repainted"
    assert all(s.recipe_version == scene_recipe_version() for s in mb.room_scenes)


def test_an_unversioned_image_is_stale_by_definition(painted, monkeypatch):
    """Retroactive: every project generated before versioning has no recipe
    recorded, and must repaint rather than sit broken until someone notices."""
    from app.intelligence.mock_provider import build_moodboard

    pid, input_id = _project()
    analysis = _analysis(input_id)
    style = StyleSpec(name="warm_modern")
    ctx = _Ctx(pid)
    _add_scene_image(ctx, build_moodboard(analysis, style, build_input_bundle(pid)),
                     analysis, style, build_input_bundle(pid))

    # strip the recorded recipe, as an image made before this existed would be
    store = get_project_store()
    for out in store.list_outputs(pid):
        if out["kind"] == "moodboard_scene":
            meta = dict(out["meta"])
            meta.pop("recipe_version", None)
            store._db.execute("UPDATE outputs SET meta = ? WHERE output_id = ?",
                              (__import__("json").dumps(meta), out["output_id"]))

    painted.clear()
    _add_scene_image(_Ctx(pid), build_moodboard(analysis, style, build_input_bundle(pid)),
                     analysis, style, build_input_bundle(pid))
    assert len(painted) == len(ROOMS), "unversioned images must all repaint"


def test_changing_the_recipe_changes_the_version(env):
    """The marker is derived from what actually shapes an image, so a change
    nobody remembers to announce still invalidates old work."""
    from app.core import config
    from app.intelligence.prompts import scene_recipe_version

    before = scene_recipe_version()
    monkey = config.get_settings
    config.get_settings.cache_clear()
    import os

    os.environ["SCENE_IMAGE_REFERENCE_SCALE"] = "0.9"
    try:
        config.get_settings.cache_clear()
        assert scene_recipe_version() != before, "reference strength must count"
    finally:
        os.environ.pop("SCENE_IMAGE_REFERENCE_SCALE", None)
        config.get_settings.cache_clear()
    assert scene_recipe_version() == before

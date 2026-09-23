"""P1-IDENTITY-003 - the provenance chain survives the last hop.

A Blender object, and therefore a rendered pixel region, could not be traced
back to the element that caused it: the manifest carried `object_id` and
nothing else about where the object came from.

Two things are pinned here, and the second was missing entirely.
`manifest_version` has been written into every manifest since 1.0 and **never
read by anything** - a version nobody checks is a comment. The reader now
refuses a major it does not understand, because building a scene from a
document you have misread fails silently and looks like success.

The Blender-side reader is exercised without launching Blender: its function is
lifted out of the script's AST, since importing `build_scene.py` runs `main()`
at module level and needs `bpy`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.blender.manifest import MANIFEST_VERSION, build_manifest
from app.scene.schema import Scene, SceneObject

BUILD_SCENE = Path(__file__).resolve().parents[1] / "blender" / "scripts" / "build_scene.py"

ELEMENT = "cel_1a2b3c4d5e"

#: The half of an object entry that decides what gets drawn. P1-IDENTITY-003
#: adds metadata beside it and must not disturb any of this.
GEOMETRY_KEYS = ("id", "semantic_type", "room_id", "strategy", "name", "location",
                 "rotation_rad", "scale", "dimensions", "color", "mount", "parent",
                 "material_overrides", "locked")


def _reader():
    """`require_supported_manifest` lifted out of the Blender script.

    Importing the module is not an option: it calls `main()` at import time and
    imports `bpy`. Lifting the function keeps this a real test of the shipped
    code rather than a re-implementation of it.
    """
    tree = ast.parse(BUILD_SCENE.read_text(encoding="utf-8"))
    wanted = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == "require_supported_manifest")
        or (isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") == "SUPPORTED_MANIFEST_MAJORS")
    ]
    assert len(wanted) == 2, "build_scene.py no longer defines the manifest version guard"
    namespace: dict = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "build_scene.py", "exec"), namespace)
    return namespace["require_supported_manifest"]


def _scene(with_identity: bool) -> Scene:
    common = {
        # Pinned. `object_id` has a random default_factory, so two scenes built
        # from the same literal are two different objects - which is correct
        # product behaviour and would make the comparisons below meaningless.
        # What is being tested is that ONE scene yields the same manifest.
        "object_id": "obj_fixed_for_test",
        "semantic_type": "bar_stool", "room_id": "kitchen",
        "position": (1.0, 0.0, 1.0), "dimensions": (0.4, 0.7, 0.4),
        "plan_key": "kitchen.bar_stool.0",
    }
    if with_identity:
        common["element_id"] = ELEMENT
        common["instance_id"] = ELEMENT + "#0"
    return Scene.model_validate({
        "scene_id": "scene_t", "project_id": "p", "name": "t",
        "rooms": [{
            "room_id": "kitchen", "name": "Kitchen", "type": "kitchen",
            "boundary": [[0, 0], [4, 0], [4, 3], [0, 3]],
            "floor_height": 0.0, "ceiling_height": 2.7,
        }],
        "objects": [SceneObject.model_validate(common).model_dump(mode="json")],
    })


def _manifest(tmp_path, with_identity=True):
    return build_manifest(_scene(with_identity), project_id="p",
                          project_root=tmp_path, preview=False)


# ── the three identity fields ────────────────────────────────────────────

def test_every_object_entry_carries_the_three_identity_fields(tmp_path):
    manifest = _manifest(tmp_path)
    assert manifest["objects"]
    for entry in manifest["objects"]:
        for field in ("element_id", "instance_id", "plan_key"):
            assert field in entry, f"{field} missing from a manifest object"


def test_identity_reaches_the_manifest_intact(tmp_path):
    entry = _manifest(tmp_path)["objects"][0]
    assert entry["element_id"] == ELEMENT
    assert entry["instance_id"] == ELEMENT + "#0"
    assert entry["plan_key"] == "kitchen.bar_stool.0"


def test_an_object_with_no_element_reports_null_rather_than_an_invented_id(tmp_path):
    """A catalog piece the planner added is not an occurrence of anything the
    client approved. Inventing an id here would put a fiction into the chain
    that every later consumer would treat as fact."""
    entry = _manifest(tmp_path, with_identity=False)["objects"][0]
    assert entry["element_id"] is None
    assert entry["instance_id"] is None
    assert entry["plan_key"] == "kitchen.bar_stool.0", "the old join survives"


# ── the version, and the reader that now actually reads it ───────────────

def test_the_manifest_version_was_bumped():
    major, minor = MANIFEST_VERSION.split(".")[:2]
    assert (int(major), int(minor)) >= (1, 2), MANIFEST_VERSION


def test_the_version_is_written_into_the_manifest(tmp_path):
    assert _manifest(tmp_path)["manifest_version"] == MANIFEST_VERSION


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", "1.9"])
def test_the_reader_accepts_any_minor_of_a_major_it_knows(version):
    """A minor bump only adds keys, which an older reader ignores harmlessly.
    Refusing those would make every additive change a breaking one."""
    _reader()({"manifest_version": version})


def test_the_reader_accepts_a_manifest_written_before_the_field_existed():
    """Absent is not unknown. Those are valid 1.x documents."""
    _reader()({})


@pytest.mark.parametrize("version", ["2.0", "3.1", "0.9"])
def test_the_reader_refuses_a_major_it_does_not_understand(version):
    """The point of the exercise: building from a document you have misread
    fails silently and looks like a successful build."""
    with pytest.raises(RuntimeError, match="does not understand"):
        _reader()({"manifest_version": version})


@pytest.mark.parametrize("version", ["banana", "v1", "x.y"])
def test_the_reader_refuses_a_version_it_cannot_parse(version):
    """Unparseable is refused, not optimistically treated as 1."""
    with pytest.raises(RuntimeError):
        _reader()({"manifest_version": version})


# ── the scene must be otherwise unchanged ────────────────────────────────

def test_adding_identity_changes_nothing_that_decides_what_is_drawn(tmp_path):
    """The criterion: the built scene is otherwise byte-identical for an
    unchanged input. Identity is metadata beside the geometry, not part of it,
    so the drawing half of every entry must be untouched by its presence."""
    with_id = _manifest(tmp_path, with_identity=True)["objects"][0]
    without = _manifest(tmp_path, with_identity=False)["objects"][0]

    for key in GEOMETRY_KEYS:
        assert with_id.get(key) == without.get(key), f"{key} changed with identity present"


def test_the_manifest_is_deterministic_for_one_scene(tmp_path):
    """Two manifests from one scene must agree, or a rebuild is a diff."""
    assert _manifest(tmp_path)["objects"] == _manifest(tmp_path)["objects"]

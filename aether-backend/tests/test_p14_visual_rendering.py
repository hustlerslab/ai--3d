"""P14: which attributes Blender actually paints, and the isolation that makes
it safe.

The measured registry has 10 multi-region assets out of 58, so a frame finish
renders on a minority of pieces and stays metadata on the rest. These assert
that split honestly against the real library, and that nothing shared is
mutated on the way.

PRESERVED is not RENDERED - P13 asserts the first, this file the second.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.assets import gltf
from app.assets.registry import get_registry
from app.blender.manifest import (_FINISH_ROUGHNESS, _finish_entry, _separable_regions,
                                  build_manifest)
from app.materials.registry import get_material_registry
from app.planning.compiler import finish_material_for
from app.planning.intent_fidelity import ExecutorSupport, VISUAL_ATTRIBUTE_CONTRACT
from app.scene.schema import ObjectVisual, Room, Scene, SceneObject


def _obj(asset_id=None, object_id="obj_1", position=(1.0, 0.0, 1.0), **visual) -> SceneObject:
    return SceneObject(object_id=object_id, semantic_type="sofa", room_id="r1",
                       asset_id=asset_id, position=position, dimensions=(2.0, 0.8, 0.9),
                       visual=ObjectVisual(**visual))


def _scene(objects) -> Scene:
    room = Room(room_id="r1", name="Living Room", boundary=[(0, 0), (6, 0), (6, 5), (0, 5)])
    return Scene(scene_id="s_p14", project_id="p_p14", rooms=[room], objects=list(objects))


def _real_assets_by_regions() -> tuple[str, str]:
    """One real asset id with a separable frame region and one without.
    Skips when the asset library is not present in this environment."""
    registry = get_registry()
    normalized = registry.root / "normalized"
    multi = single = ""
    for record in registry.list():
        path = normalized / f"{record.asset_id}.glb"
        if not path.exists():
            continue
        regions = _separable_regions(str(path))
        if regions >= 2 and not multi:
            multi = record.asset_id
        elif regions == 1 and not single:
            single = record.asset_id
        if multi and single:
            return multi, single
    pytest.skip("the real asset library is not available here")


# -- the resolver: a word only ever becomes a material that already exists --

@pytest.mark.parametrize("words,expected", [
    ("dark walnut", "veneer_walnut"),
    ("walnut", "veneer_walnut"),
    ("wooden armrests", "veneer_oak"),
    ("brushed brass", "metal_brass"),
    ("matte black steel", "metal_black"),
    ("glass", "glass_clear"),
])
def test_a_finish_resolves_only_to_a_material_the_registry_already_has(words, expected):
    resolved = finish_material_for(words)
    assert resolved == expected
    record = get_material_registry().get(resolved)
    assert record is not None, "P14 must never invent a material"
    assert "furniture" in record.applies_to


@pytest.mark.parametrize("words", ["quilted", "luxurious", "elegant", "hand-carved teak inlay", ""])
def test_a_finish_the_registry_cannot_represent_resolves_to_nothing(words):
    """Empty is a real answer. Repainting a piece the wrong species is worse
    than leaving the catalogue's own look alone."""
    assert finish_material_for(words) == ""


# -- the conditional tier, measured on real geometry ------------------------

def test_frame_finish_renders_only_where_the_real_asset_has_a_second_region():
    multi, single = _real_assets_by_regions()

    rendered = _finish_entry(_obj(multi, frame_finish="dark walnut"))
    assert rendered["state"] == "rendered"
    assert rendered["frame_material"] == "veneer_walnut"
    assert rendered["material_regions"] >= 2

    held = _finish_entry(_obj(single, frame_finish="dark walnut"))
    assert held["state"] == "metadata_only"
    assert held["material_regions"] < 2
    assert held["reason"], "a limit must say why"
    assert held["frame_material"] == "veneer_walnut", "understood, just not paintable here"


def test_an_object_with_no_asset_cannot_render_a_frame_finish():
    entry = _finish_entry(_obj(None, frame_finish="brushed brass"))
    assert entry["state"] == "metadata_only"
    assert entry["material_regions"] == 0


def test_an_unrepresentable_finish_is_unsupported_not_silently_dropped():
    entry = _finish_entry(_obj(frame_finish="hand-carved teak inlay"))
    assert entry["state"] == "unsupported"
    assert entry["frame_material"] == ""
    assert entry["reason"]
    assert entry["frame_finish"] == "hand-carved teak inlay", "the client word is kept"


# -- the two attributes P14 deliberately did NOT promote --------------------

def test_no_colour_word_is_ever_turned_into_a_colour():
    """There is no authoritative word-to-hex mapping anywhere in the
    repository, so a colour word must not become a rendered colour."""
    entry = _finish_entry(_obj(color_words=["sage green", "terracotta"]))
    assert entry["frame_material"] == ""
    assert entry["roughness"] is None
    assert entry["state"] == "none"
    assert VISUAL_ATTRIBUTE_CONTRACT["color_words"].executor is ExecutorSupport.PRESERVED_METADATA_ONLY


def test_the_resolved_hex_colour_channel_is_unchanged_by_p14(tmp_path):
    """`color` is the one channel the executor always paints. P14 adds a
    second channel beside it and must not touch it."""
    obj = _obj(color_words=["sage green"], frame_finish="dark walnut")
    obj.color = "#8a7862"
    manifest = build_manifest(_scene([obj]), project_id="p_p14", project_root=tmp_path,
                              preview=False)
    row = manifest["objects"][0]

    assert row["color"] == "#8a7862"
    assert row["finish"]["frame_material"] == "veneer_walnut"


def test_a_supported_pattern_is_preserved_and_an_unsupported_one_is_not_faked():
    """There is no pattern synthesis in the Blender path at all, so BOTH a
    common pattern and an exotic one are metadata. Nothing is invented for
    either, and neither is dropped."""
    for word in ("quilted", "herringbone", "block-printed ikat"):
        entry = _finish_entry(_obj(pattern=word))
        assert entry["state"] == "none"
        assert entry["frame_material"] == ""
    assert VISUAL_ATTRIBUTE_CONTRACT["pattern"].executor is ExecutorSupport.PRESERVED_METADATA_ONLY


# -- frame evidence that arrives in the wrong field -------------------------

@pytest.mark.parametrize("descriptors,expected", [
    (["tufted back", "wooden frame", "slatted armrest detail"], "veneer_oak"),
    (["quilted pull-out panel", "gold accent trim"], "metal_brass"),
    (["blackened steel legs"], "metal_black"),
])
def test_a_descriptor_that_names_a_part_supplies_the_frame_finish(descriptors, expected):
    """Measured on 8 real photographs: Gemini fills `frame_finish` 0 times and
    puts the same information in `visual_descriptors` instead. Reading it there
    is the model's own evidence, not an invention."""
    entry = _finish_entry(_obj(descriptors=descriptors))
    assert entry["frame_material"] == expected
    assert entry["source"] == "descriptor"


@pytest.mark.parametrize("descriptors", [
    ["glass coffee table"],          # the whole object, not its trim
    ["luxurious", "contemporary"],   # taste, no material at all
    ["quilted", "striped side panel", "branded trim"],  # a part, but no material
    ["walnut"],                      # a material, but no part named
])
def test_a_descriptor_that_does_not_name_a_part_never_supplies_a_finish(descriptors):
    """We paint only the trim meshes, so we may only act on evidence about
    trim. A whole-object phrase must not repaint a piece."""
    entry = _finish_entry(_obj(descriptors=descriptors))
    assert entry["frame_material"] == ""
    assert entry["source"] == ""


def test_a_stated_frame_finish_always_beats_a_descriptor():
    entry = _finish_entry(_obj(frame_finish="brushed brass",
                               descriptors=["wooden frame"]))
    assert entry["frame_material"] == "metal_brass"
    assert entry["source"] == "stated"


def test_a_descriptor_derived_finish_is_never_counted_as_a_stated_one():
    """Provenance matters for the fidelity report: `frame_finish` survival is
    about what the client stated, and an inferred finish must not inflate it."""
    entry = _finish_entry(_obj(descriptors=["wooden frame"]))
    assert entry["source"] == "descriptor"
    assert ObjectVisual(descriptors=["wooden frame"]).frame_finish == "", \
        "the scene object's stated field stays empty"


# -- descriptors: surface quality is resolved but NOT applied ---------------

@pytest.mark.parametrize("word,expected", [
    ("matte", 0.95), ("flat", 0.95), ("satin", 0.55), ("glossy", 0.12), ("polished", 0.12),
])
def test_a_surface_quality_descriptor_is_resolved_into_the_manifest(word, expected):
    assert _finish_entry(_obj(descriptors=["contemporary", word]))["roughness"] == expected


def test_no_blender_script_reads_the_roughness_key_so_it_is_not_claimed_as_rendered():
    """`finish.roughness` is carried, not applied. If a future phase wires it,
    this test fails and the contract text must be updated with it - which is
    the point: the claim and the executor must not drift apart."""
    scripts = Path(__file__).resolve().parents[1] / "blender" / "scripts"
    readers = [f.name for f in scripts.glob("*.py")
               if '["roughness"]' in f.read_text(encoding="utf-8")
               or "finish.get(\"roughness\")" in f.read_text(encoding="utf-8")]
    assert readers == [], f"roughness is now applied by {readers}; update the contract"


@pytest.mark.parametrize("word", ["luxurious", "premium", "elegant", "rounded", "minimal"])
def test_a_taste_descriptor_never_becomes_a_material_change(word):
    assert _finish_entry(_obj(descriptors=[word]))["roughness"] is None
    assert word not in _FINISH_ROUGHNESS


# -- isolation: nothing shared is mutated -----------------------------------

def test_resolving_one_object_never_mutates_the_shared_registry_material():
    """Blender shares material datablocks by name; the Python side must not
    edit the registry record either."""
    before = get_material_registry().get("veneer_walnut").model_dump()
    a = _finish_entry(_obj("x", object_id="a", frame_finish="dark walnut"))
    b = _finish_entry(_obj("x", object_id="b", frame_finish="brushed brass"))
    after = get_material_registry().get("veneer_walnut").model_dump()

    assert a["frame_material"] == "veneer_walnut"
    assert b["frame_material"] == "metal_brass", "one finish must not leak into another object"
    assert before == after, "the shared registry record must be untouched"


def test_two_objects_in_one_scene_keep_their_own_finishes(tmp_path):
    a = _obj(object_id="obj_a", frame_finish="dark walnut")
    b = _obj(object_id="obj_b", position=(4.0, 0.0, 3.0), frame_finish="brushed brass")
    manifest = build_manifest(_scene([a, b]), project_id="p_p14", project_root=tmp_path,
                              preview=False)

    finishes = {o["id"]: o["finish"]["frame_material"] for o in manifest["objects"]}
    assert finishes == {"obj_a": "veneer_walnut", "obj_b": "metal_brass"}


def test_the_frame_finish_never_replaces_the_upholstery_channel(tmp_path):
    """`material_overrides["primary"]` is what `_apply_upholstery` paints onto
    the body. The frame finish travels in its own key and must not displace
    it, or a linen sofa would come back as a walnut sofa."""
    obj = _obj(material="linen", upholstery="linen", frame_finish="dark walnut")
    obj.material_overrides = {"primary": "fabric_linen"}
    manifest = build_manifest(_scene([obj]), project_id="p_p14", project_root=tmp_path,
                              preview=False)
    row = manifest["objects"][0]

    assert row["material_overrides"] == {"primary": "fabric_linen"}
    assert row["finish"]["frame_material"] == "veneer_walnut"
    assert row["finish"]["frame_material"] != row["material_overrides"]["primary"]


# -- compatibility with what already shipped --------------------------------

def test_an_object_with_no_visual_block_adds_no_finish_to_the_manifest(tmp_path):
    """Every pre-P13 scene still produces a byte-identical manifest."""
    plain = SceneObject(object_id="p1", semantic_type="sofa", room_id="r1",
                        position=(1.0, 0.0, 1.0), dimensions=(2.0, 0.8, 0.9))
    manifest = build_manifest(_scene([plain]), project_id="p_p14", project_root=tmp_path,
                              preview=False)

    assert "finish" not in manifest["objects"][0]
    assert "visual" not in manifest["objects"][0]


def test_the_finish_entry_is_deterministic():
    """Same object, same answer - no uuid, no dict ordering, no clock."""
    entries = [_finish_entry(_obj("x", frame_finish="dark walnut", descriptors=["matte"]))
               for _ in range(20)]
    assert all(e == entries[0] for e in entries)


def test_material_slots_reads_real_geometry_not_declarations():
    """A file that declares materials nothing references reports none of them,
    which is why a declared-but-unused slot cannot fake a frame region."""
    doc = gltf.GltfDocument(
        json={"materials": [{"name": "unused"}, {"name": "body"}],
              "meshes": [{"primitives": [{"attributes": {}, "material": 1}]}]},
        buffers=[])
    assert gltf.material_slots(doc) == ["body"]


def test_the_contract_separates_always_from_conditional_from_metadata():
    always = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
              if v.executor is ExecutorSupport.PRESERVED_AND_RENDERED}
    conditional = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
                   if v.executor is ExecutorSupport.CONDITIONALLY_RENDERED}
    metadata = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
                if v.executor is ExecutorSupport.PRESERVED_METADATA_ONLY}

    assert always == {"color_hex", "material", "upholstery"}
    assert conditional == {"frame_finish", "descriptors"}
    assert metadata == {"color_words", "pattern"}
    for name in conditional:
        assert VISUAL_ATTRIBUTE_CONTRACT[name].how, "a conditional tier must state its condition"

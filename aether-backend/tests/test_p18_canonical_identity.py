"""P18: one canonical element, N instances, one asset.

The production identity key kept the box centre, so three bar stools along a
counter were three identities and three Meshy purchases. Measured on the real
project: 90 credits for one stool. The key chosen here won a six-way ablation
(research/element-first/identity-ablation.json) with 0 false merges and 0 false
splits; the production key scored 2 and 10.

Three things are asserted, in order of how much they matter:
  1. a false merge cannot happen where the evidence says the pieces differ,
     or where there is no evidence at all;
  2. three identical stools become one definition, three instances, one asset;
  3. meshes bought under the old key are found and reused, never re-bought.
"""
from __future__ import annotations

from app.intelligence.schema import ObjectPlan, SceneElement, SceneReading
from app.intelligence.scene_reading import (canonical_key, distinct_shapes, element_inventory,
                                            mark_duplicates, merge_reading_into_plan,
                                            resolve_elements, shape_key)
from app.jobs.handlers.generate_elements import _glb_rel, storage_key


def _el(eid, room, stype, name="", material="", color="", dims=None, bbox=None,
        check="ok", approved=None, crop_px=(100, 100)) -> SceneElement:
    return SceneElement(element_id=eid, room_id=room, semantic_type=stype, name=name,
                        material=material, color=color, dimensions_m=dims,
                        bbox=bbox or (0.1, 0.1, 0.2, 0.2), check=check, approved=approved,
                        crop_px=crop_px)


def _three_stools(**kw) -> list[SceneElement]:
    """Three identical stools at three distinct positions along a counter."""
    return [_el(f"s{i}", "kitchen", "bar_stool", "black bar stool", "plastic", "#111111",
                bbox=(0.1 + 0.3 * i, 0.5, 0.2 + 0.3 * i, 0.8), **kw) for i in range(3)]


# ── section 24: the three-bar-stool golden test ─────────────────────────

def test_three_identical_stools_are_one_element_three_instances():
    reading = SceneReading(elements=_three_stools())
    definitions, instances = resolve_elements(reading)

    assert len(element_inventory(reading)) == 1
    assert element_inventory(reading)[0].read == 3          # detected instances = 3
    assert len(definitions) == 1                              # canonical elements = 1
    assert definitions[0].instance_count == 3                 # element instances = 3
    assert len(instances) == 3
    assert {i.element_id for i in instances} == {definitions[0].element_id}
    assert len({i.bbox for i in instances}) == 3              # three distinct positions kept


def test_three_stools_are_one_generation():
    """distinct_shapes is what generate_elements buys from: one group, one call."""
    groups = distinct_shapes(_three_stools())
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 3


def test_position_never_alters_canonical_identity():
    """The invariant in words: move a stool anywhere, same identity."""
    a = _el("a", "kitchen", "bar_stool", material="plastic", color="#111111", bbox=(0.0, 0.0, 0.1, 0.1))
    b = _el("b", "kitchen", "bar_stool", material="plastic", color="#111111", bbox=(0.9, 0.9, 1.0, 1.0))
    assert canonical_key(a) == canonical_key(b)
    assert shape_key(a) != shape_key(b), "the OLD key did split them - that was the bug"


def test_the_production_key_split_the_stools_and_the_new_key_does_not():
    """Regression pin on the exact defect: 3 purchases -> 1."""
    stools = _three_stools()
    assert len({shape_key(s) for s in stools}) == 3
    assert len({canonical_key(s) for s in stools}) == 1


def test_canonical_ids_are_deterministic_and_position_free():
    ids = [resolve_elements(SceneReading(elements=_three_stools()))[0][0].element_id
           for _ in range(10)]
    assert len(set(ids)) == 1
    assert ids[0].startswith("cel_")
    # the id is content-addressed from the key; the key has no coordinate in it
    assert "0." not in canonical_key(_three_stools()[0])


# ── section 25: the negative golden test - do not over-dedupe ───────────

def test_similar_chairs_with_different_upholstery_stay_separate():
    chairs = [
        _el("c1", "dining", "dining_chair", "dining chair", "linen", "#D8CFC0"),
        _el("c2", "dining", "dining_chair", "dining chair", "velvet", "#2E4A3F"),
        _el("c3", "dining", "dining_chair", "dining chair", "leather", "#5A3A2A"),
    ]
    definitions, _ = resolve_elements(SceneReading(elements=chairs))
    assert len(definitions) == 3


def test_same_material_different_dimensions_stay_separate():
    a = _el("a", "living_room", "sofa", material="fabric", color="#888888", dims=(1.6, 0.8, 0.9))
    b = _el("b", "living_room", "sofa", material="fabric", color="#888888", dims=(2.4, 0.8, 0.9))
    assert canonical_key(a) != canonical_key(b)


def test_two_beds_in_two_rooms_stay_separate():
    """The documented false merge that made room part of the old key."""
    beds = [_el("b1", "master_bedroom", "bed", material="fabric and wood", color="#F8F9FA"),
            _el("b2", "second_bedroom", "bed", material="fabric and wood", color="#F8F9FA")]
    assert len(resolve_elements(SceneReading(elements=beds))[0]) == 2


def test_no_evidence_means_no_merge():
    """Two same-type pieces in one room with nothing known about either are
    NOT known to be the same. Uncertain identity stays separate."""
    tables = [_el("n1", "living_room", "side_table"), _el("n2", "living_room", "side_table")]
    definitions, _ = resolve_elements(SceneReading(elements=tables))
    assert len(definitions) == 2
    assert all(d.identity_method == "unresolved" for d in definitions)


def test_a_chair_and_an_armchair_never_merge():
    a = _el("a", "living_room", "chair", material="oak", color="#B08D57")
    b = _el("b", "living_room", "armchair", material="oak", color="#B08D57")
    assert canonical_key(a) != canonical_key(b)


def test_dimensions_inside_one_bucket_merge_and_a_boundary_only_ever_splits():
    """Dimensions are bucketed to 10 cm, so 42 cm and 44 cm stools are one
    stool read twice. A pair straddling a bucket boundary (44 cm and 46 cm)
    SPLITS - that is a known limitation and it is the safe failure: a split
    buys a second mesh, a merge would put the wrong piece in the room. The
    first version of this test asserted the boundary pair merged, and failed;
    it is kept as the record of that."""
    a = _el("a", "kitchen", "bar_stool", material="plastic", dims=(0.42, 0.75, 0.42))
    b = _el("b", "kitchen", "bar_stool", material="plastic", dims=(0.44, 0.75, 0.44))
    assert canonical_key(a) == canonical_key(b)

    c = _el("c", "kitchen", "bar_stool", material="plastic", dims=(0.46, 0.75, 0.46))
    assert canonical_key(b) != canonical_key(c), "boundary straddle: splits, never merges"


# ── section 13: asset cache - already-bought meshes are found ───────────

def test_a_mesh_bought_under_the_old_key_is_reused_not_rebought(tmp_path):
    stools = _three_stools()
    legacy = _glb_rel(shape_key(stools[1]))               # bought under the centre key
    (tmp_path / legacy).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / legacy).write_bytes(b"glb")

    key = canonical_key(stools[0])
    disk = storage_key(lambda rel: (tmp_path / rel).is_file(), key, stools)

    assert disk == shape_key(stools[1]), "the legacy file must be adopted"
    assert (tmp_path / _glb_rel(disk)).is_file()


def test_a_group_with_no_mesh_anywhere_generates_under_the_canonical_key(tmp_path):
    stools = _three_stools()
    key = canonical_key(stools[0])
    assert storage_key(lambda rel: (tmp_path / rel).is_file(), key, stools) == key


def test_the_canonical_file_wins_over_a_legacy_one_once_it_exists(tmp_path):
    stools = _three_stools()
    key = canonical_key(stools[0])
    for rel in (_glb_rel(key), _glb_rel(shape_key(stools[0]))):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"glb")
    assert storage_key(lambda rel: (tmp_path / rel).is_file(), key, stools) == key


def test_the_cache_key_is_independent_of_position():
    """Moving every instance must not change what the cache looks up."""
    moved = [_el(f"m{i}", "kitchen", "bar_stool", material="plastic", color="#111111",
                 bbox=(0.05 * i, 0.9, 0.05 * i + 0.05, 1.0)) for i in range(3)]
    assert canonical_key(moved[0]) == canonical_key(_three_stools()[0])


# ── section 26: the 11-item loss stays visible ──────────────────────────

def test_identity_does_not_hide_pieces_the_checks_removed():
    """Removed rows are not evidence of a piece, so they form no definition -
    but the inventory still says they were read."""
    stools = _three_stools()
    stools[2].check = "mismatch"
    reading = SceneReading(elements=stools)

    inventory = element_inventory(reading)[0]
    definitions, instances = resolve_elements(reading)

    assert inventory.read == 3 and inventory.usable == 2
    assert inventory.lost_to == {"mismatch": 1}
    assert definitions[0].instance_count == 2
    assert len(instances) == 2


def test_the_documented_edge_box_failure_is_still_reported():
    edge = [_el(f"e{i}", "kitchen", "bar_stool", material="plastic", color="#111111",
                bbox=(0.1 + 0.2 * i, 0.5, 0.9, 0.8)) for i in range(3)]
    reading = SceneReading(elements=edge)
    mark_duplicates(reading)
    inventory = element_inventory(reading)[0]
    assert (inventory.read, inventory.usable) == (3, 1)
    assert resolve_elements(reading)[0][0].instance_count == 1


# ── section 27: nothing existing changed ────────────────────────────────

def test_identity_does_not_change_what_reaches_the_plan():
    """One definition, three instances - and still three plan items, because
    the plan is placement and each instance is placed."""
    reading = SceneReading(elements=_three_stools(approved=True))
    plan, _ = merge_reading_into_plan(ObjectPlan(rooms=["kitchen"], items=[]), reading)
    assert sum(i.count for i in plan.items if i.semantic_type == "bar_stool") == 3


def test_a_reading_without_definitions_still_loads_and_resolves():
    old = SceneReading.model_validate({
        "elements": [{"room_id": "kitchen", "semantic_type": "bar_stool",
                      "material": "plastic", "bbox": [0.1, 0.5, 0.2, 0.8], "check": "ok"}]})
    assert old.definitions == [] and old.instances == []
    assert len(resolve_elements(old)[0]) == 1


def test_only_trustworthy_rows_become_instances():
    stools = _three_stools()
    stools[0].approved = False
    definitions, instances = resolve_elements(SceneReading(elements=stools))
    assert definitions[0].instance_count == 2
    assert {i.source_element_id for i in instances} == {"s1", "s2"}

"""Deterministic checks for scene_serialization.py: lossless round trip and
byte-identical determinism. No GPU, no models.
"""
from __future__ import annotations

from app.spatial.scene_graph import build_demonstration_scene
from app.spatial.scene_serialization import (
    from_canonical_dict, from_canonical_json, to_canonical_dict, to_canonical_json)


def test_round_trip_preserves_scene_and_relations():
    spatial = build_demonstration_scene()
    restored = from_canonical_dict(to_canonical_dict(spatial))
    assert restored.scene.scene_id == spatial.scene.scene_id
    assert {o.object_id for o in restored.scene.objects} == {o.object_id for o in spatial.scene.objects}
    assert {r.relation_id for r in restored.relations} == {r.relation_id for r in spatial.relations}


def test_round_trip_preserves_every_relation_field():
    spatial = build_demonstration_scene()
    restored = from_canonical_dict(to_canonical_dict(spatial))
    by_id_before = {r.relation_id: r for r in spatial.relations}
    by_id_after = {r.relation_id: r for r in restored.relations}
    assert by_id_before.keys() == by_id_after.keys()
    for rid, before in by_id_before.items():
        after = by_id_after[rid]
        assert before == after   # dataclass equality: every field, exactly


def test_json_round_trip_is_byte_identical_on_second_pass():
    spatial = build_demonstration_scene()
    text = to_canonical_json(spatial)
    restored = from_canonical_json(text)
    assert to_canonical_json(restored) == text


def test_serialization_is_deterministic_across_20_builds():
    texts = {to_canonical_json(build_demonstration_scene()) for _ in range(20)}
    assert len(texts) == 1


def test_relations_serialize_pre_sorted_by_relation_id():
    spatial = build_demonstration_scene()
    d = to_canonical_dict(spatial)
    ids = [r["relation_id"] for r in d["relations"]]
    assert ids == sorted(ids)

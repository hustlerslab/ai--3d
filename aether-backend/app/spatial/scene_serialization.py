"""P7 canonical serialization contract for `SpatialScene`.

Lossless: every field on every `GeometricRelation` round-trips exactly
(enums as their `.value` string, tuples as JSON arrays restored back to
tuples). Deterministic: `json.dumps(..., sort_keys=True)` plus relations
sorted by `relation_id` BEFORE serialization (never relying on dict/list
insertion order alone, and never on Python's set iteration order, which is
salted per-process) - the same failure class P4's random-`object_id` bug and
P6's dict-key-ordering finding both warned against.

`Scene` itself already serializes losslessly via pydantic
(`model_dump(mode="json")`); this module does not reimplement that, it wraps
it and adds the relation layer + a single top-level sort so the WHOLE
`SpatialScene` round-trips, not just the geometry half.
"""
from __future__ import annotations

import json


from app.scene.schema import Scene
from app.spatial.relation_model import (
    GeometricRelation, RelationKind, RelationStatus)
from app.spatial.scene_model import SpatialScene

SCHEMA_VERSION = "p7.1"


def _relation_to_dict(rel: GeometricRelation) -> dict:
    return {
        "relation_id": rel.relation_id, "subject_id": rel.subject_id,
        "predicate": rel.predicate, "object_id": rel.object_id,
        "kind": rel.kind.value, "status": rel.status.value,
        "confidence": rel.confidence, "source": rel.source, "frame": rel.frame,
        "note": rel.note, "provenance": rel.provenance,
        "verified_at_position": (list(rel.verified_at_position)
                                 if rel.verified_at_position is not None else None),
        "evidence_refs": list(rel.evidence_refs),
    }


def _relation_from_dict(d: dict) -> GeometricRelation:
    pos = d.get("verified_at_position")
    return GeometricRelation(
        relation_id=d["relation_id"], subject_id=d["subject_id"], predicate=d["predicate"],
        object_id=d["object_id"], kind=RelationKind(d["kind"]), status=RelationStatus(d["status"]),
        confidence=d["confidence"], source=d["source"], frame=d.get("frame", "floor_plan"),
        note=d.get("note", ""), provenance=d.get("provenance", ""),
        verified_at_position=tuple(pos) if pos is not None else None,
        evidence_refs=tuple(d.get("evidence_refs", ())))


def to_canonical_dict(spatial: SpatialScene) -> dict:
    """A plain dict, ready for `json.dumps(..., sort_keys=True)`. Relations
    are pre-sorted by `relation_id` (a content hash - see relation_model.py)
    so the ORDER in the output is itself a function of content, not of
    insertion order, matching the whole-list determinism this program has
    required since P4."""
    relations = sorted((_relation_to_dict(r) for r in spatial.relations),
                       key=lambda d: d["relation_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "scene": spatial.scene.model_dump(mode="json"),
        "relations": relations,
    }


def to_canonical_json(spatial: SpatialScene) -> str:
    return json.dumps(to_canonical_dict(spatial), sort_keys=True, indent=2)


def from_canonical_dict(d: dict) -> SpatialScene:
    scene = Scene.model_validate(d["scene"])
    relations = tuple(_relation_from_dict(r) for r in d.get("relations", []))
    return SpatialScene(scene=scene, relations=relations)


def from_canonical_json(text: str) -> SpatialScene:
    return from_canonical_dict(json.loads(text))


__all__ = ["SCHEMA_VERSION", "to_canonical_dict", "to_canonical_json",
           "from_canonical_dict", "from_canonical_json"]

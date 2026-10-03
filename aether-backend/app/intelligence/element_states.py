"""P1-FRONTEND-001: what the review screen shows about certainty, decided
here - once - so the screen displays it and never works it out.

Three things:

- `element_states`: one of four states for every reading row
    rejected    a check removed it, or the person said no
    unresolved  kept as its own piece for lack of evidence to match it
    validated   passed the checks and the person said yes
    detected    read from the picture, passed the checks, awaiting the person
- `inventory_counts`: the numbers the screen prints, counted from the same
  definitions and instances it lists. The screen used to recount them
  (`groups.filter(...).length`), which is a second copy of the rule.
- `assumptions`: every value that was estimated rather than given or read,
  in plain words, with where the person changes it.
"""
from __future__ import annotations

from typing import Any, Optional

from .schema import ElementDefinition, ElementInstance, SceneReading

STATES = ("detected", "validated", "rejected", "unresolved")


def _human(semantic_type: str) -> str:
    return semantic_type.replace("_", " ").strip().capitalize() or "Piece"


def element_states(reading: SceneReading, definitions: list[ElementDefinition],
                   instances: list[ElementInstance]) -> dict[str, str]:
    unresolved_defs = {d.element_id for d in definitions if d.identity_method == "unresolved"}
    claimed = {i.source_element_id: i.element_id for i in instances}
    out: dict[str, str] = {}
    for e in reading.elements:
        if e.approved is False or e.element_id not in claimed:
            out[e.element_id] = "rejected"
        elif claimed[e.element_id] in unresolved_defs:
            out[e.element_id] = "unresolved"
        elif e.approved is True:
            out[e.element_id] = "validated"
        else:
            out[e.element_id] = "detected"
    return out


def inventory_counts(reading: SceneReading, definitions: list[ElementDefinition],
                     instances: list[ElementInstance], states: dict[str, str]) -> dict[str, Any]:
    by_state = {s: 0 for s in STATES}
    for s in states.values():
        by_state[s] += 1
    return {
        "detected_rows": len(reading.elements),
        "canonical": len(definitions),
        "instances": len(instances),
        "assets": sum(1 for d in definitions if d.canonical_asset_id),
        "yours": sum(1 for d in definitions if d.client_owned),
        "by_state": by_state,
    }


def assumptions(reading: SceneReading, states: dict[str, str],
                definitions: list[ElementDefinition], analysis: Optional[dict] = None) -> list[dict[str, str]]:
    """Every estimate the design rests on. `ref` lets the screen place a marker
    next to the value; it is an anchor, never text for the page."""
    out: list[dict[str, str]] = []
    rooms = {r.get("room_id"): r for r in (analysis or {}).get("rooms", [])}

    def room_name(room_id: str) -> str:
        return (rooms.get(room_id) or {}).get("name") or room_id.replace("_", " ")

    for room_id, r in rooms.items():
        if r.get("estimated", True):
            out.append({
                "kind": "room_size", "ref": room_id,
                "statement": f"{room_name(room_id)}: {r.get('width_m')} × {r.get('length_m')} m is an estimate - "
                             "no measurements were given for it.",
                "change": "Enter the real size of this room.",
            })

    for e in reading.elements:
        if states.get(e.element_id) == "rejected":
            continue
        label = e.name or _human(e.semantic_type)
        if e.position_source == "derived":
            out.append({
                "kind": "position", "ref": e.element_id,
                "statement": f"Where the {label} stands in the {room_name(e.room_id)} was estimated from the picture, "
                             "not measured.",
                "change": "Move it in the 3D view.",
            })
        elif e.position_source == "":
            out.append({
                "kind": "position", "ref": e.element_id,
                "statement": f"The picture gave no position for the {label}; the layout chose one.",
                "change": "Move it in the 3D view.",
            })

    # An unresolved definition keeps its own identity (instance_count 1). The
    # guess is when several of the same kind in one room were each kept
    # apart: they may be one repeated piece, and nobody could tell.
    groups: dict[tuple[str, str], list[ElementDefinition]] = {}
    for d in definitions:
        if d.identity_method == "unresolved":
            groups.setdefault((d.room_id, d.semantic_type), []).append(d)
    for (room_id, semantic_type), defs in sorted(groups.items()):
        if len(defs) < 2:
            continue
        out.append({
            "kind": "identity", "ref": defs[0].element_id,
            "statement": f"{len(defs)} {_human(semantic_type).lower()} pieces in the {room_name(room_id)} were kept "
                         "separate: there was not enough to tell whether they are the same piece.",
            "change": "Review them below.",
        })
    return out


__all__ = ["STATES", "assumptions", "element_states", "inventory_counts"]

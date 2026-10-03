"""P1-SPATIAL-002: turn a solver warning into a decision a person can make.

The engine says `living_room.sofa.1: no valid position for grey sofa in
Living Room (priority 2)`. A person should read "The grey sofa and the
armchair won't both fit in the living room with a clear way to the door" and
be offered choices. This module does that translation deterministically -
from the compiler's own format strings, no model - and guarantees that no
internal key, id, code or priority number reaches the words a person reads.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NO_POSITION = re.compile(r"^(?P<key>[^:]+): no valid position (?:for (?P<name>.+) )?in (?P<room>.+) "
                          r"\(priority (?P<priority>\d+)\)$")
_NO_SURFACE = re.compile(r"^(?P<key>[^:]+): no surface in (?P<room>.+) to rest (?:(?P<name>.+) )?on; skipped$")

#: What a person should never see in a message (tested).
FORBIDDEN = re.compile(r"(obj_|cel_|el_|rev_|scene_|job_|priority|\b[a-z]+_[a-z_]+\b|\b\w+\.\w+\.\d+\b|C-\d+|#\d)")


@dataclass
class Option:
    id: str
    label: str


@dataclass
class TradeOff:
    kind: str                      # "doesnt_fit" | "nothing_to_rest_on"
    room: str
    pieces: list[str]
    statement: str
    options: list[Option]
    #: Plan keys, for the API to act on - never shown to a person.
    keys: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"kind": self.kind, "room": self.room, "pieces": self.pieces, "statement": self.statement,
                "options": [{"id": o.id, "label": o.label} for o in self.options], "keys": self.keys}


def _human(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def _the(piece: str) -> str:
    return piece if piece.lower().startswith(("the ", "a ", "an ")) else f"the {piece}"


def _join(items: list[str]) -> str:
    items = [_the(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _name_from_key(key: str) -> str:
    """Fallback when a warning predates named messages: `room.sofa.1` -> "sofa"."""
    parts = key.split(".")
    return _human(parts[1] if len(parts) >= 2 else parts[0])


def explain(warnings: list[str]) -> list[TradeOff]:
    """Plain-language trade-offs from the compiler's warnings, one per room
    and kind, highest-priority pieces first. Other warnings are ignored: they
    are not spatial trade-offs a person can resolve by choosing."""
    no_fit: dict[str, list[tuple[int, str, str]]] = {}
    no_surface: dict[str, list[tuple[str, str]]] = {}
    for w in warnings:
        m = _NO_POSITION.match(w.strip())
        if m:
            name = _human(m.group("name") or _name_from_key(m.group("key")))
            no_fit.setdefault(_human(m.group("room")), []).append((int(m.group("priority")), name, m.group("key")))
            continue
        m = _NO_SURFACE.match(w.strip())
        if m:
            name = _human(m.group("name") or _name_from_key(m.group("key")))
            no_surface.setdefault(_human(m.group("room")), []).append((name, m.group("key")))

    out: list[TradeOff] = []
    for room, rows in sorted(no_fit.items()):
        rows.sort()
        pieces = list(dict.fromkeys(n for _, n, _ in rows))
        room_l = room.lower()
        verb = "doesn't" if len(pieces) == 1 else "don't"
        statement = (f"{_join(pieces).capitalize()} {verb} fit in the {room_l} alongside everything else "
                     f"while keeping a clear walkway and space in front of the doors.")
        lead = pieces[0]
        options = [Option("leave_out", f"Leave {_the(lead)} out of the {room_l}"),
                   Option("smaller", f"Use a smaller {lead} that fits")]
        options.append(Option("make_room", f"Keep {_the(lead)} and drop a less important piece instead"))
        out.append(TradeOff("doesnt_fit", room, pieces, statement, options, [k for *_, k in rows]))
    for room, rows in sorted(no_surface.items()):
        pieces = list(dict.fromkeys(n for n, _ in rows))
        room_l = room.lower()
        statement = (f"{_join(pieces).capitalize()} {'needs' if len(pieces) == 1 else 'need'} a table or shelf "
                     f"to stand on in the {room_l}, and there isn't one free.")
        lead = pieces[0]
        options = [Option("add_surface", f"Add a side table in the {room_l} for {_the(lead)}"),
                   Option("floor", f"Stand {_the(lead)} on the floor instead"),
                   Option("leave_out", f"Leave {_the(lead)} out")]
        out.append(TradeOff("nothing_to_rest_on", room, pieces, statement, options, [k for _, k in rows]))
    return out


def explain_violations(scene) -> list[TradeOff]:
    """Trade-offs for what is wrong in the COMMITTED scene right now - today a
    piece standing in front of a door (§31 row 7). Names come from the scene;
    no id reaches the words."""
    from ..spatial.validation import validate_scene

    by_room: dict[str, list[tuple[str, str]]] = {}
    for v in validate_scene(scene):
        if v.severity != "hard" or v.code != "BLOCKS_DOOR" or not v.object_id:
            continue
        o = next((x for x in scene.objects if x.object_id == v.object_id), None)
        if o is None:
            continue
        room = scene.room(o.room_id)
        by_room.setdefault(_human(room.name if room else "room"), []).append(
            (_human(o.name or o.semantic_type), o.object_id))
    out = []
    for room, rows in sorted(by_room.items()):
        pieces = list(dict.fromkeys(n for n, _ in rows))
        room_l = room.lower()
        verb = "is" if len(pieces) == 1 else "are"
        statement = f"{_join(pieces).capitalize()} {verb} in the way of a door in the {room_l}."
        lead = pieces[0]
        out.append(TradeOff("blocks_door", room, pieces, statement,
                            [Option("move", f"Move {_the(lead)} clear of the door"),
                             Option("leave_out", f"Leave {_the(lead)} out of the {room_l}"),
                             Option("smaller", f"Use a smaller {lead}")],
                            [oid for _, oid in rows]))
    return out


__all__ = ["TradeOff", "Option", "explain", "explain_violations", "FORBIDDEN"]

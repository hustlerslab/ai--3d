"""Deterministic floor-plan layout from analysed rooms.

Hub-and-spoke: the living room (or the largest room) is the hub at the
origin. Bedrooms stack down the east side, kitchen/dining/balcony along the
north, study/entry/bathroom/other down the west. A room that no longer
overlaps the hub enough for a door is chained to the previous room in its
stack instead. Coordinates follow the scene convention: X right, Z down
(toward the viewer), metres.

Walls are derived from room edges: every edge is split at the endpoints of
other rooms' edges on the same line, then identical segments are merged so
a shared wall exists once. Segments bordering one room are exterior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..intelligence.schema import RoomAnalysis
from ..scene.schema import Opening, OpeningType, Vec2, Wall

EAST = {"master_bedroom", "bedroom", "kids_bedroom"}
NORTH = {"kitchen", "dining_room", "balcony"}
WEST = {"study", "entry", "bathroom", "other"}
MIN_DOOR_OVERLAP = 1.2
DOOR_WIDTH, DOOR_HEIGHT = 0.9, 2.1
WINDOW_HEIGHT, SILL = 1.3, 0.9


@dataclass
class PlacedRoom:
    room_id: str
    name: str
    type: str
    x0: float
    z0: float
    x1: float
    z1: float
    height: float = 3.0
    parent: Optional[str] = None      # the room its door connects to (None for hub)

    @property
    def boundary(self) -> list[Vec2]:
        return [(self.x0, self.z0), (self.x1, self.z0), (self.x1, self.z1), (self.x0, self.z1)]

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def depth(self) -> float:
        return self.z1 - self.z0


@dataclass
class WallSeg:
    axis: str            # "x": wall runs along X at fixed z · "z": runs along Z at fixed x
    c: float             # the fixed coordinate
    p0: float            # start along the running axis
    p1: float            # end along the running axis
    rooms: set[str] = field(default_factory=set)
    wall_id: str = ""

    @property
    def length(self) -> float:
        return self.p1 - self.p0

    @property
    def start(self) -> Vec2:
        return (self.p0, self.c) if self.axis == "x" else (self.c, self.p0)

    @property
    def end(self) -> Vec2:
        return (self.p1, self.c) if self.axis == "x" else (self.c, self.p1)

    @property
    def exterior(self) -> bool:
        return len(self.rooms) == 1


def _r(v: float) -> float:
    return round(v, 4)


# ── rooms ────────────────────────────────────────────────────────────────


def layout_rooms(rooms: list[RoomAnalysis]) -> list[PlacedRoom]:
    if not rooms:
        return []
    hub_src = next((r for r in rooms if r.type == "living_room"), None) or max(rooms, key=lambda r: r.area_m2)
    hub = PlacedRoom(hub_src.room_id, hub_src.name, hub_src.type, 0.0, 0.0, hub_src.width_m, hub_src.length_m, hub_src.height_m)
    placed = [hub]
    W, L = hub.width, hub.depth

    east = [r for r in rooms if r is not hub_src and r.type in EAST]
    north = [r for r in rooms if r is not hub_src and r.type in NORTH]
    west = [r for r in rooms if r is not hub_src and r.type in WEST]
    rest = [r for r in rooms if r is not hub_src and r not in east and r not in north and r not in west]
    # bedrooms first on the east so the master gets the hub wall
    east.sort(key=lambda r: {"master_bedroom": 0, "bedroom": 1, "kids_bedroom": 2}.get(r.type, 3))
    west += rest

    def stack(side_rooms: list[RoomAnalysis], side: str) -> None:
        cursor = 0.0
        prev: Optional[PlacedRoom] = None
        for r in side_rooms:
            if side == "east":
                pr = PlacedRoom(r.room_id, r.name, r.type, W, cursor, W + r.width_m, cursor + r.length_m, r.height_m)
                overlap = min(pr.z1, L) - max(pr.z0, 0.0)
                cursor += r.length_m
            elif side == "west":
                pr = PlacedRoom(r.room_id, r.name, r.type, -r.width_m, cursor, 0.0, cursor + r.length_m, r.height_m)
                overlap = min(pr.z1, L) - max(pr.z0, 0.0)
                cursor += r.length_m
            else:  # north
                pr = PlacedRoom(r.room_id, r.name, r.type, cursor, -r.length_m, cursor + r.width_m, 0.0, r.height_m)
                overlap = min(pr.x1, W) - max(pr.x0, 0.0)
                cursor += r.width_m
            pr.parent = hub.room_id if overlap >= MIN_DOOR_OVERLAP or prev is None else prev.room_id
            placed.append(pr)
            prev = pr

    stack(east, "east")
    stack(north, "north")
    stack(west, "west")
    return placed


# ── walls ────────────────────────────────────────────────────────────────


def _edges(room: PlacedRoom) -> list[tuple[str, float, float, float]]:
    return [
        ("x", room.z0, room.x0, room.x1),  # north edge
        ("x", room.z1, room.x0, room.x1),  # south edge
        ("z", room.x0, room.z0, room.z1),  # west edge
        ("z", room.x1, room.z0, room.z1),  # east edge
    ]


def wall_segments(placed: list[PlacedRoom]) -> list[WallSeg]:
    all_edges = [(room.room_id, *e) for room in placed for e in _edges(room)]
    segs: dict[tuple, WallSeg] = {}
    for room_id, axis, c, p0, p1 in all_edges:
        cuts = {p0, p1}
        for other_id, oaxis, oc, op0, op1 in all_edges:
            if other_id == room_id or oaxis != axis or abs(oc - c) > 1e-6:
                continue
            for p in (op0, op1):
                if p0 < p < p1:
                    cuts.add(p)
        pts = sorted(cuts)
        for a, b in zip(pts, pts[1:]):
            key = (axis, _r(c), _r(a), _r(b))
            seg = segs.get(key)
            if seg is None:
                seg = WallSeg(axis, _r(c), _r(a), _r(b))
                segs[key] = seg
            seg.rooms.add(room_id)
    ordered = sorted(segs.values(), key=lambda s: (s.axis, s.c, s.p0))
    for i, seg in enumerate(ordered, 1):
        seg.wall_id = f"wall_{i:02d}"
    return ordered


def build_walls_and_openings(
    placed: list[PlacedRoom],
    reserved: Optional[dict[str, list[tuple[float, float]]]] = None,
) -> tuple[list[Wall], list[Opening], list[str]]:
    """Walls + doors (child → parent), an entry door, and one window per room.

    `reserved` is wall_id -> spans (metres from the wall's start) that the
    approved picture has already spoken for, so an opening is not cut where a
    piece of furniture was seen. Windows go on the longest exterior wall and
    land near its middle, which is exactly where a television hangs: measured
    on proj_a25a006c88, a 1.8 m window was cut into the middle of the 5.8 m
    wall the client's 1.8 m television was read against, leaving 1.85 m clear
    at either end - too little for the TV once its margins count - so the set
    moved to another wall and faced the wrong way. The window is invented; the
    television was seen. The seen thing wins.
    """
    warnings: list[str] = []
    segs = wall_segments(placed)
    by_id = {p.room_id: p for p in placed}
    height = max((p.height for p in placed), default=3.0)
    walls = [Wall(wall_id=s.wall_id, start=s.start, end=s.end, height=height) for s in segs]
    openings: list[Opening] = []
    # Spans already spoken for. Seeded with what the picture claimed, so the
    # same `free_span` search that keeps two openings apart also keeps an
    # opening off the furniture.
    used: dict[str, list[tuple[float, float]]] = {k: list(v) for k, v in (reserved or {}).items()}

    def free_span(seg: WallSeg, width: float) -> Optional[float]:
        """Centre position (from wall start) for an opening of `width` that
        avoids existing openings on the same wall; None if it doesn't fit."""
        ranges = sorted(used.get(seg.wall_id, []))
        cursor = 0.15
        for a, b in ranges + [(seg.length - 0.15, seg.length)]:
            if a - cursor >= width + 0.1:
                return cursor + (a - cursor) / 2
            cursor = max(cursor, b + 0.1)
        return None

    def add_opening(seg: WallSeg, kind: OpeningType, width: float, height_m: float, sill: float, label: str) -> bool:
        centre = free_span(seg, width)
        if centre is None:
            return False
        openings.append(
            Opening(
                opening_id=f"open_{label}",
                type=kind,
                wall_id=seg.wall_id,
                position=round(centre, 3),
                width=width,
                height=height_m,
                sill_height=sill,
            )
        )
        used.setdefault(seg.wall_id, []).append((centre - width / 2, centre + width / 2))
        return True

    # doors: each non-hub room → its parent
    for room in placed:
        if room.parent is None:
            continue
        shared = [s for s in segs if room.room_id in s.rooms and room.parent in s.rooms and s.length >= DOOR_WIDTH + 0.3]
        if not shared:
            warnings.append(f"{room.name}: no shared wall long enough for a door to {by_id[room.parent].name}")
            continue
        seg = max(shared, key=lambda s: s.length)
        add_opening(seg, OpeningType.DOOR, DOOR_WIDTH, DOOR_HEIGHT, 0.0, f"door_{room.room_id}")

    # entry door: on the entry room's exterior wall, else the hub's south wall
    hub = next(p for p in placed if p.parent is None)
    entry = next((p for p in placed if p.type == "entry"), None)
    entry_room = entry or hub
    exterior = [s for s in segs if s.rooms == {entry_room.room_id} and s.length >= DOOR_WIDTH + 0.4]
    if exterior:
        # prefer the south wall (z max) of the hub, else the longest
        south = [s for s in exterior if s.axis == "x" and abs(s.c - entry_room.z1) < 1e-6]
        seg = max(south or exterior, key=lambda s: s.length)
        add_opening(seg, OpeningType.DOOR, DOOR_WIDTH + 0.1, DOOR_HEIGHT, 0.0, "entry")
    else:
        warnings.append("no exterior wall available for the entry door")

    # windows: the longest exterior wall of every room
    for room in placed:
        ext = [s for s in segs if s.rooms == {room.room_id} and s.length >= 1.5]
        placed_window = False
        for seg in sorted(ext, key=lambda s: s.length, reverse=True):
            width = min(1.8, round(seg.length * 0.5, 2))
            if add_opening(seg, OpeningType.WINDOW, width, WINDOW_HEIGHT, SILL, f"win_{room.room_id}"):
                placed_window = True
                break
        if not placed_window and room.type != "entry":
            warnings.append(f"{room.name}: no exterior wall for a window")

    return walls, openings, warnings

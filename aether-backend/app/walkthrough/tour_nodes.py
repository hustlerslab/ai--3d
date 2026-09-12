"""Panorama nodes for the 360° web tour (plan §8A).

One node per room at the guided tour's standing point, facing the tour's
first look target, plus further nodes as the room gets bigger. Links follow
the tour route and door connections, so hotspots always lead somewhere
reachable.

Each node is a full equirectangular panorama, so a single node already covers
every viewing angle from where it stands — extra nodes buy vantage *points*
(walk to the other end of the room), not extra angles. That is why the count
scales with floor area rather than with any fixed number of "views".
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

from ..scene.schema import Scene, Vec3
from ..spatial import geometry as geo
from . import service as walkthrough_service

# One extra vantage point per whole multiple of this area. At 18 m2 the
# behaviour is unchanged from when this was a single large/small flag: a 20 m2
# bedroom gets two nodes, a 26 m2 living room two, a 40 m2 open plan three.
LARGE_ROOM_M2 = 18.0
# Cycles renders a 2048x1024 equirect per node, so coverage is not free. Three
# standing points is enough to read any room this product designs; past that
# the tour is scrolling, not exploring.
MAX_NODES_PER_ROOM = 3


class TourNode(BaseModel):
    id: str
    room_id: str
    room_name: str
    label: str
    position: Vec3            # scene coords (x, y_up, z), eye height
    look_at: Vec3
    yaw: float                # scene rotation_y of the forward direction (radians)
    links: list[str] = []


def yaw_from(position: Vec3, look_at: Vec3) -> float:
    dx, dz = look_at[0] - position[0], look_at[2] - position[2]
    if abs(dx) < 1e-9 and abs(dz) < 1e-9:
        return 0.0
    return math.atan2(-dx, -dz)


def plan_nodes(scene: Scene) -> tuple[list[TourNode], list[str]]:
    tour = walkthrough_service.generate_tour(scene)
    nodes: list[TourNode] = []
    by_room: dict[str, list[str]] = {}
    for kf in tour.keyframes:
        room = scene.room(kf.room_id or "")
        if room is None or kf.label != room.name:
            continue  # only the "arrive" keyframes
        if any(n.room_id == room.room_id for n in nodes):
            continue
        nid = f"n{len(nodes) + 1:02d}"
        nodes.append(
            TourNode(
                id=nid, room_id=room.room_id, room_name=room.name, label=room.name,
                position=kf.position, look_at=kf.look_at, yaw=yaw_from(kf.position, kf.look_at),
            )
        )
        by_room.setdefault(room.room_id, []).append(nid)

        # Further vantage points as the room gets bigger, each placed as far as
        # possible from every point already chosen (farthest-point sampling), so
        # two cameras never end up side by side in an L-shaped room.
        area = geo.polygon_area(room.boundary)
        wanted = min(MAX_NODES_PER_ROOM, 1 + int(area // LARGE_ROOM_M2))
        taken = [(kf.position[0], kf.position[2])]
        while len(taken) < wanted:
            nxt = _far_point(scene, room, taken)
            if nxt is None:
                break
            taken.append(nxt)
            nid_n = f"n{len(nodes) + 1:02d}"
            pos = (nxt[0], walkthrough_service.EYE_HEIGHT, nxt[1])
            # Face what is in the room, not the camera we just left. The yaw
            # only sets where the panorama opens, but opening on the far wall
            # beats opening on the other tripod.
            look = walkthrough_service._room_look_target(scene, room, nxt)
            nodes.append(
                TourNode(
                    id=nid_n, room_id=room.room_id, room_name=room.name,
                    label=f"{room.name} · {len(taken)}",
                    position=pos, look_at=look, yaw=yaw_from(pos, look),
                )
            )
            by_room[room.room_id].append(nid_n)

    # links: consecutive along the route, both directions, plus door-connected rooms
    route = [n.id for n in nodes]
    for i, n in enumerate(nodes):
        if i > 0:
            n.links.append(nodes[i - 1].id)
        if i + 1 < len(nodes):
            n.links.append(nodes[i + 1].id)
    rooms = {r.room_id: r for r in scene.rooms}
    for a in nodes:
        for b in nodes:
            if a is b or b.id in a.links or a.room_id == b.room_id:
                continue
            if walkthrough_service._shared_door(scene, rooms[a.room_id], rooms[b.room_id]) is not None:
                a.links.append(b.id)
    return nodes, route


def _far_point(scene: Scene, room, existing: list[tuple[float, float]]) -> Optional[tuple[float, float]]:
    """The standable spot in `room` furthest from everything in `existing`.

    Maximises the distance to the NEAREST existing camera, not the average, so
    a third node cannot split the difference and land between the first two.
    Returns None when nothing is more than 2 m clear, which is the signal that
    the room is too small or too cluttered for another vantage point.
    """
    best, best_d = None, 2.0
    for p in walkthrough_service._grid_points(room, step=0.5):
        if not walkthrough_service.check_position(scene, p[0], p[1]).valid:
            continue
        d = min(geo.distance(p, q) for q in existing)
        if d > best_d:
            best, best_d = p, d
    return best

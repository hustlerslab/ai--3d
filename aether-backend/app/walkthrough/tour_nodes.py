"""Panorama nodes for the 360° web tour (plan §8A).

One node per room at the guided tour's standing point, facing the tour's
first look target, plus a second node in large rooms. Links follow the tour
route and door connections, so hotspots always lead somewhere reachable.
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

from ..scene.schema import Scene, Vec3
from ..spatial import geometry as geo
from . import service as walkthrough_service

LARGE_ROOM_M2 = 18.0


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
        # a second vantage point in large rooms, as far as possible from the first
        if geo.polygon_area(room.boundary) >= LARGE_ROOM_M2:
            second = _second_point(scene, room, (kf.position[0], kf.position[2]))
            if second is not None:
                nid2 = f"n{len(nodes) + 1:02d}"
                look = (kf.position[0], 1.2, kf.position[2])
                pos = (second[0], walkthrough_service.EYE_HEIGHT, second[1])
                nodes.append(
                    TourNode(
                        id=nid2, room_id=room.room_id, room_name=room.name, label=f"{room.name} · 2",
                        position=pos, look_at=look, yaw=yaw_from(pos, look),
                    )
                )
                by_room[room.room_id].append(nid2)

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


def _second_point(scene: Scene, room, first: tuple[float, float]) -> Optional[tuple[float, float]]:
    best, best_d = None, 2.0
    for p in walkthrough_service._grid_points(room, step=0.5):
        if not walkthrough_service.check_position(scene, p[0], p[1]).valid:
            continue
        d = geo.distance(p, first)
        if d > best_d:
            best, best_d = p, d
    return best

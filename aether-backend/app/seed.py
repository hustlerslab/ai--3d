"""Golden seed scene — GS-001 style two-room apartment (plan §47).

Built programmatically so it is always schema-valid. Created on first boot
when the store is empty, so the frontend has something to walk through
immediately.

Layout (plan view, meters — X right, Z down toward the viewer):

      (0,0) ─────────────── (6,0)
        │   Living Room       │
        │   6.0 × 4.5         │ (6,4.5) ── (10,4.5)? no — bedroom sits right:
        │                     │
      (0,4.5) ───────────── (6,4.5)

  Bedroom 4.0 × 3.5 attached to the right wall, sharing wall x=6
  from z=0.5 to z=4.0, door in that shared wall.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .scene.schema import (
    Calibration,
    Confidence,
    Opening,
    OpeningType,
    ObjectSource,
    Project,
    Room,
    Scene,
    SceneObject,
    Wall,
)
from .scene.store import SceneStore


def build_seed_scene(project_id: str) -> Scene:
    conf = Confidence(value=1.0, source="seed")

    living = Room(
        room_id="room_living",
        name="Living Room",
        type="living_room",
        boundary=[(0.0, 0.0), (6.0, 0.0), (6.0, 4.5), (0.0, 4.5)],
        ceiling_height=2.8,
        floor_material="wood_oak",
        confidence=conf,
    )
    bedroom = Room(
        room_id="room_bedroom",
        name="Bedroom",
        type="bedroom",
        boundary=[(6.0, 0.5), (10.0, 0.5), (10.0, 4.0), (6.0, 4.0)],
        ceiling_height=2.8,
        floor_material="wood_walnut",
        confidence=conf,
    )

    walls = [
        Wall(wall_id="wall_n", start=(0.0, 0.0), end=(6.0, 0.0)),
        Wall(wall_id="wall_w", start=(0.0, 0.0), end=(0.0, 4.5)),
        Wall(wall_id="wall_s", start=(0.0, 4.5), end=(6.0, 4.5)),
        # Shared east wall split around the bedroom span.
        Wall(wall_id="wall_e_top", start=(6.0, 0.0), end=(6.0, 0.5)),
        Wall(wall_id="wall_shared", start=(6.0, 0.5), end=(6.0, 4.0)),
        Wall(wall_id="wall_e_bot", start=(6.0, 4.0), end=(6.0, 4.5)),
        Wall(wall_id="wall_bn", start=(6.0, 0.5), end=(10.0, 0.5)),
        Wall(wall_id="wall_be", start=(10.0, 0.5), end=(10.0, 4.0)),
        Wall(wall_id="wall_bs", start=(6.0, 4.0), end=(10.0, 4.0)),
    ]

    openings = [
        # Entry door on the south wall of the living room.
        Opening(
            opening_id="open_entry",
            type=OpeningType.DOOR,
            wall_id="wall_s",
            position=1.2,
            width=0.9,
            height=2.1,
        ),
        # Door between living room and bedroom in the shared wall.
        Opening(
            opening_id="open_bedroom",
            type=OpeningType.DOOR,
            wall_id="wall_shared",
            position=2.9,
            width=0.9,
            height=2.1,
        ),
        # Windows.
        Opening(
            opening_id="open_win_living",
            type=OpeningType.WINDOW,
            wall_id="wall_n",
            position=3.0,
            width=1.8,
            height=1.3,
            sill_height=0.9,
        ),
        Opening(
            opening_id="open_win_bed",
            type=OpeningType.WINDOW,
            wall_id="wall_be",
            position=1.75,
            width=1.4,
            height=1.2,
            sill_height=1.0,
        ),
    ]

    objects = [
        SceneObject(
            object_id="obj_sofa", semantic_type="sofa", asset_id="cat_sofa_3s",
            room_id="room_living", position=(2.6, 0.0, 0.62), rotation_y=3.14159,
            dimensions=(2.1, 0.85, 0.9), color="#b7a186", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_coffee", semantic_type="coffee_table", asset_id="cat_coffee_table",
            room_id="room_living", position=(2.6, 0.0, 2.1), rotation_y=0.0,
            dimensions=(1.1, 0.42, 0.6), color="#6b4f35", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_tv", semantic_type="tv_unit", asset_id="cat_tv_unit",
            room_id="room_living", position=(2.6, 0.0, 4.12), rotation_y=0.0,
            dimensions=(1.8, 0.5, 0.45), color="#4a3826", source=ObjectSource.SEED,
            locked=True,
        ),
        SceneObject(
            object_id="obj_rug", semantic_type="rug", asset_id="cat_rug",
            room_id="room_living", position=(2.6, 0.0, 1.6), rotation_y=0.0,
            dimensions=(2.4, 0.02, 1.7), color="#c9b299", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_plant", semantic_type="plant", asset_id="cat_plant",
            room_id="room_living", position=(0.45, 0.0, 3.9), rotation_y=0.0,
            dimensions=(0.45, 1.2, 0.45), color="#5f7a4f", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_bed", semantic_type="bed", asset_id="cat_bed_queen",
            room_id="room_bedroom", position=(8.85, 0.0, 2.25), rotation_y=1.5707963,
            dimensions=(1.6, 0.55, 2.05), color="#9c8468", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_wardrobe", semantic_type="wardrobe", asset_id="cat_wardrobe",
            room_id="room_bedroom", position=(7.0, 0.0, 0.93), rotation_y=3.14159,
            dimensions=(1.5, 2.1, 0.6), color="#5a4632", source=ObjectSource.SEED,
        ),
        SceneObject(
            object_id="obj_bedside", semantic_type="bedside_table", asset_id="cat_bedside",
            room_id="room_bedroom", position=(9.65, 0.0, 3.65), rotation_y=0.0,
            dimensions=(0.45, 0.55, 0.4), color="#6b4f35", source=ObjectSource.SEED,
        ),
    ]

    return Scene(
        scene_id="scene_seed_apartment",
        project_id=project_id,
        name="Seed Apartment — Living + Bedroom",
        rooms=[living, bedroom],
        walls=walls,
        openings=openings,
        objects=objects,
        calibration=Calibration(meters_per_unit=1.0, source="seed", confidence=1.0),
        metadata={"golden_scene": "GS-001"},
    )


def ensure_seed(store: SceneStore) -> None:
    from .projects import get_project_store

    projects = get_project_store()
    if projects.find("proj_seed") is None:
        projects.create(
            name="Seed Project",
            project_id="proj_seed",
            scene_ids=["scene_seed_apartment"],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    if store.exists("scene_seed_apartment"):
        return
    store.create(build_seed_scene("proj_seed"))

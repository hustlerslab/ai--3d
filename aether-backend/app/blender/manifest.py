"""Build manifest compiler: Scene (Y-up, radians) → build_manifest.json (Z-up, metres).

Blender never sees a Scene or a prompt; it reads this file only (DPR §12).
Conversion is one function pair:
    position  (x, y, z)  →  (x, −z, y)
    yaw around +Y (rad)  →  rotation_euler.z (rad), same sign
so an object facing −Z in the scene faces +Y in Blender.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from ..assets.registry import get_registry
from ..catalog.catalog import get_item
from ..core.config import get_settings
from ..materials.registry import get_material_registry
from ..scene.schema import Scene, Vec2, Vec3
from ..walkthrough import service as walkthrough_service

MANIFEST_VERSION = "1.1"


def to_blender_xyz(p: Vec3) -> list[float]:
    return [round(p[0], 4), round(-p[2], 4), round(p[1], 4)]


def to_blender_xy(p: Vec2) -> list[float]:
    return [round(p[0], 4), round(-p[1], 4)]


def yaw_to_blender_rz(rotation_y: float) -> float:
    return round(rotation_y, 6)


def scene_forward(rotation_y: float) -> tuple[float, float]:
    """Scene-space forward direction (x, z) for a yaw, as the spatial planner defines it."""
    return (-math.sin(rotation_y), -math.cos(rotation_y))


def blender_forward(rz: float) -> tuple[float, float]:
    """Blender XY forward for rotation_euler.z, given local forward = +Y."""
    return (-math.sin(rz), math.cos(rz))


def _material_entry(material_id: str) -> Optional[dict[str, Any]]:
    rec = get_material_registry().get(material_id)
    if rec is None:
        return None
    data_dir = get_settings().data_dir
    maps: dict[str, str] = {}
    for key in ("color", "normal", "roughness", "ao"):
        rel = getattr(rec.maps, key, None)
        if rel:
            path = data_dir / rel
            if path.exists():
                maps[key] = str(path)
    return {
        "id": rec.material_id,
        "name": rec.name,
        "category": rec.category,
        "base_color": rec.base_color,
        "roughness": rec.roughness,
        "metalness": rec.metalness,
        "tile_size_m": rec.tile_size_m,
        "finish": rec.finish,
        "maps": maps,
    }


def _asset_entry(asset_id: Optional[str], semantic_type: str, *, shape_hint: Optional[str] = None,
                 texture_ref: Optional[str] = None, project_root: Optional[Path] = None) -> dict[str, Any]:
    texture = ""
    if texture_ref and project_root is not None:
        candidate = project_root / texture_ref
        if candidate.exists():
            texture = str(candidate)
    if asset_id and not texture:
        record = get_registry().get(asset_id) if hasattr(get_registry(), "get") else None
        glb = get_registry().root / "normalized" / f"{asset_id}.glb"
        if glb.exists():
            return {
                "kind": "glb",
                "asset_id": asset_id,
                "path": str(glb),
                "name": record.name if record else asset_id,
                # A model generated for THIS project came from the client's own
                # approved render, so its textures are already the fabric they
                # chose. Re-skinning it with the style material would throw that
                # away - which is the whole thing the generation was paid for.
                # A catalog piece is generic and still gets re-skinned.
                "own_materials": bool(record and record.project_id),
            }
        item = get_item(asset_id)
        if item is not None and item.shape != "model":
            shape = shape_hint or (_default_shape(semantic_type) if semantic_type in _SHAPE_BY_TYPE else item.shape)
            return {"kind": "procedural", "asset_id": asset_id, "shape": shape, "name": item.name}
    entry: dict[str, Any] = {
        "kind": "procedural", "asset_id": asset_id, "shape": shape_hint or _default_shape(semantic_type), "name": semantic_type,
    }
    if texture:
        entry["texture"] = texture
    return entry


# types whose procedural shape is richer than the catalog's generic primitive
_SHAPE_BY_TYPE = {
    "tv_unit": "tv", "kitchen_counter": "counter", "curtains": "curtains", "fridge": "fridge",
    "wall_art": "photo", "mirror": "mirror", "table_lamp": "lamp", "fireplace": "fireplace", "books": "books",
    "vase": "vase", "tray": "tray", "sconce": "sconce", "wall_shelf": "shelf", "pillows": "pillow",
    "candle": "candle", "wall_clock": "clock", "stool": "seat", "lantern": "vase", "basket": "vase",
}


def _default_shape(semantic_type: str) -> str:
    if semantic_type in ("sofa", "loveseat", "armchair", "chair", "bar_stool", "ottoman"):
        return "seat"
    if semantic_type in ("coffee_table", "dining_table", "side_table", "desk", "console", "kitchen_island"):
        return "table"
    if semantic_type in _SHAPE_BY_TYPE:
        return _SHAPE_BY_TYPE[semantic_type]
    if semantic_type in ("wardrobe", "bookshelf", "floor_lamp", "plant", "mirror"):
        return "tall"
    if semantic_type in ("pendant_lamp", "chandelier"):
        return "pendant"
    if semantic_type in ("wall_art",):
        return "photo"
    return "box"


def preview_shot(scene: Scene) -> tuple[Vec3, Vec3]:
    """An establishing shot of the largest room: camera in the corner farthest
    from the room's biggest piece of furniture, looking at the room centre."""
    from ..spatial import geometry as geo

    if not scene.rooms:
        return (0.0, 1.5, 3.0), (0.0, 1.0, 0.0)
    room = max(scene.rooms, key=lambda r: geo.polygon_area(r.boundary))
    cx, cz = geo.polygon_centroid(room.boundary)
    objects = [o for o in scene.objects if o.room_id == room.room_id and o.mount == "floor"]
    anchor = max(objects, key=lambda o: o.dimensions[0] * o.scale[0] * o.dimensions[2] * o.scale[2], default=None)
    ax, az = (anchor.position[0], anchor.position[2]) if anchor else (cx, cz)
    corner = max(room.boundary, key=lambda p: (p[0] - ax) ** 2 + (p[1] - az) ** 2)
    inset = 0.55
    px = corner[0] + (inset if cx > corner[0] else -inset)
    pz = corner[1] + (inset if cz > corner[1] else -inset)
    return (px, 1.55, pz), (cx, 0.95, cz)


def build_manifest(
    scene: Scene,
    *,
    project_id: str,
    project_root: Path,
    preview: bool = True,
    preview_profile: str = "preview",
) -> dict[str, Any]:
    blender_dir = project_root / "blender"
    previews_dir = project_root / "previews"
    material_ids: set[str] = set()

    rooms = []
    for r in scene.rooms:
        material_ids.add(r.floor_material)
        rooms.append(
            {
                "id": r.room_id,
                "name": r.name,
                "type": r.type,
                "boundary": [to_blender_xy(p) for p in r.boundary],
                "floor_height": r.floor_height,
                "ceiling_height": r.ceiling_height,
                "floor_material": r.floor_material,
                "features": list(r.features),
            }
        )

    walls = []
    for w in scene.walls:
        material_ids.add(w.material)
        walls.append(
            {
                "id": w.wall_id,
                "start": to_blender_xy(w.start),
                "end": to_blender_xy(w.end),
                "thickness": w.thickness,
                "height": w.height,
                "material": w.material,
                "openings": [
                    {
                        "id": o.opening_id,
                        "type": o.type.value,
                        "position": o.position,
                        "width": o.width,
                        "height": o.height,
                        "sill_height": o.sill_height,
                    }
                    for o in scene.openings_for_wall(w.wall_id)
                ],
            }
        )

    objects = []
    for o in scene.objects:
        for mid in o.material_overrides.values():
            material_ids.add(mid)
        objects.append(
            {
                "id": o.object_id,
                "semantic_type": o.semantic_type,
                "room_id": o.room_id,
                "strategy": o.source_strategy,
                "name": o.name,
                "asset": _asset_entry(o.asset_id, o.semantic_type, shape_hint=o.shape, texture_ref=o.texture_ref,
                                      project_root=project_root),
                "location": to_blender_xyz(o.position),
                "rotation_rad": [0.0, 0.0, yaw_to_blender_rz(o.rotation_y)],
                "scale": [o.scale[0], o.scale[2], o.scale[1]],
                "dimensions": [o.dimensions[0], o.dimensions[2], o.dimensions[1]],  # w, d, h
                "color": o.color,
                "mount": o.mount,
                "parent": o.parent_id,
                "material_overrides": dict(o.material_overrides),
                "locked": o.locked,
            }
        )

    materials = {}
    for mid in sorted(material_ids):
        entry = _material_entry(mid)
        if entry is not None:
            materials[mid] = entry

    lighting: dict[str, Any] = {}
    if scene.lighting:
        lighting = {
            "mood": scene.lighting.mood,
            "sun_azimuth_deg": scene.lighting.sun_azimuth_deg,
            "sun_elevation_deg": scene.lighting.sun_elevation_deg,
            "sun_strength": scene.lighting.sun_strength,
            "sky_turbidity": scene.lighting.sky_turbidity,
            "exposure_ev": scene.lighting.exposure_ev,
            "interior_lights": [
                {
                    "id": l.light_id,
                    "room_id": l.room_id,
                    "type": l.type,
                    "location": to_blender_xyz(l.position),
                    "power_w": l.power_w,
                    "color_temp_k": l.color_temp_k,
                    "size_m": l.size_m,
                }
                for l in scene.lighting.interior_lights
            ],
        }

    shot_pos, shot_look = preview_shot(scene)
    tour = walkthrough_service.generate_tour(scene)
    camera = {
        "preview_shot": {"position": to_blender_xyz(shot_pos), "look_at": to_blender_xyz(shot_look)},
        "keyframes": [
            {
                "position": to_blender_xyz(k.position),
                "look_at": to_blender_xyz(k.look_at),
                "duration": k.duration,
                "room_id": k.room_id,
                "label": k.label,
            }
            for k in tour.keyframes
        ],
        "total_duration": tour.total_duration,
        "room_order": tour.room_order,
    }

    return {
        "manifest_version": MANIFEST_VERSION,
        "project_id": project_id,
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "scene_name": scene.name,
        "units": "meters",
        "up_axis": "Z",
        "output": {
            "blend": str(blender_dir / "scene.blend"),
            "report": str(blender_dir / "validation_report.json"),
            "preview": str(previews_dir / "build_preview.png") if preview else "",
            "preview_profile": preview_profile,
        },
        "style": scene.style.model_dump() if scene.style else {},
        "rooms": rooms,
        "walls": walls,
        "objects": objects,
        "materials": materials,
        "lighting": lighting,
        "camera": camera,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path

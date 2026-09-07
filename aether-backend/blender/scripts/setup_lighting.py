"""Lighting from the manifest's LightingSpec: sky, sun, interior area lights, exposure."""
from __future__ import annotations

import math

import bpy  # type: ignore


def _kelvin_to_rgb(k: float) -> tuple[float, float, float]:
    """Approximate blackbody colour (Tanner Helland fit), linear-ish."""
    t = max(1000.0, min(12000.0, k)) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    clamp = lambda v: max(0.0, min(255.0, v)) / 255.0  # noqa: E731
    return (clamp(r), clamp(g), clamp(b))


def _world(lighting: dict, warnings: list[str]) -> None:
    scene = bpy.context.scene
    world = bpy.data.worlds.new("AllureWorld")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes.get("Background")
    try:
        sky = nodes.new("ShaderNodeTexSky")
        if hasattr(sky, "sky_type"):
            # Blender 5.x renamed Nishita: MULTIPLE_SCATTERING is the physical sky.
            for kind in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING"):
                try:
                    sky.sky_type = kind
                    break
                except TypeError:
                    continue
        sky.sun_elevation = math.radians(lighting.get("sun_elevation_deg", 40.0))
        sky.sun_rotation = math.radians(lighting.get("sun_azimuth_deg", 135.0))
        sky.sun_intensity = 0.6
        sky.sun_size = math.radians(1.0)
        if hasattr(sky, "dust_density"):
            sky.dust_density = float(lighting.get("sky_turbidity", 2.5))
        links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.35
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"sky texture unavailable ({exc}); flat world colour used")
        bg.inputs["Color"].default_value = (0.75, 0.8, 0.9, 1.0)
        bg.inputs["Strength"].default_value = 0.6


def setup(manifest: dict, cols: dict, warnings: list[str]) -> None:
    lighting = manifest.get("lighting") or {}
    col = cols["Lighting"]
    scene = bpy.context.scene
    _world(lighting, warnings)

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = float(lighting.get("sun_strength", 3.0))
    sun_data.angle = math.radians(1.5)
    sun_data.color = _kelvin_to_rgb(5500 if lighting.get("mood") != "evening" else 3000)
    sun = bpy.data.objects.new("Sun", sun_data)
    col.objects.link(sun)
    elev = math.radians(lighting.get("sun_elevation_deg", 40.0))
    az = math.radians(lighting.get("sun_azimuth_deg", 135.0))
    sun.rotation_euler = (math.pi / 2 - elev, 0.0, az)
    sun.location = (0.0, 0.0, 10.0)

    for spec in lighting.get("interior_lights", []):
        kind = {"area": "AREA", "point": "POINT", "spot": "SPOT"}.get(spec.get("type", "area"), "AREA")
        data = bpy.data.lights.new(spec["id"], kind)
        data.energy = float(spec.get("power_w", 60.0))
        data.color = _kelvin_to_rgb(float(spec.get("color_temp_k", 3200)))
        if kind == "AREA":
            data.shape = "SQUARE"
            data.size = float(spec.get("size_m", 0.6))
        obj = bpy.data.objects.new(spec["id"], data)
        obj.location = spec["location"]
        obj["aether_room"] = spec.get("room_id", "")
        col.objects.link(obj)

    scene.view_settings.exposure = float(lighting.get("exposure_ev", 0.0))

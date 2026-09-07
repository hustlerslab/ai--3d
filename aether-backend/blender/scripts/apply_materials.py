"""Materials: MaterialRecord → Principled BSDF, metric box-projected textures.

Registry materials carry colour / normal / roughness / AO maps tiled every
`tile_size_m` metres. Architecture meshes have no UVs, so textures use
Object coordinates with BOX projection scaled by 1 / tile_size, which gives
correct metric tiling on floors, walls and procedural furniture alike.
"""
from __future__ import annotations

import os

import bpy  # type: ignore


def _hex(color: str):
    c = color.lstrip("#")
    if len(c) != 6:
        return (0.6, 0.55, 0.5, 1.0)
    r, g, b = (int(c[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    # sRGB → linear
    lin = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return (lin(r), lin(g), lin(b), 1.0)


def _load_image(path: str, non_color: bool):
    img = bpy.data.images.get(os.path.basename(path))
    if img is None or not img.filepath or os.path.abspath(bpy.path.abspath(img.filepath)) != os.path.abspath(path):
        img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


class MaterialLibrary:
    def __init__(self, records: dict, style: dict):
        self.records = records
        self.style = style
        self._cache: dict[str, bpy.types.Material] = {}
        self.missing: list[str] = []

    # ── registry materials ───────────────────────────────────────────────
    def get(self, material_id: str | None, fallback_color: str = "#B9A88F"):
        if not material_id:
            return self.color(fallback_color)
        if material_id in self._cache:
            return self._cache[material_id]
        rec = self.records.get(material_id)
        if rec is None:
            self.missing.append(material_id)
            mat = self.color(fallback_color)
            self._cache[material_id] = mat
            return mat
        mat = bpy.data.materials.new(material_id)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = _hex(rec.get("base_color", "#cccccc"))
        bsdf.inputs["Roughness"].default_value = float(rec.get("roughness", 0.8))
        bsdf.inputs["Metallic"].default_value = float(rec.get("metalness", 0.0))
        if rec.get("category") == "glass":
            bsdf.inputs["Transmission Weight"].default_value = 1.0
            bsdf.inputs["Roughness"].default_value = 0.05
        maps = rec.get("maps") or {}
        if maps:
            tile = float(rec.get("tile_size_m") or 1.0)
            coord = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (1.0 / tile, 1.0 / tile, 1.0 / tile)
            links.new(coord.outputs["Object"], mapping.inputs["Vector"])
            y = 300
            for key, socket, non_color in (("color", "Base Color", False), ("roughness", "Roughness", True)):
                path = maps.get(key)
                if not path or not os.path.exists(path):
                    continue
                tex = nodes.new("ShaderNodeTexImage")
                tex.image = _load_image(path, non_color)
                tex.projection = "BOX"
                tex.projection_blend = 0.25
                tex.location = (-500, y)
                y -= 300
                links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                links.new(tex.outputs["Color"], bsdf.inputs[socket])
            normal = maps.get("normal")
            if normal and os.path.exists(normal):
                tex = nodes.new("ShaderNodeTexImage")
                tex.image = _load_image(normal, True)
                tex.projection = "BOX"
                tex.projection_blend = 0.25
                tex.location = (-500, y)
                links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                nm = nodes.new("ShaderNodeNormalMap")
                nm.inputs["Strength"].default_value = 0.6
                links.new(tex.outputs["Color"], nm.inputs["Color"])
                links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        self._cache[material_id] = mat
        return mat

    # ── simple materials ─────────────────────────────────────────────────
    def color(self, hex_color: str, roughness: float = 0.65, metallic: float = 0.0):
        key = f"col_{hex_color.lstrip('#').lower()}_{roughness}_{metallic}"
        if key in self._cache:
            return self._cache[key]
        mat = bpy.data.materials.new(key)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = _hex(hex_color)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        self._cache[key] = mat
        return mat

    def accent(self, hex_color: str):
        """Darker companion colour for legs, frames and trims."""
        c = hex_color.lstrip("#")
        try:
            r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            r, g, b = 90, 75, 60
        dark = "#{:02x}{:02x}{:02x}".format(int(r * 0.45), int(g * 0.45), int(b * 0.45))
        return self.color(dark, roughness=0.5)

    def ceiling(self):
        return self.color("#F4F1EA", roughness=0.9)

    def glass(self):
        if "glass" in self._cache:
            return self._cache["glass"]
        mat = bpy.data.materials.new("glass")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (0.9, 0.95, 1.0, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.02
        bsdf.inputs["Transmission Weight"].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.45
        self._cache["glass"] = mat
        return mat

    def frame(self):
        return self.color("#3A3632", roughness=0.4, metallic=0.2)

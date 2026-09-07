"""Materials: MaterialRecord → Principled BSDF, metric box-projected textures,
and moodboard tints.

Registry materials carry colour / normal / roughness / AO maps tiled every
`tile_size_m` metres. Architecture meshes have no UVs, so textures use
Object coordinates with BOX projection scaled by 1 / tile_size, which gives
correct metric tiling on floors, walls and procedural furniture alike.

A tint multiplies the colour map (or the base colour) so the same linen
texture can be the palette's upholstery colour on the sofa and the accent
colour on the curtains. Walls take the palette's first colour.
"""
from __future__ import annotations

import os

import bpy  # type: ignore


def _hex(color: str):
    c = (color or "").lstrip("#")
    if len(c) != 6:
        return (0.6, 0.55, 0.5, 1.0)
    try:
        r, g, b = (int(c[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return (0.6, 0.55, 0.5, 1.0)
    lin = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return (lin(r), lin(g), lin(b), 1.0)


def _load_image(path: str, non_color: bool):
    img = bpy.data.images.get(os.path.basename(path))
    if img is None or not img.filepath or os.path.abspath(bpy.path.abspath(img.filepath)) != os.path.abspath(path):
        img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def _tint_key(tint: str | None) -> str:
    return (tint or "").lstrip("#").lower()


class MaterialLibrary:
    def __init__(self, records: dict, style: dict):
        self.records = records
        self.style = style or {}
        self.palette: list[str] = [p for p in (self.style.get("palette") or []) if isinstance(p, str)]
        self._cache: dict[str, bpy.types.Material] = {}
        self.missing: list[str] = []

    # palette slots (prompt order): wall, floor, upholstery, accent, accent
    @property
    def wall_tint(self) -> str | None:
        return self.palette[0] if len(self.palette) >= 1 else None

    @property
    def upholstery_tint(self) -> str | None:
        return self.palette[2] if len(self.palette) >= 3 else None

    # ── registry materials ───────────────────────────────────────────────
    def get(self, material_id: str | None, fallback_color: str = "#B9A88F", tint: str | None = None, tint_strength: float = 1.0):
        if not material_id:
            return self.color(tint or fallback_color)
        key = f"{material_id}|{_tint_key(tint)}|{tint_strength}"
        if key in self._cache:
            return self._cache[key]
        rec = self.records.get(material_id)
        if rec is None:
            self.missing.append(material_id)
            mat = self.color(tint or fallback_color)
            self._cache[key] = mat
            return mat
        mat = bpy.data.materials.new(key)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        base = _hex(rec.get("base_color", "#cccccc"))
        bsdf.inputs["Base Color"].default_value = base
        bsdf.inputs["Roughness"].default_value = float(rec.get("roughness", 0.8))
        bsdf.inputs["Metallic"].default_value = float(rec.get("metalness", 0.0))
        if rec.get("category") == "glass":
            bsdf.inputs["Transmission Weight"].default_value = 1.0
            bsdf.inputs["Roughness"].default_value = 0.05
        maps = rec.get("maps") or {}
        color_socket_source = None
        if maps:
            tile = float(rec.get("tile_size_m") or 1.0)
            coord = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (1.0 / tile, 1.0 / tile, 1.0 / tile)
            links.new(coord.outputs["Object"], mapping.inputs["Vector"])
            y = 300
            for key_name, socket, non_color in (("color", "Base Color", False), ("roughness", "Roughness", True)):
                path = maps.get(key_name)
                if not path or not os.path.exists(path):
                    continue
                tex = nodes.new("ShaderNodeTexImage")
                tex.image = _load_image(path, non_color)
                tex.projection = "BOX"
                tex.projection_blend = 0.25
                tex.location = (-500, y)
                y -= 300
                links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                if socket == "Base Color":
                    color_socket_source = tex.outputs["Color"]
                else:
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
        if tint:
            # Recolour: the texture's grain (luminance, normalised around mid-grey)
            # times the tint, so a grey linen scan becomes the palette's linen.
            tint_rgba = _hex(tint)
            if color_socket_source is not None:
                bw = nodes.new("ShaderNodeRGBToBW")
                links.new(color_socket_source, bw.inputs["Color"])
                gain = nodes.new("ShaderNodeMath")
                gain.operation = "MULTIPLY"
                gain.inputs[1].default_value = 1.0 / 0.45  # typical scan luminance → 1.0
                links.new(bw.outputs["Val"], gain.inputs[0])
                mul = nodes.new("ShaderNodeMix")
                mul.data_type = "RGBA"
                mul.blend_type = "MULTIPLY"
                mul.inputs["Factor"].default_value = 1.0
                mul.inputs[7].default_value = tint_rgba  # B
                grain = nodes.new("ShaderNodeCombineColor")
                for k in range(3):
                    links.new(gain.outputs["Value"], grain.inputs[k])
                links.new(grain.outputs["Color"], mul.inputs[6])  # A
                # blend between the original scan and the recoloured one by tint_strength
                final = nodes.new("ShaderNodeMix")
                final.data_type = "RGBA"
                final.blend_type = "MIX"
                final.inputs["Factor"].default_value = tint_strength
                links.new(color_socket_source, final.inputs[6])
                links.new(mul.outputs[2], final.inputs[7])
                links.new(final.outputs[2], bsdf.inputs["Base Color"])
            else:
                mixed = tuple(base[i] * (1 - tint_strength) + tint_rgba[i] * tint_strength for i in range(3)) + (1.0,)
                bsdf.inputs["Base Color"].default_value = mixed
        elif color_socket_source is not None:
            links.new(color_socket_source, bsdf.inputs["Base Color"])
        self._cache[key] = mat
        return mat

    # ── simple materials ─────────────────────────────────────────────────
    def color(self, hex_color: str, roughness: float = 0.65, metallic: float = 0.0):
        key = f"col_{_tint_key(hex_color)}_{roughness}_{metallic}"
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
        c = (hex_color or "").lstrip("#")
        try:
            r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            r, g, b = 90, 75, 60
        dark = "#{:02x}{:02x}{:02x}".format(int(r * 0.45), int(g * 0.45), int(b * 0.45))
        return self.color(dark, roughness=0.5)

    def for_object(self, spec: dict):
        """Material for a procedural piece: style material (tinted with the
        object's moodboard colour) when the planner assigned one, else the colour."""
        override = (spec.get("material_overrides") or {}).get("primary")
        color = spec.get("color") or "#8a7862"
        if override and override in self.records:
            return self.get(override, tint=color, tint_strength=0.85)
        return self.color(color)

    def wall(self, material_id: str):
        return self.get(material_id, fallback_color="#ECE5D8", tint=self.wall_tint, tint_strength=0.7)

    def ceiling(self):
        return self.color("#F4F1EA", roughness=0.9)

    def skirting(self):
        return self.color("#F1EEE8", roughness=0.5)

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

    def screen(self):
        if "screen" in self._cache:
            return self._cache["screen"]
        mat = bpy.data.materials.new("screen")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.08
        bsdf.inputs["Metallic"].default_value = 0.3
        self._cache["screen"] = mat
        return mat

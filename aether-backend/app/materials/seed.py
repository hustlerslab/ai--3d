"""Built-in materials — the vocabulary scenes reference by id.

These carry colour/roughness only; the CC0 sourcing step attaches real PBR
maps to the same ids, so a scene authored today upgrades visually the moment
maps land without any scene change (the id is the contract).
"""
from __future__ import annotations

from .schema import MaterialRecord


def _m(material_id, name, category, base_color, roughness=0.8, metalness=0.0, tile=1.0, finish="matte", tags=(), applies=("furniture",)):
    return MaterialRecord(
        material_id=material_id,
        name=name,
        category=category,
        base_color=base_color,
        roughness=roughness,
        metalness=metalness,
        tile_size_m=tile,
        finish=finish,
        style_tags=list(tags),
        applies_to=list(applies),
    )


BUILTIN_MATERIALS: list[MaterialRecord] = [
    # Walls / paint
    _m("paint_white", "Warm White Paint", "paint", "#ece5d8", 0.92, tile=2.0, tags=["modern", "minimal"], applies=["wall", "ceiling"]),
    _m("paint_ivory", "Ivory Paint", "paint", "#f2ebdf", 0.92, tile=2.0, tags=["luxury", "classic"], applies=["wall", "ceiling"]),
    _m("paint_sage", "Sage Paint", "paint", "#b9bfae", 0.92, tile=2.0, tags=["japandi", "calm"], applies=["wall"]),
    _m("paint_terracotta", "Terracotta Paint", "paint", "#b8674a", 0.9, tile=2.0, tags=["modern_indian", "warm"], applies=["wall"]),
    _m("plaster_lime", "Lime Plaster", "plaster", "#e6dccb", 0.95, tile=2.0, finish="textured", tags=["luxury", "mediterranean"], applies=["wall"]),
    # Floors
    _m("wood_oak", "Oak Plank Floor", "wood", "#c9a578", 0.7, tile=2.0, finish="satin", tags=["modern", "warm_neutral"], applies=["floor"]),
    _m("wood_oak_herringbone", "Oak Herringbone", "wood", "#c19b6f", 0.6, tile=1.5, finish="satin", tags=["luxury", "classic"], applies=["floor"]),
    _m("wood_walnut", "Walnut Plank Floor", "wood", "#6b4f35", 0.65, tile=2.0, finish="satin", tags=["luxury", "dark"], applies=["floor"]),
    _m("wood_dark", "Dark Stained Planks", "wood", "#3f2f22", 0.6, tile=2.0, finish="satin", tags=["luxury", "moody"], applies=["floor"]),
    _m("marble", "Ivory Marble", "marble", "#e9e4dc", 0.25, tile=1.2, finish="polished", tags=["luxury", "classic"], applies=["floor", "wall"]),
    _m("tile_ivory", "Ivory Porcelain Tile", "tile", "#e4ddd0", 0.4, tile=1.2, finish="satin", tags=["modern"], applies=["floor", "wall"]),
    _m("stone_granite", "Granite Tile", "stone", "#8c8478", 0.35, tile=1.2, finish="polished", tags=["luxury"], applies=["floor"]),
    _m("terrazzo", "Terrazzo", "stone", "#d8cfc2", 0.45, tile=1.0, finish="polished", tags=["modern", "playful"], applies=["floor"]),
    # Furniture finishes
    _m("veneer_oak", "Oak Veneer", "wood", "#c9a578", 0.55, tile=0.6, finish="satin", tags=["modern", "japandi"]),
    _m("veneer_walnut", "Walnut Veneer", "wood", "#6b4f35", 0.5, tile=0.6, finish="satin", tags=["luxury", "mid_century"]),
    _m("fabric_linen", "Linen", "fabric", "#c9bba4", 0.95, tile=0.4, tags=["natural", "warm_neutral"]),
    _m("fabric_velvet", "Velvet", "fabric", "#4f5a49", 0.85, tile=0.4, finish="sheen", tags=["luxury", "moody"]),
    _m("fabric_boucle", "Wool Bouclé", "fabric", "#e2d9c8", 0.98, tile=0.35, tags=["luxury", "modern"]),
    _m("leather_tan", "Tan Leather", "leather", "#9a6b45", 0.45, tile=0.5, finish="semi_gloss", tags=["luxury", "mid_century"]),
    _m("leather_white", "Cream Leather", "leather", "#e8e0d2", 0.45, tile=0.5, finish="semi_gloss", tags=["luxury", "modern"]),
    _m("metal_brass", "Brushed Brass", "metal", "#c8a04e", 0.35, metalness=0.9, tile=0.3, finish="brushed", tags=["luxury"]),
    _m("metal_black", "Matte Black Steel", "metal", "#1f1f1f", 0.6, metalness=0.8, tile=0.3, tags=["modern", "industrial"]),
    _m("glass_clear", "Clear Glass", "glass", "#dcebf2", 0.05, tile=1.0, finish="polished", tags=["modern"]),
]

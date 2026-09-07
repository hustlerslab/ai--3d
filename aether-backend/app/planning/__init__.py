"""Scene planning (plan §7 asset decision, §9 scene assembly).

  ObjectPlan + StyleSpec ──asset_decision──▶ AssetPlan
  DesignAnalysis.rooms   ──layout──────────▶ floor plan (rooms, walls, openings)
  all of the above       ──compiler────────▶ Scene (committed through patches)
"""
from .asset_decision import decide_asset, resolve_plan
from .compiler import compile_scene, place_objects
from .layout import PlacedRoom, WallSeg, build_walls_and_openings, layout_rooms

__all__ = [
    "PlacedRoom",
    "WallSeg",
    "build_walls_and_openings",
    "compile_scene",
    "decide_asset",
    "layout_rooms",
    "place_objects",
    "resolve_plan",
]

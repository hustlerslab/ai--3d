"""Asset decision agent (plan §7, DPR §9): reuse → modify → procedural → generate.

For each planned object:
  1. a registry model of the same semantic type within ±15 % of the target
     size                                → local_asset
  2. the same within ±25 % (scaled) or with a material override → local_modified
  3. a parametric built-in exists         → procedural
  4. flagged unique and Meshy configured  → generated (procedural stand-in meanwhile)
  otherwise a generic procedural box with default dimensions.
"""
from __future__ import annotations

from typing import Optional

from ..catalog.catalog import BUILTIN, CatalogItem, all_items
from ..core.config import get_settings
from ..intelligence.schema import AssetDecision, AssetPlan, ObjectPlan, ObjectPlanItem, StyleSpec
from ..materials.registry import get_material_registry

Vec3 = tuple[float, float, float]

LOCAL_FIT = 0.85       # ±15 %
MODIFIED_FIT = 0.70    # ±25 % with scaling
SCALE_MIN, SCALE_MAX = 0.75, 1.25

# default (w, h, d) and mount for semantic types without a built-in primitive
DEFAULT_DIMS: dict[str, tuple[Vec3, str]] = {
    "side_table": ((0.5, 0.55, 0.5), "floor"),
    "ottoman": ((0.8, 0.42, 0.8), "floor"),
    "dresser": ((1.2, 0.8, 0.5), "floor"),
    "desk": ((1.4, 0.75, 0.7), "floor"),
    "sideboard": ((1.6, 0.8, 0.45), "floor"),
    "console": ((1.2, 0.8, 0.35), "floor"),
    "kitchen_island": ((1.8, 0.9, 0.9), "floor"),
    "bar_stool": ((0.4, 0.75, 0.4), "floor"),
    "vanity": ((1.0, 0.85, 0.5), "floor"),
    "bathtub": ((1.7, 0.6, 0.75), "floor"),
    "table_lamp": ((0.3, 0.5, 0.3), "floor"),
    "vase": ((0.25, 0.4, 0.25), "floor"),
    "sculpture": ((0.3, 0.6, 0.3), "floor"),
    "lantern": ((0.25, 0.45, 0.25), "floor"),
    "pillows": ((0.5, 0.15, 0.5), "floor"),
    "pendant_lamp": ((0.45, 0.5, 0.45), "ceiling"),
    "chandelier": ((0.9, 0.8, 0.9), "ceiling"),
    "mirror": ((0.8, 1.2, 0.05), "wall"),
    "wall_art": ((0.9, 0.7, 0.05), "wall"),
    "curtains": ((2.0, 2.6, 0.1), "wall"),
}

# object types that get the style's fabric / wood / metal / glass
_FABRIC = {"sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "pillows", "curtains", "rug", "bar_stool"}
_WOOD = {
    "coffee_table", "side_table", "tv_unit", "dining_table", "wardrobe", "bedside_table", "dresser", "desk",
    "bookshelf", "sideboard", "console", "kitchen_island", "vanity",
}
_METAL = {"floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "lantern", "mirror"}

_BUILTIN_BY_TYPE: dict[str, CatalogItem] = {}
for _b in BUILTIN:
    _BUILTIN_BY_TYPE.setdefault(_b.semantic_type, _b)


def _fit(have: Vec3, want: Vec3) -> float:
    """Worst-axis size agreement in 0..1 (plan §7: ±15 % per dimension)."""
    ratios = []
    for h, w in zip(have, want):
        if h <= 0 or w <= 0:
            continue
        ratios.append(min(h, w) / max(h, w))
    return min(ratios) if ratios else 0.0


def _style_overlap(item: CatalogItem, style: StyleSpec) -> int:
    return len(set(item.style_tags) & set(style.tags))


def _target_dimensions(item: ObjectPlanItem) -> tuple[Vec3, str]:
    if item.approx_dimensions:
        builtin = _BUILTIN_BY_TYPE.get(item.semantic_type)
        mount = builtin.mount if builtin else DEFAULT_DIMS.get(item.semantic_type, ((1, 1, 1), "floor"))[1]
        return tuple(item.approx_dimensions), mount  # type: ignore[return-value]
    builtin = _BUILTIN_BY_TYPE.get(item.semantic_type)
    if builtin:
        return builtin.dimensions, builtin.mount
    dims, mount = DEFAULT_DIMS.get(item.semantic_type, ((0.8, 0.8, 0.8), "floor"))
    return dims, mount


def style_materials(style: StyleSpec) -> dict[str, str]:
    """Role → material_id from the style's material list (fabric, wood, metal, glass)."""
    registry = get_material_registry()
    roles: dict[str, str] = {}
    for mid in style.materials:
        rec = registry.get(mid)
        if rec is None:
            continue
        if rec.category in ("fabric", "leather") and "fabric" not in roles:
            roles["fabric"] = mid
        elif rec.category == "wood" and "furniture" in rec.applies_to and "wood" not in roles:
            roles["wood"] = mid
        elif rec.category == "metal" and "metal" not in roles:
            roles["metal"] = mid
        elif rec.category == "glass" and "glass" not in roles:
            roles["glass"] = mid
    return roles


def _overrides(sem: str, hint: str, roles: dict[str, str]) -> dict[str, str]:
    role = hint if hint in ("fabric", "wood", "metal", "glass") else (
        "fabric" if sem in _FABRIC else "wood" if sem in _WOOD else "metal" if sem in _METAL else ""
    )
    if role and role in roles:
        return {"primary": roles[role]}
    return {}


def decide_asset(item: ObjectPlanItem, style: StyleSpec, *, roles: Optional[dict[str, str]] = None) -> AssetDecision:
    roles = roles if roles is not None else style_materials(style)
    target, mount = _target_dimensions(item)
    overrides = _overrides(item.semantic_type, item.material_hint, roles)
    candidates = [i for i in all_items() if i.semantic_type == item.semantic_type and i.model_url]

    ranked = sorted(candidates, key=lambda i: (_fit(i.dimensions, target), _style_overlap(i, style)), reverse=True)
    if ranked:
        best = ranked[0]
        fit = _fit(best.dimensions, target)
        if fit >= LOCAL_FIT:
            return AssetDecision(
                object_key=item.object_key, semantic_type=item.semantic_type, strategy="local_asset",
                asset_id=best.asset_id, asset_name=best.name, has_model=True, dimensions=best.dimensions,
                fit_score=round(fit, 3), color=best.color, mount=best.mount, material_overrides=overrides,
                reason=f"registry model within 15% of target size (fit {fit:.2f})",
            )
        if fit >= MODIFIED_FIT:
            scale = tuple(max(SCALE_MIN, min(SCALE_MAX, t / h if h > 0 else 1.0)) for t, h in zip(target, best.dimensions))
            return AssetDecision(
                object_key=item.object_key, semantic_type=item.semantic_type, strategy="local_modified",
                asset_id=best.asset_id, asset_name=best.name, has_model=True, dimensions=best.dimensions,
                scale=scale, fit_score=round(fit, 3), color=best.color, mount=best.mount,  # type: ignore[arg-type]
                material_overrides=overrides,
                reason=f"registry model scaled to target size (fit {fit:.2f})",
            )

    builtin = _BUILTIN_BY_TYPE.get(item.semantic_type)
    if item.unique and get_settings().meshy_configured:
        stand_in = builtin.dimensions if builtin else target
        return AssetDecision(
            object_key=item.object_key, semantic_type=item.semantic_type, strategy="generated",
            asset_id=builtin.asset_id if builtin else None, asset_name=builtin.name if builtin else "generated stand-in",
            has_model=False, dimensions=stand_in, color=builtin.color if builtin else "#8a7862", mount=mount,
            material_overrides=overrides,
            generation_prompt=f"{style.name.replace('_', ' ')} {item.semantic_type.replace('_', ' ')}, {item.style_notes}".strip(", "),
            reason="unique piece routed to generation; procedural stand-in until it validates",
        )
    if builtin:
        dims = tuple(item.approx_dimensions) if item.approx_dimensions else builtin.dimensions
        return AssetDecision(
            object_key=item.object_key, semantic_type=item.semantic_type, strategy="procedural",
            asset_id=builtin.asset_id, asset_name=builtin.name, has_model=False, dimensions=dims,  # type: ignore[arg-type]
            color=builtin.color, mount=builtin.mount, material_overrides=overrides,
            reason="no registry model of this type; parametric built-in" + (" (best model fit too low)" if ranked else ""),
        )
    if ranked:
        best = ranked[0]
        fit = _fit(best.dimensions, target)
        scale = tuple(max(0.6, min(1.5, t / h if h > 0 else 1.0)) for t, h in zip(target, best.dimensions))
        return AssetDecision(
            object_key=item.object_key, semantic_type=item.semantic_type, strategy="local_modified",
            asset_id=best.asset_id, asset_name=best.name, has_model=True, dimensions=best.dimensions,
            scale=scale, fit_score=round(fit, 3), color=best.color, mount=best.mount,  # type: ignore[arg-type]
            material_overrides=overrides,
            reason=f"only registry model of this type, scaled beyond the usual range (fit {fit:.2f})",
        )
    return AssetDecision(
        object_key=item.object_key, semantic_type=item.semantic_type, strategy="procedural",
        asset_id=None, asset_name=f"generic {item.semantic_type.replace('_', ' ')}", has_model=False,
        dimensions=target, color="#8a7862", mount=mount, material_overrides=overrides,
        reason="no model and no built-in primitive; generic box with default dimensions",
    )


def resolve_plan(plan: ObjectPlan, style: StyleSpec) -> AssetPlan:
    roles = style_materials(style)
    decisions = [decide_asset(item, style, roles=roles) for item in plan.items]
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.strategy] = counts.get(d.strategy, 0) + 1
    warnings = [f"{d.object_key}: {d.reason}" for d in decisions if d.strategy == "procedural" and d.asset_id is None]
    return AssetPlan(decisions=decisions, counts=counts, warnings=warnings)

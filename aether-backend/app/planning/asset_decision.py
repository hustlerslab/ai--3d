"""Asset decision agent (plan §7, DPR §9): the asset ladder.

For each planned object, top rung first:
  1. a registry model of the same type (or, for open names, a model whose
     name matches) within ±15 % of the target size      → local_asset
  2. the same within ±25 % (scaled) or with a material override → local_modified
  3. a flat item with a photo crop (art, rug) → textured plane   → procedural + texture
  4. a parametric built-in exists (by type, else by family)      → procedural
  5. flagged unique / sculptural with a crop and Meshy configured → generated
     (procedural stand-in meanwhile; the crop is the reference image)
  otherwise a generic procedural box sized by the family defaults.
"""
from __future__ import annotations

import re
from typing import Optional

from ..catalog.catalog import BUILTIN, CatalogItem, all_items
from ..core.config import get_settings
from ..intelligence import vocab
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
    "stool": ((0.45, 0.45, 0.45), "floor"),
    "dresser": ((1.2, 0.8, 0.5), "floor"),
    "desk": ((1.4, 0.75, 0.7), "floor"),
    "sideboard": ((1.6, 0.8, 0.45), "floor"),
    "console": ((1.2, 0.8, 0.35), "floor"),
    "pedestal": ((0.4, 1.0, 0.4), "floor"),
    "basket": ((0.4, 0.4, 0.4), "floor"),
    "kitchen_island": ((1.8, 0.9, 0.9), "floor"),
    "kitchen_counter": ((2.4, 2.2, 0.6), "floor"),
    "fridge": ((0.7, 1.75, 0.7), "floor"),
    "fireplace": ((1.5, 1.2, 0.35), "floor"),
    "bar_stool": ((0.4, 0.75, 0.4), "floor"),
    "vanity": ((1.0, 0.85, 0.5), "floor"),
    "bathtub": ((1.7, 0.6, 0.75), "floor"),
    "table_lamp": ((0.35, 0.6, 0.35), "surface"),
    "vase": ((0.22, 0.4, 0.22), "surface"),
    "sculpture": ((0.25, 0.4, 0.25), "surface"),
    "lantern": ((0.25, 0.45, 0.25), "surface"),
    "candle": ((0.12, 0.25, 0.12), "surface"),
    "books": ((0.3, 0.12, 0.22), "surface"),
    "tray": ((0.5, 0.06, 0.35), "surface"),
    "pillows": ((0.45, 0.45, 0.15), "surface"),
    "throw": ((0.6, 0.08, 0.4), "surface"),
    "pendant_lamp": ((0.45, 0.5, 0.45), "ceiling"),
    "chandelier": ((0.9, 0.8, 0.9), "ceiling"),
    "mirror": ((0.8, 1.2, 0.05), "wall"),
    "wall_art": ((0.9, 0.7, 0.05), "wall"),
    "wall_clock": ((0.4, 0.4, 0.05), "wall"),
    "sconce": ((0.2, 0.35, 0.15), "wall"),
    "wall_shelf": ((0.35, 0.3, 0.25), "wall"),
    "curtains": ((2.0, 2.6, 0.12), "wall"),
}

# procedural shapes richer than the catalog's generic primitive
SHAPE_BY_TYPE: dict[str, str] = {
    "tv_unit": "tv", "kitchen_counter": "counter", "curtains": "curtains", "fridge": "fridge",
    "wall_art": "photo", "mirror": "mirror", "table_lamp": "lamp", "fireplace": "fireplace",
    "books": "books", "vase": "vase", "tray": "tray", "sconce": "sconce", "wall_shelf": "shelf",
    "pillows": "pillow", "candle": "candle", "wall_clock": "clock", "pedestal": "box", "basket": "vase",
    "stool": "seat", "lantern": "vase", "sculpture": "box", "throw": "box",
}

# flat things whose look IS the photo: the crop beats any library model
TEXTURED_TYPES = {"wall_art", "rug"}
# things worth image-to-3D when nothing local fits
SCULPTURAL_FAMILIES = {"ornament", "storage", "seating", "lighting", "architecture"}

PLACEMENT_MOUNT = {"floor": "floor", "wall": "wall", "ceiling": "ceiling", "on_surface": "surface"}

# object types that get the style's fabric / wood / metal / glass
_FABRIC = {"sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "pillows", "curtains", "rug", "bar_stool", "stool", "throw"}
_WOOD = {
    "coffee_table", "side_table", "tv_unit", "dining_table", "wardrobe", "bedside_table", "dresser", "desk",
    "bookshelf", "sideboard", "console", "kitchen_island", "kitchen_counter", "vanity", "pedestal", "wall_shelf",
}
_METAL = {"floor_lamp", "pendant_lamp", "chandelier", "table_lamp", "lantern", "mirror", "sconce"}
_FAMILY_ROLE = {"seating": "fabric", "bed": "fabric", "textile": "fabric", "table": "wood", "storage": "wood", "lighting": "metal"}

_BUILTIN_BY_TYPE: dict[str, CatalogItem] = {}
for _b in BUILTIN:
    _BUILTIN_BY_TYPE.setdefault(_b.semantic_type, _b)

_STOP = {"a", "an", "the", "with", "and", "of", "on", "in", "for", "large", "small", "big", "two", "pair", "set"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t and t not in _STOP and len(t) > 2}


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


def _target(item: ObjectPlanItem) -> tuple[Vec3, str, str]:
    """(dimensions, mount, shape) for a plan item: its own type first, then its family."""
    sem = item.semantic_type
    builtin = _BUILTIN_BY_TYPE.get(sem)
    if sem in DEFAULT_DIMS:
        dims, mount = DEFAULT_DIMS[sem]
        shape = SHAPE_BY_TYPE.get(sem, "box")
    elif builtin is not None:
        dims, mount, shape = builtin.dimensions, builtin.mount, SHAPE_BY_TYPE.get(sem, builtin.shape)
    else:
        dims, mount, shape = vocab.FAMILY_DEFAULTS.get(item.family or "other", vocab.FAMILY_DEFAULTS["other"])
    if item.approx_dimensions:
        dims = tuple(item.approx_dimensions)  # type: ignore[assignment]
    if item.placement:
        mount = PLACEMENT_MOUNT.get(item.placement, mount)
    return dims, mount, shape


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


def _overrides(sem: str, hint: str, roles: dict[str, str], family: str = "") -> dict[str, str]:
    role = hint if hint in ("fabric", "wood", "metal", "glass") else (
        "fabric" if sem in _FABRIC else "wood" if sem in _WOOD else "metal" if sem in _METAL
        else _FAMILY_ROLE.get(family, "")
    )
    if role and role in roles:
        return {"primary": roles[role]}
    return {}


def _candidates(item: ObjectPlanItem) -> list[tuple[CatalogItem, float]]:
    """Registry models for the item: same type first; for open names, models
    whose name shares words with the item's name. Returns (item, name_overlap)."""
    models = [i for i in all_items() if i.model_url]
    same_type = [(i, 1.0) for i in models if i.semantic_type == item.semantic_type]
    if same_type and item.semantic_type != "other":
        return same_type
    want = _tokens(item.name) | _tokens(item.style_notes)
    by_name = []
    for i in models:
        have = _tokens(i.name) | _tokens(i.semantic_type.replace("_", " "))
        overlap = len(want & have)
        if overlap:
            by_name.append((i, overlap / max(1, len(want))))
    return same_type + by_name


def decide_asset(item: ObjectPlanItem, style: StyleSpec, *, roles: Optional[dict[str, str]] = None) -> AssetDecision:
    roles = roles if roles is not None else style_materials(style)
    target, mount, shape = _target(item)
    overrides = _overrides(item.semantic_type, item.material_hint, roles, item.family)
    base = dict(object_key=item.object_key, semantic_type=item.semantic_type, mount=mount, material_overrides=overrides)

    # ── rung 3 first for flat photo items: the crop is the look ──────────
    if item.crop_ref and item.semantic_type in TEXTURED_TYPES:
        return AssetDecision(
            **base, strategy="procedural", asset_id=None, asset_name=item.name or item.semantic_type,
            has_model=False, dimensions=target, color="#E8E2D8", shape=shape if item.semantic_type != "rug" else "box",
            texture_ref=item.crop_ref, reason="flat item textured with its photo crop",
        )

    # ── rungs 1–2: library ───────────────────────────────────────────────
    ranked = sorted(_candidates(item), key=lambda c: (_fit(c[0].dimensions, target) * (0.7 + 0.3 * c[1]), _style_overlap(c[0], style)), reverse=True)
    if ranked:
        best, overlap = ranked[0]
        fit = _fit(best.dimensions, target)
        by_name = best.semantic_type != item.semantic_type
        note = f" (matched by name '{best.name}')" if by_name else ""
        if fit >= LOCAL_FIT:
            return AssetDecision(
                **base, strategy="local_asset", asset_id=best.asset_id, asset_name=best.name, has_model=True,
                dimensions=best.dimensions, fit_score=round(fit, 3), color=best.color,
                reason=f"registry model within 15% of target size (fit {fit:.2f}){note}",
            )
        if fit >= MODIFIED_FIT:
            scale = tuple(max(SCALE_MIN, min(SCALE_MAX, t / h if h > 0 else 1.0)) for t, h in zip(target, best.dimensions))
            return AssetDecision(
                **base, strategy="local_modified", asset_id=best.asset_id, asset_name=best.name, has_model=True,
                dimensions=best.dimensions, scale=scale, fit_score=round(fit, 3), color=best.color,  # type: ignore[arg-type]
                reason=f"registry model scaled to target size (fit {fit:.2f}){note}",
            )

    builtin = _BUILTIN_BY_TYPE.get(item.semantic_type)
    stand_in_dims = target
    stand_in_color = builtin.color if builtin else "#8a7862"
    if item.semantic_type == "plant":
        stand_in_color = "#5f7a4f"

    # ── rung 5: generation for sculptural pieces with a crop ─────────────
    sculptural = item.unique or (item.family in SCULPTURAL_FAMILIES and item.crop_ref and not ranked)
    if sculptural and get_settings().meshy_configured:
        return AssetDecision(
            **base, strategy="generated", asset_id=builtin.asset_id if builtin else None,
            asset_name=builtin.name if builtin else (item.name or "generated stand-in"), has_model=False,
            dimensions=stand_in_dims, color=stand_in_color, shape=shape,
            generation_prompt=f"{style.name.replace('_', ' ')} {item.name or item.semantic_type.replace('_', ' ')}, {item.style_notes}".strip(", "),
            reference_image=item.crop_ref,
            reason="sculptural piece routed to image-to-3D; procedural stand-in until it validates",
        )

    # ── rung 4: parametric ───────────────────────────────────────────────
    if builtin and not item.approx_dimensions:
        stand_in_dims = builtin.dimensions
    why = "no registry model of this type; parametric built-in" if (builtin or item.semantic_type in DEFAULT_DIMS) else \
        f"open item '{item.name}' built from its family ({item.family or 'other'}) defaults"
    if ranked:
        why += " (best model fit too low)"
    if sculptural:
        why += "; candidate for image-to-3D once generation is enabled"
    return AssetDecision(
        **base, strategy="procedural", asset_id=builtin.asset_id if builtin else None,
        asset_name=builtin.name if builtin else (item.name or f"generic {item.semantic_type.replace('_', ' ')}"),
        has_model=False, dimensions=stand_in_dims, color=stand_in_color, shape=shape,
        texture_ref=item.crop_ref if item.semantic_type in ("pillows", "throw") else "",
        reference_image=item.crop_ref if sculptural else "",
        reason=why,
    )


def resolve_plan(plan: ObjectPlan, style: StyleSpec) -> AssetPlan:
    roles = style_materials(style)
    decisions = [decide_asset(item, style, roles=roles) for item in plan.items]
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.strategy] = counts.get(d.strategy, 0) + 1
        if d.texture_ref:
            counts["textured"] = counts.get("textured", 0) + 1
    warnings = [f"{d.object_key}: {d.reason}" for d in decisions if d.strategy == "procedural" and d.asset_id is None and not d.texture_ref]
    return AssetPlan(decisions=decisions, counts=counts, warnings=warnings)

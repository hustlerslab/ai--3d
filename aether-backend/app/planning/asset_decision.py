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

from ..assets.registry import get_registry
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


# One axis per type that must be allowed to disagree. Index 0 = width,
# 1 = height, 2 = depth.
#
# Worst-axis scoring treats every dimension as a constraint, which is wrong for
# the axis that is a style choice rather than a fit requirement. A picture frame
# hangs flat on the wall whether it is 1.6 cm or 3 cm thick; a bed occupies the
# same floor whether its headboard is low or tall. Measured: `ph_art_frame_01`
# matched its target's width and height to three decimals and was rejected at
# fit 0.523, purely for being 1.4 cm too thin, in favour of an untextured plane.
_SOFT_AXIS: dict[str, int] = {
    "wall_art": 2, "mirror": 2, "curtains": 2,   # thickness against a wall
    "bed": 1, "rug": 1,                          # height above the floor
}


def _fit(have: Vec3, want: Vec3, semantic_type: str = "") -> float:
    """Size agreement in 0..1 (plan §7: ±15 % per dimension).

    Worst-axis, except that the type's soft axis can only trim the score, never
    sink it: it scales the result across [0.85, 1.0] instead of competing in
    the minimum. A model that is wrong on a real axis still fails outright.
    """
    soft_index = _SOFT_AXIS.get(semantic_type)
    hard: list[float] = []
    soft = 1.0
    for axis, (h, w) in enumerate(zip(have, want)):
        if h <= 0 or w <= 0:
            continue
        ratio = min(h, w) / max(h, w)
        if axis == soft_index:
            soft = ratio
        else:
            hard.append(ratio)
    if not hard:
        return soft if soft_index is not None else 0.0
    return min(hard) * (0.85 + 0.15 * soft)


def _style_overlap(item: CatalogItem, style: StyleSpec) -> int:
    return len(set(item.style_tags) & set(style.tags))


# How much the style may move a candidate. Bounded deliberately: at 0.15 a
# perfect style match is worth 15 %, which settles a near-tie and cannot rescue
# a model that is the wrong size. Measured on the sample project, a Victorian
# Chesterfield was beating a modern sofa by 0.022 of dimensional fit in a room
# briefed `modern, warm, scandinavian` — style never entered the comparison
# because `_style_overlap` sat in the sort key's tiebreak position, which two
# different floats essentially never reach.
STYLE_WEIGHT = 0.15


def _style_score(item: CatalogItem, style: StyleSpec) -> float:
    """Tag agreement in 0..1, over the smaller of the two tag sets.

    Normalising by the smaller set means a catalog item with three tags is not
    punished for facing a style that lists five; what is asked is "do the tags
    this piece claims agree with the brief", not "does it cover the brief".
    """
    have, want = set(item.style_tags), set(style.tags)
    if not have or not want:
        return 0.0
    return len(have & want) / min(len(have), len(want))


# Types whose product photography routinely shows a pose the object never holds
# in a room, so the reading's bounding box is not the in-room form.
#
# Measured on the sample set: four mattresses shot in a showroom came back as
# (1.8, 0.25, 2.0) and (1.8, 2.0, 0.25) — the second is a mattress standing on
# its end, and the reading said so in its own name ("upright mattress with blue
# border"). Passed straight through, that became a 2 m tall, 20 cm thick slab
# leaning against the bedroom wall, and it also put the real bed model out of
# reach: `ph_classic_bed` is 1.53 m tall with its headboard and scored 0.16
# against a 0.25 m target.
#
# Only `bed` is re-posed. A sofa or a table photographed normally needs no help,
# and guessing a pose for every type would invent errors rather than fix them.
#
# `rug` is here on evidence, not suspicion: a sweep of every stored object plan
# found "layered area rug" read as (3.5, 2.5, 0.03) — 2.5 m of height and 3 cm
# of depth, i.e. the thickness landed in the depth slot and the length in the
# height slot. Same bug, different type.
#
# NOT included, and the sweep is why. `bookshelf` (1.1, 2.1, 0.5) and
# `floor_lamp` (0.3, 1.5, 0.3) also come back much taller than their footprint,
# but those are simply tall objects measured correctly. Re-posing them would lay
# a bookcase on its back. Height alone is not the signal — a near-zero third
# axis is.
#
# Still flagged, still unfixed, because no photo box has reached them in any
# stored plan (they arrive planner-added, `from_photo=False`): `curtains`
# (photographed folded), `mirror` (leaning), `pillows` (stacked).
_REPOSE_FROM_PHOTO = {"bed", "rug"}


def _in_room_dims(semantic_type: str, photo: Vec3, default: Vec3) -> Vec3:
    """The object's in-room box, given the box the reading measured in a photo.

    Drops the thinnest axis — that is the mattress's thickness or the rug's
    pile, wherever the photograph happened to put it — keeps the other two in
    the order they were given, and takes the height from the type's own default.

    Order matters: taking the two long sides as `(min, max)` would force every
    rug to be deeper than it is wide, silently rotating a correctly measured one
    by 90 degrees. A correctly measured object must come back unchanged, and
    with this rule it does: (1.6, 0.55, 2.05) in gives (1.6, 0.55, 2.05) out.
    """
    if semantic_type not in _REPOSE_FROM_PHOTO:
        return photo
    thinnest = min(range(3), key=lambda i: photo[i])
    width, depth = (v for i, v in enumerate(photo) if i != thinnest)
    return (width, default[1], depth)


def _score(candidate: CatalogItem, name_overlap: float, target: Vec3, semantic_type: str, style: StyleSpec) -> float:
    """Ranking score: dimensional fit first, then name, then style.

    `fit` is the veto — a candidate that is the wrong size cannot be talked up
    by the other two, because both are multipliers strictly below 1.
    """
    fit = _fit(candidate.dimensions, target, semantic_type)
    return fit * (0.7 + 0.3 * name_overlap) * ((1 - STYLE_WEIGHT) + STYLE_WEIGHT * _style_score(candidate, style))


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
        dims = _in_room_dims(sem, tuple(item.approx_dimensions), dims)  # type: ignore[arg-type]
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


def decide_asset(item: ObjectPlanItem, style: StyleSpec, *, roles: Optional[dict[str, str]] = None,
                 element_assets: Optional[dict[str, str]] = None) -> AssetDecision:
    roles = roles if roles is not None else style_materials(style)
    target, mount, shape = _target(item)
    overrides = _overrides(item.semantic_type, item.material_hint, roles, item.family)
    base = dict(object_key=item.object_key, semantic_type=item.semantic_type, mount=mount, material_overrides=overrides)

    # ── rung 0: the mesh made from THIS piece's own crop ─────────────────
    # Above the library on purpose. The client approved a picture; a mesh built
    # from the very piece in that picture is a better answer than the nearest
    # catalog item by size, even when the catalog item fits better. Everything
    # below this line is a substitute for the thing the client actually chose.
    made = (element_assets or {}).get(item.element_id) if item.element_id else None
    if made:
        # The asset's OWN measured size, exactly as rungs 1-2 do for library
        # models - not the planned target. The ingester normalizes a mesh to fit
        # inside the target while keeping its proportions, so the two differ
        # whenever the generated piece is not the shape the vocabulary assumed.
        # Publishing the target instead made every renderer rescale by the
        # smallest axis ratio to fit: the rug drew at 29 % of its size and the
        # mirror at 6 %, which read as an almost empty room.
        real = get_registry().get(made)
        dims = tuple(real.dimensions) if (real and all(d > 1e-6 for d in real.dimensions)) else target
        return AssetDecision(
            **base, strategy="generated", asset_id=made, asset_name=item.name or item.semantic_type,
            has_model=True, dimensions=dims,          # type: ignore[arg-type]
            color=item.color_hint or "#C9C3B8",
            reason="generated from this element's own crop in the approved render",
        )

    # ── rung 3 first for flat photo items: the crop is the look ──────────
    if item.crop_ref and item.semantic_type in TEXTURED_TYPES:
        return AssetDecision(
            **base, strategy="procedural", asset_id=None, asset_name=item.name or item.semantic_type,
            has_model=False, dimensions=target, color="#E8E2D8", shape=shape if item.semantic_type != "rug" else "box",
            texture_ref=item.crop_ref, reason="flat item textured with its photo crop",
        )

    # ── rungs 1–2: library ───────────────────────────────────────────────
    ranked = sorted(_candidates(item), key=lambda c: _score(c[0], c[1], target, item.semantic_type, style), reverse=True)
    if ranked:
        best, overlap = ranked[0]
        fit = _fit(best.dimensions, target, item.semantic_type)
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


def resolve_plan(plan: ObjectPlan, style: StyleSpec,
                 element_assets: Optional[dict[str, str]] = None) -> AssetPlan:
    roles = style_materials(style)
    decisions = [decide_asset(item, style, roles=roles, element_assets=element_assets)
                 for item in plan.items]
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.strategy] = counts.get(d.strategy, 0) + 1
        if d.texture_ref:
            counts["textured"] = counts.get("textured", 0) + 1
    warnings = [f"{d.object_key}: {d.reason}" for d in decisions if d.strategy == "procedural" and d.asset_id is None and not d.texture_ref]
    return AssetPlan(decisions=decisions, counts=counts, warnings=warnings)

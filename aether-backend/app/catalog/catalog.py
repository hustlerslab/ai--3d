"""Furniture catalog — built-in parametric items merged with the asset registry.

Two tiers share one record shape (plan §17):
  - built-in items: dimensions + colour only; the frontend renders a
    parametric shape. Always available, never photoreal.
  - registry items: real, normalized GLB models with provenance. When one
    exists for a semantic type it is preferred everywhere (design planner,
    search ranking) — retrieval before generation (plan §50).

Ranking is hard-filter first, then a weighted score.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..assets.registry import get_registry
from ..assets.schema import AssetRecord
from ..scene.schema import Vec3


class CatalogItem(BaseModel):
    asset_id: str
    semantic_type: str
    name: str
    dimensions: Vec3
    color: str
    style_tags: list[str] = []
    material_tags: list[str] = []
    room_types: list[str] = []
    price_inr: int = 0
    shape: str = "box"          # renderer hint for parametric fallback
    mount: str = "floor"        # floor | ceiling | wall
    model_url: Optional[str] = None      # normalized GLB, served by this API
    thumbnail_url: Optional[str] = None
    source: str = "builtin"     # builtin | polyhaven | upload | meshy
    license: str = "n/a"


BUILTIN: list[CatalogItem] = [
    CatalogItem(asset_id="cat_sofa_3s", semantic_type="sofa", name="3-Seater Sofa",
                dimensions=(2.1, 0.85, 0.9), color="#b7a186", style_tags=["modern", "warm_neutral"],
                room_types=["living_room"], price_inr=48000, shape="seat"),
    CatalogItem(asset_id="cat_sofa_2s", semantic_type="loveseat", name="2-Seater Sofa",
                dimensions=(1.5, 0.85, 0.9), color="#a89275", style_tags=["modern"],
                room_types=["living_room"], price_inr=34000, shape="seat"),
    CatalogItem(asset_id="cat_armchair", semantic_type="armchair", name="Armchair",
                dimensions=(0.8, 0.8, 0.85), color="#8f7757", style_tags=["modern", "indian"],
                room_types=["living_room", "bedroom"], price_inr=15000, shape="seat"),
    CatalogItem(asset_id="cat_coffee_table", semantic_type="coffee_table", name="Coffee Table",
                dimensions=(1.1, 0.42, 0.6), color="#6b4f35", style_tags=["wood", "modern"],
                room_types=["living_room"], price_inr=9500, shape="table"),
    CatalogItem(asset_id="cat_tv_unit", semantic_type="tv_unit", name="TV Unit",
                dimensions=(1.8, 0.5, 0.45), color="#4a3826", style_tags=["wood"],
                room_types=["living_room"], price_inr=22000, shape="box"),
    CatalogItem(asset_id="cat_dining_table", semantic_type="dining_table", name="Dining Table",
                dimensions=(1.6, 0.75, 0.9), color="#5d452e", style_tags=["wood"],
                room_types=["dining_room", "living_room"], price_inr=28000, shape="table"),
    CatalogItem(asset_id="cat_chair", semantic_type="chair", name="Dining Chair",
                dimensions=(0.45, 0.9, 0.5), color="#7a6248", style_tags=["wood"],
                room_types=["dining_room"], price_inr=4500, shape="seat"),
    CatalogItem(asset_id="cat_bed_queen", semantic_type="bed", name="Queen Bed",
                dimensions=(1.6, 0.55, 2.05), color="#9c8468", style_tags=["modern"],
                room_types=["bedroom"], price_inr=42000, shape="box"),
    CatalogItem(asset_id="cat_wardrobe", semantic_type="wardrobe", name="Wardrobe",
                dimensions=(1.5, 2.1, 0.6), color="#5a4632", style_tags=["wood"],
                room_types=["bedroom"], price_inr=35000, shape="tall"),
    CatalogItem(asset_id="cat_bedside", semantic_type="bedside_table", name="Bedside Table",
                dimensions=(0.45, 0.55, 0.4), color="#6b4f35", style_tags=["wood"],
                room_types=["bedroom"], price_inr=6000, shape="box"),
    CatalogItem(asset_id="cat_bookshelf", semantic_type="bookshelf", name="Bookshelf",
                dimensions=(0.9, 1.8, 0.35), color="#4a3826", style_tags=["wood"],
                room_types=["living_room", "bedroom"], price_inr=12000, shape="tall"),
    CatalogItem(asset_id="cat_rug", semantic_type="rug", name="Area Rug",
                dimensions=(2.4, 0.02, 1.7), color="#c9b299", style_tags=["warm_neutral", "indian"],
                room_types=["living_room", "bedroom"], price_inr=8000, shape="box"),
    CatalogItem(asset_id="cat_floor_lamp", semantic_type="floor_lamp", name="Floor Lamp",
                dimensions=(0.35, 1.6, 0.35), color="#d9c39a", style_tags=["modern"],
                room_types=["living_room", "bedroom"], price_inr=5500, shape="tall"),
    CatalogItem(asset_id="cat_plant", semantic_type="plant", name="Potted Plant",
                dimensions=(0.45, 1.2, 0.45), color="#5f7a4f", style_tags=["natural"],
                room_types=["living_room", "bedroom", "dining_room"], price_inr=2500, shape="tall"),

    # ── hospitality ──────────────────────────────────────────────────────
    CatalogItem(asset_id="cat_restaurant_table", semantic_type="restaurant_table", name="Restaurant Table for Four",
                dimensions=(0.9, 0.75, 0.9), color="#5d452e", style_tags=["wood", "brasserie"],
                room_types=["restaurant_floor", "cafe_floor", "bar", "banquet_hall"], price_inr=16000, shape="table"),
    CatalogItem(asset_id="cat_banquette", semantic_type="banquette", name="Wall Banquette (2 m run)",
                dimensions=(2.0, 1.1, 0.65), color="#7d4b42", style_tags=["brasserie", "warm"],
                room_types=["restaurant_floor", "cafe_floor", "bar"], price_inr=52000, shape="seat"),
    CatalogItem(asset_id="cat_booth", semantic_type="booth_seating", name="Dining Booth",
                dimensions=(1.6, 1.25, 1.8), color="#6b4a3a", style_tags=["brasserie", "moody"],
                room_types=["restaurant_floor", "bar"], price_inr=78000, shape="seat"),
    CatalogItem(asset_id="cat_bar_counter", semantic_type="bar_counter", name="Bar Counter (3 m run)",
                dimensions=(3.0, 1.1, 0.7), color="#3f342c", style_tags=["moody", "boutique_hotel"],
                room_types=["bar", "cafe_floor", "hotel_lobby"], price_inr=145000, shape="counter"),
    CatalogItem(asset_id="cat_lounge_sofa", semantic_type="lounge_sofa", name="Lobby Lounge Sofa",
                dimensions=(2.4, 0.78, 0.95), color="#8a7a63", style_tags=["boutique_hotel", "luxury"],
                room_types=["hotel_lobby", "suite", "breakout", "reception"], price_inr=96000, shape="seat"),
    CatalogItem(asset_id="cat_reception_desk", semantic_type="reception_desk", name="Reception Desk",
                dimensions=(2.6, 1.1, 0.8), color="#4a3826", style_tags=["boutique_hotel", "modern"],
                room_types=["reception", "hotel_lobby"], price_inr=120000, shape="counter"),

    # ── industrial (loft-style offices) ──────────────────────────────────
    CatalogItem(asset_id="cat_workstation", semantic_type="workstation", name="Bench Workstation",
                dimensions=(1.6, 0.74, 0.8), color="#6b6560", style_tags=["industrial", "modern"],
                room_types=["open_plan_office", "private_office"], price_inr=24000, shape="table"),
    CatalogItem(asset_id="cat_office_chair", semantic_type="office_chair", name="Task Chair",
                dimensions=(0.65, 1.05, 0.65), color="#3d3a37", style_tags=["industrial", "modern"],
                room_types=["open_plan_office", "private_office", "meeting_room", "reception"], price_inr=18000, shape="seat"),
    CatalogItem(asset_id="cat_meeting_table", semantic_type="meeting_table", name="Meeting Table for Eight",
                dimensions=(2.4, 0.75, 1.1), color="#5a4632", style_tags=["industrial", "wood"],
                room_types=["meeting_room", "private_office"], price_inr=68000, shape="table"),
]

# Kept for callers that only need the built-in vocabulary.
CATALOG = BUILTIN


def _from_record(record: AssetRecord) -> CatalogItem:
    return CatalogItem(
        asset_id=record.asset_id,
        semantic_type=record.semantic_type,
        name=record.name,
        dimensions=record.dimensions,
        color=record.color,
        style_tags=record.style_tags,
        material_tags=record.material_tags,
        room_types=record.room_types,
        price_inr=record.price_inr,
        shape="model",
        mount=record.mount,
        model_url=f"/files/assets/{record.asset_id}.glb",
        thumbnail_url=record.source.thumbnail_url or None,
        source=record.source.provider,
        license=record.source.license,
    )


def all_items() -> list[CatalogItem]:
    """Real models first, then built-ins."""
    real = [_from_record(r) for r in get_registry().list() if r.valid]
    return real + BUILTIN


def semantic_types() -> list[str]:
    return sorted({i.semantic_type for i in all_items()})


def get_item(asset_id: str) -> CatalogItem | None:
    return next((i for i in all_items() if i.asset_id == asset_id), None)


def find_by_semantic(semantic_type: str, style_tags: list[str] | None = None) -> CatalogItem | None:
    """Best item for a semantic type: a real model beats a primitive; among
    real models, the one with the most style overlap."""
    candidates = [i for i in all_items() if i.semantic_type == semantic_type]
    if not candidates:
        return None
    wanted = set(style_tags or [])
    return max(
        candidates,
        key=lambda i: (i.model_url is not None, len(wanted & set(i.style_tags))),
    )


def _dimension_fit(item: CatalogItem, target: Vec3 | None) -> float:
    if not target:
        return 0.5
    ratios = []
    for have, want in zip(item.dimensions, target):
        if want <= 0:
            continue
        ratios.append(min(have, want) / max(have, want))
    return sum(ratios) / len(ratios) if ratios else 0.5


def search(
    query: str = "",
    room_type: str | None = None,
    max_width: float | None = None,
    max_price: int | None = None,
    style_tags: list[str] | None = None,
    target_dimensions: Vec3 | None = None,
    require_model: bool = False,
) -> list[CatalogItem]:
    """Hard filters, then weighted ranking (plan §17):
    semantic → style → dimension fit → budget → availability."""
    results = all_items()
    if room_type:
        results = [i for i in results if room_type in i.room_types]
    if max_width is not None:
        results = [i for i in results if i.dimensions[0] <= max_width]
    if max_price is not None:
        results = [i for i in results if i.price_inr <= max_price]
    if require_model:
        results = [i for i in results if i.model_url]

    q = query.lower().strip()
    wanted = set(style_tags or [])
    scored: list[tuple[float, CatalogItem]] = []
    for item in results:
        score = 0.0
        if q:
            if q == item.semantic_type.lower() or q == item.name.lower():
                score += 3.0
            elif q in item.semantic_type.lower() or q in item.name.lower():
                score += 2.0
            score += sum(0.5 for t in item.style_tags + item.material_tags if t in q or q in t)
            if score == 0:
                continue
        if wanted:
            score += 1.5 * len(wanted & set(item.style_tags)) / len(wanted)
        score += 2.0 * _dimension_fit(item, target_dimensions)
        if max_price:
            score += 0.5 * (1 - item.price_inr / max_price)
        if item.model_url:
            score += 1.5
        scored.append((score, item))
    scored.sort(key=lambda s: -s[0])
    return [i for _, i in scored]

"""Gemini design provider adapter.

The only place the Gemini key is unwrapped. When no key is configured (or a
call fails and fallback is enabled), callers use the deterministic mock
planner in design.service instead — AI failure must degrade gracefully
(system design §29).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from ..core.config import get_settings

log = logging.getLogger("aether.providers.gemini")

PROPOSAL_SCHEMA_HINT = """
Respond ONLY with JSON matching:
{
  "summary": "one sentence describing the design direction",
  "operations": [
    {"op": "add", "semantic_type": "<catalog semantic type>", "room_id": "<room id>"},
    {"op": "remove", "object_id": "<object id>"},
    {"op": "move", "object_id": "<object id>", "relation": {"type": "near|in_front_of|against_wall", "target_id": "<object or wall id>"}}
  ]
}
Available semantic types: sofa, loveseat, armchair, coffee_table, tv_unit,
dining_table, chair, bed, wardrobe, bedside_table, bookshelf, rug,
floor_lamp, plant.
Never invent coordinates. Never propose removing a locked object.
"""


async def propose(context: dict[str, Any], instruction: str) -> Optional[dict[str, Any]]:
    """Ask Gemini for a structured proposal. Returns None when unavailable
    or the response cannot be parsed — the caller falls back to the mock."""
    settings = get_settings()
    if not settings.gemini_configured:
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    prompt = (
        "You are an interior design planner. Scene context (JSON):\n"
        + json.dumps(context)
        + "\n\nUser instruction: "
        + instruction
        + "\n"
        + PROPOSAL_SCHEMA_HINT
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
            response = await client.post(
                url,
                params={"key": settings.gemini_api_key.get_secret_value()},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        if not isinstance(parsed.get("operations"), list):
            return None
        return parsed
    except Exception as exc:  # network, quota, schema — all degrade to mock
        log.warning("Gemini proposal failed, falling back to mock: %s", exc)
        return None


def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": "gemini",
        "configured": settings.gemini_configured,
        "model": settings.gemini_model,
        "mode": "live" if settings.gemini_configured else "mock",
    }

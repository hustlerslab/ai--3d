"""Gemini vision provider: one structured call per stage (DPR §27).

Each call sends a stage-specific prompt, the reference photos inline, and a
response schema so Gemini returns JSON. The JSON is validated into the
Pydantic contract; unknown material ids or room types are coerced or
dropped with a warning rather than failing the stage. One repair retry is
attempted when the first response is not valid JSON.

Google retires model ids often, so a 404 ("no longer available"), 429 or
503 on the configured model moves to the next entry of GEMINI_FALLBACK_MODELS
and the working model is remembered for the process.
"""
from __future__ import annotations

from pathlib import Path

import json
import logging
from typing import Any, Optional

import httpx

from ..core.config import Settings, get_settings
from ..materials.registry import get_material_registry
from . import vocab
from .coerce import coerce_analysis, coerce_object_plan, coerce_style
from .images import encode_for_gemini
from .prompts import (
    ELEMENT_CHECK_SCHEMA,
    ELEMENT_DIMENSIONS_SCHEMA,
    element_dimensions_prompt,
    element_check_prompt,
    OBJECT_PLAN_SCHEMA,
    analysis_prompt,
    analysis_schema,
    gemini_schema,
    objects_prompt,
    style_prompt,
    style_schema,
    ROOM_PROMPT_SCHEMA,
    room_prompt_request,
    SCENE_READING_SCHEMA,
    scene_reading_prompt,
)
from .schema import DesignAnalysis, InputBundle, ObjectPlan, StyleSpec

log = logging.getLogger("aether.intelligence.gemini")


class GeminiError(Exception):
    pass


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.BaseTransport] = None):
        self._settings = settings or get_settings()
        if not self._settings.gemini_configured:
            raise GeminiError("GEMINI_API_KEY is not configured")
        self._client = httpx.Client(timeout=self._settings.gemini_timeout_seconds, transport=transport)
        self.models: list[str] = [self._settings.gemini_model] + [
            m.strip() for m in self._settings.gemini_fallback_models.split(",") if m.strip() and m.strip() != self._settings.gemini_model
        ]
        self.model = self.models[0]

    @property
    def label(self) -> str:
        return f"gemini:{self.model}"

    def _url(self, model: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    # ── transport ────────────────────────────────────────────────────────
    def _generate(self, parts: list[dict[str, Any]], schema: dict[str, Any], stage: str) -> dict[str, Any]:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": gemini_schema(schema),
                "temperature": 0.2,
            },
        }
        text = self._call(body, stage)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Gemini %s returned invalid JSON (%s); asking for a repair", stage, exc)
            repair = {
                "contents": [
                    {"role": "user", "parts": parts},
                    {"role": "model", "parts": [{"text": text}]},
                    {"role": "user", "parts": [{"text": "That was not valid JSON. Return ONLY the corrected JSON object."}]},
                ],
                "generationConfig": body["generationConfig"],
            }
            text = self._call(repair, stage + ".repair")
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc2:
                raise GeminiError(f"{stage}: response is not JSON after repair: {exc2}") from exc2

    def _call(self, body: dict[str, Any], stage: str) -> str:
        """POST to the current model; on a retired/overloaded model move down the fallback list."""
        start = self.models.index(self.model) if self.model in self.models else 0
        last_error: Optional[str] = None
        for model in self.models[start:]:
            try:
                response = self._client.post(
                    self._url(model),
                    params={"key": self._settings.gemini_api_key.get_secret_value()},
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise GeminiError(f"{stage}: network error: {exc}") from exc
            if response.status_code in (404, 429, 503):
                last_error = f"HTTP {response.status_code} on {model}: {response.text[:160].replace(chr(10), ' ')}"
                log.warning("Gemini %s: %s; trying the next model", stage, last_error)
                continue
            if response.status_code >= 400:
                detail = response.text[:300].replace("\n", " ")
                raise GeminiError(f"{stage}: HTTP {response.status_code} on {model}: {detail}")
            if model != self.model:
                log.info("Gemini: switched to %s", model)
                self.model = model
            try:
                payload = response.json()
                candidate = payload["candidates"][0]
                if candidate.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
                    raise GeminiError(f"{stage}: blocked ({candidate.get('finishReason')})")
                return candidate["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError) as exc:
                raise GeminiError(f"{stage}: unexpected response shape: {exc}") from exc
        raise GeminiError(f"{stage}: every configured model failed; last: {last_error}")

    def _image_parts(self, bundle: InputBundle, limit: int = 6) -> tuple[list[dict[str, Any]], list[str]]:
        parts: list[dict[str, Any]] = []
        warnings: list[str] = []
        for ref in bundle.references[:limit]:
            encoded = encode_for_gemini(ref.path, max_side=1024)
            if encoded is None:
                warnings.append(f"could not encode {ref.filename or ref.path} for Gemini")
                continue
            mime, data = encoded
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
        if len(bundle.references) > limit:
            warnings.append(f"only the first {limit} of {len(bundle.references)} references were sent to Gemini")
        return parts, warnings

    # ── stages ───────────────────────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        images, warnings = self._image_parts(bundle)
        parts = [{"text": analysis_prompt(bundle)}, *images]
        if images:
            parts.append({"text": f"{len(images)} reference photo(s) attached above."})
        raw = self._generate(parts, analysis_schema(bundle.vertical), "analyze_input")
        return coerce_analysis(raw, bundle, warnings, provider=self.label)

    # NOT part of IntelligenceProvider. The Protocol is pinned to three methods
    # and a vendor implementing only those must keep working (ADR-001), so this
    # is an optional capability discovered with hasattr; providers without it
    # fall back to the keyword template.
    # Also NOT on the Protocol (ADR-001 pins it to three methods).
    def read_scene_elements(self, image: "Path", room, style: StyleSpec, vertical) -> dict:
        """Box every piece in ONE rendered room image, plus its surfaces."""
        encoded = encode_for_gemini(str(image), max_side=1024)
        if encoded is None:
            raise ValueError(f"could not encode {image} for Gemini")
        mime, data = encoded
        parts = [
            {"text": scene_reading_prompt(room, style, vertical)},
            {"inline_data": {"mime_type": mime, "data": data}},
            {"text": "The rendered room is attached above."},
        ]
        return self._generate(parts, gemini_schema(SCENE_READING_SCHEMA), "read_scene_elements")

    def check_element_crop(self, crop: "Path", room_type: str, vertical) -> dict:
        """Look at ONE crop alone and say what it is. No label, no scene."""
        encoded = encode_for_gemini(str(crop), max_side=512)
        if encoded is None:
            raise ValueError(f"could not encode {crop} for Gemini")
        mime, data = encoded
        parts = [
            {"text": element_check_prompt(room_type, vertical)},
            {"inline_data": {"mime_type": mime, "data": data}},
        ]
        return self._generate(parts, gemini_schema(ELEMENT_CHECK_SCHEMA), "check_element_crop")

    def estimate_element_dimensions(self, room, elements, vertical) -> dict:
        """How big each piece really is, in metres. One call for the room."""
        return self._generate(
            [{"text": element_dimensions_prompt(room, elements, vertical)}],
            gemini_schema(ELEMENT_DIMENSIONS_SCHEMA), "estimate_element_dimensions",
        )

    def compose_scene_prompt(self, analysis: DesignAnalysis, style: StyleSpec,
                             bundle: InputBundle, room) -> str:
        raw = self._generate(
            [{"text": room_prompt_request(analysis, style, bundle, room)}],
            ROOM_PROMPT_SCHEMA, "compose_scene_prompt",
        )
        return str(raw.get("prompt") or "").strip()

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        images, warnings = self._image_parts(bundle)
        raw = self._generate(
            [{"text": style_prompt(analysis, bundle, catalog)}, *images],
            style_schema(bundle.vertical),
            "create_style_spec",
        )
        return coerce_style(raw, {m.material_id for m in materials}, warnings, provider=self.label, vertical=bundle.vertical)

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        # The planner sees the asset library so its own additions favour pieces
        # backed by a real model; without it every addition is a coin flip
        # between furniture and a coloured box.
        from ..catalog.catalog import planning_summary

        catalog = planning_summary([r.type for r in analysis.rooms])
        raw = self._generate(
            [{"text": objects_prompt(analysis, style, bundle, catalog)}], OBJECT_PLAN_SCHEMA, "plan_objects"
        )
        return coerce_object_plan(raw, analysis, provider=self.label)


__all__ = ["GeminiError", "GeminiProvider", "vocab"]

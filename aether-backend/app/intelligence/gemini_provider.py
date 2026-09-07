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
    ANALYSIS_SCHEMA,
    OBJECT_PLAN_SCHEMA,
    STYLE_SCHEMA,
    analysis_prompt,
    gemini_schema,
    objects_prompt,
    style_prompt,
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
        raw = self._generate(parts, ANALYSIS_SCHEMA, "analyze_input")
        return coerce_analysis(raw, bundle, warnings, provider=self.label)

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        images, warnings = self._image_parts(bundle)
        raw = self._generate([{"text": style_prompt(analysis, bundle, catalog)}, *images], STYLE_SCHEMA, "create_style_spec")
        return coerce_style(raw, {m.material_id for m in materials}, warnings, provider=self.label)

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        raw = self._generate([{"text": objects_prompt(analysis, style, bundle)}], OBJECT_PLAN_SCHEMA, "plan_objects")
        return coerce_object_plan(raw, analysis, provider=self.label)


__all__ = ["GeminiError", "GeminiProvider", "vocab"]

"""Claude vision provider (Anthropic SDK): the same three stages as Gemini.

Structured outputs (`output_config.format`) return schema-valid JSON, so no
repair loop is needed. Effort is kept low: these are extraction tasks and
latency matters more than depth.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import anthropic

from ..core.config import Settings, get_settings
from ..materials.registry import get_material_registry
from .coerce import coerce_analysis, coerce_object_plan, coerce_style
from .images import encode_for_gemini
from .prompts import (
    ANALYSIS_SCHEMA,
    OBJECT_PLAN_SCHEMA,
    STYLE_SCHEMA,
    analysis_prompt,
    objects_prompt,
    style_prompt,
)
from .schema import DesignAnalysis, InputBundle, ObjectPlan, StyleSpec

log = logging.getLogger("aether.intelligence.anthropic")


class AnthropicError(Exception):
    pass


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[anthropic.Anthropic] = None):
        self._settings = settings or get_settings()
        if client is None and not self._settings.anthropic_configured:
            raise AnthropicError("ANTHROPIC_API_KEY is not configured")
        self.model = self._settings.anthropic_model
        self._client = client or anthropic.Anthropic(
            api_key=self._settings.anthropic_api_key.get_secret_value(),
            timeout=float(self._settings.anthropic_timeout_seconds),
            max_retries=2,
        )

    @property
    def label(self) -> str:
        return f"anthropic:{self.model}"

    # ── transport ────────────────────────────────────────────────────────
    def _generate(self, content: list[dict[str, Any]], schema: dict[str, Any], stage: str) -> dict[str, Any]:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=(
                    "You are a precise interior-design analysis service. Answer only with the JSON "
                    "the schema asks for; no prose."
                ),
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "low"},
            )
        except anthropic.AuthenticationError as exc:
            raise AnthropicError(f"{stage}: invalid ANTHROPIC_API_KEY") from exc
        except anthropic.NotFoundError as exc:
            raise AnthropicError(f"{stage}: model {self.model} not found") from exc
        except anthropic.RateLimitError as exc:
            raise AnthropicError(f"{stage}: rate limited") from exc
        except anthropic.APIStatusError as exc:
            raise AnthropicError(f"{stage}: HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AnthropicError(f"{stage}: network error: {exc}") from exc
        if response.stop_reason == "refusal":
            raise AnthropicError(f"{stage}: the model declined the request")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnthropicError(f"{stage}: response is not JSON: {exc}") from exc

    def _image_blocks(self, bundle: InputBundle, limit: int = 6) -> tuple[list[dict[str, Any]], list[str]]:
        blocks: list[dict[str, Any]] = []
        warnings: list[str] = []
        for ref in bundle.references[:limit]:
            encoded = encode_for_gemini(ref.path, max_side=1024)
            if encoded is None:
                warnings.append(f"could not encode {ref.filename or ref.path} for Claude")
                continue
            mime, data = encoded
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
        if len(bundle.references) > limit:
            warnings.append(f"only the first {limit} of {len(bundle.references)} references were sent to Claude")
        return blocks, warnings

    # ── stages ───────────────────────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        images, warnings = self._image_blocks(bundle)
        content = [*images, {"type": "text", "text": analysis_prompt(bundle)}]
        raw = self._generate(content, ANALYSIS_SCHEMA, "analyze_input")
        return coerce_analysis(raw, bundle, warnings, provider=self.label)

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        images, warnings = self._image_blocks(bundle)
        content = [*images, {"type": "text", "text": style_prompt(analysis, bundle, catalog)}]
        raw = self._generate(content, STYLE_SCHEMA, "create_style_spec")
        return coerce_style(raw, {m.material_id for m in materials}, warnings, provider=self.label)

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        raw = self._generate([{"type": "text", "text": objects_prompt(analysis, style, bundle)}], OBJECT_PLAN_SCHEMA, "plan_objects")
        return coerce_object_plan(raw, analysis, provider=self.label)

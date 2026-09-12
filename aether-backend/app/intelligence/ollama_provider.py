"""Ollama provider — the reasoning stages on a local model, no API key.

Implements the same IntelligenceProvider Protocol as Gemini and Claude, so
selecting it is one env var (INTELLIGENCE_PROVIDER=ollama) and nothing else in
the pipeline changes. Output goes through the same coerce_* functions, so a
weaker model degrades into a poorer plan rather than a broken one.

Two things differ from the cloud providers, and both matter:

1. This model runs on the SAME GPU as Blender. The job runner reroutes the
   stages that call it onto the render lane when a local provider is selected,
   so an analysis and a render never contend for the 6 GB — see
   JobRunner._lane_for.
2. Ollama constrains output with a JSON Schema passed as `format`, not with a
   vendor-specific responseSchema. The schemas here are the same plain JSON
   Schema the other providers use, minus `additionalProperties`, which some
   Ollama builds reject.

API shape (Ollama 0.34):
  POST /api/chat {model, messages:[{role, content, images:[<base64>]}],
                  format:<json schema>, stream:false,
                  options:{temperature, num_ctx}}
    → {"message":{"content":"<json text>"}, "done":true, ...}
"""
from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

from ..core.config import Settings, get_settings
from ..materials.registry import get_material_registry
from .coerce import coerce_analysis, coerce_object_plan, coerce_style
from .prompts import (
    OBJECT_PLAN_SCHEMA,
    analysis_prompt,
    analysis_schema,
    objects_prompt,
    style_prompt,
    style_schema,
)
from .schema import DesignAnalysis, InputBundle, ObjectPlan, StyleSpec

log = logging.getLogger("aether.intelligence.ollama")


class OllamaError(Exception):
    pass


def _plain_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip `additionalProperties`, which some Ollama builds reject."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "properties":
            out[key] = {k: _plain_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _plain_schema(value)
        else:
            out[key] = value
    return out


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.BaseTransport] = None):
        self._settings = settings or get_settings()
        self.model = self._settings.ollama_model
        self._client = httpx.Client(
            base_url=self._settings.ollama_base_url.rstrip("/"),
            timeout=self._settings.ollama_timeout_seconds,
            transport=transport,
        )

    @property
    def label(self) -> str:
        return f"ollama:{self.model}"

    # ── transport ────────────────────────────────────────────────────────
    def _encode(self, path: Path, max_px: int) -> str:
        """Downscale, then base64.

        This is what makes a multi-photo read possible at all. qwen2.5-VL bills
        context by pixel area, so full-size uploads are ruinous: measured on the
        sample set, eight photos cost ~12.7k tokens at 512 px, ~6.5k image
        tokens at 768 px and ~11.6k at 1024 px — and sending four originals
        crashed llama-server outright with a stack overrun rather than
        returning an error. 512 px keeps all eight inside a 16k window with
        room for the prompt, and is still ample to tell a sofa from a mattress.
        Originals on disk are untouched; this resizes in memory only.
        """
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    def _images(self, bundle: InputBundle, limit: int) -> tuple[list[str], list[str]]:
        """Reference photos as downscaled base64, plus warnings for any that
        would not read."""
        out: list[str] = []
        warnings: list[str] = []
        max_px = self._settings.ollama_image_max_px
        for ref in bundle.references[:limit]:
            try:
                out.append(self._encode(Path(ref.path), max_px))
            except (OSError, ValueError) as exc:
                warnings.append(f"could not read {ref.filename or ref.path}: {exc}")
        if len(bundle.references) > limit:
            warnings.append(
                f"{len(bundle.references)} photos supplied; the local model was sent the first {limit}"
            )
        return out, warnings

    def _generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        body = {
            "model": self.model,
            "messages": [message],
            "format": _plain_schema(schema),
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": self._settings.ollama_num_ctx,
                # Without this the answer is cut off mid-string and the whole
                # call is wasted on a JSONDecodeError.
                "num_predict": self._settings.ollama_num_predict,
            },
        }
        try:
            resp = self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise OllamaError(f"{stage}: cannot reach Ollama at {self._client.base_url} ({exc})") from exc
        if resp.status_code == 404:
            raise OllamaError(
                f"{stage}: model '{self.model}' is not pulled. Run: ollama pull {self.model}"
            )
        if resp.status_code >= 400:
            raise OllamaError(f"{stage}: HTTP {resp.status_code} {resp.text[:200]}")

        text = ((resp.json().get("message") or {}).get("content") or "").strip()
        if not text:
            raise OllamaError(f"{stage}: empty response from {self.model}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # `format` should guarantee JSON, but a small model can still emit a
            # fenced block or trailing prose. Salvage the object rather than
            # throwing away a whole GPU-minute of work.
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise OllamaError(f"{stage}: response is not JSON ({exc})") from exc

    # ── the Protocol ─────────────────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        images, warnings = self._images(bundle, self._settings.ollama_max_images)
        prompt = analysis_prompt(bundle)
        if images:
            prompt += f"\n\n{len(images)} reference photo(s) are attached."
        raw = self._generate(prompt, analysis_schema(bundle.vertical), "analyze_input", images)
        return coerce_analysis(raw, bundle, warnings, provider=self.label)

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        images, warnings = self._images(bundle, self._settings.ollama_max_images)
        raw = self._generate(
            style_prompt(analysis, bundle, catalog), style_schema(bundle.vertical), "create_style_spec", images
        )
        return coerce_style(
            raw, {m.material_id for m in materials}, warnings, provider=self.label, vertical=bundle.vertical
        )

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        from ..catalog.catalog import planning_summary

        catalog = planning_summary([r.type for r in analysis.rooms])
        raw = self._generate(
            objects_prompt(analysis, style, bundle, catalog), OBJECT_PLAN_SCHEMA, "plan_objects"
        )
        return coerce_object_plan(raw, analysis, provider=self.label)


__all__ = ["OllamaError", "OllamaProvider"]

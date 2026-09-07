"""Provider selection, Gemini model fallback, Claude provider with a stubbed client."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.intelligence import InputBundle, get_provider, reset_provider
from app.intelligence.anthropic_provider import AnthropicProvider
from app.intelligence.gemini_provider import GeminiError, GeminiProvider
from app.intelligence.prompts import ANALYSIS_SCHEMA, gemini_schema
from tests.test_intelligence import ANALYSIS_OK, BRIEF, _gemini_payload


def _settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.core import config

    config.get_settings.cache_clear()
    return config.get_settings()


def test_gemini_schema_conversion():
    g = gemini_schema(ANALYSIS_SCHEMA)
    assert g["type"] == "OBJECT" and "additionalProperties" not in g
    assert g["properties"]["rooms"]["type"] == "ARRAY"
    assert g["properties"]["rooms"]["items"]["properties"]["type"]["enum"]


def test_gemini_falls_through_retired_models(env, monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = request.url.path.split("/models/")[1].split(":")[0]
        calls.append(model)
        if model == "dead-model":
            return httpx.Response(404, json={"error": {"message": "no longer available"}})
        if model == "busy-model":
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json=_gemini_payload(ANALYSIS_OK))

    settings = _settings(monkeypatch, GEMINI_API_KEY="k", GEMINI_MODEL="dead-model", GEMINI_FALLBACK_MODELS="busy-model,good-model")
    provider = GeminiProvider(settings, transport=httpx.MockTransport(handler))
    analysis = provider.analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert calls == ["dead-model", "busy-model", "good-model"]
    assert provider.model == "good-model" and analysis.provider == "gemini:good-model"
    # the working model is remembered: the next call goes straight there
    provider.analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert calls[-1] == "good-model" and len(calls) == 4


def test_gemini_all_models_failing_raises(env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "gone"}})

    settings = _settings(monkeypatch, GEMINI_API_KEY="k", GEMINI_MODEL="a", GEMINI_FALLBACK_MODELS="b")
    with pytest.raises(GeminiError) as exc:
        GeminiProvider(settings, transport=httpx.MockTransport(handler)).analyze_input(InputBundle(project_id="p", description=BRIEF))
    assert "every configured model failed" in str(exc.value)


class _StubMessages:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def test_anthropic_provider_uses_structured_output(env, monkeypatch, tmp_path):
    from PIL import Image

    img = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (150, 120, 90)).save(img)
    settings = _settings(monkeypatch, ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude-opus-5")
    stub = _StubMessages(ANALYSIS_OK)
    provider = AnthropicProvider(settings, client=SimpleNamespace(messages=stub))
    from app.intelligence.schema import ReferenceImage

    analysis = provider.analyze_input(InputBundle(project_id="p", description=BRIEF, references=[ReferenceImage(path=str(img))]))
    assert analysis.provider == "anthropic:claude-opus-5"
    assert [r.room_id for r in analysis.rooms] == ["living_room", "master_bedroom"]
    call = stub.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert call["messages"][0]["content"][0]["type"] == "image"


def test_provider_selection(env, monkeypatch):
    reset_provider()
    _settings(monkeypatch, ANTHROPIC_API_KEY="k", GEMINI_API_KEY="g", INTELLIGENCE_PROVIDER="auto")
    assert get_provider().name == "anthropic"
    reset_provider()
    _settings(monkeypatch, ANTHROPIC_API_KEY="k", GEMINI_API_KEY="g", INTELLIGENCE_PROVIDER="gemini")
    assert get_provider().name == "gemini"
    reset_provider()
    _settings(monkeypatch, ANTHROPIC_API_KEY="", GEMINI_API_KEY="g", INTELLIGENCE_PROVIDER="auto")
    assert get_provider().name == "gemini"
    reset_provider()
    _settings(monkeypatch, ANTHROPIC_API_KEY="", GEMINI_API_KEY="", INTELLIGENCE_PROVIDER="anthropic")
    assert get_provider().mode == "mock"

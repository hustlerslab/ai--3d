"""P1-QA-002 — class=REAL-PROVIDER: one live call per provider, cost-capped.

Run nightly with real keys:   pytest -m real_provider
Never runs in a MOCK run (P1-QA-001 refuses to mix classes).

Each test names its provider in its id, so a failure says which vendor broke.
Each writes one row to $ALLURE_SMOKE_REPORT (JSON lines) with the provider,
outcome, latency and cost - the nightly evidence. Spend is capped:

* Gemini / Anthropic / Ollama: one tiny structured prompt, output capped.
* Meshy: the BALANCE endpoint only - 0 credits. A generation is never
  submitted by the smoke suite; the spend ledger is asserted unchanged.
* Blender: the default-cube smoke render at 4 samples.

A provider that is not configured is SKIPPED with the reason - and the
release gate (scripts/release_gate.py) counts a skip as "did not run".
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.real_provider

TINY_SCHEMA = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
TINY_PROMPT = 'Reply with the JSON {"word": "ok"} and nothing else.'


def _record(provider: str, outcome: str, started: float, **extra) -> None:
    row = {"provider": provider, "outcome": outcome, "latency_ms": int((time.monotonic() - started) * 1000),
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **extra}
    path = os.environ.get("ALLURE_SMOKE_REPORT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def _need(env: str, provider: str) -> str:
    value = os.environ.get(env, "")
    if not value:
        pytest.skip(f"{provider}: {env} not set - REAL-PROVIDER smoke did not run for {provider}")
    return value


def test_gemini_answers_one_structured_call():
    _need("GEMINI_API_KEY", "gemini")
    from app.intelligence.gemini_provider import GeminiProvider

    started = time.monotonic()
    try:
        out = GeminiProvider()._generate([{"text": TINY_PROMPT}], TINY_SCHEMA, "smoke")
    except Exception as exc:
        _record("gemini", "failed", started, error=f"{type(exc).__name__}: {exc}"[:300])
        pytest.fail(f"gemini: {type(exc).__name__}: {exc}")
    _record("gemini", "passed", started, cost="1 tiny call")
    assert isinstance(out, dict) and "word" in out, f"gemini returned {out!r}"


def test_anthropic_answers_one_structured_call():
    _need("ANTHROPIC_API_KEY", "anthropic")
    from app.intelligence.anthropic_provider import AnthropicProvider

    started = time.monotonic()
    try:
        out = AnthropicProvider()._generate([{"type": "text", "text": TINY_PROMPT}], TINY_SCHEMA, "smoke")
    except Exception as exc:
        _record("anthropic", "failed", started, error=f"{type(exc).__name__}: {exc}"[:300])
        pytest.fail(f"anthropic: {type(exc).__name__}: {exc}")
    _record("anthropic", "passed", started, cost="1 tiny call")
    assert isinstance(out, dict) and "word" in out


def test_qwen_via_ollama_answers_one_structured_call():
    from app.core.config import get_settings

    base = get_settings().ollama_base_url.rstrip("/")
    try:
        httpx.get(f"{base}/api/tags", timeout=3).raise_for_status()
    except Exception:
        pytest.skip(f"qwen/ollama: no Ollama at {base} - REAL-PROVIDER smoke did not run for qwen")
    from app.intelligence.ollama_provider import OllamaProvider

    started = time.monotonic()
    try:
        out = OllamaProvider()._generate(TINY_PROMPT, TINY_SCHEMA, "smoke")
    except Exception as exc:
        _record("qwen", "failed", started, error=f"{type(exc).__name__}: {exc}"[:300])
        pytest.fail(f"qwen/ollama: {type(exc).__name__}: {exc}")
    _record("qwen", "passed", started, cost="local")
    assert isinstance(out, dict)


def test_meshy_balance_costs_nothing_and_answers(env):
    key = _need("MESHY_API_KEY", "meshy")
    from app.providers import meshy
    from app.spend import project_spend

    async def call():
        async with meshy.make_client(key, timeout_seconds=30) as client:
            return await meshy.balance(client)

    started = time.monotonic()
    try:
        credits = asyncio.run(call())
    except Exception as exc:
        _record("meshy", "failed", started, error=f"{type(exc).__name__}: {exc}"[:300])
        pytest.fail(f"meshy: {type(exc).__name__}: {exc}")
    _record("meshy", "passed", started, cost="0 credits (balance only)", balance=credits)
    assert isinstance(credits, int) and credits >= 0
    assert project_spend("smoke").total == 0, "the smoke suite never spends"


def test_blender_renders_the_smoke_cube(tmp_path):
    path = _need("BLENDER_PATH", "blender")
    if not Path(path).exists():
        pytest.skip(f"blender: {path} does not exist")
    from app.blender.runner import BlenderRunner

    started = time.monotonic()
    out = tmp_path / "smoke.png"
    try:
        result = BlenderRunner(blender_path=path).smoke(out, engine="BLENDER_EEVEE", samples=4,
                                                         log_path=tmp_path / "blender.log")
    except Exception as exc:
        _record("blender", "failed", started, error=f"{type(exc).__name__}: {exc}"[:300])
        pytest.fail(f"blender: {type(exc).__name__}: {exc}")
    _record("blender", "passed", started, cost="local GPU", device=result.result.get("device"))
    assert out.exists() and out.stat().st_size > 0

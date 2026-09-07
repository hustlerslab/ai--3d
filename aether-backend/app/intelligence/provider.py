"""Provider protocol, resilient wrapper and the process-wide selector."""
from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol

from ..core.config import get_settings
from .mock_provider import MockProvider
from .schema import DesignAnalysis, InputBundle, ObjectPlan, StyleSpec

log = logging.getLogger("aether.intelligence")


class IntelligenceProvider(Protocol):
    name: str

    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis: ...

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec: ...

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan: ...


class ResilientProvider:
    """Runs each stage on the primary provider; on failure falls back to the
    mock (when allowed) and records why in the result's warnings, so the UI
    can say 'estimated' instead of silently degrading."""

    def __init__(
        self,
        primary: Optional[IntelligenceProvider],
        fallback: IntelligenceProvider,
        allow_fallback: bool = True,
    ):
        self.primary = primary
        self.fallback = fallback
        self.allow_fallback = allow_fallback

    @property
    def name(self) -> str:
        return self.primary.name if self.primary else self.fallback.name

    @property
    def mode(self) -> str:
        return "live" if self.primary else "mock"

    def _run(self, stage: str, fn_primary, fn_fallback):
        if self.primary is None:
            return fn_fallback()
        try:
            return fn_primary()
        except Exception as exc:
            if not self.allow_fallback:
                raise
            log.warning("%s failed on %s (%s); falling back to mock", stage, self.primary.name, exc)
            result = fn_fallback()
            result.provider = f"{self.fallback.name}(fallback)"
            result.warnings.insert(0, f"{self.primary.name} failed during {stage}: {exc}; used deterministic estimate")
            return result

    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        return self._run(
            "analyze_input",
            lambda: self.primary.analyze_input(bundle),  # type: ignore[union-attr]
            lambda: self.fallback.analyze_input(bundle),
        )

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        return self._run(
            "create_style_spec",
            lambda: self.primary.create_style_spec(analysis, bundle),  # type: ignore[union-attr]
            lambda: self.fallback.create_style_spec(analysis, bundle),
        )

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        return self._run(
            "plan_objects",
            lambda: self.primary.plan_objects(analysis, style, bundle),  # type: ignore[union-attr]
            lambda: self.fallback.plan_objects(analysis, style, bundle),
        )


_provider: Optional[ResilientProvider] = None
_lock = threading.Lock()


def get_provider() -> ResilientProvider:
    global _provider
    with _lock:
        if _provider is None:
            settings = get_settings()
            primary: Optional[IntelligenceProvider] = None
            if settings.gemini_configured:
                from .gemini_provider import GeminiProvider

                primary = GeminiProvider(settings)
            _provider = ResilientProvider(primary, MockProvider(), settings.provider_fallback_to_mock)
        return _provider


def reset_provider() -> None:
    global _provider
    with _lock:
        _provider = None

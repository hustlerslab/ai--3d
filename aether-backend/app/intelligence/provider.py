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
    def label(self) -> str:
        """Provider and model, e.g. 'gemini:gemini-3.6-flash' or 'mock'."""
        return getattr(self.primary, "label", self.name) if self.primary else "mock"

    @property
    def mode(self) -> str:
        return "live" if self.primary else "mock"

    def read_scene_elements(self, image, room, style, vertical) -> dict:
        """Optional capability. No mock fallback: an empty reading tells the
        caller nothing was read, which is honest, where a mock-invented list of
        furniture would be fabricated detail presented as observation.

        A FAILED call is reported as `_error`, not as emptiness. The two are
        different facts - "this room genuinely has nothing in it" versus "the
        model timed out" - and collapsing both into `{}` hid a real outage: with
        no `read_scene_elements` on the local provider at all, every project
        read zero elements and the feed said only "the reader returned nothing".
        `coerce_room_reading` reads `elements` and `surfaces`, so the key is
        inert everywhere except the warning an operator actually sees.
        """
        read = getattr(self.primary, "read_scene_elements", None)
        if not callable(read):
            return {"_error": f"{self.label} cannot read renders: no read_scene_elements"}
        try:
            return read(image, room, style, vertical) or {}
        except Exception as exc:                           # noqa: BLE001
            log.exception("read_scene_elements failed on %s", self.label)
            return {"_error": f"{type(exc).__name__}: {exc}"}

    def classify_reference(self, image, description: str, vertical, filename: str = "") -> dict:
        """Optional capability (ADR-001 pins the Protocol to three methods):
        P11/P12 reference classification.

        A FAILED call is reported as `_error`, never as an empty answer. The
        caller turns `_error` into an `unread` reference with the reason
        attached, which is the whole point - a photograph the system could not
        read must be visible, not absent.

        Source follows `_run`'s own rule: with no primary at all the operator
        SELECTED the deterministic provider, so it is the provider rather than
        a degradation. But a real primary that FAILS is never papered over with
        it - that substitution would present a guess as a reading of the
        client's photograph, which is the fabricated evidence this whole phase
        exists to prevent.
        """
        source = self.primary if self.primary is not None else self.fallback
        classify = getattr(source, "classify_reference", None)
        if not callable(classify):
            return {"_error": f"{self.label} cannot classify references: no classify_reference"}  # noqa: E501
        try:
            return classify(image, description, vertical, filename=filename) or {}
        except TypeError:
            # A provider written against the original three-argument form.
            try:
                return classify(image, description, vertical) or {}
            except Exception as exc:                       # noqa: BLE001
                log.exception("classify_reference failed on %s", self.label)
                return {"_error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:                           # noqa: BLE001
            log.exception("classify_reference failed on %s", self.label)
            return {"_error": f"{type(exc).__name__}: {exc}"}

    def check_element_crop(self, crop, room_type, vertical) -> dict:
        """Optional capability. No mock fallback, and a failure is NOT a pass:
        an empty result makes the caller record `unreadable`, which sends the
        crop to a human rather than quietly waving it through to spend."""
        check = getattr(self.primary, "check_element_crop", None)
        if not callable(check):
            return {}
        try:
            return check(crop, room_type, vertical) or {}
        except Exception:                                  # noqa: BLE001
            log.exception("check_element_crop failed on %s", self.label)
            return {}

    def estimate_element_dimensions(self, room, elements, vertical) -> dict:
        """Optional capability. An empty answer means every piece keeps the
        per-type default, which is generic but never absurd."""
        estimate = getattr(self.primary, "estimate_element_dimensions", None)
        if not callable(estimate):
            return {}
        try:
            return estimate(room, elements, vertical) or {}
        except Exception:                                  # noqa: BLE001
            log.exception("estimate_element_dimensions failed on %s", self.label)
            return {}

    def compose_scene_prompt(self, analysis, style, bundle, room) -> str:
        """Optional capability, not part of the Protocol (ADR-001 pins that to
        three methods). Delegated only when the primary offers it.

        Deliberately no mock fallback: an empty string tells the caller to use
        the keyword template, which is a real prompt rather than a pretend one,
        and the caller records which was used. A mock-written prompt would be
        exactly the silent degradation this class exists to prevent.
        """
        compose = getattr(self.primary, "compose_scene_prompt", None)
        if not callable(compose):
            return ""
        try:
            return compose(analysis, style, bundle, room)
        except Exception as exc:                       # noqa: BLE001
            log.exception("compose_scene_prompt failed on %s", self.label)
            return ""

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
            choice = settings.intelligence_provider.lower().strip()
            # Local and free, but slower and weaker than the cloud models, so
            # `auto` never picks it — it has to be asked for by name.
            if choice == "ollama":
                from .ollama_provider import OllamaProvider

                _provider = ResilientProvider(
                    OllamaProvider(settings), MockProvider(), settings.provider_fallback_to_mock
                )
                return _provider

            use_anthropic = choice == "anthropic" or (choice == "auto" and settings.anthropic_configured)
            use_gemini = choice == "gemini" or (choice == "auto" and not use_anthropic and settings.gemini_configured)
            if use_anthropic and settings.anthropic_configured:
                from .anthropic_provider import AnthropicProvider

                primary = AnthropicProvider(settings)
            elif use_gemini and settings.gemini_configured:
                from .gemini_provider import GeminiProvider

                primary = GeminiProvider(settings)
            elif choice not in ("auto", "mock"):
                log.warning("INTELLIGENCE_PROVIDER=%s but its API key is missing; using the mock provider", choice)
            _provider = ResilientProvider(primary, MockProvider(), settings.provider_fallback_to_mock)
        return _provider


def reset_provider() -> None:
    global _provider
    with _lock:
        _provider = None

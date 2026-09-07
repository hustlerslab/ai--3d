"""Intelligence layer (plan §7, DPR §7, §26, §27).

Stage-specific agents turn the user's brief and photos into structured,
validated JSON. The rest of the pipeline consumes those files and never a
raw model response:

  InputBundle ──analyze_input──▶ DesignAnalysis ──create_style_spec──▶ StyleSpec
                                                                      └▶ MoodboardSpec

Providers implement `IntelligenceProvider`. `get_provider()` returns a
resilient wrapper: Gemini when a key is configured, the deterministic mock
otherwise, and a per-stage fallback to mock (with a warning) when Gemini
fails and PROVIDER_FALLBACK_TO_MOCK is on.
"""
from .bundle import build_input_bundle
from .provider import IntelligenceProvider, ResilientProvider, get_provider, reset_provider
from .schema import (
    AgentInput,
    AgentOutput,
    AssetDecision,
    AssetPlan,
    DesignAnalysis,
    InputBundle,
    MoodboardSpec,
    ObjectPlan,
    ObjectPlanItem,
    ObjectRelation,
    ReferenceImage,
    RoomAnalysis,
    SpottedObject,
    StyleSpec,
)

__all__ = [
    "AgentInput",
    "AgentOutput",
    "AssetDecision",
    "AssetPlan",
    "DesignAnalysis",
    "InputBundle",
    "IntelligenceProvider",
    "MoodboardSpec",
    "ObjectPlan",
    "ObjectPlanItem",
    "ObjectRelation",
    "ReferenceImage",
    "ResilientProvider",
    "RoomAnalysis",
    "SpottedObject",
    "StyleSpec",
    "build_input_bundle",
    "get_provider",
    "reset_provider",
]

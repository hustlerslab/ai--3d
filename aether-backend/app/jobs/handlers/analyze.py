"""Stage 5: analyze inputs → DesignAnalysis, StyleSpec, MoodboardSpec.

Checkpoints (DPR §20): analysis/design_analysis.json, analysis/style_spec.json,
analysis/moodboard_spec.json. Each is skipped on retry when present unless
params.force is true.
"""
from __future__ import annotations

import time

from ...intelligence import DesignAnalysis, StyleSpec, build_input_bundle, get_provider
from ...intelligence.mock_provider import build_moodboard
from ...intelligence.schema import AgentInput, AgentOutput
from ...projects.schema import ProjectStage
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"
MOODBOARD = "analysis/moodboard_spec.json"


class NoInputs(Exception):
    pass


@register(
    "analyze",
    lane=JobLane.ai,
    max_attempts=2,
    stage_running=ProjectStage.ANALYZING,
    stage_done=ProjectStage.DESIGN_SPEC_READY,
    description="Input analysis + style interpretation + moodboard",
)
def analyze(ctx: JobContext) -> dict:
    force = bool(ctx.params.get("force", False))
    bundle = build_input_bundle(ctx.project_id)
    if not bundle.has_content:
        raise NoInputs("project has no description, dimensions or reference images")
    provider = get_provider()
    ctx.emit("analyze.inputs", f"{len(bundle.references)} photo(s), {len(bundle.room_hints)} room hint(s), provider={provider.mode}")

    # ── design analysis ──────────────────────────────────────────────────
    if ctx.has_checkpoint(ANALYSIS) and not force:
        analysis = DesignAnalysis.model_validate(ctx.read_json(ANALYSIS))
        ctx.emit("analyze.analysis", "checkpoint present, skipped")
    else:
        t0 = time.monotonic()
        analysis = provider.analyze_input(bundle)
        analysis.version = ctx.projects.next_analysis_version(ctx.project_id, "design_analysis")
        ctx.write_json(ANALYSIS, analysis)
        ctx.write_json(
            "analysis/agent_analyze_input.json",
            _envelope(ctx, "analyze_input", analysis.provider, analysis.confidence, analysis.warnings, t0,
                      {"rooms": len(analysis.rooms), "spotted_objects": len(analysis.spotted_objects)},
                      "create_style_spec"),
        )
        ctx.projects.add_analysis(ctx.project_id, "design_analysis", ANALYSIS, analysis.version)
        ctx.mark_checkpoint("analysis")
        ctx.emit(
            "analyze.analysis",
            f"{len(analysis.rooms)} room(s), {len(analysis.spotted_objects)} object(s), "
            f"confidence {analysis.confidence:.2f} via {analysis.provider}",
        )

    # ── style ────────────────────────────────────────────────────────────
    if ctx.has_checkpoint(STYLE) and not force:
        style = StyleSpec.model_validate(ctx.read_json(STYLE))
        ctx.emit("analyze.style", "checkpoint present, skipped")
    else:
        t0 = time.monotonic()
        style = provider.create_style_spec(analysis, bundle)
        style.version = ctx.projects.next_analysis_version(ctx.project_id, "style_spec")
        ctx.write_json(STYLE, style)
        ctx.write_json(
            "analysis/agent_create_style_spec.json",
            _envelope(ctx, "create_style_spec", style.provider, style.confidence, style.warnings, t0,
                      {"name": style.name, "materials": style.materials}, "plan_scene"),
        )
        ctx.projects.add_analysis(ctx.project_id, "style_spec", STYLE, style.version)
        ctx.mark_checkpoint(STYLE)
        ctx.emit("analyze.style", f"{style.name} · {', '.join(style.palette[:3])} · {style.lighting_mood}")

    # ── moodboard (derived, always rebuilt) ──────────────────────────────
    moodboard = build_moodboard(analysis, style, bundle)
    ctx.write_json(MOODBOARD, moodboard)
    ctx.projects.add_analysis(ctx.project_id, "moodboard_spec", MOODBOARD, style.version)
    ctx.mark_checkpoint("moodboard")
    ctx.emit("analyze.moodboard", moodboard.title)

    warnings = list(dict.fromkeys(analysis.warnings + style.warnings))
    return {
        "provider": provider.mode,
        "analysis_provider": analysis.provider,
        "style_provider": style.provider,
        "rooms": [r.room_id for r in analysis.rooms],
        "style": style.name,
        "palette": style.palette,
        "warnings": warnings,
    }


def _envelope(ctx: JobContext, stage: str, provider: str, confidence: float, warnings: list[str], t0: float,
              result: dict, next_action: str) -> AgentOutput:
    return AgentOutput(
        project_id=ctx.project_id,
        stage=stage,
        status="fallback" if "fallback" in provider else "ok",
        confidence=confidence,
        result=result,
        warnings=warnings,
        next_action=next_action,
        provider=provider,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )


__all__ = ["analyze", "AgentInput", "NoInputs"]

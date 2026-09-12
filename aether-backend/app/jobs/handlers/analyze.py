"""Stage 5: analyze inputs → DesignAnalysis, StyleSpec, MoodboardSpec.

Checkpoints (DPR §20): analysis/design_analysis.json, analysis/style_spec.json,
analysis/moodboard_spec.json. Each is skipped on retry when present unless
params.force is true.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from ...intelligence import DesignAnalysis, StyleSpec, build_input_bundle, get_provider
from ...intelligence.crops import write_crops
from ...intelligence.mock_provider import build_moodboard
from ...projects.layout import project_dir
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
    uses_intelligence=True,
)
def analyze(ctx: JobContext) -> dict:
    force = bool(ctx.params.get("force", False))
    bundle = build_input_bundle(ctx.project_id)
    if not bundle.has_content:
        raise NoInputs("project has no description, dimensions or reference images")
    provider = get_provider()
    ctx.emit(
        "analyze.inputs",
        f"{len(bundle.references)} photo(s), {len(bundle.room_hints)} room hint(s), "
        f"provider={provider.mode}, vertical={bundle.vertical.value}",
    )

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
            f"confidence {analysis.confidence:.2f} via {analysis.provider} "
            f"[vertical={bundle.vertical.value}]",
        )

    # ── crops of every item the reading located in a photo (deterministic) ─
    before = [s.crop_ref for s in analysis.spotted_objects]
    crop_warnings = write_crops(analysis, bundle, project_dir(ctx.project_id), force=force)
    if [s.crop_ref for s in analysis.spotted_objects] != before:
        ctx.write_json(ANALYSIS, analysis)
    n_crops = sum(1 for s in analysis.spotted_objects if s.crop_ref)
    if n_crops or crop_warnings:
        ctx.emit("analyze.crops", f"{n_crops} item crop(s) written" + (f"; {len(crop_warnings)} warning(s)" if crop_warnings else ""))
    analysis.warnings = list(dict.fromkeys(analysis.warnings + crop_warnings))

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
        ctx.emit(
            "analyze.style",
            f"{style.name} · {', '.join(style.palette[:3])} · {style.lighting_mood} "
            f"[vertical={bundle.vertical.value}]",
        )

    # ── moodboard (derived, always rebuilt) ──────────────────────────────
    moodboard = build_moodboard(analysis, style, bundle)
    _add_scene_image(ctx, moodboard, analysis, style, bundle, force=force)
    ctx.write_json(MOODBOARD, moodboard)
    ctx.projects.add_analysis(ctx.project_id, "moodboard_spec", MOODBOARD, style.version)
    ctx.mark_checkpoint("moodboard")
    ctx.emit("analyze.moodboard", moodboard.title)

    warnings = list(dict.fromkeys(analysis.warnings + style.warnings))
    return {
        "provider": provider.mode,
        "vertical": bundle.vertical.value,
        "analysis_provider": analysis.provider,
        "style_provider": style.provider,
        "rooms": [r.room_id for r in analysis.rooms],
        "spotted_objects": len(analysis.spotted_objects),
        "crops": sum(1 for s in analysis.spotted_objects if s.crop_ref),
        "architecture": analysis.architecture,
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


SCENE_IMAGE = "analysis/moodboard_scene.png"


def _add_scene_image(
    ctx: JobContext,
    moodboard,
    analysis,
    style,
    bundle,
    *,
    force: bool = False,
) -> None:
    """Paint the room being proposed and hang it on the moodboard.

    Runs locally on Stable Diffusion, conditioned on one of the client's own
    photos through IP-Adapter, so the render shows their furniture rather than
    a generic room. No API key and no per-image cost.

    Never raises. A missing install, a disabled flag, an out-of-VRAM or a
    model failure all leave `scene_url` empty and put a readable reason in
    `scene_error`, because a moodboard without its hero image is still a usable
    moodboard — and failing the whole analysis over a picture would throw away
    the reading, the style and the crops with it.
    """
    from ...core.config import get_settings
    from ...intelligence.prompts import SD_NEGATIVE, scene_prompt_sd
    from ...projects.layout import file_url
    from ...providers import local_image

    settings = get_settings()
    if not settings.scene_image_enabled:
        return
    if not local_image.available():
        moodboard.scene_error = (
            "Local image generation is not installed. Run: pip install --index-url "
            "https://download.pytorch.org/whl/cu126 torch torchvision, then "
            "pip install 'diffusers==0.35.1' 'transformers<5' accelerate safetensors"
        )
        return

    dest = ctx.path(SCENE_IMAGE)
    if dest.exists() and not force:                 # checkpoint: the file itself
        moodboard.scene_url = file_url(ctx.project_id, SCENE_IMAGE)
        # Carry the previous run's verdict forward. Defaulting to "resolved"
        # on a resume would vouch for a render this run never looked at.
        prior = [o for o in ctx.projects.list_outputs(ctx.project_id)
                 if o["kind"] == "moodboard_scene"]
        meta = prior[-1]["meta"] if prior else {}
        moodboard.reference_resolved = bool(meta.get("reference_resolved"))
        moodboard.reference_note = str(meta.get("reference", "") or "from a previous run")
        ctx.emit("analyze.scene", "checkpoint present, skipped")
        return

    reference, ref_note = _scene_reference(analysis, bundle)
    moodboard.reference_resolved = reference is not None
    moodboard.reference_note = ref_note
    if reference is None:
        # Loud, not quiet. Generation still runs — a generic room beats no
        # moodboard — but "we could not use your photo" is a result the user
        # has to be told, not a log line nobody reads.
        ctx.log.warning("scene reference unresolved: %s", ref_note)
        ctx.emit("analyze.scene", f"no reference photo — {ref_note}", status="warning")
    try:
        image = local_image.generate(
            scene_prompt_sd(analysis, style, bundle),
            model=settings.scene_image_model,
            negative_prompt=SD_NEGATIVE,
            steps=settings.scene_image_steps,
            width=settings.scene_image_width,
            height=settings.scene_image_height,
            references=[reference] if reference else None,
            reference_scale=settings.scene_image_reference_scale,
        )
        local_image.write(image, dest)
    except Exception as exc:
        moodboard.scene_error = f"{type(exc).__name__}: {exc}"
        # Warning, not info: a degraded result that looks like a success
        # everywhere else has to be loud in the log too.
        ctx.log.warning("moodboard scene image failed: %s", exc)
        ctx.emit("analyze.scene", f"no scene image — {exc}", status="warning")
        return
    finally:
        # Hand the card back. Blender and Ollama want the same 6 GB, and the
        # runner only serialises jobs — it cannot reclaim a pipeline this
        # process is still holding.
        local_image.unload()

    moodboard.scene_url = file_url(ctx.project_id, SCENE_IMAGE)
    ctx.add_output(
        "moodboard_scene",
        SCENE_IMAGE,
        {"model": image.model, "reference_resolved": reference is not None, "reference": ref_note},
    )
    ctx.emit(
        "analyze.scene",
        f"scene painted by {image.model} ({dest.stat().st_size // 1024} KB), "
        + (f"conditioned on {ref_note}" if reference else f"UNCONDITIONED — {ref_note}"),
        status="ok" if reference else "warning",
    )


# Anchor pieces, best first: a room reads as the client's when the big
# upholstered item is theirs. IP-Adapter takes ONE embedding, so several
# references average into mush — picking the right single photo beats blending.
_ANCHOR_TYPES = ("sofa", "loveseat", "bed", "armchair", "dining_table")


def _scene_reference(analysis, bundle) -> tuple[Optional[Path], str]:
    """The one photo worth conditioning the render on, and a note saying which.

    Prefers the FULL upload an anchor piece was seen in, not its crop.
    Measured on the sample set: conditioning on a crop produced a flat
    product shot against a wall, because IP-Adapter carries composition as
    well as the object and a crop is an isolated thing on white. The same
    prompt with the full photo produced the sofa in a real room. Crops remain
    the right input for texturing — just not for composing a scene.

    Returns (path, note). A None path is never silent: the note says why, the
    caller logs it at warning level and it is stored on the moodboard, because
    an unconditioned render is a generic room wearing a successful job's
    clothes.
    """
    spotted = list(getattr(analysis, "spotted_objects", []) or [])
    missing: list[str] = []

    for wanted in _ANCHOR_TYPES:
        for s in spotted:
            if s.semantic_type != wanted:
                continue
            photo = bundle.photo_for(s)
            if photo is not None and Path(photo.path).is_file():
                return Path(photo.path), f"{s.name or wanted} in {photo.filename or Path(photo.path).name}"
            if s.image_ref or s.image_index >= 0:
                missing.append(s.name or wanted)

    for r in bundle.references:                 # any upload beats no reference
        if Path(r.path).is_file():
            note = f"no anchor piece resolved; fell back to {r.filename or Path(r.path).name}"
            if missing:
                note = f"photo for {', '.join(missing[:3])} is gone from the project; " + note
            return Path(r.path), note

    if missing:
        return None, f"photo for {', '.join(missing[:3])} is gone from the project and no upload remains"
    return None, "project has no reference photos"

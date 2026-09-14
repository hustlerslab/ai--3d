"""Stage 5: analyze inputs → DesignAnalysis, StyleSpec, MoodboardSpec.

Checkpoints (DPR §20): analysis/design_analysis.json, analysis/style_spec.json,
analysis/moodboard_spec.json. Each is skipped on retry when present unless
params.force is true.
"""
from __future__ import annotations

import random
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
    # paints the moodboard on the local GPU; see JobSpec.uses_local_gpu
    uses_local_gpu=True,
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
    _add_scene_image(ctx, moodboard, analysis, style, bundle, provider=provider, force=force)
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
    provider=None,
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

    from ...intelligence.schema import RoomScene

    rooms = list(getattr(analysis, "rooms", []) or [])
    if not rooms:
        moodboard.scene_error = "the reading found no rooms to paint"
        return

    scenes: list[RoomScene] = []
    try:
        for room in rooms:
            scenes.append(_paint_room(ctx, room, analysis, style, bundle, settings,
                                      provider=provider, force=force))
    finally:
        # Once, after every room. Unloading between rooms would pay the cold
        # load each time — measured at ~31 s for the first room against ~15 s
        # for each one after it, on the same card.
        local_image.unload()

    moodboard.room_scenes = scenes
    hero = next((s for s in scenes if s.url), None)
    if hero is None:
        moodboard.scene_error = "; ".join(dict.fromkeys(s.error for s in scenes if s.error))[:500]
        return
    # The first painted room stays the hero, so anything written against the
    # single-image shape keeps working unchanged.
    moodboard.scene_url = hero.url
    moodboard.reference_resolved = hero.reference_resolved
    moodboard.reference_note = hero.reference_note
    painted = sum(1 for s in scenes if s.url)
    ctx.emit(
        "analyze.scene",
        f"{painted}/{len(scenes)} room image(s) painted"
        + (f"; {len(scenes) - painted} failed" if painted < len(scenes) else ""),
        status="ok" if painted == len(scenes) else "warning",
    )


def _room_image(room_id: str) -> str:
    return f"analysis/moodboard_room_{room_id}.png"


def _paint_room(ctx, room, analysis, style, bundle, settings, *, provider=None,
                force: bool, seed: Optional[int] = None) -> "RoomScene":
    """One room's image. Never raises: a failed room leaves the others intact."""
    from ...intelligence.prompts import SD_NEGATIVE, compose_room_prompt, scene_recipe_version
    from ...intelligence.schema import RoomScene
    from ...projects.layout import file_url
    from ...providers import local_image

    rel = _room_image(room.room_id)
    dest = ctx.path(rel)
    scene = RoomScene(room_id=room.room_id, name=room.name, type=room.type)

    recipe = scene_recipe_version()
    prior = [o for o in ctx.projects.list_outputs(ctx.project_id)
             if o["kind"] == "moodboard_scene" and o.get("meta", {}).get("room_id") == room.room_id]
    meta = prior[-1]["meta"] if prior else {}
    painted_under = str(meta.get("recipe_version", ""))

    # The checkpoint is "is this image CURRENT", not "does a file exist". A file
    # can be newer than the code that should have produced it and still be
    # stale, because the server loads code once at start-up — that is exactly
    # how a bathroom image written at 20:13 came from 19:57 code. An image with
    # no recorded recipe predates versioning and is stale by definition, which
    # is what makes this retroactive for every existing project.
    if dest.exists() and not force and painted_under == recipe:
        scene.url = file_url(ctx.project_id, rel)
        scene.recipe_version = painted_under
        scene.reference_resolved = bool(meta.get("reference_resolved"))
        scene.reference_note = str(meta.get("reference", "") or "from a previous run")
        scene.prompt = str(meta.get("prompt", ""))
        scene.prompt_source = str(meta.get("prompt_source", "template"))
        scene.seed = int(meta.get("seed", 0) or 0)
        ctx.emit("analyze.scene", f"{room.name}: up to date, skipped")
        return scene
    if dest.exists() and not force:
        ctx.emit(
            "analyze.scene",
            f"{room.name}: repainting — made under recipe "
            f"{painted_under or '(none recorded)'}, current is {recipe}",
        )

    reference, ref_note = _scene_reference(analysis, bundle, room_id=room.room_id)
    scene.reference_resolved = reference is not None
    scene.reference_note = ref_note
    if reference is None:
        # Loud, not quiet — an unconditioned render is indistinguishable from a
        # conditioned one. Rooms the client photographed nothing of are the
        # normal case here, so this is information, not an alarm.
        ctx.log.warning("%s: scene reference unresolved: %s", room.room_id, ref_note)

    prompt, prompt_source = compose_room_prompt(provider, analysis, style, bundle, room)
    scene.prompt, scene.prompt_source = prompt, prompt_source
    # An explicit seed, always: a random draw cannot be repeated, so a reviewer
    # who likes an image cannot keep it and one who does not cannot tell whether
    # a repaint changed anything.
    scene.seed = seed if seed is not None else random.randrange(1, 2**31 - 1)
    try:
        image = local_image.generate(
            prompt,
            model=settings.scene_image_model,
            negative_prompt=SD_NEGATIVE,
            steps=settings.scene_image_steps,
            width=settings.scene_image_width,
            height=settings.scene_image_height,
            references=[reference] if reference else None,
            reference_scale=settings.scene_image_reference_scale,
            seed=scene.seed,
        )
        local_image.write(image, dest)
    except Exception as exc:
        scene.error = f"{type(exc).__name__}: {exc}"
        # exception(), not warning(): the message alone is often opaque
        # ("list index out of range" from inside diffusers) and cost hours of
        # guessing. The stack says which line, in one run instead of five.
        ctx.log.exception("%s: moodboard image failed", room.room_id)
        ctx.emit("analyze.scene", f"{room.name}: no image — {exc}", status="warning")
        return scene

    scene.url = file_url(ctx.project_id, rel)
    scene.recipe_version = recipe
    ctx.add_output("moodboard_scene", rel, {
        "model": image.model, "room_id": room.room_id, "room_name": room.name,
        "reference_resolved": reference is not None, "reference": ref_note,
        "prompt_source": prompt_source, "prompt": prompt, "recipe_version": recipe,
        "seed": scene.seed,
    })
    ctx.emit(
        "analyze.scene",
        f"{room.name}: {dest.stat().st_size // 1024} KB, "
        + (f"conditioned on {ref_note}" if reference else f"unconditioned — {ref_note}"),
        status="ok" if reference else "warning",
    )
    return scene


# Anchor pieces, best first: a room reads as the client's when the big
# upholstered item is theirs. IP-Adapter takes ONE embedding, so several
# references average into mush — picking the right single photo beats blending.
_ANCHOR_TYPES = ("sofa", "loveseat", "bed", "armchair", "dining_table")


def _scene_reference(analysis, bundle, room_id: Optional[str] = None) -> tuple[Optional[Path], str]:
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
    if room_id is not None:
        # Per-room images condition on that room's own pieces: painting the
        # bedroom from a photo of the sofa is worse than painting it from
        # nothing, because it looks conditioned and is not.
        spotted = [s for s in spotted if s.room_id == room_id]
    # Items the client keeps are theirs; a reference photo is something they
    # liked in a shop and must not be used as if it were in the room.
    spotted = [s for s in spotted if getattr(s, "role", "place") == "place"]
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

    if room_id is None:
        for r in bundle.references:             # any upload beats no reference
            if Path(r.path).is_file():
                note = f"no anchor piece resolved; fell back to {r.filename or Path(r.path).name}"
                if missing:
                    note = f"photo for {', '.join(missing[:3])} is gone from the project; " + note
                return Path(r.path), note

    if missing:
        return None, f"photo for {', '.join(missing[:3])} is gone from the project and no upload remains"
    if room_id is not None:
        return None, "no photo of this room's own pieces; painted from the brief and style"
    return None, "project has no reference photos"

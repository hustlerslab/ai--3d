"""Repaint ONE room's moodboard image, leaving the rest of the board alone.

Why this exists
---------------
Seed variance is large and is not a prompt defect. Measured on one bathroom
prompt that already names vanity, basin, mirror, toilet, walk-in shower and the
framing: two of six seeds gave a complete room, two gave a near-miss with the
shower half out of frame, one was tub-dominant and one dropped the bath
entirely. Nothing in the text distinguishes them.

ADR-002 §1 already settled what to do about that class of variation — the human
review step is the backstop, not a parameter. This is that backstop made real:
the reviewer sees a room they do not like and draws again, without re-running
the reading, the style, or the other four rooms.

Each draw records its seed, so a picture that is liked stays that picture and a
repaint is a genuinely different draw rather than a re-roll of the same dice.
"""
from __future__ import annotations

import random

from ...intelligence import DesignAnalysis, StyleSpec, build_input_bundle, get_provider
from ...intelligence.schema import MoodboardSpec
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"
MOODBOARD = "analysis/moodboard_spec.json"


class RoomNotFound(Exception):
    pass


class MoodboardRequired(Exception):
    pass


def _fresh_seed(avoid: int) -> int:
    """A different draw, not the same one again. Without this the reviewer
    presses regenerate and gets a pixel-identical image back."""
    seed = random.randrange(1, 2**31 - 1)
    while seed == avoid:
        seed = random.randrange(1, 2**31 - 1)
    return seed


@register(
    "repaint_room",
    lane=JobLane.render,
    max_attempts=2,
    description="Redraw one room's moodboard image on a fresh seed",
    # Stable Diffusion on the local card: the render lane is the GPU mutex.
    uses_local_gpu=True,
)
def repaint_room(ctx: JobContext) -> dict:
    from ...core.config import get_settings
    from ...providers import local_image
    from .analyze import _paint_room

    room_id = str(ctx.params.get("room_id") or "").strip()
    if not room_id:
        raise RoomNotFound("repaint_room needs a room_id")
    if not (ctx.has_checkpoint(ANALYSIS) and ctx.has_checkpoint(STYLE) and ctx.path(MOODBOARD).exists()):
        raise MoodboardRequired("run the analysis before repainting a room")

    analysis = DesignAnalysis.model_validate(ctx.read_json(ANALYSIS))
    style = StyleSpec.model_validate(ctx.read_json(STYLE))
    moodboard = MoodboardSpec.model_validate(ctx.read_json(MOODBOARD))
    room = next((r for r in analysis.rooms if r.room_id == room_id), None)
    if room is None:
        raise RoomNotFound(f"no room {room_id!r} in this reading")

    settings = get_settings()
    if not settings.scene_image_enabled:
        raise MoodboardRequired("scene images are disabled (SCENE_IMAGE_ENABLED=false)")
    if not local_image.available():
        raise MoodboardRequired("local image generation is not installed")

    previous = next((s for s in moodboard.room_scenes if s.room_id == room_id), None)
    seed = _fresh_seed(previous.seed if previous else 0)

    ctx.emit("repaint.start", f"{room.name}: redrawing on seed {seed}")
    try:
        scene = _paint_room(ctx, room, analysis, style, build_input_bundle(ctx.project_id),
                            settings, provider=get_provider(), force=True, seed=seed)
    finally:
        # Hand the card back; Blender and Ollama want the same 6 GB.
        local_image.unload()

    # Swap this room in place, leaving the rest of the board untouched.
    if any(s.room_id == room_id for s in moodboard.room_scenes):
        moodboard.room_scenes = [scene if s.room_id == room_id else s for s in moodboard.room_scenes]
    else:
        moodboard.room_scenes = [*moodboard.room_scenes, scene]
    hero = next((s for s in moodboard.room_scenes if s.url), None)
    if hero is not None:
        moodboard.scene_url = hero.url
    ctx.write_json(MOODBOARD, moodboard)
    ctx.projects.add_analysis(ctx.project_id, "moodboard_spec", MOODBOARD, style.version)

    ctx.emit(
        "repaint.done",
        f"{room.name}: {'redrawn' if scene.url else 'failed'} on seed {seed}"
        + (f" — {scene.error}" if scene.error else ""),
        status="ok" if scene.url else "warning",
    )
    return {
        "room_id": room_id,
        "room_name": room.name,
        "seed": seed,
        "previous_seed": previous.seed if previous else 0,
        "url": scene.url,
        "error": scene.error,
        "prompt_source": scene.prompt_source,
    }


__all__ = ["repaint_room", "RoomNotFound", "MoodboardRequired"]

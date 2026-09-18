"""Element images: one isolated picture per canonical piece, BEFORE any room
is painted.

This is the first stage of element-first that a client actually sees. The
inventory comes from the object plan - the client's photographed pieces plus
what the brief asks for, with counts - and each canonical piece gets a single
product-style render on a neutral ground. Three bar stools are one picture.

The picture is then the same picture everywhere: on the review screen, as the
Meshy input (a clean isolated piece beats a crop cut out of a busy room
render), and - once measured - as a reference for painting the room itself.

Checkpoint: planning/element_images.json plus one PNG per piece. A piece whose
PNG exists under the same recipe is not re-rendered.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from ...intelligence.schema import (DesignAnalysis, ElementDefinition, ElementImage,
                                    ElementImageSet, ObjectPlan, StyleSpec)
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"
OBJECT_PLAN = "planning/object_plan.json"       # the same file scene_plan writes
ELEMENT_IMAGES = "planning/element_images.json"
IMAGE_DIR = "planning/element_images"

#: Bumped when the prompt recipe or the render settings change meaning, so an
#: image painted under an older recipe is repainted rather than trusted.
RECIPE_VERSION = "p20.1"


class AnalysisRequired(Exception):
    pass


def _image_rel(element_id: str) -> str:
    return f"{IMAGE_DIR}/{element_id}.png"


def _seed_for(element_id: str) -> int:
    """Deterministic: the same piece paints the same picture on every run."""
    return int(hashlib.sha1(element_id.encode("utf-8")).hexdigest()[:8], 16) % (2 ** 31 - 1) or 1


@register(
    "element_images",
    lane=JobLane.render,
    max_attempts=2,
    description="One isolated image per canonical piece, before the room is painted",
    uses_intelligence=True,       # plan_objects, when no object plan exists yet
    uses_local_gpu=True,
)
def element_images(ctx: JobContext) -> dict[str, Any]:
    from ...core.config import get_settings
    from ...intelligence import build_input_bundle, get_provider
    from ...intelligence.prompts import ELEMENT_NEGATIVE, element_prompt_sd
    from ...intelligence.scene_reading import definitions_from_plan
    from ...providers import local_image

    force = bool(ctx.params.get("force", False))
    settings = get_settings()
    if not ctx.has_checkpoint(ANALYSIS) or not ctx.has_checkpoint(STYLE):
        raise AnalysisRequired("run the analyze job first: no design analysis or style spec")

    analysis = DesignAnalysis.model_validate(ctx.read_json(ANALYSIS))
    style = StyleSpec.model_validate(ctx.read_json(STYLE))
    bundle = build_input_bundle(ctx.project_id)

    # ── the inventory, from the plan ─────────────────────────────────────
    if ctx.has_checkpoint(OBJECT_PLAN) and not force:
        plan = ObjectPlan.model_validate(ctx.read_json(OBJECT_PLAN))
        ctx.emit("elements.plan", f"checkpoint present, {len(plan.items)} planned piece(s) reused")
    else:
        provider = get_provider()
        plan = provider.plan_objects(analysis, style, bundle)
        plan.version = ctx.projects.next_analysis_version(ctx.project_id, "object_plan")
        ctx.write_json(OBJECT_PLAN, plan)
        ctx.projects.add_analysis(ctx.project_id, "object_plan", OBJECT_PLAN, plan.version)
        ctx.mark_checkpoint("object_plan")
        ctx.emit("elements.plan", f"{len(plan.items)} piece(s) planned from photos and brief")

    definitions, instances = definitions_from_plan(plan)
    multi = [d for d in definitions if d.instance_count > 1]
    ctx.emit("elements.identity",
             f"{len(definitions)} canonical piece(s), {len(instances)} instance(s)"
             + (", " + ", ".join(f"{d.instance_count}x {d.semantic_type.replace('_', ' ')}"
                                 for d in multi) if multi else ""))

    available = settings.scene_image_enabled and local_image.available()
    result = ElementImageSet(definitions=definitions, instances=instances,
                             provider=settings.scene_image_model if available else "unavailable")

    if not available:
        result.warnings.append("local image generation is disabled or not installed; "
                               "definitions were written without pictures")
        ctx.write_json(ELEMENT_IMAGES, result)
        ctx.mark_checkpoint("element_images")
        return _summary(result, painted=0, reused=0, failed=0)

    # ── one picture per piece ────────────────────────────────────────────
    prior = {im.element_id: im for im in _prior_images(ctx)}
    crops = {i.object_key: i.crop_ref for i in plan.items if i.crop_ref}
    painted = reused = failed = 0
    t0 = time.monotonic()
    try:
        for d in definitions:
            image, was_reused = _paint(ctx, d, style, settings, prior.get(d.element_id), crops,
                                       force, element_prompt_sd, ELEMENT_NEGATIVE, local_image)
            result.images.append(image)
            if image.error:
                failed += 1
            elif was_reused:
                reused += 1
            else:
                painted += 1
    finally:
        local_image.unload()

    result.warnings += [f"{im.element_id}: {im.error}" for im in result.images if im.error]
    ctx.write_json(ELEMENT_IMAGES, result)
    ctx.mark_checkpoint("element_images")
    ctx.emit("elements.images",
             f"{painted} painted, {reused} up to date, {failed} failed "
             f"in {int(time.monotonic() - t0)}s",
             status="ok" if not failed else "warning")
    return _summary(result, painted=painted, reused=reused, failed=failed)


def _prior_images(ctx: JobContext) -> list[ElementImage]:
    if not ctx.has_checkpoint(ELEMENT_IMAGES):
        return []
    try:
        return ElementImageSet.model_validate(ctx.read_json(ELEMENT_IMAGES)).images
    except Exception:                                                     # noqa: BLE001
        return []


def _paint(ctx, d: ElementDefinition, style: StyleSpec, settings, prior, crops: dict[str, str],
           force: bool, element_prompt_sd, negative: str, local_image) -> tuple[ElementImage, bool]:
    """One piece. Never raises: a failed piece keeps its definition and says why.
    Returns (image, reused)."""
    from ...intelligence.scene_reading import canonical_key_for

    rel = _image_rel(d.element_id)
    dest = ctx.path(rel)
    prompt = element_prompt_sd(d.semantic_type, d.canonical_name, d.material, style.tags)
    # the plan item that carried a crop of the client's own photo, if any
    reference = next((crops[k] for k in d.source_element_ids if k in crops), "")
    scale = settings.scene_image_reference_scale if reference else 0.0
    seed = _seed_for(d.element_id)
    key = canonical_key_for(d.room_id, d.semantic_type, d.material, d.color, d.dimensions_m,
                            d.source_element_ids[0] if d.source_element_ids else d.element_id)

    image = ElementImage(
        element_image_id="eim_" + hashlib.sha1(f"{d.element_id}|{RECIPE_VERSION}".encode()).hexdigest()[:10],
        element_id=d.element_id, canonical_key=key, image_ref=rel, prompt=prompt,
        negative_prompt=negative, seed=seed, reference_ref=reference, reference_scale=scale,
        model=settings.scene_image_model)

    if (dest.exists() and not force and prior is not None
            and prior.element_image_id == image.element_image_id and prior.checksum):
        image.checksum = prior.checksum
        return image, True

    try:
        ref_path = ctx.path(reference) if reference else None
        gen = local_image.generate(
            prompt, model=settings.scene_image_model, negative_prompt=negative,
            steps=settings.scene_image_steps, width=512, height=512, seed=seed,
            references=[ref_path] if ref_path is not None and ref_path.exists() else None,
            reference_scale=scale)
        local_image.write(gen, dest)
        image.checksum = hashlib.sha1(dest.read_bytes()).hexdigest()
        ctx.add_output("element_image", rel, {
            "element_id": d.element_id, "semantic_type": d.semantic_type, "seed": seed,
            "reference": reference, "recipe_version": RECIPE_VERSION, "prompt": prompt})
        ctx.emit("elements.image", f"{d.semantic_type.replace('_', ' ')}: "
                 + (f"conditioned on {reference}" if reference else "from the brief alone"))
    except Exception as exc:                                              # noqa: BLE001
        image.error = f"{type(exc).__name__}: {exc}"
        ctx.log.exception("%s: element image failed", d.element_id)
        ctx.emit("elements.image", f"{d.semantic_type.replace('_', ' ')}: no image — {exc}",
                 status="warning")
    return image, False


def _summary(result: ElementImageSet, *, painted: int, reused: int, failed: int) -> dict[str, Any]:
    return {
        "definitions": len(result.definitions),
        "instances": len(result.instances),
        "images": sum(1 for im in result.images if not im.error),
        "painted": painted, "reused": reused, "failed": failed,
        "warnings": result.warnings,
    }

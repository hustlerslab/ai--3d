"""Stage 8b (optional): generate the sculptural pieces the ladder flagged.

The asset decision ladder's rung 5 marks a unique or sculptural item
`strategy="generated"` and writes a `generation_prompt`, but hands back a
procedural stand-in so the pipeline never blocks on a vendor. This job turns
that promise into a model: it submits each prompt to Meshy, waits, runs the
result through the shared asset pipeline, and swaps the stand-in for the real
thing through the normal patch path.

Checkpoint: `assets/generated/<object_key>.glb`. Its presence means that piece
is done, so a restart or a re-run never re-spends credits on it.

Degradation is the point. A vendor failure on one piece keeps that piece's
stand-in and moves on; running out of credits stops the batch but still commits
whatever already succeeded. The job fails outright only if Meshy is not
configured at all, which is a caller error rather than a vendor one.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from ...assets import pipeline as asset_pipeline
from ...assets.schema import AssetSource, IngestMeta
from ...core.config import Settings, get_settings
from ...spend import check_budget, record_spend
from .generate_elements import CREDITS_PER_PIECE
from ...intelligence import AssetPlan
from ...intelligence.schema import AssetDecision
from ...projects.layout import file_url
from ...providers import meshy
from ...scene.patches import Patch, PatchError, ReplaceAssetOp, commit_patch
from ...scene.store import get_store
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

ASSET_PLAN = "planning/asset_plan.json"


class MeshyNotConfigured(Exception):
    pass


class PlanRequired(Exception):
    pass


def _safe(object_key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in object_key)


def _glb_rel(object_key: str) -> str:
    return f"assets/generated/{_safe(object_key)}.glb"


def _asset_id(project_id: str, object_key: str) -> str:
    return f"gen_{project_id[-8:]}_{_safe(object_key)}".lower()


def _pending(plan: AssetPlan, ctx: JobContext, limit: int) -> list[AssetDecision]:
    """Decisions that asked for generation and have not been generated yet."""
    out: list[AssetDecision] = []
    for d in plan.decisions:
        if d.strategy != "generated" or not d.generation_prompt.strip():
            continue
        if ctx.has_checkpoint(_glb_rel(d.object_key)):
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


async def _generate_one(
    client: httpx.AsyncClient, ctx: JobContext, decision: AssetDecision, settings: Settings
) -> tuple[str, int]:
    """Submit, wait, download, ingest. Returns (asset_id, credits spent)."""

    def progress(status: str, pct: int) -> None:
        ctx.emit("generate.task", f"{decision.object_key}: {status.lower()} {pct}%")

    task_id = await meshy.submit_text_to_3d(
        client,
        decision.generation_prompt,
        mode=settings.meshy_mode,
        art_style=settings.meshy_art_style,
        should_remesh=settings.meshy_should_remesh,
        target_polycount=settings.meshy_target_polycount,
    )
    ctx.emit("generate.submit", f"{decision.object_key}: task {task_id}")

    model = await meshy.wait_for(
        client,
        task_id,
        timeout_seconds=float(settings.meshy_timeout_seconds),
        poll_seconds=float(settings.meshy_poll_seconds),
        on_progress=progress,
    )

    dest = ctx.path(_glb_rel(decision.object_key))
    await meshy.download_glb(client, model.glb_url, dest)
    # P1-ASSET-004: the preview lives beside the mesh, never as a vendor URL.
    thumb_rel = _glb_rel(decision.object_key)[:-4] + ".thumb.png"
    thumbnail = await meshy.download_thumbnail(client, model.thumbnail_url, ctx.path(thumb_rel))

    # The same ingestion every other model goes through: parse, measure,
    # normalize to the decision's target size, validate, register.
    record = asset_pipeline.ingest_file(
        dest,
        IngestMeta(
            asset_id=_asset_id(ctx.project_id, decision.object_key),
            name=decision.asset_name or decision.semantic_type.replace("_", " "),
            semantic_type=decision.semantic_type,
            expected_dimensions=decision.dimensions,
            mount=decision.mount,  # type: ignore[arg-type]
            color=decision.color,
            project_id=ctx.project_id,
            source=AssetSource(
                provider="meshy",
                source_id=model.task_id,
                url=f"{meshy.BASE}/openapi/v2/text-to-3d/{model.task_id}",
                license=meshy.LICENSE,
                license_url=meshy.LICENSE_URL,
                creator="Meshy",
                thumbnail_url=file_url(ctx.project_id, thumb_rel) if thumbnail else "",
            ),
        ),
    )
    # A hard validation failure registers the record but writes no normalized
    # glb (assets/pipeline.py), so the asset id resolves to nothing. Swapping a
    # working stand-in for it would break the scene — treat it as a failure and
    # say why, rather than reporting a success the viewer cannot load.
    if record.status == "failed":
        why = "; ".join(i.message for i in record.validation if i.severity == "hard")
        # The checkpoint IS the file, so a rejected download must not survive:
        # left on disk it reads as "already done" and _pending() would skip this
        # piece on every future run, stranding the stand-in with no retry.
        dest.unlink(missing_ok=True)
        raise meshy.MeshyError(f"generated model failed ingest validation: {why}")
    why = asset_pipeline.persisted(record, dest)
    if why:
        # P1-ASSET-004: no checkpoint until the bytes are ours; the piece is
        # retried and downloaded again while the vendor still has the file.
        dest.unlink(missing_ok=True)
        raise meshy.MeshyError(f"mesh not persisted: {why}")

    ctx.mark_checkpoint(_glb_rel(decision.object_key))
    return record.asset_id, model.credits


async def _run(ctx: JobContext, todo: list[AssetDecision], settings: Settings) -> dict[str, Any]:
    generated: dict[str, str] = {}
    warnings: list[str] = []
    credits = 0

    async with meshy.make_client(
        settings.meshy_api_key.get_secret_value(), float(settings.meshy_timeout_seconds)
    ) as client:
        try:
            ctx.emit("generate.balance", f"{await meshy.balance(client)} credit(s) before this batch")
        except meshy.MeshyError as exc:      # never block a batch on a status read
            ctx.emit("generate.balance", f"balance unavailable: {exc}", status="warning")

        for decision in todo:
            try:
                asset_id, spent = await _generate_one(client, ctx, decision, settings)
                credits += spent
                # Written the moment the provider confirms, not at the end of
                # the batch: a crash in between would lose money genuinely
                # spent, and a limit that forgets charges is not a limit.
                record_spend(
                    ctx.project_id, spent,
                    user_id=ctx.job.created_by or None,
                    job_id=ctx.job.job_id,
                    item_key=decision.object_key,
                )
                generated[decision.object_key] = asset_id
                ctx.emit("generate.done", f"{decision.object_key} -> {asset_id} ({spent} credit(s))")
            except meshy.MeshyOutOfCredits as exc:
                warnings.append(f"{decision.object_key}: {exc}")
                ctx.emit("generate.credits", f"stopping batch: {exc}", status="warning")
                break                        # every remaining item hits the same wall
            except meshy.MeshyError as exc:
                warnings.append(f"{decision.object_key}: {exc}")
                ctx.emit("generate.failed", f"{decision.object_key}: {exc}; keeping the stand-in", status="warning")
            except Exception as exc:         # network, disk, a malformed glb
                # The event and the warning both carry only the message; without
                # the stack a failure here is as opaque as the moodboard one was.
                ctx.log.exception("%s: generation failed", decision.object_key)
                warnings.append(f"{decision.object_key}: {type(exc).__name__}: {exc}")
                ctx.emit("generate.failed", f"{decision.object_key}: {exc}; keeping the stand-in", status="warning")

    return {"generated": generated, "warnings": warnings, "credits": credits}


@register(
    "generate_assets",
    lane=JobLane.ai,
    max_attempts=2,
    description="Generate the sculptural pieces the asset ladder flagged (Meshy)",
)
def generate_assets(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    if not settings.meshy_configured:
        raise MeshyNotConfigured("MESHY_API_KEY is not set; nothing to generate with")
    if not ctx.has_checkpoint(ASSET_PLAN):
        raise PlanRequired("run scene_plan first: planning/asset_plan.json missing")

    plan = AssetPlan.model_validate(ctx.read_json(ASSET_PLAN))
    limit = max(0, int(ctx.params.get("limit", settings.meshy_max_per_project)))
    todo = _pending(plan, ctx, limit)
    if not todo:
        ctx.emit("generate.skip", "no pieces are waiting on generation")
        return {"generated": {}, "warnings": [], "credits": 0, "replaced": 0}

    # P0-SEC-003. `limit` caps this ONE job and resets with the next; this caps
    # the project and the user for good, read from the persisted ledger.
    budget = check_budget(
        ctx.project_id,
        ctx.job.created_by or None,
        pieces=len(todo),
        credits_per_piece=CREDITS_PER_PIECE,
        project_cap=settings.meshy_max_credits_per_project,
        user_cap=settings.meshy_max_credits_per_user,
    )
    capped = 0
    if budget.blocked:
        capped = len(todo) - budget.allowed
        todo = todo[:budget.allowed]
        ctx.emit(
            "generate.capped",
            f"spend cap reached: {capped} piece(s) held back. {budget.reason}. "
            "The plan and every asset already placed are untouched.",
            status="warning",
        )
        if not todo:
            return {"generated": {}, "warnings": [f"spend cap reached: {budget.reason}"],
                    "credits": 0, "replaced": 0, "held_by_spend_cap": capped}

    ctx.emit("generate.start", f"{len(todo)} piece(s) to generate, mode={settings.meshy_mode}")
    result = asyncio.run(_run(ctx, todo, settings))
    generated: dict[str, str] = result["generated"]

    # Swap the stand-ins for the real models through the normal patch path, so
    # the same validation applies as to any other asset replacement.
    replaced = 0
    if generated and ctx.project.scene_ids:
        store = get_store()
        scene = store.load(ctx.project.scene_ids[-1])
        ops = [
            ReplaceAssetOp(object_id=obj.object_id, asset_id=generated[obj.plan_key])
            for obj in scene.objects
            if obj.plan_key in generated and not obj.locked
        ]
        if ops:
            try:
                commit_patch(store, Patch(
                    scene_id=scene.scene_id, base_version=scene.version,
                    operations=ops, source="system",
                ))
                replaced = len(ops)
            except PatchError as exc:
                result["warnings"].append(f"replacement rejected: {exc.message}")
                ctx.emit("generate.replace", f"rejected: {exc.message}", status="warning")

    # Record what was generated against the plan so a re-plan can see it.
    for d in plan.decisions:
        if d.object_key in generated:
            d.asset_id = generated[d.object_key]
            d.has_model = True
            d.reason = "generated by Meshy and normalized through the asset pipeline"
    plan.warnings = list(dict.fromkeys(list(plan.warnings) + result["warnings"]))
    ctx.write_json(ASSET_PLAN, plan)

    ctx.emit(
        "generate.summary",
        f"{len(generated)} generated, {replaced} placed, {result['credits']} credit(s) spent"
        + (f", {len(result['warnings'])} warning(s)" if result["warnings"] else ""),
    )
    return {**result, "replaced": replaced, "held_by_spend_cap": capped,
            "project_credits_spent": budget.project_spent + result["credits"],
            "project_credit_cap": budget.project_cap}

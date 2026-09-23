"""Stages 6–9: object plan → asset plan → compiled Scene (committed via patches).

Checkpoints: planning/object_plan.json, planning/asset_plan.json,
planning/scene_spec.json (a snapshot of the committed Scene). `resolve_assets`
re-runs the asset decision on the current scene after user edits.
"""
from __future__ import annotations

from typing import Any

from ...intelligence import (
    AssetPlan,
    DesignAnalysis,
    ObjectPlan,
    StyleSpec,
    build_input_bundle,
    get_provider,
)
from ...intelligence.schema import ObjectPlanItem
from ...planning import compile_scene, decide_asset, place_objects, resolve_plan
from ...intelligence.design_intent import DesignIntentSet, merge_intents
from ...intelligence.reference_reader import classify_references
from ...planning.asset_decision import style_materials
from ...planning.intent_fidelity import visual_intent_fidelity
from ...planning.intent_resolution import ResolutionRung, apply_intents_to_plan, resolve_all
from ...planning.spatial_pipeline import repair_placement, spatial_check
from ...projects.schema import ProjectStage
from ...scene.patches import Patch, PatchError, ReplaceAssetOp, commit_patch
from ...scene.store import get_store
from ...spatial.validation import validate_scene
from ..context import JobContext
from ..registry import register
from ..schema import JobLane

SCENE_READING = "planning/scene_reading.json"
SPATIAL_GRAPH = "planning/spatial_graph.json"
OBJECT_PLAN = "planning/object_plan.json"
ASSET_PLAN = "planning/asset_plan.json"
SCENE_SPEC = "planning/scene_spec.json"
SPATIAL_CHECK = "planning/spatial_check.json"
SPATIAL_SCENE = "planning/spatial_scene.json"
DESIGN_INTENT = "planning/design_intent.json"
VISUAL_FIDELITY = "planning/visual_intent_fidelity.json"
ANALYSIS = "analysis/design_analysis.json"
STYLE = "analysis/style_spec.json"


class AnalysisRequired(Exception):
    pass


def _room_images(ctx: JobContext, analysis) -> dict:
    """room_id -> the approved render, for rooms that actually have one."""
    from ...intelligence.schema import MoodboardSpec

    path = ctx.path("analysis/moodboard_spec.json")
    if not path.exists():
        return {}
    board = MoodboardSpec.model_validate(ctx.read_json("analysis/moodboard_spec.json"))
    out = {}
    for scene in board.room_scenes:
        if not scene.url:
            continue
        # scene.url is a /files/... url; the file sits under the project dir
        rel = scene.url.split(f"{ctx.project_id}/", 1)[-1]
        candidate = ctx.path(rel)
        if candidate.is_file():
            out[scene.room_id] = candidate
    return out


def _write_spatial_graph(ctx: JobContext, reading) -> None:
    """Derive the arrangement graph from a reading and store it.

    Deterministic and free - no model call and no GPU - so it is safe to run on
    a cached reading as well as a fresh one. `detections=None` because the
    detector is still benchmark-only; the graph works without it and says so in
    its own warnings.

    Never raises: a plan must not fail because of a layer that only annotates.
    """
    try:
        from ...planning.spatial_graph import build_spatial_graph

        graph = build_spatial_graph(reading, provider=reading.provider)
        ctx.write_json(SPATIAL_GRAPH, graph)
        ctx.emit("plan.spatial",
                 f"{len(graph.nodes)} node(s), {len(graph.relations)} relation(s), "
                 f"{len(graph.groups)} group(s), {len(graph.conflicts)} conflict(s)")
    except Exception as exc:                               # noqa: BLE001
        ctx.emit("plan.spatial",
                 f"spatial reconciliation failed ({type(exc).__name__}: {exc}); "
                 f"the plan is unaffected", status="warning")


def _classify_references(ctx: JobContext, bundle, provider, *, force: bool) -> DesignIntentSet:
    """Every uploaded reference becomes typed design intent, cached like the
    moodboard reading.

    Classification costs one vision call per reference, so the checkpoint is
    reused - but ONLY while it still covers the project's current references.
    A photo uploaded after the last plan must not be ignored because an older
    classification happens to exist; that would be the silent reference loss
    this work exists to end, wearing a different hat.
    """
    current = [r.input_id for r in bundle.references]
    if ctx.has_checkpoint(DESIGN_INTENT) and not force:
        try:
            cached = DesignIntentSet.model_validate(ctx.read_json(DESIGN_INTENT))
        except Exception as exc:                                        # noqa: BLE001
            ctx.emit("plan.intent", f"could not read the cached design intent "
                                    f"({type(exc).__name__}); re-classifying", status="warning")
        else:
            if cached.reference_ids == current:
                ctx.emit("plan.intent", f"checkpoint present, {len(cached.intents)} intent(s) reused")
                return cached
            ctx.emit("plan.intent", f"references changed since the last classification "
                                    f"({len(cached.reference_ids)} -> {len(current)}); re-reading")

    if not current:
        ctx.emit("plan.intent", "no reference photos uploaded; the plan is brief-driven only")
        return DesignIntentSet()

    result = classify_references(bundle, provider)
    ctx.write_json(DESIGN_INTENT, result)
    ctx.mark_checkpoint("design_intent")
    counts: dict[str, int] = {}
    for intent in result.intents:
        counts[intent.reference_class.value] = counts.get(intent.reference_class.value, 0) + 1
    ctx.emit("plan.intent",
             f"{len(result.intents)} of {len(current)} reference(s) classified"
             + (f" ({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})" if counts else "")
             + (f"; {len(result.unread)} unread" if result.unread else ""))
    return result


def _carry_element_decisions(ctx: JobContext, reading) -> int:
    """Apply the client's pre-moodboard decisions to matching reading rows.

    Deterministic and id-based: a row inherits a decision only when its
    canonical key equals a decided definition's key. A row already decided by
    a human on the review screen is never overwritten.
    """
    from ...intelligence.schema import ElementImageSet
    from ...intelligence.scene_reading import canonical_key, canonical_key_for

    if not ctx.has_checkpoint("planning/element_images.json"):
        return 0
    try:
        images = ElementImageSet.model_validate(ctx.read_json("planning/element_images.json"))
    except Exception:                                                     # noqa: BLE001
        return 0
    decided: dict[str, bool] = {}
    for d in images.definitions:
        if d.approved is None:
            continue
        key = canonical_key_for(d.room_id, d.semantic_type, d.material, d.color, d.dimensions_m,
                                d.source_element_ids[0] if d.source_element_ids else d.element_id)
        decided[key] = d.approved
    if not decided:
        return 0
    carried = 0
    for el in reading.elements:
        if el.approved is not None:
            continue
        verdict = decided.get(canonical_key(el))
        if verdict is None:
            continue
        el.approved = verdict
        carried += 1
    return carried


def _read_scene(ctx: JobContext, analysis, style, provider, *, force: bool):
    """Read every approved room render into elements, crops and surfaces.

    Optional by design: a provider without the capability, or a project whose
    moodboard was never painted, yields an empty reading and the plan proceeds
    exactly as it did before. The reading enriches the plan; it is not a
    precondition for having one.
    """
    from ...intelligence.scene_reading import (
        carry_asset_bindings, check_element_crops, coerce_room_reading, element_inventory,
        ensure_anchors, estimate_dimensions, inventory_notes, resolve_elements,
        write_element_crops)
    from ...intelligence.schema import SceneReading
    from ...projects.layout import project_dir

    # P1-ASSET-001: a forced re-read replaces this file. Keep what it knew
    # about paid meshes, so the bindings can follow the pieces (below).
    previous = None
    if force and ctx.has_checkpoint(SCENE_READING):
        try:
            previous = SceneReading.model_validate(ctx.read_json(SCENE_READING))
        except Exception as exc:                                       # noqa: BLE001
            ctx.emit("plan.read", f"previous reading unreadable, nothing to carry: {exc}",
                     status="warning")

    if ctx.has_checkpoint(SCENE_READING) and not force:
        reading = SceneReading.model_validate(ctx.read_json(SCENE_READING))
        ctx.emit("plan.read", f"checkpoint present, skipped ({len(reading.elements)} element(s))")
        # A project read before the spatial layer existed has no graph, and
        # without this it would never get one: the read is skipped, so the
        # builder below is never reached. Deriving it costs nothing - no model
        # call, no GPU - and it is what the plan step then consumes.
        if not ctx.has_checkpoint(SPATIAL_GRAPH):
            _write_spatial_graph(ctx, reading)
        # Same reasoning as the graph above, for the render-frame anchors: a
        # project read before they existed would never get them, because the
        # read is skipped. The crop box is already stored, so this costs no
        # model call and no repaint - and it is why every project has anchors,
        # not only the ones read since.
        filled = ensure_anchors(reading, {r.room_id: r for r in analysis.rooms})
        if filled:
            ctx.write_json(SCENE_READING, reading)
            ctx.emit("plan.anchors",
                     f"{filled} element(s) given a position from their crop box (estimated, not read)")
        return reading

    images = _room_images(ctx, analysis)
    read = getattr(provider, "read_scene_elements", None)
    if not images or not callable(read):
        why = "no approved room images yet" if not images else f"{provider.label} cannot read renders"
        ctx.emit("plan.read", f"skipped — {why}", status="warning")
        return SceneReading(provider=getattr(provider, "label", "none"),
                            warnings=[f"scene reading skipped: {why}"])

    elements, surfaces, warnings = [], [], []
    for room in analysis.rooms:
        image = images.get(room.room_id)
        if image is None:
            warnings.append(f"{room.room_id}: no approved image; not read")
            continue
        raw = read(image, room, style, ctx.project.vertical) or {}
        # A failure and an empty room are different facts. Reporting "returned
        # nothing" for both is how a provider with no reader at all went
        # unnoticed: every project read zero elements and nothing said why.
        failure = raw.get("_error") if isinstance(raw, dict) else None
        if failure:
            warnings.append(f"{room.room_id}: read failed — {failure}")
            ctx.emit("plan.read", f"{room.name}: read failed — {failure}", status="warning")
            continue
        if not raw:
            warnings.append(f"{room.room_id}: the reader returned nothing")
            continue
        # A read that was recovered from a truncated answer is a success with a
        # caveat, not a clean one: fewer elements may have survived than the
        # model saw, and the reviewer should know before approving spend.
        for note in (raw.get("_warnings") or []) if isinstance(raw, dict) else []:
            warnings.append(f"{room.room_id}: {note}")
            ctx.emit("plan.read", f"{room.name}: {note}", status="warning")
        room_elements, room_surfaces = coerce_room_reading(raw, room, ctx.project.vertical, warnings)
        elements.extend(room_elements)
        if room_surfaces is not None:
            surfaces.append(room_surfaces)
        ctx.emit("plan.read", f"{room.name}: {len(room_elements)} element(s)")

    reading = SceneReading(elements=elements, surfaces=surfaces,
                           provider=getattr(provider, "label", "unknown"), warnings=warnings)
    root = project_dir(ctx.project_id)
    reading.warnings += write_element_crops(reading, images, root, force=force)
    # Second look at each crop on its own. A box can be structurally perfect
    # and around the wrong thing, and only a fresh look at the cut-out picture
    # can tell. Optional like the read itself: a provider that cannot do it
    # leaves every element `unchecked`, which the approval gate treats as
    # needing a human, not as a pass.
    # How big each piece really is, before anything is generated from it: the
    # mesh is scaled to this at ingest, and a per-type table cannot tell a
    # single bed from a king or size a range hood at all.
    sized = estimate_dimensions(reading, {r.room_id: r for r in analysis.rooms},
                                ctx.project.vertical, provider, reading.warnings)
    if sized:
        ctx.emit("plan.size", f"{sized} piece(s) measured in metres by the reader")

    if callable(getattr(provider, "check_element_crop", None)):
        tally = check_element_crops(
            reading, {r.room_id: r.type for r in analysis.rooms},
            ctx.project.vertical, root, provider)
        ctx.emit("plan.check", ", ".join(f"{n} {k}" for k, n in sorted(tally.items())) or "nothing to check",
                 status="warning" if tally.get("ok", 0) < sum(tally.values()) else "info")
    # Instance counts, AFTER every check has had its say - the number that
    # matters is how many survive to the plan, not how many boxes came back.
    # Three bar stools whose boxes each ran to the image edge reach the plan as
    # ONE piece; before this the other two left no trace anywhere.
    reading.inventory = element_inventory(reading)
    for note in inventory_notes(reading.inventory):
        ctx.emit("plan.inventory", note, status="warning")
    # Canonical identities: what each piece IS, with its instances. One
    # definition per piece however many times it appears, so three stools
    # become one generation and three placements.
    # Element-first: a decision the client made on the PICTURED piece carries
    # onto the moodboard rows that are the same piece, matched by canonical
    # key. The same stool is not asked about twice, and a piece they left out
    # is not quietly built because the render happened to contain it. Rows
    # the pictures did not cover stay undecided for the review screen.
    carried = _carry_element_decisions(ctx, reading)
    if carried:
        ctx.emit("plan.decisions", f"{carried} row(s) inherited the client's element decision")
        reading.inventory = element_inventory(reading)
    # P1-ASSET-001: meshes already bought follow the piece, not the box. Before
    # resolve_elements() so the definitions' canonical_asset_id sees them.
    if previous is not None and any(e.asset_id for e in previous.elements):
        from ...assets.registry import get_registry

        def _resolves(asset_id: str) -> bool:
            rec = get_registry().get(asset_id)
            return rec is not None and rec.status != "failed"

        kept = carry_asset_bindings(previous, reading, valid=_resolves)
        n = kept["carried"] + kept["carried_loose"]
        ctx.emit("plan.assets",
                 f"{n} mesh binding(s) carried across the re-read by canonical key"
                 + (f" ({kept['carried_loose']} by loose match)" if kept["carried_loose"] else "")
                 + (f"; {kept['unbound']} not matched - the piece changed or is gone"
                    if kept["unbound"] else ""),
                 status="warning" if kept["unbound"] else "info")
    reading.definitions, reading.instances = resolve_elements(reading)
    multi = [d for d in reading.definitions if d.instance_count > 1]
    if multi:
        ctx.emit("plan.identity",
                 f"{len(reading.definitions)} canonical piece(s), "
                 + ", ".join(f"{d.instance_count}x {d.semantic_type.replace('_', ' ')}"
                             for d in multi))

    reading.version = ctx.projects.next_analysis_version(ctx.project_id, "scene_reading")
    ctx.write_json(SCENE_READING, reading)

    # Spatial reconciliation: what the picture implies about ARRANGEMENT.
    #
    # Written, not yet consumed. The compiler still places from `against` and
    # `faces` exactly as before, so this changes no placement and no render -
    # it makes the structure inspectable while the coordinate solver that will
    # read it is still to be built. `detections=None` because the detector is
    # benchmark-only; the graph works without it and says so in its warnings.
    _write_spatial_graph(ctx, reading)
    ctx.projects.add_analysis(ctx.project_id, "scene_reading", SCENE_READING, reading.version)
    ctx.mark_checkpoint("scene_reading")
    cut = sum(1 for e in reading.elements if e.crop_ref)
    ctx.emit(
        "plan.read",
        f"{len(reading.elements)} element(s) across {len(images)} room(s), {cut} crop(s) cut, "
        f"{len(reading.surfaces)} surface set(s)",
    )
    return reading


def _load_specs(ctx: JobContext) -> tuple[DesignAnalysis, StyleSpec]:
    if not ctx.has_checkpoint(ANALYSIS) or not ctx.has_checkpoint(STYLE):
        raise AnalysisRequired("run the analyze job first: analysis/design_analysis.json or style_spec.json missing")
    return DesignAnalysis.model_validate(ctx.read_json(ANALYSIS)), StyleSpec.model_validate(ctx.read_json(STYLE))


@register(
    "scene_plan",
    lane=JobLane.ai,
    max_attempts=2,
    stage_running=ProjectStage.ASSET_PLANNING,
    stage_done=ProjectStage.ASSETS_READY,
    description="Object plan → asset resolution → compiled Scene",
    uses_intelligence=True,
)
def scene_plan(ctx: JobContext) -> dict[str, Any]:
    force = bool(ctx.params.get("force", False))
    # Re-reading the moodboard is NOT part of "force". It calls the vision model
    # again, and because the answer is non-deterministic the new elements get
    # new ids and new names — which discards every approval a human made and
    # orphans every mesh already bought from those crops. Forcing a re-plan cost
    # 12 approvals and re-priced 7 pieces we already owned at 210 credits before
    # this was separated. Ask for it explicitly.
    force_read = bool(ctx.params.get("force_read", False))
    analysis, style = _load_specs(ctx)
    bundle = build_input_bundle(ctx.project_id)
    provider = get_provider()
    warnings: list[str] = []

    # ── design intent from the client's OWN reference photos ─────────────
    # Runs before anything reads a render. This is the channel that does not
    # pass through Stable Diffusion: each uploaded reference is classified on
    # its own, so "the sofa I own" stays distinguishable from "a mood I like"
    # all the way to asset resolution.
    intent_set = _classify_references(ctx, bundle, provider, force=force_read)
    warnings += intent_set.warnings

    # ── read the approved moodboard ──────────────────────────────────────
    reading = _read_scene(ctx, analysis, style, provider, force=force_read)
    warnings += reading.warnings

    # ── object plan ──────────────────────────────────────────────────────
    if ctx.has_checkpoint(OBJECT_PLAN) and not force:
        plan = ObjectPlan.model_validate(ctx.read_json(OBJECT_PLAN))
        ctx.emit("plan.objects", "checkpoint present, skipped")
    else:
        plan = provider.plan_objects(analysis, style, bundle)
        # The approved render decides what is in the rooms it shows; the brief
        # keeps the rooms it does not. Free, and not gated on approval -
        # approval gates SPENDING, which is the generate_elements job.
        from ...intelligence.scene_reading import merge_reading_into_plan

        plan, merge_notes = merge_reading_into_plan(plan, reading)
        for note in merge_notes:
            ctx.emit("plan.merge", note)

        # Fill the relation fields the merge above leaves empty.
        #
        # `merge_reading_into_plan` builds items from the render but sets neither
        # `relation` nor `support_key`, so every moodboard-derived piece reached
        # the compiler with no relationship at all - while `_relation_candidates`
        # and `_pick_support` sat there ready to use them. This attaches what the
        # spatial graph already worked out. It computes no coordinate: the
        # compiler still decides every metre, exactly as before.
        #
        # Skipped silently when there is no graph, so a project planned before
        # this existed replans unchanged.
        if ctx.has_checkpoint(SPATIAL_GRAPH):
            try:
                from ...intelligence.schema import SpatialGraph
                from ...planning.spatial_graph import apply_spatial_graph

                graph = SpatialGraph.model_validate(ctx.read_json(SPATIAL_GRAPH))
                plan, spatial_notes = apply_spatial_graph(plan, graph)
                for note in spatial_notes:
                    ctx.emit("plan.spatial", note)
            except Exception as exc:                       # noqa: BLE001
                ctx.emit("plan.spatial",
                         f"could not attach the spatial graph ({type(exc).__name__}: {exc}); "
                         f"the plan is unchanged", status="warning")

        # The client's own references apply LAST, and that ordering is the
        # whole point. `merge_reading_into_plan` above REPLACES a room's items
        # with what a vision model read out of an SD render, and before P12
        # that render was the only channel a reference had - so a photograph of
        # the client's actual sofa was outranked by a guess about a picture of
        # a sofa. Applying intent after the merge makes the order
        #   planner inference -> render reading -> spatial evidence -> the
        #   client's own photo
        # without touching the round-trip, which other production behaviour
        # still depends on. Reconciliation, not addition: an intent whose
        # category is already in the room enriches that item instead of adding
        # a second one, and an uncertain or contradicted intent is held back
        # for a human rather than guessed at.
        merged = merge_intents(intent_set.intents)
        room_for = {r.name.lower(): r.room_id for r in analysis.rooms}
        room_for.update({r.type.replace("_", " "): r.room_id for r in analysis.rooms})
        default_room = analysis.rooms[0].room_id if analysis.rooms else ""
        plan.items, intent_notes = apply_intents_to_plan(list(plan.items), merged, room_for,
                                                         default_room_id=default_room)
        for note in intent_notes:
            ctx.emit("plan.intent", note)
        held = [m for m in merged if m.uncertain]
        for m in held:
            ctx.emit("plan.intent",
                     f"{m.object_category or 'reference'}: held back for input "
                     f"({m.conflicts[0].message if m.conflicts else 'not classified with confidence'})",
                     status="warning")

        plan.version = ctx.projects.next_analysis_version(ctx.project_id, "object_plan")
        ctx.write_json(OBJECT_PLAN, plan)
        ctx.projects.add_analysis(ctx.project_id, "object_plan", OBJECT_PLAN, plan.version)
        ctx.mark_checkpoint("object_plan")
        ctx.emit(
            "plan.objects",
            f"{len(plan.items)} item(s) across {len(plan.rooms)} room(s) via {plan.provider} "
            f"[vertical={ctx.project.vertical.value}]",
        )
    warnings += plan.warnings

    # ── asset plan ───────────────────────────────────────────────────────
    if ctx.has_checkpoint(ASSET_PLAN) and not force:
        assets = AssetPlan.model_validate(ctx.read_json(ASSET_PLAN))
        ctx.emit("plan.assets", "checkpoint present, skipped")
    else:
        # Meshes already made from these elements' own crops outrank the
        # catalog: the client chose that piece, everything else is a substitute.
        element_assets = {e.element_id: e.asset_id for e in reading.elements if e.asset_id}
        assets = resolve_plan(plan, style, element_assets)
        if element_assets:
            ctx.emit("plan.assets", f"{len(element_assets)} element(s) carry a generated mesh")
        assets.version = ctx.projects.next_analysis_version(ctx.project_id, "asset_plan")
        ctx.write_json(ASSET_PLAN, assets)
        ctx.projects.add_analysis(ctx.project_id, "asset_plan", ASSET_PLAN, assets.version)
        ctx.mark_checkpoint("asset_plan")
        ctx.emit("plan.assets", ", ".join(f"{k}={v}" for k, v in sorted(assets.counts.items())))
    warnings += assets.warnings

    # ── scene ────────────────────────────────────────────────────────────
    store = get_store()
    if ctx.has_checkpoint(SCENE_SPEC) and not force:
        snapshot = ctx.read_json(SCENE_SPEC)
        scene = store.load(snapshot["scene_id"])
        ctx.emit("plan.scene", f"checkpoint present, skipped (scene {scene.scene_id} v{scene.version})")
    else:
        scene, layout_warnings = compile_scene(ctx.project_id, analysis, style,
                                               name=f"{ctx.project.name} · {style.name}", reading=reading)
        warnings += layout_warnings
        store.create(scene)
        ctx.emit("plan.scene", f"{len(scene.rooms)} room(s), {len(scene.walls)} wall(s), {len(scene.openings)} opening(s) laid out")

        ops, place_warnings = place_objects(scene, plan, assets, reading=reading)
        warnings += place_warnings
        # P4 repair between the solver and the commit gate: only objects in
        # hard violation move, only to positions validate_object accepts.
        ops, repair = repair_placement(scene, ops)
        ctx.emit("plan.repair", f"{repair['terminal_state']} · hard {repair['hard_before']} -> {repair['hard_after']}"
                                f" · moved {len(repair['moved'])}")
        committed = _commit_with_retry(store, scene, ops, warnings)
        scene = committed
        ctx.write_json(SCENE_SPEC, scene)
        ctx.projects.attach_scene(ctx.project_id, scene.scene_id)
        ctx.projects.add_scene_spec(ctx.project_id, scene.scene_id, scene.version, SCENE_SPEC)
        ctx.mark_checkpoint("scene_spec")
        # P1-IDENTITY-005: refresh the identity index now that both files it is
        # derived from are on disk. A failure here must not fail the plan — the
        # index is a cache of what the files already say, and `ensure_indexed()`
        # rebuilds it on the next read.
        try:
            from ...provenance import index_project

            counts = index_project(ctx.project_id)
            ctx.emit("plan.provenance",
                     f"{counts['elements']} element(s), {counts['instances']} instance(s) indexed"
                     f" · {counts['placed']} placed")
        except Exception as exc:                               # noqa: BLE001
            ctx.emit("plan.provenance", f"identity index not refreshed: {exc}", status="warning")
        ctx.emit("plan.scene", f"{len(scene.objects)} object(s) placed and validated · scene {scene.scene_id} v{scene.version}")
        # Independent intent evaluation (P8, read-only) + P7 spatial scene of the
        # committed result; refreshed only when the scene itself was rebuilt.
        check, canonical = spatial_check(scene, plan, repair)
        ctx.write_json(SPATIAL_CHECK, check)
        ctx.write_json(SPATIAL_SCENE, canonical)
        ctx.mark_checkpoint("spatial_check")
        intent = check["intent"]
        ctx.emit("plan.intent", f"{intent['satisfied']} satisfied · {intent['violated']} violated · "
                                f"{intent['unknown']} unknown · {sum(intent['unsupported_relations'].values())} unsupported")

    # ── did the client's references survive into the scene? ──────────────
    # Measured against the COMMITTED scene, not against the plan: a field that
    # only exists in an intermediate object has not survived. Read-only.
    from ...core.config import get_settings

    resolutions = resolve_all(merge_intents(intent_set.intents), style,
                              generation_available=get_settings().meshy_configured)
    fidelity = visual_intent_fidelity(intent_set, resolutions, scene)
    ctx.write_json(VISUAL_FIDELITY, {**fidelity.model_dump(),
                                     "resolutions": [r.model_dump() for r in resolutions]})
    ctx.mark_checkpoint("visual_intent_fidelity")
    for res in resolutions:
        if res.rung is ResolutionRung.GENERATE and res.generation:
            ctx.emit("plan.intent",
                     f"{res.object_category}: no compatible asset - generation requested "
                     f"({res.generation.prompt})")
        elif res.needs_input:
            ctx.emit("plan.intent", f"{res.object_category}: unresolved - {res.reason}",
                     status="warning")
    if intent_set.intents:
        ctx.emit("plan.intent",
                 "fidelity " + ", ".join(f"{k}={v}" for k, v in sorted(fidelity.metrics.items())
                                         if v is not None))

    violations = validate_scene(scene)
    hard = [v for v in violations if v.severity == "hard"]
    strategies: dict[str, int] = {}
    for o in scene.objects:
        strategies[o.source_strategy] = strategies.get(o.source_strategy, 0) + 1
    check = ctx.read_json(SPATIAL_CHECK) if ctx.has_checkpoint(SPATIAL_CHECK) else None
    return {
        "scene_id": scene.scene_id,
        "scene_version": scene.version,
        "rooms": len(scene.rooms),
        "objects": len(scene.objects),
        "strategies": strategies,
        "hard_violations": len(hard),
        "planned_items": len(plan.items),
        "repair": {k: v for k, v in (check or {}).get("repair", {}).items() if k != "records"} if check and check.get("repair") else None,
        "intent": {k: v for k, v in (check or {}).get("intent", {}).items() if k != "results"} if check else None,
        "design_intent": {
            "references": len(intent_set.reference_ids),
            "classified": len(intent_set.intents),
            "unread": len(intent_set.unread),
            "conflicts": len(intent_set.conflicts),
            "needs_input": len(intent_set.needing_input()),
        },
        "visual_intent_fidelity": fidelity.metrics,
        "generation_requests": [
            {"object_category": r.object_category, "prompt": r.generation.prompt,
             "source_intent_ids": r.generation.source_intent_ids}
            for r in resolutions if r.rung is ResolutionRung.GENERATE and r.generation],
        "unresolved_intents": [
            {"object_category": r.object_category, "reason": r.reason}
            for r in resolutions if r.needs_input],
        "warnings": list(dict.fromkeys(warnings)),
    }


def _commit_with_retry(store, scene, ops, warnings: list[str], attempts: int = 4):
    """Commit the add operations; on hard violations drop the offending
    objects and retry, so one bad placement never blocks the whole scene."""
    current = ops
    for _ in range(attempts):
        if not current:
            return store.load(scene.scene_id)
        patch = Patch(scene_id=scene.scene_id, base_version=store.load(scene.scene_id).version, operations=current, source="system")
        try:
            return commit_patch(store, patch)
        except PatchError as exc:
            bad = {v.object_id for v in exc.violations if v.object_id} | {v.related_id for v in exc.violations if v.related_id}
            if not bad:
                raise
            dropped = [op for op in current if op.object.object_id in bad]
            for op in dropped:
                warnings.append(f"dropped {op.object.semantic_type} ({op.object.plan_key}): {exc.message}")
            current = [op for op in current if op.object.object_id not in bad]
    return store.load(scene.scene_id)


@register(
    "resolve_assets",
    lane=JobLane.ai,
    max_attempts=2,
    description="Re-run the asset decision on the current scene (after edits)",
    uses_intelligence=True,
)
def resolve_assets(ctx: JobContext) -> dict[str, Any]:
    analysis, style = _load_specs(ctx)
    if not ctx.project.scene_ids:
        raise AnalysisRequired("project has no scene yet: run scene_plan first")
    store = get_store()
    scene = store.load(ctx.project.scene_ids[-1])
    roles = style_materials(style)
    decisions = []
    ops: list[ReplaceAssetOp] = []
    for obj in scene.objects:
        if obj.locked:
            continue
        item = ObjectPlanItem(
            object_key=obj.plan_key or obj.object_id,
            semantic_type=obj.semantic_type,
            room_id=obj.room_id,
            approx_dimensions=tuple(d * s for d, s in zip(obj.dimensions, obj.scale)),  # type: ignore[arg-type]
        )
        decision = decide_asset(item, style, roles=roles)
        decisions.append(decision)
        if decision.has_model and decision.asset_id and decision.asset_id != obj.asset_id:
            ops.append(ReplaceAssetOp(object_id=obj.object_id, asset_id=decision.asset_id))
    changed = 0
    if ops:
        try:
            scene = commit_patch(store, Patch(scene_id=scene.scene_id, base_version=scene.version, operations=ops, source="system"))
            changed = len(ops)
        except PatchError as exc:
            ctx.emit("resolve.assets", f"replacement rejected: {exc.message}", status="warning")
    assets = AssetPlan(decisions=decisions, counts={}, warnings=[])
    for d in decisions:
        assets.counts[d.strategy] = assets.counts.get(d.strategy, 0) + 1
    assets.version = ctx.projects.next_analysis_version(ctx.project_id, "asset_plan")
    ctx.write_json(ASSET_PLAN, assets)
    ctx.projects.add_analysis(ctx.project_id, "asset_plan", ASSET_PLAN, assets.version)
    ctx.write_json(SCENE_SPEC, scene)
    ctx.emit("resolve.assets", f"{changed} object(s) upgraded to registry models")
    return {"scene_id": scene.scene_id, "scene_version": scene.version, "replaced": changed, "counts": assets.counts}

"""HTTP API.

Response envelope matches the frontend client convention:
  reads  → {"success": true, "data": ...}
  writes → flat object with "success": true
  errors → {"success": false, "error": {code, message, retryable}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..assets import pipeline as asset_pipeline
from ..assets.registry import get_registry
from ..assets.schema import AssetSource, IngestMeta
from ..catalog.catalog import all_items, get_item, search
from ..core.config import get_settings
from ..materials import pipeline as material_pipeline
from ..materials.registry import get_material_registry
from ..providers import polyhaven
from ..design import service as design_service
from ..providers import gemini
from ..scene.patches import (
    Patch,
    PatchError,
    PatchOperation,
    commit_patch,
    preview_patch,
)
from ..projects import get_project_store
from ..scene.schema import SavedView, Scene, Vec3
from ..scene.store import SceneNotFound, VersionConflict, get_store
from ..seed import build_seed_scene
from ..spatial.validation import validate_scene
from ..walkthrough import service as walkthrough_service

router = APIRouter(prefix="/api")


from .envelope import error_response, ok  # noqa: E402  (shared envelope)


# ── Error handlers are registered in main.py ────────────────────────────


def _intelligence_status() -> dict:
    from ..intelligence import get_provider

    p = get_provider()
    return {"provider": p.name, "mode": p.mode, "model": p.label, "fallback_to_mock": p.allow_fallback}


_STARTED_AT = datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _git_sha() -> dict[str, str]:
    """The commit this process was started from, plus whether the tree was
    dirty. Read once: it cannot change without a restart, which is the point."""
    import subprocess

    root = get_settings().repo_root
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except Exception:                                  # noqa: BLE001
            return ""

    sha = run("rev-parse", "HEAD")
    return {
        "sha": sha[:12] or "unknown",
        "branch": run("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        # A dirty tree means the running process may differ from the commit
        # even when the sha matches, so say so rather than imply precision.
        "dirty": bool(run("status", "--porcelain")),
    }


def _runtime_status() -> dict:
    now = datetime.now(timezone.utc)
    git = _git_sha()
    return {
        "started_at": _STARTED_AT.isoformat(),
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "git": git,
        # The one question this endpoint exists to answer.
        "note": (
            "Code is loaded at start-up (no --reload). If files changed after "
            f"{_STARTED_AT.isoformat()}, restart the server before trusting behaviour."
        ),
    }


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "aether-walkthrough-backend",
        "version": "0.1.0",
        # Which code is actually RUNNING, not which code is on disk. The server
        # is launched without --reload (stale-route hang on Windows), so a
        # process can serve code that was edited hours ago and nothing says so.
        # That cost two full rounds of misdiagnosis: a deleted Gemini image path
        # kept answering because a process from before its removal was still up.
        "runtime": _runtime_status(),
        "providers": {
            "intelligence": _intelligence_status(),
            "gemini": gemini.status(),
            "meshy": {
                "provider": "meshy",
                "configured": settings.meshy_configured,
                "mode": "live" if settings.meshy_configured else "mock",
            },
            "blender": {
                "provider": "blender",
                "configured": settings.blender_configured,
                "mode": "live" if settings.blender_configured else "unavailable",
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Projects live in api/projects_routes.py (SQLite-backed) ─────────────

# ── Scenes ──────────────────────────────────────────────────────────────


class CreateSceneBody(BaseModel):
    project_id: str
    name: str = "New scene"
    from_seed: bool = True


@router.get("/scenes")
def list_scenes() -> dict:
    store = get_store()
    summaries = []
    for scene_id in store.list_scene_ids():
        try:
            scene = store.load(scene_id)
        except SceneNotFound:
            continue
        summaries.append(
            {
                "scene_id": scene.scene_id,
                "name": scene.name,
                "project_id": scene.project_id,
                "version": scene.version,
                "rooms": len(scene.rooms),
                "objects": len(scene.objects),
            }
        )
    return ok(summaries)


@router.post("/scenes")
def create_scene(body: CreateSceneBody) -> dict:
    store = get_store()
    scene = build_seed_scene(body.project_id)
    scene.scene_id = Scene(project_id=body.project_id).scene_id  # fresh id
    scene.name = body.name
    if not body.from_seed:
        scene.objects = []
    store.create(scene)
    get_project_store().attach_scene(body.project_id, scene.scene_id)
    return {"success": True, "scene": scene.model_dump()}


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: str) -> dict:
    scene = get_store().load(scene_id)
    history = get_store().history_info(scene_id)
    return ok({"scene": scene.model_dump(), "history": history})


@router.get("/scenes/{scene_id}/validate")
def validate(scene_id: str) -> dict:
    scene = get_store().load(scene_id)
    violations = validate_scene(scene)
    return ok(
        {
            "valid": not any(v.severity == "hard" for v in violations),
            "violations": [v.model_dump() for v in violations],
        }
    )


# ── Patches ─────────────────────────────────────────────────────────────


class PatchBody(BaseModel):
    base_version: int
    operations: list[PatchOperation]
    source: str = "user"


@router.post("/scenes/{scene_id}/patches")
def post_patch(scene_id: str, body: PatchBody) -> dict:
    patch = Patch(
        scene_id=scene_id,
        base_version=body.base_version,
        operations=body.operations,
        source=body.source,
    )
    scene = commit_patch(get_store(), patch)
    return {
        "success": True,
        "scene": scene.model_dump(),
        "version": scene.version,
        "history": get_store().history_info(scene_id),
    }


@router.post("/scenes/{scene_id}/patches/preview")
def post_patch_preview(scene_id: str, body: PatchBody) -> dict:
    patch = Patch(
        scene_id=scene_id,
        base_version=body.base_version,
        operations=body.operations,
        source=body.source,
    )
    result = preview_patch(get_store(), patch)
    return {
        "success": True,
        "valid": not any(v.severity == "hard" for v in result.violations),
        "violations": [v.model_dump() for v in result.violations],
    }


@router.post("/scenes/{scene_id}/undo")
def undo(scene_id: str) -> dict:
    scene = get_store().undo(scene_id)
    return {
        "success": True,
        "scene": scene.model_dump(),
        "history": get_store().history_info(scene_id),
    }


@router.post("/scenes/{scene_id}/redo")
def redo(scene_id: str) -> dict:
    scene = get_store().redo(scene_id)
    return {
        "success": True,
        "scene": scene.model_dump(),
        "history": get_store().history_info(scene_id),
    }


# ── Asset upgrade ───────────────────────────────────────────────────────


@router.post("/scenes/{scene_id}/assets/upgrade")
def upgrade_scene_assets(scene_id: str) -> dict:
    """Swap every parametric object for the best real model of its type.

    Each swap is tried on a working copy and validated individually — a
    real sofa is wider than the placeholder, so one that no longer fits its
    spot is skipped with a reason rather than failing the whole upgrade.
    Locked objects are left alone. The result commits as one patch.
    """
    from ..catalog.catalog import find_by_semantic
    from ..scene.patches import ReplaceAssetOp, apply_operations
    from ..spatial.validation import validate_object

    store = get_store()
    scene = store.load(scene_id)
    working = scene
    ops: list[PatchOperation] = []
    replaced: list[dict] = []
    skipped: list[dict] = []

    for obj in scene.objects:
        current = get_item(obj.asset_id) if obj.asset_id else None
        if current and current.model_url:
            continue
        if obj.locked:
            skipped.append({"object_id": obj.object_id, "reason": "locked"})
            continue
        best = find_by_semantic(obj.semantic_type)
        if best is None or not best.model_url:
            skipped.append({"object_id": obj.object_id, "reason": f"no real model for {obj.semantic_type}"})
            continue
        op = ReplaceAssetOp(object_id=obj.object_id, asset_id=best.asset_id)
        candidate = apply_operations(working, [op])
        swapped = candidate.object(obj.object_id)
        hard = [v for v in validate_object(candidate, swapped) if v.severity == "hard"] if swapped else []
        if hard:
            skipped.append({"object_id": obj.object_id, "reason": hard[0].message})
            continue
        working = candidate
        ops.append(op)
        replaced.append({"object_id": obj.object_id, "asset_id": best.asset_id, "name": best.name})

    if ops:
        scene = commit_patch(
            store,
            Patch(scene_id=scene_id, base_version=scene.version, operations=ops, source="system"),
        )
    return {
        "success": True,
        "scene": scene.model_dump(),
        "version": scene.version,
        "history": store.history_info(scene_id),
        "replaced": replaced,
        "skipped": skipped,
    }


# ── Walkthrough ─────────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/walkthrough/tour")
def tour(scene_id: str, seconds_per_room: float = 6.0) -> dict:
    scene = get_store().load(scene_id)
    path = walkthrough_service.generate_tour(scene, seconds_per_room)
    return ok(path.model_dump())


@router.get("/scenes/{scene_id}/walkthrough/spawn")
def spawn(scene_id: str) -> dict:
    scene = get_store().load(scene_id)
    position, look_at = walkthrough_service.spawn_point(scene)
    return ok({"position": position, "look_at": look_at})


class CheckPositionBody(BaseModel):
    x: float
    z: float


@router.post("/scenes/{scene_id}/walkthrough/check-position")
def check_position(scene_id: str, body: CheckPositionBody) -> dict:
    scene = get_store().load(scene_id)
    result = walkthrough_service.check_position(scene, body.x, body.z)
    return ok(result.model_dump())


class SavedViewBody(BaseModel):
    name: str
    position: Vec3
    target: Vec3
    mode: str = "orbit"


@router.get("/scenes/{scene_id}/walkthrough/views")
def list_views(scene_id: str) -> dict:
    scene = get_store().load(scene_id)
    return ok([v.model_dump() for v in scene.saved_views])


@router.post("/scenes/{scene_id}/walkthrough/views")
def save_view(scene_id: str, body: SavedViewBody) -> dict:
    store = get_store()
    scene = store.load(scene_id)
    view = SavedView(
        name=body.name,
        position=body.position,
        target=body.target,
        mode="first_person" if body.mode == "first_person" else "orbit",
    )
    scene.saved_views.append(view)
    store.commit(scene, base_version=scene.version)
    return {"success": True, "view": view.model_dump()}


# ── Design proposals ────────────────────────────────────────────────────


class ProposalBody(BaseModel):
    instruction: str


@router.post("/scenes/{scene_id}/design/proposals")
async def create_proposal(scene_id: str, body: ProposalBody) -> dict:
    scene = get_store().load(scene_id)
    proposal = await design_service.create_proposal(scene, body.instruction)
    preview = design_service.proposal_preview(scene, proposal)
    return {"success": True, **preview}


@router.post("/scenes/{scene_id}/design/proposals/{proposal_id}/apply")
def apply_proposal(scene_id: str, proposal_id: str) -> dict:
    proposal = design_service.get_proposal(proposal_id)
    if proposal is None or proposal.scene_id != scene_id:
        return error_response("PROPOSAL_NOT_FOUND", "Proposal not found.", 404)
    if proposal.status == "applied":
        return error_response("PROPOSAL_ALREADY_APPLIED", "Already applied.", 409)
    patch = Patch(
        scene_id=scene_id,
        base_version=proposal.base_version,
        operations=proposal.planned_patch or [],
        source="ai",
    )
    scene = commit_patch(get_store(), patch)
    proposal.status = "applied"
    design_service.save_proposal(proposal)
    return {
        "success": True,
        "scene": scene.model_dump(),
        "version": scene.version,
        "history": get_store().history_info(scene_id),
    }


@router.post("/scenes/{scene_id}/design/proposals/{proposal_id}/reject")
def reject_proposal(scene_id: str, proposal_id: str) -> dict:
    proposal = design_service.get_proposal(proposal_id)
    if proposal is None or proposal.scene_id != scene_id:
        return error_response("PROPOSAL_NOT_FOUND", "Proposal not found.", 404)
    proposal.status = "rejected"
    design_service.save_proposal(proposal)
    return {"success": True, "proposal_id": proposal_id, "status": "rejected"}


# ── Catalog ─────────────────────────────────────────────────────────────


@router.get("/catalog")
def catalog(
    q: str = "",
    room_type: Optional[str] = None,
    max_width: Optional[float] = None,
    max_price: Optional[int] = None,
    style: Optional[str] = None,
    require_model: bool = False,
    # A renderer asks for one project's catalog so it can resolve the generated
    # pieces that project's scene references. Searching without it never sees
    # them, which is what keeps one client's sofa out of another's results.
    project_id: str = "",
) -> dict:
    style_tags = [s.strip() for s in style.split(",")] if style else None
    if q or room_type or max_width or max_price or style_tags or require_model:
        items = search(q, room_type, max_width, max_price, style_tags, None, require_model)
    else:
        items = all_items(project_id)
    return ok([i.model_dump() for i in items])


@router.get("/catalog/{asset_id}")
def catalog_item(asset_id: str) -> dict:
    item = get_item(asset_id)
    if item is None:
        return error_response("ASSET_NOT_FOUND", f"No catalog item {asset_id}.", 404)
    return ok(item.model_dump())


# ── Assets (plan §14–16) ────────────────────────────────────────────────


@router.get("/assets")
def list_assets() -> dict:
    return ok([r.model_dump() for r in get_registry().list()])


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str) -> dict:
    record = get_registry().get(asset_id)
    if record is None:
        return error_response("ASSET_NOT_FOUND", f"No asset {asset_id}.", 404)
    return ok(record.model_dump())


@router.post("/assets/upload")
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(...),
    semantic_type: str = Form(...),
    asset_id: Optional[str] = Form(None),
    expected_width: Optional[float] = Form(None),
    expected_height: Optional[float] = Form(None),
    expected_depth: Optional[float] = Form(None),
    yaw_offset: float = Form(0.0),
    mount: str = Form("floor"),
    style_tags: str = Form(""),
    room_types: str = Form(""),
    price_inr: int = Form(0),
    color: str = Form("#8a7862"),
    license: str = Form("unknown"),
    creator: str = Form(""),
) -> dict:
    """Upload a .glb/.gltf (glTF with external files must be packed as GLB first).

    MIME/extension check → size limit → pipeline. Same path as every other source.
    """
    filename = file.filename or "upload.glb"
    if not filename.lower().endswith((".glb", ".gltf")):
        return error_response("UNSUPPORTED_FILE_TYPE", "Only .glb or .gltf files are accepted.", 415)
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        return error_response("FILE_TOO_LARGE", "Uploads are limited to 200 MB.", 413)
    slug = asset_id or f"asset_{asset_pipeline._slug(name)}"
    dest = get_registry().source_dir(slug) / filename
    dest.write_bytes(data)
    expected = (
        (expected_width, expected_height, expected_depth)
        if expected_width and expected_height and expected_depth
        else None
    )
    meta = IngestMeta(
        asset_id=slug,
        name=name,
        semantic_type=semantic_type,
        expected_dimensions=expected,
        yaw_offset=yaw_offset,
        mount=mount,  # type: ignore[arg-type]
        style_tags=[t.strip() for t in style_tags.split(",") if t.strip()],
        room_types=[t.strip() for t in room_types.split(",") if t.strip()],
        price_inr=price_inr,
        color=color,
        source=AssetSource(provider="upload", source_id=filename, license=license, creator=creator),
    )
    record = asset_pipeline.ingest_file(dest, meta)
    return {"success": True, "asset": record.model_dump()}


class PolyhavenIngestBody(BaseModel):
    source_id: str
    name: str
    semantic_type: str
    asset_id: Optional[str] = None
    resolution: str = "1k"
    expected_dimensions: Optional[Vec3] = None
    yaw_offset: float = 0.0
    mount: str = "floor"
    style_tags: list[str] = []
    material_tags: list[str] = []
    room_types: list[str] = []
    price_inr: int = 0
    color: str = "#8a7862"


@router.post("/assets/ingest/polyhaven")
async def ingest_polyhaven(body: PolyhavenIngestBody) -> dict:
    """Download a CC0 model from Poly Haven and run it through the pipeline."""
    slug = body.asset_id or f"ph_{body.source_id.lower()}"
    dest = get_registry().source_dir(slug)
    async with polyhaven.make_client() as client:
        files = await polyhaven.model_files(client, body.source_id, body.resolution)
        written = await polyhaven.download(client, files, dest)
    gltf_path = next(p for p in written if p.suffix == ".gltf")
    meta = IngestMeta(
        asset_id=slug,
        name=body.name,
        semantic_type=body.semantic_type,
        expected_dimensions=body.expected_dimensions,
        yaw_offset=body.yaw_offset,
        mount=body.mount,  # type: ignore[arg-type]
        style_tags=body.style_tags,
        material_tags=body.material_tags,
        room_types=body.room_types,
        price_inr=body.price_inr,
        color=body.color,
        source=AssetSource(
            provider="polyhaven",
            source_id=body.source_id,
            url=polyhaven.page_url(body.source_id),
            license=polyhaven.LICENSE,
            license_url=polyhaven.LICENSE_URL,
            creator="Poly Haven contributors",
            thumbnail_url=polyhaven.thumbnail_url(body.source_id),
        ),
    )
    record = asset_pipeline.ingest_file(gltf_path, meta)
    return {"success": True, "asset": record.model_dump()}


class RenormalizeBody(BaseModel):
    expected_dimensions: Optional[Vec3] = None
    yaw_offset: Optional[float] = None


@router.post("/assets/{asset_id}/renormalize")
def renormalize_asset(asset_id: str, body: RenormalizeBody) -> dict:
    try:
        record = asset_pipeline.renormalize(asset_id, body.expected_dimensions, body.yaw_offset)
    except KeyError:
        return error_response("ASSET_NOT_FOUND", f"No asset {asset_id}.", 404)
    return {"success": True, "asset": record.model_dump()}


# ── Materials (plan §34) ────────────────────────────────────────────────


@router.get("/materials")
def list_materials() -> dict:
    return ok([m.model_dump() for m in get_material_registry().list()])


@router.get("/materials/{material_id}")
def get_material(material_id: str) -> dict:
    record = get_material_registry().get(material_id)
    if record is None:
        return error_response("MATERIAL_NOT_FOUND", f"No material {material_id}.", 404)
    return ok(record.model_dump())


class PolyhavenMaterialBody(BaseModel):
    source_id: str
    material_id: str
    name: Optional[str] = None
    category: Optional[str] = None
    resolution: str = "1k"
    tile_size_m: Optional[float] = None
    base_color: Optional[str] = None
    roughness: Optional[float] = None
    style_tags: Optional[list[str]] = None
    applies_to: Optional[list[str]] = None


@router.post("/materials/ingest/polyhaven")
async def ingest_polyhaven_material(body: PolyhavenMaterialBody) -> dict:
    dest = get_material_registry().material_dir(body.material_id)
    async with polyhaven.make_client() as client:
        remote = await polyhaven.texture_files(client, body.source_id, body.resolution)
        if "color" not in remote:
            return error_response("EXTERNAL_PROVIDER_ERROR", f"{body.source_id} has no diffuse map at {body.resolution}.", 502)
        written = await polyhaven.download(client, list(remote.values()), dest)
    files = {key: path for key, path in zip(remote.keys(), written)}
    record = material_pipeline.attach_maps(
        body.material_id,
        files,
        AssetSource(
            provider="polyhaven",
            source_id=body.source_id,
            url=polyhaven.page_url(body.source_id),
            license=polyhaven.LICENSE,
            license_url=polyhaven.LICENSE_URL,
            creator="Poly Haven contributors",
            thumbnail_url=polyhaven.thumbnail_url(body.source_id),
        ),
        tile_size_m=body.tile_size_m,
        name=body.name,
        category=body.category,
        base_color=body.base_color,
        roughness=body.roughness,
        style_tags=body.style_tags,
        applies_to=body.applies_to,
    )
    return {"success": True, "material": record.model_dump()}

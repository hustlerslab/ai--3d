"""Project lifecycle, inputs and jobs (DPR §17, plan §6).

Long work never runs inside a request: routes create a Job and return it,
the UI polls GET /jobs/{id} and GET /projects/{id}/events.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from ..core.config import get_settings
from ..jobs import get_job_store, get_runner, known_types
from ..projects import (
    InputKind,
    InputRecord,
    ProjectStage,
    RoomHint,
    Vertical,
    get_project_store,
)
from ..projects.layout import CHECKPOINTS, ensure_layout, file_url, project_dir
from ..projects.store import VerticalLocked
from .envelope import ok

router = APIRouter(prefix="/api", tags=["projects"])
files_router = APIRouter(tags=["files"])

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_REFERENCES = 12
# A brief is prose, not a document: ~3k words. It is scanned on every write,
# stored in a TEXT column and pasted verbatim into every provider prompt, so
# the real ceiling is the prompt. References are already capped at 25 MB x 12.
MAX_BRIEF_CHARS = 20_000

# Regulated industrial-facility work this product declines. Facility and
# regulatory phrases only — the aesthetic vocabulary ("industrial", "loft",
# "exposed brick", "warehouse") is deliberately absent, a loft-look flat is
# ordinary work. Matching is a plain substring scan whose only outcome is a
# refusal: nothing here evaluates a load, a code or a safety rule.
OUT_OF_SCOPE_TERMS = (
    "manufacturing plant",
    "manufacturing facility",
    "factory floor",
    "machine guarding",
    "load bearing",
    "load-bearing",
    "structural load",
    "fire code",
    "factories act",
    "osh code",
)

IN_SCOPE_SUMMARY = (
    "This product designs interiors — residential, hospitality and "
    "industrial-style spaces: layout, furnishing, materials, lighting mood "
    "and walkthrough renders."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateProjectBody(BaseModel):
    name: str
    description: str = ""
    room_hints: list[RoomHint] = []
    vertical: Vertical = Vertical.RESIDENTIAL


class UpdateProjectBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    room_hints: Optional[list[RoomHint]] = None
    vertical: Optional[Vertical] = None


class EnqueueJobBody(BaseModel):
    type: str
    params: dict[str, Any] = {}


# ── Projects ────────────────────────────────────────────────────────────


@router.get("/projects")
def list_projects() -> dict:
    return ok([p.model_dump(mode="json") for p in get_project_store().list()])


@router.post("/projects")
def create_project(body: CreateProjectBody) -> dict:
    refusal = _brief_refusal(body.description)
    if refusal is not None:
        return refusal  # nothing is created for a brief we decline
    store = get_project_store()
    project = store.create(
        name=body.name,
        description=body.description,
        room_hints=body.room_hints,
        vertical=body.vertical,
    )
    get_job_store().add_event(project.project_id, "project", "created", f"project '{project.name}' created")
    if body.description:
        _write_description(project.project_id, body.description)
    return {"success": True, "project": project.model_dump(mode="json")}


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    store = get_project_store()
    project = store.get(project_id)
    jobs = get_job_store().list_for_project(project_id, limit=20)
    return ok(
        {
            "project": project.model_dump(mode="json"),
            "inputs": [i.model_dump(mode="json") for i in store.list_inputs(project_id)],
            "jobs": [j.model_dump(mode="json") for j in jobs],
            "checkpoints": _checkpoints(project_id),
            "outputs": store.list_outputs(project_id),
        }
    )


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: UpdateProjectBody) -> dict:
    store = get_project_store()
    refusal = _brief_refusal(body.description)
    if refusal is not None:
        return refusal
    try:
        # the store gates the vertical inside the write itself; an unknown
        # project raises ProjectNotFound and 404s through its handler
        project = store.update(
            project_id,
            name=body.name,
            description=body.description,
            room_hints=body.room_hints,
            vertical=body.vertical,
        )
    except VerticalLocked as exc:
        return _error(
            "VERTICAL_LOCKED",
            f"The vertical is fixed once a project leaves CREATED (now {exc.stage.value}); "
            f"the work already done was analysed as '{exc.vertical.value}' and changing it "
            "would invalidate that. Start a new project for a different vertical.",
            409,
        )
    if body.description is not None:
        _write_description(project_id, body.description)
    return {"success": True, "project": project.model_dump(mode="json")}


# ── Inputs ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/inputs")
def list_inputs(project_id: str) -> dict:
    store = get_project_store()
    store.get(project_id)
    return ok([i.model_dump(mode="json") for i in store.list_inputs(project_id)])


@router.delete("/projects/{project_id}/inputs/{input_id}")
def delete_input(project_id: str, input_id: str) -> dict:
    """Remove one uploaded file. Without this the 12-reference cap is a dead
    end: a user who uploads the wrong photos has no way to make room."""
    store = get_project_store()
    store.get(project_id)                      # 404s through ProjectNotFound
    record = store.delete_input(project_id, input_id)
    if record is None:
        return _error("INPUT_NOT_FOUND", f"No such input on this project: {input_id}", 404)

    # Same containment check as the file route: resolve both sides and refuse
    # anything that escapes the project directory, whatever the stored path says.
    root = project_dir(project_id).resolve()
    target = (root / record.path).resolve()
    removed = False
    if root in target.parents and target.is_file():
        try:
            target.unlink()
            removed = True
        except OSError:
            pass                               # the row is gone; a stale file is not fatal

    # Room hints live on the project, not in the file, so dropping the
    # dimensions input has to clear them or they outlive their source.
    if record.kind == InputKind.dimensions:
        store.update(project_id, room_hints=[])

    return ok({"input_id": input_id, "kind": record.kind.value, "file_removed": removed})


@router.post("/projects/{project_id}/inputs")
async def add_inputs(
    project_id: str,
    description: Optional[str] = Form(None),
    dimensions: Optional[str] = Form(None),
    references: list[UploadFile] = File([]),
) -> dict:
    """Multipart: `description` (text), `dimensions` (JSON list of RoomHint),
    `references[]` (images). Any subset may be sent; each call appends."""
    store = get_project_store()
    project = store.get(project_id)
    refusal = _brief_refusal(description)
    if refusal is not None:
        return refusal  # refuse before anything in the request is stored
    root = ensure_layout(project_id)
    created: list[InputRecord] = []
    rejected: list[dict] = []

    if description is not None and description.strip():
        path = _write_description(project_id, description)
        rec = InputRecord(
            project_id=project_id,
            kind=InputKind.description,
            filename="description.txt",
            path="input/description.txt",
            content_type="text/plain",
            size_bytes=path.stat().st_size,
            created_at=_now(),
        )
        created.append(store.add_input(rec))
        store.update(project_id, description=description.strip())

    if dimensions is not None and dimensions.strip():
        try:
            hints = [RoomHint.model_validate(h) for h in json.loads(dimensions)]
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            return _error("INVALID_DIMENSIONS", f"dimensions must be a JSON list of rooms: {exc}", 422)
        target = root / "input" / "dimensions.json"
        target.write_text(json.dumps([h.model_dump() for h in hints], indent=2), encoding="utf-8")
        rec = InputRecord(
            project_id=project_id,
            kind=InputKind.dimensions,
            filename="dimensions.json",
            path="input/dimensions.json",
            content_type="application/json",
            size_bytes=target.stat().st_size,
            meta={"rooms": len(hints)},
            created_at=_now(),
        )
        created.append(store.add_input(rec))
        store.update(project_id, room_hints=hints)

    existing = len(store.list_inputs(project_id, InputKind.reference))
    for upload in references:
        if not upload.filename:
            continue
        ctype = (upload.content_type or "").lower()
        data = await upload.read()
        if ctype not in IMAGE_TYPES:
            rejected.append({"filename": upload.filename, "reason": f"unsupported type {ctype or 'unknown'}"})
            continue
        if len(data) > MAX_IMAGE_BYTES:
            rejected.append({"filename": upload.filename, "reason": "larger than 25 MB"})
            continue
        if existing >= MAX_REFERENCES:
            rejected.append({"filename": upload.filename, "reason": f"more than {MAX_REFERENCES} references"})
            continue
        existing += 1
        ext = Path(upload.filename).suffix.lower() or ".jpg"
        safe_name = f"ref_{existing:02d}{ext}"
        rel = f"input/references/{safe_name}"
        (root / rel).write_bytes(data)
        rec = InputRecord(
            project_id=project_id,
            kind=InputKind.reference,
            filename=upload.filename,
            path=rel,
            content_type=ctype,
            size_bytes=len(data),
            meta={"url": file_url(project_id, rel)},
            created_at=_now(),
        )
        created.append(store.add_input(rec))

    if created and project.stage == ProjectStage.CREATED:
        project = store.set_stage(project_id, ProjectStage.INPUT_RECEIVED)
        get_job_store().add_event(project_id, "inputs", "received", f"{len(created)} input(s) stored")
    elif created:
        get_job_store().add_event(project_id, "inputs", "updated", f"{len(created)} input(s) added")

    return {
        "success": True,
        "project": store.get(project_id).model_dump(mode="json"),
        "inputs": [i.model_dump(mode="json") for i in created],
        "rejected": rejected,
    }


# ── Analysis (stage 5) ──────────────────────────────────────────────────


class AnalyzeBody(BaseModel):
    force: bool = False


class RoomPatch(BaseModel):
    room_id: str
    name: Optional[str] = None
    type: Optional[str] = None
    width_m: Optional[float] = None
    length_m: Optional[float] = None
    height_m: Optional[float] = None
    estimated: Optional[bool] = None
    notes: Optional[str] = None


class StylePatch(BaseModel):
    name: Optional[str] = None
    tags: Optional[list[str]] = None
    palette: Optional[list[str]] = None
    materials: Optional[list[str]] = None
    lighting_mood: Optional[str] = None
    description: Optional[str] = None


class AnalysisPatchBody(BaseModel):
    intent: Optional[str] = None
    constraints: Optional[list[str]] = None
    rooms: Optional[list[RoomPatch]] = None
    remove_rooms: list[str] = []
    style: Optional[StylePatch] = None


@router.post("/projects/{project_id}/analyze")
def analyze_project(project_id: str, body: AnalyzeBody = AnalyzeBody()) -> dict:
    from ..intelligence import build_input_bundle

    if not build_input_bundle(project_id).has_content:
        return _error("NO_INPUTS", "Add a description, dimensions or reference photos before analysing.", 422)
    job = get_runner().enqueue(project_id, "analyze", {"force": body.force})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/analysis")
def get_analysis(project_id: str) -> dict:
    store = get_project_store()
    store.get(project_id)
    root = project_dir(project_id)
    analysis_path = root / "analysis" / "design_analysis.json"
    if not analysis_path.exists():
        latest = get_job_store().latest_of_type(project_id, "analyze")
        return _error(
            "ANALYSIS_NOT_READY",
            "No analysis yet. POST /analyze first." + (f" Latest job: {latest.status.value}." if latest else ""),
            404,
        )
    return ok(
        {
            "analysis": _read(root / "analysis" / "design_analysis.json"),
            "style": _read(root / "analysis" / "style_spec.json"),
            "moodboard": _read(root / "analysis" / "moodboard_spec.json"),
            "versions": store.list_analyses(project_id),
            "provider": _provider_status(),
        }
    )


@router.patch("/projects/{project_id}/analysis")
def patch_analysis(project_id: str, body: AnalysisPatchBody) -> dict:
    """User corrections from the Analysis Review screen: room sizes, intent,
    constraints, style. Writes a new version; the original stays in history."""
    from ..intelligence import DesignAnalysis, StyleSpec
    from ..intelligence.mock_provider import build_moodboard
    from ..intelligence import build_input_bundle

    store = get_project_store()
    store.get(project_id)
    root = project_dir(project_id)
    analysis_path = root / "analysis" / "design_analysis.json"
    style_path = root / "analysis" / "style_spec.json"
    if not analysis_path.exists():
        return _error("ANALYSIS_NOT_READY", "Nothing to patch: run /analyze first.", 404)

    analysis = DesignAnalysis.model_validate(_read(analysis_path))
    changed = False
    if body.intent is not None:
        analysis.intent = body.intent
        changed = True
    if body.constraints is not None:
        analysis.constraints = body.constraints
        changed = True
    if body.remove_rooms:
        analysis.rooms = [r for r in analysis.rooms if r.room_id not in body.remove_rooms]
        changed = True
    for patch in body.rooms or []:
        room = analysis.room(patch.room_id)
        data = patch.model_dump(exclude_none=True, exclude={"room_id"})
        if room is None:
            from ..intelligence.schema import RoomAnalysis
            from ..intelligence import vocab

            rtype = data.get("type", "other")
            # the project's vertical decides what a room of this type measures
            dims = vocab.room_default_dims(store.get(project_id).vertical)
            dw, dl = dims.get(rtype, dims["other"])
            analysis.rooms.append(
                RoomAnalysis(
                    room_id=patch.room_id,
                    name=data.get("name", vocab.ROOM_LABELS.get(rtype, "Room")),
                    type=rtype,
                    width_m=data.get("width_m", dw),
                    length_m=data.get("length_m", dl),
                    height_m=data.get("height_m", 3.0),
                    estimated=data.get("estimated", "width_m" not in data),
                    notes=data.get("notes", ""),
                )
            )
        else:
            for key, value in data.items():
                setattr(room, key, value)
            if "width_m" in data or "length_m" in data:
                room.estimated = data.get("estimated", False)
        changed = True
    if changed:
        analysis.version = store.next_analysis_version(project_id, "design_analysis")
        analysis.provider = "user"
        _write(analysis_path, analysis)
        store.add_analysis(project_id, "design_analysis", "analysis/design_analysis.json", analysis.version)
        # keep the project's room hints in sync so later re-analysis honours the corrections
        store.update(
            project_id,
            room_hints=[
                RoomHint(name=r.name, type=r.type, width_m=r.width_m, length_m=r.length_m,
                         height_m=r.height_m, estimated=r.estimated)
                for r in analysis.rooms
            ],
        )

    style = StyleSpec.model_validate(_read(style_path)) if style_path.exists() else None
    if body.style is not None and style is not None:
        merged = {**style.model_dump(), **body.style.model_dump(exclude_none=True)}
        merged["version"] = store.next_analysis_version(project_id, "style_spec")
        merged["provider"] = "user"
        style = StyleSpec.model_validate(merged)  # re-runs palette/enum validation
        _write(style_path, style)
        store.add_analysis(project_id, "style_spec", "analysis/style_spec.json", style.version)
        changed = True

    if changed and style is not None:
        moodboard = build_moodboard(analysis, style, build_input_bundle(project_id))
        _write(root / "analysis" / "moodboard_spec.json", moodboard)
        get_job_store().add_event(project_id, "analysis", "edited", "analysis corrected by user")

    return {
        "success": True,
        "analysis": analysis.model_dump(mode="json"),
        "style": style.model_dump(mode="json") if style else None,
    }


# ── Scene planning (stages 6–9) ─────────────────────────────────────────


class ScenePlanBody(BaseModel):
    force: bool = False


@router.post("/projects/{project_id}/scene-plan")
def scene_plan_project(project_id: str, body: ScenePlanBody = ScenePlanBody()) -> dict:
    get_project_store().get(project_id)
    root = project_dir(project_id)
    if not (root / "analysis" / "style_spec.json").exists():
        return _error("ANALYSIS_REQUIRED", "Run POST /analyze before planning the scene.", 409)
    job = get_runner().enqueue(project_id, "scene_plan", {"force": body.force})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.post("/projects/{project_id}/assets/resolve")
def resolve_project_assets(project_id: str) -> dict:
    project = get_project_store().get(project_id)
    if not project.scene_ids:
        return _error("SCENE_REQUIRED", "Run POST /scene-plan before resolving assets.", 409)
    job = get_runner().enqueue(project_id, "resolve_assets", {})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/scene-spec")
def get_scene_spec(project_id: str) -> dict:
    from ..scene.store import SceneNotFound, get_store
    from ..spatial.validation import validate_scene

    store = get_project_store()
    project = store.get(project_id)
    root = project_dir(project_id)
    if not project.scene_ids:
        latest = get_job_store().latest_of_type(project_id, "scene_plan")
        return _error(
            "SCENE_NOT_READY",
            "No scene yet. POST /scene-plan first." + (f" Latest job: {latest.status.value}." if latest else ""),
            404,
        )
    scene_store = get_store()
    try:
        scene = scene_store.load(project.scene_ids[-1])
    except SceneNotFound:
        return _error("SCENE_NOT_READY", "Scene file missing; re-run POST /scene-plan with force.", 404)
    violations = validate_scene(scene)
    return ok(
        {
            "scene": scene.model_dump(mode="json"),
            "history": scene_store.history_info(scene.scene_id),
            "violations": [v.model_dump() for v in violations],
            "object_plan": _read(root / "planning" / "object_plan.json"),
            "asset_plan": _read(root / "planning" / "asset_plan.json"),
            "scene_specs": store.list_scene_specs(project_id),
        }
    )


# ── Blender build (stage 9, render lane) ────────────────────────────────


class BuildBody(BaseModel):
    force: bool = False
    preview: bool = True
    preview_profile: str = "preview"


@router.post("/projects/{project_id}/build")
def build_project(project_id: str, body: BuildBody = BuildBody()) -> dict:
    project = get_project_store().get(project_id)
    if not project.scene_ids:
        return _error("SCENE_REQUIRED", "Run POST /scene-plan before building.", 409)
    if not get_settings().blender_configured:
        return _error("BLENDER_NOT_CONFIGURED", "BLENDER_PATH is not set; the render lane cannot build.", 503)
    job = get_runner().enqueue(
        project_id, "build", {"force": body.force, "preview": body.preview, "preview_profile": body.preview_profile}
    )
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/build")
def get_build(project_id: str) -> dict:
    get_project_store().get(project_id)
    root = project_dir(project_id)
    report = _read(root / "blender" / "validation_report.json")
    manifest = _read(root / "blender" / "build_manifest.json")
    if report is None and manifest is None:
        latest = get_job_store().latest_of_type(project_id, "build")
        return _error("BUILD_NOT_READY", "No build yet. POST /build first." + (f" Latest job: {latest.status.value}." if latest else ""), 404)
    return ok(
        {
            "report": report,
            "manifest_summary": {
                "scene_id": manifest.get("scene_id"),
                "scene_version": manifest.get("scene_version"),
                "objects": len(manifest.get("objects", [])),
                "walls": len(manifest.get("walls", [])),
                "materials": sorted(manifest.get("materials", {}).keys()),
            } if manifest else None,
            "files": {
                "blend": file_url(project_id, "blender/scene.blend") if (root / "blender" / "scene.blend").exists() else None,
                "preview": file_url(project_id, "previews/build_preview.png") if (root / "previews" / "build_preview.png").exists() else None,
                "manifest": file_url(project_id, "blender/build_manifest.json") if manifest else None,
            },
        }
    )


# ── Tour: preview + final walkthrough (stage 11) ────────────────────────


class PreviewBody(BaseModel):
    force: bool = False
    profile: str = "pano_preview"


class WalkthroughBody(BaseModel):
    force: bool = False
    profile: str = "pano_final"
    hero_stills: int = 2


def _render_ready(project_id: str):
    project = get_project_store().get(project_id)
    if not project.scene_ids:
        return _error("SCENE_REQUIRED", "Run POST /scene-plan before rendering.", 409)
    if not (project_dir(project_id) / "blender" / "scene.blend").exists():
        return _error("BUILD_REQUIRED", "Run POST /build before rendering the tour.", 409)
    if not get_settings().blender_configured:
        return _error("BLENDER_NOT_CONFIGURED", "BLENDER_PATH is not set; the render lane cannot run.", 503)
    return None


@router.post("/projects/{project_id}/preview")
def preview_project(project_id: str, body: PreviewBody = PreviewBody()) -> dict:
    err = _render_ready(project_id)
    if err is not None:
        return err
    job = get_runner().enqueue(project_id, "preview", {"force": body.force, "profile": body.profile})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.post("/projects/{project_id}/walkthrough")
def walkthrough_project(project_id: str, body: WalkthroughBody = WalkthroughBody()) -> dict:
    err = _render_ready(project_id)
    if err is not None:
        return err
    job = get_runner().enqueue(
        project_id, "walkthrough", {"force": body.force, "profile": body.profile, "hero_stills": body.hero_stills}
    )
    return {"success": True, "job": job.model_dump(mode="json")}


class FilmBody(BaseModel):
    force: bool = False
    profile: str = "preview"


@router.post("/projects/{project_id}/film")
def film_project(project_id: str, body: FilmBody = FilmBody()) -> dict:
    err = _render_ready(project_id)
    if err is not None:
        return err
    job = get_runner().enqueue(project_id, "film", {"force": body.force, "profile": body.profile})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/tour")
def get_tour(project_id: str) -> dict:
    """Read-only web package for the share page (/w/{projectId})."""
    get_project_store().get(project_id)
    tour = _read(project_dir(project_id) / "outputs" / "web" / "tour.json")
    if tour is None:
        latest = get_job_store().latest_of_type(project_id, "preview")
        return _error(
            "TOUR_NOT_READY",
            "No tour yet. POST /preview first." + (f" Latest job: {latest.status.value}." if latest else ""),
            404,
        )
    return ok(tour)


# ── Jobs and events ─────────────────────────────────────────────────────


@router.get("/jobs/types")
def job_types() -> dict:
    return ok(known_types())


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    store = get_job_store()
    job = store.get(job_id)
    return ok({"job": job.model_dump(mode="json"), "events": [e.model_dump() for e in store.list_job_events(job_id)]})


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: str) -> dict:
    get_project_store().get(project_id)
    return ok([j.model_dump(mode="json") for j in get_job_store().list_for_project(project_id)])


@router.post("/projects/{project_id}/jobs")
def enqueue_job(project_id: str, body: EnqueueJobBody) -> dict:
    job = get_runner().enqueue(project_id, body.type, body.params)
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/events")
def list_events(project_id: str, after: int = 0, limit: int = 200) -> dict:
    get_project_store().get(project_id)
    events = get_job_store().list_events(project_id, after=after, limit=min(limit, 500))
    return ok({"events": [e.model_dump() for e in events], "last_id": events[-1].event_id if events else after})


@router.get("/projects/{project_id}/outputs")
def list_outputs(project_id: str) -> dict:
    store = get_project_store()
    store.get(project_id)
    return ok({"outputs": store.list_outputs(project_id), "checkpoints": _checkpoints(project_id)})


# ── Project files ───────────────────────────────────────────────────────
# Served by a route rather than a StaticFiles mount so the directory is
# resolved per request (data dir can change between test runs) and paths
# are confined to the project folder.


@files_router.get("/files/projects/{project_id}/{path:path}")
def project_file(project_id: str, path: str):
    root = project_dir(project_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        return _error("FILE_NOT_FOUND", f"No such project file: {path}", 404)
    return FileResponse(str(target))


# ── helpers ─────────────────────────────────────────────────────────────


def _brief_refusal(text: Optional[str]):
    """Bound a brief and decline one that asks for regulated industrial-facility
    work. Returns an error response, or None when the brief is acceptable. The
    refusal is all it does — it makes no judgement about the building."""
    if not text or not text.strip():
        return None
    if len(text) > MAX_BRIEF_CHARS:
        return _error(
            "BRIEF_TOO_LONG",
            f"The brief is {len(text)} characters; keep it under {MAX_BRIEF_CHARS}. "
            "Describe the space and the look you want — plans and photos belong in "
            "the dimensions and reference uploads.",
            422,
        )
    lowered = text.lower()
    hit = next((term for term in OUT_OF_SCOPE_TERMS if term in lowered), None)
    if hit is None:
        return None
    return _error(
        "OUT_OF_SCOPE",
        f"This brief asks for regulated industrial-facility work ('{hit}'), which is out of "
        "scope: no plant or factory-floor layouts, no structural or load-bearing work, and no "
        f"fire, safety or building-code advice. {IN_SCOPE_SUMMARY}",
        422,
    )


def _write_description(project_id: str, text: str) -> Path:
    root = ensure_layout(project_id)
    path = root / "input" / "description.txt"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _checkpoints(project_id: str) -> dict[str, bool]:
    root = project_dir(project_id)
    return {name: (root / rel).exists() for name, rel in CHECKPOINTS.items()}


def _error(code: str, message: str, status: int):
    from .envelope import error_response

    return error_response(code, message, status)


def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2), encoding="utf-8")


def _provider_status() -> dict:
    from ..intelligence import get_provider

    provider = get_provider()
    return {"mode": provider.mode, "name": provider.name, "model": provider.label, "fallback_to_mock": provider.allow_fallback}

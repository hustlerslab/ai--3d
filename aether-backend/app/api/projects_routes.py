"""Project lifecycle, inputs and jobs (DPR §17, plan §6).

Long work never runs inside a request: routes create a Job and return it,
the UI polls GET /jobs/{id} and GET /projects/{id}/events.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from ..core.config import get_settings
from ..intelligence.schema import SceneReading
from ..jobs.handlers.generate_elements import CREDITS_PER_PIECE as _CREDITS_PER_PIECE
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
def list_projects(request: Request) -> dict:
    """Only what this caller may see.

    Filtering here rather than in the gate is deliberate: the gate answers
    "may you touch project X", and a list has no X. Without this a signed-in
    stranger could not OPEN anyone else's project but could still read every
    project's name and id, which is most of what a client brief reveals.
    """
    from ..auth.authz import visible_project_ids
    from ..auth.deps import require_principal

    visible = visible_project_ids(require_principal(request))
    projects = get_project_store().list()
    if visible is not None:
        projects = [p for p in projects if p.project_id in visible]
    return ok([p.model_dump(mode="json") for p in projects])


@router.post("/projects")
def create_project(body: CreateProjectBody, request: Request) -> dict:
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
    # Stamp the owner immediately. A project that exists for even one request
    # without an owner is a project only an admin can reach - including the
    # person who just created it.
    from ..auth.authz import set_owner
    from ..auth.deps import require_principal

    set_owner(project.project_id, require_principal(request).user_id)
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


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Delete a project, keeping the moodboard renders and generated meshes.

    Archive first, then delete. The other order risks removing the folder and
    then failing halfway through the copy, and what is kept is the expensive
    half: renders the client approved, and meshes at 30 credits each.

    The response says what survived, so the caller can tell the user instead of
    leaving them to guess whether their work is gone.
    """
    import shutil

    from ..projects.layout import archive_project

    store = get_project_store()
    project = store.get(project_id)            # 404s through ProjectNotFound
    manifest = archive_project(project_id, name=project.name,
                               description=project.description,
                               vertical=project.vertical.value)
    store.delete_project(project_id)
    root = project_dir(project_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    return ok({"deleted": project_id, "kept": manifest["kept"]})


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
    #: False for the element-first entry: analysis, crops and style without
    #: painting rooms, so pieces can be pictured before any room exists.
    paint: bool = True


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
    # {object_id: "place" | "reference"} — the client settling which read items
    # are theirs and which were shop photos. Keyed by the item's stable id, not
    # its position (ADR-002 §2).
    item_roles: dict[str, str] = {}


@router.post("/projects/{project_id}/analyze")
def analyze_project(project_id: str, body: AnalyzeBody = AnalyzeBody()) -> dict:
    from ..intelligence import build_input_bundle

    if not build_input_bundle(project_id).has_content:
        return _error("NO_INPUTS", "Add a description, dimensions or reference photos before analysing.", 422)
    job = get_runner().enqueue(project_id, "analyze", {"force": body.force, "paint": body.paint})
    return {"success": True, "job": job.model_dump(mode="json")}


# ── Element images (element-first, stage 1) ─────────────────────────────


class ElementImagesBody(BaseModel):
    force: bool = False


@router.post("/projects/{project_id}/element-images")
def element_images_project(project_id: str, body: ElementImagesBody = ElementImagesBody()) -> dict:
    """One isolated picture per canonical piece, decided from the photos and
    the brief before any room is painted. Local GPU, no per-image cost."""
    get_project_store().get(project_id)
    root = project_dir(project_id)
    if not (root / "analysis" / "style_spec.json").exists():
        return _error("ANALYSIS_REQUIRED", "Run /analyze first.", 409)
    job = get_runner().enqueue(project_id, "element_images", {"force": body.force})
    return {"success": True, "job": job.model_dump(mode="json")}


@router.get("/projects/{project_id}/element-images")
def get_element_images(project_id: str) -> dict:
    get_project_store().get(project_id)
    root = project_dir(project_id)
    data = _read(root / "planning" / "element_images.json")
    if data is None:
        latest = get_job_store().latest_of_type(project_id, "element_images")
        return _error(
            "ELEMENT_IMAGES_NOT_READY",
            "No element images yet. POST /element-images first."
            + (f" Latest job: {latest.status.value}." if latest else ""),
            404,
        )
    return ok(_element_images_payload(project_id, data))


class ElementDecisionsBody(BaseModel):
    """{element_id: true|false} — the client confirming or leaving out a
    pictured piece, BEFORE any room is painted. Keyed by the canonical element
    id, which is content-addressed and survives a re-run."""
    decisions: dict[str, bool]


@router.patch("/projects/{project_id}/element-images")
def review_element_images(project_id: str, body: ElementDecisionsBody) -> dict:
    from ..intelligence.schema import ElementImageSet

    get_project_store().get(project_id)
    path = project_dir(project_id) / "planning" / "element_images.json"
    data = _read(path)
    if data is None:
        return _error("ELEMENT_IMAGES_NOT_READY", "Nothing to review yet.", 404)
    images = ElementImageSet.model_validate(data)
    known = {d.element_id for d in images.definitions}
    unknown = sorted(set(body.decisions) - known)
    if unknown:
        return _error("UNKNOWN_ELEMENT",
                      f"No such element(s): {', '.join(unknown)}. Re-fetch and review again.", 409)
    for d in images.definitions:
        if d.element_id in body.decisions:
            d.approved = body.decisions[d.element_id]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(images.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)
    return ok(_element_images_payload(project_id, images.model_dump(mode="json")))


def _element_images_payload(project_id: str, data: dict) -> dict:
    """URLs are minted here, not stored: only the API knows how files are
    served. Every read of the element images goes through this, for GET and
    PATCH alike, so the two answers cannot drift."""
    for im in data.get("images", []):
        ref = im.get("image_ref") or ""
        im["image_url"] = f"/files/projects/{project_id}/{ref}" if ref and not im.get("error") else ""
        crop = im.get("reference_ref") or ""
        im["reference_url"] = f"/files/projects/{project_id}/{crop}" if crop else ""
    return data


@router.post("/projects/{project_id}/moodboard/rooms/{room_id}/repaint")
def repaint_room(project_id: str, room_id: str) -> dict:
    """Redraw one room's moodboard image on a fresh seed.

    The reviewer's backstop for seed variance (ADR-002 §1): the same prompt
    gives a complete bathroom on one seed and a bathtub in an alcove on another,
    and no wording distinguishes them. Repainting one room leaves the reading,
    the style and the other rooms untouched.
    """
    from ..intelligence import DesignAnalysis

    store = get_project_store()
    store.get(project_id)
    root = project_dir(project_id)
    analysis_path = root / "analysis" / "design_analysis.json"
    if not analysis_path.exists():
        return _error("ANALYSIS_NOT_READY", "Nothing to repaint: run /analyze first.", 404)
    analysis = DesignAnalysis.model_validate(_read(analysis_path))
    if not any(r.room_id == room_id for r in analysis.rooms):
        known = ", ".join(r.room_id for r in analysis.rooms) or "none"
        return _error("ROOM_NOT_FOUND", f"No room {room_id!r} in this reading. Rooms: {known}.", 404)
    job = get_runner().enqueue(project_id, "repaint_room", {"room_id": room_id})
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
    if body.item_roles:
        bad = sorted(set(body.item_roles.values()) - {"place", "reference"})
        if bad:
            return _error("INVALID_ROLE", f"Unknown item role(s): {', '.join(bad)}. Use 'place' or 'reference'.", 422)
        by_id = {s.object_id: s for s in analysis.spotted_objects}
        missing = sorted(set(body.item_roles) - set(by_id))
        if missing:
            return _error("ITEM_NOT_FOUND", f"No read item with id(s): {', '.join(missing)}.", 404)
        for object_id, role in body.item_roles.items():
            by_id[object_id].role = role  # type: ignore[assignment]
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
    #: Re-read the approved moodboard as well, which `force` deliberately does
    #: not (it costs a vision call per room). The handler has honoured this
    #: since the read was checkpointed, but nothing could set it: the body
    #: carried only `force`, so the reading was frozen at whatever the first
    #: read produced and no later fix to the reader could reach an existing
    #: project. Found while verifying the render-frame anchors live.
    force_read: bool = False


class ElementReviewBody(BaseModel):
    """{element_id: true|false} — the client confirming or rejecting crops.

    Keyed by the element's stable id, never its position in the list, for the
    same reason item roles are (ADR-002 s2): the list is re-read and re-ordered
    between the render and the click.
    """

    decisions: dict[str, bool] = {}


@router.get("/projects/{project_id}/scene-reading")
def get_scene_reading(project_id: str) -> dict:
    """The elements read out of the approved moodboard, for human review.

    Each one carries its crop, the label the scene read gave it, and the
    verdict of the isolated second look. Nothing here is generated yet: this is
    the screen where a wrong crop gets stopped before it costs credits.
    """
    get_project_store().get(project_id)
    root = project_dir(project_id)
    data = _read(root / "planning" / "scene_reading.json")
    if data is None:
        latest = get_job_store().latest_of_type(project_id, "scene_plan")
        return _error(
            "SCENE_READING_NOT_READY",
            "The moodboard has not been read yet. POST /scene-plan first."
            + (f" Latest job: {latest.status.value}." if latest else ""),
            404,
        )
    return ok(_reading_payload(project_id, data))


@router.patch("/projects/{project_id}/scene-reading")
def review_scene_reading(project_id: str, body: ElementReviewBody) -> dict:
    """Record the human's confirm/reject per element, and re-resolve identity.

    **It used to say "nothing else changes", and that was the bug.** `trustworthy()`
    gates `resolve_elements()`, and it answers `element.approved` whenever the
    human has spoken. So approving a crop the automated check had rejected made
    that row trustworthy — but the definitions had been computed at reading time
    and were never recomputed, so the piece stayed permanently outside the
    canonical element set.

    That costs money. Sharing one mesh between identical pieces is done by
    grouping instances under a definition; a row with no definition cannot join a
    group, so two approved identical chairs become two Meshy generations instead
    of one. Found by the P1-IDENTITY-005 provenance query, which reported an
    `instance` gap on exactly the two approved-but-unresolved objects in
    `proj_a25a006c88` (a `crowded` rug and a `mismatch` tv unit).

    Re-resolving is safe because `resolve_elements()` is deterministic and its
    ids are content-addressed from the canonical key: measured on that project,
    all 9 existing definition ids survived unchanged and 2 were added.
    """
    get_project_store().get(project_id)
    path = project_dir(project_id) / "planning" / "scene_reading.json"
    data = _read(path)
    if data is None:
        return _error("SCENE_READING_NOT_READY", "Nothing to review yet.", 404)
    reading = SceneReading.model_validate(data)
    known = {e.element_id for e in reading.elements}
    unknown = sorted(set(body.decisions) - known)
    if unknown:
        # Loudly, not quietly: a decision landing on nothing means the client is
        # looking at a reading that has since been re-read, and silently
        # dropping it would approve crops nobody actually looked at.
        return _error("UNKNOWN_ELEMENT",
                      f"No such element(s) in this reading: {', '.join(unknown)}. Re-fetch and review again.",
                      409)
    for el in reading.elements:
        if el.element_id in body.decisions:
            el.approved = bool(body.decisions[el.element_id])

    # Only when the reading already carried resolved identity. A reading written
    # before `resolve_elements()` existed has no definitions, and minting a set
    # here would hand it identity its asset bindings were never made against.
    if reading.definitions or reading.instances:
        from ..intelligence.scene_reading import resolve_elements

        reading.definitions, reading.instances = resolve_elements(reading)
    _write(path, reading)
    # The identity index is derived from this file, so it is stale the moment the
    # file changes. Rebuilt rather than patched: it is cheap, and a patched index
    # is a second implementation of the same rules.
    try:
        from ..provenance import index_project

        index_project(project_id)
    except Exception:                                          # noqa: BLE001
        pass                    # ensure_indexed() rebuilds it on the next read
    return ok(_reading_payload(project_id, reading.model_dump(mode="json")))


def _reading_payload(project_id: str, data: dict) -> dict:
    """The reading as the review screen needs it, for BOTH routes.

    `crop_url` is derived here rather than stored, because the file lives under
    the project directory and only the API knows how it is served. It used to be
    added by the GET alone, and the PATCH answered with the bare model — so
    saving a decision handed the client elements with no crop_url and the review
    screen crashed in `fileUrl` on the next render. Every read of the reading
    goes through this function now, so the two answers cannot drift again.
    """
    summary = _review_summary(data, project_id)
    for el in data.get("elements", []):
        crop = el.get("crop_ref") or ""
        el["crop_url"] = f"/files/projects/{project_id}/{crop}" if crop else ""
    return {"reading": data, "summary": summary}


def _review_summary(data: dict, project_id: str = "") -> dict:
    """What still needs a human, and what the next click would actually cost.

    The cost is computed the same way the job computes it - shape groups minus
    the ones already on disk - so the number on the button is the number that
    gets spent, not an estimate of it.
    """
    from ..intelligence.schema import SceneReading
    from ..intelligence.scene_reading import (approved_for_generation, distinct_shapes,
                                              element_inventory, inventory_notes,
                                              resolve_elements)
    from ..jobs.handlers.generate_elements import CREDITS_PER_PIECE, _glb_rel, storage_key

    # Recomputed, not read from the stored field: a reading written before the
    # field existed still gets a count, and a reading the human has just edited
    # gets the count that reflects the edit rather than the one from the read.
    parsed = SceneReading.model_validate(data)
    inventory = element_inventory(parsed)
    definitions, instances = resolve_elements(parsed)

    els = [e for e in data.get("elements", []) if e.get("crop_ref")]
    approved = [e for e in els if e.get("approved") is True]
    rejected = [e for e in els if e.get("approved") is False]

    to_generate = reused = 0
    if project_id and approved:
        ready, _ = approved_for_generation(SceneReading.model_validate(data))
        root = project_dir(project_id)
        for key, members in distinct_shapes(ready).items():
            disk = storage_key(lambda rel: (root / rel).is_file(), key, members)
            if (root / _glb_rel(disk)).is_file():
                reused += 1
            else:
                to_generate += 1
    return {
        "with_crops": len(els),
        "approved": len(approved),
        "rejected": len(rejected),
        "pending": len(els) - len(approved) - len(rejected),
        "flagged_by_check": sum(1 for e in els if e.get("check") not in ("ok",)),
        "ready_to_generate": len(approved),
        # What pressing Generate would do right now.
        "to_generate": to_generate,
        "already_generated": reused,
        "credits_needed": to_generate * CREDITS_PER_PIECE,
        # How many of each piece the room was read to hold, and what the review
        # screen should say when fewer than that survived the checks. Three bar
        # stools reaching the plan as one used to be invisible here.
        "inventory": [row.model_dump() for row in inventory],
        "inventory_notes": inventory_notes(inventory),
        # What the pieces ARE, independent of where they sit: one definition
        # per canonical piece with its instance count, so the screen can say
        # "Bar Stool - 3 instances - 1 asset" instead of listing three stools.
        "definitions": [d.model_dump() for d in definitions],
        # One row per physical occurrence, each naming its definition and the
        # reading row (and crop) it came from. The review screen shows three
        # stools as three instances of one piece because these say so; it
        # never counts or groups anything itself.
        "instances": [i.model_dump() for i in instances],
    }


@router.post("/projects/{project_id}/scene-plan")
def scene_plan_project(project_id: str, body: ScenePlanBody = ScenePlanBody()) -> dict:
    get_project_store().get(project_id)
    root = project_dir(project_id)
    if not (root / "analysis" / "style_spec.json").exists():
        return _error("ANALYSIS_REQUIRED", "Run POST /analyze before planning the scene.", 409)
    job = get_runner().enqueue(project_id, "scene_plan",
                               {"force": body.force, "force_read": body.force_read})
    return {"success": True, "job": job.model_dump(mode="json")}


class GenerateElementsBody(BaseModel):
    # Defaults to the per-project cap. A caller can lower it; raising it past
    # the configured cap is refused below rather than silently honoured.
    limit: Optional[int] = None


@router.post("/projects/{project_id}/elements/generate")
def generate_project_elements(project_id: str, body: GenerateElementsBody = GenerateElementsBody()) -> dict:
    """Turn the crops a human approved into meshes. This is the paid step.

    Refuses rather than no-ops when nothing is approved: a button that appears
    to work and quietly does nothing is how a reviewer concludes the pipeline
    is broken.
    """
    get_project_store().get(project_id)
    settings = get_settings()
    if not settings.meshy_configured:
        return _error("MESHY_NOT_CONFIGURED", "MESHY_API_KEY is not set; nothing to generate with.", 409)
    root = project_dir(project_id)
    data = _read(root / "planning" / "scene_reading.json")
    if data is None:
        return _error("SCENE_READING_NOT_READY", "Plan the space first: there are no crops to generate from.", 409)
    summary = _review_summary(data, project_id)
    if not summary["approved"]:
        return _error("NOTHING_APPROVED",
                      "No crops are approved yet. Confirm the pieces you want built first.", 409)
    cap = int(settings.meshy_max_per_project)
    limit = cap if body.limit is None else max(0, min(int(body.limit), cap))
    job = get_runner().enqueue(project_id, "generate_elements", {"limit": limit})
    return {"success": True, "job": job.model_dump(mode="json"), "summary": summary}


@router.get("/credits")
def get_credits() -> dict:
    """Remaining Meshy credits, for the screen that is about to spend them.

    Never fails the page: an unreachable vendor answers `available: false` with
    the reason, because a missing balance is not a reason to block planning.
    """
    import asyncio

    from ..providers import meshy

    settings = get_settings()
    if not settings.meshy_configured:
        return ok({"available": False, "reason": "MESHY_API_KEY is not set",
                   "credits_per_piece": _CREDITS_PER_PIECE})

    async def read() -> int:
        async with meshy.make_client(settings.meshy_api_key.get_secret_value(), 15.0) as client:
            return await meshy.balance(client)

    try:
        return ok({"available": True, "balance": asyncio.run(read()),
                   "credits_per_piece": _CREDITS_PER_PIECE,
                   "max_per_project": int(settings.meshy_max_per_project)})
    except Exception as exc:                                   # noqa: BLE001
        return ok({"available": False, "reason": f"{type(exc).__name__}: {exc}",
                   "credits_per_piece": _CREDITS_PER_PIECE})


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
            "spatial_check": _read(root / "planning" / "spatial_check.json"),
            # What the client's own reference photos asked for, and how much of
            # it survived into this scene. Null until a plan has run.
            "design_intent": _read(root / "planning" / "design_intent.json"),
            "visual_intent_fidelity": _read(root / "planning" / "visual_intent_fidelity.json"),
            "scene_specs": store.list_scene_specs(project_id),
        }
    )


# ── Provenance (P1-IDENTITY-005) ────────────────────────────────────────


@router.get("/projects/{project_id}/provenance")
def get_provenance_coverage(project_id: str) -> dict:
    """How much of the committed scene traces back to a source photograph.

    The scene-wide form of the query below. Counted, never asserted: the
    acceptance criterion for P1-IDENTITY-005 is stated over *every* object, and
    a per-object endpoint alone cannot answer it without 14 round trips.
    """
    from ..provenance import coverage, ensure_indexed

    get_project_store().get(project_id)          # 404s on an unknown project
    ensure_indexed(project_id)
    return ok(coverage(project_id))


@router.get("/projects/{project_id}/provenance/{scene_object_id}")
def get_provenance(project_id: str, scene_object_id: str) -> dict:
    """What caused this rendered object to exist — the whole chain, by query.

    404 only when the object is not in the committed scene. An object that IS in
    the scene but whose chain stops early returns 200 with the hop that stopped
    it: "this piece has no source photograph" is an answer, and returning an
    error for it would make an ordinary catalog chair look like a failure.
    """
    from ..provenance import resolve

    get_project_store().get(project_id)
    chain = resolve(project_id, scene_object_id)
    if chain.origin == "unknown":
        return _error("OBJECT_NOT_FOUND",
                      f"No object {scene_object_id} in this project's committed scene.", 404)
    return ok(chain.model_dump(mode="json"))


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


# ── Share links (P0-SEC-004) ────────────────────────────────────────────
#
# The tour route itself is unchanged. What changed is who may reach it: the
# gate in authz.py now wants a capability token, because the project id used to
# BE the capability and a project id is not a secret.


class ShareLinkBody(BaseModel):
    label: str = ""
    #: None means "until revoked". An expiry is offered, not imposed: a link
    #: that dies on its own while a client is still looking at the design is a
    #: support call, and a silently-expiring share is worse than a revocable one.
    expires_in_days: Optional[int] = None


@router.post("/projects/{project_id}/share")
def create_share_link(project_id: str, body: ShareLinkBody, request: Request) -> dict:
    """Mint a link that shows this project's tour and nothing else.

    The token comes back ONCE. It is stored only as a SHA-256, so it cannot be
    reprinted - if it is lost, mint another and revoke this one.
    """
    from ..auth.capability import mint
    from ..auth.deps import require_principal

    get_project_store().get(project_id)               # 404 for a project that is not there
    principal = require_principal(request)
    days = body.expires_in_days
    if days is not None and days <= 0:
        return _error("INVALID_EXPIRY", "expires_in_days must be a positive number of days.", 422)

    token, tid = mint(project_id, created_by=principal.user_id,
                      label=body.label.strip()[:80], expires_in_days=days)
    return ok({
        "token_id": tid,
        "url": f"/w/{project_id}?k={token}",
        "token": token,
        "label": body.label.strip()[:80],
        "expires_in_days": days,
        "note": "This link is shown once. It grants read-only access to this "
                "project's tour and nothing else, and can be revoked at any time.",
    })


@router.get("/projects/{project_id}/share")
def list_share_links(project_id: str) -> dict:
    """Every link ever minted for this project, including revoked ones.

    Revoked links stay listed on purpose: "this stopped working on the 3rd" is
    what people actually ask, and a list that forgets them cannot answer.
    """
    from ..auth.capability import list_for_project

    get_project_store().get(project_id)
    return ok({"links": list_for_project(project_id)})


@router.delete("/projects/{project_id}/share/{token_id}")
def revoke_share_link(project_id: str, token_id: str) -> dict:
    """Break one link. Idempotent - revoking an already-dead link is not an
    error, because the caller's intent is already satisfied."""
    from ..auth.capability import revoke

    get_project_store().get(project_id)
    return ok({"revoked": revoke(project_id, token_id)})


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
    """One project's artifacts.

    Authorization happens in the gate (`authz.authorize`), which sees
    `project_id` as a path parameter and applies the same owner/member/admin
    rule as every other project route - plus the narrow share-link carve-out
    for `outputs/web/`. This function keeps doing exactly what it did: resolve
    the path and refuse anything outside the project directory.
    """
    root = project_dir(project_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        return _error("FILE_NOT_FOUND", f"No such project file: {path}", 404)
    return FileResponse(str(target))


def _serve_from(root, path: str, what: str):
    """Serve `path` from under `root`, or 404.

    `root not in target.parents` is the whole traversal guard: `..` segments
    are resolved first, so a path that climbs out simply is not under the root
    any more and never matches. A missing file and an escaping path answer
    identically, so the 404 cannot be used to map the filesystem.
    """
    root = Path(root).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        return _error("FILE_NOT_FOUND", f"No such {what}: {path}", 404)
    return FileResponse(str(target))


# The shared library. Not per-project, but not public either: a Meshy mesh is
# generated from somebody's moodboard crop, so a sofa in here can be as
# identifying as the photograph it came from. The gate requires a principal or
# a live share token - see authz.SHARED_LIBRARY.


@files_router.get("/files/assets/{path:path}")
def asset_file(path: str):
    from ..assets.registry import get_registry

    return _serve_from(get_registry().root / "normalized", path, "asset")


@files_router.get("/files/assets-web/{path:path}")
def asset_web_file(path: str):
    """The browser's copy: same geometry, textures sized to a GPU budget.
    Separate from `normalized/` because Blender reads that folder off disk and
    must keep getting every pixel."""
    from ..assets.registry import get_registry

    return _serve_from(get_registry().root / "web", path, "asset")


@files_router.get("/files/materials/{path:path}")
def material_file(path: str):
    from ..materials.registry import get_material_registry

    return _serve_from(get_material_registry().root, path, "material")


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

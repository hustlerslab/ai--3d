"""Aether walkthrough backend — FastAPI entry point.

Run:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.envelope import error_response
from .api.projects_routes import files_router
from .api.projects_routes import router as projects_router
from .api.routes import router
from .assets.registry import get_registry
from .blender import BlenderNotConfigured
from .core.config import get_settings
from .db import get_db
from .jobs import JobNotFound, UnknownJobType, get_runner
from .materials.registry import get_material_registry
from .projects import ProjectNotFound, get_project_store
from .scene.patches import PatchError
from .scene.store import SceneNotFound, VersionConflict, get_store
from .seed import ensure_seed

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aether")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    get_db()  # creates data/allure.db and the schema
    migrated = get_project_store().migrate_legacy(settings.data_dir / "projects.json")
    if migrated:
        log.info("Migrated %d project(s) from projects.json into SQLite", migrated)
    ensure_seed(get_store())
    runner = get_runner()
    runner.start()
    log.info(
        "Aether backend up. data_dir=%s gemini=%s meshy=%s blender=%s",
        settings.data_dir,
        "live" if settings.gemini_configured else "mock",
        "live" if settings.meshy_configured else "mock",
        settings.blender_path if settings.blender_configured else "unavailable",
    )
    try:
        yield
    finally:
        runner.shutdown(wait=False)


app = FastAPI(title="Aether Walkthrough Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(projects_router)

# Binary assets are served as static files, never through PostgreSQL/JSON
# (system design §26). Only the normalized models, material maps and the
# per-project artifact folders are exposed — never the raw data dir.
app.mount("/files/assets", StaticFiles(directory=str(get_registry().root / "normalized")), name="asset-files")
# The browser's copy: same geometry, textures sized to a GPU budget. A separate
# mount rather than a replacement, because Blender reads the normalized folder
# straight off disk and must keep getting every pixel.
_web_dir = get_registry().root / "web"
_web_dir.mkdir(parents=True, exist_ok=True)
app.mount("/files/assets-web", StaticFiles(directory=str(_web_dir)), name="asset-files-web")
app.mount("/files/materials", StaticFiles(directory=str(get_material_registry().root)), name="material-files")
app.include_router(files_router)  # /files/projects/{id}/{path} resolved per request


@app.exception_handler(ProjectNotFound)
async def project_not_found_handler(request: Request, exc: ProjectNotFound):
    return error_response("PROJECT_NOT_FOUND", f"Project {exc} not found.", 404)


@app.exception_handler(JobNotFound)
async def job_not_found_handler(request: Request, exc: JobNotFound):
    return error_response("JOB_NOT_FOUND", f"Job {exc} not found.", 404)


@app.exception_handler(UnknownJobType)
async def unknown_job_type_handler(request: Request, exc: UnknownJobType):
    return error_response("UNKNOWN_JOB_TYPE", f"Unknown job type '{exc}'. See GET /api/jobs/types.", 422)


@app.exception_handler(BlenderNotConfigured)
async def blender_not_configured_handler(request: Request, exc: BlenderNotConfigured):
    return error_response("BLENDER_NOT_CONFIGURED", str(exc), 503)


@app.exception_handler(SceneNotFound)
async def scene_not_found_handler(request: Request, exc: SceneNotFound):
    return error_response("SCENE_NOT_FOUND", f"Scene {exc} not found.", 404)


@app.exception_handler(VersionConflict)
async def version_conflict_handler(request: Request, exc: VersionConflict):
    return error_response(
        "VERSION_CONFLICT",
        f"Scene changed: your base version {exc.expected} is behind {exc.actual}. Refresh and retry.",
        409,
        retryable=True,
    )


@app.exception_handler(PatchError)
async def patch_error_handler(request: Request, exc: PatchError):
    payload = error_response(exc.code, exc.message, 422)
    if exc.violations:
        import json

        body = json.loads(payload.body)
        body["error"]["violations"] = [v.model_dump() for v in exc.violations]
        return type(payload)(status_code=422, content=body)
    return payload


@app.get("/")
def root():
    return {"service": "aether-walkthrough-backend", "docs": "/docs", "api": "/api"}

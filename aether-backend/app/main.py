"""Aether walkthrough backend — FastAPI entry point.

Run:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.envelope import error_response
from .api.projects_routes import files_router
from .auth import router as auth_router
from .auth.authz import authorize, current_actor
from .auth.deps import optional_principal
from fastapi.responses import JSONResponse

from .core import ratelimit
from .core.logging import bind, configure_logging, new_correlation_id
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

# P0-OBSERVABILITY-001. `basicConfig(level=INFO)` was the ENTIRE logging
# configuration; this replaces it with one JSON line per record, each carrying
# correlation_id / project_id / job_id / stage. Ids only - never a brief, a
# prompt, an image path or a key.
configure_logging()
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
    # Resolve the reasoning provider HERE, at boot, not lazily on the first job.
    # Its own logging then names the model that will read customers' homes while
    # somebody is still watching the console - see provider._announce.
    from .intelligence import get_provider

    provider = get_provider()
    log.info(
        "Aether backend up. data_dir=%s provider=%s model=%s mode=%s meshy=%s blender=%s",
        settings.data_dir,
        provider.name,
        provider.label,
        provider.mode,
        "live" if settings.meshy_configured else "mock",
        settings.blender_path if settings.blender_configured else "unavailable",
    )
    try:
        yield
    finally:
        runner.shutdown(wait=False)


app = FastAPI(title="Aether Walkthrough Backend", version="0.1.0", lifespan=lifespan)

# P0-SEC-002 made the session cookie essential, so CORS has to carry
# credentials. The CORS spec forbids wildcards once it does - a browser will
# refuse `*` for origin, methods or headers on a credentialed request - so all
# three are explicit. `cors_origins` is a parsed list and is never `*`, which is
# what makes allow_credentials safe here rather than an open door.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Identity first, so /api/auth/* is reachable even while the rest of the API
# is still open. P0-SEC-001 adds capability only - no route below is gated by
# it yet; P0-SEC-002 attaches require_principal to both routers.
@app.middleware("http")
async def _remember_who_is_asking(request: Request, call_next):
    """Record the caller for the life of the request.

    This has to be middleware. Setting the contextvar inside the `authorize`
    dependency looks equivalent and is not: FastAPI runs a sync dependency and
    a sync endpoint in two separate threadpool calls, each with its own copied
    context, so the value never arrives. Jobs were created with created_by=""
    and the per-user spend cap had nothing to attribute a charge to.

    Resolving the session here also means it is resolved once per request
    instead of twice - `authorize` reuses what this leaves on request.state.
    """
    principal = optional_principal(request)
    request.state.principal = principal
    token = current_actor.set(principal.user_id if principal else "")

    # One correlation id per request. An inbound X-Correlation-Id is honoured
    # so a frontend retry, or a call that fans out into jobs, stays one thread
    # in the logs; otherwise a fresh one is minted here.
    #
    # correlation_id ONLY. `request.path_params` is empty in middleware - this
    # runs before routing - so binding project_id here would silently bind
    # nothing. The runner binds project_id and job_id where they exist.
    cid = request.headers.get("x-correlation-id") or new_correlation_id()
    request.state.correlation_id = cid
    try:
        with bind(correlation_id=cid):
            # P0-SEC-006. Here rather than in its own middleware because the
            # decision needs the principal this one just resolved, and
            # resolving a session twice per request to answer one question is
            # waste.
            verdict = ratelimit.check(
                request.method,
                request.url.path,
                principal_id=principal.user_id if principal else None,
                client=request.client.host if request.client else None,
                settings=get_settings(),
            )
            if not verdict.allowed:
                log.warning("rate limit hit", extra={
                    "bucket": verdict.bucket,
                    "path": request.url.path,
                    "limit": verdict.limit,
                })
                return JSONResponse(
                    status_code=429,
                    headers={
                        "Retry-After": str(verdict.retry_after),
                        "X-Correlation-Id": cid,
                    },
                    content={
                        "success": False,
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": (
                                f"Too many requests. Try again in "
                                f"{verdict.retry_after} second(s)."
                            ),
                            # The one error in this codebase genuinely worth
                            # retrying: waiting is the fix.
                            "retryable": True,
                        },
                    },
                )
            response = await call_next(request)
            # Hand the id back so a user can quote it in a support request and
            # somebody can find the run without asking them what they clicked.
            response.headers["X-Correlation-Id"] = cid
            return response
    finally:
        current_actor.reset(token)


app.include_router(auth_router)
# P0-SEC-002: ONE dependency, both routers, deny by default. Attached here
# rather than on 63 individual route functions - a per-route check is a
# per-route opportunity to forget, and the forgotten one is the one that
# matters. The anonymous allow-list lives in authz.is_anonymous().
app.include_router(router, dependencies=[Depends(authorize)])
app.include_router(projects_router, dependencies=[Depends(authorize)])

# Binary assets are served as files, never through PostgreSQL/JSON (system
# design §26). Only the normalized models, material maps and the per-project
# artifact folders are exposed — never the raw data dir.
#
# P0-SEC-005: these were three bare StaticFiles mounts, which a router-level
# dependency cannot reach — a mount is not a route, so `authorize` never saw
# them and every byte was world-readable. They are ordinary routes now, on
# files_router, so the same gate covers them as covers everything else.
_web_dir = get_registry().root / "web"
_web_dir.mkdir(parents=True, exist_ok=True)
app.include_router(files_router, dependencies=[Depends(authorize)])


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

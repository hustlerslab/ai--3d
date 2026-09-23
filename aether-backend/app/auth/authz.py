"""Authorization: one choke point, deny by default — P0-SEC-002.

`deps.py` answers *who is asking*. This module answers *may they*. Keeping the
two apart is what let identity ship in P0-SEC-001 without changing behaviour:
nothing here existed yet.

**The gate is attached once**, in `main.py`, as a router-level dependency on
both routers. It is deliberately not sprinkled across 63 route functions — a
per-route check is a per-route opportunity to forget, and the one that gets
forgotten is the one that matters.

What stays anonymous, and why each is a decision rather than an oversight:

| Route | Why |
|---|---|
| `GET /health`, `GET /` | Liveness. A probe that needs credentials reports the wrong thing during an outage. |
| `/api/auth/*` | You cannot authenticate in order to authenticate. |
| `GET /api/projects/{id}/tour` | The share link `/w/{projectId}` is a *feature* (AUTH_PLAN.md). P0-SEC-004 replaces it with a capability token; until then, narrowing it would be a regression. |
| `/files/*` | AUTH_PLAN.md calls this the largest single hole, and it is P0-SEC-005's whole job. Guarding it here, in passing, would be worse than guarding it there, deliberately. |

Everything else requires a principal. Project-scoped and scene-scoped routes
additionally require that the principal may touch *that* project.
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from ..db.sqlite import get_db
from .capability import SCOPE_TOUR, project_for_token
from .deps import require_principal
from .service import Principal

log = logging.getLogger("aether.authz")

#: The user id of whoever is making the current request, or "".
#:
#: Read by `Runner.enqueue` so every job records who asked for it, without
#: threading a `request` argument through eleven route signatures that have no
#: other use for it.
#:
#: **Set by middleware, not by the `authorize` dependency.** That was the first
#: attempt and it silently did not work: FastAPI runs a sync dependency and a
#: sync endpoint in two SEPARATE threadpool calls, each with its own copied
#: context, so a value set in the dependency never reaches the endpoint. Jobs
#: came out with created_by="" and the per-user cap had nothing to attribute a
#: charge to. Middleware runs in the parent context, which both copies inherit.
#:
#: The job EXECUTES later on a worker thread where this is unset again - which
#: is exactly why the id is written to the job row at enqueue time.
current_actor: ContextVar[str] = ContextVar("current_actor", default="")

#: Exact (method, path) pairs that never require a principal.
ANONYMOUS_EXACT: set[tuple[str, str]] = {
    ("GET", "/"),
    ("GET", "/api/health"),
    ("GET", "/health"),
}

#: Any path starting with one of these is anonymous, for any method.
ANONYMOUS_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
# "/files/" was here until P0-SEC-005. It made every uploaded photograph, every
# render and every .blend readable by anyone who could guess a project id -
# what AUTH_PLAN.md calls the largest single hole. File routes are now
# authorized like any other project route, with a narrow capability carve-out
# for a share link (see capability_allows).

#: (method, compiled pattern) pairs. Kept tiny on purpose — every entry is a
#: hole somebody has to justify.
#:
#: EMPTY since P0-SEC-004. `GET /api/projects/{id}/tour` used to live here,
#: which meant the project id WAS the capability — a value that appears in
#: URLs, logs and support emails and that an owner can neither change nor
#: revoke. It now requires a capability token instead; see CAPABILITY_ROUTES.
ANONYMOUS_PATTERNS: list[tuple[str, re.Pattern]] = []

#: Where a share link carries its token. A query parameter because the whole
#: point is that it can be pasted into a message; a header cannot be.
#:
#: The cost, stated: query strings reach server logs, browser history and
#: `Referer` headers. That is why these tokens are scoped to one project and
#: one capability, and why revocation exists and is one call.
CAPABILITY_PARAM = "k"

#: The shared asset library: normalized meshes, their web-sized copies, and
#: material maps. Not per-project, but not public either - a Meshy mesh is
#: generated from somebody's moodboard crop, so a sofa in here can be as
#: identifying as the photograph it came from. A principal or a live share
#: token is required; nothing more specific, because these files genuinely are
#: shared across every project.
SHARED_LIBRARY = re.compile(r"^/files/(assets|assets-web|materials)/.+$")

#: The read-only catalog API the 3D viewer consults to resolve a scene's meshes
#: and materials. Same privacy class as SHARED_LIBRARY above - these describe
#: the shared library, not anybody's project - and the viewer cannot draw a
#: room without them. Reads only; every mutating asset route (upload, ingest,
#: renormalize) is absent by design.
#: The negative lookahead is defence in depth, not a live fix: capability_allows
#: already refuses every method but GET, and `upload` is a POST. It is here so
#: that adding a GET at that path later cannot silently inherit share access.
SHARED_CATALOG_READ = re.compile(
    r"^/api/(materials|assets|catalog)(/(?!upload$|ingest$)[^/]+)?/?$"
)

#: The scene routes the share page's "Explore in 3D" tab reads.
SCENE_READ = re.compile(r"^/api/scenes/(?P<scene_id>[^/]+)(?:/walkthrough/(?:spawn|tour|views))?/?$")


def capability_allows(request) -> bool:
    """Whether a share link may make THIS request.

    The rule is one sentence: a tour-scoped token grants read access to the
    published tour package and to exactly what that package points at. Every
    branch below is one thing the tour package references, and nothing else is
    reachable - the tests walk ten other project routes and expect 401 on all
    of them.
    """
    if request.method.upper() != "GET":
        return False                        # a link never writes
    token = request.query_params.get(CAPABILITY_PARAM, "")
    project_id = project_for_token(token, SCOPE_TOUR)
    if project_id is None:
        return False                        # absent, wrong, revoked or expired

    path = request.url.path

    # 1. the tour package itself
    if re.match(rf"^/api/projects/{re.escape(project_id)}/tour/?$", path):
        return True
    # 2. the rendered assets it names - panoramas, film, poster. Scoped to
    #    outputs/web/ so a link cannot reach the uploaded photographs, the
    #    analyses or the .blend in the same project directory.
    if path.startswith(f"/files/projects/{project_id}/outputs/web/"):
        return True
    # 3. the shared library the 3D tab needs to draw anything at all, and the
    #    catalog API that tells it which file belongs to which object
    if SHARED_LIBRARY.match(path) or SHARED_CATALOG_READ.match(path):
        return True
    # 4. the scene that package points at, and only that one
    match = SCENE_READ.match(path)
    if match and project_for_scene(match.group("scene_id")) == project_id:
        return True
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_anonymous(method: str, path: str) -> bool:
    if (method, path) in ANONYMOUS_EXACT:
        return True
    if path.startswith(ANONYMOUS_PREFIXES):
        return True
    return any(m == method and p.match(path) for m, p in ANONYMOUS_PATTERNS)


# ── ownership ─────────────────────────────────────────────────────────────

def project_owner(project_id: str) -> Optional[str]:
    row = get_db().one("SELECT owner_id FROM projects WHERE project_id = ?", (project_id,))
    return row["owner_id"] if row else None


def set_owner(project_id: str, user_id: str) -> None:
    get_db().execute(
        "UPDATE projects SET owner_id = ? WHERE project_id = ?", (user_id, project_id)
    )


def add_member(project_id: str, user_id: str, role: str = "designer") -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO project_members(project_id, user_id, role, created_at)"
        " VALUES (?, ?, ?, ?)",
        (project_id, user_id, role, _now_iso()),
    )


def project_for_scene(scene_id: str) -> Optional[str]:
    """Which project a scene belongs to, via `scene_specs`.

    A scene with no spec row belongs to no project — the seeded demo scenes are
    like this. Those are treated as shared: a principal is still required, but
    no ownership check applies, because there is no owner to check against.
    """
    row = get_db().one(
        "SELECT project_id FROM scene_specs WHERE scene_id = ? LIMIT 1", (scene_id,)
    )
    return row["project_id"] if row else None


def may_access_project(principal: Principal, project_id: str) -> bool:
    """Owner, assigned member, or admin. Anything else is False.

    An **unowned** project (owner_id IS NULL) is readable only by an admin. That
    is the deliberate consequence of NULL meaning "unclaimed": a legacy project
    is not public just because it predates the users table.
    """
    if principal.is_admin:
        return True
    db = get_db()
    row = db.one("SELECT owner_id FROM projects WHERE project_id = ?", (project_id,))
    if row is None:
        # A project that does not exist. Answer the same as "not yours", so the
        # 403 does not become a probe for which project ids are real.
        return False
    if row["owner_id"] and row["owner_id"] == principal.user_id:
        return True
    member = db.one(
        "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, principal.user_id),
    )
    return member is not None


def visible_project_ids(principal: Principal) -> Optional[set[str]]:
    """Which projects this principal may list. None means "all" (admin).

    Returning None rather than every id keeps the admin path from loading the
    whole table just to compare it against itself.
    """
    if principal.is_admin:
        return None
    db = get_db()
    owned = {r["project_id"] for r in db.query(
        "SELECT project_id FROM projects WHERE owner_id = ?", (principal.user_id,))}
    shared = {r["project_id"] for r in db.query(
        "SELECT project_id FROM project_members WHERE user_id = ?", (principal.user_id,))}
    return owned | shared


# ── first-run bootstrap ───────────────────────────────────────────────────

def claim_unowned_projects(user_id: str) -> int:
    """Give every unclaimed project to `user_id`. Returns how many moved."""
    db = get_db()
    n = db.scalar("SELECT COUNT(*) FROM projects WHERE owner_id IS NULL")
    db.execute("UPDATE projects SET owner_id = ? WHERE owner_id IS NULL", (user_id,))
    return int(n or 0)


def bootstrap_first_user(user_id: str) -> dict:
    """The first account ever created becomes admin and adopts existing work.

    Without this, switching on deny-by-default locks everyone out of a database
    that already holds projects: `owner_id` is NULL on all of them, only an
    admin may read an unowned project, and no admin exists. The alternative —
    inventing an owner inside a migration — would guess, and guess wrong.

    **The security cost, stated plainly:** between deploying this and creating
    the first account, whoever registers first becomes administrator and
    inherits every existing project. On a laptop that is the operator. On a
    reachable host it is a race, so the first account must be created before
    the host is exposed. P0-INFRA-001 carries that as a deployment step.

    Only fires when `users` holds exactly one row, so it cannot be replayed.
    """
    db = get_db()
    if int(db.scalar("SELECT COUNT(*) FROM users") or 0) != 1:
        return {"bootstrapped": False, "claimed": 0}
    db.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (user_id,))
    claimed = claim_unowned_projects(user_id)
    log.warning(
        "BOOTSTRAP: %s is the first account on this instance and has been made "
        "administrator, adopting %d previously unowned project(s). If that was "
        "not you, this instance was reachable before it was claimed.",
        user_id, claimed,
    )
    return {"bootstrapped": True, "claimed": claimed}


# ── the gate ──────────────────────────────────────────────────────────────

def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "success": False,
            "error": {
                "code": "FORBIDDEN",
                "message": "You do not have access to this project.",
                "retryable": False,
            },
        },
    )


def authorize(request: Request) -> Optional[Principal]:
    """The single router-level dependency. Deny by default.

    Order matters: 401 before 403. "Identify yourself" and "identifying
    yourself again will not help" are different instructions, and collapsing
    them leaves a signed-out user retrying forever.
    """
    method = request.method.upper()
    path = request.url.path
    if is_anonymous(method, path):
        return None

    # A valid share link, checked BEFORE demanding a session: the holder has no
    # account and never will. An invalid or absent one simply falls through to
    # the 401 below, so a wrong token is indistinguishable from no token.
    if capability_allows(request):
        return None

    principal = require_principal(request)          # 401 when nobody is asking

    project_id = request.path_params.get("project_id")
    if project_id is None:
        scene_id = request.path_params.get("scene_id")
        if scene_id is not None:
            project_id = project_for_scene(scene_id)
            if project_id is None:
                # A scene belonging to no project (the seeded demos). A
                # principal was still required; there is simply no owner to
                # compare against.
                return principal

    if project_id is not None and not may_access_project(principal, project_id):
        raise _forbidden()
    return principal

"""FastAPI dependencies that turn a request into a principal.

P0-SEC-001 ships these; **no route uses them yet**. P0-SEC-002 attaches
`require_principal` to both routers as a single deny-by-default gate. Keeping
the two steps apart is what lets identity land without breaking all 63 routes
in one commit.

Kept separate from `service.py` so that module stays free of FastAPI and can be
tested as plain Python.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from .service import Principal, resolve_session

#: Where the browser keeps the session once the frontend stops using a header.
#: AUTH_PLAN.md records sessionStorage as a demo-only choice with a stated
#: migration path to httpOnly cookies; accepting both now means that migration
#: is a frontend change alone.
COOKIE_NAME = "allure_session"


def session_token(request: Request) -> str:
    """`Authorization: Bearer <token>`, else the session cookie, else ''.

    The header wins, so an explicit token in a cURL call is never silently
    overridden by a stale cookie in the same browser.
    """
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(COOKIE_NAME) or ""


def optional_principal(request: Request) -> Optional[Principal]:
    """Who is asking, or None. Never raises.

    This is the dependency for routes that are *deliberately* anonymous — the
    `/w/{projectId}` share link is a feature, not a gap (AUTH_PLAN.md), and
    tightening it would be a regression, not a fix.

    The `_remember_who_is_asking` middleware resolves the session once per
    request and leaves the answer on `request.state`; reuse it rather than
    querying again. `hasattr` rather than a truthiness check, because a
    correctly-resolved *anonymous* request stores None and must not be
    re-resolved on every dependency that asks.
    """
    if hasattr(request.state, "principal"):
        return request.state.principal
    return resolve_session(session_token(request))


def require_principal(request: Request) -> Principal:
    """Who is asking. 401 when the answer is "nobody".

    Deliberately one error for every failure mode — absent, malformed, unknown,
    revoked, expired, disabled. Telling a caller *which* it was is an oracle,
    and none of the six deserves a different remedy: sign in again.
    """
    principal = optional_principal(request)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "NOT_AUTHENTICATED",
                    "message": "Sign in to continue.",
                    "retryable": False,
                },
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_admin(request: Request) -> Principal:
    """Admin only. 401 when nobody is asking, 403 when somebody is but may not.

    The two must stay distinct: 401 means "identify yourself", 403 means
    "identifying yourself again will not help".
    """
    principal = require_principal(request)
    if not principal.is_admin:
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "FORBIDDEN",
                    "message": "This action requires an administrator.",
                    "retryable": False,
                },
            },
        )
    return principal

"""`/api/auth/*` — register, sign in, sign out, who am I.

P0-SEC-001. These are the only routes that know about credentials. Everything
else in the codebase asks `require_principal` and never sees a password.

Nothing here enforces anything on the existing 63 routes; that is P0-SEC-002.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..api.envelope import error_response, ok
from .deps import COOKIE_NAME, optional_principal, require_principal, session_token
from .service import (
    DEFAULT_ROLE,
    SESSION_TTL,
    AuthError,
    create_user,
    login,
    revoke_all_sessions,
    revoke_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: str
    password: str
    # Self-registration cannot mint an admin. Roles above homeowner are granted,
    # never claimed — a field a stranger controls is not an authorization input.
    role: str = Field(default=DEFAULT_ROLE)


class LoginBody(BaseModel):
    email: str
    password: str


def _principal_payload(p) -> dict:
    """What a client is allowed to know about itself. No hash, no token, no
    internal columns — whatever is listed here is what leaks if this response
    is ever logged by a proxy."""
    return {"user_id": p.user_id, "email": p.email, "role": p.role}


def _set_cookie(response: Response, token: str) -> None:
    """httpOnly so script cannot read it; samesite=lax so a cross-site form post
    cannot ride it.

    `secure` is intentionally NOT set. This backend is served over plain HTTP on
    localhost today, and a secure cookie would simply never be stored — a login
    that silently does nothing. It must be turned on with TLS, which is recorded
    in P0-INFRA-001 rather than left to memory.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
    )


@router.post("/register")
def register(body: RegisterBody, response: Response):
    """Create an account and sign in with it in one step.

    Signing in here rather than making the caller post twice is deliberate: the
    password is already in memory, and a register-then-login dance is one more
    place to send it over the wire.
    """
    try:
        if body.role != DEFAULT_ROLE:
            raise AuthError(
                "ROLE_NOT_SELF_ASSIGNABLE",
                "Accounts are created as homeowner. Ask an administrator for another role.",
                status=403,
            )
        created = create_user(body.email, body.password)
    except AuthError as exc:
        return error_response(exc.code, exc.message, exc.status)

    # First account on a fresh or legacy instance becomes administrator and
    # adopts the projects that predate the users table. Without it,
    # deny-by-default locks everyone out of a database that already has work in
    # it. See authz.bootstrap_first_user for the security cost, stated.
    from .authz import bootstrap_first_user

    boot = bootstrap_first_user(created.user_id)

    token, principal = login(body.email, body.password)
    _set_cookie(response, token)
    return ok({"user": _principal_payload(principal), "token": token,
               "expires_in_days": SESSION_TTL.days, **boot})


@router.post("/login")
def sign_in(body: LoginBody, response: Response):
    try:
        token, principal = login(body.email, body.password)
    except AuthError as exc:
        return error_response(exc.code, exc.message, exc.status)
    _set_cookie(response, token)
    return ok({"user": _principal_payload(principal), "token": token,
               "expires_in_days": SESSION_TTL.days})


@router.post("/logout")
def sign_out(request: Request, response: Response):
    """Idempotent, and never 401.

    Signing out of a session that has already expired must not fail — a user
    clicking "sign out" wants to be signed out, and an error there teaches
    people to close the tab instead, which leaves the session alive.
    """
    ended = revoke_session(session_token(request))
    response.delete_cookie(COOKIE_NAME)
    return ok({"ended": ended})


@router.post("/logout-everywhere")
def sign_out_everywhere(request: Request, response: Response):
    """Kill every session for this user. The control you reach for when a laptop
    goes missing — and the reason these are opaque revocable tokens, not JWTs."""
    principal = require_principal(request)
    count = revoke_all_sessions(principal.user_id)
    response.delete_cookie(COOKIE_NAME)
    return ok({"revoked": count})


@router.get("/me")
def me(request: Request):
    """The dependency's own behaviour, exposed: a principal, or 401."""
    return ok({"user": _principal_payload(require_principal(request))})


@router.get("/session")
def session_status(request: Request):
    """Anonymous-safe companion to /me: 200 with `authenticated: false` rather
    than a 401. A frontend deciding whether to show a sign-in button should not
    have to treat a normal, expected state as an error."""
    principal = optional_principal(request)
    return ok({
        "authenticated": principal is not None,
        "user": _principal_payload(principal) if principal else None,
    })

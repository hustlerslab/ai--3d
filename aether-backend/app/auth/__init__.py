"""Identity for Allure — P0-SEC-001.

The rest of the codebase should import exactly two things from here:
`require_principal` (or `optional_principal`) and `Principal`. Everything else
is implementation, and keeping it that way is what allows the open A/B/C
identity decision in `docs/AUTH_PLAN.md` to be made later without a rewrite.

This package adds capability, not enforcement. No existing route is gated by
it; that is P0-SEC-002.
"""
from .deps import (  # noqa: F401
    COOKIE_NAME,
    optional_principal,
    require_admin,
    require_principal,
    session_token,
)
from .routes import router  # noqa: F401
from .service import (  # noqa: F401
    ROLES,
    AuthError,
    Principal,
    create_user,
    login,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
)

__all__ = [
    "COOKIE_NAME",
    "ROLES",
    "AuthError",
    "Principal",
    "create_user",
    "login",
    "optional_principal",
    "require_admin",
    "require_principal",
    "resolve_session",
    "revoke_all_sessions",
    "revoke_session",
    "router",
    "session_token",
]

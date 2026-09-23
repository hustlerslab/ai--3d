"""Identity: users, sessions, and the principal every route can ask for.

P0-SEC-001. This module gives the system a concept of *who is asking*. It
deliberately enforces nothing — adding enforcement here would break all 63
routes at once. P0-SEC-002 turns the dependency into a gate.

Two choices worth defending, because both were deliberate:

**Passwords use `hashlib.scrypt` from the standard library.** Not bcrypt, not
argon2, not passlib. scrypt is memory-hard, has been in the stdlib since 3.6,
and adding a dependency to a security path means owning its supply chain. The
parameters are stored *inside the hash string*, so raising them later is a
per-user upgrade on next login rather than a migration.

**Sessions are opaque random tokens, not JWTs.** `docs/AUTH_PLAN.md` cites an
HS256 JWT ADR — but that ADR belongs to a sibling codebase, and a JWT cannot be
revoked before it expires. A stolen session for a customer's home photographs
has to be killable *now*. Only the SHA-256 of the token is stored, so a database
leak does not hand over live sessions.

**The A/B/C decision in AUTH_PLAN.md is not pre-empted.** `users` carries both
`password_hash` (Option B, self-hosted) and `external_id` (Options A/C, managed
identity), either of which may be NULL. Choosing C later replaces
`verify_password` and adds a callback route; `Principal` and `require_principal`
— everything the rest of the codebase touches — do not change.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..db.sqlite import get_db

# Roles, deliberately three. AUTH_PLAN.md: "widen only when a real requirement
# appears." A permission matrix invented before anyone needs it is a matrix
# nobody can safely change later.
ROLES = ("homeowner", "designer", "admin")
DEFAULT_ROLE = "homeowner"

SESSION_TTL = timedelta(days=14)

# scrypt cost. n=2**14 is the stdlib's own documented interactive-login figure;
# it costs roughly 16 MB and tens of milliseconds here, which is the point.
_N, _R, _P, _DKLEN, _SALT_BYTES = 1 << 14, 8, 1, 32, 16

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 10


class AuthError(Exception):
    """Something about the credentials or the session is wrong.

    Carries an API error code so routes never have to invent one, and never
    have to decide how much to reveal — see `login`, which uses one code for
    both "no such user" and "wrong password".
    """

    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Principal:
    """Who is asking. The only auth type the rest of the codebase should know.

    Frozen because a request handler must never be able to promote itself by
    assigning to `role`.
    """

    user_id: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ── time ──────────────────────────────────────────────────────────────────
# Stored as ISO-8601 UTC with a Z, matching projects.created_at. Never a naive
# local timestamp: an expiry that means a different instant on a different
# machine is not an expiry.

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ── passwords ─────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt_b64$hash_b64`.

    The parameters live in the string so a future cost increase can be applied
    per user on next login instead of invalidating every password at once.
    """
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(
            "WEAK_PASSWORD",
            f"Password must be at least {MIN_PASSWORD_LEN} characters.",
            status=400,
        )
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "scrypt$%d$%d$%d$%s$%s" % (
        _N, _R, _P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. A malformed or empty hash is False, never a crash
    and never a pass — a user row with no password (Option A/C) must not be
    loggable-into with an empty string."""
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


# ── users ─────────────────────────────────────────────────────────────────

def normalise_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        raise AuthError("INVALID_EMAIL", "That does not look like an email address.", status=400)
    return e


def create_user(email: str, password: str, role: str = DEFAULT_ROLE) -> Principal:
    if role not in ROLES:
        raise AuthError("INVALID_ROLE", f"Role must be one of {', '.join(ROLES)}.", status=400)
    e = normalise_email(email)
    # Hash before the uniqueness check, so a weak password is rejected the same
    # way whether or not the email is already taken.
    pw = hash_password(password)
    db = get_db()
    if db.one("SELECT user_id FROM users WHERE email = ?", (e,)) is not None:
        raise AuthError("EMAIL_TAKEN", "That email is already registered.", status=409)
    user_id = "usr_" + uuid.uuid4().hex[:12]
    db.execute(
        "INSERT INTO users(user_id, email, role, password_hash, external_id, created_at)"
        " VALUES (?, ?, ?, ?, NULL, ?)",
        (user_id, e, role, pw, _iso(_now())),
    )
    return Principal(user_id=user_id, email=e, role=role)


def get_user_by_email(email: str):
    return get_db().one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))


def get_user(user_id: str):
    return get_db().one("SELECT * FROM users WHERE user_id = ?", (user_id,))


# ── sessions ──────────────────────────────────────────────────────────────

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(email: str, password: str) -> tuple[str, Principal]:
    """Returns (session_token, principal). The token is returned once and never
    stored — only its SHA-256 is.

    Both "no such user" and "wrong password" raise the *same* error. The
    difference is an account-enumeration oracle, and the cost of leaking it is
    paid by the user, not by us. The dummy verify on the missing-user path keeps
    the two branches taking comparable time.
    """
    row = get_user_by_email(email)
    if row is None:
        verify_password(password, hash_password("x" * MIN_PASSWORD_LEN))
        raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
    if row["disabled_at"]:
        raise AuthError("ACCOUNT_DISABLED", "This account has been disabled.", status=403)
    if not verify_password(password, row["password_hash"] or ""):
        raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
    principal = Principal(user_id=row["user_id"], email=row["email"], role=row["role"])
    return start_session(principal.user_id), principal


def start_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    get_db().execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, _iso(now), _iso(now + SESSION_TTL)),
    )
    return token


def resolve_session(token: str) -> Optional[Principal]:
    """The token -> principal lookup. None for anything not currently valid:
    unknown, revoked, expired, or belonging to a disabled account.

    One joined query, so a disabled account cannot keep working until its
    session happens to expire.
    """
    if not token:
        return None
    row = get_db().one(
        "SELECT s.expires_at, s.revoked_at, u.user_id, u.email, u.role, u.disabled_at"
        "  FROM sessions s JOIN users u ON u.user_id = s.user_id"
        " WHERE s.token_hash = ?",
        (_token_hash(token),),
    )
    if row is None or row["revoked_at"] or row["disabled_at"]:
        return None
    try:
        if _parse(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None  # an unparseable expiry is not a valid session
    return Principal(user_id=row["user_id"], email=row["email"], role=row["role"])


def revoke_session(token: str) -> bool:
    """Idempotent. Returns whether a live session was actually ended, which is
    what lets a caller tell "logged out" from "was never logged in"."""
    if not token:
        return False
    db = get_db()
    before = db.one(
        "SELECT revoked_at FROM sessions WHERE token_hash = ?", (_token_hash(token),)
    )
    if before is None or before["revoked_at"]:
        return False
    db.execute(
        "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
        (_iso(_now()), _token_hash(token)),
    )
    return True


def revoke_all_sessions(user_id: str) -> int:
    """Every session for a user. The control you need the day a laptop is lost;
    a JWT scheme could not offer it."""
    db = get_db()
    n = db.scalar(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND revoked_at IS NULL", (user_id,)
    )
    db.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (_iso(_now()), user_id),
    )
    return int(n or 0)


def expire_session_now(token: str) -> None:
    """Force a session's expiry into the past. Exists so tests can prove the
    expiry branch without sleeping for fourteen days."""
    get_db().execute(
        "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
        (_iso(_now() - timedelta(seconds=1)), _token_hash(token)),
    )

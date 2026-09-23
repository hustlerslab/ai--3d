"""Capability tokens — P0-SEC-004.

A share link is not a session, and building it out of one would be a mistake.
A session says *who you are* and unlocks everything that person may do. A
capability says *nothing about who you are* and unlocks exactly one thing on
exactly one project. Somebody forwarding a share link to a builder should not
be handing over an account.

So: unguessable, scoped, revocable, and optionally time-limited.

`docs/AUTH_PLAN.md` is explicit that anonymous sharing is **a feature, not a
gap**. What made it a hole was that the capability *was the project id* — a
value that appears in URLs, logs and support emails, and which the owner can
neither change nor revoke. The id still identifies the project; it just no
longer authorises anything.

Only the SHA-256 of a token is stored, as with sessions: a database leak must
not hand over working share links.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..db.sqlite import get_db

#: The only scope that exists today. A link can never quietly become a skeleton
#: key: widening is a deliberate act with a name, not a side effect of reusing
#: an existing token.
SCOPE_TOUR = "tour"
SCOPES = (SCOPE_TOUR,)

#: 32 bytes from `secrets` — the same strength as a session token. "Guessing a
#: project id does not grant access" is only true if guessing THIS does not
#: either.
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class Capability:
    """A granted capability. Never carries the token itself."""

    project_id: str
    scope: str
    label: str
    created_at: str
    expires_at: Optional[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_id(token: str) -> str:
    """A short, safe handle for one link.

    The first 12 characters of the hash: enough to name a link in a revoke call
    or a UI list, and useless for reconstructing the token.
    """
    return _hash(token)[:12]


def mint(
    project_id: str,
    *,
    created_by: Optional[str] = None,
    scope: str = SCOPE_TOUR,
    label: str = "",
    expires_in_days: Optional[int] = None,
) -> tuple[str, str]:
    """Create a share link. Returns (token, token_id).

    The token is returned **once**. It is not stored and cannot be recovered —
    if it is lost, mint another and revoke this one. That is a deliberate cost:
    a link the server can reprint is a link a server compromise can reprint.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown capability scope {scope!r}; known: {', '.join(SCOPES)}")
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = _now()
    get_db().execute(
        "INSERT INTO capability_tokens(token_hash, project_id, scope, created_by, label,"
        " created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        (_hash(token), project_id, scope, created_by, label, _iso(now),
         _iso(now + timedelta(days=expires_in_days)) if expires_in_days else None),
    )
    return token, token_id(token)


def resolve(token: str, project_id: str, scope: str = SCOPE_TOUR) -> Optional[Capability]:
    """The token -> capability lookup. None for anything not currently valid.

    `project_id` and `scope` are part of the QUERY, not checked afterwards. A
    valid token for project A must not even look like a near-miss for project
    B: there is no branch here in which the wrong project can be returned and
    then rejected by a caller who forgets to check.
    """
    if not token:
        return None
    row = get_db().one(
        "SELECT project_id, scope, label, created_at, expires_at, revoked_at"
        "  FROM capability_tokens"
        " WHERE token_hash = ? AND project_id = ? AND scope = ?",
        (_hash(token), project_id, scope),
    )
    if row is None or row["revoked_at"]:
        return None
    if row["expires_at"]:
        try:
            if _parse(row["expires_at"]) <= _now():
                return None
        except ValueError:
            return None  # an unparseable expiry is not a valid link
    return Capability(
        project_id=row["project_id"],
        scope=row["scope"],
        label=row["label"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def project_for_token(token: str, scope: str = SCOPE_TOUR) -> Optional[str]:
    """Which project a live token covers, or None.

    `resolve()` answers "is this token valid for THIS project", which is the
    right question when the project is already known from the path. A file or
    scene URL does not name the project, so this answers the other direction -
    and still refuses anything revoked or expired.
    """
    if not token:
        return None
    row = get_db().one(
        "SELECT project_id, expires_at, revoked_at FROM capability_tokens"
        " WHERE token_hash = ? AND scope = ?",
        (_hash(token), scope),
    )
    if row is None or row["revoked_at"]:
        return None
    if row["expires_at"]:
        try:
            if _parse(row["expires_at"]) <= _now():
                return None
        except ValueError:
            return None
    return row["project_id"]


def list_for_project(project_id: str) -> list[dict]:
    """Every link ever minted for a project, live or not.

    Revoked links are included on purpose: "this link stopped working on the
    3rd" is exactly what somebody asks about, and a list that silently forgets
    them cannot answer.
    """
    rows = get_db().query(
        "SELECT token_hash, scope, label, created_at, expires_at, revoked_at"
        "  FROM capability_tokens WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    )
    now = _now()
    out = []
    for r in rows:
        expired = False
        if r["expires_at"]:
            try:
                expired = _parse(r["expires_at"]) <= now
            except ValueError:
                expired = True
        out.append({
            "token_id": r["token_hash"][:12],
            "scope": r["scope"],
            "label": r["label"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "revoked_at": r["revoked_at"],
            "active": not r["revoked_at"] and not expired,
        })
    return out


def revoke(project_id: str, token_id_prefix: str) -> bool:
    """Kill one link by its id. Returns whether a live link was actually ended.

    Scoped to the project, so holding a token id from one project cannot revoke
    a link on another.
    """
    if not token_id_prefix:
        return False
    db = get_db()
    row = db.one(
        "SELECT token_hash, revoked_at FROM capability_tokens"
        " WHERE project_id = ? AND substr(token_hash, 1, 12) = ?",
        (project_id, token_id_prefix),
    )
    if row is None or row["revoked_at"]:
        return False
    db.execute(
        "UPDATE capability_tokens SET revoked_at = ? WHERE token_hash = ?",
        (_iso(_now()), row["token_hash"]),
    )
    return True


def revoke_all(project_id: str) -> int:
    """Kill every live link for a project — the "I shared that with the wrong
    person" button."""
    db = get_db()
    n = db.scalar(
        "SELECT COUNT(*) FROM capability_tokens WHERE project_id = ? AND revoked_at IS NULL",
        (project_id,),
    )
    db.execute(
        "UPDATE capability_tokens SET revoked_at = ? WHERE project_id = ? AND revoked_at IS NULL",
        (_iso(_now()), project_id),
    )
    return int(n or 0)

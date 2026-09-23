"""Rate limiting — P0-SEC-006.

A sliding window per (bucket, caller), in memory, with no dependency.

**Per principal, falling back to client address.** Keying on the address alone
would let one office behind one NAT exhaust everyone's allowance, and would
reset the moment an attacker changed IP. Keying on the principal alone cannot
work for `/api/auth/login`, where the whole point is that nobody has identified
themselves yet — that route is where a password-guessing attack lives, so it
falls back to the address and gets the strictest bucket.

**Buckets, not one global number.** Reading a project list and spending thirty
Meshy credits are not the same act and cannot share a limit: a number loose
enough for the first is useless for the second.

**Deliberately in-process, and the cost is stated.** The job runner is already
an in-process thread pool (`AUTH_PLAN.md` finding 2), so a second instance
would need a shared store for both. Until Allure runs more than one process a
dict is the honest amount of machinery — and a limiter that silently gave every
instance its own allowance would be worse than none, because it would read as
protection.

Times are `time.monotonic()`, never wall-clock: a clock change mid-window must
not widen a limit or void it.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

#: bucket -> (max requests, window seconds). Overridden from Settings at call
#: time; these are the shape, not the policy.
DEFAULT_BUCKETS: dict[str, tuple[int, int]] = {
    # Password guessing lives here. Strict, and keyed on the address because
    # the caller has not identified themselves yet.
    "auth": (10, 60),
    # Anything that spends real money.
    "spend": (5, 60),
    # Everything else that changes state.
    "write": (60, 60),
    # Reads. Generous: a studio page legitimately makes a burst of them, and a
    # limit that fires during normal use trains people to reload harder.
    "read": (300, 60),
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    bucket: str
    limit: int
    remaining: int
    retry_after: int          # seconds; 0 when allowed


class _Windows:
    """One sliding window per key. Old entries drop out as they age."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def take(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                # How long until the oldest hit leaves the window.
                retry = max(1, int(hits[0] + window - now) + 1)
                return False, 0, retry
            hits.append(now)
            return True, limit - len(hits), 0

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


_windows = _Windows()


def reset() -> None:
    """Drop every window. For tests, and for a deliberate operational reset."""
    _windows.clear()


def bucket_for(method: str, path: str) -> str:
    """Which limit applies. Most specific first."""
    if path.startswith("/api/auth/"):
        return "auth"
    if path.endswith("/elements/generate") or path.endswith("/assets/resolve"):
        return "spend"
    if path.endswith("/jobs") and method == "POST":
        # The wildcard dispatcher reaches both Meshy handlers (P0-ARCH-001), so
        # it is priced as spending even though most job types do not.
        return "spend"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    return "read"


def limits_from(settings) -> dict[str, tuple[int, int]]:
    """Read the policy off Settings, falling back to the defaults above."""
    window = int(getattr(settings, "rate_limit_window_seconds", 60) or 60)
    return {
        "auth": (int(getattr(settings, "rate_limit_auth_per_window", 10)), window),
        "spend": (int(getattr(settings, "rate_limit_spend_per_window", 5)), window),
        "write": (int(getattr(settings, "rate_limit_write_per_window", 60)), window),
        "read": (int(getattr(settings, "rate_limit_read_per_window", 300)), window),
    }


def check(
    method: str,
    path: str,
    *,
    principal_id: Optional[str],
    client: Optional[str],
    settings,
) -> Decision:
    """Whether this request may proceed.

    A limit of 0 or less disables that bucket. That is how the documented
    rollback works — "raise limits to effectively unlimited via configuration"
    — and it is why the check is built to be turned off from the outside rather
    than commented out from the inside.
    """
    if not getattr(settings, "rate_limit_enabled", True):
        return Decision(True, "disabled", 0, 0, 0)

    bucket = bucket_for(method, path)
    limit, window = limits_from(settings)[bucket]
    if limit <= 0:
        return Decision(True, bucket, 0, 0, 0)

    # The auth bucket keys on the address on purpose: a login attempt has no
    # principal, and one that did would let an attacker reset their own limit
    # by signing out.
    who = client or "unknown"
    if bucket != "auth" and principal_id:
        who = principal_id

    allowed, remaining, retry = _windows.take(f"{bucket}:{who}", limit, window)
    return Decision(allowed, bucket, limit, remaining, retry)

"""The spend ledger — P0-SEC-003.

Every credit this system spends is written to a row on disk before anyone asks
how much has been spent. That is the whole idea: an in-memory counter makes
"restart the process" a way to clear a spending limit, and a limit you can
clear by restarting is not a limit.

Three rules the rest of the codebase relies on:

**Actual over estimated, always.** `credits` is what the provider reported
consuming. When that figure genuinely is not available the row is marked
`is_estimate=1`, and totals report estimated and measured separately — an
estimated total that reads as measured is how a budget quietly becomes fiction.

**Record the charge, not the intention.** A row is written after the provider
confirms, so a failed generation that cost nothing leaves no row, and one that
cost something before failing still does.

**A refused batch changes nothing else.** Hitting a cap stops the spending and
leaves the project exactly as it was, with a warning a human can act on. It is
not an error state for the project.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..db.sqlite import get_db


@dataclass(frozen=True)
class Spend:
    """What has been spent, with measured and estimated kept apart."""

    measured: int
    estimated: int

    @property
    def total(self) -> int:
        """The number a cap is compared against.

        Estimated credits count. They were probably really spent, and leaving
        them out would make an unmeasurable charge a way to exceed the budget.
        """
        return self.measured + self.estimated

    @property
    def is_exact(self) -> bool:
        return self.estimated == 0


@dataclass(frozen=True)
class BudgetDecision:
    """Whether a batch may go ahead, and how much of it."""

    allowed: int          # how many pieces may be generated now
    requested: int
    reason: str           # empty when nothing was held back
    project_spent: int
    project_cap: int
    user_spent: int
    user_cap: int

    @property
    def blocked(self) -> bool:
        return self.allowed < self.requested

    @property
    def halted(self) -> bool:
        return self.allowed == 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_spend(
    project_id: str,
    credits: int,
    *,
    user_id: Optional[str] = None,
    job_id: str = "",
    provider: str = "meshy",
    item_key: str = "",
    is_estimate: bool = False,
) -> str:
    """Write one charge. Returns the record id.

    Zero-credit rows are still written when they represent a real decision (a
    reused asset, say), because "we generated nothing and it cost nothing" and
    "we never looked" are different facts.
    """
    record_id = "spd_" + uuid.uuid4().hex[:12]
    get_db().execute(
        "INSERT INTO spend_records(record_id, project_id, user_id, job_id, provider,"
        " item_key, credits, is_estimate, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (record_id, project_id, user_id, job_id, provider, item_key,
         int(credits), 1 if is_estimate else 0, _now_iso()),
    )
    return record_id


def _sum(where: str, params: tuple) -> Spend:
    row = get_db().one(
        "SELECT COALESCE(SUM(CASE WHEN is_estimate = 0 THEN credits ELSE 0 END), 0) AS measured,"
        "       COALESCE(SUM(CASE WHEN is_estimate = 1 THEN credits ELSE 0 END), 0) AS estimated"
        f"  FROM spend_records WHERE {where}",
        params,
    )
    return Spend(measured=int(row["measured"] or 0), estimated=int(row["estimated"] or 0))


def project_spend(project_id: str) -> Spend:
    return _sum("project_id = ?", (project_id,))


def user_spend(user_id: str) -> Spend:
    if not user_id:
        return Spend(0, 0)
    return _sum("user_id = ?", (user_id,))


def check_budget(
    project_id: str,
    user_id: Optional[str],
    pieces: int,
    credits_per_piece: int,
    project_cap: int,
    user_cap: int,
) -> BudgetDecision:
    """How many of `pieces` may be generated, given what is already spent.

    Both caps are read from the ledger on every call, so a restart cannot reset
    them and a second job on the same project cannot start the count again.

    A cap of 0 or less means "no limit" — for a deployment that deliberately
    runs uncapped. It is an explicit setting, never the default.

    Partial allowance is deliberate. With 3 of 10 pieces affordable, generating
    3 and flagging 7 is more useful than refusing all 10: the project moves
    forward and a human is told exactly what is waiting.
    """
    spent_project = project_spend(project_id).total
    spent_user = user_spend(user_id).total if user_id else 0

    limits = []
    if project_cap > 0:
        limits.append(("this project", project_cap - spent_project, project_cap, spent_project))
    if user_cap > 0 and user_id:
        limits.append(("your account", user_cap - spent_user, user_cap, spent_user))

    allowed = pieces
    reason = ""
    for label, remaining, cap, spent in limits:
        affordable = max(0, remaining) // max(1, credits_per_piece)
        if affordable < allowed:
            allowed = affordable
            reason = (
                f"{label} has spent {spent} of {cap} credits; "
                f"{max(0, remaining)} left, enough for {affordable} more piece(s) "
                f"at {credits_per_piece} each"
            )

    return BudgetDecision(
        allowed=max(0, min(allowed, pieces)),
        requested=pieces,
        reason=reason if allowed < pieces else "",
        project_spent=spent_project,
        project_cap=project_cap,
        user_spent=spent_user,
        user_cap=user_cap,
    )

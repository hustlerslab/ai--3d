"""What a person is told when the Supervisor acts (task.md §31, "Expected
user experience"). Plain words only: no category, code, id or round internals
beyond "N of 2" - the one number that stops a bounded repair looking like a
hang.
"""
from __future__ import annotations

from typing import Optional

from ..spatial.failures import FailureCategory as FC


def user_message(decision: str, *, category: Optional[FC] = None, repair_round: int = 0, cap: int = 2,
                 reason: str = "") -> str:
    slow = "timeout" in reason.lower() or "longer" in reason.lower() or "in_progress" in reason.lower()
    if decision == "RE_READ":
        return "We re-checked your room"
    if decision == "RE_SOLVE":
        return f"Correcting the layout — {repair_round} of {cap}"
    if decision == "REGENERATE":
        return "Taking longer than usual" if slow else "Rebuilding a piece that didn't come out right"
    if decision == "RETRY":
        return "Taking longer than usual" if slow else "Retrying"
    if decision in ("HUMAN_REVIEW", "ESCALATE", "FAIL"):
        return "One thing to look at"
    return ""


__all__ = ["user_message"]

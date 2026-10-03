"""The Orchestrator's policy table (design.md §21.3, P1-ORCHESTRATOR-001).

FailureCategory -> directive, for all twelve categories. The table decides;
a model is consulted only where the table abstains (UNKNOWN) and a model is
configured - and even then only among directives the table permits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from ..spatial.failures import FailureCategory as FC

Decision = Literal["CONTINUE", "RETRY", "REGENERATE", "RE_SOLVE", "RE_READ", "ESCALATE", "HUMAN_REVIEW", "FAIL"]
#: Decisions that dispatch a deterministic service through the queue.
DISPATCHING = frozenset({"RETRY", "REGENERATE", "RE_SOLVE", "RE_READ"})
#: Decisions that end in a person.
TO_HUMAN = frozenset({"ESCALATE", "HUMAN_REVIEW", "FAIL"})


@dataclass(frozen=True)
class Rule:
    decision: Decision
    job_type: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    #: After this many automatic rounds for this category, escalate instead.
    #: The runner's cap still applies on top; this is the policy's own view.
    escalate_after_round: Optional[int] = None


POLICY: dict[FC, Rule] = {
    # `force_read`, not only `force`: scene_plan re-plans on `force` but reads
    # the moodboard again only on `force_read` - RE_READ must actually re-read.
    FC.PERCEPTION_FAILURE: Rule("RE_READ", "scene_plan", {"force": True, "force_read": True},
                                "the model's reading was wrong: read again"),
    FC.ASSET_FAILURE: Rule("REGENERATE", "generate_elements", {},
                           "the asset was wrong: regenerate (bounded by the spend gates)"),
    FC.GEOMETRY_FAILURE: Rule("RE_SOLVE", "repair_scene", {},
                              "geometry is repaired by the Repair Engine - never a model asked for coordinates"),
    FC.SOLVER_FAILURE: Rule("RE_SOLVE", "repair_scene", {},
                            "the solver chose wrong among valid candidates: re-solve"),
    FC.CANDIDATE_VOCABULARY_FAILURE: Rule("HUMAN_REVIEW", note="code defect: no candidate could express a valid "
                                                               "solution - retrying is wasted spend"),
    FC.CONSTRAINT_FAILURE: Rule("HUMAN_REVIEW", note="code defect: a constraint was mis-specified or mis-compiled"),
    FC.REPRESENTATION_FAILURE: Rule("HUMAN_REVIEW", note="code defect: the data model could not express a true fact"),
    FC.REPAIR_FAILURE: Rule("ESCALATE", note="repair could not reach a valid scene"),
    FC.VALIDATION_FAILURE: Rule("HUMAN_REVIEW", note="a check was missing or wrong: a person decides"),
    FC.BLENDER_EXECUTION_FAILURE: Rule("RETRY", "build", {"force": True},
                                       "the build itself failed: retry once, then escalate",
                                       escalate_after_round=1),
    FC.HARDWARE_FAILURE: Rule("RETRY", None, {}, "a compute limit, not a wrong answer: requeue - never blame the model"),
    FC.UNKNOWN: Rule("ESCALATE", note="correctly abstained: evidence gathered, escalated - NOT 'no problem'"),
}

assert set(POLICY) == set(FC), "every FailureCategory must have a policy row"


def rule_for(category: FC, *, repair_round: int, failed_job_type: str = "") -> Rule:
    rule = POLICY[category]
    if rule.escalate_after_round is not None and repair_round >= rule.escalate_after_round:
        return Rule("ESCALATE", note=f"{rule.note} (already retried {repair_round} time(s))")
    if rule.decision == "RETRY" and rule.job_type is None:
        # requeue whatever failed; without a job to requeue, a person decides
        if not failed_job_type:
            return Rule("ESCALATE", note="a hardware limitation with no job to requeue")
        return Rule("RETRY", failed_job_type, {"force": True}, rule.note)
    return rule


__all__ = ["POLICY", "Rule", "rule_for", "Decision", "DISPATCHING", "TO_HUMAN"]

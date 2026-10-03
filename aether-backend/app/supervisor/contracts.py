"""Typed contracts between the Supervisor's agents (design.md §21).

Every agent speaks in these and nothing else. The point is what they CANNOT
carry: a `WatcherObservation` has `observed`/`expected`/`confidence`/
`detection_method` and no field where "looks correct" can travel, so one
agent's opinion cannot arrive at the next as a premise (§21.5).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CONTRACT_SCHEMA_VERSION = "1.0"

Severity = Literal["info", "warning", "error", "critical"]
AnomalyType = Literal[
    "missing_output", "unexpected_output", "schema_drift", "identity_discontinuity", "provenance_gap",
    "count_drift", "latency_outlier", "cost_outlier", "retry_storm", "state_regression", "none",
]
#: Provenance of a finding. `rule` and `statistic` are measured; `model` is a
#: suggestion. Consumers weight by it (P1-WATCHER-002).
DetectionMethod = Literal["rule", "statistic", "model"]
METHOD_WEIGHT: dict[str, float] = {"rule": 1.0, "statistic": 0.8, "model": 0.3}

#: Words that make a sentence an ACTION. A recommended_check is a question for
#: the Validator, never an instruction to the pipeline.
_ACTION_VERBS = ("retry", "regenerate", "re-solve", "resolve", "re_solve", "repair", "rerun", "re-run",
                 "escalate", "delete", "fix", "restart", "approve", "reject", "continue", "fail")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, *parts: Any) -> str:
    """Content-addressed id: the same finding about the same thing is the
    same observation, so observing twice records once."""
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


class WatcherObservation(BaseModel):
    observation_id: str
    schema_version: str = CONTRACT_SCHEMA_VERSION
    project_id: str
    job_id: str = ""
    stage: str = ""
    event_type: str = ""
    observed_at: str = Field(default_factory=_now)
    entity_ids: list[str] = []
    evidence_refs: list[str] = []
    anomaly_type: AnomalyType
    #: Which detector produced it - one of the nine rules, the statistic, or
    #: the model pass. Recorded so a finding can be traced to its code.
    detector: str
    observed: dict[str, Any] = {}
    expected: dict[str, Any] = {}
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    detection_method: DetectionMethod
    recommended_check: str
    watcher_version: str
    #: The event this finding rests on, when there is one.
    source_event_id: Optional[int] = None

    @field_validator("recommended_check")
    @classmethod
    def _a_check_not_an_action(cls, v: str) -> str:
        head = v.strip().lower()
        if not head.startswith(("check ", "verify ", "confirm ", "compare ", "inspect ")):
            raise ValueError("recommended_check must be a check (check/verify/confirm/compare/inspect ...), "
                             f"never an action: {v!r}")
        first_clause = head.split(":", 1)[0]
        if any(f" {verb} " in f" {first_clause} " for verb in _ACTION_VERBS):
            raise ValueError(f"recommended_check reads as an action: {v!r}")
        return v

    @property
    def weight(self) -> float:
        return METHOD_WEIGHT[self.detection_method]


from ..spatial.failures import FailureCategory  # noqa: E402 - the EXISTING enum, never a new one

ValidationStatus = Literal["PASS", "FAIL", "WARNING", "REVIEW_REQUIRED"]
RecommendedAction = Literal["continue", "retry", "regenerate_asset", "re_solve", "re_read", "human_review"]
EntityKind = Literal["element", "instance", "asset", "scene_object", "room", "report"]


class AffectedEntity(BaseModel):
    kind: EntityKind
    id: str


class ValidationResult(BaseModel):
    """design.md §21.2. The schema itself refuses the two things a verifier
    must never emit: a FAIL with nothing behind it, and a verdict whose
    failure category is not one of the existing twelve."""

    validation_id: str
    schema_version: str = CONTRACT_SCHEMA_VERSION
    project_id: str
    scene_id: str = ""
    scene_version: int = 0
    status: ValidationStatus
    severity: Severity
    issue_type: str
    failure_category: Optional[FailureCategory] = None
    affected_entities: list[AffectedEntity] = []
    expected: dict[str, Any] = {}
    observed: dict[str, Any] = {}
    evidence: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: RecommendedAction
    determinism: Literal["deterministic", "model_assisted"]
    rationale: str
    validator_version: str
    validated_at: str = Field(default_factory=_now)

    @field_validator("evidence")
    @classmethod
    def _paths(cls, v: list[str]) -> list[str]:
        from ..jobs.store import _check_evidence_refs

        return _check_evidence_refs(v)

    @model_validator(mode="after")
    def _verdict_is_supported(self) -> "ValidationResult":
        if self.status == "FAIL" and not self.evidence:
            raise ValueError("a FAIL must cite at least one evidence ref: an unsupported verdict is invalid")
        if self.status == "FAIL" and self.failure_category is None:
            raise ValueError("a FAIL must name its FailureCategory")
        if self.status == "PASS" and self.recommended_action != "continue":
            raise ValueError("a PASS recommends continue and nothing else")
        return self


DirectiveDecision = Literal["CONTINUE", "RETRY", "REGENERATE", "RE_SOLVE", "RE_READ", "ESCALATE",
                            "HUMAN_REVIEW", "FAIL"]


class DirectiveTarget(BaseModel):
    job_type: str = ""
    entity_ids: list[str] = []
    params: dict[str, Any] = {}


class DirectiveBasis(BaseModel):
    observation_ids: list[str] = []
    validation_ids: list[str] = []


class Directive(BaseModel):
    """design.md §21.3. What the Orchestrator decided, on what evidence, and
    whether a policy row or a model made the call."""

    directive_id: str
    schema_version: str = CONTRACT_SCHEMA_VERSION
    project_id: str
    job_id: str = ""
    decision: DirectiveDecision
    target: DirectiveTarget = DirectiveTarget()
    based_on: DirectiveBasis = DirectiveBasis()
    repair_round: int = 0
    rationale: str
    decided_by: Literal["policy", "model"]
    confidence: float = Field(ge=0.0, le=1.0)
    failure_category: Optional[FailureCategory] = None
    orchestrator_version: str
    decided_at: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _cites_and_targets(self) -> "Directive":
        if self.decision != "CONTINUE" and not (self.based_on.observation_ids or self.based_on.validation_ids):
            raise ValueError("every directive but CONTINUE must cite the observations/validations it rests on")
        if self.decision in ("RETRY", "REGENERATE", "RE_SOLVE", "RE_READ") and not self.target.job_type:
            raise ValueError(f"{self.decision} must name the deterministic service it dispatches")
        return self


_SEVERITY_RANK = {"info": 1, "warning": 2, "error": 3, "critical": 4}


def weigh(observations: list[WatcherObservation]) -> list[tuple[float, WatcherObservation]]:
    """How a consumer ranks findings: severity x method weight x confidence.
    A model narration (weight 0.3, confidence <= 0.5) can never outrank a
    rule finding of equal severity - that is the point of recording
    `detection_method` at all."""
    scored = [(_SEVERITY_RANK[o.severity] * o.weight * o.confidence, o) for o in observations]
    return sorted(scored, key=lambda t: -t[0])


__all__ = ["CONTRACT_SCHEMA_VERSION", "WatcherObservation", "AnomalyType", "DetectionMethod", "Severity",
           "METHOD_WEIGHT", "stable_id", "weigh", "ValidationResult", "AffectedEntity", "ValidationStatus"]

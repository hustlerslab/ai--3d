"""The Orchestrator — "What next?" (design.md §21.3, §32.4;
P1-ORCHESTRATOR-001 / 002, the decision side of P1-REPAIR-001).

Decides; directs deterministic services; never authors geometry. It is BUILT
with exactly three things - its own memory, a queue handle and a review
handle - and none of them can write a scene: the capability to move a sofa
is not in its object graph. Geometry failures go to the Repair Engine
(`repair_scene` job); no model is ever asked for coordinates.

The policy table decides (`policy.py`). A model - only if the orchestrator
role is configured - is consulted only where the table abstains (UNKNOWN),
and only to choose among directives the table allows. `decided_by` records
which.

The repair BOUND is not the Orchestrator's: `QueueHandle.dispatch` goes
through `JobRunner.request_repair`, which numbers the round itself and
refuses past `repair_max_rounds`. A misbehaving Orchestrator that asks for
repair forever gets a refusal and must escalate.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..spatial.failures import FailureCategory as FC
from .contracts import Directive, DirectiveBasis, DirectiveTarget, ValidationResult, WatcherObservation
from .memory import OrchestratorMemoryStore, as_untrusted_data, require_store
from .policy import DISPATCHING, POLICY, TO_HUMAN, rule_for
from .review import ReviewHandle

log = logging.getLogger("aether.supervisor.orchestrator")

ORCHESTRATOR_VERSION = "orchestrator@1.0"
#: The only services the Orchestrator can set in motion.
DISPATCHABLE = frozenset({"scene_plan", "repair_scene", "generate_elements", "build"})
_SEVERITY = {"info": 1, "warning": 2, "error": 3, "critical": 4}

MODEL_OPTIONS = ("RETRY", "RE_SOLVE", "RE_READ", "ESCALATE")
MODEL_SCHEMA = {"type": "object", "properties": {
    "decision": {"type": "string", "enum": list(MODEL_OPTIONS)},
    "rationale": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["decision", "rationale", "confidence"]}


#: What each option means, in words for the MODEL. Not the policy table's
#: notes: those are written for engineers ("correctly abstained: evidence
#: gathered, escalated") and, put in the prompt verbatim, left every model
#: benchmarked no better than a fixed answer. This wording is the one P1-MM-002
#: measured - gemma2:2b and qwen2.5vl:3b went from 4/16 to 8/16 correct, on
#: different cases - and it was frozen before being run, not tuned against
#: the result. Its meaning follows the policy rows each option dispatches to.
MODEL_OPTION_MEANINGS: dict[str, str] = {
    "RETRY": "the build itself failed, or a compute limit was hit - not a wrong answer: requeue.",
    "RE_SOLVE": "geometry is repaired by the Repair Engine; the solver chose wrong among valid candidates.",
    "RE_READ": "the model's reading of the client's photos was wrong: read again.",
    "ESCALATE": "repair could not reach a valid scene, or no automatic step is left: a person decides.",
}


def option_definitions() -> str:
    """Every option the model may choose, defined. P1-MM-002 found the prompt
    used to define only RE_SOLVE, and all four local models benchmarked then
    answered RE_SOLVE to every one of 16 labelled cases."""
    return ("The four options mean:\n"
            + "".join(f"- {o}: {MODEL_OPTION_MEANINGS[o]}\n" for o in MODEL_OPTIONS) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QueueHandle:
    """Enqueue-only. Holds one bound callable (`JobRunner.request_repair`) and
    the allow-list of services; no store, no scene, no job row."""

    def __init__(self, request_repair: Callable[..., Any]):
        self._request = request_repair

    def dispatch(self, project_id: str, job_type: str, params: dict[str, Any]) -> Optional[str]:
        if job_type not in DISPATCHABLE:
            raise PermissionError(f"the Orchestrator may not dispatch {job_type!r}")
        job = self._request(project_id, job_type, params, requested_by="orchestrator")
        return None if job is None else job.job_id


class AuditTrail:
    """P1-ORCHESTRATOR-002: one `repair_rounds` row per round, filled as the
    round progresses. Reads the database; cannot reach a scene."""

    def __init__(self, project_id: str):
        from ..db import get_db

        self.project_id = project_id
        self._db = get_db()

    def open_round(self, *, round_no: int, directive: Directive, failure: Optional[ValidationResult],
                   action_job_id: str, action_job_type: str, outcome: str, scene_version: int,
                   correlation_id: str) -> str:
        round_id = "rr_" + uuid.uuid4().hex[:12]
        self._db.execute(
            """INSERT INTO repair_rounds(round_id, project_id, correlation_id, round, failure_category,
                    failure_evidence, validation_ids, validator_status, directive_id, decision, rationale,
                    decided_by, action_job_id, action_job_type, scene_version_before, outcome,
                    created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (round_id, self.project_id, correlation_id, round_no,
             directive.failure_category.value if directive.failure_category else "",
             json.dumps(failure.evidence if failure else []), json.dumps(directive.based_on.validation_ids),
             failure.status if failure else "", directive.directive_id, directive.decision, directive.rationale,
             directive.decided_by, action_job_id, action_job_type, scene_version, outcome, _now(), _now()))
        return round_id

    def close_round(self, action_job_id: str, *, scene_version_after: int, second_validation: str,
                    outcome: str) -> bool:
        row = self._db.one("SELECT round_id FROM repair_rounds WHERE project_id = ? AND action_job_id = ? "
                           "AND outcome = 'in_progress'", (self.project_id, action_job_id))
        if row is None:
            return False
        self._db.execute(
            "UPDATE repair_rounds SET scene_version_after = ?, second_validation = ?, outcome = ?, updated_at = ? "
            "WHERE round_id = ?", (scene_version_after, second_validation, outcome, _now(), row["round_id"]))
        return True

    def rounds(self) -> list[dict[str, Any]]:
        out = []
        for r in self._db.query("SELECT * FROM repair_rounds WHERE project_id = ? ORDER BY created_at",
                                (self.project_id,)):
            d = dict(r)
            d["failure_evidence"], d["validation_ids"] = json.loads(d["failure_evidence"]), json.loads(d["validation_ids"])
            out.append(d)
        return out


def _failing(validations: list[ValidationResult]) -> list[ValidationResult]:
    """What calls for a decision: a FAIL, or a REVIEW_REQUIRED that means a
    verifier ran and could not vouch. `appearance_unverified` (no model, or
    nothing rendered) is a deployment state and is not escalated."""
    return [v for v in validations
            if v.status == "FAIL" or (v.status == "REVIEW_REQUIRED" and v.issue_type != "appearance_unverified")]


class Orchestrator:
    def __init__(self, memory: OrchestratorMemoryStore, queue: QueueHandle, review: ReviewHandle,
                 provider: Any = None):
        require_store(memory, OrchestratorMemoryStore)
        if not isinstance(queue, QueueHandle) or not isinstance(review, ReviewHandle):
            raise TypeError("the Orchestrator is built with a QueueHandle and a ReviewHandle, nothing else")
        self.memory = memory
        self.queue = queue
        self.review = review
        self.provider = provider

    # -- decide ---------------------------------------------------------------
    def decide(self, validations: list[ValidationResult], observations: list[WatcherObservation], *,
               repair_round: int, job_id: str = "", failed_job_type: str = "") -> Directive:
        failing = _failing(validations)
        serious = [o for o in observations if o.detection_method != "model" and _SEVERITY[o.severity] >= 3]
        # §31 row 13: the Validator's model contradicting the deterministic
        # layers is itself the finding - a person sees BOTH verdicts.
        conflict = self._conflict(validations)
        if conflict is not None:
            model_v, det_ids = conflict
            return self._directive("HUMAN_REVIEW", "policy", 1.0,
                                   "the Validator's model disagrees with the deterministic checks; both verdicts "
                                   "are shown for a person to judge",
                                   job_id=job_id, repair_round=repair_round, category=FC.VALIDATION_FAILURE,
                                   validations=[model_v.validation_id, *det_ids],
                                   target=DirectiveTarget(entity_ids=[e.id for e in model_v.affected_entities]))
        if not failing:
            return self._from_observations(observations, job_id=job_id, repair_round=repair_round,
                                           validations=[v.validation_id for v in validations])

        worst = max(failing, key=lambda v: (_SEVERITY[v.severity], v.status == "FAIL"))
        category = worst.failure_category or FC.UNKNOWN
        if worst.status == "REVIEW_REQUIRED":
            category = FC.UNKNOWN if worst.failure_category is None else category
        rule = rule_for(category, repair_round=repair_round, failed_job_type=failed_job_type)
        decision, by, confidence, why = rule.decision, "policy", 1.0, rule.note
        if category is FC.UNKNOWN and self.provider is not None:
            decision, by, confidence, why = self._ask_model(worst, observations, rule.decision, why)
            if decision in DISPATCHING and not rule.job_type:
                rule = POLICY[FC.SOLVER_FAILURE] if decision == "RE_SOLVE" else (
                    POLICY[FC.PERCEPTION_FAILURE] if decision == "RE_READ" else rule)
        entity_ids = [e.id for e in worst.affected_entities]
        return self._directive(decision, by, confidence, why, job_id=job_id, repair_round=repair_round,
                               category=category, validations=[v.validation_id for v in failing],
                               observations=[o.observation_id for o in serious],
                               target=DirectiveTarget(job_type=rule.job_type or "", entity_ids=entity_ids,
                                                      params=dict(rule.params)) if decision in DISPATCHING
                               else DirectiveTarget(entity_ids=entity_ids))

    def _conflict(self, validations: list[ValidationResult]):
        """A model-assisted FAIL about geometry, while every deterministic
        verdict on geometry is clean (the deterministic layers own geometry)."""
        geometric = {FC.GEOMETRY_FAILURE, FC.SOLVER_FAILURE, FC.REPAIR_FAILURE}
        model_fails = [v for v in validations if v.determinism == "model_assisted" and v.status == "FAIL"
                       and v.failure_category in geometric]
        det = [v for v in validations if v.determinism == "deterministic"]
        det_geometry_fail = [v for v in det if v.status == "FAIL" and v.failure_category in geometric]
        if model_fails and not det_geometry_fail:
            return model_fails[0], [v.validation_id for v in det] or ["deterministic:clean"]
        return None

    def _from_observations(self, observations: list[WatcherObservation], *, job_id: str, repair_round: int,
                           validations: list[str]) -> Directive:
        """No verdict failed. A Watcher finding is a question, not a verdict:
        rule-measured identity breaks are perception (§31 row 1); spend above
        budget is escalated; statistical or model hunches do not disrupt the
        pipeline (§31 row 14)."""
        rule = [o for o in observations if o.detection_method == "rule"]
        identity = [o for o in rule if o.anomaly_type in ("count_drift", "identity_discontinuity")]
        if identity:
            r = rule_for(FC.PERCEPTION_FAILURE, repair_round=repair_round)
            return self._directive(r.decision, "policy", 1.0, "the element chain lost pieces between the reading "
                                   "and the committed scene: " + r.note, job_id=job_id, repair_round=repair_round,
                                   category=FC.PERCEPTION_FAILURE,
                                   observations=[o.observation_id for o in identity],
                                   target=DirectiveTarget(job_type=r.job_type or "", params=dict(r.params),
                                                          entity_ids=sorted({i for o in identity for i in o.entity_ids})))
        spend = [o for o in rule if o.anomaly_type == "cost_outlier"]
        if spend:
            return self._directive("ESCALATE", "policy", 1.0, "spend above the project budget", job_id=job_id,
                                   repair_round=repair_round, category=FC.UNKNOWN,
                                   observations=[o.observation_id for o in spend])
        return self._directive("CONTINUE", "policy", 1.0,
                               "no failing verdict; Watcher findings recorded as questions, not acted on"
                               if observations else "no failing verdict and no observation",
                               job_id=job_id, repair_round=repair_round, validations=validations)

    def _ask_model(self, worst: ValidationResult, observations: list[WatcherObservation], default: str,
                   why: str) -> tuple[str, str, float, str]:
        from .providers import RoleProviderError

        prompt = ("A verification failed and no policy row covers it. Choose the next step. Coordinates are "
                  "never yours to choose: RE_SOLVE hands geometry to the deterministic Repair Engine.\n\n"
                  + option_definitions()
                  + as_untrusted_data({"verdict": worst.model_dump(mode="json"),
                                       "observations": [o.model_dump(mode="json") for o in observations[:10]]}))
        try:
            answer = self.provider.complete_json(prompt, MODEL_SCHEMA, "orchestrator.decide")
        except RoleProviderError as exc:
            return default, "policy", 1.0, f"{why}; model unavailable ({exc})"
        decision = answer.get("decision")
        if decision not in ("RETRY", "RE_SOLVE", "RE_READ", "ESCALATE"):
            return default, "policy", 1.0, f"{why}; model answer unusable"
        try:
            conf = max(0.0, min(1.0, float(answer.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.6:
            return default, "policy", 1.0, f"{why}; model not confident ({conf:.2f})"
        return decision, "model", conf, str(answer.get("rationale", ""))[:500] or "model choice"

    def _directive(self, decision: str, by: str, confidence: float, rationale: str, *, job_id: str,
                   repair_round: int, category: Optional[FC] = None, validations: Optional[list[str]] = None,
                   observations: Optional[list[str]] = None,
                   target: Optional[DirectiveTarget] = None) -> Directive:
        return Directive(directive_id="dir_" + uuid.uuid4().hex[:12], project_id=self.memory.project_id,
                         job_id=job_id, decision=decision, target=target or DirectiveTarget(),
                         based_on=DirectiveBasis(observation_ids=observations or [],
                                                 validation_ids=validations or []),
                         repair_round=repair_round, rationale=rationale, decided_by=by, confidence=confidence,
                         failure_category=category, orchestrator_version=ORCHESTRATOR_VERSION)

    # -- act ------------------------------------------------------------------
    def act(self, directive: Directive, *, failure: Optional[ValidationResult] = None,
            audit: Optional[AuditTrail] = None, scene_version: int = 0, correlation_id: str = "") -> dict[str, Any]:
        out = self._act(directive, failure=failure, audit=audit, scene_version=scene_version,
                        correlation_id=correlation_id)
        from ..core.config import get_settings
        from .messages import user_message

        final = out.get("decision", directive.decision)
        out["user_message"] = user_message(final, category=directive.failure_category,
                                           repair_round=directive.repair_round + 1,
                                           cap=get_settings().repair_max_rounds,
                                           reason=(failure.rationale if failure else directive.rationale))
        if final != "CONTINUE":
            self._announce(directive, final, out)
        return out

    def _announce(self, directive: Directive, final: str, out: dict[str, Any]) -> None:
        """What a person sees, as a typed event (canonical types
        repair.requested / human_review.required). Never fails the act."""
        try:
            from ..jobs.store import get_job_store

            event_type = "human_review.required" if "review_item" in out else "repair.requested"
            get_job_store().add_event(
                directive.project_id, "supervisor", "decided", out["user_message"],
                event_type=event_type, severity="warning" if event_type == "repair.requested" else "error",
                producer="supervisor.orchestrator", entity_ids=directive.target.entity_ids,
                payload={"decision": final, "directive_id": directive.directive_id,
                         "failure_category": directive.failure_category.value if directive.failure_category else "",
                         "job_id": out.get("job_id", ""), "review_item": out.get("review_item", "")})
        except Exception:                                  # noqa: BLE001
            log.warning("supervisor decision not announced")

    def _act(self, directive: Directive, *, failure: Optional[ValidationResult] = None,
             audit: Optional[AuditTrail] = None, scene_version: int = 0, correlation_id: str = "") -> dict[str, Any]:
        self.memory.append("directive", directive.model_dump(mode="json"), key=directive.directive_id,
                           job_id=directive.job_id, entity_ids=directive.target.entity_ids)
        if directive.decision == "CONTINUE":
            return {"decision": "CONTINUE"}
        if directive.decision in DISPATCHING:
            job_id = self.queue.dispatch(directive.project_id, directive.target.job_type, directive.target.params)
            if job_id is not None:
                if audit is not None:
                    audit.open_round(round_no=directive.repair_round + 1, directive=directive, failure=failure,
                                     action_job_id=job_id, action_job_type=directive.target.job_type,
                                     outcome="in_progress", scene_version=scene_version,
                                     correlation_id=correlation_id)
                self.memory.append("repair_round", {"directive_id": directive.directive_id, "job_id": job_id},
                                   key=job_id, job_id=job_id)
                return {"decision": directive.decision, "job_id": job_id}
            # The runner refused: the bound is reached. Escalate, recorded.
            directive = directive.model_copy(update={
                "directive_id": "dir_" + uuid.uuid4().hex[:12], "decision": "ESCALATE",
                "rationale": f"automatic repair limit reached; {directive.rationale}"})
            self.memory.append("escalation", directive.model_dump(mode="json"), key=directive.directive_id)
        return self._escalate(directive, failure=failure, audit=audit, scene_version=scene_version,
                              correlation_id=correlation_id)

    def _escalate(self, directive: Directive, *, failure: Optional[ValidationResult], audit: Optional[AuditTrail],
                  scene_version: int, correlation_id: str) -> dict[str, Any]:
        category = directive.failure_category
        code_defect = category in (FC.REPRESENTATION_FAILURE, FC.CONSTRAINT_FAILURE, FC.CANDIDATE_VOCABULARY_FAILURE)
        recommendation = "accept_as_is" if (failure and failure.status == "REVIEW_REQUIRED") else (
            "replan" if category in (FC.PERCEPTION_FAILURE, FC.ASSET_FAILURE) else
            "retry_repair" if category in (FC.GEOMETRY_FAILURE, FC.SOLVER_FAILURE, FC.REPAIR_FAILURE) and not code_defect
            else "accept_as_is")
        item = self.review.open(
            project_id=directive.project_id,
            issue=(failure.rationale if failure else directive.rationale)[:500],
            category=category, issue_type=failure.issue_type if failure else "",
            entity_ids=directive.target.entity_ids, evidence_refs=list(failure.evidence) if failure else [],
            expected=failure.expected if failure else {}, observed=failure.observed if failure else {},
            recommendation=recommendation, actions=["accept_as_is", "retry_repair", "replan", "cancel"],
            directive_id=directive.directive_id)
        if audit is not None:
            audit.open_round(round_no=directive.repair_round, directive=directive, failure=failure,
                             action_job_id="", action_job_type="human_review", outcome="escalated",
                             scene_version=scene_version, correlation_id=correlation_id)
        return {"decision": directive.decision, "review_item": item["item_id"], "audience": item["audience"]}


def orchestrate_project(project_id: str, trigger_job, validations: list[ValidationResult],
                        observations: list[WatcherObservation]) -> Optional[dict[str, Any]]:
    """Called by the runner after the Validator. Advisory: never raises."""
    from ..core.config import get_settings

    s = get_settings()
    if not (s.supervisor_enabled and s.orchestrator_enabled):
        return None
    memory = None
    try:
        from ..jobs import get_runner
        from ..projects import get_project_store
        from ..projects.schema import ProjectStage
        from .providers import get_role_provider, role_config

        runner = get_runner()
        project = get_project_store().get(project_id)
        audit = AuditTrail(project_id)
        scene_version = max((v.scene_version for v in validations), default=0)
        failing = _failing(validations)

        if getattr(trigger_job, "repair_round", 0) > 0:
            summary = ", ".join(sorted({f"{v.issue_type}:{v.status}" for v in validations})) or "no verdict"
            audit.close_round(trigger_job.job_id, scene_version_after=scene_version, second_validation=summary,
                              outcome="resolved" if not failing else "failed_again")
            if not failing and project.stage == ProjectStage.REPAIRING:
                get_project_store().set_stage(project_id, ProjectStage.SCENE_VALIDATING)

        memory = OrchestratorMemoryStore(project_id, agent_version=ORCHESTRATOR_VERSION)
        provider = get_role_provider("orchestrator") if role_config("orchestrator").enabled else None
        orch = Orchestrator(memory, QueueHandle(runner.request_repair), ReviewHandle(), provider=provider)
        directive = orch.decide(validations, observations, repair_round=runner.repair_rounds_used(project_id),
                                job_id=trigger_job.job_id, failed_job_type=trigger_job.type)
        worst = max(failing, key=lambda v: (_SEVERITY[v.severity], v.status == "FAIL")) if failing else None
        outcome = orch.act(directive, failure=worst, audit=audit, scene_version=scene_version,
                           correlation_id=project.correlation_id)
        return {"directive": directive.model_dump(mode="json"), **outcome}
    except Exception:                                      # noqa: BLE001
        log.exception("orchestrator failed for %s; pipeline unaffected", project_id)
        return None
    finally:
        if memory is not None:
            memory.close()


__all__ = ["Orchestrator", "QueueHandle", "AuditTrail", "orchestrate_project", "ORCHESTRATOR_VERSION",
           "DISPATCHABLE"]

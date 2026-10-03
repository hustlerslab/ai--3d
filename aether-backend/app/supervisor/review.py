"""Human review — P1-HUMAN-001. Escalation as a piece of work with evidence,
not an error path.

A review item carries the issue, the affected things BY HUMAN NAME, evidence,
expected vs observed, what was attempted per round, a recommendation and the
explicit actions available. A decision records who, why and what resulted,
and an override (an action other than the recommendation) requires a reason.

Routing: a rendering or infrastructure defect goes to OPERATIONS, never to the
homeowner; a reading or asset problem to the DESIGNER; a question of taste or
intent to the HOMEOWNER.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator

from ..spatial.failures import FailureCategory as FC

Audience = Literal["homeowner", "designer", "operations"]
Action = Literal["accept_as_is", "retry_repair", "replan", "cancel"]

AUDIENCE_FOR: dict[FC, Audience] = {
    FC.PERCEPTION_FAILURE: "designer",
    FC.ASSET_FAILURE: "designer",
    FC.GEOMETRY_FAILURE: "operations",
    FC.SOLVER_FAILURE: "operations",
    FC.CANDIDATE_VOCABULARY_FAILURE: "operations",
    FC.CONSTRAINT_FAILURE: "operations",
    FC.REPRESENTATION_FAILURE: "operations",
    FC.REPAIR_FAILURE: "operations",
    FC.VALIDATION_FAILURE: "operations",
    FC.BLENDER_EXECUTION_FAILURE: "operations",
    FC.HARDWARE_FAILURE: "operations",
    FC.UNKNOWN: "operations",
}
#: Who may see (and decide) which audience's items.
VISIBLE_TO: dict[str, set[str]] = {
    "homeowner": {"homeowner"},
    "designer": {"homeowner", "designer"},
    "admin": {"homeowner", "designer", "operations"},
}
#: What each action is for, in words a reviewer reads.
ACTION_TEXT: dict[str, str] = {
    "accept_as_is": "Accept the design as it is",
    "retry_repair": "Try the automatic repair again",
    "replan": "Re-plan the room from the approved moodboard",
    "cancel": "Stop work on this project",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewDecisionIn(BaseModel):
    action: Action
    reason: str = ""


class ReviewError(ValueError):
    pass


class DecisionRecord(BaseModel):
    decision_id: str
    item_id: str
    user_id: str
    user_email: str
    action: Action
    is_override: bool
    reason: str
    result: dict[str, Any]
    created_at: str

    @model_validator(mode="after")
    def _override_needs_reason(self) -> "DecisionRecord":
        if not self.user_id:
            raise ValueError("a decision names the person who made it")
        if self.is_override and len(self.reason.strip()) < 10:
            raise ValueError("overriding the recommendation requires a reason (at least a sentence)")
        return self


def audience_for(category: Optional[FC], issue_type: str = "") -> Audience:
    if issue_type.startswith("appearance") and category in (None, FC.ASSET_FAILURE):
        return "homeowner"          # does it look like what they asked for: their call
    return AUDIENCE_FOR.get(category or FC.UNKNOWN, "operations")


def _names(project_id: str) -> dict[str, str]:
    """entity id -> the name a person uses for it, read from the project's own
    files (read-only)."""
    from ..projects.layout import project_dir

    root = project_dir(project_id)
    names: dict[str, str] = {}
    for rel, key in (("planning/scene_spec.json", "objects"),):
        try:
            for o in json.loads((root / rel).read_text("utf-8")).get(key, []):
                label = (o.get("name") or o.get("semantic_type", "item")).replace("_", " ")
                room = o.get("room_id", "")
                names[o.get("object_id", "")] = label
                if o.get("element_id"):
                    names.setdefault(o["element_id"], label)
                if room:
                    names.setdefault(room, room.replace("_", " "))
        except (OSError, ValueError, AttributeError):
            pass
    try:
        reading = json.loads((root / "planning/scene_reading.json").read_text("utf-8"))
        for d in reading.get("definitions", []):
            names.setdefault(d.get("element_id", ""), (d.get("canonical_name") or d.get("semantic_type", "")).replace("_", " "))
    except (OSError, ValueError, AttributeError):
        pass
    return names


def _human(entity_id: str, names: dict[str, str]) -> dict[str, str]:
    if entity_id in names:
        return {"name": names[entity_id], "id": entity_id}
    if entity_id.endswith((".png", ".jpg", ".json")):
        return {"name": "the " + entity_id.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " "), "id": entity_id}
    return {"name": "an unnamed item", "id": entity_id}


class ReviewQueue:
    """The review store. The Orchestrator gets `ReviewHandle` (create only);
    the API gets this."""

    def __init__(self, db=None):
        from ..db import get_db

        self._db = db or get_db()

    # -- creation (via ReviewHandle) ------------------------------------------
    def create_item(self, *, project_id: str, issue: str, category: Optional[FC], issue_type: str = "",
                    entity_ids: list[str], evidence_refs: list[str], expected: dict, observed: dict,
                    recommendation: str, actions: list[str], directive_id: str = "") -> dict[str, Any]:
        from ..projects import get_project_store
        from ..projects.schema import ProjectStage

        names = _names(project_id)
        attempts = [
            {"round": r["round"], "decision": r["decision"], "action": r["action_job_type"],
             "outcome": r["outcome"], "rationale": r["rationale"]}
            for r in self._db.query("SELECT * FROM repair_rounds WHERE project_id = ? ORDER BY created_at",
                                    (project_id,))]
        project = get_project_store().get(project_id)
        item = {
            "item_id": "rev_" + uuid.uuid4().hex[:12], "project_id": project_id, "status": "open",
            "audience": audience_for(category, issue_type), "issue": issue,
            "failure_category": category.value if category else "",
            "affected": [_human(i, names) for i in entity_ids], "evidence_refs": evidence_refs,
            "expected": expected, "observed": observed, "attempts": attempts,
            "recommendation": recommendation, "actions": actions, "directive_id": directive_id,
            "stage_before": project.stage.value, "created_at": _now(), "resolved_at": None,
        }
        self._db.execute(
            """INSERT INTO review_items(item_id, project_id, status, audience, issue, failure_category, affected,
                                        evidence_refs, expected, observed, attempts, recommendation, actions,
                                        directive_id, stage_before, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["item_id"], project_id, "open", item["audience"], issue, item["failure_category"],
             json.dumps(item["affected"]), json.dumps(evidence_refs), json.dumps(expected, default=str),
             json.dumps(observed, default=str), json.dumps(attempts), recommendation, json.dumps(actions),
             directive_id, item["stage_before"], item["created_at"]))
        get_project_store().set_stage(project_id, ProjectStage.HUMAN_REVIEW)
        return item

    # -- reading ---------------------------------------------------------------
    def _row(self, r) -> dict[str, Any]:
        d = dict(r)
        for f in ("affected", "evidence_refs", "expected", "observed", "attempts", "actions"):
            d[f] = json.loads(d[f])
        d["action_labels"] = {a: ACTION_TEXT.get(a, a) for a in d["actions"]}
        d["decisions"] = [dict(x) | {"result": json.loads(x["result"]), "is_override": bool(x["is_override"])}
                          for x in self._db.query("SELECT * FROM review_decisions WHERE item_id = ? "
                                                  "ORDER BY created_at", (d["item_id"],))]
        return d

    def items(self, project_id: str, *, role: str, status: Optional[str] = None) -> list[dict[str, Any]]:
        visible = VISIBLE_TO.get(role, {"homeowner"})
        sql = "SELECT * FROM review_items WHERE project_id = ?"
        params: tuple = (project_id,)
        if status:
            sql += " AND status = ?"
            params += (status,)
        return [self._row(r) for r in self._db.query(sql + " ORDER BY created_at", params)
                if r["audience"] in visible]

    def get(self, project_id: str, item_id: str) -> Optional[dict[str, Any]]:
        r = self._db.one("SELECT * FROM review_items WHERE project_id = ? AND item_id = ?", (project_id, item_id))
        return None if r is None else self._row(r)

    # -- deciding --------------------------------------------------------------
    def decide(self, project_id: str, item_id: str, principal, body: ReviewDecisionIn) -> dict[str, Any]:
        """Record who decided what and why, then do it. Never deletes project
        state: the worst an action does is queue work or change the stage."""
        from ..jobs import get_runner
        from ..projects import get_project_store
        from ..projects.schema import ProjectStage

        item = self.get(project_id, item_id)
        if item is None:
            raise ReviewError("no such review item")
        if item["audience"] not in VISIBLE_TO.get(principal.role, {"homeowner"}):
            raise ReviewError("this item is routed to a different audience")
        if item["status"] != "open":
            raise ReviewError("this item has already been resolved")
        if body.action not in item["actions"]:
            raise ReviewError(f"{body.action!r} is not one of this item's actions: {item['actions']}")
        is_override = body.action != item["recommendation"]
        # Validate BEFORE acting: an override without a reason changes nothing.
        DecisionRecord(decision_id="probe", item_id=item_id, user_id=principal.user_id,
                       user_email=principal.email, action=body.action, is_override=is_override,
                       reason=body.reason, result={}, created_at=_now())

        projects = get_project_store()
        result: dict[str, Any] = {}
        if body.action == "accept_as_is":
            projects.set_stage(project_id, ProjectStage.VERIFIED)
            result = {"stage": ProjectStage.VERIFIED.value}
        elif body.action in ("retry_repair", "replan"):
            job_type = "repair_scene" if body.action == "retry_repair" else "scene_plan"
            # A person asked: an ordinary job (repair_round 0), which also
            # starts a fresh automatic-repair budget.
            job = get_runner().enqueue(project_id, job_type, {"force": True} if job_type == "scene_plan" else {},
                                       created_by=principal.user_id)
            result = {"job_id": job.job_id, "job_type": job_type}
        elif body.action == "cancel":
            projects.set_stage(project_id, ProjectStage.CANCELLED)
            result = {"stage": ProjectStage.CANCELLED.value}

        record = DecisionRecord(decision_id="dec_" + uuid.uuid4().hex[:12], item_id=item_id,
                                user_id=principal.user_id, user_email=principal.email, action=body.action,
                                is_override=is_override, reason=body.reason.strip(), result=result,
                                created_at=_now())
        with self._db.tx() as c:
            c.execute(
                """INSERT INTO review_decisions(decision_id, item_id, project_id, user_id, user_email, action,
                                                is_override, reason, result, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (record.decision_id, item_id, project_id, record.user_id, record.user_email, record.action,
                 int(record.is_override), record.reason, json.dumps(result), record.created_at))
            c.execute("UPDATE review_items SET status = 'resolved', resolved_at = ? WHERE item_id = ?",
                      (record.created_at, item_id))
        try:
            from ..jobs.store import get_job_store

            get_job_store().add_event(project_id, "review", "decided", f"{body.action} by {principal.email}",
                                      event_type="human_review.decided", severity="info", producer="api.review",
                                      entity_ids=[item_id], payload={"action": body.action,
                                                                     "override": is_override, **result})
        except Exception:                                  # noqa: BLE001
            pass
        return record.model_dump()


class ReviewHandle:
    """What the Orchestrator is given: it can open an item, and nothing else -
    it cannot read, decide or resolve one."""

    def __init__(self, queue: Optional[ReviewQueue] = None):
        self._create = (queue or ReviewQueue()).create_item

    def open(self, **kw) -> dict[str, Any]:
        return self._create(**kw)


__all__ = ["ReviewQueue", "ReviewHandle", "ReviewDecisionIn", "DecisionRecord", "ReviewError", "audience_for",
           "AUDIENCE_FOR", "ACTION_TEXT"]

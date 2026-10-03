"""The Watcher — "What happened?" (design.md §21.1, P1-WATCHER-001).

Reads the event stream and nothing else; writes its own memory and nothing
else. Rules first: the nine detectors below are pure functions of events,
settings and the Watcher's own latency history. They make ZERO model calls -
they do not even receive the provider. A model is consulted only afterwards,
on the residue, and its findings are marked `detection_method="model"` so
they never carry the weight of a count (P1-WATCHER-002).

Advisory and outside the data path (§21.6): `watch_project()` is called after a
job ends, never raises, and changes nothing the pipeline reads.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..core.config import get_settings
from ..jobs.schema import JobEvent
from ..projects.schema import STAGE_ORDER, ProjectStage
from .contracts import WatcherObservation, stable_id
from .memory import WatcherMemoryStore, require_store

log = logging.getLogger("aether.supervisor.watcher")

WATCHER_VERSION = "watcher@1.0"

#: A job type that SUCCEEDED must have produced this output event, in this
#: job or an earlier one (a checkpoint re-run legitimately skips it).
EXPECTED_OUTPUT: dict[str, str] = {"scene_plan": "scene.committed"}
#: Error types that mean a document did not match its schema.
SCHEMA_ERRORS = ("ValidationError", "JSONDecodeError", "SchemaError", "ContractError")
KNOWN_EVENT_SCHEMAS = {"", "1.0"}

Detector = Callable[["_Context"], list[WatcherObservation]]


def _ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


class _Context:
    """Everything a detector may read. Deliberately no provider."""

    def __init__(self, project_id: str, events: list[JobEvent], memory: WatcherMemoryStore,
                 now: datetime, project_root: Optional[Path]):
        self.project_id = project_id
        self.events = sorted(events, key=lambda e: e.event_id)
        self.memory = memory
        self.now = now
        self.project_root = project_root
        self.settings = get_settings()
        self.by_job: dict[str, list[JobEvent]] = defaultdict(list)
        for e in self.events:
            if e.job_id:
                self.by_job[e.job_id].append(e)

    def obs(self, *, anomaly_type: str, detector: str, severity: str, confidence: float, method: str,
            observed: dict, expected: dict, check: str, event: Optional[JobEvent] = None,
            entity_ids: Optional[list[str]] = None, key: Any = "") -> WatcherObservation:
        return WatcherObservation(
            observation_id=stable_id("obs", self.project_id, detector, anomaly_type,
                                     event.event_id if event else "", key),
            project_id=self.project_id, job_id=event.job_id if event else "",
            stage=event.stage if event else "", event_type=event.event_type if event else "",
            entity_ids=sorted(entity_ids or []), evidence_refs=list(event.evidence_refs) if event else [],
            anomaly_type=anomaly_type, detector=detector, observed=observed, expected=expected,
            severity=severity, confidence=confidence, detection_method=method, recommended_check=check,
            watcher_version=WATCHER_VERSION, source_event_id=event.event_id if event else None)


# ── the nine rule detectors ─────────────────────────────────────────────────


def missing_terminal_event(ctx: _Context) -> list[WatcherObservation]:
    """A job started and never finished, and has been silent too long."""
    out = []
    for job_id, evs in ctx.by_job.items():
        transitions = [e for e in evs if e.producer == "jobs.runner"]
        if not transitions or transitions[-1].event_type not in ("job.started", "job.queued"):
            continue
        last = transitions[-1]
        age = (ctx.now - _ts(last.ts)).total_seconds()
        if age < ctx.settings.watcher_stale_job_seconds:
            continue
        out.append(ctx.obs(
            anomaly_type="missing_output", detector="missing_terminal_event", severity="error",
            confidence=1.0, method="rule", event=last, key=job_id,
            observed={"last_event": last.event_type, "silent_seconds": int(age)},
            expected={"terminal_event": ["job.succeeded", "job.failed", "job.retrying"],
                      "within_seconds": ctx.settings.watcher_stale_job_seconds},
            check=f"Check whether job {job_id} ({last.stage}) is still running or its worker died"))
    return out


def absent_output(ctx: _Context) -> list[WatcherObservation]:
    """A stage said it succeeded but its promised output is not there: either
    the output event never fired, or an event's evidence path is missing."""
    out = []
    seen_types: set[str] = set()
    for e in ctx.events:
        if e.event_type:
            seen_types.add(e.event_type)
        if e.event_type == "job.succeeded" and e.stage in EXPECTED_OUTPUT:
            want = EXPECTED_OUTPUT[e.stage]
            if want not in seen_types:
                out.append(ctx.obs(
                    anomaly_type="missing_output", detector="absent_output_checkpoint", severity="error",
                    confidence=1.0, method="rule", event=e, key=want,
                    observed={"succeeded": e.stage, "output_event": None},
                    expected={"output_event": want},
                    check=f"Verify that {e.stage} wrote its output: no {want} event exists for this project"))
    if ctx.project_root is not None:
        for e in ctx.events:
            missing = [r for r in e.evidence_refs if not (ctx.project_root / r).exists()]
            if missing:
                out.append(ctx.obs(
                    anomaly_type="missing_output", detector="absent_output_checkpoint", severity="warning",
                    confidence=1.0, method="rule", event=e, key="evidence:" + ",".join(missing),
                    observed={"missing_evidence": missing}, expected={"evidence_refs_exist": True},
                    check=f"Check whether {', '.join(missing)} was moved or never written"))
    return out


def schema_parse_failure(ctx: _Context) -> list[WatcherObservation]:
    out = []
    for e in ctx.events:
        if e.schema_version not in KNOWN_EVENT_SCHEMAS:
            out.append(ctx.obs(
                anomaly_type="schema_drift", detector="schema_parse_failure", severity="warning",
                confidence=1.0, method="rule", event=e, key="event_schema",
                observed={"event_schema_version": e.schema_version},
                expected={"event_schema_version": sorted(KNOWN_EVENT_SCHEMAS)},
                check="Check which producer writes this event schema version"))
        if e.event_type in ("job.failed", "job.retrying"):
            error = str(e.payload.get("error", ""))
            if error.startswith(SCHEMA_ERRORS):
                out.append(ctx.obs(
                    anomaly_type="schema_drift", detector="schema_parse_failure", severity="error",
                    confidence=1.0, method="rule", event=e, key="job_error",
                    observed={"error": error[:300]}, expected={"parses": True},
                    check=f"Inspect the document {e.stage} failed to parse against its schema"))
    return out


def _identity_then_commit(ctx: _Context) -> list[tuple[JobEvent, JobEvent]]:
    """Each scene.committed paired with the latest moodboard identity
    resolution before it - the upstream/downstream pair the next two
    detectors compare."""
    pairs = []
    latest: Optional[JobEvent] = None
    for e in ctx.events:
        if e.event_type == "element.identity.resolved" and e.payload.get("source") == "moodboard_reading":
            latest = e
        elif e.event_type == "scene.committed" and latest is not None:
            pairs.append((latest, e))
    return pairs


def element_count_drift(ctx: _Context) -> list[WatcherObservation]:
    out = []
    for upstream, commit in _identity_then_commit(ctx):
        want = int(upstream.payload.get("instances", 0))
        got = int(commit.payload.get("with_identity", 0))
        if want != got:
            out.append(ctx.obs(
                anomaly_type="count_drift", detector="element_count_drift",
                severity="warning" if got else "error", confidence=1.0, method="rule", event=commit,
                key=upstream.event_id,
                observed={"placed_with_identity": got, "commit_event_id": commit.event_id},
                expected={"instances_resolved": want, "identity_event_id": upstream.event_id},
                check=f"Compare the {want} resolved instance(s) with the {got} placed object(s) carrying identity"))
    return out


def element_id_discontinuity(ctx: _Context) -> list[WatcherObservation]:
    out = []
    for upstream, commit in _identity_then_commit(ctx):
        lost = sorted(set(upstream.entity_ids) - set(commit.entity_ids))
        if lost:
            out.append(ctx.obs(
                anomaly_type="identity_discontinuity", detector="element_id_discontinuity", severity="error",
                confidence=1.0, method="rule", event=commit, entity_ids=lost, key=upstream.event_id,
                observed={"missing_downstream": lost, "commit_event_id": commit.event_id},
                expected={"present_upstream_in": upstream.event_id},
                check=f"Check why {len(lost)} resolved element(s) have no placed object in the committed scene"))
    return out


def latency_outlier(ctx: _Context) -> list[WatcherObservation]:
    """Against the stage's own history across projects - aggregates only,
    never another project's rows. Each duration is compared with the history
    BEFORE it is added to it."""
    out = []
    k, min_n = ctx.settings.watcher_latency_sigma, ctx.settings.watcher_latency_min_samples
    for e in ctx.events:
        if e.event_type != "job.succeeded" or e.duration_ms <= 0:
            continue
        if ctx.memory.has_key("latency_sample", e.job_id):
            continue                                    # already judged on an earlier pass
        hist = ctx.memory.aggregate("latency_sample", e.stage)
        limit = hist["mean"] + k * hist["sd"]
        if hist["n"] >= min_n and hist["sd"] > 0 and e.duration_ms > limit:
            out.append(ctx.obs(
                anomaly_type="latency_outlier", detector="latency_outlier", severity="warning",
                confidence=0.8, method="statistic", event=e, key="latency",
                observed={"duration_ms": e.duration_ms},
                expected={"at_most_ms": round(limit), "mean_ms": round(hist["mean"]), "sd_ms": round(hist["sd"]),
                          "n": int(hist["n"]), "sigma": k},
                check=f"Check what slowed {e.stage}: {e.duration_ms} ms against a historical {round(hist['mean'])} ms"))
        ctx.memory.append("latency_sample", {"project_id": ctx.project_id}, key=e.job_id, stage=e.stage,
                          job_id=e.job_id, value=float(e.duration_ms))
    return out


def cost_above_budget(ctx: _Context) -> list[WatcherObservation]:
    cap = ctx.settings.meshy_max_credits_per_project
    spent_events = [e for e in ctx.events if e.event_type == "asset.generated"]
    spent = sum(int(e.payload.get("credits", 0) or 0) for e in spent_events)
    if cap <= 0 or spent <= cap or not spent_events:
        return []
    last = spent_events[-1]
    return [ctx.obs(
        anomaly_type="cost_outlier", detector="cost_above_budget", severity="critical", confidence=1.0,
        method="rule", event=last, key=f"spent>{cap}",
        entity_ids=[i for e in spent_events for i in e.entity_ids],
        observed={"credits_spent": spent, "generations": len(spent_events)},
        expected={"credits_at_most": cap},
        check=f"Verify the spend ledger against {spent} credits reported by events, above the {cap} cap")]


def retry_storm(ctx: _Context) -> list[WatcherObservation]:
    out = []
    limit = ctx.settings.watcher_retry_threshold
    for job_id, evs in ctx.by_job.items():
        retries = [e for e in evs if e.event_type == "job.retrying"]
        if len(retries) > limit:
            out.append(ctx.obs(
                anomaly_type="retry_storm", detector="retry_count_above_threshold", severity="warning",
                confidence=1.0, method="rule", event=retries[-1], key=job_id,
                observed={"retries": len(retries), "errors": [str(r.payload.get("error", ""))[:120]
                                                              for r in retries]},
                expected={"retries_at_most": limit},
                check=f"Check whether the {len(retries)} failures of {retries[-1].stage} share one cause"))
    return out


def stage_moved_backwards(ctx: _Context) -> list[WatcherObservation]:
    out = []
    order = {s.value: i for i, s in enumerate(STAGE_ORDER)}
    for e in ctx.events:
        if e.event_type != "project.stage.changed":
            continue
        a, b = e.payload.get("from"), e.payload.get("to")
        if ProjectStage.FAILED.value in (a, b) or a not in order or b not in order:
            continue
        if order[b] < order[a]:
            out.append(ctx.obs(
                anomaly_type="state_regression", detector="stage_moved_backwards", severity="warning",
                confidence=1.0, method="rule", event=e, key=f"{a}->{b}",
                observed={"from": a, "to": b}, expected={"stage_order": "forward"},
                check=f"Check whether the move {a} -> {b} was requested by a user or lost completed work"))
    return out


RULE_DETECTORS: tuple[Detector, ...] = (
    missing_terminal_event, absent_output, schema_parse_failure, element_count_drift,
    element_id_discontinuity, latency_outlier, cost_above_budget, retry_storm, stage_moved_backwards,
)


# ── the agent ──────────────────────────────────────────────────────────────


NARRATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"anomalies": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "event_ids": {"type": "array", "items": {"type": "integer"}},
            "summary": {"type": "string"},
            "severity": {"type": "string", "enum": ["info", "warning"]},
            "recommended_check": {"type": "string"},
        },
        "required": ["event_ids", "summary", "severity", "recommended_check"],
    }}},
    "required": ["anomalies"],
}
#: A model's finding is a suggestion: it can never outrank a count.
MODEL_MAX_CONFIDENCE = 0.5
MODEL_SEVERITIES = ("info", "warning")


def residual_events(events: list[JobEvent], rule_findings: list[WatcherObservation]) -> list[JobEvent]:
    """Events that look wrong and that no rule already explains. Only these
    reach the model - the rules own everything they can see."""
    covered = {o.source_event_id for o in rule_findings if o.source_event_id is not None}
    suspicious = []
    for e in events:
        if e.event_id in covered or e.producer == "jobs.runner":
            continue
        if e.severity in ("warning", "error", "critical") or e.status in ("warning", "failed"):
            suspicious.append(e)
    return suspicious


def _narration_prompt(residue: list[JobEvent]) -> str:
    from .memory import as_untrusted_data

    rows = [{"event_id": e.event_id, "stage": e.stage, "status": e.status, "event_type": e.event_type,
             "severity": e.severity, "message": e.message[:400], "entity_ids": e.entity_ids[:20]}
            for e in residue]
    return ("These pipeline events were flagged but match no deterministic rule. Describe any pattern "
            "among them that a reviewer should look into. Cite event_ids. Severity at most 'warning'. "
            "Each recommended_check must be a CHECK starting with 'Check', 'Verify', 'Compare' or "
            "'Inspect' - never an action. Return an empty list if there is no pattern.\n\n"
            + as_untrusted_data(rows))


class Watcher:
    """Built with exactly one memory - its own - and optionally the provider
    for the residual narration pass. The rule pass never sees the provider."""

    def __init__(self, memory: WatcherMemoryStore, provider: Any = None):
        require_store(memory, WatcherMemoryStore)
        self.memory = memory
        self.provider = provider

    def narrate(self, events: list[JobEvent], rule_findings: list[WatcherObservation]) -> list[WatcherObservation]:
        """P1-WATCHER-002: a model pass over the RESIDUE only.

        Its findings are `detection_method="model"`, capped at confidence
        0.5 and severity warning, stored as `narration` - never as
        `observation` - and dropped if they cite an event a rule already
        explains. A model therefore cannot overwrite, restate or outrank a
        measured fact; it can only add a suggestion beside it. Without a
        provider, or with nothing residual, no model is called."""
        residue = residual_events(events, rule_findings)
        if self.provider is None or not residue:
            return []
        answer = self.provider.complete_json(_narration_prompt(residue), NARRATION_SCHEMA, "watcher.narrate")
        residue_ids = {e.event_id for e in residue}
        by_id = {e.event_id: e for e in events}
        out: list[WatcherObservation] = []
        for item in answer.get("anomalies", []) or []:
            ids = sorted({int(i) for i in item.get("event_ids", []) if int(i) in residue_ids})
            if not ids:
                continue                                   # cites nothing it was shown, or only covered events
            severity = item.get("severity") if item.get("severity") in MODEL_SEVERITIES else "warning"
            try:
                o = WatcherObservation(
                    observation_id=stable_id("obsm", self.memory.project_id, *ids),
                    project_id=self.memory.project_id, job_id=by_id[ids[0]].job_id, stage=by_id[ids[0]].stage,
                    event_type=by_id[ids[0]].event_type,
                    entity_ids=sorted({i for n in ids for i in by_id[n].entity_ids}),
                    anomaly_type="unexpected_output", detector="model_narration",
                    observed={"summary": str(item.get("summary", ""))[:600], "event_ids": ids},
                    expected={"no_unexplained_warnings": True}, severity=severity,
                    confidence=MODEL_MAX_CONFIDENCE, detection_method="model",
                    recommended_check=str(item.get("recommended_check", "")),
                    watcher_version=WATCHER_VERSION, source_event_id=ids[0])
            except ValueError:
                continue                                   # an "action" dressed as a check is not accepted
            out.append(o)
            self.memory.append("narration", o.model_dump(mode="json"), key=o.observation_id, stage=o.stage,
                               job_id=o.job_id, entity_ids=o.entity_ids)
        return out

    def observe(self, events: list[JobEvent], *, now: Optional[datetime] = None,
                project_root: Optional[Path] = None) -> list[WatcherObservation]:
        """Rule and statistic findings. Zero model calls."""
        ctx = _Context(self.memory.project_id, events, self.memory, now or datetime.now(timezone.utc),
                       project_root)
        found: list[WatcherObservation] = []
        for detector in RULE_DETECTORS:
            try:
                found += detector(ctx)
            except Exception:                              # noqa: BLE001 - one bad detector is not all
                log.exception("watcher detector %s failed", detector.__name__)
        #: findings recorded for the first time on this pass - what the
        #: Orchestrator may act on, so an old finding cannot re-trigger it
        self.new: list[WatcherObservation] = []
        for o in found:
            if self.memory.append("observation", o.model_dump(mode="json"), key=o.observation_id, stage=o.stage,
                                  job_id=o.job_id, entity_ids=o.entity_ids, evidence_refs=o.evidence_refs) is not None:
                self.new.append(o)
        return found


def watch_project(project_id: str, *, now: Optional[datetime] = None,
                  new_only: bool = False) -> list[WatcherObservation]:
    """Run the Watcher over one project's stream. Never raises; returns [] on
    any failure of its own (advisory - §21.6). `new_only`: just the findings
    first recorded on this pass (what the runner hands the Orchestrator)."""
    if not get_settings().supervisor_enabled:
        return []
    memory = None
    try:
        from ..jobs.store import get_job_store
        from ..projects.layout import project_dir

        from .providers import RoleProviderError, get_role_provider, role_config

        events = get_job_store().list_events(project_id, limit=100_000)
        memory = WatcherMemoryStore(project_id, agent_version=WATCHER_VERSION)
        provider = get_role_provider("watcher") if role_config("watcher").enabled else None
        watcher = Watcher(memory, provider=provider)
        found = watcher.observe(events, now=now, project_root=project_dir(project_id))
        fresh = list(watcher.new)
        if provider is not None:
            try:
                narrated = watcher.narrate(events, found)
                found += narrated
                fresh += narrated
            except RoleProviderError as exc:
                log.warning("watcher narration unavailable (%s); rule findings stand", exc)
        return fresh if new_only else found
    except Exception:                                      # noqa: BLE001
        log.exception("watcher failed for %s; pipeline unaffected", project_id)
        return []
    finally:
        if memory is not None:
            memory.close()


__all__ = ["Watcher", "watch_project", "RULE_DETECTORS", "WATCHER_VERSION", "EXPECTED_OUTPUT"]

"""The Validator — "Is it correct?" (design.md §21.2, §32.3; P1-VALIDATOR-002).

Verifies; returns evidence; never writes a scene. It does NOT re-check
geometry: layers 1-7 already did, deterministically, and the Validator is
handed their RESULTS (`ValidatorInputs`), never a `Scene` to re-derive. It
adjudicates what those layers cannot: appearance and design-intent adherence,
judged by a model it is shown renders from.

A Validator that cannot run says so. Its provider must be built with
`allow_fallback=False` and temperature 0 - the constructor refuses anything
else - and every path on which the model is absent, failed, unconvinced or
unsupported by evidence ends in REVIEW_REQUIRED. There is no path from a
model failure to PASS.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ..spatial.failures import FailureCategory as FC
from .classify import TERMINAL_CATEGORY
from .contracts import AffectedEntity, ValidationResult, stable_id
from .memory import ValidatorMemoryStore, as_untrusted_data, require_store
from .providers import RoleProvider, RoleProviderError

log = logging.getLogger("aether.supervisor.validator")

VALIDATOR_VERSION = "validator@1.0"
#: Below this a model's PASS is not a pass; it is a human's call.
MIN_PASS_CONFIDENCE = 0.7

APPEARANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "FAIL", "WARNING"]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "issue_type": {"type": "string"},
                "expected": {"type": "string"},
                "observed": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["issue_type", "expected", "observed", "evidence_refs"],
        }},
    },
    "required": ["status", "confidence", "rationale", "issues"],
}


class ValidatorInputs(BaseModel):
    """What the Validator is given: REPORT RESULTS and references. There is
    deliberately no field that can hold a Scene, a position or a polygon -
    the deterministic layers own geometry, and the Validator cannot re-derive
    what it is never handed."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    scene_id: str = ""
    scene_version: int = 0
    #: `planning/spatial_check.json` as written: repair summary, intent
    #: evaluation counts, consistency findings.
    spatial_check: Optional[dict[str, Any]] = None
    #: `blender/validation_report.json` as written.
    build_report: Optional[dict[str, Any]] = None
    #: `planning/visual_intent_fidelity.json` as written.
    visual_fidelity: Optional[dict[str, Any]] = None
    #: `planning/render_verification.json` as written - the render verifier's
    #: own VerificationEvidence (P1-VALIDATOR-001), a report, not geometry.
    render_verification: Optional[dict[str, Any]] = None
    #: Project-relative render paths the model will be shown.
    renders: list[str] = []
    #: The brief's design intents, as the model should judge them.
    design_intents: list[dict[str, Any]] = []
    #: Where each input came from, for evidence refs.
    refs: dict[str, str] = {}


class Validator:
    def __init__(self, memory: ValidatorMemoryStore, provider: Optional[RoleProvider] = None,
                 project_root: Optional[Path] = None):
        require_store(memory, ValidatorMemoryStore)
        if provider is not None:
            if provider.config.allow_fallback:
                raise ValueError("the Validator's provider must have allow_fallback=False: "
                                 "a fallback verdict is fabricated evidence")
            if provider.config.temperature != 0.0:
                raise ValueError("the Validator runs at temperature 0")
        self.memory = memory
        self.provider = provider
        self.project_root = project_root

    # ── public ────────────────────────────────────────────────────────────
    def validate(self, inputs: ValidatorInputs) -> list[ValidationResult]:
        if not isinstance(inputs, ValidatorInputs):
            raise TypeError("the Validator takes ValidatorInputs (report results), never a Scene")
        results = self._deterministic(inputs) + [self._appearance(inputs)]
        for r in results:
            self.memory.append("verdict", r.model_dump(mode="json"), key=r.validation_id,
                               entity_ids=[e.id for e in r.affected_entities], evidence_refs=r.evidence)
        return results

    # ── layers 1-7: consume their results, never recompute them ───────────
    def _result(self, inputs: ValidatorInputs, **kw) -> ValidationResult:
        return ValidationResult(
            validation_id=stable_id("val", inputs.project_id, inputs.scene_id, inputs.scene_version,
                                    kw["issue_type"], kw.get("status")),
            project_id=inputs.project_id, scene_id=inputs.scene_id, scene_version=inputs.scene_version,
            validator_version=VALIDATOR_VERSION, **kw)

    def _deterministic(self, inputs: ValidatorInputs) -> list[ValidationResult]:
        out: list[ValidationResult] = []
        sc_ref = inputs.refs.get("spatial_check", "planning/spatial_check.json")
        if inputs.spatial_check is None:
            out.append(self._result(inputs, status="REVIEW_REQUIRED", severity="warning",
                                    issue_type="spatial_report_missing", confidence=1.0,
                                    recommended_action="human_review", determinism="deterministic",
                                    rationale="no spatial check report: layers 1-7 did not report, so "
                                              "nothing about geometry can be vouched for"))
        else:
            repair = inputs.spatial_check.get("repair", {}) or {}
            hard = int(repair.get("hard_after", 0) or 0)
            state = str(repair.get("terminal_state", ""))
            if hard > 0:
                mapped = TERMINAL_CATEGORY.get(state) or (FC.SOLVER_FAILURE, "architecture")
                action = {"PERCEPTION_FAILURE": "re_read", "HARDWARE_FAILURE": "retry"}.get(
                    mapped[0].name, "re_solve")
                out.append(self._result(
                    inputs, status="FAIL", severity="error", issue_type="spatial_hard_violations",
                    failure_category=mapped[0], observed={"hard_after": hard, "terminal_state": state},
                    expected={"hard_after": 0}, evidence=[sc_ref], confidence=1.0,
                    recommended_action=action, determinism="deterministic",
                    rationale=f"the committed scene still carries {hard} hard violation(s) after repair ({state})"))
            missing = list(repair.get("missing_objects") or [])
            if missing:
                out.append(self._result(
                    inputs, status="FAIL", severity="error", issue_type="objects_missing",
                    failure_category=FC.VALIDATION_FAILURE,
                    affected_entities=[AffectedEntity(kind="scene_object", id=i) for i in missing[:50]],
                    observed={"missing": missing[:50]}, expected={"missing": []}, evidence=[sc_ref],
                    confidence=1.0, recommended_action="human_review", determinism="deterministic",
                    rationale=f"{len(missing)} piece(s) the plan committed are no longer in the scene"))
            intent = inputs.spatial_check.get("intent", {}) or {}
            violated = int(intent.get("violated", 0) or 0)
            if violated:
                out.append(self._result(
                    inputs, status="WARNING", severity="warning", issue_type="placement_intent_violated",
                    observed={"violated": violated, "satisfied": int(intent.get("satisfied", 0) or 0)},
                    expected={"violated": 0}, evidence=[sc_ref], confidence=1.0,
                    recommended_action="human_review", determinism="deterministic",
                    rationale=f"{violated} planned relationship(s) were not met by the committed scene"))
        out += self._render_verification(inputs)
        if inputs.build_report is not None and not inputs.build_report.get("ok", False):
            ref = inputs.refs.get("build_report", "blender/validation_report.json")
            errors = inputs.build_report.get("errors", [])
            no_report = errors == ["no report"]
            out.append(self._result(
                inputs, status="FAIL", severity="error",
                issue_type="build_report_missing" if no_report else "build_errors",
                failure_category=FC.VALIDATION_FAILURE if no_report else FC.BLENDER_EXECUTION_FAILURE,
                observed={"errors": errors[:20]}, expected={"ok": True}, evidence=[ref], confidence=1.0,
                recommended_action="human_review" if no_report else "retry", determinism="deterministic",
                rationale="the Blender build reported errors" if not no_report
                else "the build produced no validation report; its checks did not run"))
        return out

    def _render_verification(self, inputs: ValidatorInputs) -> list[ValidationResult]:
        """Layer 7, consumed as the render verifier reported it (task.md §31
        rows 5 and 12). Two findings escalate:

        - the render no longer matches the committed scene (an object removed
          or added after the render was taken): VALIDATION_FAILURE, a person
          decides - the picture being judged is not the design any more;
        - a piece's built size is beyond ±25% of what the plan asked for:
          ASSET_FAILURE, the mesh is wrong - regenerate.

        Visibility is deliberately NOT escalated: four corner cameras do not
        see every piece of a correct room (measured 69.6% coverage on one), so
        "not seen" is evidence for a person reading the report, not a failure.
        """
        ev = inputs.render_verification
        if not ev:
            return []
        ref = inputs.refs.get("render_verification", "planning/render_verification.json")
        out: list[ValidationResult] = []
        if (ev.get("scene_checks") or {}).get("render_matches_committed_scene") == "fail":
            drifted = list((ev.get("summary") or {}).get("drifted_object_ids") or [])
            out.append(self._result(
                inputs, status="FAIL", severity="error", issue_type="render_mismatch",
                failure_category=FC.VALIDATION_FAILURE,
                affected_entities=[AffectedEntity(kind="scene_object", id=i) for i in drifted[:50]],
                observed={"changed_since_render": drifted[:50]}, expected={"changed_since_render": []},
                evidence=[ref], confidence=1.0, recommended_action="human_review", determinism="deterministic",
                rationale=f"{len(drifted)} piece(s) changed after the render was taken, so the render no longer "
                          "shows the design"))
        wrong_size = [o.get("scene_object_id") for o in ev.get("per_object") or []
                      if (o.get("checks") or {}).get("scale") == "fail" and o.get("scene_object_id")]
        if wrong_size:
            out.append(self._result(
                inputs, status="FAIL", severity="error", issue_type="asset_dimensions",
                failure_category=FC.ASSET_FAILURE,
                affected_entities=[AffectedEntity(kind="scene_object", id=i) for i in wrong_size[:50]],
                observed={"beyond_tolerance": wrong_size[:50]}, expected={"beyond_tolerance": []},
                evidence=[ref], confidence=1.0, recommended_action="regenerate_asset", determinism="deterministic",
                rationale=f"{len(wrong_size)} piece(s) came out of the build more than 25% off the size the plan "
                          "asked for"))
        return out

    # ── appearance + design intent: the model's job, and only this ───────
    def _review(self, inputs: ValidatorInputs, why: str, *, unverified: bool = False,
                **observed) -> ValidationResult:
        # `appearance_unverified`: nothing could be judged - no model is
        # configured, or nothing was rendered. A deployment state, reported
        # honestly, not a defect for the Orchestrator to escalate. Every other
        # REVIEW_REQUIRED here means a model ran and could not vouch.
        return self._result(inputs, status="REVIEW_REQUIRED", severity="warning",
                            issue_type="appearance_unverified" if unverified else "appearance",
                            observed=observed, confidence=0.0, recommended_action="human_review",
                            determinism="model_assisted", rationale=why)

    def _appearance(self, inputs: ValidatorInputs) -> ValidationResult:
        if self.provider is None or not self.provider.config.enabled:
            return self._review(inputs, "no Validator model is configured; appearance cannot be vouched for",
                                unverified=True)
        renders = [r for r in inputs.renders
                   if self.project_root is not None and (self.project_root / r).is_file()]
        if not renders:
            return self._review(inputs, "nothing rendered to judge", unverified=True,
                                renders_supplied=len(inputs.renders))
        prompt = ("Judge whether the rendered room matches the client's stated design intent and looks like a "
                  "coherent, finished interior. Geometry and placement were already verified by deterministic "
                  "checks - do not re-judge positions. Every FAIL or WARNING issue must cite evidence_refs "
                  f"chosen ONLY from: {renders}. Report PASS only if you are confident.\n\n"
                  + as_untrusted_data({"design_intents": inputs.design_intents,
                                       "visual_fidelity": (inputs.visual_fidelity or {}).get("metrics", {}),
                                       "renders": renders}))
        try:
            answer = self.provider.complete_json(prompt, APPEARANCE_SCHEMA, "validator.appearance",
                                                 images=[self.project_root / r for r in renders])
        except RoleProviderError as exc:
            return self._review(inputs, f"the Validator model could not run: {exc}")
        if not isinstance(answer, dict) or answer.get("_fallback"):
            return self._review(inputs, "the Validator model returned no verdict")
        return self._verdict(inputs, answer, set(renders))

    def _verdict(self, inputs: ValidatorInputs, answer: dict, allowed_refs: set[str]) -> ValidationResult:
        status = answer.get("status")
        try:
            confidence = max(0.0, min(1.0, float(answer.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        issues = answer.get("issues") or []
        cited = sorted({r for i in issues for r in (i.get("evidence_refs") or []) if r in allowed_refs})
        rationale = str(answer.get("rationale", ""))[:1000]
        if status == "PASS":
            if confidence < MIN_PASS_CONFIDENCE or issues:
                return self._review(inputs, f"the model's PASS is not convincing (confidence {confidence:.2f}, "
                                            f"{len(issues)} issue(s) listed)", model_status=status)
            return self._result(inputs, status="PASS", severity="info", issue_type="appearance",
                                confidence=confidence, recommended_action="continue",
                                determinism="model_assisted", evidence=sorted(allowed_refs),
                                rationale=rationale or "appearance consistent with intent")
        if status in ("FAIL", "WARNING"):
            if not cited:
                return self._review(inputs, f"the model said {status} without citing a render it was shown",
                                    model_status=status)
            return self._result(
                inputs, status=status, severity="error" if status == "FAIL" else "warning",
                issue_type="appearance",
                failure_category=FC.ASSET_FAILURE if status == "FAIL" else None,
                affected_entities=[AffectedEntity(kind="report", id=r) for r in cited],
                observed={"issues": [{k: str(i.get(k, ""))[:300] for k in ("issue_type", "observed")}
                                     for i in issues][:10]},
                expected={"issues": [str(i.get("expected", ""))[:300] for i in issues][:10]},
                evidence=cited, confidence=confidence,
                recommended_action="human_review", determinism="model_assisted", rationale=rationale)
        return self._review(inputs, f"the model returned an unrecognised status {status!r}")


def inputs_for_project(project_id: str) -> tuple[ValidatorInputs, Path]:
    """Read a project's reports from disk into ValidatorInputs."""
    import json

    from ..projects.layout import project_dir

    root = project_dir(project_id)

    def load(rel: str) -> Optional[dict]:
        p = root / rel
        try:
            return json.loads(p.read_text("utf-8")) if p.is_file() else None
        except (OSError, ValueError):
            return None

    spec = load("planning/scene_spec.json") or {}
    intents = load("planning/design_intent.json") or {}
    renders = sorted(str(p.relative_to(root)).replace("\\", "/")
                     for pattern in ("previews/*.png", "renders/*.png") for p in root.glob(pattern))
    report = load("blender/validation_report.json")
    if report is None and (root / "blender" / "scene.blend").exists():
        report = {"ok": False, "errors": ["no report"]}     # a build ran and its checks did not
    spatial = load("planning/spatial_check.json")
    # The version the deterministic layer actually examined wins over the
    # spec file: a scene changed after planning is checked at ITS version.
    checked = int(((spatial or {}).get("repair") or {}).get("scene_version") or 0)
    return ValidatorInputs(
        project_id=project_id, scene_id=str(spec.get("scene_id", "")),
        scene_version=max(checked, int(spec.get("version", 0) or 0)),
        spatial_check=spatial,
        build_report=report,
        visual_fidelity=load("planning/visual_intent_fidelity.json"),
        render_verification=load("planning/render_verification.json"),
        renders=renders, design_intents=list(intents.get("intents", []))[:20],
        refs={"spatial_check": "planning/spatial_check.json", "build_report": "blender/validation_report.json",
              "render_verification": "planning/render_verification.json"},
    ), root


def validate_project(project_id: str) -> list[ValidationResult]:
    """Advisory, never raises (design.md §21.6)."""
    from ..core.config import get_settings

    if not get_settings().supervisor_enabled:
        return []
    memory = None
    try:
        from .providers import get_role_provider, role_config

        inputs, root = inputs_for_project(project_id)
        memory = ValidatorMemoryStore(project_id, agent_version=VALIDATOR_VERSION)
        provider = get_role_provider("validator") if role_config("validator").enabled else None
        return Validator(memory, provider=provider, project_root=root).validate(inputs)
    except Exception:                                      # noqa: BLE001
        log.exception("validator failed for %s; pipeline unaffected", project_id)
        return []
    finally:
        if memory is not None:
            memory.close()


__all__ = ["Validator", "ValidatorInputs", "validate_project", "inputs_for_project", "VALIDATOR_VERSION",
           "APPEARANCE_SCHEMA"]

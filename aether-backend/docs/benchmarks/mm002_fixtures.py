"""P1-MM-002: labelled known-good / known-bad states for all three Supervisor
roles' model calls - Watcher narration, Orchestrator decide, Validator
appearance.

Ground truth here is not measured from the world - it is *authored*, the same
way a unit test's expected value is authored - but each case is built so the
correct answer is checkable from the case itself without judgment calls,
exactly the property task.md asks a labelled set to have (known-good AND
known-bad, not only good).

The Validator's model call (`_appearance`) judges RENDERS, so only a
vision-capable model can take those cases; the harness asks Ollama for each
model's capabilities and runs appearance cases only on the ones that can see.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.jobs.schema import JobEvent
from app.spatial.failures import FailureCategory as FC
from app.supervisor.contracts import AffectedEntity, ValidationResult, WatcherObservation


# ── Watcher narration: does the residue contain a real cross-event pattern? ──

@dataclass
class NarrationCase:
    case_id: str
    label: Literal["pattern", "no_pattern"]
    residue: list[JobEvent]
    #: For a "pattern" case: event_ids the correct answer must cite at least
    #: one of (the ones that carry the pattern, not incidental others).
    pattern_event_ids: set[int] = field(default_factory=set)


def _ev(event_id: int, stage: str, event_type: str, message: str, entity_ids: list[str],
        severity: str = "warning", status: str = "warning") -> JobEvent:
    return JobEvent(event_id=event_id, project_id="proj_bench", job_id=f"job_{event_id}", stage=stage,
                    status=status, message=message, ts="2026-09-26T00:00:00Z", event_type=event_type,
                    severity=severity, producer="bench", entity_ids=entity_ids)


NARRATION_CASES: list[NarrationCase] = [
    # ── known-bad: a real pattern spans several events ──────────────────
    NarrationCase("pat_01_same_asset_three_stages", "pattern", [
        _ev(101, "generate_elements", "asset.slow", "texture fetch for obj_sofa_12 took 41s, above the 20s budget",
            ["obj_sofa_12"]),
        _ev(102, "build", "asset.slow", "Blender import of obj_sofa_12 stalled for 38s waiting on disk",
            ["obj_sofa_12"]),
        _ev(103, "render_viewpoints", "asset.slow", "camera pass touching obj_sofa_12 ran 44s over its usual time",
            ["obj_sofa_12"]),
        _ev(104, "scene_plan", "asset.committed", "unrelated: bedside_table_03 committed on schedule",
            ["obj_table_03"], severity="info", status="ok"),
    ], pattern_event_ids={101, 102, 103}),
    NarrationCase("pat_02_repeated_network_reset", "pattern", [
        _ev(201, "generate_elements", "provider.retry", "Meshy request for obj_chair_04 reset mid-transfer, retried",
            ["obj_chair_04"]),
        _ev(202, "generate_elements", "provider.retry", "Meshy request for obj_lamp_07 reset mid-transfer, retried",
            ["obj_lamp_07"]),
        _ev(203, "generate_elements", "provider.retry", "Meshy request for obj_rug_01 reset mid-transfer, retried",
            ["obj_rug_01"]),
        _ev(204, "scene_plan", "scene.committed", "unrelated informational note about room naming",
            [], severity="info", status="ok"),
    ], pattern_event_ids={201, 202, 203}),
    NarrationCase("pat_03_one_room_keeps_failing_repair", "pattern", [
        _ev(301, "build", "repair.round", "living_room repair round 1: 2 hard violations remained",
            ["room_living"]),
        _ev(302, "build", "repair.round", "living_room repair round 2: 2 hard violations remained (same pair)",
            ["room_living"]),
        _ev(303, "build", "repair.round", "living_room repair round 3: 2 hard violations remained (same pair)",
            ["room_living"]),
    ], pattern_event_ids={301, 302, 303}),
    NarrationCase("pat_04_one_client_photo_reread_thrice", "pattern", [
        _ev(401, "scene_reading", "reader.uncertain", "reference photo living_01.jpg read with low confidence "
            "for the sofa region", ["in_living_01"]),
        _ev(402, "scene_reading", "reader.uncertain", "reference photo living_01.jpg re-read, still low confidence "
            "for the sofa region", ["in_living_01"]),
        _ev(403, "scene_reading", "reader.uncertain", "reference photo living_01.jpg re-read a third time, sofa "
            "region confidence unchanged", ["in_living_01"]),
        _ev(404, "generate_elements", "asset.slow", "unrelated slow fetch for a curtains texture", ["obj_curtains_01"]),
    ], pattern_event_ids={401, 402, 403}),
    # ── known-good: independently odd, no cross-cutting pattern ─────────
    NarrationCase("nop_01_four_unrelated_one_offs", "no_pattern", [
        _ev(501, "generate_elements", "asset.slow", "texture fetch for obj_rug_09 took 24s, slightly over budget",
            ["obj_rug_09"]),
        _ev(502, "build", "material.fallback", "no registry material for descriptor 'burnished' on obj_lamp_02, "
            "used nearest match", ["obj_lamp_02"]),
        _ev(503, "render_viewpoints", "camera.adjusted", "camera 3 nudged 4cm to clear a doorway", ["room_hall"]),
        _ev(504, "scene_plan", "intent.soft_miss", "one soft placement preference ('near window') was not met "
            "for obj_chair_11", ["obj_chair_11"], severity="info", status="ok"),
    ]),
    NarrationCase("nop_02_single_isolated_warning", "no_pattern", [
        _ev(601, "generate_elements", "asset.slow", "texture fetch for obj_ottoman_05 took 22s, slightly over budget",
            ["obj_ottoman_05"]),
    ]),
    NarrationCase("nop_03_four_different_rooms_different_causes", "no_pattern", [
        _ev(701, "build", "material.fallback", "fallback material for obj_shelf_01 in the study", ["obj_shelf_01"]),
        _ev(702, "render_viewpoints", "camera.adjusted", "camera 1 nudged in the bedroom", ["room_bed"]),
        _ev(703, "scene_plan", "intent.soft_miss", "soft placement miss in the kitchen for obj_stool_02",
            ["obj_stool_02"], severity="info", status="ok"),
        _ev(704, "generate_elements", "asset.slow", "slow fetch in the bathroom for obj_mirror_01", ["obj_mirror_01"]),
    ]),
    NarrationCase("nop_04_two_events_same_stage_different_entities", "no_pattern", [
        _ev(801, "build", "material.fallback", "fallback material for obj_vase_03", ["obj_vase_03"]),
        _ev(802, "build", "material.fallback", "fallback material for obj_frame_02, unrelated descriptor",
            ["obj_frame_02"]),
    ]),
]


# ── Orchestrator decide: an UNKNOWN-category verdict → the right next step ──

@dataclass
class DecideCase:
    case_id: str
    label: Literal["RETRY", "RE_SOLVE", "RE_READ", "ESCALATE"]
    worst: ValidationResult
    observations: list[WatcherObservation] = field(default_factory=list)


def _verdict(vid: str, issue_type: str, rationale: str, *, status: str = "FAIL",
            determinism: str = "deterministic", recommended_action: str = "human_review") -> ValidationResult:
    """A verdict whose category the deterministic policy table has no row for -
    `failure_category=FC.UNKNOWN`, exactly what makes `_ask_model` fire (it
    only runs `if category is FC.UNKNOWN`). A FAIL must name a category
    (the schema itself enforces this); REVIEW_REQUIRED does not, and
    `_ask_model`'s own caller maps a None category there to UNKNOWN too."""
    return ValidationResult(validation_id=vid, project_id="proj_bench", status=status, severity="error",
                            issue_type=issue_type, affected_entities=[AffectedEntity(kind="scene_object", id="obj_x")],
                            failure_category=FC.UNKNOWN if status == "FAIL" else None,
                            evidence=["planning/spatial_check.json"], confidence=0.8,
                            recommended_action=recommended_action, determinism=determinism, rationale=rationale,
                            validator_version="bench@1.0")


DECIDE_CASES: list[DecideCase] = [
    # ── RETRY: a transient, infrastructure-shaped failure ───────────────
    DecideCase("retry_01_worker_process_killed", "RETRY", _verdict(
        "v_retry_1", "build_errors",
        "the Blender worker process was killed by the OS (out-of-memory reaper) partway through the render; "
        "no geometry or design error was reported, the process simply did not finish")),
    DecideCase("retry_02_provider_connection_reset", "RETRY", _verdict(
        "v_retry_2", "build_errors",
        "the render job's connection to the local render queue was reset mid-request (network-level RST); "
        "the same job had succeeded on an earlier, identical attempt")),
    DecideCase("retry_03_timeout_no_content_issue", "RETRY", _verdict(
        "v_retry_3", "build_errors",
        "the build step exceeded its 1800s timeout while idle, waiting on a lock file from a previous run that "
        "had not been cleaned up; nothing about the scene itself was reported as wrong")),
    DecideCase("retry_04_disk_io_error", "RETRY", _verdict(
        "v_retry_4", "build_errors",
        "a transient disk I/O error (input/output error, errno 5) interrupted writing the .blend file; "
        "the file system reported the volume as healthy afterward")),
    # ── RE_SOLVE: an uncategorized geometric/placement problem ──────────
    DecideCase("resolve_01_unclassified_overlap", "RE_SOLVE", _verdict(
        "v_rs_1", "spatial_hard_violations",
        "two committed objects overlap by 4cm in a way the repair engine's nine violation classes do not name; "
        "positions exist that would clear it, this is a coordinate problem, not a missing or wrong asset")),
    DecideCase("resolve_02_orphaned_clearance_conflict", "RE_SOLVE", _verdict(
        "v_rs_2", "spatial_hard_violations",
        "a walkway clearance conflict remains after 2 repair rounds between two objects whose relationship "
        "the clearance engine had not modeled; geometry and positions are both known and valid, they are simply "
        "arranged wrong")),
    DecideCase("resolve_03_unhandled_rotation_conflict", "RE_SOLVE", _verdict(
        "v_rs_3", "spatial_hard_violations",
        "an object's rotation satisfies its own placement rule but now collides with a wall after a later "
        "object was added; this is a coordinate/rotation conflict the solver has not been asked to resolve, "
        "not a wrong mesh or a misread photo")),
    DecideCase("resolve_04_frame_graph_gap", "RE_SOLVE", _verdict(
        "v_rs_4", "spatial_hard_violations",
        "the object's parent surface moved during a later edit and the child's position was never re-derived, "
        "leaving it floating; the fix is purely a coordinate re-derivation, no asset or photo is at fault")),
    # ── RE_READ: the scene reading disagrees with the source photo ──────
    DecideCase("reread_01_wrong_region_cropped", "RE_READ", _verdict(
        "v_rr_1", "appearance",
        "the element described as 'the armchair by the window' does not correspond to anything in the "
        "cropped region of the client's living-room photo; the crop appears to have caught the wrong furniture "
        "entirely",
        determinism="model_assisted", status="REVIEW_REQUIRED", recommended_action="human_review")),
    DecideCase("reread_02_photo_mismatch_material", "RE_READ", _verdict(
        "v_rr_2", "appearance",
        "the client's reference photo shows a fabric sofa but the scene reading recorded it as leather with high "
        "confidence; re-examining the same photo region is the only way to tell which reading is right",
        determinism="model_assisted", status="REVIEW_REQUIRED", recommended_action="human_review")),
    DecideCase("reread_03_dimension_photo_conflict", "RE_READ", _verdict(
        "v_rr_3", "appearance",
        "the reading recorded the dining table as 2.4m long, but the source photo's own visible doorway "
        "reference makes that implausible; the photo itself needs to be re-read with the doorway as scale",
        determinism="model_assisted", status="REVIEW_REQUIRED", recommended_action="human_review")),
    DecideCase("reread_04_count_mismatch_photo", "RE_READ", _verdict(
        "v_rr_4", "appearance",
        "three dining chairs were committed but the client's own photo of the dining area clearly shows four "
        "chairs around the table; the photo was misread for count, not the scene miscommitted",
        determinism="model_assisted", status="REVIEW_REQUIRED", recommended_action="human_review")),
    # ── ESCALATE: repeated failure with no available automatic fix ──────
    DecideCase("escalate_01_third_round_same_failure", "ESCALATE", _verdict(
        "v_esc_1", "spatial_hard_violations",
        "this is the third consecutive repair round to end with the same two hard violations unresolved; "
        "the automatic repair engine has exhausted its strategies for this pair"),
        observations=[WatcherObservation(observation_id="obsm_esc1", project_id="proj_bench",
                                         anomaly_type="state_regression", detector="rule",
                                         severity="error", confidence=1.0, detection_method="rule",
                                         recommended_check="Check whether round 3's violations match rounds 1-2",
                                         watcher_version="bench@1.0")]),
    DecideCase("escalate_02_conflicting_reports_no_path", "ESCALATE", _verdict(
        "v_esc_2", "build_errors",
        "the deterministic build report and the render verifier disagree about whether the object was placed, "
        "and there is no further automatic check that could adjudicate between them")),
    DecideCase("escalate_03_budget_and_repeated_failure", "ESCALATE", _verdict(
        "v_esc_3", "spatial_hard_violations",
        "this project has already spent 3 of its 3 allotted repair rounds and 2 of its 2 allotted regenerations "
        "for this object, and the violation remains; no automatic option is left to try"),
        observations=[WatcherObservation(observation_id="obsm_esc3", project_id="proj_bench",
                                         anomaly_type="cost_outlier", detector="rule", severity="critical",
                                         confidence=1.0, detection_method="rule",
                                         recommended_check="Check whether spend is above the project cap",
                                         watcher_version="bench@1.0")]),
    DecideCase("escalate_04_no_plausible_automatic_step", "ESCALATE", _verdict(
        "v_esc_4", "appearance",
        "the client's brief and the two reference photos describe mutually exclusive styles for the same room "
        "(mid-century modern vs. maximalist eclectic) and no automatic step can decide which one the design "
        "should follow"),
        observations=[]),
]


# ── Validator appearance: does the render match the stated design intent? ──
#
# Two real renders from the production build (tests.test_blender_build.
# _compiled_scene through build_scene.py, 2026-09-27): the dining area as
# compiled, and the same scene with every object removed. Each label is a
# fact about what is VISIBLE in the picture - furniture present or not, wall
# colour, room type - never a matter of taste. Mood ("evening" vs
# "daylight") was considered and dropped: the two moods' renders differ too
# subtly for an unambiguous label.

RENDER_ROOT_REL = ("version 4", "evidence", "P1-MM-002")
FULL = "renders/full_dining_room.png"      # table, 3 chairs, curtains, rug; white walls, beige floor
EMPTY = "renders/empty_room.png"           # bare white walls, beige floor, two doorways, no furniture


@dataclass
class AppearanceCase:
    case_id: str
    label: Literal["PASS", "FAIL"]
    render: str
    intent: str


APPEARANCE_CASES: list[AppearanceCase] = [
    AppearanceCase("pass_01_dining_has_table_and_chairs", "PASS", FULL,
                   "A dining area with a table and chairs."),
    AppearanceCase("pass_02_light_neutral_palette", "PASS", FULL,
                   "A light, neutral palette: white walls and soft beige tones."),
    AppearanceCase("pass_03_floor_length_curtains", "PASS", FULL,
                   "Floor-length curtains at the windows."),
    AppearanceCase("pass_04_empty_room_asked_for_empty", "PASS", EMPTY,
                   "An empty, unfurnished room with white walls, ready for the client to furnish."),
    AppearanceCase("fail_01_empty_but_dining_asked", "FAIL", EMPTY,
                   "A dining area with a table and chairs."),
    AppearanceCase("fail_02_empty_but_sofa_asked", "FAIL", EMPTY,
                   "A furnished living room centred on a large sofa."),
    AppearanceCase("fail_03_red_walls_asked", "FAIL", FULL,
                   "Bold, saturated red walls throughout."),
    AppearanceCase("fail_04_bedroom_asked", "FAIL", FULL,
                   "A bedroom centred on a double bed."),
]


ALL_CASE_COUNTS = {"narration": len(NARRATION_CASES), "decide": len(DECIDE_CASES),
                   "appearance": len(APPEARANCE_CASES)}

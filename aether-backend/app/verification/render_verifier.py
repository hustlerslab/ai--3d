"""P1-VALIDATOR-001: promote `research/placement_loop.py`'s render-verification
loop to production (design.md §16, `docs/production/research_to_production.md`
migration discipline).

WHAT MOVED AND WHAT DIDN'T. `research/placement_loop.py` already measured
coverage 100%, placement 91% @1.0m, orientation 100%, composite 98% (N=1) by
rendering four room-corner viewpoints and ray-casting visibility
(`blender/scripts/check_visibility.py`) rather than asking a vision model what
it sees - a generative reader scored the SAME unchanged scene 0.556 / 0.778 /
0.556 / 0.556 across four reads while inventing furniture that was not there
(`check_visibility.py`'s own docstring). This module keeps that method exactly
and gives it a typed, testable, production output contract
(`VerificationEvidence`, design.md §16) instead of a loop's local dict math.
`app/jobs/handlers/verify.py` is the new caller; `render_viewpoints.py` /
`check_visibility.py` themselves are unchanged.

Eleven of the thirteen checks in design.md §16's table are computed here,
deterministically, from signals that already exist elsewhere in the pipeline
(the Blender build's own validation report, `app/spatial/validation.py`,
`app/spatial/clearance_engine.py`, the committed `Scene`, the object plan).
The other two - major materials match, major colours match - need a model
reading the render against `ObjectVisual`; none is wired here (P1-MM-002,
still needing a live model, is what would benchmark which one). Per design.md
§16: "`unknown` is a first-class result. A check that could not run is NOT a
pass." Those two are always reported `unknown`, never invented as a pass.
"""
from __future__ import annotations

import math
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from ..planning import compiler
from ..scene.schema import Scene, new_id
from ..spatial.clearance_engine import circulation_violations, door_swing_violations
from ..spatial.validation import validate_scene

Verdict = Literal["pass", "fail", "unknown"]
Visibility = Literal["visible", "occluded", "never_in_frame", "unknown"]

#: design.md §16's table, in order. The first 11 are deterministic; the last
#: two need a model and are never computed here (see module docstring).
CHECK_NAMES: tuple[str, ...] = (
    "expected_objects_exist",
    "object_count",
    "major_objects_visible",
    "approximate_location",
    "scale",
    "orientation",
    "floating_objects",
    "severe_intersections",
    "room_architecture_preserved",
    "doors_windows_respected",
    "circulation",
    "major_materials_match",
    "major_colours_match",
)
DETERMINISTIC_CHECKS: tuple[str, ...] = CHECK_NAMES[:11]
MODEL_CHECKS: tuple[str, ...] = CHECK_NAMES[11:]

#: Same tolerances research/placement_loop.py measured with.
PLACEMENT_TOLERANCE_M = 1.0
SCALE_TOLERANCE = 0.25
FLOATING_TOLERANCE_M = 0.02
FACING_TOLERANCE_DEG = 1.0


class PerObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_object_id: str
    element_id: Optional[str] = None
    instance_id: Optional[str] = None
    visibility: Visibility
    checks: dict[str, Verdict]


class VerificationEvidence(BaseModel):
    """design.md §16 "Output contract". `scene_checks` is this
    implementation's home for the checks design.md's illustrative `summary`
    didn't have a per-check slot for (severe_intersections,
    room_architecture_preserved, doors_windows_respected, circulation,
    expected_objects_exist, object_count) - scene-scoped, not per-object."""

    model_config = ConfigDict(extra="forbid")

    verification_id: str
    scene_id: str
    scene_version: int
    render_ids: list[str]
    per_object: list[PerObjectEvidence]
    scene_checks: dict[str, Verdict]
    summary: dict[str, Any]
    verifier_version: str = "1.0"
    produced_at: str

    @property
    def ok(self) -> bool:
        """No deterministic check failed. `unknown` is not failure - a check
        that could not run is withheld from judgement, not scored against."""
        if any(v == "fail" for v in self.scene_checks.values()):
            return False
        return not any(
            check in DETERMINISTIC_CHECKS and verdict == "fail"
            for obj in self.per_object
            for check, verdict in obj.checks.items()
        )


def default_viewpoints(scene: Scene) -> list[dict]:
    """Every corner of the largest room, each looking at its centre - the
    same viewpoint choice `research/placement_loop.py` measured with.
    Corners, not the middle: a camera in the centre of a small room sees a
    wall, and every piece should appear in at least one corner shot."""
    from ..blender.manifest import to_blender_xyz
    from ..spatial import geometry as geo

    if not scene.rooms:
        return []
    room = max(scene.rooms, key=lambda r: geo.polygon_area(r.boundary))
    cx, cz = geo.polygon_centroid(room.boundary)
    eye = 1.55
    views = []
    for i, (px, pz) in enumerate(room.boundary):
        ix = px + (0.5 if cx > px else -0.5)
        iz = pz + (0.5 if cz > pz else -0.5)
        views.append({
            "name": f"corner_{i}",
            "position": list(to_blender_xyz((ix, eye, iz))),
            "look_at": list(to_blender_xyz((cx, 1.1, cz))),
        })
    return views


def _expected_objects_and_count(build_report: dict) -> tuple[Verdict, Verdict]:
    errors = build_report.get("errors") or []
    exists = "fail" if any("no geometry" in e for e in errors) else (
        "unknown" if not build_report else "pass"
    )
    count = "fail" if any("placed" in e and " of " in e and "objects" in e for e in errors) else (
        "unknown" if not build_report else "pass"
    )
    return exists, count


def _render_matches_committed_scene(build_report: dict, scene: Scene) -> tuple[Verdict, list[str]]:
    """Scene-level, beyond design.md §16's 13: does the render being verified
    still reflect the scene that is CURRENTLY committed? The 13 checks all
    compare the build's OWN manifest against its OWN output - none of them
    would catch an object removed or replaced by a later patch without a
    rebuild (task.md §31 row 12, "render mismatch (object moved
    post-capture)"). `build_report["objects"]` is Blender's own record of
    what it actually placed at build time; comparing it against the live
    `Scene` catches drift with no rebuild required."""
    built = build_report.get("objects") or []
    built_ids = {o.get("id") for o in built if o.get("id")}
    if not built_ids:
        return "unknown", []
    current_ids = {o.object_id for o in scene.objects}
    drifted = sorted((built_ids - current_ids) | (current_ids - built_ids))
    return ("fail" if drifted else "pass"), drifted


def _room_architecture_preserved(build_report: dict) -> Verdict:
    errors = build_report.get("errors") or []
    if not build_report:
        return "unknown"
    bad = ("no floor mesh", "no ceiling mesh", "pivot outside room")
    return "fail" if any(any(b in e for b in bad) for e in errors) else "pass"


def _scale_verdicts(build_report: dict, object_ids: set[str]) -> dict[str, Verdict]:
    """The build's own bbox-vs-manifest check (±25%, `validate_scene.py`
    Blender-side) reports a per-object NOTE, not a hard error - a piece a
    little off is not a broken build. Verification grades it as a real
    check: flagged objects fail, everything else passes."""
    if not build_report:
        return {oid: "unknown" for oid in object_ids}
    warnings = build_report.get("warnings") or []
    flagged = set()
    for w in warnings:
        oid = w.split(" (", 1)[0]
        if oid in object_ids:
            flagged.add(oid)
    return {oid: ("fail" if oid in flagged else "pass") for oid in object_ids}


def _approximate_location(scene: Scene, object_plan_items: dict[str, dict]) -> dict[str, tuple[Verdict, Optional[float]]]:
    by_room = {r.room_id: r for r in scene.rooms}
    out: dict[str, tuple[Verdict, Optional[float]]] = {}
    for obj in scene.objects:
        item = object_plan_items.get(obj.plan_key or "")
        if not item or not item.get("anchor_m") or item.get("anchor_source") != "read":
            out[obj.object_id] = ("unknown", None)
            continue
        room = by_room.get(obj.room_id)
        if room is None:
            out[obj.object_id] = ("unknown", None)
            continue
        from ..intelligence.schema import ObjectPlanItem

        spot = compiler.anchor_spot(ObjectPlanItem.model_validate(item), room, obj.dimensions[2])
        if spot is None:
            out[obj.object_id] = ("unknown", None)
            continue
        d = math.dist(spot, (obj.position[0], obj.position[2]))
        out[obj.object_id] = ("pass" if d <= PLACEMENT_TOLERANCE_M else "fail", round(d, 3))
    return out


def _orientation(scene: Scene, object_plan_items: dict[str, dict]) -> dict[str, Verdict]:
    out: dict[str, Verdict] = {}
    for obj in scene.objects:
        item = object_plan_items.get(obj.plan_key or "")
        if not item or not item.get("facing_dir") or obj.semantic_type not in compiler.ORIENTED_TYPES:
            out[obj.object_id] = "unknown"
            continue
        want = math.degrees(compiler._rotation_facing(tuple(item["facing_dir"]))) % 360
        got = math.degrees(obj.rotation_y) % 360
        aligned = abs((want - got + 180) % 360 - 180) <= FACING_TOLERANCE_DEG
        out[obj.object_id] = "pass" if aligned else "fail"
    return out


def _floating(scene: Scene) -> dict[str, Verdict]:
    by_room = {r.room_id: r for r in scene.rooms}
    out: dict[str, Verdict] = {}
    for obj in scene.objects:
        if obj.mount != "floor":
            out[obj.object_id] = "unknown"
            continue
        room = by_room.get(obj.room_id)
        floor_height = room.floor_height if room else 0.0
        out[obj.object_id] = "pass" if abs(obj.position[1] - floor_height) <= FLOATING_TOLERANCE_M else "fail"
    return out


def _severe_intersections(scene: Scene) -> tuple[Verdict, set[str]]:
    hard = [v for v in validate_scene(scene) if v.severity == "hard" and v.code in ("COLLIDES_WALL", "COLLIDES_OBJECT")]
    offenders = {v.object_id for v in hard if v.object_id}
    return ("fail" if hard else "pass"), offenders


def _doors_windows(scene: Scene) -> tuple[Verdict, set[str]]:
    blocked_door = [v for v in validate_scene(scene) if v.severity == "hard" and v.code == "BLOCKS_DOOR"]
    swing = door_swing_violations(scene)
    offenders = {v.object_id for v in blocked_door if v.object_id} | {v.target_id for v in swing}
    verdict: Verdict = "fail" if (blocked_door or swing) else "pass"
    return verdict, offenders


def _circulation(scene: Scene, entrance_xz: Optional[tuple[float, float]]) -> Verdict:
    if entrance_xz is None:
        return "unknown"
    hard = [v for v in circulation_violations(scene, entrance_xz) if v.severity == "hard"]
    return "fail" if hard else "pass"


def verify_scene(
    scene: Scene,
    *,
    build_report: dict,
    visibility_detail: list[dict],
    render_ids: list[str],
    object_plan_items: Optional[dict[str, dict]] = None,
    entrance_xz: Optional[tuple[float, float]] = None,
) -> VerificationEvidence:
    """Pure function: every input is already-produced data (the committed
    Scene, the Blender build's validation report, `check_visibility.py`'s
    per-object detail, the object plan). No Blender call, no I/O - the
    `verify` job handler does that and hands the results here."""
    object_plan_items = object_plan_items or {}
    object_ids = {o.object_id for o in scene.objects}

    exists_verdict, count_verdict = _expected_objects_and_count(build_report)
    architecture_verdict = _room_architecture_preserved(build_report)
    scale_verdicts = _scale_verdicts(build_report, object_ids)
    location_verdicts = _approximate_location(scene, object_plan_items)
    orientation_verdicts = _orientation(scene, object_plan_items)
    floating_verdicts = _floating(scene)
    intersections_verdict, intersecting_ids = _severe_intersections(scene)
    doors_verdict, door_offender_ids = _doors_windows(scene)
    circulation_verdict = _circulation(scene, entrance_xz)
    drift_verdict, drifted_ids = _render_matches_committed_scene(build_report, scene)

    visibility_by_id: dict[str, dict] = {d["name"]: d for d in visibility_detail}

    per_object: list[PerObjectEvidence] = []
    for obj in scene.objects:
        vd = visibility_by_id.get(obj.object_id)
        if vd is None:
            visibility: Visibility = "unknown"
            visible_verdict: Verdict = "unknown"
        elif vd.get("visible", 0) > 0:
            visibility, visible_verdict = "visible", "pass"
        elif vd.get("in_frame", 0) > 0:
            visibility, visible_verdict = "occluded", "fail"
        else:
            visibility, visible_verdict = "never_in_frame", "fail"

        loc_verdict, _dist = location_verdicts.get(obj.object_id, ("unknown", None))
        checks: dict[str, Verdict] = {
            "expected_objects_exist": exists_verdict,
            "object_count": count_verdict,
            "major_objects_visible": visible_verdict,
            "approximate_location": loc_verdict,
            "scale": scale_verdicts.get(obj.object_id, "unknown"),
            "orientation": orientation_verdicts.get(obj.object_id, "unknown"),
            "floating_objects": floating_verdicts.get(obj.object_id, "unknown"),
            "severe_intersections": "fail" if obj.object_id in intersecting_ids else "pass",
            "room_architecture_preserved": architecture_verdict,
            "doors_windows_respected": "fail" if obj.object_id in door_offender_ids else "pass",
            "circulation": circulation_verdict,
            "major_materials_match": "unknown",
            "major_colours_match": "unknown",
        }
        per_object.append(PerObjectEvidence(
            scene_object_id=obj.object_id,
            element_id=obj.element_id,
            instance_id=obj.instance_id,
            visibility=visibility,
            checks=checks,
        ))

    scene_checks: dict[str, Verdict] = {
        "expected_objects_exist": exists_verdict,
        "object_count": count_verdict,
        "severe_intersections": intersections_verdict,
        "room_architecture_preserved": architecture_verdict,
        "doors_windows_respected": doors_verdict,
        "circulation": circulation_verdict,
        "render_matches_committed_scene": drift_verdict,
    }

    measured = [d for oid, d in ((o, location_verdicts.get(o)) for o in object_ids) if d and d[1] is not None]
    coverage = (sum(1 for d in visibility_detail if d.get("visible", 0) > 0) / len(visibility_detail)) if visibility_detail else 0.0
    placement_within_tolerance = (sum(1 for _, d in measured if d <= PLACEMENT_TOLERANCE_M) / len(measured)) if measured else None
    oriented = [v for v in orientation_verdicts.values() if v != "unknown"]
    orientation_match = (sum(1 for v in oriented if v == "pass") / len(oriented)) if oriented else None
    asset_bound = (sum(1 for oid in object_ids if scale_verdicts.get(oid) == "pass") / len(object_ids)) if object_ids else None

    summary = {
        "coverage": round(coverage, 3),
        "placement_within_tolerance": round(placement_within_tolerance, 3) if placement_within_tolerance is not None else None,
        "orientation_match": round(orientation_match, 3) if orientation_match is not None else None,
        "asset_bound": round(asset_bound, 3) if asset_bound is not None else None,
        "object_count": len(object_ids),
        "drifted_object_ids": drifted_ids,
    }

    return VerificationEvidence(
        verification_id=new_id("verify"),
        scene_id=scene.scene_id,
        scene_version=scene.version,
        render_ids=render_ids,
        per_object=per_object,
        scene_checks=scene_checks,
        summary=summary,
        produced_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

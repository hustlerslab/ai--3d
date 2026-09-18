"""P4 repair / re-solve loop: DETECT -> CLASSIFY -> LOCALIZE -> GENERATE
VALID REPAIRS -> SCORE -> APPLY -> RE-VALIDATE -> ACCEPT/REJECT ->
RE-SOLVE IF NECESSARY -> ESCALATE ONLY WHEN JUSTIFIED.

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. Extends P1 (`collision_solver.find_valid_nudge`, a real
min-conflicts-heuristic instance - Minton et al. 1992, see
docs/spatial_architecture/repair.md P4.1) and P3 (`scene_optimizer.
solve_backtracking`) rather than rewriting either. Adds one new geometric
primitive (`identify_blocking_object`, a straight-line obstruction proxy for
CIRCULATION failures - repair.md P4.2) and no new dependency.

ESCALATION LADDER (repair.md P4.2, optimization.md's own literature):
  LEVEL 1  local repair       find_valid_nudge on the responsible object
                               (P1's existing lattice - min-conflicts)
  LEVEL 2  direct competitor  find_valid_nudge on the OTHER object in a
                               two-way conflict (conflict-directed
                               backjumping - Prosser 1993: jump to the
                               actual conflict partner, not merely the
                               previous placement)
  LEVEL 3  bounded local      scene_optimizer.solve_backtracking, scoped to
           backtracking       ONLY the objects already implicated (movable
                               set), never the whole scene - P3 measured a
                               whole-scene shared budget starving later
                               objects; this ladder avoids that entirely by
                               construction (local scope, not a shared
                               global one)
  LEVEL 4  broader search     P3's solve_backtracking/solve_beam over every
           (opt-in only)      currently-placed object - NOT invoked by
                               default (`max_level=3`); P3 already measured
                               this costing 30-50x greedy's latency with no
                               guaranteed benefit at real scene sizes
  LEVEL 5  explicit failure   UNREPAIRABLE / UPSTREAM_REQUIRED / ESCALATE /
                               TIMEOUT - never a silently-accepted invalid
                               scene

CIRCULATION IS CHECKED PER-ITERATION, NOT PER-CANDIDATE. P2/P3 both measured
circulation_violations at 0.4-3.5 s/scene - embedding it inside the
candidate-testing inner loop (which may try dozens of lattice offsets) would
be computationally prohibitive, exactly the reasoning optimization.md §3
already gave for excluding it from P3's per-candidate score. `count_hard_fast`
(validate_scene only) gates every candidate; `count_hard_full` (+ circulation)
is called once per outer iteration and once at the end.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


from app.scene.schema import Scene, SceneObject
from app.spatial.geometry import distance as geo_distance
from app.spatial.geometry import segments_intersect
from app.spatial.validation import object_footprint, validate_object, validate_scene
from app.spatial.clearance_engine import (
    circulation_violations, functional_clearance_violations,
    pairwise_clearance_violations)
from app.spatial.collision_solver import (
    find_valid_nudge)
from app.spatial.bounded_search import (
    PlacementTask, solve_backtracking)

MAX_ITERATIONS = 20
LEVEL3_BUDGET = 400
DUPLICATE_IOU_THRESHOLD = 0.70


class TerminalState(str, Enum):
    REPAIRED = "REPAIRED"
    ALREADY_VALID = "ALREADY_VALID"
    UNREPAIRABLE = "UNREPAIRABLE"
    ESCALATE = "ESCALATE"
    TIMEOUT = "TIMEOUT"
    UPSTREAM_REQUIRED = "UPSTREAM_REQUIRED"


@dataclass(frozen=True)
class RepairRecord:
    level: int
    repair_type: str
    subject_id: str
    target_id: Optional[str]
    cause: str
    outcome: str
    distance_moved_m: float
    candidates_tried: int
    priority: int
    evidence: tuple


@dataclass(frozen=True)
class RepairResult:
    scene: Scene
    terminal_state: str
    records: tuple
    hard_before: int
    hard_after: int
    soft_before: float
    soft_after: float
    escalation_level_reached: int
    nodes_explored: int


@dataclass(frozen=True)
class _Failure:
    code: str
    subject_id: str
    target_id: Optional[str]


def _wall_by_object(relations) -> dict:
    return {r["subject_id"]: r["object_id"] for r in relations
            if r.get("predicate") == "AGAINST_WALL"}


def count_hard_fast(scene: Scene) -> int:
    return sum(1 for v in validate_scene(scene) if v.severity == "hard")


def count_hard_full(scene: Scene, entrance_xz: Optional[tuple]) -> int:
    n = count_hard_fast(scene)
    if entrance_xz is not None:
        n += sum(1 for v in circulation_violations(scene, entrance_xz) if v.severity == "hard")
    return n


def sum_soft(scene: Scene) -> float:
    return (sum(v.deficit_m for v in pairwise_clearance_violations(scene)) +
           sum(v.deficit_m for v in functional_clearance_violations(scene)))


def _footprint_iou(a: SceneObject, b: SceneObject) -> float:
    """Coarse IoU via each footprint's own axis-aligned bounding box - exact
    convex-polygon intersection area is not needed for a >70% threshold
    check; an AABB approximation is conservative enough (never reports a
    higher IoU than the true convex intersection could for near-aligned
    boxes) and reuses no new geometry primitive."""
    fa, fb = object_footprint(a), object_footprint(b)
    ax0, ax1 = min(p[0] for p in fa), max(p[0] for p in fa)
    az0, az1 = min(p[1] for p in fa), max(p[1] for p in fa)
    bx0, bx1 = min(p[0] for p in fb), max(p[0] for p in fb)
    bz0, bz1 = min(p[1] for p in fb), max(p[1] for p in fb)
    ix0, ix1 = max(ax0, bx0), min(ax1, bx1)
    iz0, iz1 = max(az0, bz0), min(az1, bz1)
    if ix1 <= ix0 or iz1 <= iz0:
        return 0.0
    inter = (ix1 - ix0) * (iz1 - iz0)
    area_a = (ax1 - ax0) * (az1 - az0)
    area_b = (bx1 - bx0) * (bz1 - bz0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def is_duplicate_pair(a: SceneObject, b: SceneObject) -> bool:
    """repair.md P4.2: same semantic_type, >70% footprint IoU, centers
    within a small multiple of their own size - conservative on purpose so
    two real, distinct, closely-pushed-together objects are never
    misclassified as one duplicate detection."""
    if a.semantic_type != b.semantic_type:
        return False
    if _footprint_iou(a, b) <= DUPLICATE_IOU_THRESHOLD:
        return False
    size = max(a.dimensions[0], a.dimensions[2], 0.1)
    d = geo_distance((a.position[0], a.position[2]), (b.position[0], b.position[2]))
    return d < size * 0.5


def identify_blocking_object(scene: Scene, entrance_xz: tuple, target_object_id: str) -> Optional[str]:
    """repair.md P4.2: the floor-mounted object whose footprint the direct
    entrance-to-target line crosses first - a deterministic, explainable
    PROXY for "what's in the way," not a formal blame-attribution algorithm
    (see repair.md for why a graph-cut/max-flow analysis is not justified
    without evidence it is needed)."""
    target = scene.object(target_object_id)
    if target is None:
        return None
    target_center = (target.position[0], target.position[2])
    hits = []
    for obj in scene.objects:
        if obj.object_id == target_object_id or obj.mount != "floor":
            continue
        poly = object_footprint(obj)
        n = len(poly)
        if any(segments_intersect(entrance_xz, target_center, poly[i], poly[(i + 1) % n]) for i in range(n)):
            hits.append((geo_distance(entrance_xz, (obj.position[0], obj.position[2])), obj.object_id))
    if not hits:
        return None
    hits.sort()
    return hits[0][1]


def collect_hard_failures(scene: Scene, relations, entrance_xz) -> list:
    out = []
    for v in validate_scene(scene):
        if v.severity == "hard":
            out.append(_Failure(v.code, v.object_id, v.related_id))
    if entrance_xz is not None:
        for v in circulation_violations(scene, entrance_xz):
            if v.severity == "hard":
                out.append(_Failure("CIRCULATION", v.target_id, None))
    return out


def classify_and_get_movers(failure: _Failure, scene: Scene, entrance_xz) -> tuple:
    """Returns (movable_object_ids | None, reason). None means "not
    repairable by movement" - repair.md P4.2's mandatory distinction."""
    if failure.code in ("COLLIDES_WALL", "BLOCKS_DOOR"):
        return [failure.subject_id], f"{failure.code}: wall/opening not movable, single mover"
    if failure.code == "COLLIDES_OBJECT":
        a, b = scene.object(failure.subject_id), scene.object(failure.target_id)
        if a is not None and b is not None and is_duplicate_pair(a, b):
            return None, (f"OBJECT_IDENTITY_SUSPECTED: {a.object_id}/{b.object_id} same "
                          f"semantic_type, footprint IoU > {DUPLICATE_IOU_THRESHOLD}, "
                          "near-identical position - likely two groundings of one object")
        return [failure.subject_id, failure.target_id], "two-way mover, priority resolves which moves"
    if failure.code == "CIRCULATION":
        if entrance_xz is None:
            return None, "no entrance point supplied - circulation cannot be attributed"
        blocker = identify_blocking_object(scene, entrance_xz, failure.subject_id)
        if blocker is None:
            return None, "no identifiable blocking object along the direct entrance-target line"
        return [blocker], f"identified blocking object {blocker} via straight-line proxy"
    return [failure.subject_id], f"{failure.code}: default single mover"


def _pick_mover(scene: Scene, movable: list) -> str:
    if len(movable) == 1:
        return movable[0]
    objs = [scene.object(oid) for oid in movable]
    objs = [o for o in objs if o is not None]
    if not objs:
        return movable[0]
    objs.sort(key=lambda o: (o.confidence.value, o.object_id))
    return objs[0].object_id   # lower confidence moves first (P1's own rule)


def _try_nudge(scene: Scene, obj_id: str, relations, entrance_xz) -> Optional[tuple]:
    """LEVEL 1/2 primitive: remove `obj_id`, search P1's lattice for a
    candidate that reduces the FAST hard count (validate_scene only -
    circulation is checked once by the caller, not per candidate). Returns
    (new_scene, distance_moved_m, candidates_tried) or None."""
    obj = scene.object(obj_id)
    if obj is None:
        return None
    before = count_hard_fast(scene)
    working_minus = scene.model_copy(update={"objects": [o for o in scene.objects if o.object_id != obj_id]})
    wall_id = _wall_by_object(relations).get(obj_id)
    wall = working_minus.wall(wall_id) if wall_id else None
    placed, dist, tried = find_valid_nudge(working_minus, obj, wall)
    if placed is None:
        return None
    candidate_scene = working_minus.model_copy(update={"objects": working_minus.objects + [placed]})
    if count_hard_fast(candidate_scene) < before:
        return candidate_scene, dist, tried
    return None


def _circulation_hard_count(scene: Scene, entrance_xz) -> int:
    if entrance_xz is None:
        return 0
    return sum(1 for v in circulation_violations(scene, entrance_xz) if v.severity == "hard")


def _try_nudge_for_circulation(scene: Scene, obj_id: str, relations, entrance_xz,
                               max_probes: int = 5) -> Optional[tuple]:
    """CIRCULATION's LEVEL 1 primitive - deliberately the OPPOSITE bias from
    `_try_nudge`. A collision/wall repair wants the SMALLEST deviation from
    evidence; a circulation repair needs ENOUGH clearance to open a path, so
    the nearest-valid candidate (which `find_valid_nudge` returns) is often
    geometrically clean but circulation-useless - it may move the object
    only a few centimetres. This tries the lattice FARTHEST-offset-first and
    checks circulation on each geometrically-clean candidate it reaches -
    bounded to `max_probes` circulation calls (each costs 0.4-3.5 s/scene,
    P2/P3), deliberately small: LEVEL 1 is meant to be a cheap, fast-failing
    heuristic, not an exhaustive search - LEVEL 3's bounded local
    backtracking (below) is the systematic fallback if this quick try misses,
    and it pays the circulation cost only once, on its own final result."""
    obj = scene.object(obj_id)
    if obj is None:
        return None
    before_fast = count_hard_fast(scene)
    before_circ = _circulation_hard_count(scene, entrance_xz)
    working_minus = scene.model_copy(update={"objects": [o for o in scene.objects if o.object_id != obj_id]})
    wall_id = _wall_by_object(relations).get(obj_id)
    wall = working_minus.wall(wall_id) if wall_id else None
    probes = 0
    for cand in reversed(_lattice_candidates(obj, wall)):
        if validate_object(working_minus, cand):
            continue
        candidate_scene = working_minus.model_copy(update={"objects": working_minus.objects + [cand]})
        if count_hard_fast(candidate_scene) > before_fast:
            continue
        probes += 1
        if _circulation_hard_count(candidate_scene, entrance_xz) < before_circ:
            import math as _m
            dist = _m.hypot(cand.position[0] - obj.position[0], cand.position[2] - obj.position[2])
            return candidate_scene, round(dist, 4)
        if probes >= max_probes:
            return None
    return None


def _try_local_backtracking(scene: Scene, movable: list, relations, budget: int,
                            entrance_xz=None, require_circulation_fix: bool = False) -> Optional[tuple]:
    """LEVEL 3: scene_optimizer.solve_backtracking, scoped to ONLY the
    objects in `movable` (plus everything else in the scene held fixed as
    backdrop) - never the whole scene's shared budget, the exact thing P3
    measured starving later objects."""
    before = count_hard_fast(scene)
    others = [o for o in scene.objects if o.object_id not in movable]
    base = scene.model_copy(update={"objects": others})
    tasks = []
    for oid in movable:
        obj = scene.object(oid)
        if obj is None:
            continue
        wall_id = _wall_by_object(relations).get(oid)
        wall = base.wall(wall_id) if wall_id else None
        cands = [obj] + _lattice_candidates(obj, wall)
        tasks.append(PlacementTask(oid, tuple(cands)))
    if not tasks:
        return None
    result = solve_backtracking(base, tasks, budget, "level3_local")
    candidate_scene = result.scene
    if result.unplaced or count_hard_fast(candidate_scene) > before:
        return None
    if require_circulation_fix:
        if _circulation_hard_count(candidate_scene, entrance_xz) < _circulation_hard_count(scene, entrance_xz):
            return candidate_scene, result.nodes_explored
        return None
    if count_hard_fast(candidate_scene) < before:
        return candidate_scene, result.nodes_explored
    return None


def _lattice_candidates(obj: SceneObject, wall) -> list:
    """The same offsets `find_valid_nudge` searches, as an unvalidated
    candidate LIST rather than a first-match search - needed to feed
    `solve_backtracking`, which explores/backtracks over a supplied list
    rather than generating one on demand."""
    import math as _math

    from app.spatial.collision_solver import (
        MAX_SEARCH_M, STEP_M, _radial_candidates, _slide_offsets)
    origin = (obj.position[0], obj.position[2])
    out = []
    if wall is not None:
        dx, dz = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
        length = _math.hypot(dx, dz) or 1.0
        tangent = (dx / length, dz / length)
        for offset in _slide_offsets(MAX_SEARCH_M, STEP_M):
            cand_xz = (origin[0] + tangent[0] * offset, origin[1] + tangent[1] * offset)
            out.append(obj.model_copy(update={"position": (round(cand_xz[0], 6), obj.position[1], round(cand_xz[1], 6))}))
    else:
        for dx_r, dz_r in _radial_candidates(MAX_SEARCH_M, STEP_M):
            cand_xz = (origin[0] + dx_r, origin[1] + dz_r)
            out.append(obj.model_copy(update={"position": (round(cand_xz[0], 6), obj.position[1], round(cand_xz[1], 6))}))
    return out


def repair_scene(scene: Scene, relations: list = (), entrance_xz: Optional[tuple] = None,
                 max_iterations: int = MAX_ITERATIONS, max_level: int = 3) -> RepairResult:
    """The full DETECT -> CLASSIFY -> LOCALIZE -> REPAIR -> RE-VALIDATE ->
    ESCALATE loop. `max_level` caps the escalation ladder (repair.md); 3
    (local repair -> direct competitor -> bounded local backtracking) is the
    production default - LEVEL 4 (broader search) is available but opt-in
    only, per P3's own measured cost-vs-benefit finding."""
    hard0 = count_hard_fast(scene) + (sum(1 for v in circulation_violations(scene, entrance_xz) if v.severity == "hard")
                                      if entrance_xz is not None else 0)
    soft0 = sum_soft(scene)
    if hard0 == 0:
        return RepairResult(scene, TerminalState.ALREADY_VALID.value, (), 0, 0, soft0, soft0, 0, 0)

    working = scene
    records: list = []
    blocked: set = set()          # (code, subject_id, target_id) already known unrepairable
    escalation_level = 0
    nodes = 0
    priority = 0
    hit_iteration_cap = True

    for _iteration in range(max_iterations):
        failures = [f for f in collect_hard_failures(working, relations, entrance_xz)
                   if (f.code, f.subject_id, f.target_id) not in blocked]
        if not failures:
            hit_iteration_cap = False
            break

        failures.sort(key=lambda f: (f.code, f.subject_id, f.target_id or ""))
        failure = failures[0]
        priority += 1
        movable, reason = classify_and_get_movers(failure, working, entrance_xz)

        if movable is None:
            blocked.add((failure.code, failure.subject_id, failure.target_id))
            records.append(RepairRecord(0, "CLASSIFY_UNREPAIRABLE", failure.subject_id, failure.target_id,
                                        failure.code, TerminalState.UPSTREAM_REQUIRED.value, 0.0, 0,
                                        priority, (reason,)))
            continue

        mover = _pick_mover(working, movable)

        if failure.code == "CIRCULATION":
            # CIRCULATION needs its own LEVEL 1/3 (far-biased nudge, then
            # bounded local backtracking checked against circulation, not
            # count_hard_fast, which cannot see circulation at all) - see
            # _try_nudge_for_circulation's docstring.
            rc1 = _try_nudge_for_circulation(working, mover, relations, entrance_xz)
            if rc1 is not None:
                working, dist = rc1
                escalation_level = max(escalation_level, 1)
                records.append(RepairRecord(1, "LOCAL_NUDGE_FAR", mover, None, failure.code, "MOVED",
                                            dist, 0, priority, (reason,)))
                continue
            if max_level >= 3:
                rc3 = _try_local_backtracking(working, movable, relations, LEVEL3_BUDGET,
                                              entrance_xz=entrance_xz, require_circulation_fix=True)
                if rc3 is not None:
                    working, explored = rc3
                    nodes += explored
                    escalation_level = max(escalation_level, 3)
                    records.append(RepairRecord(3, "BOUNDED_LOCAL_BACKTRACK", movable[0], None,
                                                failure.code, "MOVED", 0.0, explored, priority, (reason,)))
                    continue
            blocked.add((failure.code, failure.subject_id, failure.target_id))
            records.append(RepairRecord(escalation_level, "NONE", failure.subject_id, failure.target_id,
                                        failure.code, TerminalState.ESCALATE.value, 0.0, 0, priority,
                                        ("no circulation-fixing repair found at levels 1/3",)))
            continue

        r1 = _try_nudge(working, mover, relations, entrance_xz)
        if r1 is not None:
            working, dist, tried = r1
            nodes += tried
            escalation_level = max(escalation_level, 1)
            records.append(RepairRecord(1, "LOCAL_NUDGE", mover, None, failure.code, "MOVED",
                                        dist, tried, priority, (reason,)))
            continue

        if len(movable) == 2 and max_level >= 2:
            other = movable[1] if mover == movable[0] else movable[0]
            r2 = _try_nudge(working, other, relations, entrance_xz)
            if r2 is not None:
                working, dist, tried = r2
                nodes += tried
                escalation_level = max(escalation_level, 2)
                records.append(RepairRecord(2, "COMPETITOR_NUDGE", other, mover, failure.code, "MOVED",
                                            dist, tried, priority, (reason,)))
                continue

        if max_level >= 3:
            r3 = _try_local_backtracking(working, movable, relations, LEVEL3_BUDGET)
            if r3 is not None:
                working, explored = r3
                nodes += explored
                escalation_level = max(escalation_level, 3)
                records.append(RepairRecord(3, "BOUNDED_LOCAL_BACKTRACK", movable[0],
                                            movable[1] if len(movable) > 1 else None,
                                            failure.code, "MOVED", 0.0, explored, priority, (reason,)))
                continue

        blocked.add((failure.code, failure.subject_id, failure.target_id))
        records.append(RepairRecord(escalation_level, "NONE", failure.subject_id, failure.target_id,
                                    failure.code, TerminalState.ESCALATE.value, 0.0, 0, priority,
                                    ("no repair at levels 1-3 found a valid, improving candidate",)))
    else:
        hit_iteration_cap = True

    # One consistent terminal-state computation, whether the loop exited via
    # "nothing left to try" or the iteration cap - both paths land here so
    # the classification can never disagree with itself (the earlier bug
    # this fixes: "nothing left to try" used to hardcode UPSTREAM_REQUIRED
    # even when every remaining violation had genuinely been attempted and
    # failed, not classified as unrepairable-by-movement).
    final_hard = count_hard_full(working, entrance_xz)
    final_soft = sum_soft(working)
    if final_hard == 0:
        terminal = TerminalState.REPAIRED
    elif hit_iteration_cap:
        terminal = TerminalState.TIMEOUT
    else:
        any_upstream = any(r.outcome == TerminalState.UPSTREAM_REQUIRED.value for r in records)
        any_moved = any(r.outcome == "MOVED" for r in records)
        terminal = (TerminalState.UPSTREAM_REQUIRED if any_upstream and not any_moved
                   else TerminalState.ESCALATE if any_moved
                   else TerminalState.UNREPAIRABLE)

    return RepairResult(working, terminal.value if isinstance(terminal, TerminalState) else terminal,
                        tuple(records), hard0, final_hard, soft0, final_soft, escalation_level, nodes)


__all__ = ["TerminalState", "RepairRecord", "RepairResult", "repair_scene",
           "classify_and_get_movers", "identify_blocking_object", "is_duplicate_pair",
           "count_hard_fast", "count_hard_full", "sum_soft"]

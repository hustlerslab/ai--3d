"""P3 bounded LOCAL backtracking: the one search strategy the P3/P4 gates
validated for production use - as the LEVEL 3 escalation inside
`app.spatial.repair_engine`, scoped to the implicated objects, never as a
whole-scene default (P3 decision: GREEDY IS DEFAULT, `place_objects`).

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md.

The research comparison harness (greedy/beam/greedy+repair, `STRATEGIES`)
stays in research/spatial_architecture/scene_optimizer.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


from app.scene.schema import Scene, SceneObject
from app.spatial.validation import validate_object, validate_scene
from app.spatial.clearance_engine import (
    functional_clearance_violations, pairwise_clearance_violations)


@dataclass(frozen=True)
class PlacementTask:
    object_id: str
    candidates: tuple[SceneObject, ...]   # ranked best-first, exactly as the real generators produce


@dataclass(frozen=True)
class SolveResult:
    strategy: str
    scene: Scene
    unplaced: tuple[str, ...]
    hard_count: int
    soft_deficit: float
    nodes_explored: int


def _committed_scene(base: Scene, objects: list[SceneObject]) -> Scene:
    return base.model_copy(update={"objects": objects})


def score(scene: Scene) -> tuple[int, float]:
    """(hard_count, soft_deficit) - lexicographic per optimization.md §3."""
    hard = sum(1 for v in validate_scene(scene) if v.severity == "hard")
    soft = sum(v.deficit_m for v in pairwise_clearance_violations(scene))
    soft += sum(v.deficit_m for v in functional_clearance_violations(scene))
    return hard, soft


# ── B/C. backtracking = DFS over the assignment tree, budget-parametrized ──

def solve_backtracking(base: Scene, tasks: list[PlacementTask], node_budget: int,
                       label: str = "backtracking") -> SolveResult:
    n = len(tasks)
    committed: list[Optional[SceneObject]] = [None] * n
    nodes = [0]
    # An anytime/bounded search must never do worse than greedy: if the node
    # budget runs out mid-recursion, unwinding without remembering the best
    # partial assignment seen so far would discard every already-valid
    # commitment, not just the abandoned deep branch - a real bug caught by
    # this harness's own n=20/30 scaling runs (bounded_backtracking and dfs
    # both reported EVERY object unplaced, which is impossible for a search
    # that explores greedy's own choices as its first branch). `best` tracks
    # the assignment with the fewest unplaced objects found at any point.
    best: dict = {"committed": list(committed), "count": -1}

    def snapshot_if_better() -> None:
        placed_count = sum(1 for c in committed if c is not None)
        if placed_count > best["count"]:
            best["count"] = placed_count
            best["committed"] = list(committed)

    def rec(i: int) -> bool:
        if i == n:
            snapshot_if_better()
            return True
        for cand in tasks[i].candidates:
            nodes[0] += 1
            if nodes[0] > node_budget:
                snapshot_if_better()
                return False
            working = _committed_scene(base, [c for c in committed[:i] if c is not None] + [cand])
            if not validate_object(working, cand):
                committed[i] = cand
                snapshot_if_better()
                if rec(i + 1):
                    return True
                committed[i] = None
        snapshot_if_better()
        return False

    rec(0)
    placed = [c for c in best["committed"] if c is not None]
    unplaced = tuple(tasks[i].object_id for i in range(n) if best["committed"][i] is None)
    scene = _committed_scene(base, placed)
    hard, soft = score(scene)
    return SolveResult(label, scene, unplaced, hard, soft, nodes[0])

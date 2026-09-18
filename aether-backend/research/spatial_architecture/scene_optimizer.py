"""P3 search-strategy comparison harness: one candidate space, several
search algorithms over it, per docs/spatial_architecture/optimization.md's
formal definition (discrete/combinatorial, NOT continuous - the existing
candidate generators already enumerate finite, ranked position/rotation
options, so every strategy below is a CSP/weighted-CSP search over the SAME
`(objects, candidates-per-object, Score)` triple, not a different problem
representation).

Research harness. `PlacementTask`/`SolveResult`/`score`/`solve_backtracking`
(the validated portion) now live in `app.spatial.bounded_search`; the
comparison-only strategies stay here. `score()` reuses production's own `validate_object`
(collision/room/door) plus P2's `pairwise_clearance_violations`/
`functional_clearance_violations` (soft deficits) - no new geometry check.
Circulation is deliberately NOT part of the per-candidate score: P2 measured
it at 0.4-3.5 s per full scene (decisions.md), so evaluating it inside a
combinatorial search loop that may try hundreds of candidate combinations is
computationally prohibitive; it is checked once on each strategy's FINAL
output instead, exactly like `integration_benchmark.py` already does.

FIVE STRATEGIES, NOT SIX. CP-SAT/MILP (the brief's item E) is not
implemented here - see docs/spatial_architecture/decisions.md's P3 entry for
why, decided from research before writing any code, per the standing rule
"if research conclusively eliminates an approach before implementation,
document why." "Greedy + bounded backtracking" and "DFS / bounded search"
(items B and C) are the SAME algorithm (chronological backtracking IS
depth-first search over the assignment tree, a standard CSP-literature
equivalence) at two different node budgets, not two different mechanisms -
`solve_backtracking` takes the budget as a parameter instead of being
duplicated. Item G (one additional method justified by research) is greedy
followed by P1's own local-repair pattern (`collision_solver.py`), adapted
to this harness's candidate representation - already-measured, already-cheap,
and a real fifth point of comparison rather than an arbitrary addition.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scene.schema import Scene, SceneObject  # noqa: E402
from app.spatial.validation import validate_object  # noqa: E402
from app.spatial.bounded_search import (  # noqa: E402
    PlacementTask, SolveResult, _committed_scene, score, solve_backtracking)


# ── A. greedy (the existing production pattern, generalized) ───────────────

def solve_greedy(base: Scene, tasks: list[PlacementTask]) -> SolveResult:
    committed: list[SceneObject] = []
    unplaced: list[str] = []
    nodes = 0
    for task in tasks:
        placed = None
        for cand in task.candidates:
            nodes += 1
            working = _committed_scene(base, committed + [cand])
            if not validate_object(working, cand):
                placed = cand
                break
        if placed is not None:
            committed.append(placed)
        else:
            unplaced.append(task.object_id)
    scene = _committed_scene(base, committed)
    hard, soft = score(scene)
    return SolveResult("greedy", scene, tuple(unplaced), hard, soft, nodes)


# ── D. beam search ──────────────────────────────────────────────────────────

def solve_beam(base: Scene, tasks: list[PlacementTask], beam_width: int) -> SolveResult:
    # each beam entry: (committed list incl. None for unplaced, working Scene)
    beams: list[tuple[list[Optional[SceneObject]], Scene]] = [([], base)]
    nodes = 0
    for task in tasks:
        expanded: list[tuple[tuple[int, float], list[Optional[SceneObject]], Scene]] = []
        for committed, working in beams:
            any_valid = False
            for cand in task.candidates:
                nodes += 1
                if not validate_object(working, cand):
                    any_valid = True
                    trial = _committed_scene(base, [c for c in committed if c is not None] + [cand])
                    h, s = score(trial)
                    expanded.append(((h, s), committed + [cand], trial))
            if not any_valid:
                h, s = score(working)
                expanded.append(((h + 1, s), committed + [None], working))
        expanded.sort(key=lambda e: e[0])
        beams = [(c, w) for _, c, w in expanded[:beam_width]]
    best_committed, best_scene = min(beams, key=lambda cw: score(cw[1]))
    unplaced = tuple(tasks[i].object_id for i, c in enumerate(best_committed) if c is None)
    hard, soft = score(best_scene)
    return SolveResult("beam", best_scene, unplaced, hard, soft, nodes)


# ── F. greedy + P1-style local repair (the justified 5th strategy) ─────────

def solve_greedy_then_repair(base: Scene, tasks: list[PlacementTask],
                             max_search_offsets: int = 20) -> SolveResult:
    """Runs `solve_greedy`, then applies P1's own pattern (order by
    confidence, re-commit sequentially, nudge a conflicting object along a
    small deterministic offset lattice) to the objects `solve_greedy` placed
    - NOT a new algorithm, `collision_solver.resolve_collisions`'s pattern
    adapted to this harness's simpler (no wall-tangent evidence) candidates:
    each unresolved object retries its OWN remaining ranked candidates
    (rather than a geometric offset lattice), since here - unlike P1's photo
    bridge - a ranked candidate list already exists to fall back on."""
    greedy = solve_greedy(base, tasks)
    by_id = {t.object_id: t for t in tasks}
    ordered_ids = sorted((o.object_id for o in greedy.scene.objects),
                        key=lambda oid: (-next(o for o in greedy.scene.objects if o.object_id == oid)
                                        .confidence.value, oid))
    committed: list[SceneObject] = []
    nodes = greedy.nodes_explored
    for oid in ordered_ids:
        original = next(o for o in greedy.scene.objects if o.object_id == oid)
        working = _committed_scene(base, committed + [original])
        if not validate_object(working, original):
            committed.append(original)
            continue
        task = by_id[oid]
        placed = None
        for cand in task.candidates[:max_search_offsets]:
            nodes += 1
            working = _committed_scene(base, committed + [cand])
            if not validate_object(working, cand):
                placed = cand
                break
        committed.append(placed if placed is not None else original)
    unplaced = tuple(greedy.unplaced)
    scene = _committed_scene(base, committed)
    hard, soft = score(scene)
    return SolveResult("greedy_then_repair", scene, unplaced, hard, soft, nodes)


STRATEGIES = {
    "greedy": lambda base, tasks: solve_greedy(base, tasks),
    "bounded_backtracking": lambda base, tasks: solve_backtracking(base, tasks, 50, "bounded_backtracking"),
    "dfs": lambda base, tasks: solve_backtracking(base, tasks, 5000, "dfs"),
    "beam_5": lambda base, tasks: solve_beam(base, tasks, 5),
    "greedy_then_repair": lambda base, tasks: solve_greedy_then_repair(base, tasks),
}

__all__ = ["PlacementTask", "SolveResult", "score", "solve_greedy", "solve_backtracking",
           "solve_beam", "solve_greedy_then_repair", "STRATEGIES"]

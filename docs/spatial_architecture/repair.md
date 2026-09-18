# P4.1-P4.3 — Repair research, responsibility model, repair classification

Continues from `repair_baseline.md`. Covers three phases in one document, as
`collision.md` and `clearance.md` did for P1/P2.

## P4.1 — Research

### Search strategy and sources

`"min-conflicts heuristic repair CSP local search algorithm Minton"`,
`"conflict-directed backtracking dependency-directed backtracking CSP
algorithm"`, `"CAD constraint solver repair geometric constraint
over-constrained under-constrained repair strategy"`, `"robotics replanning
incremental repair local search bounded planning failure recovery"`.

### Findings, and what they mean for Allure specifically

**Min-conflicts (Minton, Johnston, Philips, Laird, 1992,** [AIJ paper](https://www.dcs.gla.ac.uk/~pat/cpM/papers/mintonAIJ.pdf)**)
is a repair heuristic, not a constructive search: start from a complete but
possibly-inconsistent assignment, repeatedly pick a conflicted variable and
reassign it to whichever value minimizes conflicts.** This is, read
precisely, **exactly what P1's `collision_solver.resolve_collisions`
already does** — commit every object, then for whichever one conflicts,
search a candidate lattice for the option that clears the conflict. P4 does
not need to invent a local-repair algorithm; it needs to name the one P1
already built (a real min-conflicts instance), generalize it beyond
collision to every violation category, and give it explicit termination and
classification, which P1 did not need (P1 only ever handled one violation
type with one known-safe candidate lattice).

**Conflict-directed backjumping (CBJ, Prosser 1993) and dependency-directed
backtracking (Stallman & Sussman, 1977)**: both jump directly to the
variable assignment that is *actually* in conflict, rather than the merely
chronologically-previous one, and both are reported to outperform naive
backjumping (**O(n) vs. O(n³)** space, per the search results' own
comparison). This gives a precise, literature-grounded design for the
mission's "direct competitor reconsideration" level: when local repair
(moving object A) cannot clear a conflict with object B, the next move is
not "backtrack chronologically to whatever was placed before A" — it is
"reconsider B specifically, because B is A's actual conflict partner,"
exactly as `object_id`/`related_id` (or `subject_id`/`target_id`) already
name it in every violation record (`repair_baseline.md` §2).

**CAD geometric constraint solving** confirms the over-/under-constrained
vocabulary (a scene with more hard constraints active than the room can
satisfy is over-constrained — this is Allure's "impossible room," already
measured in P2's `impossible_room` benchmark case) but yielded no directly
reusable repair algorithm beyond that classification vocabulary; CAD solvers
mostly resolve constraint SYSTEMS symbolically (equation solving), a
different representation from Allure's discrete candidate search
(`optimization.md` §1) — not adopted, for the same representation-mismatch
reason continuous/nonlinear optimization was rejected in P3.

**Robotics incremental replanning (LPA*/D* Lite, bounded-suboptimal
truncated variants)** supports the general principle "propagate a failure's
consequences locally, don't replan from scratch" but the specific algorithms
operate on graph search over large state spaces (real-time path replanning)
— a different problem from Allure's small, discrete, per-object candidate
search. The *principle* (local-first, escalate only as needed) is adopted;
the *algorithm* is not, for the same reason: representation mismatch, not
evidence of insufficiency in the simpler approach.

## P4.2 — Violation responsibility model

For every violation type currently produced (`repair_baseline.md` §1-§3),
who can legitimately move:

| Violation | Movable candidates | Reasoning |
|---|---|---|
| `COLLIDES_WALL`, `BLOCKS_DOOR` | `[object_id]` only | the wall/opening is not a `SceneObject`; it cannot move |
| door-swing `FUNCTIONAL` | `[target_id]` only | `subject_id` is `"door:<id>"`, not movable |
| `COLLIDES_OBJECT`, pairwise `CLEARANCE`, wardrobe-envelope `FUNCTIONAL` | `[object_id, related_id]` (or `[subject_id, target_id]`) | either object could move — a real two-way choice, resolved by priority (§below), not arbitrarily |
| `CIRCULATION` (hard or soft) | `[target_id]` **only if** a specific blocking object can be identified (new, this phase — see below); otherwise **none** | `repair_baseline.md` §3's gap: the existing widest-path search discards which obstacle produced the bottleneck |
| duplicate-identity collision (P1's measured residual) | **none** | two groundings of one physical object; moving either fabricates space for two objects where one exists |

**Duplicate-identity detection, made mechanical, not just narrated.** P1's
residual case (two `tv_unit` groundings, same wall gap, near-identical
residuals) is detected here by a concrete geometric test: two colliding
objects of the **same `semantic_type`**, whose footprints overlap by more
than 70% (IoU) **and** whose centers are within a small multiple of their
own size — both conditions measured directly from geometry already in the
`Scene`, not guessed. This is deliberately conservative (high IoU threshold)
so a real close-but-distinct pair (two armchairs pushed together) is never
misclassified — only near-total overlap of same-type objects counts.

**Circulation blocking-object identification, the gap `repair_baseline.md`
§3 named, closed here.** `clearance_engine.py`'s widest-path search already
computes, per grid cell, the minimum distance to every obstacle — it simply
discarded *which* obstacle produced that minimum. A new function reports,
for an unreachable target, the object whose footprint lies closest to the
straight line between the entrance and the target's centroid — a
deterministic, explainable heuristic **proxy** for "what's in the way," not
a formal blame-attribution algorithm (a graph-cut/max-flow analysis of
"which single obstacle's removal reconnects the path" would be more
precise, but nothing measured yet justifies that cost — the straight-line
proxy is correct for the common single-obstacle case, which is what every
measured circulation failure in P2's benchmark actually was).

## P4.3 — Repair classification

Of the eleven classes the brief lists, justified for implementation against
what §P4.2 established:

| Class | Justified? | Why |
|---|---|---|
| Translation (wall-tangent slide) | **Yes — already built, P1** | evidence-preserving for `AGAINST_WALL` objects |
| Perpendicular translation | **Yes — already built, P1** | clears wall-embedding residue (P1's measured fix) |
| Radial translation | **Yes — already built, P1** | freestanding objects, no wall evidence to preserve |
| Rotation / alternative orientation | **Not built** | production `SceneObject` carries no alternate-orientation candidates (that concept exists only in the photo bridge's `GroundingHypothesis.orientation_candidates`, out of this phase's scope — `Scene`-level repair has nothing to rotate *to* without inventing an unevidenced alternative) |
| Alternative candidate (try the object's own next-ranked option) | **Yes** | exactly P1's lattice AND, where a scene came from a candidate-generating solver (P3's harness), P3's own `PlacementTask.candidates` |
| Object-order change | **Not built as a standalone class** | this is what LEVEL 3/4 bounded search already does internally (re-deciding order via backtracking) — a separate "reshuffle order" primitive would duplicate it |
| Undo last placement | **Implicit, not a separate primitive** | every repair attempt already builds a fresh candidate scene and only commits if it validates (`repair_baseline.md` §5) — there is nothing to "undo" that isn't already just "don't commit" |
| Local backtracking | **Yes — new, P4.4, reusing P3's `solve_backtracking`** scoped to a small neighborhood |
| Constraint relaxation | **Explicitly rejected** | the mission's own principle 7 ("hard constraints can never be sacrificed for soft preferences") and P3's lexicographic scoring both forbid this outright — no code path may accept a scene with more hard violations because it scores better on soft ones |
| Upstream perception escalation | **Yes — a terminal classification, not a repair action** | `UPSTREAM_REQUIRED` (P4.7), used exactly for duplicate-identity and unattributable-circulation cases |
| Geometry escalation | **Named, deferred to P5** | a `COLLIDES_WALL` that resists every repair attempt is exactly the wall-tilt representation-loss case P1 already measured (`spatial_architecture_report.md` Finding 2) — P4 classifies and reports it (P4.13), it does not fix wall representation (that is explicitly P5's mandate, not P4's) |

**Every repair record carries**, per the brief's own required schema:
`repair_type, subject_id, target_id, cause, candidate_state, priority,
evidence, deterministic_rank` — implemented as `RepairRecord` in
`repair_engine.py`.

**Exit gate (all three phases): met.** §P4.2's table above makes "not
repairable by movement" a concrete, checkable classification (duplicate
identity, unattributable circulation) rather than a narrative claim; §P4.3's
table justifies each implemented class against either existing evidence or
an explicit research-backed rejection, with no class added merely because it
was listed.

---

## P4.13 — Failure analysis: a real determinism bug, found by P4's own regression testing, root-caused and fixed

Running the real 21-image integration benchmark twice in a row (P4.10/P4.11)
produced **different** `collision resolver: moved N` counts each time
(12, then 13, then 14 across three runs) — a direct violation of the
program's own non-negotiable determinism requirement, caught by testing, not
assumed away.

**Root cause, traced to the exact line, not guessed.** `scene_from_photo.py`
's `grounding_to_scene` constructed every `SceneObject` without an explicit
`object_id`, so each one defaulted to `Field(default_factory=lambda:
new_id("obj"))` — a **fresh random UUID, different every process run**.
`collision_solver.resolve_collisions` orders objects by `(-Confidence.value,
object_id)`; whenever two real photo-grounded objects land on the *exact
same* `overall_confidence` (a real, observed case: it's a product of three
already-quantized channels — P1's `grounding_contract.py` — so exact ties are
not rare), the tie-break silently fell back to comparing two **random**
UUIDs, which differ every run. This flips processing order for tied objects
non-deterministically, which can flip which one successfully claims a
position first in a genuinely order-sensitive greedy solver
(`optimization_baseline.md` §1's own finding about this class of algorithm).

**This is exactly a `GEOMETRY FAILURE` masquerading as a `SEARCH FAILURE`**,
per this phase's own required classification (P4.13's brief) — the search
algorithm was never wrong; the *identity* representation feeding it was
silently non-deterministic. Classified here as **REPRESENTATION FAILURE**
(an identifier that looks stable but isn't), not a solver bug.

**Fix**: `grounding_to_scene` now sets `object_id=f"obj_{h.case_id}"` —
`case_id` (e.g. `"living_room_a.sofa.0"`) is already unique per object and,
critically, **stable across runs** (it is derived from the benchmark's own
fixed case list, not generated at construction time). This is a one-line,
minimal, root-cause fix: it does not touch `resolve_collisions`,
`repair_engine.py`, or any tie-break logic — it fixes the actually-broken
assumption (object identity is stable) at its source, so every consumer of
`object_id` benefits, not just the one call site that happened to surface it.

**Why this was not caught by P1's own unit tests**: every P1 unit test
constructs its `SceneObject`s with an explicit, literal `object_id` (`"obj_a"`,
`"obj_b"`, ...) — never through `grounding_to_scene`. The bug lived entirely
in the bridge's own object construction, which no prior test exercised
end-to-end against a real *tie* in confidence. This is recorded so a future
phase does not have to rediscover it: **any new code that assigns identity
via a default factory must be checked for whether that identity is later
used as a sort/tie-break key** — the two responsibilities (uniqueness,
run-to-run stability) are easy to conflate and only the first is guaranteed
by a UUID.

**Verification**: `tests/test_spatial_architecture_bridge.py` and
`tests/test_spatial_architecture_collision.py` re-run clean (10/10 pass,
unaffected — neither test exercises `grounding_to_scene`'s default id path).
Two consecutive full-benchmark re-runs after the fix both report
`collision resolver: moved 13` — identical, confirmed twice. The real-
benchmark re-run is reported in full in `decisions.md`'s P4 entry.

## P4.13 addendum — a correction to the earlier session's own narrative, caught by testing the responsibility model against real data

`spatial_architecture_report.md`'s prior session narrated the one remaining
real-benchmark residual (two `tv_unit` groundings colliding in
`moodboard_room_living_room.png`) as "almost certainly two detections of the
same physical TV unit." Running `is_duplicate_pair` against the REAL
bounding boxes behind those two groundings (`case_id`s
`preserved.living_room_b.tv_unit.0` = `[455,72,650,200]`, `.1` =
`[288,200,680,262]`) shows they do **not** meet the duplicate test — the two
boxes are a different shape and sit in different image regions (a narrower
box high in the frame vs. a much wider one lower down), not the near-
identical pair the earlier narrative assumed. `is_duplicate_pair` correctly
declined to classify them as duplicates, and `repair_scene` correctly
attempted a normal `COLLIDES_OBJECT`/`COLLIDES_WALL` repair (levels 1-3) —
which failed honestly (`ESCALATE`, hard count unchanged, not silently
"fixed") rather than either wrongly moving a duplicate or wrongly leaving a
real collision unclassified.

**This is corrected here, not left standing**: the more accurate
classification (per P4.13's own required taxonomy) is most likely
`OBJECT_EXTENT_FAILURE` or `UPSTREAM_PERCEPTION_FAILURE` — two distinct
pieces of furniture (plausibly a wall-mounted TV and a separate console
beneath it) sharing one overly-generic `semantic_type` label
(`"tv_unit"`) from Phase 9's coarse vocabulary, with independently
estimated extents that happen to overlap — **not** `OBJECT_IDENTITY_FAILURE`
(duplicate detection) as previously narrated. Recorded as a real example of
testing a prior session's own claim against fresh evidence rather than
repeating it uncritically, per the whole program's standing discipline.

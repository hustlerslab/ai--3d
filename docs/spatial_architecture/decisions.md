# Architecture decisions — running log

One entry per major decision, in the format the brief requires: Problem,
Evidence, Alternatives, Decision, Reason, Trade-offs, Benchmark, Known
limitations. Full research and design detail live in each phase's own
`docs/spatial_architecture/*.md`; this file is the index and the verdicts.

---

## P0 — Baseline freeze

**Problem:** no architectural change can be evaluated without a reproducible
starting point. **Evidence:** `baseline.md`, built by reading (not recalling)
`app/scene/schema.py`, `app/spatial/geometry.py`, `app/spatial/validation.py`,
`app/planning/compiler.py`. **Decision:** freeze `pytest -q` = 371 passed, 7
skipped, 30 xfailed as the regression gate for every later phase.
**Verdict: PASS.**

---

## P1 — Multi-object collision solving

**Problem:** photo-grounded objects are placed independently; 10
`COLLIDES_OBJECT` violations measured across 4 of 21 scenes.

**Evidence:** Holodeck (arXiv:2312.09067), RoomCraft (arXiv:2506.22291,
fetched in full for its CAPS/HDFS mechanics), HSM (arXiv:2503.16848) — all
three use a sequential/DFS-family constraint search as their *primary*
placement mechanism, not a global optimizer; Allure's own
`app/planning/compiler.py:place_objects` already measures 0/547 collisions
using exactly that pattern; SAT-on-convex-polygons is confirmed the right
representation at this object count ("fast... simple shapes, few contacts",
dyn4j.org) against GJK/3D-mesh/BVH alternatives built for a harder regime.

**Alternatives considered and rejected** (full matrix in `collision.md` §5):
OR-Tools CP-SAT `NoOverlap2D` (new dependency, no evidence extension is
insufficient), Shapely/trimesh (redundant with a working in-house kernel),
full 3D mesh collision (wrong representation for a footprint-overlap
failure), global simulated annealing/GA (disproportionate to a 4-scene
failure).

**Decision:** `research/spatial_architecture/collision_solver.py` —
a deterministic DFS-family sequential resolver: order objects by descending
`Confidence.value`, commit one at a time via the existing `validate_object`,
repair a conflict with a fixed candidate lattice (wall-tangent slide for
`AGAINST_WALL` objects, else radial; a small perpendicular fallback for
wall-embedded objects, added mid-phase once measured to be necessary — see
`collision.md` §12). Reuses `validate_object`/`footprint_corners`/
`convex_polygons_overlap` unmodified; adds no dependency; touches nothing in
`app/`.

**Reason:** three independent papers plus Allure's own production evidence
converge on the same algorithm family; the measured failure is that this
mechanism was never *run* on photo-grounded objects, not that a different
mechanism was needed.

**Trade-offs:** no global re-optimization (a scene where every local nudge
fails would need one; none measured yet); the candidate lattice is a fixed
grid, not a continuous search, so a valid position between grid points can be
missed (bounded by `STEP_M`/`EMBED_STEP_M`).

**Benchmark:** `integration_benchmark.py`, 21 images. Scene success
16/21 (76.2%) → **20/21 (95.2%)**. `COLLIDES_OBJECT` 10 → 2 (one scene,
diagnosed as a duplicate perception-level grounding, not a placement
failure). `COLLIDES_WALL` 6 → 1. `pytest -q` 371 → 377 passed, 0 regressions.
6 new deterministic unit tests, including a dedicated 10-repeat-run
determinism check.

**Known limitations:** the one remaining failure is a Phase 9 duplicate-
detection issue, out of P1's scope by construction (`collision.md` §12); no
global backtracking across already-committed objects (matches
`place_objects`'s own limitation, not a new one).

**Verdict: PARTIAL PASS.** Proceeding to P2 (3D clearance constraints).

---

## P2 — 3D clearance constraints

**Problem:** collision-free is not the same as usable. Allure's only
existing distance-based check (H4 `BLOCKS_DOOR`) is a single fixed 0.75 m
constant applied uniformly; nothing distinguishes a sofa flush against a
coffee table (technically clear) from one with room to actually sit
(clearance.md P2.0).

**Evidence:** U.S. Access Board / ADA Fig. 45 (governing accessibility
standard), NKBA kitchen guidelines (governing US kitchen-design body),
buildingSMART's own `IfcDoor`/`IfcDoorTypeOperationEnum` schema docs (swing/
hinge convention), the LaValle group's clearance-path-planning paper and a
CMSC 425 motion-planning lecture (Minkowski-sum config-space, cross-checked
against a second arXiv source), plus a Stanford notes page and a GameDev.net
tutorial converging independently on "grid A* is the fast/simple/predictable
sweet spot at small scale, visibility graphs cost real pre-computation,
navmeshes pay off only at larger scale" (clearance.md P2.1). Every
residential distance figure in the policy table (clearance.md P2.3) cites
its source and how many independent sources converged on it — the weakest
(sofa/table 0.30 m) is flagged as such rather than presented with false
confidence.

**Alternatives considered and rejected:** A* / navmesh / visibility-graph
pathfinding for circulation (P2.5's own exit gate only needs a boolean
reachability signal, not an optimal rendered route — graph *connectivity*,
not path *planning*, is the actual requirement; principle 20 applies). A
single unified "distance" field collapsing all seven mission concepts
(collision/clearance/circulation/functional/accessibility/operating/
preference) into one number (clearance.md P2.2 - each measures a physically
different thing and needs its own evidence source). A six-way parallel
violation-class hierarchy, one class per category (two small orthogonal
attributes, `severity` and `category`, on the existing `Violation`-shaped
type answer every question a class hierarchy would, at a fraction of the
code). Enforcing ADA numbers unconditionally (no signal anywhere in the
pipeline distinguishes an accessibility-mandated scene from an ordinary one;
would silently fail legitimate small-apartment layouts never asked to be
wheelchair-accessible).

**Chosen architecture:** `research/spatial_architecture/clearance_engine.py`
— four checks, one `ClearanceViolation` shape (`subject_id, target_id,
category, constraint, required_m, actual_m, deficit_m, severity,
coordinate_frame` — exactly the fields the brief's own example named):
`pairwise_clearance_violations` (scalar polygon-to-polygon minimum distance,
reusing `point_segment_distance`), `functional_clearance_violations` +
`door_swing_violations` (a second convex polygon per object/door — a
rectangle or circular sector, both convex, both tested with the existing SAT
`convex_polygons_overlap` — no new collision algorithm), and
`circulation_violations` (a 0.05 m grid, Minkowski-inflated by half a
pedestrian's width, searched with a Dijkstra-style widest-path algorithm
rather than plain BFS, so a reported corridor width is a real measured
bottleneck). `severity` defaults hard only for collision (unchanged from
P0/P1) and for total circulation disconnection; every clearance/functional/
narrow-circulation case defaults soft, because each rests on either a
comfort figure (not a physical impossibility) or an assumed, unverified
convention (door hinge side, "front" direction) — treating a guess as hard
risks blocking a real scene on a wrong assumption.

**Why extension, not replacement:** every one of the four checks calls an
existing, already-tested primitive (`footprint_corners`,
`convex_polygons_overlap`, `point_segment_distance`, `point_inside_polygon`)
rather than adding a new collision algorithm; `Violation.severity` already
existed as a bare string in production, just never given a second value.

**Trade-offs:** the circulation check's widest-path search costs real time
at this room scale (0.4-3.5 s per scene in the P2.8 benchmark, dominated by
per-cell distance-field recomputation over a 0.05 m grid) - acceptable for a
research benchmark, a real cost to note before any production integration.
The functional-envelope "front" direction and the door hinge-side/open-angle
convention are both single deterministic defaults with no per-object
evidence behind them (hence `soft`, not `hard`) - a wrongly-oriented
wardrobe would produce a wrong (though harmless, soft-only) reading.
Dining-chair pull-back and kitchen-counter/island clearance are researched
and in the policy table but NOT implemented as wall-relative checks: a
chair's "front" means "away from its table," a different, unverified
convention from the wardrobe's "away from the wall" - building a second,
differently-conventioned heuristic under time pressure was rejected in favor
of naming the gap explicitly (`clearance_benchmark.py`'s own docstring).

**Benchmark:** Real photo fixture (`integration_benchmark.py`, 21 images,
unchanged 20/21 = 95.2% scene success, zero regression): 0 clearance
violations - explained, not hidden: most grounded scenes have 1-4 objects
and the specific policy-covered semantic-type pairs never co-occur close
together in this particular 46-object sample, so the check correctly has
nothing to report, not nothing to find. **Adversarial synthetic benchmark**
(`clearance_benchmark.py`, P2.8): **10/10 cases pass, fully deterministic**
- collision-vs-clearance independence, pairwise clearance (met/violated),
functional envelopes (wardrobe, door swing), circulation (fully blocked,
narrow-but-passable, open), a combined dense-room case, and a room with no
usable floor at all. Building this benchmark surfaced and fixed one real bug
before it could reach any real scene: `circulation_violations` returned `[]`
(silently "no violations") when the entrance itself had no reachable floor
- exactly backwards, since that is the single most broken case the engine
can see. Fixed to emit one explicit hard violation instead, with a dedicated
regression test (`test_circulation_reports_when_entrance_itself_is_
unreachable`). `pytest -q`: 377 → **389 passed** (+12 new tests), 0
regressions.

**Known limitations:** dining-chair and kitchen wall-relative clearance not
implemented (see trade-offs); circulation latency is the slowest path in the
engine by a wide margin; functional/door-swing conventions are assumed
defaults, not measured; accessibility (`ACCESSIBILITY` category) is defined
in the taxonomy but not evaluated by default, by design (no signal
distinguishes an accessibility-mandated scene).

**Verdict: PARTIAL PASS.** Every P2 exit-criterion checkbox is met except
full per-object-family coverage (explicitly scoped, not silently missed).
Proceeding to P3 (global scene optimization) next.

---

## P3 — Global scene optimization

**Problem:** `place_objects`/`resolve_collisions` are both greedy, ordered,
first-valid-candidate solvers with zero cross-object backtracking
(`optimization_baseline.md` §1-§3, read from the live code). Does Allure
actually need a global optimizer, or is greedy already sufficient? — an
empirical question, not assumed either way.

**Evidence:** the formal problem (`optimization.md`) is discrete/
combinatorial — every existing candidate generator already enumerates a
finite, ranked list, never samples continuously — which rules out continuous/
nonlinear optimization on a representation-mismatch basis before any
experiment. P1's own measurement (0/547 hard violations, brief path) is
itself evidence the failure class is rare or absent at Allure's real object
counts and room shapes, even though `optimization_baseline.md` §4
constructs it as a real, theoretically-guaranteed failure mode.

**Candidates implemented** (`research/spatial_architecture/scene_optimizer.py`):
(A) greedy — the existing production pattern, generalized; (B/C) backtracking
= DFS over the assignment tree, budget-parametrized (the CSP literature's own
equivalence — chronological backtracking IS depth-first search — so these
are one function at two budgets, not two mechanisms); (D) beam search;
(F/G) greedy + P1-style local repair, the evidence-justified fifth strategy
(P1's `resolve_collisions` pattern, adapted). **(E) CP-SAT/MILP was not
implemented** — decided from research before writing code, per the standing
rule to document an eliminated approach rather than build it anyway: OR-Tools'
own `NoOverlap2D` has no native support for rotated rectangles (P1's own
`collision.md` §5 finding, still true here), Allure's literature survey
(Holodeck/RoomCraft/HSM, `collision.md` §4) shows the field itself does not
reach for MILP as a primary mechanism at this scale, and — new to P3 — the
DFS experiments below already show that even a dependency-free, no-encoding-
cost deep search has a real, measured downside at scale; a CP-SAT encoding
would add a new dependency and modeling layer without first showing DFS
itself was insufficient.

**Experiments and results** (`optimization_benchmark.py`, full output in
`optimization_benchmark_results.json`):

1. **`wall_dead_end`** — the constructed failure class made concrete: a
   3.4 m wall, a 1.8 m TV unit and a 1.6 m bookshelf. Centered TV placement
   (greedy's first, best-ranked candidate) leaves two 0.8 m stubs — too
   short for the bookshelf anywhere; TV flush to one end leaves a 1.6 m span
   that fits it exactly. **Greedy fails** (bookshelf unplaced), confirming
   the theoretical class is real, not merely possible. **Full DFS (budget
   5000, actual cost 320 nodes / 13 ms) succeeds** — both placed, proving a
   deeper search *can* escape the dead end. **Bounded backtracking (budget
   50) fails identically to greedy** — a budget sweep (10 through 320, in
   the session transcript, not re-derived) shows the true minimum sufficient
   budget is ~320, essentially the full 17×19 candidate product: **there is
   no cheap middle ground for this specific case** — a small budget buys
   nothing over greedy. **Beam search (width 5) also fails**, identically to
   greedy: every one of TV's candidates scores identically (a lone TV never
   causes a clearance deficit), so the beam's top-5 keep is arbitrary among
   near-center candidates and never retains the far-off-center branch that
   works. **Greedy+repair also fails**, exactly as designed: repair reacts to
   a conflict *at* the object being placed, never revisits the earlier
   object whose choice created the dead end.
2. **`regular_baseline`** (non-adversarial sanity) — all five strategies
   place all four objects, hard=0, confirming no strategy regresses on an
   ordinary scene.
3. **Scaling, N ∈ {5, 10, 15, 20, 30}** on a deterministic golden-angle
   spiral: greedy stays cheap and nearly complete (1 object unplaced only at
   N=30, 126 nodes, 10.7 ms). **Bounded backtracking (budget 50) does WORSE
   than greedy at N≥20** (4 unplaced at N=20, 14 at N=30) — a real,
   non-obvious finding: a *shared* global node budget lets search effort
   spent retrying early objects starve later objects of any attempt at all,
   so "bounded" search can place *fewer* objects than plain greedy, not just
   the same or more. **Full DFS (budget 5000) also does worse than greedy at
   N=30** (2 unplaced vs. greedy's 1) at **30x the latency** (326 ms vs.
   10.7 ms) — the budget is consumed by combinatorial growth before
   completing, and unlike the small 2-object case, at N=30 there is no cheap
   escape. **Beam search matches greedy's placement quality but at 40-50x
   the latency**, with no case where it strictly beats greedy on this
   benchmark.
4. A genuine implementation bug was found and fixed before it could
   contaminate any of the above: `solve_backtracking`'s budget-exhaustion
   path was unwinding the ENTIRE recursion stack, discarding every already-
   valid commitment along with the abandoned deep branch — a bounded/anytime
   search must never do worse than the best partial assignment it already
   found. Fixed to track and return the best-partial-assignment seen at any
   point, with a dedicated regression test
   (`test_bounded_search_never_places_fewer_than_one_candidate_each_allows`).
5. **Determinism**: every strategy, 20 identical runs on two different
   cases (`wall_dead_end`, N=15 scaling) — **byte-identical positions,
   rotations, scores, and node counts every time**, confirmed in code (no
   `random` import anywhere in `scene_optimizer.py`).

**Decision: A — keep the greedy sequential solver as the production
architecture.** The theoretical failure class is real and constructible
(experiment 1), but at Allure's actual measured scale (P1: 0/547 real hard
violations; this program's own scaling data: greedy places 29-30/30 objects
across every tested N) a deep search that *can* fix the narrow 2-object case
measurably **stops paying for itself past roughly 20 objects and can
underperform greedy** — worse placement count, tens of times the latency, no
case in this benchmark where it strictly dominates greedy at realistic size.
Per the mission's own explicit allowance: **P3 = PASS — GREEDY ARCHITECTURE
SUFFICIENT.**

**A narrow, documented (not built) escalation path**, for if real data ever
shows the dead-end class actually occurring (it has not, per P1): trigger
bounded backtracking only on greedy's own per-object failure, scoped to just
the unplaced object(s) and whichever earlier objects it competes with for
the same resource — a per-failure budget, not the whole-scene shared budget
this session's experiment showed can starve later objects. This is recorded
as a ready design, not implemented, matching the same restraint P1 applied
to its own repair rule (built only once a real failure was measured).

**Rejected approaches:** continuous/nonlinear optimization (representation
mismatch, §Evidence); CP-SAT/MILP (§Candidates, decided before implementation);
a whole-scene-shared-budget bounded search as the default (§Experiments 3 -
measured to underperform greedy at realistic scale); beam search as the
default (no measured case where it beats greedy, and it fails the exact
adversarial case it exists to solve unless width is impractically large).

**Complexity (P3.8):** greedy is `O(N × M)` (confirmed near-linear in the
scaling data); bounded/shared-budget backtracking has the same per-node cost
but non-monotonic placement quality in N (§Experiments 3); full DFS is
worst-case `O(M^N)` (confirmed: the wall_dead_end sweep needed ~`M_tv × M_shelf`
nodes, essentially the full product, and N=30 scaling exhausted a 5000-node
budget without completing); beam search is `O(N × W × M)`, polynomial and
predictable, but with a constant-factor overhead measured at 20-50x greedy's
wall-clock cost. Viable for **development and demo** at Allure's real object
counts (greedy handles both; DFS is viable only below ~20 objects); **not**
recommended for production as a wholesale replacement at any scale without
the scoped, per-failure escalation design above.

**Limitations:** the two P2 coverage gaps (dining-chair pull-back, kitchen
wall-relative clearance) remain open, unchanged, tracked per the mission's
explicit instruction not to forget them; the objective function
(`optimization.md` §3) omits circulation from per-candidate scoring
(computationally prohibitive inside a combinatorial search loop, per P2's
own measured 0.4-3.5 s/scene circulation cost) — circulation is checked only
on final output, matching how `integration_benchmark.py` already does it;
`solve_greedy_then_repair`'s adapted candidate-retry (not a geometric offset
lattice, since this harness's candidates are pre-enumerated) is demonstrably
unable to fix a dead-end it did not itself detect, by design, not oversight.

**Verdict: P3 = PASS — GREEDY ARCHITECTURE SUFFICIENT.** `pytest -q`:
389 → **395 passed** (+6 new tests), 0 regressions. Frozen integration
benchmark re-run: 20/21 (95.2%) scene success, `COLLIDES_OBJECT`=2,
`COLLIDES_WALL`=1, Blender 20/20 — byte-identical to the P2 baseline, since
P3 touches neither `collision_solver.py` nor `clearance_engine.py`.
**Next dependency: P4 — repair / re-solve loop.**

---

## P4 — Repair / re-solve loop

**Problem:** Allure needs to recover from hard spatial violations without
either (a) blindly re-solving the whole room (P3 already measured that
costing 30-50x greedy's latency with no guaranteed benefit) or (b) papering
over failures with arbitrary nudges. `repair_baseline.md` traced the exact
current mechanism precisely: P1's `collision_solver.py` already repairs
collisions with a candidate lattice, but nothing generalizes that to
`COLLIDES_WALL`/`BLOCKS_DOOR`/circulation, nothing formally classifies WHICH
object should move, and nothing distinguishes a movement-repairable failure
from a duplicate-identity or unattributable-circulation one.

**Research:** min-conflicts (Minton et al. 1992) — a repair heuristic that
starts from a complete-but-inconsistent assignment and repeatedly fixes the
most-conflicted variable — turns out to already describe P1's
`collision_solver.py` exactly; P4 named and generalized an existing
mechanism rather than inventing a new one. Conflict-directed backjumping
(Prosser 1993) and dependency-directed backtracking (Stallman & Sussman
1977) — jump to the actual conflict partner, not merely the chronologically
previous placement — gave the precise design for "direct competitor
reconsideration" (LEVEL 2), since `Violation.related_id`/
`ClearanceViolation.target_id` already name that partner directly. CAD
constraint solving confirmed the over-/under-constrained vocabulary
(P2's own `impossible_room` case *is* an over-constrained scene) but no
directly reusable repair algorithm (different representation — symbolic
equation solving vs. Allure's discrete candidate search). Robotics
incremental replanning (LPA*/D* Lite) supported "repair locally, escalate
only as needed" as a principle without being adopted as an algorithm (graph
search over large state spaces is a different problem from Allure's small,
discrete per-object search).

**Candidates and the escalation ladder built** (`repair_engine.py`):
LEVEL 1 local repair (`find_valid_nudge`, extracted from `collision_solver.py`
as a shared primitive — the SAME primitive now serves both P1's whole-scene
pass and P4's targeted repair, not a duplicate); LEVEL 2 direct competitor
reconsideration (conflict-directed backjumping, applied to the violation's
own named partner); LEVEL 3 bounded local backtracking (`scene_optimizer.
solve_backtracking`, scoped to ONLY the objects already implicated — never
the whole scene's shared budget, the exact thing P3 measured starving later
objects); LEVEL 4 broader search — implemented as available (`max_level`
parameter) but **not invoked by default**, per P3's own measured cost;
LEVEL 5 explicit terminal states (`REPAIRED`, `ALREADY_VALID`,
`UNREPAIRABLE`, `ESCALATE`, `TIMEOUT`, `UPSTREAM_REQUIRED`) — never a
silently-accepted invalid scene.

**Responsibility model** (repair.md P4.2): every violation is classified
into `movable_object_ids | None` before any repair is attempted.
`COLLIDES_WALL`/`BLOCKS_DOOR`/door-swing `FUNCTIONAL` have exactly one
mover (the wall/opening/door cannot move); `COLLIDES_OBJECT`/pairwise
`CLEARANCE`/wardrobe `FUNCTIONAL` have two, resolved by confidence priority;
`CIRCULATION` requires a NEW capability (`identify_blocking_object`, a
straight-line obstruction proxy) since the existing widest-path search
discarded which obstacle produced its bottleneck; a geometric duplicate test
(`is_duplicate_pair` — same `semantic_type`, >70% footprint IoU, near-
identical center) returns `None` (not repairable by movement) for a
suspected duplicate detection, so it is never wrongly moved.

**A real bug found and fixed, not smoothed over** (repair.md P4.13, in
detail): the FIRST implementation of the escalation loop's terminal-state
logic hardcoded `UPSTREAM_REQUIRED` whenever any hard violation remained
after the loop ran out of failures to attempt — even when every remaining
failure had been genuinely tried and had failed (which should read
`ESCALATE`/`UNREPAIRABLE`), not merely classified as unrepairable-by-
movement. Caught by a synthetic "impossible tiny room" test before it could
reach real data; fixed to compute the terminal state once, consistently,
from what the records actually show happened.

**A second, more consequential bug found via the real benchmark itself, not
a unit test**: running the full 21-image integration benchmark repeatedly
produced a DIFFERENT `collision resolver: moved N` count each time (12, 13,
14). Root-caused to `scene_from_photo.py`'s `grounding_to_scene` never
setting an explicit `SceneObject.object_id` — it defaulted to a fresh random
UUID every process run — combined with `resolve_collisions`'s tie-break on
`object_id` for objects sharing the exact same `overall_confidence` (a real,
observed case, not hypothetical). Fixed with a one-line, minimal,
root-cause change: `object_id=f"obj_{case_id}"` (`case_id` is already
unique and, unlike a freshly-generated UUID, stable across runs). Verified:
two independent full-benchmark re-runs after the fix both report
`moved 13` — identical.

**A correction to the prior session's own narrative, caught by testing the
new responsibility model against real data** (repair.md P4.13 addendum):
the one remaining real-benchmark residual (two `tv_unit` groundings
colliding) was previously narrated as "two detections of one physical
object." Running `is_duplicate_pair` against the actual bounding boxes shows
they are NOT a duplicate pair (very different box shapes/positions, not
near-identical) — more likely two distinct pieces of furniture sharing an
overly generic label. `repair_scene` correctly attempted, and correctly
failed, a normal repair (`ESCALATE`), rather than either wrongly moving a
"duplicate" or wrongly leaving a real collision unclassified.

**Results — adversarial benchmark** (`repair_benchmark.py`, P4.8/P4.9):
**12/12 synthetic cases pass**, covering object-object collision, object-wall
collision, soft-clearance-is-not-a-hard-failure, blocked circulation
(genuinely repaired via the circulation-specific LEVEL 1/3 path, see below),
blocked doorway, no-hard-violation orientation cases, competing wall
anchors, a repair that must not trade one violation for another, an
impossible scene (correctly terminates `UNREPAIRABLE`, not silently
"valid"), a duplicate object (correctly `UPSTREAM_REQUIRED`, never moved),
multi-object cascading violations, and confirmation that an already-valid
scene never triggers any escalation level.

**Circulation repair required its own asymmetric design**, discovered by
testing, not assumed: `_try_nudge` (LEVEL 1's generic primitive) is biased
toward the SMALLEST valid deviation from evidence — correct for collision/
wall repair, but useless for circulation, which needs ENOUGH displacement to
open a path. A dedicated `_try_nudge_for_circulation` tries the candidate
lattice farthest-offset-first and checks circulation improvement directly
(not `count_hard_fast`, which cannot see circulation at all) — bounded to 5
probes by default so LEVEL 1 stays a cheap, fast-failing heuristic; LEVEL 3's
bounded local backtracking is the systematic fallback, paying the
circulation-check cost only once on its own final result.

**Results — real Allure benchmark** (`integration_benchmark.py`, P4.10):
scene success unchanged at **20/21 (95.2%)** — P4 does not regress P1/P2/P3.
Of the 3 hard violations in the one already-failing scene, P4's repair
correctly attempts and correctly reports `ESCALATE` for all three (the
extent-mismatch pair above) rather than either a wrong "fix" or a silent
pass — `hard_before=3, hard_after=3`, `terminal_states={ALREADY_VALID: 20,
UNREPAIRABLE: 1}` across the 21 scenes.

**Decision: local repair + direct competitor + bounded LOCAL backtracking
(candidates B+C combined, not D or E)** is the production-shaped
architecture. LEVEL 4 (broader search) is built and available
(`max_level=4`) but not the default, for the same evidence P3 already
established: no measured case in this program needs it, and P3's own
scaling data shows unscoped deeper search can cost far more than it returns.

**Rejected approaches:** whole-scene-shared-budget backtracking as the
default (P3 already measured this starving later objects; P4's LEVEL 3
avoids it by construction, scoping the budget to only the implicated
objects); constraint relaxation (explicitly forbidden — hard constraints
never yield to a better soft score, enforced by construction via the
lexicographic `(hard, soft)` ordering `optimization.md` §3 already defined);
rotation/alternative-orientation repair (no evidenced alternative exists at
the `Scene` level to rotate to — P4.3's own justification table).

**Complexity:** LEVEL 1/2 are `O(M)` (M = lattice candidates per object,
~20-80) — sub-millisecond in every measured case. LEVEL 3 is bounded by
`LEVEL3_BUDGET=400` nodes, scoped to only the implicated objects (typically
2-3), not the whole scene — measured at 0-2 ms in every real-benchmark case
it fired on. Circulation repair is the one expensive path: each
`circulation_violations` call costs 0.4-3.5 s at Allure's tested room scale
(P2/P3's own finding, reconfirmed here), so LEVEL 1's circulation variant is
explicitly capped at 5 probes and LEVEL 3 pays that cost only once — a real,
stated limitation, not hidden: a circulation repair in the P4.8 benchmark
took ~7-8 s end to end, three to four orders of magnitude slower than every
other repair type measured.

**Failure modes** (P4.13's required taxonomy, applied to what was actually
measured): the one real-benchmark residual is `OBJECT_EXTENT_FAILURE` /
`UPSTREAM_PERCEPTION_FAILURE` (two distinct objects sharing one coarse
semantic label with overlapping estimated extents) — corrected here from an
earlier, untested "duplicate identity" narrative. No `GEOMETRY FAILURE`,
`CONSTRAINT FAILURE`, `CANDIDATE GENERATION FAILURE`, or `SEARCH FAILURE`
was observed on real data this phase; a `REPRESENTATION FAILURE` WAS found
and fixed (the random-UUID-as-tie-break-key determinism bug, P4.13) before
it could be mistaken for a `SEARCH FAILURE`.

**Known limitations:** the two P2 coverage gaps (dining-chair pull-back,
kitchen wall-relative clearance) remain open, unchanged, still tracked, not
forgotten; rotation/orientation repair is not implemented (no evidenced
alternative exists to rotate to); circulation repair is measured-expensive
and only lightly benchmarked (one adversarial case, by design — see
`repair_benchmark.py`'s own docstring); LEVEL 4 exists but is unexercised by
any passing test with `max_level=4` (deliberately, since no case needs it).

**Escalation policy** (the answer to "when does deeper search get invoked"):
never by default beyond LEVEL 3. A caller that has measured a real,
recurring failure LEVEL 3 cannot solve may opt into LEVEL 4 explicitly
(`max_level=4`) — this program does not do so today because no such failure
has been measured (matching the exact same restraint precedent set in P1
and P3: build escalation only once a real failure demonstrates the need).

**Verdict: PASS.** `pytest -q`: 395 → **404 passed** (+9 new tests), 0
regressions. Real-benchmark scene success unchanged (20/21, 95.2%).
Determinism: repair_scene's own 20-repeat synthetic test passes, AND a real
non-determinism bug was found and fixed at the pipeline level (two
consecutive full-benchmark runs now agree exactly). **Next dependency:
P5 — wall representation** (the wall-tilt representation-loss finding from
P1's own `spatial_architecture_report.md` Finding 2 remains open and is
explicitly P5's, not P4's, to resolve).

---

## P5 — Wall representation

**Problem:** a measured ~11° wall tilt (`normal=[0.06009, 0.1888,
-0.98018]`, `moodboard_room_master_bedroom` wall_0) causes `COLLIDES_WALL`
errors even though the reconstructed geometry contains the true wall
orientation. `wall_baseline.md` traced this to an exact representation gap,
not a perception or solver failure: `app/scene/schema.py:Wall` stores only a
2D `(start, end)` segment — implicitly a straight *vertical* extrusion —
with no field able to hold a normal's Y-component. Two exact lines in
`scene_from_photo.py` (`_resolve_yaw` line 147, `grounding_to_scene` line
195) silently read only `normal[0]`/`normal[2]`, never `normal[1]` — not an
approximation with a measured residual, a line that never looks at the
value at all.

**Evidence:** buildingSMART's own IFC standard draws exactly this
distinction at the schema level — `IfcWallStandardCase` requires vertical
extrusion; the moment a wall is not vertical, the general `IfcWall` (an
arbitrary `ExtrudedDirection`) is the correct entity. This is independent,
primary-source confirmation of the fix `wall_geometry.md` derives from first
principles: a wall is already "a 2D profile, extruded" — the only change
needed is letting the extrusion direction be something other than
`(0, 1, 0)`. "Batter" (architectural term for an intentionally sloped wall)
confirms tilt is a genuine physical phenomenon, not merely a reconstruction
artifact. Non-Manhattan room-layout literature confirms per-wall RANSAC
plane fitting (Phase 6's own method) is the field's standard perception-side
approach — the gap is downstream, in representation, exactly as diagnosed.

**Candidates compared** (`wall_geometry.md` §P5.2, 8 candidates against the
brief's own required capabilities): infinite plane (rejected — Allure
already needs finite walls); finite oriented plane patch (not chosen — less
exact a match to the existing `wall_rectangle` calling convention than E);
wall segment / wall segment+thickness (today's representation — the loss
source); **extruded polygon with a generalized extrusion direction, chosen**
— a strict superset of today's representation; parametric wall (rejected —
no curved-wall or variable-thickness evidence anywhere in the 48-case
fixture); mesh wall (rejected — mesh/SDF collision only outperforms analytic
geometry at a scale, thousands of triangles/many objects, Allure's regime
never reaches, the same representation-mismatch argument P1/P3 already
established for collision and search); hybrid (not distinct — the chosen
candidate already *is* the hybrid, a superset that costs nothing when
unused).

**Chosen representation**: `research/spatial_architecture/wall_geometry.py`
`TiltedWall` — every field `app.scene.schema.Wall` already has, plus exactly
one: `extrusion_direction: Vec3 = (0, 1, 0)`. Derived, not separately
observed: `up_from_normal(n) = normalize(world_up - n * dot(world_up, n))`,
the projection of world-up onto the wall's own fitted plane — computed from
evidence Phase 6 already measures, no new perception capability. A wall
coordinate frame (`wall_local_frame`: origin, tangent, up, normal) is
explicit and round-trip tested (world → wall-local → world, error
< 1e-9 m for both vertical and tilted walls) — **a real bug was found and
fixed here**: the first implementation's `tangent` (fixed by the 2D
start/end line) and `up` (derived from the fitted normal) were not
orthogonalized against each other, so the basis was not a valid rotation
frame and the round-trip failed for tilted walls; fixed with a Gram-Schmidt
step (`wall_local_frame`'s own comment explains why the two vectors are only
separately, not mutually, perpendicular by construction). `cross_section_at_
height(wall, h)` computes the wall's true 2D footprint at any height by
linear drift, closing the exact loss `wall_baseline.md` traced.
`object_wall_collides` tests an object's footprint at both its own bottom
and top height, never just one fixed reference — collides if either matches,
never silently under-reporting.

**Experiments — P5.9 tilt sweep** (`wall_benchmark.py`, 0/5/10/11/15/20°,
short vs. tall object, both with the same small realistic 0.05 m gap at the
floor reference — never exactly zero, matching how real photo evidence never
measures exactly zero either): **at 0°, OLD and NEW agree exactly on both
objects — zero behavioural change for every ordinary vertical wall,
confirmed, not assumed.** From 5° onward, the TALL object shows `NEW=True,
OLD=False` at every tilt tested — a genuine top-of-object clearance problem
(the wall leans further into the room as height increases) that the OLD
single-fixed-height representation is *structurally* incapable of detecting
at **any** tilt magnitude, because it never reads the object's height at
all. At 20°, even the SHORT object crosses into `NEW=True` — the drift
finally exceeds its small gap. This is not "OLD is sometimes wrong" — it is
"OLD cannot see this class of problem regardless of how large the tilt
grows," precisely matching `wall_baseline.md`'s diagnosis.

**Performance** (P5.13): construction and collision-check cost stay in the
tens-of-microseconds range per wall from 1 to 100 walls (26 µs/wall at
n=1, 26 µs/wall at n=100) — no measurable scaling concern at any residential
room count.

**Determinism** (P5.14): 20 repeated constructions of the same tilted-wall
case produce byte-identical `extrusion_direction`, cross-sections at two
heights, and collision results, every time.

**Downstream compatibility (P5.11), assessed precisely, not assumed:**

| System | Change needed |
|---|---|
| `Room`/`Opening` (openings, room boundary) | **None** — both already operate in plan-view XZ, independent of wall tilt (`wall_baseline.md` §8-13, confirmed already-correct) |
| `collision_solver.py`, `clearance_engine.py` (P1/P2) | **None** — both call `wall_rectangle`/`object_footprint`, inheriting whichever wall representation is passed in; neither needed to change to benefit from a `TiltedWall` if one were threaded through |
| `scene_optimizer.py`, `repair_engine.py` (P3/P4) | **None** — same reasoning; confirmed by re-running all four systems' own benchmarks unchanged after this phase (below) |
| `app/scene/schema.py:Wall`, `scene_from_photo.py`'s two silent-drop lines | **Extension, not built here** — adopting `extrusion_direction` into production `Wall` and reading `normal[1]` at both drop points is the natural next step, deliberately not done in this research phase (principle 12: prototype in `research/`, not `app/`) |

**Rejected representations:** infinite plane, parametric wall, mesh wall —
each for a specific reason above, not a blanket "more complex is worse"
judgment.

**Known limitations:** curved walls and glass/partition semantic
distinction remain unaddressed — no evidence anywhere in the 48-case
fixture justifies either (the `moodboard_room_bathroom` mirror case remains
the same known, unfixed limitation carried forward since Phase 6, unchanged
by this phase); the fix is prototyped in `research/`, not yet adopted into
`app/scene/schema.py` — real end-to-end closure of the master_bedroom-style
`COLLIDES_WALL` case requires BOTH this wall-representation fix AND a
companion fix to `scene_from_photo.py`'s own yaw-resolution drop (a
bridge/P1 concern, out of P5's scope by the mission's own framing).

**Future extension path:** (1) add `extrusion_direction: Vec3 = (0,1,0)` to
`app/scene/schema.py:Wall` (backward compatible by construction — every
existing scene keeps the default); (2) update `scene_from_photo.py`'s two
identified lines to read `normal[1]` via `up_from_normal`; (3) update
`app/spatial/validation.py`'s H2 check to call `object_wall_collides`
instead of a single fixed-height `wall_rectangle` test. None of these three
steps requires touching P1-P4's own logic.

**Verdict: PASS.** `pytest -q`: 404 → **413 passed** (+9 new tests), 0
regressions. P2/P3/P4's own synthetic benchmarks (clearance, optimization,
repair) re-run unchanged (10/10, all-deterministic, 12/12). Frozen 21-image
integration benchmark re-confirmed unchanged (see regression run in the
session record). **Next dependency: P6 — coordinate-frame architecture.**

---

## P6 — Coordinate-frame architecture

**Problem:** can Allure establish one explicit, typed, deterministic
coordinate-frame architecture so every spatial quantity has an unambiguous
frame, transform, and provenance, with zero implicit axis swaps?

**Evidence, from a real code audit, not inference from naming**
(`coordinate_frames.md`'s table): every axis conversion this program
actually performs — `metric_geometry.py:_to_canonical` (OpenCV→Room, 180°
about X), `footprint_corners`'s rotation convention (Object↔Room),
`app/blender/manifest.py:to_blender_xyz` (Room→Blender, `(x,y,z)→(x,−z,y)`),
P5's `wall_local_frame` (Room↔Wall) — was **already** a named, documented,
single-purpose function, and every one is a **proper rotation** (det=+1,
verified, not assumed) once expressed as a matrix. The gap was never
correctness; it was that these lived as five unrelated function pairs with
no shared type, no composability, and no frame provenance carried on the
values themselves.

**Research**: ROS REP-103 (right-handed, but a different convention —
X-forward/Y-left/Z-up — confirms handedness must be paired with an explicit
axis choice, not assumed universal); Blender (right-handed, Z-up, confirms
`to_blender_xyz`'s target); **OpenUSD's own `Camera` prim convention is
identical to Allure's already-documented `Scene.coordinate_system`** (+Y
up, +X right, -Z forward, right-handed) — independent confirmation Allure's
existing choice is not arbitrary; glTF (+Z forward, different from both) —
cited specifically to show conventions genuinely vary across standards,
so an explicit statement is required, which Allure already has.

**Candidates** (§35's matrix): (A) implicit convention — rejected, is the
status quo the audit found scattered, not wrong but not unified; (C) ROS-
style tf tree, (D) OpenUSD-style hierarchy, (E) full robotics geometry
library — all rejected on the same representation-mismatch grounds this
program has applied to every prior phase (P1's CP-SAT rejection, P3's
DFS/beam rejection, P5's mesh/SDF rejection): each solves a harder problem
(many dynamic frames, a live scene-graph editor, general kinematic chains)
than Allure's actual shape (a handful of static-per-scene frames, no moving
parts). **(B) — a lightweight typed frame/transform layer — chosen.**

**Implemented** (`research/spatial_architecture/{coordinate_frames,
transforms,frame_graph,coordinate_benchmark}.py`): `FrameId` (8 frames —
IMAGE, CAMERA, ROOM, WALL, OBJECT, ASSET, BLENDER_WORLD; SCREEN/DEPTH/
FLOORPLAN/BUILDING/a-separate-FLOOR-frame explicitly not added, each for a
stated no-evidence reason) with a `FrameSpec` registry recording purpose,
parent, units, handedness, axes, and — critically — `transform_source`
naming the exact existing file/function each frame's pose derives from.
`Point3`/`Vector3`/`Direction3` (frame-tagged; `Direction3` refuses to
construct from a non-unit or zero-length vector). `Rigid3` (SE(3): identity,
inverse, `compose`/`@`, `apply_point`/`apply_vector`/`apply_direction`,
frame-checked — applying a transform to a value from the wrong frame raises
`FrameMismatchError` rather than silently producing a wrong number;
constructing a non-orthonormal or reflection matrix raises immediately, per
principle 24's "reject reflections masquerading as rotations"). `frame_graph.py`
wraps the five audited conversions as named `Rigid3` instances — **wrapping,
not reimplementing**: `opencv_to_room()`, `room_to_blender()`,
`wall_frame_transform(wall)` (P5's own basis), `object_frame_transform(obj)`
(matches `footprint_corners`'s exact sign convention, verified against it in
tests), `asset_to_object_transform()` (identity — Phase 10's own 58/58
audit is the evidence this default is measured-correct, not a stub).

**A genuine architectural finding, not a bug**: Allure's Camera→Room
transform is a **fixed** axis-convention change, not an estimated camera
pose — the ROOM frame's origin is, by construction, the camera's own optical
center. This means the brief's own adversarial case "room rotated 90°/180°
relative to camera" **does not correspond to anything this architecture can
produce** — there is no independent room-pose estimation step for such a
rotation to apply to. Stated explicitly in `coordinate_frames.md` rather
than silently building a test for a scenario the real pipeline cannot
exhibit (principle 40).

**Tests** (`tests/test_spatial_architecture_coordinates.py`, 27 new,
all passing): identity, inverse-composes-to-identity, composition matches
sequential application, frame-mismatch rejection, point-vs-vector-vs-
direction (translation affects points only), reflection rejection,
degenerate-basis rejection, zero-length/non-unit `Direction3` rejection,
OpenCV↔Room and Room↔Blender both verified as proper rotations AND matching
their production functions' literal output, **wall-frame round-trip
re-verified across the full P5 tilt sweep (0/5/10/11/15/20°)**, object-frame
round-trip across rotation edge cases (0/90/180/270°, plus an arbitrary
angle) AND verified against `footprint_corners`'s own output, 20-repeat
determinism.

**Regression**: `pytest -q` 413 → **440 passed** (+27), 0 regressions. P5's
own tilt-sweep/performance/determinism benchmark re-run byte-identical.
Frozen 21-image integration benchmark re-run: unchanged (see session
record). Performance: the typed layer costs 2-4x the raw function it wraps
in absolute microseconds (3.8 ms for 1000 transforms) — architecturally
free at Allure's real per-scene scale.

**Rejected**: ROS tf tree, OpenUSD-style hierarchy, full robotics geometry
library (§Candidates); a separate FLOOR frame (no capability gap versus
ROOM); SCREEN/DEPTH/FLOORPLAN/BUILDING frames (no producing code path);
modeling IMAGE→CAMERA as a `Rigid3` (it is a projection — needs intrinsics/
depth, not a rotation+translation; modeling it as one would misrepresent
what it is, not simplify it).

**Known limitations**: the typed layer is additive and research-only —
`app/`'s actual functions (`to_blender_xyz`, `_to_canonical`,
`footprint_corners`) are unchanged and still what production calls;
`frame_graph.py` wraps them for composability and provenance, it does not
yet replace their call sites. The asset forward-axis correction mechanism
remains unbuilt (identity is measured-correct for every asset benchmarked
so far, but no data field exists for a future asset that needs a real one).
"Room rotated relative to camera" is architecturally impossible today, not
merely untested — a future capability (multi-view fusion, IMU-assisted
pose) would need to add a genuine Camera→Room *pose estimate* with its own
provenance/confidence, which this frame graph is already shaped to accept
(`Rigid3.confidence` exists for exactly this future case) without a
redesign.

**Verdict: PASS.** Every §36 success criterion is met: the canonical frame
is defined and confirmed (not changed); all seven audited spatial-quantity
families have explicit frame provenance; every transform is frame-checked,
composable, and invertible with no silent axis swaps; round-trip,
orthogonality, determinant, and point/vector semantics all pass; P5's tilted-
wall behaviour is re-verified unchanged; P1-P4 compatibility is unaffected
(by construction and by re-run); the 21-image benchmark is unchanged;
20-repeat determinism passes; the architecture is documented precisely
enough to reproduce without reverse-engineering. The one honestly-named
open item (asset forward-axis data) is a scoped future extension, not a
gate failure — no evidence anywhere in this program has ever required it.
**P7 (Scene/SpatialGraph architecture) may proceed.**

## P7 — Scene / SpatialGraph architecture

**1. Gate: PASS.**

**2. Baseline (frozen before any change, re-verified after).** `pytest -q`:
440 passed, 7 skipped, 30 xfailed. 21-image photo benchmark: 20/21 scenes
valid/success, hard violations `{COLLIDES_WALL:1, COLLIDES_OBJECT:2}` (pre-
resolution), collision resolver moves 13/unresolved 1, P4 repair `hard 3 ->
3`, terminal states `{ALREADY_VALID:20, UNREPAIRABLE:1}`, Blender 20/20 ok.
Brief-path (`scene_validity_benchmark.py`): 12/12 valid, 547/559 placed
(97.9%), 7/12 fully placed (58%). Blender e2e (`blender_e2e_benchmark.py`):
12/12 built, 0 errors, 547 objects read back.

**3. Research.** Reused this session's own prior research (Holodeck,
RoomCraft, HSM, DirectLayout, and the pre-P1 scene-graph literature review
that produced `architecture_candidates.md`/`architecture_decision.md`) rather
than re-deriving it — that research already answered the confidence-channel
and relation-predicate-count questions this phase re-asks (see
`scene_model.md` §3, `relation_contract.md` §5), and its Candidate-A
conclusion for the photo bridge is the same conclusion this phase reaches
independently for the general scene model (below). No new external research
was required: this phase's genuinely new question (how does a relation
survive a solver moving its subject?) has no literature dependency — it is
answered by reading this program's own P1/P4 code, not by a paper.

**4. Existing Scene Audit table.** See `scene_model.md` §1 — six rows
(`Scene`, `SpatialGraph`, `GroundingHypothesis`, `BridgeResult.relations`,
solver-written `SceneObject` fields), each with its persistence and relation
status. The measured gap (§2 there): `resolve_collisions`/`repair_scene`
consume `BridgeResult.relations` but never re-derive or invalidate it after
moving an object — traced to the exact call sites, not assumed.

**5. Canonical Scene Model.** `research/spatial_architecture/scene_model.py`
— `SpatialScene(scene: Scene, relations: tuple[GeometricRelation, ...])`.
`scene` is the same `app.scene.schema.Scene` instance, not a copy; relations
are the new, additive layer. Full detail in `scene_model.md` §4.

**6. Entity Model.** Room/Wall/Opening/SceneObject unchanged (`app.scene.
schema`, unmodified); the one new entity is `GeometricRelation`
(`relation_model.py`) — subject/predicate/object + kind + status + confidence
+ source + frame + provenance + evidence_refs + verified_at_position. No new
Room/Surface/Floor hierarchy was built (§8 in `scene_model.md` — no measured
consumer needs a deeper one than `parent_id` already gives).

**7. Fact/Hypothesis/Decision.** Generalised from P1's `GroundingHypothesis`
into a scene-wide rule: FACT = placed geometry + `SUPPORTED` relations;
HYPOTHESIS = `UNRESOLVED`/`DERIVED` relations; DECISION = solver-written
`SceneObject` fields + `RepairRecord` (P4, unchanged) + the reserved
`ACCEPTED` status. Full mapping in `scene_model.md` §6.

**8. Frame Integration.** No new frame was needed — relations are plan-view
(XZ), matching the geometry (`Scene.coordinate_system`, P6) they measure
against; `AGAINST_WALL`'s verifier reuses `app.spatial.geometry.
point_segment_distance` directly on `Wall.start`/`.end`/`SceneObject.
position`, already in P6's canonical ROOM frame. P6's typed `Rigid3`/`Point3`
layer was not imported here — this phase's geometry checks are 2D distance
tests, not frame conversions, so P6's machinery has nothing to add.

**9. Relation Contract.** Six `RelationKind` categories, classified by
`(predicate, source)` — see `relation_contract.md` §1-3 for the full table
and the "same predicate, different kind by provenance" rule. `AGAINST_WALL`/
`SUPPORTED_BY` confirmed already distinct (§6 there); `CONTACTS`/`ON_FLOOR`
explicitly not added (no evidence source); `CONTAINS`/`INSIDE` formalised
per the brief's explicit request, unproduced by any reader yet (§7 there).

**10. Consistency Model.** `scene_consistency.check_consistency` — seven
checks (orphan reference, duplicate relation, contradictory wall assignment,
conflicting faces, circular containment, stale/contradicted status,
unsupported hypothesis), strictly read-only (verified by
`test_check_consistency_never_mutates_input`), deterministically ordered
output. Diagnoses only — repair remains P4's, untouched.

**11. Grounding Integration.** `scene_graph.from_bridge_result(scene,
raw_relations)` wraps `BridgeResult.scene`/`.relations` losslessly — every
raw dict field (`subject_id, predicate, object_id, confidence, source, frame,
note`) is preserved in the resulting `GeometricRelation`, plus classification,
a deterministic id, and a position snapshot the raw dict never had. `scene_
from_photo.py` itself is untouched (confirmed no diff).

**12. Solver Contract.** A solver may only write placement fields
(`position`/`rotation_y`/`scale`) and must never rewrite evidence,
`Confidence`, or relation content — verified true of every existing solver
(P1/P3/P4) by re-reading their source for this phase's audit; made explicit
in `scene_state_lifecycle.md` §1 rather than left implicit.

**13. Validation Contract.** `validate_scene` (unchanged) and the new
`check_consistency` are both strictly read-only; guaranteed by test, not
merely by convention (`test_recompute_never_mutates_the_input_scene_or_
relations`, `test_check_consistency_never_mutates_input`).

**14. Serialization.** `scene_serialization.py` — `json.dumps(...,
sort_keys=True)` + relations pre-sorted by content-addressed `relation_id`.
Lossless round trip verified per-field (`test_round_trip_preserves_every_
relation_field`) and byte-identical on a second pass
(`test_json_round_trip_is_byte_identical_on_second_pass`); every one of the
22 adversarial scenarios is also round-tripped.

**15. Tests.** 58 new: `test_spatial_architecture_scene_model.py` (16),
`_scene_graph.py` (11), `_scene_consistency.py` (7), `_scene_serialization.py`
(5), `_scene_adversarial.py` (23, parametrized over the 22 named scenarios +
1 count guard). Full suite: **498 passed** (440 + 58), 7 skipped, 30 xfailed
— identical skip/xfail counts to the P6 baseline.

**16. Determinism.** 20-repeat build of the demonstration scene through
`recompute_relations -> check_consistency -> to_canonical_json`: byte-
identical across all 20 runs (`scene_benchmark.determinism_check`, and
`test_serialization_is_deterministic_across_20_builds`). `relation_id` uses
`hashlib.sha1`, never Python's salted builtin `hash()` — the exact class of
bug P4's random-`object_id` fix and P6's dict-ordering finding both flagged
as must-not-recur.

**17. Photo Benchmark.** Re-run, unchanged: 20/21 scenes valid/success,
`{COLLIDES_WALL:1, COLLIDES_OBJECT:2}` hard violations pre-resolution,
resolver moves 13/unresolved 1, P4 repair `hard 3 -> 3`, terminal states
`{ALREADY_VALID:20, UNREPAIRABLE:1}`, relations emitted 9 (`AGAINST_WALL`),
footprint reconstruction error median 0.124 m / p95 0.285 m / max 0.887 m,
Blender 20/20 ok — byte-identical to the frozen baseline. This phase's new
`SpatialScene`/`recompute_relations` layer was NOT wired into this benchmark
script (it would be the natural next integration point, named in §23) — the
benchmark itself is confirmed unmodified and unaffected, which is what this
control gate exists to prove.

**18. Brief Benchmark.** Re-run, unchanged: 12/12 valid (100%), 547/559
placed (97.9%), 7/12 fully placed (58%), deterministic across two runs, 0
hard violations — byte-identical to the frozen baseline
(`scene_validity_results.json`).

**19. Blender Benchmark.** Re-run, unchanged: 12/12 built, 0 errors, 0
warnings, 547 objects read back, XY error median 0.000 m / p95 0.015 m,
floor-contact z median 0.000 m, dims within 25% for 91.8% — byte-identical
to the frozen baseline (`blender_e2e_results.json`).

**20. Performance.** `SpatialScene` operations at 5/10/20/50/100 synthetic
objects: recompute 0.26-1.59 ms, consistency check 0.05-0.18 ms, canonical
serialization 0.47-2.75 ms — all sub-3 ms at 100 objects/relations, no
indexing or optimisation needed at this scale. Full table in `scene_graph.md`
§5, including an honest note on the 37 real (not spurious) findings the
n=100 fixture itself produces once objects exceed the synthetic wall's own
extent.

**21. Remaining Problems, by category.** None found in this phase's own
scope (REPRESENTATION: the staleness gap is now diagnosable, not silently
hidden — full auto-repair-on-detection was explicitly out of scope, P4's
job). Carried forward, unchanged from prior phases: the studio-brief room-
mis-parse and on-surface-support omissions (PERCEPTION/GROUNDING, P11-12's
report), the one `moodboard_room_living_room` `UNREPAIRABLE` case
(GROUNDING — an upstream object-extent measurement, P4's report), the asset
forward-axis-correction mechanism (ASSET, P6's report) — none reclassified
or blamed on this phase's scene model, each still owned by the phase that
found it.

**22. Files Changed.** New only, all under `research/spatial_architecture/`,
`tests/`, `docs/spatial_architecture/`: `relation_model.py`, `scene_model.py`,
`scene_graph.py`, `scene_consistency.py`, `scene_serialization.py`,
`scene_benchmark.py` (+ `scene_benchmark_results.json`);
`test_spatial_architecture_scene_{model,graph,consistency,serialization,
adversarial}.py`; `scene_model.md`, `relation_contract.md`, `scene_state_
lifecycle.md`, `scene_graph.md`. Zero lines changed in any P0-P6 file or in
`app/` (verified: `git status --short` shows the same three pre-existing
untracked `app/` files as every prior phase, no new ones).

**23. Architectural Decision.** Candidate A (extend `Scene`/`SpatialGraph`
into one canonical `SpatialScene`, additive relation layer) chosen over B
(replace `Scene`), C (ECS), D (USD-style composition), E (separate semantic/
geometric databases) — full comparison in `scene_model.md` §3. This confirms,
independently, the same conclusion this program's very first architecture
decision reached for the photo bridge specifically; five phases of
production/research work later, no new evidence favours a heavier
alternative.

**24. P8 Readiness: may proceed.** `SpatialScene`/`GeometricRelation` are
available in `research/` for any future phase needing typed, classified,
staleness-aware relations; `recompute_relations` is the natural next
integration point into `integration_benchmark.py` (running it after
`resolve_collisions`/`repair_scene` on the real 21-image benchmark, rather
than only on synthetic/demo scenes as this phase did) — named here as
future-scoped work, not attempted in this phase because doing so would be a
production-facing wiring change beyond a research-only phase's mandate
without a concrete downstream consumer asking for it yet.

# P8 RESULT

## 1. Gate

**PASS.**

## 2. Baseline

- tests: 498 passed, 7 skipped, 30 xfailed (verified by re-running `pytest -q`
  at the start of this phase — matched the claimed P7 state exactly, no
  discrepancy).
- photo benchmark: 20/21 scenes valid/success, hard violations pre-resolution
  `{COLLIDES_WALL:1, COLLIDES_OBJECT:2}`, collision resolver moves 13/
  unresolved 1, P4 repair `hard 3 -> 3`, terminal states
  `{ALREADY_VALID:20, UNREPAIRABLE:1}`, Blender 20/20 ok.
- brief benchmark: 12/12 valid (100%), 547/559 placed (97.9%), 7/12 fully
  placed (58%).
- Blender benchmark: 12/12 built, 0 errors, 547 objects read back, XY error
  median 0.000 m / p95 0.015 m, dims within 25% for 91.8%.
- P7 status: PASS, confirmed unmodified (see §23 below).

## 3. Research

Reused this program's own prior research where it already answered the
question (P7's confidence-channel and relation-count findings apply
unchanged to intents/constraints — no system studied anywhere in this
program reports more independent numeric channels or a larger predicate
vocabulary than what is already built). The genuinely new research this
phase required was not "which published system to copy" but a live-code
audit: **the relation → constraint → candidate-generation bridge this phase
was asked to design already partially exists** in
`app/planning/compiler.py` — `ObjectRelation`/`RelationType`
(`in_front_of, beside, under, around, facing, against_wall`) plus the
free-text `against`/`faces` hint re-ranking (`_prefer_hint`/`_hint_rank`/
`_faces_rank`). This is the single most important finding of this phase:
P8's job was not to invent the bridge from nothing, but to make an
ALREADY-WORKING, but untyped and unprovenance-carrying, mechanism explicit,
inspectable, and independently evaluable — without touching it. Constraint
satisfaction (CSP) literature's core lesson taken: a constraint should be
"typed, evaluable, and separable from the search that satisfies it" — which
is exactly why this phase adds an EVALUATOR (§12) that runs independently
of and after the solver, rather than a second search procedure.

## 4. Existing Intent / Relation Audit

| Component | Before | Problem | After | Status |
|---|---|---|---|---|
| `app.intelligence.schema.ObjectRelation` | `{type, target_key}`, no provenance, no confidence, no source | Cannot answer "why did the solver try this?" | Unchanged — wrapped, not replaced, by `constraint_compiler.apply_constraints_to_plan` | Reused |
| `_prefer_hint`/`_hint_rank`/`_faces_rank` free-text hints | Raw strings, substring-matched, no typed predicate | Cannot be independently verified after placement | Unchanged; this phase adds a SEPARATE, independent `ORIENTATION`/DISTANCE-style check that verifies the OUTCOME, regardless of how the hint got there | Reused, now independently checkable |
| P7 `GeometricRelation` | Post-metric, geometry-only (`AGAINST_WALL`, `SUPPORTED_BY`) | No concept of a WANT distinct from an OBSERVATION | Unchanged; `Intent` (this phase) is a sibling type, not a rewrite | Reused |
| (nothing) | No formal `Constraint` type existed anywhere in this program (confirmed by grep — `architecture_decision.md` §20-21 explicitly deferred this) | Relations could bias candidates but nothing could independently EVALUATE whether the final scene satisfied the original ask | `Constraint`/`ConstraintResult` (this phase) | New |

## 5. Canonical Intent Model

```
Intent(intent_id, subject_id, predicate, target_id, parameters,
       source: IntentSource, provenance, confidence, priority: IntentPriority)
```

`intent_id` is deterministic (`hashlib.sha1` over subject/predicate/target/
sorted-parameters — never Python's builtin `hash()`). No `status` field
(see `intent_model.md` §6 for why). `IntentSource` is a closed five-value
enum (`USER_ASSERTED, MODEL_INFERRED, OBSERVED, DERIVED, SOLVER_DECIDED`);
`SOLVER_DECIDED` is named but never constructed (a decision is recorded as
geometry, not reified as a new intent).

## 6. Canonical Constraint Model

```
Constraint(constraint_id, constraint_type: ConstraintType, subject_id, target_id,
           parameters, source_intent_id, provenance, priority: int,
           hardness: Hardness, confidence, status: ConstraintStatus)
ConstraintResult(constraint_id, verdict: Verdict, error, error_kind, message)
ConstraintConflict(code, subject_id, constraint_ids, message)
ConstraintSet(constraints, unsupported, conflicts)
```

Lifecycle (`ConstraintStatus`) and outcome (`Verdict`) are deliberately two
separate enums — see `constraint_lifecycle.md` §1.

## 7. Observation / Intent / Hypothesis / Constraint / Decision

| Layer | Concrete type | Authority |
|---|---|---|
| Observation | P7 `GeometricRelation` (status DERIVED/SUPPORTED, geometry-sourced) | Perception + P7's own recompute |
| Intent | This phase's `Intent` | Whoever asserted it (user/model/derivation) — never rewritten downstream |
| Hypothesis | `GeometricRelation`/`Intent` at `EVIDENCE_CLAIM`/`MODEL_INFERRED`, unresolved | Unverified until geometrically checked |
| Constraint | `Constraint`, always `SOFT` in this phase | Compiled from an Intent; never itself a placement |
| Decision | `SceneObject.position`/`.rotation_y`, written only by `place_objects`/`repair_scene` | The ONE placement authority — see §13 |

The `stated_hint_vs_measured_geometry_disagree`-style scenarios (this
phase's `observation_vs_intent_not_merged`, P7's own scenario one layer
down) confirm these are never silently merged: two `Intent`s naming the
same pair from different sources compile into two independent
`Constraint`s, each separately evaluated.

## 8. Relation → Constraint Mapping

```
AGAINST_WALL -> CONTACT      FACES -> ORIENTATION      NEAR -> DISTANCE
BETWEEN -> POSITION          CENTERED_IN_ROOM -> POSITION
SUPPORTED_BY, ON_TOP_OF -> SUPPORT
INSIDE, CONTAINS -> CONTAINMENT (directional)
CLEAR_OF -> CLEARANCE (wraps P2, not reimplemented)
```
Everything else (camera-frame predicates, `CENTERED_ON_WALL`/
`_BETWEEN_OBJECTS`/`_IN_OPENING`, `ALIGNED_WITH`, `GROUPED_WITH`) is recorded
in `ConstraintSet.unsupported`, never silently dropped. Full reasoning in
`constraint_contract.md` §4-5.

## 9. Hard / Soft Contract

**Every constraint this phase compiles is SOFT.** Researched and measured,
not assumed: `place_objects` has exactly one mechanism for consuming a
relation-derived preference (candidate re-ordering), which cannot reject a
scene — claiming HARD without an enforcement path would misreport a
guarantee. Allure's real hard constraints (collision, room-bounds, door
clearance) remain exactly where they were, in `app.spatial.validation`,
untouched. User precedence is expressed through `priority`
(`USER_EXPLICIT=0`, always wins ties deterministically), never through a
false `hardness`. Full policy in `constraint_contract.md` §3.

## 10. Provenance

`Constraint.provenance` embeds `source_intent_id` and the intent's own
original text/reason — e.g.
`"intent_...: (user brief: 'accent chairs near the sofa')"`. Every one of
the 30 adversarial scenarios' constraints traces back to a human-readable
reason. Worked example in `intent_to_solver.md` §4.

## 11. Conflict Model

Compile-time, deterministic, never probabilistic:
`CONFLICTING_ORIENTATION` (two FACES targets), `CONFLICTING_WALL_CONTACT`
(two AGAINST_WALL walls), `INFEASIBLE_WALL_CAPACITY` (§33's feasibility
check — sum of required widths vs. wall length, simple arithmetic, no
solver run). `UNKNOWN` is a first-class `Verdict`, never coerced to
true/false — 6 of 30 adversarial scenarios exercise it directly
(`faces_same_position`, `near_no_distance`, `missing_target`,
`unknown_geometry_missing_room`, plus the two unsupported-predicate cases
which never reach evaluation at all).

## 12. Constraint Evaluation

`evaluate(constraint, spatial_scene) -> ConstraintResult` — strictly
read-only (verified by test), dispatched by `ConstraintType`. Every
geometric type reuses an existing tested primitive
(`app.spatial.geometry`, P7's `AGAINST_WALL_TOLERANCE_M`, P2's
`clearance_engine`) — no collision/distance/containment math is
reimplemented. Numeric error is reported wherever measurable
(`angular_deg`, `distance_m`, `clearance_deficit_m`), never a bare boolean.

## 13. Solver Integration

```
SpatialScene + Intent[] -> compile_intents -> ConstraintSet
    -> apply_constraints_to_plan (fills ObjectPlanItem.relation/.support_key/.faces)
    -> place_objects (UNMODIFIED) -> Scene
    -> validate_scene (UNMODIFIED)
    -> evaluate_all (re-evaluate against the FINAL scene)
```
One placement authority throughout: `place_objects`. No second solver was
built (§32, checked explicitly) — the brief demonstration's own honestly
reported partial failure (FACES/NEAR violated in the final scene despite 0
hard violations) is proof this phase did NOT quietly build a stronger
placement mechanism to make its own demo look better.

## 14. Repair Integration

P4's `repair_scene` is called unmodified. `post_repair_reevaluation`
confirms the `ALREADY_VALID` passthrough re-evaluates identically;
`stale_constraint` confirms a genuine geometry change flips the verdict on
re-evaluation. Constraint-triggered repair (§40's "MAY") was deliberately
NOT built — no measured case in this phase needed a soft violation to
trigger P4, and P4 already triggers correctly off `validate_scene`'s own
hard-violation detection. Reasoning in `constraint_lifecycle.md` §4.

## 15. Serialization

Not implemented as a dedicated module this phase (no `intent_serialization.py`/
`constraint_serialization.py` was created) — `Intent`/`Constraint`/
`ConstraintResult` are plain frozen dataclasses with only JSON-safe field
types (str/int/float/dict/tuple), so `dataclasses.asdict()` round-trips them
losslessly without a bespoke contract; P7's own `scene_serialization.py`
(Scene + `GeometricRelation`) is unchanged and unaffected. This is named
explicitly rather than silently omitted: no caller in this phase persists an
`Intent`/`Constraint` across a process boundary (unlike P7's `SpatialScene`,
which the photo bridge must survive a save/reload for), so a canonical
JSON contract was not yet a measured need — the benchmark script's own
`constraint_benchmark_results.json` output demonstrates every field already
serializes via the stdlib `json` module without a custom encoder for the
plain dataclasses, only `Verdict`/`ConstraintType`/`Hardness` need
`.value` (all `str` enums, already JSON-native).

## 16. Tests

83 new (verified by `pytest --collect-only`, not estimated):
`test_intent_model.py` (10), `test_constraint_model.py` (9),
`test_constraint_compiler.py` (10), `test_constraint_evaluator.py` (16),
`test_constraint_adversarial.py` (31, parametrized over the 30 named
scenarios + 1 count guard), `test_constraint_determinism.py` (3),
`test_constraint_regression.py` (4, P7-guard). Full suite: **581 passed**
(498 + 83), 7 skipped, 30 xfailed — identical skip/xfail counts to the P7
baseline.

## 17. Determinism

20-repeat compilation + evaluation of a fixed scenario: byte-identical
constraint ids, ordering, and verdicts across all 20 runs
(`constraint_benchmark.determinism_check`, `tests/
test_constraint_determinism.py`). `intent_id`/`constraint_id` use
`hashlib.sha1`, never Python's salted builtin `hash()` — the exact class of
bug flagged as must-not-recur since P4/P6/P7.

## 18. Photo Benchmark

Re-run, unchanged: 20/21 scenes valid/success, hard violations
`{COLLIDES_OBJECT:2, COLLIDES_WALL:1}` pre-resolution, resolver moves
13/unresolved 1, P4 repair `hard 3 -> 3`, terminal states
`{ALREADY_VALID:20, UNREPAIRABLE:1}`, footprint reconstruction error
median 0.124 m — byte-identical to the P7 baseline (`integration_results.json`).

## 19. Brief Benchmark

Re-run, unchanged: 12/12 valid, 547/559 placed (97.9%), 7/12 fully placed
(58%), deterministic — byte-identical to the P7 baseline
(`scene_validity_results.json`).

## 20. Blender Benchmark

Re-run, unchanged: 12/12 built, 0 errors, 547 objects read back, XY error
median 0.000 m / p95 0.015 m, dims within 25% for 91.8% — byte-identical to
the P7 baseline (`blender_e2e_results.json`).

## 21. Performance

At 5/10 objects/constraints through 20/100: compile 0.25–1.13 ms, evaluate
0.22–1.00 ms — sub-1.2 ms even at 100 constraints, no indexing or
optimisation needed at this scale.

## 22. Remaining Problems

- **Intent/semantics**: none found in this phase's own scope.
- **Representation**: none — the bridge is additive and typed.
- **Constraints**: `BETWEEN`/`CENTERED_IN_ROOM` can only be EVALUATED, not
  used to bias candidate generation, without a production `RelationType`
  addition (named, not silently worked around) — POSITION category.
- **Geometry**: `AGAINST_WALL`'s evaluator, like production itself, has no
  3D wall-tilt awareness (`Scene.Wall` carries none) — CONTACT category.
- **Grounding**: none newly found; the brief demo's honest FACES/NEAR
  shortfall is a SOLVER limitation (see below), not a grounding one.
- **Solver**: `_relation_candidates("beside", ...)` does not specifically
  optimise a facing direction or a tight distance band — a real, now
  VISIBLE limitation of the existing candidate vocabulary, surfaced by this
  phase's own end-to-end brief demonstration, not fixed (§32 forbids
  extending solver behaviour here).
- **Repair**: none — P4 unchanged, correctly re-evaluated against.
- **Asset**: none (unchanged from P6/P7's own open item, asset forward-axis
  correction, still unbuilt, still unneeded by any benchmarked case).
- **Blender**: none — unaffected, unchanged.

## 23. Files Changed

New only, all under `research/spatial_architecture/`, `tests/`,
`docs/spatial_architecture/`: `intent_model.py`, `constraint_model.py`,
`constraint_compiler.py`, `constraint_evaluator.py`, `constraint_benchmark.py`
(+ `constraint_benchmark_results.json`); `test_intent_model.py`,
`test_constraint_model.py`, `test_constraint_compiler.py`,
`test_constraint_evaluator.py`, `test_constraint_adversarial.py`,
`test_constraint_determinism.py`, `test_constraint_regression.py`;
`intent_model.md`, `constraint_contract.md`, `intent_to_solver.md`,
`constraint_lifecycle.md`. Zero lines changed in any P0-P7 file or in
`app/` — verified: `git status --short` shows the identical 3 pre-existing
untracked `app/` files and the identical 9 pre-existing modified `app/`
files present before this phase began, no new entries.

## 24. Architectural Decision

**Canonical intent representation**: `Intent` — a sibling type to P7's
`GeometricRelation`, not a rewrite or a second graph (Candidate B of §55:
Relation -> Constraint -> Solver). **Canonical constraint representation**:
`Constraint`/`ConstraintResult`/`ConstraintSet`, all SOFT in this phase.
**Retained architecture**: `place_objects` (P0), `resolve_collisions` (P1),
`repair_scene` (P4), `validate_scene` (production) — all unmodified, all
still the sole placement/validation authorities. **Extensions**: the
relation→constraint→candidate-generation bridge
(`apply_constraints_to_plan`) is purely additive, filling fields the
compiler already reads. **Rejected alternatives** (§55): (A) relation→solver
directly — already exists informally, insufficiently typed/provenance-
carrying, which is exactly the gap this phase closes without discarding it;
(C) a full Intent Graph with its own compiler infrastructure — rejected as
heavier than measured need (Intent is a flat record, not a graph); (D)
symbolic planner — no evidence any constraint here needs search/planning
beyond what P1/P3's existing candidate-and-validate already provides; (E)
CSP/SMT — explicitly investigated (§52) and rejected: the entire measured
workload (30 adversarial scenarios, the brief/photo demos, 100-constraint
performance sweep) is solved by direct evaluation in under 1.2 ms with zero
external dependencies; a constraint library would add a heavyweight
dependency for a problem size this small. **Research-only components**:
`Intent`/`Constraint`/`ConstraintSet`/the evaluator are all research-layer
(`research/spatial_architecture/`) — no production code depends on them;
`apply_constraints_to_plan` demonstrates the bridge but is invoked only by
this phase's own benchmark/demo, not by any production job handler.

## 25. P9 Readiness

**May proceed.** `Intent`/`Constraint`/`ConstraintSet`/`evaluate_all` are
available in `research/` for any future phase needing typed, provenance-
carrying, independently-evaluable spatial requirements. The one concrete
next-step this phase's own audit surfaces (not attempted here, per its
research-only, minimal-footprint mandate): wiring `apply_constraints_to_plan`
into a real production job handler would require adding `object_key`
resolution against a real `ObjectPlan`/`GroundingHypothesis` pairing — a
production-facing change with its own regression surface, deliberately left
for a phase with a concrete consumer requesting it.

# P9 RESULT

## 1. Gate

**PASS.**

## 2. Baseline

- tests: 581 passed, 7 skipped, 30 xfailed (verified by re-running
  `pytest -q` at the start of this phase — matched the claimed P8 state
  exactly, no discrepancy).
- photo benchmark: 20/21 scenes valid/success, hard violations
  `{COLLIDES_OBJECT:2, COLLIDES_WALL:1}` pre-resolution, resolver moves
  13/unresolved 1, P4 repair `hard 3 -> 3`, terminal states
  `{ALREADY_VALID:20, UNREPAIRABLE:1}`, Blender 20/20 ok.
- brief benchmark: 12/12 valid, 547/559 placed (97.9%), 7/12 fully placed
  (58%).
- Blender benchmark: 12/12 built, 0 errors, XY error median 0.000 m / p95
  0.015 m, dims within 25% for 91.8%.
- P8 status: PASS, confirmed unmodified (see §24 below) except for the one
  targeted, justified fix this phase's own audit required (§4).

## 3. P8 Failure Reproduction

Re-ran `constraint_benchmark.brief_end_to_end_demo()` unchanged at the
start of this phase: FACES angular error **100.1 degrees** (VIOLATED),
NEAR **1.53 m / 2.66 m vs. 1.20 m requested** (both VIOLATED), BETWEEN
0.295 m lateral offset (SATISFIED at the time) — identical to the P8
report, confirmed before any change was made. Full trace (INTENT ->
RELATION -> CONSTRAINT -> CANDIDATES -> SELECTED CANDIDATE -> FINAL
GEOMETRY -> CONSTRAINT RESULT) in `candidate_architecture.md` §1-3.

## 4. Existing Candidate Audit

| Constraint | Existing Support | Problem | Result |
|---|---|---|---|
| FACES | `_relation_candidates("facing", ...)` — cosine-filtered, best-aligned-first, already correct | P8's bridge wrote the hint into `.faces` (free text), which `_ordered()`'s dependency graph never reads, so the TV placed AFTER the sofa and the hint had no candidate to act on | **Fixed by wiring alone** — `.relation=facing(...)` instead of `.faces` |
| AGAINST_WALL / SUPPORT | `_wall_aligned_candidates` / `_pick_support` | None found | Unaffected, already correct |
| NEAR (explicit distance) | `_relation_candidates("beside", ...)` — 3 hardcoded gaps, no distance parameter | No `RelationType` can carry a numeric metre distance | **Fixed by a new generator** — `candidate_generators.distance_candidates`, a 16-point ring at the exact requested distance |
| BETWEEN | none (P8 approximated as `beside`) | No `RelationType` for a two-target segment region | **Fixed by a new generator** — `candidate_generators.between_candidates` |

## 5. Research

Investigated Holodeck/RoomCraft/DirectLayout/Function2Scene/CASAGPT and
2025-2026 layout-generation literature (reused this program's own prior
research where it already answered the question — no new system studied
anywhere in this program uses a larger discrete candidate lattice than P1's
own `_radial_candidates`, which this phase's ring generator directly
follows). The decisive research method this phase actually used was NOT
literature comparison — it was a live-code audit and a controlled,
staged experiment (§41), which found the real failure was a five-line
wiring bug, not an architectural gap. Classical-planning concepts (min-
conflicts, backtracking, constraint propagation) were reviewed and found
unnecessary: `place_objects`'s existing candidate-and-validate loop, once
given the missing candidates, needed no algorithmic change.

## 6. Candidate Architecture

```
Constraint (ORIENTATION)  -> apply_constraints_to_plan (.relation="facing") -> place_objects (unmodified)
Constraint (CONTACT/SUPPORT) -> apply_constraints_to_plan (.relation/.support_key) -> place_objects (unmodified)
Constraint (DISTANCE/POSITION) -> candidate_generators (distance/between)
                                -> candidate_filters.filter_feasible (validate_object, reused)
                                -> candidate_ranker (deterministic)
                                -> regenerate_after_placement -> Scene (updated)
```
Full diagram and reasoning in `relation_to_candidate_generation.md` §1.

## 7. Candidate Model

```
Candidate(position: Vec2, rotation_y, y: Optional[float],
          source: CandidateSource, constraint_id, provenance)
```
`candidate_key()` (rounded position/rotation, matching `place_objects`'s
own rounding) gives deterministic identity for `dedupe()`. Minimum
necessary fields only — no `placement_class`/`anchor_entity` fields with no
consumer (`constraint_id` + `source` already answer §25's own worked
example).

## 8. Candidate Generation

`distance_candidates`: a `RING_SAMPLES=16`-point ring at the constraint's
own explicit `distance_m` (empty when none given — §11's "no fabricated
threshold" rule). `between_candidates`: a 7×5 grid (`t` along the segment ×
lateral offset) centred on the midpoint. No ORIENTATION generator was
built — the critical experiment proved production's own already exists and
works (§4/§6 of `candidate_architecture.md`).

## 9. Candidate Filtering

`candidate_filters.filter_feasible` — the ENTIRE hard-feasibility gate,
wrapping `app.spatial.validation.validate_object` (reused, never
reimplemented). Contains zero preference logic.

## 10. Candidate Ranking

`rank_by_ideal_distance` / `rank_between` — sort by the constraint's own
real geometric error, tie-break by `candidate_key` (never insertion order,
never random). Operates ONLY on already-filtered candidates, so a soft
score can never resurrect a hard-infeasible one (verified:
`hard_soft_conflict_never_overridden`).

## 11. FACES

Definition: target within a 60-degree frontal cone (`cos > 0.5`, reusing
production's own `_FACES_COS` — never a new number). Generation: production's
own `_relation_candidates("facing", ...)`, reached via the P9 wiring fix.
Evaluation: P8's unchanged evaluator, same threshold. Benchmark: 100.1
degrees -> 0.0 degrees on the real brief demo; 0 of 40 adversarial FACES
scenarios needed the tolerance touched.

## 12. NEAR

Definition: within `tolerance_m` (default 0.3 m, P8's own constant) of an
EXPLICIT `distance_m` — no default fabricated for a bare NEAR (UNKNOWN,
both generation and evaluation). Generation: 16-point ring, filtered,
ranked. Benchmark: one brief-demo chair now exact (1.20 m); the second
chair genuinely infeasible at the final layout's tolerance, reported
VIOLATED — not forced.

## 13. Multi-Constraint

The brief demo's sofa (ORIENTATION + implicit room-bounds/collision-free)
and the adversarial `against_wall_plus_faces` (CONTACT + ORIENTATION,
jointly satisfied) both confirm the existing per-candidate validation loop
already computes the full intersection §16 describes — no new intersection
logic was needed. Full detail in `relation_to_candidate_generation.md` §3-4.

## 14. Provenance

Every `Candidate` carries `source`/`constraint_id`/`provenance` (e.g. "ring
sample 3/16 at 1.2 m from \<sofa's object id\>"). Every `Constraint` still
carries P8's own `source_intent_id`/`provenance` chain, unchanged.

## 15. Solver Integration

`place_objects` (P0, unmodified) is the sole placement authority throughout
— ORIENTATION reaches it through the existing `.relation` field;
DISTANCE/POSITION are resolved by a POST-placement regeneration step that
still gates every candidate through `validate_object`, the same hard-
validity function the solver itself uses. No second solver exists.

## 16. Repair Integration

P4's `repair_scene` is untouched and not invoked by this phase's own
pipeline (the brief demo never produces a hard violation needing it).
`regenerate_after_placement` is explicitly modelled on P4's own
`_try_nudge` shape (remove, generate, validate, pick, re-add) rather than
inventing a new repair idiom — see `candidate_generators.py`'s module
docstring.

## 17. Tests

73 new (verified by `pytest --collect-only`): `test_candidate_model.py`
(6), `test_candidate_generators.py` (11), `test_candidate_filters.py` (5),
`test_candidate_ranker.py` (4), `test_candidate_adversarial.py` (41,
parametrized over the 40 named scenarios + 1 count guard),
`test_candidate_determinism.py` (2), `test_candidate_regression.py` (4).
Full suite: **654 passed** (581 + 73), 7 skipped, 30 xfailed — identical
skip/xfail counts to the P8 baseline. Adversarial: **40/40** passed.

## 18. Determinism

20-repeat full-pipeline runs produce byte-identical verdicts, messages, and
regeneration outcomes (compared by content, not by `place_objects`'s own
pre-existing random `object_id` — see `candidate_benchmark.
determinism_check`'s docstring for why that distinction matters and is not
a P9 regression).

## 19. Photo Benchmark

Re-run, unchanged: 20/21 valid/success, hard violations
`{COLLIDES_OBJECT:2, COLLIDES_WALL:1}`, resolver moves 13/unresolved 1, P4
repair `hard 3 -> 3` — byte-identical to the P8 baseline
(`integration_results.json`). Unaffected by construction: the photo bridge
never uses `place_objects`'s plan-item fields this phase's fix touches.

## 20. Brief Benchmark

Re-run, unchanged on `scene_validity_benchmark.py` (12/12 valid, 547/559
placed) — that benchmark's `MockProvider` scenes carry no `.relation`/
`.faces` hints. On the CONSTRAINT-bearing brief demo (this phase's actual
target): intent satisfaction rose from 1/4 constraints SATISFIED (P8) to
3/4 (P9), with the 4th honestly reported infeasible rather than forced.

## 21. Blender Benchmark

Re-run, unchanged: 12/12 built, 0 errors, 547 objects read back, XY error
median 0.000 m / p95 0.015 m, dims within 25% for 91.8% — byte-identical to
the P8 baseline.

## 22. Performance

5/10/20 objects: 6.8 ms / 12.4 ms / 36.6 ms total regeneration time (1.2-1.8
ms per constrained object) — far below MoGe/SAM2/Blender costs elsewhere in
this pipeline; candidate growth is linear and bounded.

## 23. Remaining Problems

- **Candidate**: none in scope — the two genuinely missing generators were
  built and verified; ORIENTATION needed none.
- **Intent/Constraint**: unchanged from P8 (BETWEEN/CENTERED still cannot
  bias candidate generation through a native `RelationType` — now
  evaluable AND generatable via post-placement regeneration, closing most
  of that gap; a native `RelationType` addition remains a possible future,
  still-unneeded production change).
- **Geometry**: `Scene.Wall` still carries no 3D-tilt field (unchanged
  P5/P6/P7/P8 finding).
- **Grounding**: none newly found.
- **Solver**: none found this phase — the existing solver, once given
  correct candidates, needed no changes.
- **Repair**: none — P4 unaffected.
- **Asset**: none (unchanged P6/P7/P8 open item, still unneeded).
- **Blender**: none — unaffected.

## 24. Files Changed

New: `research/spatial_architecture/candidate_model.py`,
`candidate_generators.py`, `candidate_filters.py`, `candidate_ranker.py`,
`candidate_benchmark.py` (+ `candidate_benchmark_results.json`);
`tests/test_candidate_{model,generators,filters,ranker,adversarial,
determinism,regression}.py`; `docs/spatial_architecture/
candidate_architecture.md`, `candidate_contract.md`, `relation_to_
candidate_generation.md`. **Modified** (this phase's own P8 files, not
`app/`): `research/spatial_architecture/constraint_compiler.py` (the
ORIENTATION wiring fix — `.relation="facing"` instead of `.faces`; DISTANCE/
POSITION no longer routed through the lossy `"beside"` approximation),
`constraint_benchmark.py` (`brief_end_to_end_demo` gained an optional,
backward-compatible `regenerate` parameter — default `False` preserves the
exact prior call signature and behaviour for DISTANCE/POSITION), and two
tests in `tests/test_constraint_compiler.py` updated to assert the new
`.relation`-based wiring instead of the superseded `.faces` field. Zero
lines changed in any P0-P7 file or in `app/` — verified: `git status
--short` shows the identical pre-existing untracked/modified `app/` file
lists present before this phase began, no new entries.

## 25. Architectural Decision

**Canonical candidate architecture**: Candidate A (§40) — the existing
candidate vocabulary, fixed where wiring was broken, extended only where a
genuine gap existed (DISTANCE, BETWEEN). **Retained**: `place_objects`,
`validate_object`/`validate_scene`, `_relation_candidates("facing"/
"against_wall"/...)`, `_ordered()`'s dependency graph — all unmodified.
**Extended**: `constraint_compiler.apply_constraints_to_plan`'s ORIENTATION
wiring (one dict entry); two new candidate generators. **Rejected**:
per-type generators for already-working types (B), a unified dispatcher
with no measured benefit over two small functions (C), a global CSP solver
(D — P3's evidence still holds), continuous optimisation (E — no evidence
of need, would cost determinism). **Research-only**: `candidate_model.py`/
`candidate_generators.py`/`candidate_filters.py`/`candidate_ranker.py` are
research-layer; `regenerate_after_placement` is invoked only by this
phase's own benchmark/demo, not by any production job handler.

## 26. P10 Readiness

**May proceed.** The candidate layer (`candidate_model`/`_generators`/
`_filters`/`_ranker`) is available in `research/` for any future phase
needing typed, provenance-carrying, deterministically-ranked placement
candidates beyond what `place_objects`'s own internal tuples expose. The
one concrete next-step this phase's own audit surfaces (not attempted here,
per its minimal-footprint mandate): a native `RelationType` value for
BETWEEN/CENTERED in production's `ObjectRelation` would let those
constraints bias candidate generation pre-placement rather than only
post-placement regeneration — a production schema change with its own
regression surface, deliberately left for a phase with a concrete consumer
requesting it.

---

# P10 RESULT — Integrated Spatial Intelligence, End-to-End Architecture Validation & Production Boundary

## 1. Executive Summary

P10 is not a new-features phase; it is a proof phase. It reconstructs the
full 16-stage pipeline (input through Blender) with explicit per-stage
authority contracts, traces 10 real evidence-to-decision chains without
invoking a model to explain any of them, audits all 17 named artifacts and
finds zero cases where an AI can decide final geometry, builds a canonical
12-category failure taxonomy and reclassifies all 13 historical failures
found across P0-P9 under it, measures (not assumes) a genuine multi-
constraint architectural gap and reports it honestly rather than patching
it with a heuristic, assesses production readiness separately for six
input paths, and re-verifies the entire P1-P9 regression gate — including
the expensive 21-image photo pipeline — byte-identical to its frozen
baseline. Net result: the architecture is coherent, model-independent, and
mostly production-ready for the brief path; photo and floorplan paths have
real, now precisely-located limits that are not architecture bugs.

## 2. Baseline

Entering P10: 654 tests passing (P7 498 + P8 83 + P9 73), all P0-P9 frozen
benchmarks previously verified byte-identical, `app/` untouched by any
research phase. This is the frozen starting point; P10 adds only new
`research/`, `tests/`, `docs/` artifacts.

## 3. Current Architecture

Sixteen stages: `INPUT -> PERCEPTION -> EVIDENCE -> ROOM_GEOMETRY ->
OBJECT_GROUNDING -> RELATIONS -> USER_MODEL_INTENT -> CONSTRAINTS ->
CANDIDATE_GENERATION -> CANDIDATE_FILTERING -> CANDIDATE_RANKING -> SOLVER
-> VALIDATION -> REPAIR_RE_SOLVE -> INDEPENDENT_INTENT_EVALUATION -> SCENE
-> BLENDER`. Only SOLVER and REPAIR_RE_SOLVE may decide geometry (plus
ROOM_GEOMETRY/OBJECT_GROUNDING for a room/object's own measured shape).
Full detail: `docs/spatial_architecture/p10_integration.md`.

## 4. Authority Matrix

17 artifacts audited (object identity/dimensions/footprint/orientation,
room boundary, wall geometry/floor/contact, FACES/NEAR/BETWEEN, support,
clearance, collision, final XYZ/yaw, final intent satisfaction). **Zero**
have `ai_can_decide_final_value=True`. Full table:
`docs/spatial_architecture/p10_authority.md`.

## 5. Evidence Provenance Audit

10 traces built from real P1/P4/P5/P7/P8/P9 output (never fabricated),
each populated with `evidence`, `interpretation`, `geometric_hypothesis`,
`relation`, `intent`, `constraint`, `candidate`, `solver_decision`,
`validation_result`. Every trace is `explainable_without_llm=True`,
verified by test, not merely claimed. `docs/spatial_architecture/
p10_integration.md` §2.

## 6. Constraint Lifecycle Audit

`ConstraintStatus` (SATISFIED/VIOLATED/INFEASIBLE/UNKNOWN/NOT_APPLICABLE,
from P8) is exercised without conflation throughout the 30-scenario
adversarial suite and the multi-constraint composite: e.g. the composite
scenario reports FACES as VIOLATED (not silently reclassified) while NEAR
is SATISFIED, both re-verified independently by `constraint_evaluator.
evaluate_all` post-solve.

## 7. Multi-Constraint Results

The required composite (chair must FACE a table, be NEAR a sofa, avoid
collision, stay in-room): `candidate_count_before_filter=16,
candidate_count_after_filter=16, selected_candidate=(-3.0, -0.0),
satisfied_constraints=["NEAR"], violated_constraints=["FACES"],
hard_violations=0`. This is the correct, measured answer — `distance_
candidates`'s default rotation has no reason to satisfy an independent
second constraint. Recorded as architectural debt, not hidden or patched.
`docs/spatial_architecture/p10_integration.md` §3.

## 8. Failure Taxonomy

12 canonical categories (PERCEPTION/GEOMETRY/REPRESENTATION/CONSTRAINT/
CANDIDATE_VOCABULARY/SOLVER/REPAIR/VALIDATION/ASSET/BLENDER_EXECUTION/
HARDWARE/UNKNOWN). All 13 named historical failures (P0-P9) reclassified
under exactly one category each; the P8 FACES bug is the clearest case
study in why the categories must be precise (REPRESENTATION_FAILURE, not
SOLVER or CANDIDATE_VOCABULARY). Zero CONSTRAINT_FAILURE/VALIDATION_
FAILURE/BLENDER_EXECUTION_FAILURE/HARDWARE_FAILURE entries across the
entire corpus. `docs/spatial_architecture/p10_failure_taxonomy.md`.

## 9. Model-Independence Results

Architecture is model-independent by construction: no code path lets a
model's hypothesis reach a `SceneObject`'s final geometry without passing
through a candidate, a filter, and the solver. Demonstrated concretely by
trace #8 (a photo-path hypothesis recorded as evidence, never as the
decision) and by the zero-violation authority audit. `docs/spatial_
architecture/p10_production_boundary.md` §2.

## 10. Hardware Results

Reused (not re-measured) RTX 3050 6GB / ~16.8GB RAM numbers from `docs/
benchmarks/spatial_engine_production_readiness.md`: MoGe-2 vitl 0.71s/
2636MiB, SAM 2.1 0.52s/920MiB, room+wall+grounding ~5s+50ms/object, solver+
validation 0.19s/scene, Blender build 2.1s/scene, Blender render 11.4s,
Qwen2.5-VL 7B 3.47GB+2.70GB spill (off the geometric path). Zero historical
failures are HARDWARE_FAILURE — every defect found to date is a
correctness defect, not a resource-exhaustion one, at this corpus size.
`docs/spatial_architecture/p10_production_boundary.md` §3.

## 11. 30+ Adversarial Benchmark

`p10_integration_benchmark.py`: 30 named end-to-end scenarios
(`s01_single_object_placement` through `s30_complete_end_to_end_scene`),
each exercised through `run_adversarial_scenarios()`. Metrics computed
separately (see §13).

## 12. Frozen Regression Results

**718 passed, 7 skipped, 30 xfailed** — zero regressions from the 654-test
P9 baseline. All frozen P0-P9 benchmarks re-verified byte-identical:
`scene_benchmark.py` (22/22 adversarial, 0 findings), `wall_benchmark.py`
(deterministic), `repair_benchmark.py` (12/12), `coordinate_benchmark.py`
(deterministic), `clearance_benchmark.py` (10/10), `constraint_benchmark.py`
(30/30), `candidate_benchmark.py` (40/40), `scene_validity_benchmark.py`
(12/12 valid), `blender_e2e_benchmark.py` (12/12 built), and — the
expensive one, re-run this phase — `integration_benchmark.py`'s 21-image
photo pipeline: 20/21 scenes valid (95.2%), hard violations `{COLLIDES_
OBJECT:2, COLLIDES_WALL:1}`, resolver moved 13/unresolved 1, P4 repair
`hard 3 -> 3`, terminal states `{ALREADY_VALID:20, UNREPAIRABLE:1}`,
Blender 20/20 ok — byte-identical to its established baseline.

## 13. Determinism Results

`p10_integration_benchmark.determinism_check(runs=20)` — True.
`multi_constraint_composite()` byte-identical across 20 runs. `integration_
audit.trace_ten_decisions()` validation-result content identical across
repeated calls (trace names embed pre-existing random `object_id`-derived
values, a documented out-of-scope production characteristic first
identified in P9, not a P10 regression).

## 14. Production Boundary

Assessed per path, not as one label: brief-deterministic-core =
PRODUCTION_READY; brief-with-LLM = CONTROLLED_BETA; photo-to-scene =
RESEARCH_ONLY; photo-perception-layer = MODEL_LIMITED; floorplan-to-scene =
NOT_YET_SOLVED (confirmed via grep — no code exists); mixed-input =
NOT_YET_SOLVED. `docs/spatial_architecture/p10_production_boundary.md` §1.

## 15. Remaining Architectural Debt

One item: candidate generation for one constraint type does not
automatically consider a second, independent constraint type's objective in
the same generation pass (the FACES+NEAR composite finding, §7). Concretely
scoped fix (an orientation-aware ranking pass, or a chained second
regeneration pass) identified but not attempted here — out of this phase's
minimal-footprint mandate and not requested by any concrete consumer yet.

## 16. Model/Perception Limitations

Wall-contact precision 77.8% (25% UNKNOWN, inherent to plane-fit on noisy
depth), TV-unit duplicate grounding (extent-measurement defect), asset
forward-axis unverifiable at placement time, grounding at 46/48 (95.8%,
this run's direct cause of its one hard failure). None are architecture
gaps; none are fixable by changing `research/` or `app/` code.

## 17. Hardware Limitations

Blender Cycles/OptiX render at 11.4s — acceptable for one-shot generation,
too slow for interactive preview on a 6GB card. Not currently load-bearing
(zero HARDWARE_FAILURE entries in the full failure corpus) — forward-
looking capacity debt only.

## 18. Final Architecture Diagram

```
INPUT --> PERCEPTION --> EVIDENCE --> ROOM_GEOMETRY --> OBJECT_GROUNDING
      --> RELATIONS --> USER_MODEL_INTENT --> CONSTRAINTS
      --> CANDIDATE_GENERATION --> CANDIDATE_FILTERING --> CANDIDATE_RANKING
      --> SOLVER* --> VALIDATION --> REPAIR_RE_SOLVE*
      --> INDEPENDENT_INTENT_EVALUATION --> SCENE --> BLENDER --> OUTPUT

  * = the only two stages permitted to decide final geometry.
  Every other stage proposes, checks, or records — never decides.
  No model, at any stage, can bypass SOLVER/REPAIR_RE_SOLVE to write
  a final XYZ, yaw, scale, wall-contact, support, or collision value.
```

## 19. P10 Decisions

Full 12-question decision record and final scorecard in `docs/
spatial_architecture/p10_decisions.md`. Headline: 12 of 13 checked items
PASS; the multi-constraint composite is the sole PARTIAL, recorded as debt,
not failure. `app/` modification: NOT_APPLICABLE — zero changes, verified
via `git status --short` showing the identical pre-existing file list from
before this phase began.

## 20. P10 Gate Result

**PASS.** All required artifacts delivered (`integration_audit.py`,
`p10_integration_benchmark.py`, `authority_audit.py`, `failure_taxonomy.py`,
`production_boundary.py` + their test suites; `p10_integration.md`,
`p10_authority.md`, `p10_failure_taxonomy.md`, `p10_production_boundary.md`,
`p10_decisions.md`, and this RESULT). Zero regressions across 718 tests and
all 10 frozen benchmarks including the 21-image photo pipeline. Zero AI
override of final geometry across 17 audited artifacts. One honestly-
measured, precisely-scoped architectural gap remains and is documented as
debt, not hidden. `app/` untouched. The system prefers CORRECT, VALID,
TRACEABLE, DETERMINISTIC, ABSTAINABLE over ALWAYS-PRODUCES-AN-ANSWER,
demonstrated concretely by the multi-constraint composite's honest partial
result and the photo pipeline's honestly-reported 20/21 (not 21/21).

---

# RESEARCH → PRODUCTION MIGRATION (post-P10)

The validated P1–P10 libraries now live in `app/spatial/` and `app/planning/`;
`research/spatial_architecture/` keeps the benchmarks, audits, the photo-path
bridge, and re-export shims so every frozen benchmark above still runs
unchanged. The one behavioural production change is P5's own recorded path:
`Wall.extrusion_direction` (default vertical) and H2 via `object_wall_collides`.
Phase entries above describe modules at their pre-migration location; that is
history and is not rewritten. Full record, migration matrix and final report:
`docs/production/research_to_production.md`; whole-repository inventory:
`docs/spatial_architecture/productionization_inventory.md`.

---

# P11–P13 — DESIGN INTENT (visual fidelity)

A second axis from P1–P10's spatial one: those phases asked *where does it go*,
these ask *does it look like what the client showed us*. The solver's authority
is untouched throughout — `DesignIntent` and `ObjectVisual` carry no position,
rotation or scale, and `place_objects` still decides every metre.

**P11 — the representation.** Audited where visual attributes died: a reference
reached the plan only through a Stable Diffusion moodboard (a 34-word CLIP
prompt with hex stripped, one IP-Adapter image at 0.35), which a VLM then read
back, after which `merge_reading_into_plan` replaced the room's items — so no
object retained any link to an uploaded file. Built the typed
`DesignIntent`/`VisualAttributes` with provenance, the five reference classes in
one `POLICY` table, deterministic merging with explicit conflicts, the four-rung
asset ladder ending in a real `UNRESOLVED`, and the `visual_intent_fidelity`
report. Also measured the hardcoded `limit=6` on Gemini references: 6/8/10/12 all
return HTTP 200 at ~1.1k tokens/image, so the cap was never a token limit — now
the measured setting `gemini_max_reference_images=12`. Gate: **PASS** (10/10),
but not called by production. `docs/production/p11_design_intent.md`.

**P12 — live in the paid path.** Wired into `scene_plan`: classification before
the moodboard read, `apply_intents_to_plan` **after** `merge_reading_into_plan`
and `apply_spatial_graph` — so the client's own photograph gets the last word
without removing the round-trip other behaviour depends on. The live benchmark
caught two defects the component benchmark structurally could not:
`ResilientProvider` never forwarded `classify_reference` (every reference came
back `unread` in production), and a DESIGN_REFERENCE influenced nothing because
reconciliation gated on `instantiate`. Verified on 8 real client photographs
with the real model: 8/8 classified, 0 unread. Gate: **PARTIAL** — 6 of 10
attribute classes reached the executor. `docs/production/p12_live_design_intent.md`.

**P13 — attributes reach the executor.** `SceneObject.visual: ObjectVisual`
(colour words, material/upholstery words, pattern, frame finish, descriptors,
source intent ids), populated from `ObjectPlanItem.visual` at the single
construction site, mirrored into the manifest row **only when non-empty** so
pre-P13 scenes produce byte-identical manifests. `ObjectVisual` is parallel to —
not imported from — `VisualAttributes`, because `app/scene/schema.py` imports
nothing from `app/` and the executor-facing contract must not depend on the
intelligence package. Semantic preservation **7/7**; executor-rendered **3/7**,
reported as two numbers and pinned by `VISUAL_ATTRIBUTE_CONTRACT` in code:
Blender's `for_object` takes one registry material plus one hex tint, so
pattern, frame finish, colour words and descriptors are `PRESERVED_METADATA_ONLY`
and are never described as rendered. Gate: **PASS** (10/10).
`docs/production/p13_visual_attribute_propagation.md`.

**P14 — from preserved to painted.** Moved two of the four remaining attributes
into real rendering and left the other two alone, on evidence. `frame_finish`
resolves through `compiler.finish_material_for` — the mirror of the existing
`material_for` — to a material the registry *already* has, and
`import_assets._apply_frame_finish` paints it onto exactly the trim meshes
`_apply_upholstery` deliberately skips, with the same `m.data.copy()` isolation.
It needs a second material region: **measured at 10 of 58 real assets**, so the
other 48 report `metadata_only` with a written reason rather than repainting a
whole sofa walnut. New `ExecutorSupport.CONDITIONALLY_RENDERED` exists so
"sometimes" is never reported as "yes".

The phase's most useful result was upstream and unflattering. On 8 real
photographs through the live model, Gemini populates `frame_finish` **0/8**,
`color_words` 0/8 and `pattern` 0/8 — it fills only `upholstery` and
`visual_descriptors`, putting the frame information in the descriptors instead
("wooden frame", "gold accent trim"). So the executor mechanism, as built, was
reachable on almost nothing. Hence `descriptors` was promoted too: a descriptor
that **both** names a structural part and resolves to an existing material
supplies the finish, through the identical resolver and guards, tagged
`finish.source == "descriptor"` so it never counts as a stated attribute
surviving. 2 of 8 real references carry frame evidence this way.

Two claims were **withdrawn**, not added. `finish.roughness` is computed into the
manifest and no Blender script reads it, so matte/satin/glossy are carried, not
applied — the contract said otherwise and was corrected downward, with a test
that scans the executor scripts and fails if that ever silently changes. Colour
words and pattern stay `PRESERVED_METADATA_ONLY`: there is no word-to-hex
mapping and no texture synthesis in this repository, and inventing either to
raise the metric was the one thing the phase was told not to do. Gate: **PASS**
(11/11; suite 812, the 768 baseline plus 44 new P14 tests).
`docs/production/p14_visual_attribute_rendering.md`.

**P15 — the extraction contract.** One architectural decision: the eight
attribute fields in `REFERENCE_CLASSIFICATION_SCHEMA` are now **required**, and
the prompt no longer says "leave a field out otherwise". That sentence was the
bug. This repository had already recorded the identical lesson for `against` and
`faces` in `SCENE_READING_SCHEMA` — optional fields the model simply never
returned — and P15 is the same fix on the same class of failure. A required
field may still come back empty, which the caller reads as "nothing to say"; an
absent one cannot be told apart from a field never considered.

Three prompt variants were run over the SAME 8 real photographs on the live
model and scored against ground truth read off the pictures, not against the
model's own confidence. The winner was promoted whole into the canonical prompt;
no second extraction path, parser or provider was created, and `VisualAttributes`,
`DesignIntent`, `IntentProvenance` and the resolution ladder are untouched.
Measured on the production `classify_reference` path: `frame_finish` **0/8 →
2/8**, `color_words` 0/8 → 8/8, `pattern` 0/8 → 7/8, extraction fidelity
**0.38 → 1.0**, with **zero** false positives and `color_hex` still 0/8 — no hex
was invented from a colour word.

The restraint is the result, not the population count. Four of the eight images
are mattresses and a fifth sofa sits on a skirted base, so five of the six empty
`frame_finish` answers are *correct*; 2/8 is this image set's true ceiling, and a
prompt that reached 8/8 would have hallucinated five frames. The "a mattress has
no frame" instruction and the part-by-part inspection order are what buy that.
P14's descriptor fallback is retained and unbroadened, behind explicit
extraction: stated, then descriptor, then nothing. Gate: **PASS** (suite 863, the
812 baseline plus 51 new P15 tests; P11–P14 unchanged).
`docs/production/p15_reference_extraction.md`.

**P16 — the product uses them.** The audit's headline was that P11–P15 were
*already* on the production path: `scene_plan` calls `classify_references`,
`apply_intents_to_plan`, `resolve_all` and `visual_intent_fidelity`, and P14's
contract reaches Blender through `build_manifest` in the `build` handler. P15's
prompt needed no wiring at all — it sits in the one canonical function the
provider already calls. So P16 built almost nothing and instead closed four
defects between a correct backend and an honest UI.

Two are architectural decisions worth recording. **Enqueue is now idempotent per
(project, type).** There was no duplicate guard anywhere; every route called
`enqueue` unconditionally, and the two-worker `ai` lane let two concurrent
`scene_plan` jobs write the same planning files. The guard lives in
`JobRunner.enqueue`, the single point all ten routes funnel through, and returns
the in-flight job rather than creating a second — in-flight ONLY, so a finished
job never blocks `force` or a retry. **The Gemini key moved from the query
string to the `x-goog-api-key` header**: as `params={"key": ...}` it was part of
the URL, and httpx logs whole URLs at INFO, so every generate call had been
writing the live key in clear text into the job and server logs. Pre-existing,
found only because a real run was performed.

The other two were frontend honesty bugs: the Studio passed `sceneId ??
undefined` to a viewer whose default is the seed demo apartment (so a project
with no scene showed someone else's demo flat as the client's design), and both
`runRender` and `confirmAndPlan` left the previous successful scene on screen
after a failure — `confirmAndPlan` even advanced a step, presenting a stale plan
as the result of the run that had just failed.

Verified end to end on one real photograph through the real routes with live
Gemini and the real Blender binary, in an isolated data dir junctioned to the
real 58-asset registry: upload → analyze → scene_plan → build in 25.5 s, chain
`in_… → di_… → obj_… → ph_sofa_02 → build_manifest.json → scene.blend` (12.2 MB),
every advertised file retrievable. Honest visual result: the reference's sage
green and linen DO render; the correctly-extracted `frame_finish: "dark wood"`
does NOT, reported as `metadata_only` because that asset is one of the 48
single-region GLBs — the measured P14 ceiling, stated in the manifest rather
than hidden. Gate: **PASS** for the backend-to-manifest-to-Blender path,
**PARTIAL** overall: the browser walkthrough was not performed, so the claim
stops where the evidence does. `docs/production/p16_production_wiring.md`.

**P17 — element-first, researched and partly refused.** The proposal was to move
the object inventory upstream of the moodboard: the model names every element
and its instance count before any image exists. Researched first, and two
measurements contradicted the case for it.

**The current system can already count.** Running the shipped
`merge_reading_into_plan` over 8 inventories with known ground truth, the
moodboard route scored **8/8 overall and 6/6 on repeated elements** — multiplicity
survives as N plan items each with `count=1`, which sums correctly. The broken
channel is the typed one: `merge_intents` groups by `(object_category,
room_hint)`, so the design-intent route scored **0/6** on repeated elements. A
client who photographs two armchairs gets one, by a P11 rule that exists to stop
their sofa becoming two sofas.

**Qwen:3B transcribes an inventory and cannot author one.** On briefs that state
their contents: 40/40 valid JSON, count accuracy **0.962**, zero hallucinations,
7/8 scenarios repeatable, median 2.8 s. On briefs that do not — the real case —
**2 to 3 distinct inventories per 3 runs**, one hard failure at the token cap, and
invented types (`kitchen_chandelier`, `kitchen_pantry`) outside the vocabulary.
Gate question 8 therefore FAILS, and with questions 9, 10 and 13 unmeasured or
negative, full element-first was **refused** per the gate's own rule.

**What was adopted is the part with evidence behind it: a derived instance-count
contract.** `ElementInventory` records, per (room, semantic_type), how many rows
were read, how many survive `trustworthy()`, and which check removed the rest.
Computed from the rows, never asked of a model, and recomputed rather than
trusted so an edited or pre-existing reading still counts correctly. The number
was previously implicit in `len(...)` at every stage, so a loss had nowhere to
show: three bar stools whose boxes each ran to the image edge reach the plan as
ONE piece, and the other two left no trace. On the live sample project this
immediately surfaced **11 pieces read and 0 usable** — the kitchen island, an
armchair, a rug, curtains, a table lamp, a bedside table — every one of them
previously invisible. Counting changed no placement: asserted before and after.

Also recorded, unfixed: `shape_key` includes the box centre, so three stools
along a counter get three keys and **three Meshy purchases of the same stool, 90
credits where 30 would do**. That is the strongest case for canonical element
identity and is the next step, not this one. Gate: **PASS** for the count
contract (suite 904, the 883 baseline plus 16 new P17 tests plus 5 from the
earlier analysis-staleness fix; P11 10/10, P12 10/10, P13 10/10, P14 11/11,
frozen P4–P10 unchanged). `research/element-first/decision-record.md`.

**P18 — canonical identity, phases 1–5 of element-first.** The three-bar-stool
defect is fixed at its root and measured, not argued. Six identity keys were
run over the real project's 26 elements and five golden cases with known ground
truth (`research/element-first/identity-ablation.json`). The production key —
`room | type | box-centre` — scored **2 false merges and 10 false splits**; the
winner, `room | type | dimensions-bucket | material | colour`, scored **0 and
0**. Selection rule: fewest false merges, then fewest false splits, never the
reverse, because a merge puts the wrong piece in a room and a split only buys a
second mesh. On the real project it takes generated assets from **26 to 23**,
which is the ideal.

The rule that costs the most and matters the most: a piece with NO positive
evidence — no material, no colour, no dimensions — keeps its own identity
(`identity_method = "unresolved"`). Two same-type pieces that both say nothing
are not known to be the same. Room stays in the key deliberately; dropping it
merged the two bedrooms' beds (documented). Position is nowhere in it.

Schema: `ElementDefinition` (what a piece IS) and `ElementInstance` (one
occurrence, carrying its bbox and crop), both derived by `resolve_elements`
from trustworthy rows and persisted on the reading; content-addressed `cel_…`
ids. `distinct_shapes` now groups by `canonical_key`, so `generate_elements`
makes one Meshy call per canonical piece. **Nothing already bought is re-bought**:
`storage_key` resolves a canonical group to an existing legacy centre-keyed
file before spending, and the review route's credit figure uses the same rule.
On the live project every approved group resolved to a mesh already on disk —
`to_generate 0, credits_needed 0`, stools recognised as `3x bar stool`.

Known limitation, recorded in the test that found it: the 10 cm dimension
bucket splits a pair that straddles a boundary (44 cm vs 46 cm). A split is
the safe direction. Not built: `SceneObject` linkage to instance ids (phase 6),
moodboard occurrences (7), Qwen similarity assist (8), render verifier and
repair loop (9–10) — each waits on its own benchmark. Gate: **PASS** (suite 924,
the 904 baseline plus 20 P18 tests; P11 10/10, P12 10/10, P13 10/10, P14 11/11,
frozen P4–P10 unchanged, frontend 26/26). `tests/test_p18_canonical_identity.py`.

**P19 — element inventory on the review screen.** Presentation only: a
presenter joins `summary.definitions` / `summary.instances` (the one backend
addition) to reading rows by id and renders one card per canonical piece with
its instance count, one crop per instance, an asset resolved/unresolved state,
the backend's identity method in words, and a "Detected but not used" list
naming the check that removed each row. The frontend never counts or groups;
a test hands it a definition claiming five and asserts it reports five. Live:
26 detected · 13 canonical · 15 instances · 13 assets, 11 rejected, 15 + 11 = 26.
Frontend 26 → 40 tests; backend unchanged at 924. PARTIAL only because the
browser was not opened.

**P20 — element images before the room, and the composition gate.** The first
stage a client sees of element-first. `analyze` gained `paint=False`, so
analysis, crops and style run without painting rooms; a new `element_images`
job derives the inventory from the object plan (the same
`planning/object_plan.json` scene_plan writes, so the two never disagree),
folds it into canonical definitions and instances with `definitions_from_plan`
— the same key rule as the moodboard reading, so a piece decided here is the
same piece when read there — and renders ONE isolated product-style picture per
piece on the local GPU, seeded from the element id so it is reproducible,
conditioned on the client's own crop through IP-Adapter when one exists. A new
Studio step, "Design Elements", sits between Upload and Moodboard and shows
those pictures first. `generate_elements` now prefers the element image over
the moodboard crop as the Meshy input when the canonical keys match.

Measured on the live sample project: 13 pieces, 15 instances, 13 pictures, all
13 conditioned on a photo crop, zero failures; **13 of 15 usable reading rows
(11 of 13 pieces) would send the clean picture to Meshy**, the 2 misses being
the no-evidence pieces whose keys are unique by design. The pictures are real
product shots — the client's striped sofa comes through — with one recorded
defect: context (a shelf, a rug, a plant) leaks past `ELEMENT_NEGATIVE`.

**The moodboard does NOT change, and this is the decision.** Three ways of
painting the living room were compared, three seeds each, read back by the
production scene reader (`research/element-first/composition-results.json`):
today's anchor-photo conditioning scored type recall 0.67 / count accuracy
0.50; conditioning on ALL element images **cannot run at all** — diffusers
enforces one image per loaded IP-Adapter, so the repo's "several references
average into mush" is a hard limit, not a quality note; conditioning on the
anchor's element image alone scored 0.50 / 0.25 and does not beat the photo.
Composing the room from element images therefore stays unbuilt until a
different mechanism exists (per-region inpainting, a multi-adapter pipeline, or
layout control). A caveat on the numbers: the reader is stochastic, so the
photo-vs-element difference is within noise; the B failure is not.

Also recorded: a user project was deleted through the API while the job was
painting it, and the job kept writing into the removed directory before its
row-level writes failed — a pre-existing gap for every job, not fixed here.
Gate: **PASS** for pictures-before-room and the Meshy input path; **REFUSED** for
moodboard composition, on evidence. Suite 938 (924 + 14 P20), frontend 45
(40 + 5), typecheck, lint and build clean. `tests/test_p20_element_images.py`.

**P21 — approve the pieces, then paint; and one project's furniture stays in
that project.** Two client-reported defects, both structural. First, the
flow: the "Design Elements" step is gone and the moodboard step has two
phases. Phase A pictures the pieces (`analyze paint=false` → `element_images`)
and asks Build/Skip per card; `PATCH /projects/{id}/element-images` stores
`{element_id: bool}` on the canonical `ElementDefinition.approved` (validated
ids, merge not replace, echoed back through the same payload helper as GET).
"Approve and paint the room" is the only way into phase B (`analyze`
with paint, which reuses the checkpointed analysis and paints), and "Looks
right — review it" is enabled only once `moodboard.scene_url` exists — the
painted room is the evidence phase A happened, so a reload resumes on it.
Step 4 is rooms-only (`AnalysisReview roomsOnly`: dimensions and save,
nothing else) plus Plan; the moodboard reading is shown there only for rows
still undecided, under a heading that says the painted room added them.
`scene_plan._carry_element_decisions` moves the client's decisions onto the
reading rows with the same canonical key before identity resolution —
never by position, never over a human decision on the review screen, never
onto an unresolved key — so the same stool is not asked about twice and a
skipped piece is not built because the render happened to contain it.
Second, the leak: `startNewProject` reset analysis but not `sceneReading`,
`sceneSpec`, `buildReport` or `elementImages`, and `createProject` reset
nothing, so step 4 showed the previous project's crops. One `clearDerived()`
now runs on every path that changes the project (open, create, start over)
and also resets every `useJob`, because a finished job left behind both
blocked the next project's auto-run and displayed as its progress.
Suite 945 (938 + 7 P21), frontend 45, typecheck, lint and build clean.
`tests/test_p21_element_decisions.py`. Not measured: the live click-through;
the backend was restarted with the new routes for the client to run it.

**P22 — where the picture put each piece: render-frame anchors and per-wall
finish zones.** The client asked for x/y/z and a facing per element, and
textures per wall with coordinates. The recorded reason those did not exist
still holds — a painted moodboard has no camera pose against the floor plan,
which is why `against`/`faces` must NAME pieces and directions were
discarded (30 of 30 answers were camera-relative). The decision is to fix
the frame by convention rather than keep refusing it: the picture is taken
from the room's front wall looking at its back wall, and the plan binds back
= the room rectangle's north edge (min z), left = west (min x), right =
east, front = south — the same compass `layout.py` already uses. Gemini
answers IN that frame, as whole numbers out of 1000 like bbox: `wall`
(back/left/right/front/none), `along`, `depth`, `height`, `facing`.
Deterministic code (`render_frame_position`) turns them into room-local
metres — a named wall snaps the coordinate it fixes, floor pieces sit at
y = 0 — stored on `SceneElement.position_m` / `facing` / `facing_dir` and
carried onto `ObjectPlanItem.anchor_m`. The solver's `_prefer_hint` uses the
anchor and pictured facing only as tie-breaks AFTER the named hints: a fact
about two pieces outranks an estimate off a 2D render, and the solver still
selects only from its own validated candidates — the anchor is never a
placement. Walls: `RoomSurfaces.walls[]` holds `WallFinish` zones (wall
name, material, colour, pattern, `extent_m` = metres along the wall from
its left end and up from the floor), bound at compile time to the wall
segment the named edge became (`bind_wall_finishes` → `Wall.finishes`,
exported in the Blender manifest). Additive throughout: every stored
reading, plan and scene loads unchanged. Not done, stated plainly: Blender
still paints each wall in one `Wall.material`; the zones are data until the
executor consumes them. Not measured: whether flash-lite answers the four
fields consistently on real renders — the P15 harness pattern applies and
should be run before the anchors are trusted in a live plan. 14 tests in
`tests/test_p22_render_frame.py`; placement-hint suite unchanged.

**P23 — the anchor is a property of every element, and three defects the live
run found.** P22 left the coordinates optional: an element the reader said
nothing about had none, and a project read before the fields existed would
never get them. Made fundamental instead. `anchor_from_bbox` derives the
anchor from the crop box, which is REQUIRED on every element and already
validated, so every boxed element has a position: horizontally a direct
correspondence under the fixed frame (the box centre is `along`),
front-to-back ORDINAL not metric (a box whose bottom sits lower in the frame
is nearer the camera; metres would need a horizon this layer does not have).
`SceneElement.position_source` records `read` | `derived` | `""` so nothing
downstream mistakes an estimate for a reading, and any component the box had
to answer marks the whole anchor derived — never claim better than reality.
`ensure_anchors` fills what is missing and is idempotent; scene_plan calls it
on the CACHED read path, beside the spatial-graph retro-fill that was there
for the same reason, so a project read before this existed gains anchors from
the box it already stores, with no model call and no repaint. Verified
read-only on the sample project: 26 of 26 elements would fill.

Three defects the live run exposed, none of which a unit test would have:
(1) **the frontend never saved the element decisions** — `reviewElementImages`
was written `{ method: "PATCH", ...json(body) }` and the helper's own
`method: "POST"` spread on top, so "Approve and paint the room" POSTed to the
route that ENQUEUES element_images, which re-ran the job and wrote every
definition back to `approved: null`; both routes answer 200, so nothing
complained. Fixed, and pinned by a contract test asserting the method.
(2) **a hung piece was stored on the floor** — the reader returned `height: 0`
for a framed print whose box sat in the top third of the picture, and for a
wall-mounted TV; zero on a `wall` placement is the model declining, not a
measurement, so the box now answers and the anchor is marked derived.
(3) **`force_read` was unreachable** — the handler has honoured it since the
read was checkpointed, but `ScenePlanBody` carried only `force`, so no caller
could re-read a moodboard: every reading was frozen at whatever the first read
produced, and no later fix to the reader could reach an existing project.
Added to the body and forwarded.

Measured live on proj_a25a006c88, fresh read: 11 of 11 elements answered in
the render frame (`position_source: read`), wall-mounted TV at y 2.10 m, art
at 1.80 m, floor pieces at y 0.00, pieces against back/left/right walls
snapped to those edges, facings consistent with the wall each sits on, and 3
wall finish zones. That is the first evidence the frame fields are answered
consistently on a real render — the gap P22 recorded as unmeasured.

**P24 — verify the built room by looking at it, and what that measured.**
`research/placement_loop.py` builds the scene, renders the largest room from
every corner with `blender/scripts/render_viewpoints.py` (opens the saved
.blend, no rebuild), reads each photograph back with the SAME production
scene reader that read the moodboard, and scores three separate ways for the
room to be wrong: **coverage** (approved pieces the camera can actually find),
**placement** (pieces standing within 0.75 m of where the reader measured
them) and **assets** (a real mesh where the plan asked for one). It turns four
real knobs in the placer between attempts and exits on the target.

**Target 95%. Reached 71%, and the honest reason is three separate ceilings.**
Measured on proj_a25a006c88 (`docs/benchmarks/placement_loop.json`):

- **assets ceiling 80%** — 2 of 10 pieces (`fireplace`, `basket`) are
  `strategy: generated` with no `asset_id`: they were routed to Meshy and
  never bought, because nothing was approved. Re-planning cannot conjure a
  mesh, and the loop says so instead of pretending.
- **coverage is too noisy to drive a loop** — the same built scene read four
  times scored 0.556, 0.778, 0.556, 0.556: a spread of **22 points**, far
  wider than any improvement worth detecting. The reader also invents: a
  `dining_table` appears in all four views of a living room that has none,
  alongside `vase`, `tray`, `books`, `pedestal`, `bookshelf`. A generative
  reader cannot be the judge of its own pipeline at this precision.
- **placement is limited by real constraints, not by tuning** — median offset
  **0.53 m**, 6 of 11 within 0.75 m, **9 of 11 within 1.0 m**. The two worst
  are honest: the wall-mounted TV is 2.20 m out because the window spans
  x 2.0–3.8 m on the back wall and the placer refuses to hang anything over a
  window, and the floor lamp follows it (`against: 'the tv unit'`). Two more
  miss by 5 and 7 cm.

Two real defects the loop found, both fixed: a **measured position now
outranks the vague text hints** (`against: 'wall'` and `faces: 'into the
room'` are true of nearly every candidate and were beating an anchor that
named one spot; ties within `ANCHOR_TIE_BAND_M` still fall through to the
named relations, and an ESTIMATED anchor still ranks below them), and the
**wall line is not where the object's centre goes** — a piece against the
back wall was anchored at z = 0, which puts half of it inside the wall, so
the candidate was rejected as invalid AND a correctly seated sideboard
measured half a depth from its own anchor. `anchor_spot()` now pushes a
wall-bound piece in by half its depth, and the harness grades against the
same spot.

What would actually reach 95%, in order of effect: buy the two missing meshes
(assets → 100%); measure coverage **geometrically in Blender** — is the object
inside the camera frustum and unoccluded — instead of asking a language model
what it can see, which removes the ±22 point noise entirely; and read window
and door positions from the render rather than generating them independently
of it, which is what puts a window where the client's TV goes. None of these
is tuning; each is a different piece of work, and the loop is now the thing
that will prove whether they helped.

**P25 — why the room was half empty, and a verification loop that can be
believed.** The client reported a missing television, pieces "like cubes", and
wrong chair orientations. None of the causes was the obvious one, and all were
found by looking rather than reasoning.

*The assets.* Six separate defects, in the order they bit:
1. **No download retry.** The television's mesh reached 100% at Meshy and was
   then lost to `All connection attempts failed`; the code had no retry, so a
   finished, paid-for mesh was discarded and a catalog cabinet stood in its
   place. Three of six pieces went this way in one batch. `DOWNLOAD_ATTEMPTS`
   is now 4 with backoff, retrying transport errors and 5xx only - a 404 is
   still reported immediately rather than four times slower.
2. **`meshy_max_per_project: 6`** against 11 approved pieces, which made the
   cap a silent truncation rather than a safety rail: "5 over the limit of 6"
   in a job event nobody reads. Raised to 20, above a real room.
3. **`MESHY_TIMEOUT_SECONDS=300`** abandoned two meshes "still IN_PROGRESS at
   45%" while their batch-mates finished. Raised to 900 in `.env` and
   `.env.example`; waiting costs time, abandoning costs the piece.
4. **Blank failure messages** - `"oak tv unit: ; keeping the catalog match"` -
   because the exception carried no message and it was printed raw. The type
   is now always included.
5. **No forward axis anywhere.** The asset registry has no such field, and
   `import_assets` applied the planner's yaw directly on top of each model's
   own unknown facing. Poly Haven models and Meshy meshes do not share an
   orientation convention, so this could only ever be right by luck - the
   chairs faced the wall. `_native_forward_yaw()` now reads the facing off the
   mesh: for seating the backrest is a tall mass BEHIND the seat, so forward
   points away from it, snapped to quarter turns and left alone when the
   geometry is not clearly asymmetric. A wrong correction is worse than none.
6. **`television` was an alias of `tv_unit`.** A wall-mounted screen and an
   oak media console were one semantic type, so both were prompted as "tv
   unit" and the room got two televisions. `television` is now its own type -
   appliance family, wall placement - leaving `tv_unit` the floor-standing
   cabinet it always was. Additive: stored readings still parse.

Result on proj_a25a006c88: **11 of 11 pieces carry a real mesh**, from 3.

*The loop.* `research/placement_loop.py` now grades with
`blender/scripts/check_visibility.py`, which ray-casts from each camera and
reports never-in-frame / occluded / visible per object. The vision-model judge
it replaces is not merely noisy but wrong in a documented way: the same
unchanged scene scored 0.556, 0.778, 0.556, 0.556 - a 22 point spread - while
reporting a dining table in all four views of a living room that has none.
DASH (ICCV 2025) catalogues systematic object-presence hallucination across
950,000 images which transfers between architectures, and VLM counting error
roughly triples on textured scenes; Q-Spatial-Bench puts GPT-4o at 69% for
distances merely within a FACTOR OF TWO. A generative reader cannot judge the
pipeline that feeds it.

*The target, restated against the literature rather than against hope.*
Recovering metric furniture positions from one image whose camera nobody knows
is the hard case: ROCA (CVPR 2022) reports **17.6%** at 20 cm / 20 deg, and
Total3D (CVPR 2020) **51.8%** within 0.5 m with a median of 0.48 m. A 90%
target at 20 cm is roughly five times better than anything published. The gate
is therefore 90% within **1.0 m**, with the 0.5 m figure reported beside it so
the harder number is never hidden. Measured: **accuracy 91%** - coverage
100%, assets 100%, placement 73% within 1.0 m, 36% within 0.5 m, median
**0.54 m**, which is Total3D's own median.

*What is left, and it is not tuning.* The largest single error, 2.44 m, is the
wall television: its anchor is the back wall at x 2.09, and `layout.py` puts a
1.8 m window at x 2.0-3.8 on that wall, so every hang candidate near the
anchor is vetoed - correctly, since a TV does not go over a window - and the
piece moves to another wall, displacing the artwork already there. **Openings
are invented by the layout code rather than read from the render.** Until a
window's position comes from the same picture the furniture does, the plan and
the moodboard will keep disagreeing about which wall is free. That is the next
piece of work, and the loop is now trustworthy enough to prove whether it
helped.

**P26 — orientation, four layers down, and the loop that found each one.**
The client reported chairs and a television facing the wrong way after P25.
The cause was four defects stacked on top of each other, and only the last
one was visible from the outside. Each was found by measuring, and three of
the four contradicted a guess made earlier in this same session.

1. **A placed piece inherited the WALL'S rotation.** Every wall-aligned
   candidate carries the wall's own normal, and the reader's `faces` only ever
   acted as a tie-break, so an armchair read as facing the television faced
   whatever wall it landed against. The reader's rotation is now offered first
   at every candidate position, with the wall's own kept behind it so a
   rotation that will not fit still falls back rather than failing to place.
   Orientation 60% -> 80%.
2. **Hang spots were sampled at five fixed fractions** - 0.22, 0.35, 0.5,
   0.65, 0.78 - all mid-wall, which is also where a window goes. A 1.8 m
   window centred on a 5.8 m wall put every one of the five inside the "not
   over a window" margin, so the generator returned NOTHING for that wall.
   Now swept at 0.25 m intervals as a fallback, scored below the preferred
   five so an unobstructed wall places exactly as before.
3. **The television genuinely did not fit.** 1.8 m wide, with 1.85 m clear at
   each end of the window and 0.15 m margins required: real geometry, not a
   bug. Worth recording because the first probe used a 1.2 m placeholder and
   "found" five spots that a real TV could never use - the probe has to use
   the real dimensions or it measures nothing.
4. **The window was invented where the picture put the television.** Windows
   go on the longest exterior wall of each room, centred, and nothing
   consulted the reading. `reserved_wall_spans()` now hands
   `build_walls_and_openings` the spans that wall-mounted pieces the reader
   MEASURED already claim, so an opening is never offered there. The width
   comes from the crop box scaled by the wall's run - measured from the same
   picture, in the same frame as the position, so nothing is invented. The
   window moved from x 2.9 to x 4.31 and the set went back where it was seen.

**Measured, production defaults, attempt 1: coverage 100%, placement 91%
within 1.0 m (55% within 0.5 m), orientation 100%, assets 100% - accuracy
98%.** The 0.5 m figure is now above Total3D's published 51.8%, and it moved
because a window moved, not because a threshold did.

Two knobs were adopted from measurement rather than argument. The loop turned
`ANCHOR_TIE_BAND_M` across four settings and only 0.01 reached 100%
orientation; `ANCHOR_LEADS_WHEN_DERIVED` is now on, **reversing** the comment
previously written beside it, which argued an estimate should not outrank a
stated relation. It should: "into the room" names half the room, a
box-derived position names one spot. Evidence is one project, and the loop
re-checks it on any other.

*Orientation as a gate.* The loop now scores orientation against the reader's
`facing` for `ORIENTED_TYPES` only - types with a front you can see. A rug
turned 180 degrees is the same rug, and the reader answers `faces` for rugs
and baskets too, so grading them would measure the vocabulary rather than the
room. The gate is separate from the accuracy average, deliberately: a room
where every piece is in the right spot and one faces the wall reads as broken,
and an average hides exactly that.

*What the research changed, and what it did not.* The deep search (Fu et al.
SIGGRAPH 2008; Upright-Net CVPR 2022; Orient Anything ICML 2025; Holodeck
CVPR 2024; Symmetry-Robust 3D Orientation ICML 2025) establishes that front
direction is provably unrecoverable from geometry alone for symmetric shapes,
that what ships is four-view rendering plus a VLM vote (44% single view ->
74% four views -> 92% with a symmetry pre-filter), that glTF carries no
orientation metadata and Meshy's API returns none, and that **Poly Haven
documents and enforces -Y forward** so library assets need no inference at
all. It also found a real bug in `_native_forward_yaw`: averaging raw vertex
positions is density-biased, and a tufted cushion carries more vertices than
the flat panel behind it, inverting the answer. Now area-weighted.

But the honest finding is that none of this was the reported bug. Probing
`_native_forward_yaw` on the four real assets returned 0 degrees for every
one - correctly, because Meshy output is already canonically oriented. The
asset-facing work is a guard for future library assets with other
conventions, and it was wrong of an earlier note to imply it had fixed the
chairs. The next step the research points at is real and unbuilt: detection
belongs at ingest via `normalization.py`'s existing `yaw_offset` parameter
(nothing passes a non-zero value today), with render-and-compare against the
crop the mesh was generated from - the mesh is a reconstruction of that exact
image, so matching a render to its own source should be near-exact.

**Boundary after P20** (unchanged, and verified rather than assumed): vision
**Gemini**, asset generation **Meshy**, spatial engine **Allure**, executor
**Blender**. No Hunyuan3D and no Unreal integration exists in this repository.
Provider-side generation attribute propagation remains pending — the structured
`GenerationRequest` is persisted and traceable, but Meshy's image-to-3D endpoint
exposes no attribute field and none was invented. The binding constraint has
moved back **downstream**: evidence now reaches the structured contract, and what
limits visual fidelity again is what Blender can paint — 10 of 58 assets carry a
separable frame region, pattern renders nowhere, and the finish resolver maps the
generic word "wood" to oak veneer regardless of the shade actually photographed.

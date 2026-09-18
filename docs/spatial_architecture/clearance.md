# P2.1-P2.3 — Clearance representation, taxonomy, and residential policy

Continues directly from `clearance_baseline.md` (P2.0's five named gaps).
Covers three of the brief's phases in one document, as `collision.md` did for
P1 — the taxonomy and the policy table are both small enough that a separate
file per phase would fragment one decision across three files for no reader
benefit.

## P2.1 — Representation

### Research questions

What representation distinguishes "collision-free" from "usable," at what
computational cost, and does Allure need one representation or several for
different sub-problems (pairwise clearance vs. circulation vs. functional
envelopes)?

### Search strategy and sources

`"interior design furniture clearance standards inches sofa coffee table
walkway"`, `"ADA accessibility clear floor space wheelchair minimum
clearance residential"`, `"configuration space Minkowski sum clearance
robotics path planning obstacle"`, `"navigation mesh vs visibility graph vs
grid pathfinding small indoor room comparison determinism"`, `"door swing
clearance furniture BIM IFC door opening arc representation standard"`, plus
three follow-ups for specific residential numbers (§P2.3).

Primary sources: [U.S. Access Board — Clear Floor/Ground Space](https://www.access-board.gov/ada/guides/chapter-3-clear-floor-or-ground-space-and-turning-space/)
and [ADA Fig. 45](https://archive.ada.gov/descript/reg3a/fig45des.htm) (the
governing accessibility standard, not a blog's restatement of it); [NKBA
kitchen guidelines](https://www.thewcsupply.com/pages/kitchen-design-guidelines-standard-clearances);
buildingSMART's own [`IfcDoor`](https://github.com/buildingSMART/IFC4.x-development/blob/master/docs/schemas/shared/IfcSharedBldgElements/Entities/IfcDoor.md)
and `IfcDoorTypeOperationEnum` (hinge-side/swing convention, official IFC
schema docs, not a third-party summary); the LaValle group's [path-planning-
with-clearance paper](https://lavalle.pl/papers/SakLav21.pdf) and a CMSC 425
motion-planning lecture (Minkowski-sum config-space, primary robotics
formulation, cross-checked against a second arXiv source on parameterized
C-space obstacles); a Stanford game-programming notes page and a GameDev.net
tutorial (navmesh vs. grid vs. visibility graph, cross-checked against two
independent write-ups reaching the same conclusion). Interior-design numbers
came from multiple independent retailer/blog sources per figure — none
treated as authoritative alone; only figures where ≥2 independent sources
converged were kept (§P2.3 states the source count per number).

### Findings

**No single representation answers all seven concepts (§ mission).**
Cross-checking the config-space/Minkowski literature against the navmesh-vs-
grid literature shows they solve *different* problems: Minkowski-sum
"shrink the mover to a point, grow every obstacle" is the right tool for
**circulation** (can a person get from A to B at all), not for **pairwise
clearance** (is object A far enough from object B) — inflating a coffee
table's obstacle by half a person's width and testing "does a point fit
between it and the sofa" would answer a different, less precise question
than "what is the actual gap between their footprints." Allure needs both,
computed differently:

| Concept | Chosen representation | Why |
|---|---|---|
| Pairwise clearance (sofa↔table, chair↔wall, ...) | **Scalar minimum distance between two footprint polygons** (not center-to-center, not AABB gap) | Exact, reuses the existing footprint (`footprint_corners`) and an existing primitive (`point_segment_distance`); center-to-center over-counts large objects, AABB gap under/over-estimates for rotated objects |
| Functional/operating envelope (wardrobe door, drawer) | **A second, per-`semantic_type` convex polygon attached to the object's footprint** (same rotation math as `footprint_corners`), tested with the existing SAT `convex_polygons_overlap` | A circular sector (door swing, ≤180°) and a rectangle (drawer pull-out) are both convex — no new collision algorithm needed, only a new polygon *source* |
| Door swing arc | **A convex circular-sector polygon** (a coarse fan of points, chord-approximated), same SAT test | IFC's own model represents a swing as an arc on a plan; approximating it as a convex polygon keeps it inside the one collision primitive the whole codebase already uses |
| Circulation / walkway passability | **Minkowski-inflated occupancy grid + BFS connectivity** (not A*, not a navmesh, not a visibility graph) | See below |

**Circulation, argued specifically.** The three candidates the P2.5 brief
names (grid, navmesh, visibility graph) trade off exactly as the literature
says: visibility graphs give optimal paths but cost real pre-computation
(bitangent construction); navmeshes pay off at large/complex scale; grid A*
is "good-enough, fast-enough, simple-enough" and is explicitly named in one
source as the sweet spot for *exactly* this regime. Allure's rooms are
single-room, ≤20 objects, and P2.5's own exit gate only asks for a **boolean**
("can Allure detect a known circulation-blocking arrangement"), not an
optimal path or a rendered route. That downgrades the requirement from
*path planning* to *graph connectivity* — BFS on an inflated grid answers
"is entrance reachable to object" with certainty and no heuristic, at a
fraction of a visibility graph's implementation cost, and needs no new
dependency (Python `collections.deque`, stdlib only). A full A*/navmesh is
therefore evidence-rejected here as solving a harder problem (an optimal
route to render) than Allure has ever needed (a pass/fail signal) — matching
principle 20 ("if evidence demonstrates a simpler architecture is better,
choose the simpler architecture").

**Grid cell size and inflation radius**, both parameters, not
guesses: cell size = 0.05 m (half the smallest researched clearance
tolerance, so a real gap is never lost to quantization); inflation radius =
half of `PEDESTRIAN_WIDTH_M` (§P2.3) — the canonical Minkowski-sum
"shrink the walker to a point" step from the robotics literature above,
applied at room scale instead of robot scale.

### Exit gate: met

The representation table above is defensible per-row (each cites the
specific reason a *different* technique was picked, not one default reused
everywhere), and every one of the four rows reuses an existing geometry
primitive (`footprint_corners`, `convex_polygons_overlap`, `point_segment_
distance`) rather than adding a new collision algorithm.

---

## P2.2 — Constraint taxonomy

### The question the brief poses: separate classes, or attributes?

**Decision: two small orthogonal attributes on one violation type, not six
parallel classes.** `severity` (does it block commit: `hard` | `soft`) and
`category` (what physical truth it represents: `COLLISION` | `CLEARANCE` |
`CIRCULATION` | `FUNCTIONAL` | `ACCESSIBILITY` | `PREFERENCE`). A `category`
can take *either* severity depending on the measured deficit (e.g.
circulation: completely blocked = hard, narrow-but-passable = soft) — a
class-per-category design would need `HardCirculationViolation` and
`SoftCirculationViolation` as separate types for no benefit, since every
consumer (the resolver, the benchmark, the report) only ever needs to ask
"does this block commit" and "what kind of problem is this," which two
fields already answer unambiguously. This also costs nothing against the
existing schema: production's own `Violation.severity` (`app/spatial/
validation.py`) is already a bare string with exactly this shape, just never
given a second value — P2 is documenting and using that field's second value
for the first time, not inventing a new one.

### The seven concepts from the mission, mapped

| Mission concept | `category` | Default `severity` | Reason |
|---|---|---|---|
| 1. Collision | `COLLISION` | hard | unchanged from P0/P1 |
| 2. Clearance (pairwise minimum distance) | `CLEARANCE` | **soft** | a comfort/usability number (§P2.3's own sources give ranges, not physical impossibilities) — violating it makes a room worse, not physically wrong |
| 3. Circulation | `CIRCULATION` | **hard if zero path exists, soft if a path exists but is narrower than the researched minimum** | a room with literally no way to reach an object is broken the way `OUTSIDE_ROOM` is broken; a tight-but-passable room is a comfort issue |
| 4. Functional clearance (operating envelopes) | `FUNCTIONAL` | **soft** | computed against an *assumed* hinge-side/swing convention (no per-object evidence exists — `clearance_baseline.md` §5.2); treating a guessed convention as hard risks blocking a scene on a wrong guess, which principle 9/the standing "UNKNOWN over confidently wrong" rule forbids |
| 5. Accessibility | `ACCESSIBILITY` | **defined, not evaluated by default** | see below |
| 6. Operating clearance (door/appliance swing) | folds into `FUNCTIONAL` | soft | same mechanism as #4, not a separate category — a door swing IS a functional envelope |
| 7. Visual/design preference | `PREFERENCE` | **defined, not implemented at all in P2** | no signal anywhere in the pipeline (brief, VLM, or photo grounding) computes symmetry/balance; inventing a scorer with no measured need repeats the mistake P1's decision doc explicitly avoided for a global solver |

**Why `ACCESSIBILITY` is defined but not enforced by default.** The ADA
numbers gathered in §P2.1 (36 in / 0.91 m accessible route, 30×48 in / 0.76×
1.22 m clear floor at seating, 60 in / 1.52 m turning circle) are real and
sourced from the governing standard itself, not a paraphrase — but Allure has
**no signal anywhere** (not in a design brief, not in VLM output, not in
photo grounding) that a given scene is being designed to ADA compliance
versus ordinary residential comfort. Enforcing the ADA numbers unconditionally
would silently fail many legitimate, comfortable small-apartment layouts that
were never asked to be wheelchair-accessible. The category exists in the
schema (so a caller *can* ask for it), the numbers are recorded (§P2.3), and
the general circulation check (§P2.1, `CIRCULATION`) uses the smaller,
broadly-converged **36 in / 0.91 m** figure by default — which happens to
equal the ADA accessible-route width anyway, so the default is never *less*
accommodating, only not *additionally* stricter (60 in turning circles, 48 in
clear floor at every seat) without being asked.

### Exit gate: met

Every one of the mission's seven concepts maps to exactly one
`(category, severity-rule)` pair above — unambiguous by construction, since
`severity` for six of seven categories is a fixed constant and the seventh
(`CIRCULATION`) has an explicit, measured, non-arbitrary rule for which value
applies.

---

## P2.3 — Residential clearance policy (sourced, not invented)

Every figure below cites the search(es) that produced it and the number of
independently-converging sources; principle 19 (label non-reproducible or
under-sourced claims) applies — anything with only one source is marked.

| Rule | Subject ↔ target | Minimum (m) | Sources | Convergence |
|---|---|--:|---|---|
| Seating-to-table reach | `sofa`/`loveseat`/`armchair` ↔ `coffee_table` | **0.30** | "12 in absolute minimum... 14-18 in comfortable" | 1 aggregated search, multiple underlying retailer sources cited together — flagged as the weakest-sourced figure in this table |
| Primary walkway | any floor object ↔ circulation path | **0.90** (36 in) | ADA accessible route (access-board.gov, governing standard) **and independently** the general furniture-clearance search **and** NKBA primary traffic path | **3 independent sources, same number** — the strongest-sourced figure here |
| Secondary walkway | any floor object ↔ circulation path, non-primary | **0.65** (≈25.5 in, midpoint of 24-30 in) | general furniture-clearance search | 1 source |
| Dining chair pull-back | `chair` ↔ wall/obstruction behind it | **0.90** (36 in, pull-back-only default; 1.05-1.20 m if the room's circulation also runs behind seated diners — not enforced by default, no signal distinguishes the two cases) | dedicated dining-chair search | 1 aggregated search, internally consistent across its own multiple cited sources |
| Bed-side access | `bed` ↔ wall/`wardrobe`/`bedside_table` | **0.60** (24 in, the sourced minimum; 30-36 in is "ideal," not enforced) | dedicated bedroom-clearance search | 1 aggregated search |
| Wardrobe door swing (functional envelope depth) | `wardrobe` front | **0.90** | two independently-phrased figures in the same search ("800-900mm... at least"; "90-100cm... workable") | 2 converging figures, 1 search |
| Kitchen work aisle | `kitchen_counter`/`kitchen_island`/`bar_counter` ↔ same category | **1.05** (42 in, single-cook default; 1.22 m/48 in if evidence of a multi-cook or appliance-opposite case — not distinguishable from grounding today) | NKBA (dedicated search) | 1 source, but NKBA is itself the governing US kitchen-design standard body, not a blog |

`PEDESTRIAN_WIDTH_M = 0.55` (a person's shoulder width plus a small margin,
used only for the Minkowski inflation radius in circulation, §P2.1 — distinct
from the 0.90 m *walkway* figure above, which is a path's clear width, not a
person's own width; conflating the two would double-inflate every obstacle).

**What is deliberately NOT in this table**, matching P2.3's own instruction
to classify what's universal vs. context-dependent vs. uncertain:
`sofa ↔ sofa`, `sofa ↔ TV`, any pair with no sourced number and no close
analogue above — these emit **no clearance constraint** (silently passing)
rather than a fabricated threshold; §P1's own precedent (never invent
evidence) applies here identically. `preference`-category rules (symmetry,
visual balance) are not in this table by design (§P2.2).

### Exit gate: met

Every rule above traces to a named search and a stated source count; rules
with no research backing were left out rather than filled with a plausible-
sounding guess.

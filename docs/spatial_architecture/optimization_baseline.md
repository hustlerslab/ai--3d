# P3.0 — Global-optimization baseline inspection

Read from the live tree on 2026-09-16, continuing directly from
`baseline.md`/`collision.md`/`clearance_baseline.md`/`clearance.md`. Nothing
below is re-derived from memory.

## 1. What is currently optimized, precisely

`app/planning/compiler.py:place_objects` and `research/spatial_architecture/
collision_solver.py:resolve_collisions` are BOTH the same algorithm family
(confirmed independently for each in P1's research): a **fixed, deterministic
priority order**, then **greedy first-valid-candidate acceptance**, with
**zero backtracking across already-committed objects**.

`place_objects`'s ordering (`_ordered`, `compiler.py:532`), read exactly:

```python
pending = sorted(plan.items, key=lambda i: (i.priority, rank(i), footprint(i), i.object_key))
```

`priority` (explicit, from the plan) first, then `rank` (33 for anything
`on_surface`, else a fixed `ANCHOR_RANK` lookup by `semantic_type` — larger
anchor furniture goes first), then `footprint` (bigger on-surface items claim
their host surface before smaller ones), then `object_key` for a stable,
deterministic tie-break. A second pass (`while pending and guard < 10`)
defers any item whose `relation.target_key`/`support_key` isn't placed yet.
**This is a topological + priority sort, computed once, before any placement
begins — not re-evaluated as placement proceeds.**

Per item, `place_objects` (`compiler.py:583-662`) tries a **ranked list of
candidates** (wall-aligned, relation-derived, surface-derived, or hint-
derived), builds each as a real `SceneObject` inside a `working` copy that
already contains every earlier commitment, and takes the **first candidate**
`validate_object` accepts. There is exactly **one existing local-retry
mechanism** — `shrink_steps = (1.0, 0.8, 0.65)` for a fixed list of
semantic types (`kitchen_counter, wardrobe, curtains, bookshelf, sideboard`)
— that reduces an item's OWN dimensions and retries its OWN candidates if
none fit; it never revisits or moves any other object.

`resolve_collisions` (P1, `collision_solver.py`) orders by
`(-Confidence.value, object_id)` instead of the plan's priority/rank, but is
otherwise the identical pattern: commit sequentially, repair a conflict with
a local candidate lattice, no cross-object backtracking.

## 2. What is NOT optimized

- **No global objective function exists anywhere.** Neither `place_objects`
  nor `resolve_collisions` computes a scene-level score; each only asks
  "does THIS candidate for THIS object pass `validate_object`," a per-object
  boolean, never "which arrangement of ALL objects is best."
- **No object, once committed, is ever revisited.** Confirmed by reading:
  neither function contains any code path that removes or moves an
  already-`working.objects.append`-ed object once a LATER object fails.
- **Clearance/circulation (P2) are not part of placement at all.** `clearance_
  engine.py`'s four checks run only as a post-hoc report in
  `integration_benchmark.py` — they cannot influence which candidate
  `place_objects`/`resolve_collisions` picks, because neither function calls
  them (confirmed by grep: `clearance_engine` has zero imports outside
  `integration_benchmark.py` and its own tests).

## 3. What decisions are irreversible, precisely

Once `working.objects.append(candidate)` succeeds inside `place_objects`'s
inner loop (or the equivalent commit in `resolve_collisions`), that object's
**position, rotation, and which wall/surface it claimed** are fixed for
every subsequent item in the same pass. The only thing that can later change
about it is a full second run of `resolve_collisions` moving it in response
to a *later*-discovered collision — but that repair only reacts to a
conflict already measured against the current arrangement; it cannot
anticipate that a smarter earlier choice would have avoided the conflict
altogether.

## 4. Where greedy failure can occur — a concrete, constructible class

**Two same-rank objects compete for one finite resource (a single long wall,
or one usable region), and the ranking order determines who gets the good
spot — with no mechanism to notice a better global split exists.**

Concretely, constructible from what §1 established: a room with exactly one
wall long enough for wall-aligned furniture, and two anchor-ranked items
(e.g. a `tv_unit` and a `bookshelf`, both plausible wall-aligned pieces of
similar `ANCHOR_RANK`) whose combined width exceeds the wall's length by a
small margin — but each individually fits, and a **specific split** (e.g.
TV unit pushed to one end, bookshelf given the remainder) fits both, while
the **centered-first** placement `place_objects`'s own candidate ranking
would naturally try first for the higher-ranked item consumes exactly enough
extra margin that the second item's every candidate collides. Because
`_ordered` fixes the whole sequence before any geometry is examined, and
`place_objects` never revisits item 1 once item 2 fails, the result is:
item 1 well-placed, item 2 **unplaced or shrunk** (via the one existing local
retry) — a scene the brief's own P3 example describes exactly
("A1 + B + C creates a dead-end; A2 + B + C creates a globally superior
room"). This is stated as a *class* (not asserted from a specific past
failure — none is on record for the brief path, which the P1 architecture
decision already noted: 0/547 hard violations measured) because it follows
directly from the algorithm's own structure (§1-§3), not from an observed
bug; P3.2 constructs this class as an actual adversarial benchmark scene to
turn the theoretical argument into a measurement.

## 5. What this baseline means for P3's core question

The theoretical failure class in §4 is real and constructible, but its
**existence does not by itself answer "does Allure need global
optimization"** — P1's own measured result (0/547 hard violations across 12
real briefs) shows the class may be rare or absent in practice at Allure's
actual object counts and room shapes. P3.1-P3.6 must measure whether the
class actually occurs at a rate and severity that justifies a more complex
architecture, not merely that it is theoretically possible — matching the
mission's own instruction not to assume the answer is yes.

**Exit gate: met.** §4 names a concrete, constructible scene class where
local greedy placement can produce a worse global solution than an
alternative split — derived from reading the actual ordering/commit code,
not assumed.

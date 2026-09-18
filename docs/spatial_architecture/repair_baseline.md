# P4.0 — Repair baseline inspection

Read from the live tree on 2026-09-16, continuing directly from
`optimization_baseline.md`/`optimization.md`/`decisions.md`'s P1-P3 entries.
Nothing below is re-derived from memory.

## 1. What currently constitutes a "failure," precisely

Two independent violation shapes exist, confirmed unchanged since P1/P2:

```
app/spatial/validation.py: Violation(code, severity, message, object_id, related_id)
    codes: OUTSIDE_ROOM, COLLIDES_WALL, COLLIDES_OBJECT, BLOCKS_DOOR,
           ROOM_NOT_FOUND, ORPHAN_OPENING, INVALID_ROOM_POLYGON
    severity: bare string, always "hard" today (P2 gave the FIELD a second
              meaning in the taxonomy, but validate_scene itself never emits
              "soft" - that only happens in clearance_engine.py)

research/spatial_architecture/clearance_engine.py: ClearanceViolation(
    subject_id, target_id, category, constraint, required_m, actual_m,
    deficit_m, severity, coordinate_frame)
    category: CLEARANCE | FUNCTIONAL | CIRCULATION
    severity: "hard" (circulation fully blocked) | "soft" (everything else)
```

A "failure" for P4's purposes is any element of `validate_scene(scene)` with
`severity=="hard"`, plus any `ClearanceViolation` with `severity=="hard"`
(fully-blocked circulation) — matching `optimization.md` §3's `HardCount`
definition exactly, not a new definition.

## 2. How a failing object is identified today

`object_id`/`subject_id` always names the primary object. For `COLLIDES_WALL`
and `BLOCKS_DOOR`, `related_id` names a wall/opening — **not movable**. For
`COLLIDES_OBJECT` and pairwise `CLEARANCE`, `related_id`/`target_id` names a
**second real object** — either could move. Confirmed by re-reading
`validate_scene`: it calls `validate_object` once per object, so a symmetric
pair (A collides with B) is reported **twice** — once as `(A, B)`, once as
`(B, A)` — already noted and relied on in P1's benchmark numbers
(`spatial_architecture_report.md` §5). Neither `Violation` nor
`ClearanceViolation` currently states *which* of the two is at fault; P1's
`collision_solver.py` makes that call itself (lower `Confidence.value` moves)
— that logic lives in the repair layer, not the violation record.

## 3. Responsibility gap found by this inspection: circulation

`circulation_violations` (`clearance_engine.py`) reports `subject_id=
"entrance"`, `target_id=<unreachable object>` — it names the **victim**, not
any blocking object. Re-reading `_clearance_field` and the widest-path search:
the algorithm computes a scalar distance-to-nearest-obstacle per grid cell
but **discards which obstacle produced that minimum** once the scalar is
returned. There is currently **no way to ask "which object is blocking this
path"** — a real gap P4.2 must address before circulation violations can be
locally repaired by moving a specific object (see `repair_baseline.md` §6).

## 4. Which candidates are already available for reuse

- **P1's candidate lattice** (`collision_solver.py`): wall-tangent slide
  (evidence-preserving, for `AGAINST_WALL` objects), a small perpendicular
  fallback (clears wall-embedding residue), and a radial ring (freestanding
  objects) — all deterministic, all already tested (P1, 6 unit tests) and
  measured (P1's photo benchmark: 14 moved, 1 unresolved out of the frozen
  21-image fixture).
- **P3's `PlacementTask`/candidate-list abstraction** (`scene_optimizer.py`):
  a *different* representation — a pre-enumerated ranked list per object,
  not a geometric offset lattice. P1's lattice is *generated on demand* from
  geometry (wall direction, room centroid); P3's candidates are *supplied up
  front*. P4 needs both: P1's lattice for real `Scene`/`SceneObject` repair
  (no pre-supplied candidate list exists once a scene is built), P3's
  strategies (`solve_backtracking`, `solve_beam`) for the escalation ladder
  once local repair is exhausted.

## 5. Can the current solver be safely re-entered? What's mutable?

`Scene` is a Pydantic model; every repair primitive built so far
(`collision_solver.resolve_collisions`, `scene_optimizer`'s five strategies)
already operates by **committing into a fresh `working` copy**
(`scene.model_copy(...)`), never mutating the input `Scene` in place —
confirmed by re-reading both files. This means:

- **Rollback is trivial and already the default pattern**: any repair
  attempt that doesn't validate clean is simply not committed; the caller's
  original `Scene` is untouched unless the caller reassigns it. No new
  rollback mechanism is needed — P4 inherits this "build a new candidate
  scene, only keep it if it validates" pattern rather than inventing one.
- **Previous placements CAN be reconsidered** — nothing prevents rebuilding
  `working` with an earlier object at a different position — but **no
  existing code does this today**: `collision_solver.py`'s single pass
  commits each object once, in confidence order, and never revisits an
  earlier commitment once later objects are processed. This is the same
  "no cross-object backtracking" limitation `optimization_baseline.md` §3
  already established for `place_objects` — P1's repair layer inherited it,
  it was not a new gap P4 discovered.

## 6. Can the current validator explain the exact cause?

**Partially.** `Violation`/`ClearanceViolation` both name the constraint
violated and the object(s) involved with a numeric deficit where applicable
(`ClearanceViolation.deficit_m`) — enough to *classify* a failure
mechanically (§8 below). What neither currently provides: **why** a
constraint is violated at the representation level — e.g. `COLLIDES_WALL`
gives no signal distinguishing "the object is genuinely misplaced" from "the
wall's own fitted geometry is tilted beyond what the flat schema can
represent" (the exact P5-relevant finding from `spatial_architecture_report.md`
Finding 2). P4's failure-analysis phase (P4.13) needs a classification layer
*on top of* the raw violation, not a change to the violation types
themselves — building that classification is in scope for P4; changing wall
representation is explicitly P5's job, not P4's (mission's own instruction).

## 7. Duplicate-identity failures: already correctly excluded

P1's own measured residual (`spatial_architecture_report.md` §7a) is exactly
the case P4.2 asks to distinguish: two `tv_unit` groundings of one physical
object. That finding is **already on record as NOT movement-repairable** —
P4 does not need to re-discover this, only to formalize it as a named
terminal classification (`UPSTREAM_REQUIRED` / `OBJECT_IDENTITY_FAILURE`, per
P4.13's own taxonomy) so future repair attempts recognize the pattern instead
of re-litigating it.

## 8. Trace: placement → violation → failure state → candidate state → validation

```
1. PLACEMENT     greedy solver commits an object (place_objects OR the
                 photo bridge's grounding_to_scene) into Scene.objects.
2. VIOLATION     validate_scene(scene) + clearance_engine's four checks
                 produce Violation / ClearanceViolation records - each
                 names its object(s), a severity, and (clearance only) a
                 numeric deficit.
3. FAILURE STATE severity=="hard" (either type) => scene is invalid;
                 severity=="soft" => scene is valid but imperfect (P2.2).
4. CANDIDATE     P1's lattice (geometric, on-demand) or P3's pre-supplied
   STATE         ranked list, depending on which repair layer is invoked.
5. VALIDATION    re-run validate_object/validate_scene (+ clearance checks
                 if in scope) on the candidate before ever committing it.
```

No ambiguity remains in this chain: every step above cites the exact
function that performs it, read from the live code, not assumed.

**Exit gate: met.**

# P2.0 — Clearance baseline inspection

Read from the live tree on 2026-09-16 (continuing directly from
`baseline.md`/`collision.md`; not re-deriving what those already established).

## 1. What already exists

Re-confirmed unchanged since P0/P1: `Scene`/`SceneObject`/`Room`/`Wall`/
`Opening` (`app/scene/schema.py`), the 2D geometry kernel (`app/spatial/
geometry.py`: `footprint_corners`, `convex_polygons_overlap` SAT, `point_
inside_polygon`, `wall_rectangle`), `validate_object`/`validate_scene`
(`app/spatial/validation.py`), `place_objects` (`app/planning/compiler.py`),
and the P1 `resolve_collisions` DFS-family resolver
(`research/spatial_architecture/collision_solver.py`). None of this is
duplicated below — only what is new to P2 is designed from here on.

## 2. The one existing clearance concept, read precisely

`app/spatial/validation.py` has exactly one clearance-shaped check, H4
`BLOCKS_DOOR`:

```python
DOOR_CLEARANCE_DEPTH = 0.75   # a single global constant, every door, every context
```

`door_clearance_rects` builds a fixed 0.75 m-deep rectangle on **both** sides
of every door opening, regardless of the door's own width, its swing
direction, or what's on the other side. This is the baseline's only positive
evidence that "clearance" as a concept is already anticipated in the schema
— and its only negative evidence that today's implementation is a single
scalar applied uniformly, not a taxonomy.

**Nothing else in `app/` computes a distance-based (non-overlap) constraint.**
Grep for `clearance|swing|circulation` across `app/` turns up only this one
constant and this one function.

## 3. What is genuinely absent (confirmed by reading, not assumed)

| Concept the P2 mission distinguishes | Present in `app/`? | Evidence |
|---|---|---|
| Object-to-object minimum clearance (not just non-overlap) | **No** | P1's `resolve_collisions` and H3 `COLLIDES_OBJECT` both stop at zero-overlap; touching is explicitly accepted (`convex_polygons_overlap`'s own docstring: "Touching edges... do NOT count as overlap") |
| Door swing arc (as geometry, not a flat rectangle) | **No** | `Opening` has `type, wall_id, position, width, height, sill_height` — no swing direction, no hinge side, no open angle |
| Circulation / walkway passability | **No** | no path, graph, or grid structure anywhere in `app/spatial` or `app/planning` |
| Object-specific operating envelope (wardrobe doors, drawers) | **No** | `SceneObject` has `dimensions`, `mount`, `parent_id` — no envelope field, no per-`semantic_type` behavior table |
| Accessibility path width | **No** | not referenced anywhere |
| Hard/soft/preference constraint taxonomy | **No** | every existing `Violation` (`app/spatial/validation.py`) has `severity: str = "hard"` — a string, not an enum, and every current check IS hard; nothing in the codebase has ever emitted `"soft"` |

## 4. What already-known object metadata P2 can reuse without inventing new geometry

- `SceneObject.dimensions: Vec3` (width, height, depth at scale 1) — the same
  field the P1 resolver already reads for footprints.
- `SceneObject.semantic_type: str` — the catalogue's own vocabulary
  (`app/catalog/catalog.py`: `sofa, loveseat, armchair, coffee_table,
  tv_unit, dining_table, chair, bed, wardrobe, bedside_table, bookshelf,
  rug, floor_lamp, plant, restaurant_table, banquette, booth_seating,
  bar_counter, lounge_sofa, reception_desk, workstation, office_chair,
  meeting_table` — 23 values total). A clearance policy keyed on
  `semantic_type` needs no new taxonomy; it reuses this one.
- `Opening.width`, `Opening.wall_id`, `Opening.position` — enough to build a
  swing arc's footprint given a hinge-side and open-angle convention (both
  absent today and must be added, §5).
- `Room.boundary` — already the polygon P0/P1 use for `OUTSIDE_ROOM`; the
  same polygon a circulation check needs as its walkable region's outer
  bound.

## 5. Exactly what new information P2 needs, named precisely (the exit-gate deliverable)

1. **A per-`semantic_type` clearance policy table** (object ↔ object and
   object ↔ circulation minimum distances) — does not exist, must be
   researched (P2.3) before being invented.
2. **A door hinge-side + open-angle convention**, so a swing arc can be
   computed from the *existing* `Opening` fields rather than adding new ones
   speculatively — a single deterministic default is enough (P2.6) since no
   evidence yet distinguishes left- from right-hung doors in the pipeline.
3. **A severity taxonomy beyond the current bare `"hard"` string** — `Violation.
   severity` already has the field, just never a second value; P2.2 defines
   what the second (and later) values mean before anything emits them.
4. **A circulation representation** — deliberately not designed yet; P2.5
   researches whether Allure's room scale (≤20 objects, single-room, no
   multi-room pathfinding requirement measured anywhere) justifies a navmesh/
   grid/graph, or whether a much cheaper test suffices.
5. **A functional/operating envelope per relevant `semantic_type`** — new,
   object-class-specific, P2.6.

Nothing above duplicates an existing structure: each is additive to
`Scene`/`SceneObject`/`Opening`/`Violation`, or lives entirely in new
`research/` data (a clearance policy table is data, not a schema change).

**Exit gate: met.** The five items in §5 are exactly what's missing, named
without re-deriving anything §1-§4 already answers from the live code.

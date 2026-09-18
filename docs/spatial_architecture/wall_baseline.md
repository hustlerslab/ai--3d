# P5.0 — Wall representation baseline inspection

Read from the live tree on 2026-09-16. Nothing below is re-derived from
memory — every claim cites the exact file/line read this session.

## 1-7. What a wall currently stores, exactly (`app/scene/schema.py:65-71`)

```python
class Wall(BaseModel):
    wall_id: str
    start: Vec2      # (x, z) — NO Y component anywhere in the type
    end: Vec2        # (x, z)
    thickness: float = 0.15
    height: float = 2.8
    material: str = "paint_white"
```

- **Finite**: yes — `start`/`end` are endpoints, not an infinite line (§P5.5
  answer: already correct, confirmed by reading, not assumed).
- **Thickness**: yes, explicit, already a scalar field (§P5.6 answer:
  already correct).
- **Height**: yes, explicit scalar (constant along the wall's length).
- **Orientation**: only implicit — a 2D direction (`end - start`) in the XZ
  plane. **There is no field for the wall's 3D normal, and no way to
  represent that the wall leans (a non-zero Y-component in its true fitted
  normal).**
- **Local coordinate frame**: not represented at all — nothing computes or
  stores a `T_world_wall` transform (§P5.4's gap, confirmed absent).
- **Tilt**: **cannot be represented.** `start`/`end` are 2D; a `Wall` is
  implicitly a straight vertical extrusion of a 2D line from `y=0` to
  `y=height`. There is no field whose value could encode "this wall leans."

## 8-13. Openings, glass, partial walls, curved walls

- **Openings** (`app/scene/schema.py:54-62`): already a **separate**
  top-level entity (`Opening`), referencing `wall_id` + a scalar `position`
  along the wall — not nested inside `Wall`. §P5.7's question ("should
  openings be inside Wall or separate SpatialGraph objects") is **already
  answered by the existing schema**: separate, and this works (P2's
  `door_swing_violations`/`BLOCKS_DOOR` both consume it without friction).
  No change needed here.
- **Glass / partition semantics**: no field distinguishes a physical
  barrier from a visual surface. Every `Wall` is treated as an opaque solid
  by `validate_object`'s H2 check, unconditionally. The wall-quality
  gate (Phase 6, `research/spatial_engine/wall_quality.py`) already flags a
  `moodboard_room_bathroom` mirror case as a known, unfixed limitation
  (`wall_quality_abstention_report.md`) — carried forward, not solved here
  (§P5.8, evidence below).
- **Curved walls**: `start`/`end` (a straight segment) cannot represent a
  curve. No curved-wall evidence exists anywhere in the 48-case fixture
  (confirmed: every wall Phase 6 has ever fit is a straight RANSAC segment).

## 14-17. Where 3D evidence exists, and the exact two lines where it is discarded

**The evidence is not lost at the perception layer.** Phase 6's
`extract_wall_features` produces a full 3D unit `normal` (3 components) per
wall — the real, measured case: `normal=[0.06009, 0.1888, -0.98018]` on
`moodboard_room_master_bedroom`'s `wall_0`
(`spatial_architecture_report.md` Finding 2). `WallEvidence` (`scene_from_
photo.py:58-76`) carries this full 3-component `normal` through unchanged.

**It is discarded at exactly two lines, both in `scene_from_photo.py`,
both silently:**

```python
# line 147, _resolve_yaw() — the object's own wall-relative yaw:
forward = (normal[0], normal[2])          # normal[1] (the tilt) never read

# line 195, grounding_to_scene() — the wall's own centerline point:
p0 = (-w.offset * n[0], -w.offset * n[2])  # n[1] never read
```

Both lines project the wall's true 3D normal onto the XZ plane as if it
already had zero Y-component — not an approximation applied deliberately
with a measured residual, but a silent drop: the code never reads `normal[1]`
at all. `app/scene/schema.py:Wall` has no field that could hold it even if
these lines wanted to keep it — **the representation, not the extraction
code, is the root constraint**, matching this phase's own framing
("investigate as a REPRESENTATION problem first").

## Downstream systems that assume a vertical (Manhattan-height) wall

- `app/spatial/geometry.py:wall_rectangle(start, end, thickness)` — builds
  ONE 2D rectangle for the wall's entire height. A tilted wall's true XZ
  footprint drifts horizontally by `height * tan(tilt)` from floor to
  ceiling (at 11°, `2.8 m * tan(11°) ≈ 0.54 m` over the full wall height) —
  `wall_rectangle` has no height parameter, so it can only ever represent
  ONE cross-section, implicitly the one at the fitted plane's own reference
  height.
- `app/spatial/validation.py:validate_object` H2 — calls `wall_rectangle`
  once per wall and tests EVERY object's footprint against that single
  cross-section, regardless of the object's own height range. This is
  exactly why a large object (bed, sofa — spanning more vertical extent
  relative to its own footprint's sensitivity, and in practice measured
  with the largest footprint-reconstruction residuals, 0.68-0.89 m) shows
  the worst `COLLIDES_WALL` errors while small objects (bedside tables,
  ~0.1 m residual) barely show it (`spatial_architecture_report.md`
  Finding 2's own size-proportional pattern — now explained precisely,
  not just observed).
- `app/blender/manifest.py` — builds wall geometry as a straight vertical
  extrusion (confirmed by the module's own `scene_forward`/wall-building
  pattern read in P1); a tilted wall would render upright regardless of its
  true measured lean.
- `research/spatial_architecture/collision_solver.py` and
  `clearance_engine.py` — both call `wall_rectangle`/`object_footprint`
  and inherit this limitation without adding a new one of their own (they
  are downstream of the same 2D kernel, not an independent source of loss).

## Exit gate: met

Every one of the 17 P5.0 questions is answered above from the literal code,
with the exact two lines where 3D tilt information is discarded named
precisely, and the exact downstream mechanism by which that loss becomes a
measured `COLLIDES_WALL` error (a single fixed-height 2D cross-section
tested against every object regardless of height) identified without
speculation.

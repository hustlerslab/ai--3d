# P5.1-P5.4 — Wall research, representation candidates, minimum sufficient model, local frame

Continues from `wall_baseline.md`. Covers four phases in one document, as
`collision.md`/`clearance.md`/`repair.md` did for P1/P2/P4.

## P5.1 — Research

### Search strategy and sources

`"IfcWall IfcExtrudedAreaSolid extrusion direction tilted wall representation
IFC standard"`, `"non-Manhattan indoor room layout reconstruction tilted wall
plane fitting computer vision"`, `"finite oriented plane patch representation
robotics collision geometry world model"`, `"architectural wall batter rake
slanted wall definition construction"`, `"signed distance field vs mesh
collision architectural scene memory computational cost small scene"`.

### The decisive finding

**buildingSMART's own IFC standard already distinguishes exactly this
case**, at the schema level, not as an afterthought:
[`IfcExtrudedAreaSolid`](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcExtrudedAreaSolid.htm)
defines a wall's solid as a 2D profile swept along an `ExtrudedDirection` —
and IFC's own [`IfcWall` documentation](https://github.com/buildingSMART/IFC4.3.x-development/blob/master/docs/schemas/shared/IfcSharedBldgElements/Entities/IfcWall.md)
states the rule precisely: *"If the wall body can be described by a
**vertical** extrusion of a polygonal footprint with constant thickness...
the subtype `IfcWallStandardCase` should be used. If the extrusion is not
equal to global Z, then the general `IfcWall` should be used"* — i.e., the
*only* schema difference between an ordinary vertical wall and a leaning one
is **which direction the same 2D profile gets extruded along**, not a
different representation family. This is independent confirmation (a
governing international standard, not a paper's proposal) of the fix this
phase derives from first principles in §P5.3: Allure's `Wall` is already
"a 2D profile, extruded" — it simply hardcodes the extrusion direction to
`(0, 1, 0)` where IFC leaves it general.

**Real buildings genuinely have non-vertical walls.** [Batter](https://en.wikipedia.org/wiki/Batter_(walls))
is the standard architectural term for an intentionally-sloped wall
(retaining walls, fortifications, some residential foundations) — tilt is a
real physical phenomenon this program's data can encounter, not merely a
reconstruction artifact to be tolerated.

**Non-Manhattan room-layout literature** confirms per-wall Manhattan/non-
Manhattan classification via RANSAC plane fitting is the field's standard
approach (exactly Phase 6's own `extract_wall_features` + verticality-
tolerance gate) — no better *perception*-side alternative surfaced; the gap
this phase closes is specifically in the *downstream representation*, which
the literature does not address (papers stop at plane fitting, they do not
propose a Scene-graph wall schema).

**Mesh/SDF collision** genuinely outperforms analytic geometry only at scale
the search results themselves name — "large numbers of objects or detailed
meshes containing thousands of nodes and triangles"; for Allure's regime
(≤20 objects, a handful of walls per room) this is the same
representation-mismatch argument that already rejected mesh/SDF-scale
approaches in P1 (collision) and P3 (search) — reconfirmed here for walls
specifically, not assumed by analogy.

## P5.2 — Representation candidates, compared

| Candidate | Represents tilt? | Finite? | Thickness? | Openings? | Cost | Verdict |
|---|---|---|---|---|---|---|
| A. Infinite plane | Yes (any normal) | No | Separate bookkeeping needed | Awkward (infinite surface, "hole" is unnatural) | Low | **Rejected** — Allure already needs finite walls (openings, room bounds); an infinite plane re-opens a problem already solved |
| B. Finite oriented plane patch | Yes | Yes | Needs a second offset plane or extra field | Needs a sub-region cutout | Medium | **Not chosen** — expressively similar to E but without E's exact match to `wall_rectangle`'s existing 2D-rectangle-per-height calling convention |
| C. Wall segment (current) | **No** | Yes | N/A (no volume) | Yes (separate `Opening`) | Lowest | Current baseline — the representation-loss source |
| D. Wall segment + thickness (current, exactly) | **No** | Yes | Yes | Yes | Lowest | Current baseline — thickness already present, tilt still absent |
| **E. Extruded polygon (generalized extrusion direction)** | **Yes** | Yes | Yes (unchanged) | Yes (unchanged) | **Same as D at runtime for the 100% of walls that are vertical** | **CHOSEN** |
| F. Parametric wall (curves, variable thickness, etc.) | Yes | Yes | Yes | Yes | High | **Rejected** — no curved-wall or variable-thickness evidence exists anywhere in the 48-case fixture; matches principle 9 ("do not turn Allure into a full BIM system without evidence") |
| G. Mesh wall | Yes (arbitrarily) | Yes | Implicit in geometry | Yes (boolean cut) | High (own §P5.1 finding) | **Rejected** — solves a harder problem than measured (see mesh/SDF finding above) |
| H. Hybrid | — | — | — | — | — | **Not a distinct candidate here** — E *is* the hybrid: a strict superset of D that costs nothing when unused (§P5.3) |

Every "can it represent X" sub-question the brief poses (vertical, tilted,
finite, thickness, height, room boundary, doorway, window, partial wall,
irregular wall) is answered **yes** by E except curved walls and glass
semantics, both explicitly out of scope (no evidence, §P5.8 below).

## P5.3 — Minimum sufficient representation

**One new field, added to a research-only wrapper, not to `app/`:**

```
extrusion_direction: Vec3 = (0.0, 1.0, 0.0)   # unit vector, need not be vertical
```

Everything else `Wall` already has (`start`, `end`, `thickness`, `height`)
is kept **unchanged** — confirmed sufficient by `wall_baseline.md` §1-13.
This is deliberately the **smallest possible change**: for the 100% of
walls where `extrusion_direction == (0, 1, 0)` (every wall in every existing
brief/photo scene measured so far), every computation below is byte-
identical to today's — zero behavioural change, zero regression risk, by
construction, not by testing alone.

**Field provenance** (required/optional/derived/observed):

| Field | Status | Source |
|---|---|---|
| `start`, `end`, `thickness`, `height` | Required, observed | unchanged (Phase 6 fitting) |
| `extrusion_direction` | **Derived**, not separately observed | computed from the SAME fitted 3D plane normal Phase 6 already measures (§P5.4's formula) — no new perception capability needed |

**Rejected additions** (research-backed, not merely unconsidered): variable
thickness along the wall's length (no evidence — every fitted wall in the
48-case fixture has one RANSAC-fit thickness); a full local `T_world_wall`
stored ON the `Wall` object itself (§P5.4 computes it on demand from the
four fields above — storing a redundant transform risks it drifting out of
sync with `start`/`end`, a correctness hazard with no benefit, since the
transform is cheap to recompute).

## P5.4 — Wall-local coordinate frame

```
origin  = (start.x, 0.0, start.z)                          # floor-level start point
tangent = normalize(end - start), embedded in XZ, y=0       # along the wall
up      = extrusion_direction                                # the wall's own "vertical"
normal  = normalize(cross(tangent, up))                       # the wall's fitted plane normal

T_world_wall = [tangent | up | normal | origin]   (a 4x4 rigid transform)
```

`up` is **derived directly from the wall's own fitted 3D plane normal** n
(no new evidence needed): `up = normalize(world_up - n * dot(world_up, n))`
— the projection of world-up onto the wall's fitted plane. This reduces to
exactly `(0, 1, 0)` when `n`'s Y-component is zero (an ordinary vertical
wall) and tilts smoothly otherwise — verified against the real measured case
(`normal=[0.06009, 0.1888, -0.98018]`) below.

**Round-trip test** (implemented in `wall_geometry.py`, see tests): for 50
random world points, transform world → wall-local → world; maximum error
must be at floating-point precision (< 1e-9 m). This is not "the
representation is probably reversible" — it is measured on every test run.

**No silent flattening.** Every function that consumes `extrusion_direction`
either uses it correctly (the height-aware cross-section, §wall_geometry.py)
or is unaffected because it never needed a wall's vertical extent in the
first place (e.g., `point_inside_polygon` for room bounds, which already
operates in plan-view XZ regardless of wall tilt). No function in this
program's new code path takes `extrusion_direction` as an input and
discards it — grep-verifiable in `wall_geometry.py`.

## Exit gate (all four phases): met

The representation table (§P5.2) compares eight candidates against the
brief's own required capabilities; the minimum sufficient model (§P5.3) adds
exactly one field, derived (not newly observed) from evidence Phase 6
already produces; the local frame (§P5.4) is explicit, computed from that
one field, and round-trip-tested rather than assumed reversible.

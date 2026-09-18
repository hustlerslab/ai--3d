# P6 — Coordinate-frame audit, research, and canonical architecture

Continues from `wall_geometry.md`/`decisions.md`'s P5 entry. Covers the
audit, research, canonical-frame decision, frame taxonomy, and downstream
compatibility analysis in one document, per this program's established
pattern (`collision.md`, `clearance.md`, `repair.md`, `wall_geometry.md`).

## Audit — traced from the live code, not inferred from naming

| Subsystem | Current frame | Units | Handedness | Up | Forward | Transform explicit? | Risk |
|---|---|---|---|---|---|---|---|
| Source photo pixels | IMAGE | px | n/a (2D) | n/a | n/a | n/a — never converted to a rigid transform, correctly (it's a projection, §below) | None |
| MoGe-2 raw output | CAMERA | m | right | -Y (OpenCV: Y down) | +Z | **Yes** — `metric_geometry.py:_to_canonical`, one function, used nowhere else, docstring states the exact convention and that it is a 180° rotation about X | None — already correct and isolated |
| `app.scene.schema.Scene` | ROOM | m | right | +Y | -Z | **Yes** — `Scene.coordinate_system` field states this explicitly; independently verified against a real footprint corner in P1 | None |
| `app.spatial.geometry.footprint_corners` | OBJECT (local) → ROOM | m | right | +Y | -Z | **Yes**, but the rotation sign convention (`cos(-rotation), sin(-rotation)`) is explained only in a one-line comment, not a named transform function | Low — correct (already round-trip tested by P1's bridge tests), but implicit enough that a future reader could get the sign wrong without re-deriving it. **P6 wraps this in `frame_graph.object_frame_transform`, giving it a name.** |
| P5 `wall_geometry.TiltedWall` | WALL (local) → ROOM | m | right | `extrusion_direction` | `normal` | **Yes** — `wall_local_frame`, already round-trip tested (P5) | None (P5 already closed the one real bug found there — the Gram-Schmidt orthogonalization) |
| `app.blender.manifest.to_blender_xyz` | ROOM → BLENDER_WORLD | m | right | +Z | +Y | **Yes** — one function, docstring states the exact mapping and why (`(x,y,z)->(x,-z,y)`), already round-trip tested in production (Phase 13) | None |
| Asset registry (`app.catalog.catalog`) | ASSET → OBJECT | m | right (assumed) | +Y (assumed) | -Z (assumed) | **No explicit per-asset correction field exists** | **The one real open item** — see §Asset frame below |

**Grep sweep for implicit axis operations** (`x, z = z, x` / `y = height - y`
/ bare sign flips outside a named, documented function): none found outside
the three functions in the table above (`_to_canonical`, `footprint_corners`,
`to_blender_xyz`) and P5's `wall_geometry.py`. Every axis manipulation in
this codebase is already inside a named, single-purpose, documented
function — the gap P6 closes is that these functions were never unified
into one typed, composable system with explicit frame identifiers and
provenance; it is not that any of them is wrong.

## Research

**ROS REP-103**: right-handed, but a **different** convention from Allure's
own (X-forward, Y-left, Z-up) — this is a robot-body convention, not
adopted; the useful idea taken is REP-103's own discipline of *naming every
frame and never leaving handedness implicit*, not its specific axis choice.

**Blender** (official-adjacent documentation, cross-checked against
multiple sources): right-handed, **Z-up** — confirms `to_blender_xyz`'s
target convention is exactly Blender's own real default, not a project-
specific guess.

**OpenUSD**: right-handed; **stage** up-axis is configurable (Y or Z), but
`Camera` prims are *always* rendered "up is +Y, right is +X, forward is -Z"
— **identical to Allure's own documented `Scene.coordinate_system`**. This
is independent confirmation that Allure's chosen convention is not
arbitrary — it already matches the one fixed convention even a
configurable-up-axis standard like USD does not vary.

**glTF**: right-handed, but +Z forward (not -Z) — a genuinely different
convention from Allure/USD, cited here specifically to show *not every*
industry standard agrees, so "right-handed" alone is insufficient
specification; forward direction must always be stated explicitly, which
Allure's own `Scene.coordinate_system` already does.

**Architectural conclusion**: Allure's existing convention needs no
change — it already matches OpenUSD's camera convention, is already
explicitly documented, and every individual conversion already found in the
audit is already a correct, tested, proper rotation. P6's job is
formalization (typed, composable, provenance-carrying) and closing exactly
one real gap (asset forward-axis correction data), not correcting a broken
convention.

## Canonical Allure coordinate system (confirmed, not changed)

- **Handedness**: right-handed.
- **Units**: metres.
- **Up**: +Y.
- **Right**: +X.
- **Forward**: -Z.
- **Origin (ROOM frame)**: the camera's own optical center at capture time
  (§Camera→Room below — this is a measured architectural fact, not a
  choice: Allure never estimates a room-anchored origin independent of the
  camera, because monocular metric depth alone cannot provide one).
- **Rotation**: yaw around +Y, radians, positive = counter-clockwise seen
  from above (matches `footprint_corners`'s `cos(-rotation)` convention,
  now named explicitly in `frame_graph.object_frame_transform`).
- **Matrix convention**: row-major 3×3, applied as `R @ v` (column vector on
  the right), composition `A.compose(B)` means "apply B first, then A" —
  standard graphics/robotics convention, stated explicitly in
  `transforms.py`'s own docstrings.

## Camera → Room: a measured architectural fact, not an assumption

**Allure's pipeline does not estimate camera pose relative to a room-
anchored origin.** `opencv_to_room()` is a **fixed** axis-convention change
(180° about X) — the same transform for every photo, never parameterized by
scene content. The ROOM frame's origin is, by construction, wherever the
camera's optical center was. This was verified, not assumed: P1's own
architecture decision checked a real footprint corner against this exact
convention. **This means "room rotated 90°/180° relative to camera" is not
a scenario this architecture can produce** — there is no independent room-
pose estimation step for such a rotation to apply to. This is stated
explicitly here (rather than silently building an adversarial test for a
scenario the pipeline cannot exhibit) per principle 40's own instruction not
to manufacture appearances of coverage.

## Frame taxonomy: eight frames, not twelve

See `research/spatial_architecture/coordinate_frames.py`'s own module
docstring for the full per-frame table (purpose, parent, units, handedness,
axes, metric/persistent/serializable flags, transform source) — not
duplicated here to avoid the two copies drifting apart. IMAGE, CAMERA, ROOM,
WALL, OBJECT, ASSET, BLENDER_WORLD are implemented; SCREEN, DEPTH,
FLOORPLAN, BUILDING and a separate FLOOR frame are explicitly not created,
each for a stated reason (no code path produces a value that would live in
it, or — for FLOOR — no capability gap it would close beyond what ROOM
already provides).

## Asset frame: the one real open item

No per-asset "forward axis correction" field exists in the catalog/registry
today. This is not a placeholder pretending to be complete —
`asset_to_object_transform()` returns identity, and Phase 10's own asset
audit (58/58 registry assets, `asset_normalization_report.md`) found **zero**
assets that needed an orientation correction to pass their geometric audit.
Identity is therefore the **measured-correct default** for every asset this
program has ever benchmarked, not an unverified assumption — but it is
correctly named here as the one place a *future* asset with a genuine
forward-axis mismatch would need a real (currently unbuilt) correction
mechanism, per principle 6's "if an asset requires a correction, it must be
represented as data, not buried in code."

## Downstream compatibility (P1-P5)

None of P1 (`collision_solver.py`), P2 (`clearance_engine.py`), P3
(`scene_optimizer.py`), P4 (`repair_engine.py`) import anything from P6's
new modules, and P6's new modules do not modify any function those systems
call (`footprint_corners`, `convex_polygons_overlap`, `wall_rectangle`,
`object_footprint` are all read, never edited). P5's `wall_geometry.py` is
imported (`wall_local_frame`, reused exactly, not reimplemented) — confirmed
by the P5 tilt sweep re-run producing byte-identical output after P6 was
added. This is compatibility by construction (a wholly additive layer), not
merely compatibility observed by testing — though it was tested too (below).

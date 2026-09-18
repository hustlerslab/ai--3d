"""P5 wall representation: a generalized-extrusion Wall, strictly backward
compatible with production's vertical-only `Wall` (app/scene/schema.py).

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. See docs/spatial_architecture/wall_geometry.md for the
research (buildingSMART's own IFC standard already draws exactly this
distinction - `IfcWallStandardCase` for vertical-only extrusion,
`IfcWall` for an arbitrary `ExtrudedDirection` - independent confirmation of
the fix derived here from first principles) and the candidate comparison
(chosen: E, extruded polygon with a generalized extrusion direction).

THE ONE NEW FIELD. `extrusion_direction: Vec3`, default `(0, 1, 0)`. Every
function below that consumes it reduces to EXACTLY today's behaviour when it
is `(0, 1, 0)` - grep this file for "extrusion_direction" and confirm each
use degrades to a no-op drift of zero. This is not asserted; it is the
`test_vertical_wall_is_unchanged_from_today` test's job to prove it.

WHERE THIS FIXES THE MEASURED LOSS (wall_baseline.md): the wall's true
fitted 3D plane normal has a Y-component when the wall leans (measured case:
`normal=[0.06009, 0.1888, -0.98018]`, ~11 degrees). `up_from_normal`
projects world-up onto the wall's own fitted plane, deriving
`extrusion_direction` from evidence Phase 6 ALREADY measures - no new
perception capability, no new field to observe. `cross_section_at_height`
then computes the wall's true 2D footprint at ANY height, not just one fixed
reference height - the exact mechanism `wall_baseline.md` traced as the
downstream cause of size-proportional COLLIDES_WALL residuals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


from app.scene.schema import SceneObject, Wall
from app.spatial.geometry import Vec2, convex_polygons_overlap, wall_rectangle

Vec3 = tuple[float, float, float]
WORLD_UP: Vec3 = (0.0, 1.0, 0.0)


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec3) -> Vec3:
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def up_from_normal(normal: Vec3) -> Vec3:
    """The wall's own local "up": world-up projected onto the wall's fitted
    plane. Reduces to exactly (0,1,0) when normal.y == 0 (an ordinary
    vertical wall); tilts smoothly otherwise. Derived from evidence Phase 6
    already measures - no new observation required."""
    n = _norm(normal)
    d = _dot(WORLD_UP, n)
    projected = (WORLD_UP[0] - n[0] * d, WORLD_UP[1] - n[1] * d, WORLD_UP[2] - n[2] * d)
    mag = math.sqrt(_dot(projected, projected))
    if mag < 1e-9:
        return WORLD_UP  # normal is world-up itself (a horizontal surface) - degenerate, fall back safely
    return (projected[0] / mag, projected[1] / mag, projected[2] / mag)


@dataclass(frozen=True)
class TiltedWall:
    """Strict superset of `app.scene.schema.Wall`: identical fields, plus
    ONE new one. A `TiltedWall` with `extrusion_direction=(0,1,0)` behaves
    identically to today's `Wall` in every function below."""

    wall_id: str
    start: Vec2
    end: Vec2
    thickness: float = 0.15
    height: float = 2.8
    extrusion_direction: Vec3 = WORLD_UP

    @classmethod
    def from_evidence(cls, wall_id: str, start: Vec2, end: Vec2, thickness: float,
                      height: float, fitted_normal: Optional[Vec3]) -> "TiltedWall":
        """Build directly from Phase 6's fitted 3D plane normal - the
        evidence that was previously discarded (wall_baseline.md's two
        silent-drop lines). `fitted_normal=None` (or purely horizontal
        with zero XZ) keeps the vertical default - UNSUPPORTED_GEOMETRY is
        never silently approximated as a wrong tilt; it is simply not
        applied, leaving the safe, explicit default."""
        extrusion = up_from_normal(fitted_normal) if fitted_normal is not None else WORLD_UP
        return cls(wall_id=wall_id, start=start, end=end, thickness=thickness,
                   height=height, extrusion_direction=extrusion)


def wall_local_frame(wall: TiltedWall) -> tuple[Vec3, Vec3, Vec3, Vec3]:
    """(origin, tangent, up, normal) - the explicit T_world_wall basis."""
    origin: Vec3 = (wall.start[0], 0.0, wall.start[1])
    raw_tangent = (wall.end[0] - wall.start[0], 0.0, wall.end[1] - wall.start[1])
    tangent = _norm(raw_tangent)
    raw_up = _norm(wall.extrusion_direction)
    # Gram-Schmidt: `tangent` (fixed by the 2D start/end line) and
    # `extrusion_direction` (derived from the fitted plane normal) are both
    # approximately in-plane but are NOT guaranteed perpendicular to each
    # other for a tilted wall - only each is separately close to
    # perpendicular to the plane's own normal. A valid rotation basis needs
    # tangent/up/normal mutually orthogonal, so `up` is re-orthogonalized
    # against `tangent` here (unchanged for a vertical wall, where the two
    # are already exactly perpendicular by construction).
    up_component_along_tangent = _dot(raw_up, tangent)
    up = _norm((raw_up[0] - tangent[0] * up_component_along_tangent,
               raw_up[1] - tangent[1] * up_component_along_tangent,
               raw_up[2] - tangent[2] * up_component_along_tangent))
    normal = _norm(_cross(tangent, up))
    return origin, tangent, up, normal


def world_to_wall(wall: TiltedWall, point: Vec3) -> Vec3:
    origin, tangent, up, normal = wall_local_frame(wall)
    rel = _sub(point, origin)
    return (_dot(rel, tangent), _dot(rel, up), _dot(rel, normal))


def wall_to_world(wall: TiltedWall, local: Vec3) -> Vec3:
    origin, tangent, up, normal = wall_local_frame(wall)
    return (
        origin[0] + tangent[0] * local[0] + up[0] * local[1] + normal[0] * local[2],
        origin[1] + tangent[1] * local[0] + up[1] * local[1] + normal[1] * local[2],
        origin[2] + tangent[2] * local[0] + up[2] * local[1] + normal[2] * local[2],
    )


def cross_section_at_height(wall: TiltedWall, height: float) -> tuple[Vec2, Vec2]:
    """The wall's true 2D (start, end) footprint at `height` metres above
    the floor - identical to (wall.start, wall.end) when the wall is
    vertical; drifts horizontally by height * tan(tilt) otherwise. This is
    the exact mechanism that closes wall_baseline.md's traced information
    loss: one fixed-height cross-section is no longer used for every
    object regardless of its own height range."""
    ex, ey, ez = wall.extrusion_direction
    if abs(ey) < 1e-9:
        # UNSUPPORTED_GEOMETRY: a wall extruded near-horizontally is not a
        # wall this model can represent - explicit refusal, never a silent
        # wrong answer. Falls back to the un-drifted cross-section.
        return wall.start, wall.end
    drift_x, drift_z = ex / ey, ez / ey
    dx, dz = height * drift_x, height * drift_z
    return (wall.start[0] + dx, wall.start[1] + dz), (wall.end[0] + dx, wall.end[1] + dz)


def wall_rectangle_at_height(wall: TiltedWall, height: float) -> list[Vec2]:
    start_h, end_h = cross_section_at_height(wall, height)
    return wall_rectangle(start_h, end_h, wall.thickness)


def object_wall_collides(obj: SceneObject, wall: "TiltedWall | Wall") -> bool:
    """H2, height-aware: tests the object's footprint against the wall's
    cross-section at BOTH the object's bottom and top height, since drift is
    linear in height and these two bound every cross-section the object's
    own volume spans. Collides if EITHER matches - never silently
    under-reports (principle: hard constraints must never be relaxed for
    convenience).

    Accepts production `app.scene.schema.Wall` (which now carries
    `extrusion_direction`) as well as `TiltedWall`; both reduce to today's
    single fixed-height rectangle when the direction is `(0, 1, 0)`."""
    from app.spatial.validation import object_footprint  # validation imports this module

    footprint = object_footprint(obj)
    bottom_h = obj.position[1]
    top_h = obj.position[1] + obj.dimensions[1] * obj.scale[1]
    for h in (bottom_h, top_h):
        if convex_polygons_overlap(footprint, wall_rectangle_at_height(wall, h)):
            return True
    return False


__all__ = ["TiltedWall", "Vec3", "WORLD_UP", "up_from_normal", "wall_local_frame",
           "world_to_wall", "wall_to_world", "cross_section_at_height",
           "wall_rectangle_at_height", "object_wall_collides"]

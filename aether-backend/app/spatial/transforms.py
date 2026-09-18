"""P6 SE(3) transform contract: a strongly-typed rigid transform between two
named `FrameId`s, plus frame-tagged Point/Vector/Direction wrappers so a
spatial value carries enough information to know which frame it belongs to.

Production code, migrated from research/spatial_architecture/ once the phase that built it PASSED its gate - see docs/production/research_to_production.md. This is candidate B from coordinate_frames.md's decision
matrix (a lightweight typed layer) - not ROS tf2, not a robotics library.
Every concrete `Rigid3` this program actually needs (see frame_graph.py)
WRAPS a transform that already exists and was already measured correct
(Scene->Blender, OpenCV->Room, P5's wall frame) - this module adds the type
safety and composability around them, not new geometry.

POINT vs VECTOR vs DIRECTION, and why it matters here concretely: a Point3
is a location (translation applies); a Vector3 is a displacement (rotation
only, no translation - e.g. "2 m along the wall"); a Direction3 is a Vector3
constrained to unit length (e.g. a wall normal). Treating a wall's fitted
normal as a Point (translating it) would silently corrupt it - exactly the
"never treat them as interchangeable" rule this module enforces at the type
level, not by convention.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from app.spatial.coordinate_frames import FrameId

Mat3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Vec3 = tuple[float, float, float]

IDENTITY_MAT3: Mat3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class FrameMismatchError(ValueError):
    """Raised when a transform is applied to a value from the wrong frame -
    the one error this whole module exists to make impossible to ignore."""


def _mat_vec(m: Mat3, v: Vec3) -> Vec3:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _mat_transpose(m: Mat3) -> Mat3:
    return ((m[0][0], m[1][0], m[2][0]), (m[0][1], m[1][1], m[2][1]), (m[0][2], m[1][2], m[2][2]))


def _mat_mat(a: Mat3, b: Mat3) -> Mat3:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore


def determinant3(m: Mat3) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def is_orthonormal(m: Mat3, tol: float = 1e-6) -> bool:
    """RᵀR = I and det(R) = +1 - a proper rotation, not a reflection."""
    rt_r = _mat_mat(_mat_transpose(m), m)
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            if abs(rt_r[i][j] - expected) > tol:
                return False
    return abs(determinant3(m) - 1.0) < tol


@dataclass(frozen=True)
class Point3:
    x: float
    y: float
    z: float
    frame: FrameId

    def as_tuple(self) -> Vec3:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float
    frame: FrameId

    def as_tuple(self) -> Vec3:
        return (self.x, self.y, self.z)

    def length(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)


@dataclass(frozen=True)
class Direction3:
    x: float
    y: float
    z: float
    frame: FrameId

    def __post_init__(self) -> None:
        n = math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)
        if n < 1e-9:
            raise ValueError("Direction3 cannot be constructed from a zero-length vector")
        if abs(n - 1.0) > 1e-6:
            raise ValueError(f"Direction3 must be unit length, got {n:.6f} - normalize before constructing")

    def as_tuple(self) -> Vec3:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class Rigid3:
    """A rigid (rotation + translation, no scale) transform from `source` to
    `target`. `rotation` must be orthonormal with det=+1 (a proper rotation)
    - constructors below enforce this; nothing bypasses it silently."""

    source: FrameId
    target: FrameId
    rotation: Mat3
    translation: Vec3
    provenance: str
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if not is_orthonormal(self.rotation, tol=1e-5):
            raise ValueError(f"Rigid3({self.source}->{self.target}) rotation is not a proper "
                             f"orthonormal matrix (det={determinant3(self.rotation):.6f}) - "
                             "a reflection or a bug, never accepted silently")

    @staticmethod
    def identity(frame: FrameId, provenance: str = "identity") -> "Rigid3":
        return Rigid3(source=frame, target=frame, rotation=IDENTITY_MAT3,
                     translation=(0.0, 0.0, 0.0), provenance=provenance, confidence=1.0)

    def inverse(self) -> "Rigid3":
        rt = _mat_transpose(self.rotation)
        neg_rt_t = _mat_vec(rt, tuple(-c for c in self.translation))  # type: ignore
        return Rigid3(source=self.target, target=self.source, rotation=rt,
                     translation=neg_rt_t, provenance=f"inverse({self.provenance})",
                     confidence=self.confidence)

    def compose(self, inner: "Rigid3") -> "Rigid3":
        """self.compose(inner): apply `inner` first, then self.
        Requires inner.target == self.source (parent<-child chaining)."""
        if inner.target != self.source:
            raise FrameMismatchError(
                f"cannot compose {self}: inner.target={inner.target} != self.source={self.source}")
        r = _mat_mat(self.rotation, inner.rotation)
        t = _mat_vec(self.rotation, inner.translation)
        t = (t[0] + self.translation[0], t[1] + self.translation[1], t[2] + self.translation[2])
        conf = (min(self.confidence, inner.confidence)
               if self.confidence is not None and inner.confidence is not None else None)
        return Rigid3(source=inner.source, target=self.target, rotation=r, translation=t,
                     provenance=f"{self.provenance} ∘ {inner.provenance}", confidence=conf)

    def __matmul__(self, other: "Rigid3") -> "Rigid3":
        return self.compose(other)

    def apply_point(self, p: Point3) -> Point3:
        if p.frame != self.source:
            raise FrameMismatchError(f"Rigid3({self.source}->{self.target}) cannot apply to a "
                                     f"Point3 in frame {p.frame}")
        v = _mat_vec(self.rotation, p.as_tuple())
        return Point3(v[0] + self.translation[0], v[1] + self.translation[1],
                     v[2] + self.translation[2], frame=self.target)

    def apply_vector(self, v: Vector3) -> Vector3:
        if v.frame != self.source:
            raise FrameMismatchError(f"Rigid3({self.source}->{self.target}) cannot apply to a "
                                     f"Vector3 in frame {v.frame}")
        r = _mat_vec(self.rotation, v.as_tuple())
        return Vector3(r[0], r[1], r[2], frame=self.target)

    def apply_direction(self, d: Direction3) -> Direction3:
        if d.frame != self.source:
            raise FrameMismatchError(f"Rigid3({self.source}->{self.target}) cannot apply to a "
                                     f"Direction3 in frame {d.frame}")
        r = _mat_vec(self.rotation, d.as_tuple())
        n = math.sqrt(sum(c * c for c in r)) or 1.0
        return Direction3(r[0] / n, r[1] / n, r[2] / n, frame=self.target)

    @staticmethod
    def from_diagonal(source: FrameId, target: FrameId, signs: Vec3,
                      provenance: str) -> "Rigid3":
        """A pure axis-flip/permutation-free rotation: diag(sx, sy, sz), each
        +/-1. Used for the two existing conversions this program already had
        (OpenCV->Room negates Y,Z; both are 180-degree rotations about X)."""
        m = ((signs[0], 0.0, 0.0), (0.0, signs[1], 0.0), (0.0, 0.0, signs[2]))
        return Rigid3(source=source, target=target, rotation=m, translation=(0.0, 0.0, 0.0),
                     provenance=provenance, confidence=1.0)

    @staticmethod
    def from_axis_permutation(source: FrameId, target: FrameId, row0: Vec3, row1: Vec3,
                              row2: Vec3, translation: Vec3, provenance: str,
                              confidence: Optional[float] = None) -> "Rigid3":
        """An explicit rotation given by its three rows (each row says how
        one target axis is built from the source axes) - used for
        Room<->Blender ((x,y,z)->(x,-z,y)) and any wall-local basis."""
        return Rigid3(source=source, target=target, rotation=(row0, row1, row2),
                     translation=translation, provenance=provenance, confidence=confidence)


__all__ = ["Mat3", "Vec3", "IDENTITY_MAT3", "FrameMismatchError", "determinant3",
           "is_orthonormal", "Point3", "Vector3", "Direction3", "Rigid3"]

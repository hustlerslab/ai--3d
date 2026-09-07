"""Asset validation (plan §15 quality checks).

Hard issues keep an asset out of the catalog; warnings are recorded on the
record so a curator can see why something looks heavy or odd.
"""
from __future__ import annotations

from ..scene.schema import Vec3
from .gltf import GltfDocument, Measurement
from .schema import ValidationIssue

MAX_TRIANGLES_WARN = 300_000
MAX_TRIANGLES_HARD = 1_500_000
MAX_TEXTURE_BYTES_WARN = 40 * 1024 * 1024
MIN_DIMENSION_M = 0.03
MAX_DIMENSION_M = 8.0


def validate(
    doc: GltfDocument,
    measurement: Measurement,
    textures: dict[str, int],
    dimensions: Vec3,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if measurement.mesh_instances == 0:
        issues.append(ValidationIssue(code="EMPTY_SCENE", severity="hard", message="No meshes in the default scene."))
    if measurement.has_nan:
        issues.append(ValidationIssue(code="NAN_TRANSFORM", severity="hard", message="A node transform or vertex bound is NaN."))
    if doc.missing_files:
        issues.append(
            ValidationIssue(
                code="MISSING_FILES",
                severity="hard",
                message="Referenced files not found: " + ", ".join(doc.missing_files[:5]),
            )
        )
    if measurement.triangles > MAX_TRIANGLES_HARD:
        issues.append(ValidationIssue(code="POLYCOUNT_EXTREME", severity="hard", message=f"{measurement.triangles:,} triangles exceeds the hard limit."))
    elif measurement.triangles > MAX_TRIANGLES_WARN:
        issues.append(ValidationIssue(code="POLYCOUNT_HIGH", severity="warn", message=f"{measurement.triangles:,} triangles — consider decimation or LOD."))
    if textures.get("bytes", 0) > MAX_TEXTURE_BYTES_WARN:
        issues.append(ValidationIssue(code="TEXTURES_LARGE", severity="warn", message=f"Textures total {textures['bytes'] / 1e6:.1f} MB — consider a lower resolution or KTX2."))
    if textures.get("count", 0) == 0:
        issues.append(ValidationIssue(code="NO_TEXTURES", severity="info", message="Model has no textures (flat materials only)."))

    if any(d <= 0 for d in dimensions):
        issues.append(ValidationIssue(code="ZERO_SIZE", severity="hard", message="Normalized bounding box has a zero extent."))
    else:
        if min(dimensions) < MIN_DIMENSION_M and max(dimensions) < 0.2:
            issues.append(ValidationIssue(code="TOO_SMALL", severity="warn", message="Normalized object is under 20 cm — check units."))
        if max(dimensions) > MAX_DIMENSION_M:
            issues.append(ValidationIssue(code="TOO_LARGE", severity="hard", message=f"Normalized object is {max(dimensions):.1f} m — check units."))

    return issues

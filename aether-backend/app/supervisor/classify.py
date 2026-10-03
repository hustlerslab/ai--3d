"""P1-VALIDATOR-003: classify every failure against the one taxonomy that
already exists (`app/spatial/failures.py`, twelve categories). The enum is
not changed; this module is the only thing that maps evidence onto it.

The three P10 rules are enforced in the constructor, not by convention: a
`Classification` carries the ORIGIN of the failure (model / architecture /
hardware / asset / environment / unknown) and refuses a category that origin
may not have. So:

* a model error cannot be labelled an architecture error,
* an architecture error cannot be labelled a model error,
* a hardware limitation cannot be labelled a model failure,

because such an object cannot be built.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..spatial.failures import FailureCategory as FC

Origin = str   # "model" | "architecture" | "hardware" | "asset" | "environment" | "unknown"

#: What each origin may be labelled. This table IS the P10 rules.
ALLOWED: dict[str, frozenset[FC]] = {
    "model": frozenset({FC.PERCEPTION_FAILURE}),
    "architecture": frozenset({FC.GEOMETRY_FAILURE, FC.REPRESENTATION_FAILURE, FC.CONSTRAINT_FAILURE,
                               FC.CANDIDATE_VOCABULARY_FAILURE, FC.SOLVER_FAILURE, FC.REPAIR_FAILURE,
                               FC.VALIDATION_FAILURE}),
    "hardware": frozenset({FC.HARDWARE_FAILURE}),
    "asset": frozenset({FC.ASSET_FAILURE}),
    "environment": frozenset({FC.BLENDER_EXECUTION_FAILURE}),
    "unknown": frozenset({FC.UNKNOWN}),
}
#: Categories that mean "a human must change code" - retrying is wasted spend
#: (design.md §21.3, the three code-defect rows).
CODE_DEFECTS = frozenset({FC.REPRESENTATION_FAILURE, FC.CONSTRAINT_FAILURE, FC.CANDIDATE_VOCABULARY_FAILURE})


class ClassificationError(ValueError):
    """A category the origin may not carry - a P10 rule would be broken."""


@dataclass(frozen=True)
class Classification:
    category: FC
    origin: Origin
    layer: str                      # which component reported it
    code: str                       # the reporter's own code / exception type
    reason: str
    entity_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.origin not in ALLOWED:
            raise ClassificationError(f"unknown origin {self.origin!r}")
        if self.category not in ALLOWED[self.origin]:
            raise ClassificationError(
                f"{self.category.value} is not a {self.origin} failure (P10: "
                f"{self.origin} may only be {sorted(c.value for c in ALLOWED[self.origin])})")

    @property
    def is_code_defect(self) -> bool:
        return self.category in CODE_DEFECTS

    @property
    def abstained(self) -> bool:
        """UNKNOWN means the classifier correctly declined to guess. It is NOT
        'no problem': something failed, and nobody may treat it as fine."""
        return self.category is FC.UNKNOWN

    def as_payload(self) -> dict[str, Any]:
        return {"failure_category": self.category.value, "failure_origin": self.origin,
                "failure_layer": self.layer, "failure_code": self.code, "code_defect": self.is_code_defect}


# ── spatial validation (app/spatial/validation.py) ─────────────────────────

VIOLATION_CATEGORY: dict[str, tuple[FC, Origin]] = {
    # The scene's own structure is inconsistent: a reference to something the
    # representation does not hold.
    "ROOM_NOT_FOUND": (FC.REPRESENTATION_FAILURE, "architecture"),
    "ORPHAN_OPENING": (FC.REPRESENTATION_FAILURE, "architecture"),
    # The compiler built geometry that is wrong in itself.
    "INVALID_ROOM_POLYGON": (FC.GEOMETRY_FAILURE, "architecture"),
    "OPENING_OUTSIDE_WALL": (FC.GEOMETRY_FAILURE, "architecture"),
    # An object in hard violation in a scene that was solved: valid positions
    # were available (or repair would say otherwise) and one was not chosen.
    "OUTSIDE_ROOM": (FC.SOLVER_FAILURE, "architecture"),
    "COLLIDES_WALL": (FC.SOLVER_FAILURE, "architecture"),
    "COLLIDES_OBJECT": (FC.SOLVER_FAILURE, "architecture"),
    "BLOCKS_DOOR": (FC.SOLVER_FAILURE, "architecture"),
}


def from_violation(v: Any) -> Classification:
    code = getattr(v, "code", "")
    cat, origin = VIOLATION_CATEGORY.get(code, (FC.UNKNOWN, "unknown"))
    ids = tuple(i for i in (getattr(v, "object_id", None), getattr(v, "related_id", None)) if i)
    return Classification(cat, origin, "spatial.validation", code, getattr(v, "message", code), ids)


# ── repair engine (app/spatial/repair_engine.py) ───────────────────────────

TERMINAL_CATEGORY: dict[str, Optional[tuple[FC, Origin]]] = {
    "REPAIRED": None,
    "ALREADY_VALID": None,
    # No candidate the engine can generate expresses a valid layout.
    "UNREPAIRABLE": (FC.CANDIDATE_VOCABULARY_FAILURE, "architecture"),
    # Repair moved things and still could not reach validity.
    "ESCALATE": (FC.REPAIR_FAILURE, "architecture"),
    # The search budget ran out: a compute limit, not a wrong answer.
    "TIMEOUT": (FC.HARDWARE_FAILURE, "hardware"),
    # The input is wrong upstream (e.g. the reading produced a duplicate
    # pair) - a perception error; repair must not be asked again.
    "UPSTREAM_REQUIRED": (FC.PERCEPTION_FAILURE, "model"),
}


def from_repair(terminal_state: str, *, hard_after: int = 0, moved: int = 0) -> Optional[Classification]:
    mapped = TERMINAL_CATEGORY.get(terminal_state, (FC.UNKNOWN, "unknown"))
    if mapped is None:
        return None
    cat, origin = mapped
    return Classification(cat, origin, "spatial.repair_engine", terminal_state,
                          f"repair ended {terminal_state} with {hard_after} hard violation(s)",
                          evidence={"hard_after": hard_after, "moved": moved})


# ── compiler (app/planning/compiler.py `place_objects`) ────────────────────
# Mirrors the compiler's own warning format strings exactly; the test drives
# the real compiler to produce each one.

COMPILER_PATTERNS: tuple[tuple[re.Pattern, FC, Origin], ...] = (
    (re.compile(r": no asset decision$"), FC.ASSET_FAILURE, "asset"),
    (re.compile(r": room \S+ not in scene$"), FC.REPRESENTATION_FAILURE, "architecture"),
    (re.compile(r": plan says \d+, the approved reading has \d+ occurrence"), FC.PERCEPTION_FAILURE, "model"),
    (re.compile(r": no surface in .+ to rest (.+ )?on; skipped$"), FC.CANDIDATE_VOCABULARY_FAILURE, "architecture"),
    (re.compile(r": no valid position (for .+ )?in .+ \(priority \d+\)$"), FC.CANDIDATE_VOCABULARY_FAILURE,
     "architecture"),
)


def from_compiler_warning(text: str) -> Classification:
    key = text.split(":", 1)[0]
    for pattern, cat, origin in COMPILER_PATTERNS:
        if pattern.search(text):
            return Classification(cat, origin, "planning.compiler", pattern.pattern, text, (key,))
    return Classification(FC.UNKNOWN, "unknown", "planning.compiler", "unmatched", text, (key,))


# ── constraint compilation (app/planning/constraint_compiler.py) ───────────


def from_constraints(constraint_set: Any, plan_keys: set[str]) -> list[Classification]:
    """A compiled constraint that names a subject or target the plan does not
    contain was mis-compiled: `apply_constraints_to_plan` skips it silently,
    so without this nothing would say it was lost."""
    out = []
    for c in getattr(constraint_set, "constraints", []) or []:
        missing = [i for i in (getattr(c, "subject_id", None), getattr(c, "target_id", None))
                   if i and i not in plan_keys]
        if missing:
            out.append(Classification(FC.CONSTRAINT_FAILURE, "architecture", "planning.constraint_compiler",
                                      getattr(c, "constraint_id", "constraint"),
                                      f"constraint names {', '.join(missing)}, which the plan does not contain",
                                      tuple(missing)))
    return out


# ── the Blender build (app/jobs/handlers/build.py) ─────────────────────────


def from_build_report(report: dict) -> Optional[Classification]:
    """The build's own validation report. A report that is missing means a
    check did not run - which is not a pass."""
    if not report or report.get("errors") == ["no report"]:
        return Classification(FC.VALIDATION_FAILURE, "architecture", "jobs.build", "NO_REPORT",
                              "the build produced no validation report; its checks did not run")
    if report.get("ok"):
        return None
    return Classification(FC.BLENDER_EXECUTION_FAILURE, "environment", "jobs.build", "REPORT_ERRORS",
                          "; ".join(map(str, report.get("errors", [])))[:500])


# ── exceptions that fail a job (app/jobs/runner.py) ────────────────────────

_HARDWARE_MARKERS = ("out of memory", "cuda error", "cudnn", "vram", "memoryerror", "gpu",
                     "timed out", "timeout", "rate limit", "rate limited", "network error",
                     "connection", "429", "503")
_MODEL_ERRORS = ("GeminiError", "AnthropicError", "OllamaError", "OllamaReadError", "ProviderError",
                 "JSONDecodeError", "ValidationError")


def from_exception(exc: BaseException, *, job_type: str = "") -> Classification:
    name = type(exc).__name__
    text = f"{name}: {exc}".lower()
    # Hardware first: a timeout or out-of-memory INSIDE a model call is still a
    # hardware limitation, and P10 forbids calling it a model failure.
    if name in ("BlenderTimeout", "TimeoutError", "MemoryError") or any(m in text for m in _HARDWARE_MARKERS):
        return Classification(FC.HARDWARE_FAILURE, "hardware", f"jobs.{job_type}" if job_type else "jobs",
                              name, str(exc)[:500])
    if name.startswith("Blender"):
        return Classification(FC.BLENDER_EXECUTION_FAILURE, "environment", f"jobs.{job_type}", name, str(exc)[:500])
    if name in _MODEL_ERRORS or name.endswith("ReadError"):
        return Classification(FC.PERCEPTION_FAILURE, "model", f"jobs.{job_type}", name, str(exc)[:500])
    if name in ("MeshyTaskFailed",) or "asset" in name.lower() or "mesh" in name.lower():
        return Classification(FC.ASSET_FAILURE, "asset", f"jobs.{job_type}", name, str(exc)[:500])
    if name in ("PatchError", "VersionConflict"):
        return Classification(FC.REPRESENTATION_FAILURE, "architecture", f"jobs.{job_type}", name, str(exc)[:500])
    return Classification(FC.UNKNOWN, "unknown", f"jobs.{job_type}" if job_type else "jobs", name, str(exc)[:500])


def from_asset_rejection(asset_id: str, reason: str) -> Classification:
    return Classification(FC.ASSET_FAILURE, "asset", "assets", "ASSET_REJECTED", reason, (asset_id,))


__all__ = ["Classification", "ClassificationError", "ALLOWED", "CODE_DEFECTS", "VIOLATION_CATEGORY",
           "TERMINAL_CATEGORY", "from_violation", "from_repair", "from_compiler_warning", "from_constraints",
           "from_build_report", "from_exception", "from_asset_rejection"]

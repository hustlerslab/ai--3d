"""P10 production boundary: one classification per input path, never one
vague overall label (§15's own explicit requirement).

METHOD. `app/` import graph re-checked this phase
(`grep -rl "research\\.spatial_architecture\\|research\\.spatial_engine\\|from research" app/`
- zero matches, confirmed unchanged since P1) plus the measured numbers
already on record in `docs/benchmarks/spatial_engine_production_readiness.md`
and every `docs/spatial_architecture/decisions.md` phase entry - not
re-asserted from memory, cited.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Readiness(str, Enum):
    PRODUCTION_READY = "production_ready"
    CONTROLLED_BETA = "controlled_beta"
    RESEARCH_ONLY = "research_only"
    MODEL_LIMITED = "model_limited"
    HARDWARE_LIMITED = "hardware_limited"
    NOT_YET_SOLVED = "not_yet_solved"


@dataclass(frozen=True)
class PathAssessment:
    path: str
    readiness: Readiness
    evidence: str
    limitation: str


PRODUCTION_BOUNDARY: tuple[PathAssessment, ...] = (
    PathAssessment(
        path="design-from-brief (deterministic core: compile -> solve -> validate -> Blender)",
        readiness=Readiness.PRODUCTION_READY,
        evidence="12/12 frozen scenes valid, 547/559 objects placed (97.9%), 12/12 Blender builds "
                "with 0 errors, XY read-back p95 0.015 m (scene_validity_report.md, "
                "blender_execution_report.md) - all production code (app/), deterministic, "
                "re-confirmed byte-identical after every P1-P9 phase including this one.",
        limitation="7/12 scenes are FULL successes (every requested object placed); the 5 shortfalls "
                  "are upstream room-analysis/on-surface-support gaps in the analysis provider, not "
                  "in the deterministic core itself.",
    ),
    PathAssessment(
        path="design-from-brief (end-to-end, including a real LLM-driven analysis/style/asset provider)",
        readiness=Readiness.CONTROLLED_BETA,
        evidence="The deterministic core above is production-grade; the upstream "
                "DesignAnalysis/StyleSpec/ObjectPlan generation has only been benchmarked against "
                "MockProvider (deterministic, no LLM) in the frozen scene_validity/blender_e2e "
                "benchmarks - a real provider's own accuracy is not characterized by this program.",
        limitation="No frozen benchmark in this program measures a real LLM provider's "
                  "room-count/dimension/object-plan accuracy - only the deterministic solver/"
                  "validator/Blender stages downstream of it.",
    ),
    PathAssessment(
        path="photo-to-scene",
        readiness=Readiness.RESEARCH_ONLY,
        evidence="Nothing in app/ imports research/spatial_architecture/ or research/spatial_engine/ "
                "- confirmed by grep, unchanged since P1 through P10. The research bridge itself "
                "measures 95.2% scene success (20/21) on the frozen 21-image benchmark, re-confirmed "
                "byte-identical in P7/P8/P9/P10, but is not reachable by any user-facing code path.",
        limitation="Wiring it into a production job handler is a deliberately deferred, "
                  "production-facing change (named as future-scoped work in every phase from P7 "
                  "onward) - out of every phase's own minimal-footprint mandate absent a concrete "
                  "consumer requesting it.",
    ),
    PathAssessment(
        path="photo-to-scene perception layer specifically (wall-contact/floor/grounding)",
        readiness=Readiness.MODEL_LIMITED,
        evidence="Wall-contact precision 77.8% / 25% UNKNOWN on the frozen 48-case benchmark, "
                "against a 90% target (spatial_engine_production_readiness.md §6-7) - the "
                "abstention mechanism itself is architecturally sound (UNKNOWN is a first-class, "
                "never-silently-defaulted answer - app/spatial/planes.py's own rule 2), the ceiling "
                "is mask/depth evidence quality, not a missing capability.",
        limitation="Through-glass depth contamination, no room-height prior for a failed floor fit, "
                  "and no non-wall orientation fallback are all named, open, perception-quality items.",
    ),
    PathAssessment(
        path="floorplan-to-scene",
        readiness=Readiness.NOT_YET_SOLVED,
        evidence="No code path in app/ or research/ ingests a 2D floorplan image and produces a "
                "Scene - confirmed by grep across the whole repository. `RoomGeometry.metric_source "
                "== FLOORPLAN` (app/spatial/planes.py) is an unused enum VALUE, not an implemented "
                "pipeline - it exists so a future metric-source can be named without a breaking "
                "change, exactly like this program's own reserved-taxonomy-slot pattern (P7's "
                "GEOMETRIC_INVARIANT/FUNCTIONAL, P9's CandidateSource).",
        limitation="Does not exist. Not attempted by P0-P9 - no phase's mission included it.",
    ),
    PathAssessment(
        path="mixed-input scene generation (photo + brief combined)",
        readiness=Readiness.NOT_YET_SOLVED,
        evidence="No code path combines a photo-grounded SpatialScene with a brief-derived "
                "ObjectPlan into one scene - the two paths (grounding_to_scene vs. compile_scene + "
                "place_objects) produce independent Scene objects with no merge function anywhere "
                "in app/ or research/.",
        limitation="Does not exist. Not attempted by P0-P9.",
    ),
)


def by_path(path_substring: str):
    return next((p for p in PRODUCTION_BOUNDARY if path_substring.lower() in p.path.lower()), None)


def readiness_counts() -> dict[str, int]:
    counts = {r.value: 0 for r in Readiness}
    for p in PRODUCTION_BOUNDARY:
        counts[p.readiness.value] += 1
    return counts


__all__ = ["Readiness", "PathAssessment", "PRODUCTION_BOUNDARY", "by_path", "readiness_counts"]

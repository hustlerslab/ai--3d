"""GroundingHypothesis: the FACT/HYPOTHESIS layer between perception and Scene.

Research only. Nothing in `app/` imports this. See architecture_decision.md §1-3
for why this shape and not a new top-level scene type, and §2 for why three
confidence channels rather than the seven the brief asked to consider.

WHAT THIS IS NOT. It is not a rewrite of Phase 9's `ObjectGrounding`
(research/spatial_engine/object_grounding.py). That module's footprint, extent,
orientation-candidate and wall-contact logic is frozen and benchmarked; this
type WRAPS one `ObjectGrounding` plus the two pieces of evidence it does not
carry itself (mask-coverage perception confidence, and the destination scene's
image key), and nothing else. `from_object_grounding` is the only constructor,
so a hypothesis can never be built except from real grounding output.

FACT vs HYPOTHESIS vs DECISION, concretely, in this one object:

    FACT        footprint, room_position, depth_m, evidence strings -
                measured directly from MoGe/SAM output, never revised.
    HYPOTHESIS  orientation_candidates - multiple, RANKED, never collapsed to
                one until a caller asks for `best_orientation`.
    DECISION    wall_contact - the YES/NO/UNKNOWN this phase's frozen geometry
                already decided; the bridge does not re-decide it.

THREE CONFIDENCE CHANNELS, KEPT SEPARATE, NEVER AVERAGED INTO ONE UNEXPLAINED
NUMBER:

    perception_confidence   SAM mask coverage with valid MoGe depth
    extent_confidence       AssetSpatialMetadata.confidence (registry/builtin/
                            family/unknown - Phase 7)
    wall_confidence         the selected wall's Phase 6 enclosure_fraction

`overall_confidence` is their product, `weakest_channel` names whichever is
lowest - so a caller wanting one number still gets one, and a caller wanting
the breakdown can read the three without recomputing anything.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.spatial_engine.object_grounding import ObjectGrounding  # noqa: E402


@dataclass(frozen=True)
class OrientationCandidate:
    """One ranked, unresolved orientation hypothesis. See §31 of the brief:
    do not prematurely collapse ambiguity."""

    wall_index: Optional[int]
    axis: str                     # "depth" | "width" | "principal" | "flush"
    feasible: Optional[bool]
    score: float


@dataclass(frozen=True)
class GroundingHypothesis:
    """One object's FACT/HYPOTHESIS/DECISION state, ready for the scene bridge."""

    object_id: str
    case_id: str
    room_image: str
    semantic_type: str
    canonical_type: str
    placement_class: str
    support: str

    # FACT
    footprint: Optional[list]             # 4 (x, y, z) corners, canonical frame
    footprint_axes: dict                  # {"along": [...], "normal": [...]}
    room_position: Optional[tuple]
    depth_m: Optional[float]
    extent_wdh_m: tuple                   # (width, height, depth), metres
    floor_contact_m: Optional[float]
    base_occluded: bool
    evidence: list

    # HYPOTHESIS
    orientation_candidates: list          # list[OrientationCandidate]

    # DECISION (from the frozen geometry, not re-decided here)
    wall_decision: str                    # "YES" | "NO" | "UNKNOWN"
    wall_index: Optional[int]
    wall_distance_m: Optional[float]

    # confidence, kept as three channels
    perception_confidence: float
    extent_confidence: float
    wall_confidence: float

    failure_reason: Optional[str] = None
    failure_category: str = "NONE"

    @property
    def overall_confidence(self) -> float:
        return round(self.perception_confidence * self.extent_confidence
                     * self.wall_confidence, 4)

    @property
    def weakest_channel(self) -> str:
        chans = {"perception": self.perception_confidence,
                 "extent": self.extent_confidence, "wall": self.wall_confidence}
        return min(chans, key=lambda k: chans[k])

    @property
    def grounded(self) -> bool:
        return self.footprint is not None

    @property
    def best_orientation(self) -> Optional[OrientationCandidate]:
        feasible = [c for c in self.orientation_candidates if c.feasible]
        pool = feasible or self.orientation_candidates
        return max(pool, key=lambda c: c.score) if pool else None

    @classmethod
    def from_object_grounding(cls, g: ObjectGrounding, *, room_image: str,
                              canonical_type: str, perception_confidence: float,
                              extent_confidence: float,
                              failure_category: str = "NONE") -> "GroundingHypothesis":
        wc = g.wall_contact or {}
        wall_conf = wc.get("confidence")
        if wall_conf is None:
            wall_conf = 0.0 if wc.get("decision") in (None, "UNKNOWN") else 0.5
        oc = [OrientationCandidate(wall_index=c.get("wall_index"), axis=c.get("axis", ""),
                                   feasible=c.get("feasible"), score=float(c.get("score", 0.0)))
              for c in (g.orientation_candidates or [])]
        return cls(
            object_id=g.object_id, case_id=g.case_id, room_image=room_image,
            semantic_type=canonical_type, canonical_type=canonical_type,
            placement_class=g.placement_class, support=g.support,
            footprint=[tuple(c) for c in g.footprint] if g.footprint else None,
            footprint_axes=g.footprint_axes or {},
            room_position=tuple(g.room_position) if g.room_position else None,
            depth_m=g.depth_m, extent_wdh_m=tuple(g.extent_wdh_m),
            floor_contact_m=g.floor_contact_m, base_occluded=g.base_occluded,
            evidence=list(g.evidence),
            orientation_candidates=oc,
            wall_decision=wc.get("decision", "UNKNOWN"), wall_index=wc.get("wall_index"),
            wall_distance_m=wc.get("distance_m"),
            perception_confidence=round(float(perception_confidence), 4),
            extent_confidence=round(float(extent_confidence), 4),
            wall_confidence=round(float(wall_conf), 4),
            failure_reason=g.failure_reason, failure_category=failure_category)


__all__ = ["GroundingHypothesis", "OrientationCandidate"]

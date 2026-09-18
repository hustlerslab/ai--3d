"""Spatial reconciliation: what the moodboard implies about arrangement.

Sits between the scene reading and the object plan. Takes what the reader knows
(WHAT each piece is, and the words it used for how the piece sits) and, when a
detector is available, what image geometry knows (WHERE each box is), and
produces a structured `SpatialGraph`.

What this layer refuses to do, and why
--------------------------------------
No metres, no XYZ, no wall assignment. A render has no depth and does not obey
the room's real size - the sample 2.5 x 2.0 m bathroom renders as a long spa -
so turning bounding boxes into positions would be inventing facts the picture
cannot support. The graph says "the coffee table is near the sofa"; deciding
that means (3.2, 0, 1.8) is the coordinate solver's job, with the room's real
dimensions and the collision checks in hand.

Geometry is OPTIONAL
--------------------
`detections` defaults to None and everything works without it, because the
detector is still benchmark-only (Phase 0b kept it out of production pending a
larger re-benchmark). With no geometry, relations come from the reader's own
words and are capped at LOW confidence. Hand it detections and the same
relations can reach HIGH. Nothing here imports `app.vision`.

Deterministic throughout: same inputs, same graph, no model call.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from ..intelligence import vocab
from ..intelligence.schema import (
    SceneElement, SceneReading, SpatialConfidence, SpatialConflict, SpatialGraph,
    SpatialGroup, SpatialNode, SpatialRelation, UnmatchedDetection)

# ── thresholds, in fractions of the image ────────────────────────────────
#
# All normalised, so they mean the same thing at any render size. Chosen to be
# forgiving: this layer proposes relationships for a solver to use as
# preferences, so a missed NEAR costs less than a confident wrong one.

#: Centres closer than this are NEAR. ~a quarter of the frame.
NEAR_DISTANCE = 0.25
#: Gap between two boxes, along the axis they do not overlap on, to be ADJACENT.
ADJACENT_GAP = 0.06
#: Ranges must overlap by at least this much of the smaller box to count as
#: "sharing a row/column" - a sliver of overlap is not adjacency.
ADJACENT_OVERLAP = 0.25
#: Centres closer than this on an axis are not meaningfully left/right or
#: above/below of each other. Without it, two pieces side by side in the same
#: row generate a confident LEFT_OF from a three-pixel difference.
AXIS_TOLERANCE = 0.08
#: IoU above which two boxes are recorded as OVERLAPS. Occlusion, grouping and
#: a bad box all look like this, so it is recorded and never acted on.
OVERLAP_IOU = 0.10
#: A semantic claim of nearness that geometry puts further apart than this is a
#: conflict worth surfacing rather than quietly believing one side.
CONFLICT_DISTANCE = 0.45

#: Interior clusters worth naming. Kept small and additive to vocab's families
#: rather than replacing them: `vocab.FAMILY_BY_TYPE` already knows a sofa is
#: seating, but not that a sofa, a coffee table and a rug are one arrangement.
GROUP_PATTERNS: dict[str, tuple[set[str], set[str]]] = {
    # group_type: (anchor types, companion types)
    "seating": ({"sofa", "loveseat", "sectional"},
                {"coffee_table", "side_table", "rug", "armchair", "ottoman",
                 "floor_lamp", "table_lamp", "pillows", "throw", "tv_unit"}),
    "dining": ({"dining_table"},
               {"chair", "dining_chair", "sideboard", "chandelier", "pendant_lamp", "rug"}),
    "sleeping": ({"bed"},
                 {"bedside_table", "rug", "wardrobe", "dresser", "table_lamp",
                  "pillows", "throw", "wall_art"}),
    "workstation": ({"desk"},
                    {"chair", "office_chair", "bookshelf", "table_lamp", "storage_cabinet"}),
    "counter": ({"kitchen_counter", "kitchen_island"},
                {"bar_stool", "stool", "pendant_lamp", "fridge"}),
}

#: Words in an `against` hint that mean architecture rather than a piece.
_WALL_WORDS = ("wall", "window", "glazing", "corner", "french door", "alcove")

#: Frame-independent ways of saying "turned inward", matching the compiler's
#: own list. "floor" is deliberately absent: everything stands on the floor,
#: so it carries no arrangement information.
_INWARD_WORDS = ("into the room", "room", "centre", "center", "middle",
                 "inward", "inwards", "inside")


# ── geometry helpers (image space, fractions) ────────────────────────────

def _centre(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _distance(a, b) -> float:
    (ax, ay), (bx, by) = _centre(a), _centre(b)
    return math.hypot(ax - bx, ay - by)


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _range_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """How much two 1D ranges share, as a fraction of the smaller one."""
    lo, hi = max(a0, b0), min(a1, b1)
    if hi <= lo:
        return 0.0
    smaller = min(a1 - a0, b1 - b0)
    return (hi - lo) / smaller if smaller > 0 else 0.0


def _gap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Clear space between two ranges; 0 when they touch or overlap."""
    return max(0.0, max(a0, b0) - min(a1, b1))


# ── reconciliation ───────────────────────────────────────────────────────

def _match_detections(elements: Sequence[SceneElement],
                      detections: Sequence[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Pair each element with at most one detection of the same canonical type.

    Greedy on IoU, one detection per element and one element per detection, so
    three identical bar stools cannot all claim the same box. Whatever is left
    over is NOT promoted - see `UnmatchedDetection`.
    """
    pairs = []
    for el in elements:
        if not el.bbox:
            continue
        for index, det in enumerate(detections):
            if _canonical(det.get("label", "")) != el.semantic_type:
                continue
            score = _iou(el.bbox, det["bbox"])
            if score > 0:
                pairs.append((score, el.element_id, index))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))        # deterministic ties

    matched: dict[str, dict] = {}
    used: set[int] = set()
    for score, element_id, index in pairs:
        if element_id in matched or index in used:
            continue
        matched[element_id] = {**detections[index], "iou": round(score, 3)}
        used.add(index)
    leftovers = [d for i, d in enumerate(detections) if i not in used]
    return matched, leftovers


def _canonical(label: str) -> str:
    raw = (label or "").strip().lower().replace(" ", "_")
    return raw if raw in vocab.ALL_SEMANTIC_TYPES else vocab.canonical_type(label)


def _box_for(el: SceneElement, matched: dict[str, dict]):
    """Geometry wins where it exists; the reader's own box is the fallback.

    Phase 0d measured the detector at 0.680 mean IoU against the reader's 0.285,
    so where both have an opinion about WHERE, the detector's is taken. The
    reader's opinion about WHAT is never overridden.
    """
    hit = matched.get(el.element_id)
    if hit:
        return hit["bbox"], True
    return el.bbox, False


# ── semantic relations, from the reader's own words ──────────────────────

def _resolve_named(hint: str, room_nodes: Sequence[SceneElement],
                   exclude: str) -> Optional[SceneElement]:
    """Which piece in this room does a hint name?

    Same rule `_hint_rank` uses in the compiler: match the semantic type as
    words inside the free text, so "beside the striped sofa" finds the sofa.
    Longest type first, so `side_table` is preferred over `table`.
    """
    text = (hint or "").strip().lower()
    if not text:
        return None
    candidates = sorted(room_nodes, key=lambda e: -len(e.semantic_type))
    for other in candidates:
        if other.element_id == exclude:
            continue
        name = (other.semantic_type or "").replace("_", " ")
        if name and name in text:
            return other
    return None


def _semantic_relations(elements: Sequence[SceneElement],
                        by_room: dict[str, list[SceneElement]]) -> list[SpatialRelation]:
    """`against` and `faces`, turned into predicates. Phase 0a's fields, reused.

    Camera-relative answers are dropped, exactly as the placement engine drops
    them: a render has no fixed left, so "against the left wall" is not a fact
    about the room. The prompt now asks for named targets for this reason.
    """
    out: list[SpatialRelation] = []
    for el in elements:
        siblings = by_room.get(el.room_id, [])

        against = (el.against or "").strip().lower()
        if against:
            target = _resolve_named(against, siblings, el.element_id)
            if target is not None:
                out.append(SpatialRelation(
                    subject_id=el.element_id, predicate="AGAINST",
                    object_id=target.element_id, confidence="LOW",
                    source="semantic", note=f"reader said {against!r}"))
            elif any(word in against for word in _WALL_WORDS):
                out.append(SpatialRelation(
                    subject_id=el.element_id, predicate="AGAINST_WALL",
                    confidence="LOW", source="semantic",
                    note=f"reader said {against!r}; which wall is not decided here"))

        faces = (el.faces or "").strip().lower()
        if faces:
            target = _resolve_named(faces, siblings, el.element_id)
            if target is not None:
                out.append(SpatialRelation(
                    subject_id=el.element_id, predicate="FACES",
                    object_id=target.element_id, confidence="LOW",
                    source="semantic", note=f"reader said {faces!r}"))
            elif any(word in faces for word in _INWARD_WORDS):
                # "into the room" is frame-independent and is one of the answers
                # the prompt asks for by name. `_faces_rank` already consumes it
                # in the compiler; dropping it here would lose orientation the
                # reader actually supplied. No object: which way "inward" points
                # depends on the room, which this layer does not decide.
                out.append(SpatialRelation(
                    subject_id=el.element_id, predicate="FACES_ROOM",
                    confidence="LOW", source="semantic",
                    note=f"reader said {faces!r}; turned inward, not at a named piece"))

        # `on_surface` is a placement, not a guess: the reader put this piece on
        # something. Which something is the compiler's `_pick_support` decision,
        # so the relation is recorded without an object where none is named.
        if el.placement == "on_surface":
            support = _resolve_named(against or faces, siblings, el.element_id)
            out.append(SpatialRelation(
                subject_id=el.element_id,
                predicate="ON_TOP_OF" if support else "SUPPORTED_BY",
                object_id=support.element_id if support else "",
                confidence="MEDIUM" if support else "LOW",
                source="placement",
                note="read as resting on a surface"))
    return out


# ── geometric relations, from boxes ──────────────────────────────────────

def _geometric_relations(pairs: Iterable[tuple[SceneElement, SceneElement]],
                         boxes: dict[str, tuple]) -> list[SpatialRelation]:
    """Everything two boxes in one image can honestly say about each other."""
    out: list[SpatialRelation] = []
    for a, b in pairs:
        box_a, box_b = boxes.get(a.element_id), boxes.get(b.element_id)
        if not box_a or not box_b:
            continue
        (ax, ay), (bx, by) = _centre(box_a), _centre(box_b)
        distance = _distance(box_a, box_b)

        overlap = _iou(box_a, box_b)
        if overlap >= OVERLAP_IOU:
            out.append(SpatialRelation(
                subject_id=a.element_id, predicate="OVERLAPS", object_id=b.element_id,
                confidence="MEDIUM", source="geometry",
                note=f"boxes share {overlap:.0%} - occlusion, grouping or a bad box"))

        if distance <= NEAR_DISTANCE:
            out.append(SpatialRelation(
                subject_id=a.element_id, predicate="NEAR", object_id=b.element_id,
                confidence="MEDIUM", source="geometry",
                note=f"centres {distance:.2f} apart"))

        # Adjacent: sharing a row or a column, with little space between.
        rows = _range_overlap(box_a[1], box_a[3], box_b[1], box_b[3])
        cols = _range_overlap(box_a[0], box_a[2], box_b[0], box_b[2])
        if rows >= ADJACENT_OVERLAP and _gap(box_a[0], box_a[2], box_b[0], box_b[2]) <= ADJACENT_GAP:
            out.append(SpatialRelation(
                subject_id=a.element_id, predicate="ADJACENT_TO", object_id=b.element_id,
                confidence="MEDIUM", source="geometry", note="side by side, touching"))
        elif cols >= ADJACENT_OVERLAP and _gap(box_a[1], box_a[3], box_b[1], box_b[3]) <= ADJACENT_GAP:
            out.append(SpatialRelation(
                subject_id=a.element_id, predicate="ADJACENT_TO", object_id=b.element_id,
                confidence="MEDIUM", source="geometry", note="stacked, touching"))

        # CAMERA FRAME from here down. Ordering between two pieces in one view,
        # never a direction in the room - see SpatialRelation.frame.
        if abs(ax - bx) > AXIS_TOLERANCE:
            out.append(SpatialRelation(
                subject_id=a.element_id,
                predicate="LEFT_OF" if ax < bx else "RIGHT_OF",
                object_id=b.element_id, confidence="MEDIUM", source="geometry",
                frame="camera", note="ordering in the render, not a room direction"))
        if abs(ay - by) > AXIS_TOLERANCE:
            out.append(SpatialRelation(
                subject_id=a.element_id,
                predicate="ABOVE" if ay < by else "BELOW",
                object_id=b.element_id, confidence="MEDIUM", source="geometry",
                frame="camera", note="ordering in the render, not a room direction"))
    return out


# ── merge, conflicts, groups ─────────────────────────────────────────────

_RANK: dict[SpatialConfidence, int] = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
#: Frame-independent geometry predicates that can corroborate a semantic claim.
#: LEFT_OF and friends cannot: they are camera-frame, so agreeing with them
#: would raise confidence on the strength of where someone stood.
_CORROBORATES = {"NEAR", "ADJACENT_TO", "OVERLAPS"}


def _merge(semantic: list[SpatialRelation], geometric: list[SpatialRelation],
           confirmed: set[str]) -> list[SpatialRelation]:
    """Combine the two views, promoting only genuinely independent agreement.

    HIGH means two sources that could have disagreed did not. That is why
    `confirmed` is required: without a detection, the "geometry" corroborating a
    semantic claim is the READER'S OWN bounding box, so promoting on it would be
    one source agreeing with itself and calling the result high confidence. A
    first cut of this function did exactly that, and reported HIGH relations on
    a run with no detector attached at all.

      HIGH    semantic claim + geometry from a matched detection
      MEDIUM  geometry alone, or a semantic claim the reader's own box supports
      LOW     semantic claim with nothing supporting it
    """
    near_pairs: dict[frozenset, SpatialRelation] = {}
    for rel in geometric:
        if rel.predicate in _CORROBORATES:
            near_pairs.setdefault(frozenset({rel.subject_id, rel.object_id}), rel)

    merged: list[SpatialRelation] = []
    for rel in semantic:
        if not rel.object_id:                       # AGAINST_WALL, SUPPORTED_BY
            merged.append(rel)
            continue
        support = near_pairs.get(frozenset({rel.subject_id, rel.object_id}))
        if support is None:
            merged.append(rel)
            continue
        independent = rel.subject_id in confirmed and rel.object_id in confirmed
        merged.append(rel.model_copy(update={
            "confidence": "HIGH" if independent else "MEDIUM",
            "source": "semantic+geometry" if independent else "semantic",
            "note": (f"{rel.note}; geometry agrees ({support.note})" if independent
                     else f"{rel.note}; the reader's own box agrees ({support.note}), "
                          f"but nothing independent confirms it")}))
    merged.extend(geometric)
    return merged


def _conflicts(semantic: list[SpatialRelation], boxes: dict[str, tuple],
               names: dict[str, str]) -> list[SpatialConflict]:
    """A named relationship the picture puts far apart.

    Neither side is deleted. The reader may be right about intent while the
    boxes are right about this render, and only a person can say which.
    """
    out: list[SpatialConflict] = []
    for rel in semantic:
        # FACES is deliberately absent. Facing something across the room is the
        # normal arrangement - a sofa faces a television on the opposite wall -
        # so distance says nothing about whether the claim is wrong. Only
        # AGAINST and ON_TOP_OF assert nearness, and only those can contradict
        # it. Including FACES here blocked exactly the sofa/tv case this layer
        # exists to capture.
        if not rel.object_id or rel.predicate not in ("AGAINST", "ON_TOP_OF"):
            continue
        box_a, box_b = boxes.get(rel.subject_id), boxes.get(rel.object_id)
        if not box_a or not box_b:
            continue
        distance = _distance(box_a, box_b)
        if distance > CONFLICT_DISTANCE:
            out.append(SpatialConflict(
                subject_id=rel.subject_id, predicate=rel.predicate,
                object_id=rel.object_id,
                semantic_evidence=rel.note or f"reader placed it {rel.predicate}",
                geometry_evidence=(f"{names.get(rel.subject_id, '?')} and "
                                   f"{names.get(rel.object_id, '?')} are {distance:.2f} "
                                   f"apart in the render"),
                resolution="unresolved"))
    return out


def _groups(by_room: dict[str, list[SceneElement]], boxes: dict[str, tuple],
            confirmed: set[str]) -> list[SpatialGroup]:
    """Clusters that belong together. Membership only, never a position.

    An anchor claims companions in its own room. Where boxes exist, a companion
    must also be nearby - a wardrobe across the room is not part of the bed
    group. Without boxes the pattern alone decides and confidence stays LOW.
    """
    out: list[SpatialGroup] = []
    for room_id, elements in sorted(by_room.items()):
        for group_type, (anchors, companions) in sorted(GROUP_PATTERNS.items()):
            heads = [e for e in elements if e.semantic_type in anchors]
            if not heads:
                continue
            for index, head in enumerate(heads):
                members = [head.element_id]
                head_box = boxes.get(head.element_id)
                for other in elements:
                    if other.element_id == head.element_id:
                        continue
                    if other.semantic_type not in companions:
                        continue
                    other_box = boxes.get(other.element_id)
                    if head_box and other_box and _distance(head_box, other_box) > NEAR_DISTANCE * 2:
                        continue                    # in the room, but not this arrangement
                    members.append(other.element_id)
                if len(members) < 2:
                    continue                        # an anchor alone is not a group
                geometry_backed = all(m in confirmed for m in members)
                out.append(SpatialGroup(
                    group_id=f"{room_id}.{group_type}.{index}",
                    group_type=group_type, room_id=room_id, members=members,
                    confidence="HIGH" if geometry_backed else "LOW",
                    source="semantic+geometry" if geometry_backed else "semantic"))
    return out


# ── the entry point ──────────────────────────────────────────────────────

def build_spatial_graph(reading: SceneReading,
                        detections: Optional[dict[str, list[dict]]] = None,
                        *, provider: str = "") -> SpatialGraph:
    """The moodboard's arrangement, as structure. No coordinates, ever.

    Parameters
    ----------
    reading
        The approved render, already read and checked. Elements the checks
        rejected are skipped: an element the second look called a mismatch
        should not be drawing relationships around itself.
    detections
        Optional, per room: ``{"living_room": [{"label", "bbox", "score"}]}``
        in the same normalised (x0, y0, x1, y1) fractions the reading uses.
        None means no geometry - every relation then rests on the reader alone
        and is capped at LOW. Nothing here imports the detector; the caller
        decides whether one ran.
    """
    usable = [el for el in reading.elements
              if el.element_id and el.check in ("unchecked", "ok")]
    by_room: dict[str, list[SceneElement]] = {}
    for el in usable:
        by_room.setdefault(el.room_id, []).append(el)

    warnings: list[str] = []
    skipped = len(reading.elements) - len(usable)
    if skipped:
        warnings.append(f"{skipped} element(s) excluded: flagged by the crop check or "
                        f"duplicate pass, so they do not draw relationships")

    boxes: dict[str, tuple] = {}
    confirmed: set[str] = set()
    unmatched: list[UnmatchedDetection] = []
    for room_id, elements in by_room.items():
        room_detections = (detections or {}).get(room_id) or []
        matched, leftovers = _match_detections(elements, room_detections)
        for el in elements:
            box, is_confirmed = _box_for(el, matched)
            if box:
                boxes[el.element_id] = box
            if is_confirmed:
                confirmed.add(el.element_id)
        for det in leftovers:
            unmatched.append(UnmatchedDetection(
                label=str(det.get("label", "")), bbox=tuple(det["bbox"]),
                room_id=room_id, score=float(det.get("score", 0.0))))

    if detections is None:
        warnings.append("no image geometry supplied; relationships rest on the "
                        "reader's own words and boxes, so none reach HIGH")

    nodes = [SpatialNode(
        node_id=el.element_id, semantic_type=el.semantic_type, name=el.name,
        room_id=el.room_id, geometry_confirmed=el.element_id in confirmed,
        source_confidence="HIGH" if el.element_id in confirmed else "LOW",
    ) for el in usable]

    semantic = _semantic_relations(usable, by_room)
    geometric: list[SpatialRelation] = []
    for elements in by_room.values():
        ordered = sorted(elements, key=lambda e: e.element_id)   # deterministic
        pairs = [(a, b) for i, a in enumerate(ordered) for b in ordered[i + 1:]]
        geometric.extend(_geometric_relations(pairs, boxes))

    names = {el.element_id: (el.name or el.semantic_type) for el in usable}
    relations = _merge(semantic, geometric, confirmed)
    conflicts = _conflicts(semantic, boxes, names)
    groups = _groups(by_room, boxes, confirmed)

    if unmatched:
        warnings.append(f"{len(unmatched)} detection(s) matched no element in the "
                        f"reading; recorded, never added to the plan")

    return SpatialGraph(
        provider=provider or reading.provider,
        created_at=datetime.now(timezone.utc).isoformat(),
        nodes=nodes,
        relations=sorted(relations, key=lambda r: (r.subject_id, r.predicate, r.object_id)),
        groups=groups,
        conflicts=conflicts,
        unmatched_detections=unmatched,
        warnings=warnings,
    )


__all__ = ["apply_spatial_graph", "build_spatial_graph", "GROUP_PATTERNS",
           "NEAR_DISTANCE", "ADJACENT_GAP", "AXIS_TOLERANCE", "CONFLICT_DISTANCE"]


# ── feeding the object plan ──────────────────────────────────────────────
#
# The compiler has had relation machinery since M3 - `_relation_candidates`
# generates positions from `in_front_of`/`beside`/`under`/`around`/`facing`, and
# `_pick_support` tries `support_key` before guessing. On the planner path
# `coerce.py` fills both. On the MOODBOARD path `merge_reading_into_plan` never
# did, so every item read from an approved render reached the compiler with
# `relation=None` and `support_key=None`. The machinery was built and starved.
#
# This is the bridge. It does not place anything and does not compute a
# coordinate: it fills two existing fields so the existing engine can.

#: Which graph predicate becomes which `RelationType`, and which are
#: deliberately left in the graph instead.
#:
#: LEFT_OF / RIGHT_OF / ABOVE / BELOW are absent BY DESIGN. They carry
#: `frame="camera"`, and a render has no fixed left relative to the floor plan -
#: turning one into a placement would put a sofa on whichever wall the camera
#: happened to face. NEAR and OVERLAPS are absent because neither says the
#: pieces belong together: OVERLAPS is as often occlusion or a bad box.
_PREDICATE_TO_RELATION: dict[str, str] = {
    "AGAINST_WALL": "against_wall",
    "FACES": "facing",
    "ADJACENT_TO": "beside",
    "AGAINST": "beside",          # "against the sofa" means beside it, not on a wall
}

#: When one piece carries several usable relations, which wins. ONE list, and it
#: answers a different question from the compiler's `ANCHOR_RANK`: that orders
#: the sequence pieces are PLACED in, this picks which single relation an item
#: carries. They do not compete.
#:
#: Ordered by how much each constrains the result. `against_wall` fixes a whole
#: edge, `facing` fixes an orientation, `beside` only fixes a neighbour.
_RELATION_PRIORITY = ("against_wall", "facing", "beside")

#: Predicates that mean "this rests on that", which is `support_key`, not a
#: relation - the compiler reads the two separately and they never compete.
_SUPPORT_PREDICATES = ("ON_TOP_OF", "SUPPORTED_BY")


def apply_spatial_graph(plan, graph: SpatialGraph, *,
                        accept_geometry_from: str = "MEDIUM") -> tuple[object, list[str]]:
    """Fill `relation` and `support_key` on plan items from the graph.

    Returns the same plan object (mutated) and notes for the job feed.

    Confidence gate
    ---------------
    An INFERRED relation - one geometry proposed - must clear
    `accept_geometry_from`. A STATED one - the reader's own `against`/`faces` -
    is accepted at LOW, and that is deliberate rather than lax: those words
    already steer placement today through `_prefer_hint`, with no gate at all.
    Gating them here would place the moodboard's furniture WORSE than before
    this function existed, which is not an improvement.

    Nothing is consumed for a piece named in an unresolved conflict, and no
    camera-frame relation is consumed at any confidence.
    """
    by_element = {i.element_id: i for i in plan.items if getattr(i, "element_id", "")}
    if not by_element:
        return plan, ["no plan item carries an element_id; the graph cannot be attached"]

    disputed = {c.subject_id for c in graph.conflicts if c.resolution == "unresolved"}
    disputed |= {c.object_id for c in graph.conflicts
                 if c.resolution == "unresolved" and c.object_id}
    rank = {level: index for index, level in enumerate(("HIGH", "MEDIUM", "LOW", "UNKNOWN"))}
    floor = rank.get(accept_geometry_from, 1)

    supports: dict[str, str] = {}
    candidates: dict[str, list[tuple[int, str, Optional[str]]]] = {}
    skipped_camera = skipped_conflict = skipped_weak = 0

    for rel in graph.relations:
        if rel.frame == "camera":
            skipped_camera += 1
            continue
        if rel.subject_id in disputed or (rel.object_id and rel.object_id in disputed):
            skipped_conflict += 1
            continue
        stated = rel.source in ("semantic", "placement", "semantic+geometry")
        if not stated and rank.get(rel.confidence, 3) > floor:
            skipped_weak += 1
            continue

        subject = by_element.get(rel.subject_id)
        if subject is None:
            continue
        target = by_element.get(rel.object_id) if rel.object_id else None

        if rel.predicate in _SUPPORT_PREDICATES:
            if target is not None and subject.placement == "on_surface":
                supports.setdefault(subject.object_key, target.object_key)
            continue

        relation_type = _PREDICATE_TO_RELATION.get(rel.predicate)
        if relation_type is None:
            continue
        if relation_type != "against_wall" and target is None:
            continue                    # a relation with no target places nothing
        candidates.setdefault(subject.object_key, []).append(
            (_RELATION_PRIORITY.index(relation_type), relation_type,
             target.object_key if target else None))

    from ..intelligence.schema import ObjectRelation

    relations_set = supports_set = 0
    for item in plan.items:
        if item.object_key in supports and not item.support_key:
            item.support_key = supports[item.object_key]
            supports_set += 1
        options = candidates.get(item.object_key)
        if not options or item.relation is not None:
            continue                    # never overwrite what the planner decided
        options.sort()                  # priority, then type, then target - deterministic
        _, relation_type, target_key = options[0]
        item.relation = ObjectRelation(type=relation_type, target_key=target_key)
        relations_set += 1

    notes = [f"spatial graph: {relations_set} relation(s) and {supports_set} support "
             f"link(s) attached to the object plan"]
    if skipped_camera:
        notes.append(f"{skipped_camera} camera-frame relation(s) left in the graph; "
                     f"a render's left is not the room's left")
    if skipped_conflict:
        notes.append(f"{skipped_conflict} relation(s) skipped: the piece is in an "
                     f"unresolved conflict")
    if skipped_weak:
        notes.append(f"{skipped_weak} inferred relation(s) below {accept_geometry_from} "
                     f"confidence were not used")
    return plan, notes

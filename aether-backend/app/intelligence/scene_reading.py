"""Read the approved moodboard back into elements, crops and surfaces.

The client agrees to a picture; from that moment the picture is the brief. This
turns each approved room render into:

  * one tight crop per visible piece, which image-to-3D turns into a mesh
  * metadata linking that mesh to the 2D element it came from
  * the room's wall and floor as MATERIALS, never as generated geometry

Why surfaces are materials only: room geometry is built procedurally by Blender
from the room boundary, which is what keeps corners square, doors aligned, and
lets the spatial validator prove nothing blocks a doorway. Generating wall
meshes from crops would replace geometry that is correct by construction with
geometry that is correct by luck.

Why positions are words, not coordinates: a render has no depth and does not
obey the room's real size — a 2.5 x 2.0 m bathroom renders as a long spa. The
`against` and `faces` fields are arrangement INTENT for the planner, which still
decides actual metres and still proves the result.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

from . import vocab
from .schema import (ElementDefinition, ElementInstance, ElementInventory, ObjectPlan, WallFinish,
                     ObjectPlanItem, RoomSurfaces, SceneElement, SceneReading)

try:
    from PIL import Image
except ImportError:                                        # pragma: no cover
    Image = None                                           # type: ignore

log = logging.getLogger("aether.intelligence.scene_reading")

CROP_DIR = "planning/scene_crops"
PAD = 0.02          # a hair of context; a tight box makes a better mesh

# Things the model is told not to box, guarded again here because a reading that
# boxed "the room" would send a whole render to image-to-3D and get a doll's
# house back — and walls and floors are materials in this pipeline, not meshes.
NOT_ELEMENTS = {"room", "wall", "walls", "floor", "ceiling", "window", "door", "doorway"}


def _hex(value: Any) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if not v.startswith("#"):
        v = "#" + v
    return v.upper() if len(v) == 7 and all(c in "0123456789abcdefABCDEF" for c in v[1:]) else ""


# A floor, not a quality bar. Below this a side is a handful of pixels and
# there is no shape to read; above it, whether the crop is usable is decided by
# looking at it - the isolated check, then a person - not by its area.
#
# The area threshold this replaces (6,000 px^2, 30 px short side) was measured
# and found to be judging the wrong thing. It discarded a towel rail whose
# silhouette is plainly legible at 59 x 88, while three stools boxed as one
# "bar stool" and a bed boxed as a "rug" sailed through on size alone. Detail
# retention across our whole crop range is 83-95 % at silhouette scale and
# 1-36 % at texture scale, and image-to-3D infers geometry from the former -
# so pixel count is a weak proxy for the only thing that matters, which is
# whether the piece can be recognised.
MIN_LEGIBLE_PX = 16
MAX_AREA_FRACTION = 0.92   # a box this big is the room, not a thing in it

# Every crop is enlarged to roughly the size that image-to-3D was validated at
# (the mesh we kept came from a 1024 x 452 source). LANCZOS adds no information
# - measured, it recovers 28-54 % of lost detail and none of the texture - so
# this is a formatting step, not a quality one. It is here because it is free
# (5-10 ms) and because the alternative, a diffusion upscaler, was measured
# making the input LESS faithful: sharper, with the arms and cushions of the
# sofa quietly redrawn. A changed silhouette is worse than a soft one when the
# mesh is built from the silhouette.
UPSCALE_SHORT_PX = 512
UPSCALE_MAX_LONG_PX = 1536
UPSCALE_MIN_GAIN = 1.2     # below this the resample costs more sharpness than it buys


def _bbox(raw: Any, warn: Optional[list] = None, label: str = "") -> Optional[tuple[float, float, float, float]]:
    """Four fractions in order, or None — never a plausible-looking guess.

    Vision models answer in 0-1 or in 0-1000, and the difference is silent: a
    0-1000 box read as fractions crops a few pixels of the top-left corner.

    The dangerous case is a box that mixes BOTH inside itself. Gemini really
    returned `[402, 237, 1.0, 712]` for a sofa: `1.0` meant "the right edge" as
    a fraction while its neighbours were 0-1000. Scaling the whole box by 1000
    turned that into 0.001, and because the old code then SORTED the pair, the
    inversion vanished and the crop silently came from the left 40 % of the
    image instead of the right 60 %. It looked like a normal result.

    So: decide the convention, then demand the box be self-consistent in it.
    An inconsistent box is rejected and said out loud — the same standard the
    mock fallback and the stale photo reference were held to.
    """
    def reject(why: str) -> None:
        if warn is not None:
            warn.append(f"{label or 'element'}: unusable box {raw!r} — {why}")

    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        reject("not four numbers")
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        reject("not numeric")
        return None
    if any(v != v or v in (float("inf"), float("-inf")) for v in vals):
        reject("not finite")
        return None

    scaled = max(vals) > 1.5
    if scaled:
        # In a 0-1000 box every coordinate is either 0 (unambiguous) or well
        # above 1. Anything between is a fraction that wandered in.
        stray = [v for v in vals if 0 < v <= 1.5]
        if stray:
            reject(f"mixes 0-1000 with fractions {stray}")
            return None
        vals = [v / 1000.0 for v in vals]

    x0, y0, x1, y1 = vals
    if x1 <= x0 or y1 <= y0:
        # Not silently swapped: a reversed pair is how the mixed-convention bug
        # disguised itself, and a genuinely reversed box is just as suspect.
        reject("corners are not top-left then bottom-right")
        return None
    if min(vals) < -0.01 or max(vals) > 1.01:
        reject("outside the image")
        return None
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)
    w, h = x1 - x0, y1 - y0
    if w <= 0.01 or h <= 0.005:
        reject(f"degenerate ({w:.3f} x {h:.3f} of the image)")
        return None
    if w * h > MAX_AREA_FRACTION:
        reject("covers the whole image — that is the room, not an object in it")
        return None
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


MAX_PHRASE = 120        # "oak floorboards" is a surface; a paragraph is a loop


def _phrase(value: Any, warn: list[str], label: str, limit: int = MAX_PHRASE) -> str:
    """A short description of a surface, or a truncated one said out loud.

    These fields are asked for as a couple of words and are used to pick a
    material. A bathroom really came back with 39,640 characters of looping
    filler - "properly seamlessly today accurately correctly today easily
    safely everywhere" repeated to the token limit - which sailed into the
    scene file and made it unreadable. Runaway generation is a known failure of
    small models; leaving the field unbounded meant the whole project carried
    it forever.
    """
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    warn.append(f"{label}: {len(text):,} characters is a runaway answer; kept the first {limit}")
    return text[:limit].rstrip()


WALL_NAMES = ("back", "left", "right", "front")
#: The way a piece faces when it faces a named wall, as a unit (dx, dz) in the
#: room frame: the back wall is -z (the room rectangle's north edge), the
#: right wall +x. The compiler's yaw-0 forward is (0, -1), i.e. "back".
FACING_DIR: dict[str, tuple[float, float]] = {
    "back": (0.0, -1.0), "front": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0),
}


def _frac(raw: Any) -> Optional[float]:
    """0-1 from a whole number out of 1000 (the prompt's convention) or a
    fraction; None when unreadable. Clamped, never rejected: a 1040 is a
    piece against the wall, not a reason to lose its anchor."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1.0:
        v = v / 1000.0
    return min(1.0, max(0.0, v))


def _pair(raw: Any) -> Optional[tuple[float, float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    a, b = _frac(raw[0]), _frac(raw[1])
    if a is None or b is None:
        return None
    return (min(a, b), max(a, b))


def render_frame_position(wall: str, along: Optional[float], depth: Optional[float],
                          height: Optional[float], placement: str,
                          width_m: float, length_m: float, height_m: float,
                          ) -> Optional[tuple[float, float, float]]:
    """Room-local metres from the render-frame fractions. Pure and total.

    x runs along the back wall from the left corner (0..width), z from the
    back wall towards the camera (0..length), y up. A named wall snaps the
    coordinate it fixes - "against the back wall" is z = 0 whatever `depth`
    said - because the wall is the stronger claim. Floor pieces are at y = 0;
    a wall piece's y is its bottom edge; a ceiling piece hangs from the top.
    """
    if along is None and depth is None and wall not in WALL_NAMES:
        return None
    x = (0.5 if along is None else along) * width_m
    z = (0.5 if depth is None else depth) * length_m
    if wall == "back":
        z = 0.0
    elif wall == "front":
        z = length_m
    elif wall == "left":
        x = 0.0
    elif wall == "right":
        x = width_m
    if placement == "ceiling":
        y = height_m
    elif placement == "floor":
        y = 0.0
    else:
        y = (0.0 if height is None else height) * height_m
    return (round(x, 2), round(y, 2), round(z, 2))


def anchor_from_bbox(bbox: tuple[float, float, float, float], placement: str,
                     width_m: float, length_m: float, height_m: float,
                     ) -> Optional[tuple[float, float, float]]:
    """The anchor the crop box alone implies, for when the reader is silent.

    The box is REQUIRED on every element and already validated, so it is the
    one cue that always exists. Horizontally it is a direct correspondence
    under the fixed frame - the picture's left is the room's left - so the
    box's centre is `along`. Front-to-back it is ORDINAL, not metric: a piece
    whose box bottom sits lower in the frame is nearer the camera, but turning
    that into metres needs a horizon this layer does not have. That is enough
    for the only thing the anchor does - order candidates the solver has
    already ruled valid - and it is marked `derived` so nothing downstream
    mistakes it for something the reader actually said.
    """
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    along = (x0 + x1) / 2.0
    if placement in ("wall", "ceiling"):
        # Image y grows downward, so the box's bottom edge is (1 - y1) up.
        return render_frame_position("", along, None, max(0.0, 1.0 - y1), placement,
                                     width_m, length_m, height_m)
    return render_frame_position("", along, y1, None, placement, width_m, length_m, height_m)


def ensure_anchors(reading, rooms) -> int:
    """Give every boxed element an anchor, whatever the reader answered.

    `rooms` maps room_id to anything carrying width_m / length_m / height_m.
    Idempotent: an element that already has a position keeps it, so this can
    run on every load. Returns how many were derived.

    This is what makes the anchor a property of EVERY reading rather than of
    the lucky ones: a project read before the frame fields existed gets its
    anchors the next time its plan is opened, from the box it already carries,
    with no model call and no repaint.
    """
    filled = 0
    for el in reading.elements:
        if el.position_m is not None or el.bbox is None:
            continue
        room = rooms.get(el.room_id)
        if room is None:
            continue
        position = anchor_from_bbox(el.bbox, el.placement, float(room.width_m),
                                    float(room.length_m), float(room.height_m))
        if position is None:
            continue
        el.position_m = position
        el.position_source = "derived"
        filled += 1
    return filled


def wall_finish_extent(wall: str, span: Optional[tuple[float, float]], band: Optional[tuple[float, float]],
                       width_m: float, length_m: float, height_m: float) -> tuple[float, float, float, float]:
    """Metres along the named wall (from its left end, seen from inside) and
    up from the floor. Back and front walls run the room's width, left and
    right its length. A missing span or band means the whole wall."""
    run = width_m if wall in ("back", "front") else length_m
    s0, s1 = span or (0.0, 1.0)
    b0, b1 = band or (0.0, 1.0)
    return (round(s0 * run, 2), round(s1 * run, 2), round(b0 * height_m, 2), round(b1 * height_m, 2))


def coerce_room_reading(raw: dict, room, vertical, warnings: list[str]):
    """Validate one room's raw reading into (elements, surfaces)."""
    elements: list[SceneElement] = []
    seen: dict[str, int] = {}
    for item in (raw.get("elements") or []):
        name = str(item.get("name") or "").strip()
        given = str(item.get("semantic_type") or "").strip().lower().replace(" ", "_")
        if name.lower() in NOT_ELEMENTS or given in NOT_ELEMENTS:
            warnings.append(
                f"{room.room_id}: ignored {(name or given)!r} - surfaces are materials, not meshes")
            continue
        box = _bbox(item.get("bbox"), warnings, f"{room.room_id}/{name or given}")
        if box is None:
            continue
        sem = vocab.canonical_type(name, given)
        seed = f"{room.room_id}|{sem}|{name}|{box}"
        n = seen.get(seed, 0)
        seen[seed] = n + 1
        placement = vocab.placement_for(sem, str(item.get("placement") or ""))
        wall = str(item.get("wall") or "").strip().lower()
        wall = wall if wall in WALL_NAMES else ""
        facing = str(item.get("facing") or "").strip()
        # Always an anchor: what the reader said, else what the box implies.
        height_frac = _frac(item.get("height"))
        source = "read"
        if placement == "wall" and not height_frac:
            # Zero counts as unanswered here, not as a measurement: a piece
            # that hangs ON A WALL cannot have its bottom edge on the floor,
            # so 0 is the model declining, the same as omitting the field.
            # Measured live on proj_a25a006c88: a framed print whose box ran
            # from the top of the picture to a third of the way down, and a
            # wall-mounted TV, both came back height 0 and were stored at
            # y = 0.0 - on the floor. The box knows: image y grows downward,
            # so the bottom edge is (1 - y1) up the picture. Any component the
            # box had to answer makes the whole anchor `derived` - never claim
            # the reader said more than it did.
            height_frac = max(0.0, 1.0 - box[3])
            source = "derived"
        position = render_frame_position(
            wall, _frac(item.get("along")), _frac(item.get("depth")), height_frac,
            placement, float(room.width_m), float(room.length_m), float(room.height_m))
        if position is None:
            position = anchor_from_bbox(box, placement, float(room.width_m),
                                        float(room.length_m), float(room.height_m))
            source = "derived" if position is not None else ""
        elements.append(
            SceneElement(
                element_id="el_" + hashlib.sha1(f"{seed}#{n}".encode("utf-8")).hexdigest()[:10],
                room_id=room.room_id,
                name=name or sem.replace("_", " "),
                semantic_type=sem,
                bbox=box,
                material=str(item.get("material") or "").strip(),
                color=_hex(item.get("color")),
                placement=placement,
                against=str(item.get("against") or "").strip(),
                faces=str(item.get("faces") or "").strip(),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.6) or 0.6))),
                wall=wall,
                position_m=position,
                position_source=source,
                facing=facing,
                facing_dir=FACING_DIR.get(facing.lower()),
            )
        )

    raw_surfaces = raw.get("surfaces") or {}
    surfaces = None
    if raw_surfaces:
        finishes: list[WallFinish] = []
        for zone in (raw_surfaces.get("walls") or []):
            if not isinstance(zone, dict):
                continue
            wall = str(zone.get("wall") or "").strip().lower()
            if wall not in WALL_NAMES:
                warnings.append(f"{room.room_id}: wall finish on {wall or '?'!r} dropped - not a named wall")
                continue
            finishes.append(WallFinish(
                wall=wall,
                material=_phrase(zone.get("material"), warnings, f"{room.room_id}.{wall}.material"),
                color=_hex(zone.get("color")),
                pattern=_phrase(zone.get("pattern"), warnings, f"{room.room_id}.{wall}.pattern"),
                extent_m=wall_finish_extent(wall, _pair(zone.get("span")), _pair(zone.get("band")),
                                            float(room.width_m), float(room.length_m), float(room.height_m)),
            ))
        surfaces = RoomSurfaces(
            room_id=room.room_id,
            wall_color=_hex(raw_surfaces.get("wall_color")),
            wall_material=_phrase(raw_surfaces.get("wall_material"), warnings,
                                  f"{room.room_id}.wall_material"),
            floor_color=_hex(raw_surfaces.get("floor_color")),
            floor_material=_phrase(raw_surfaces.get("floor_material"), warnings,
                                   f"{room.room_id}.floor_material"),
            notes=_phrase(raw_surfaces.get("notes"), warnings, f"{room.room_id}.notes", limit=400),
            walls=finishes,
        )
    return elements, surfaces


DUPLICATE_IOU = 0.6         # two boxes this alike are one piece counted twice
DUPLICATE_INSIDE = 0.8      # ...or one box swallowed almost whole by another


def _overlap(a, b) -> tuple[float, float]:
    """(IoU, how much of the SMALLER box lies inside the larger).

    Both are needed. IoU alone misses a box nested inside a much bigger one:
    the third 'black bar stool' sat entirely within the first, and still scored
    only 0.42 because the union was dominated by the big box.
    """
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0, 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter), inter / min(area_a, area_b)


def mark_duplicates(reading: SceneReading) -> int:
    """Flag boxes that are really the same piece twice. No model call, no cost.

    Three 'black bar stool' boxes came back each reaching from its stool to the
    right edge of the kitchen, so each contained the next. Generating all three
    buys the same mesh three times at 30 credits each. The widest box keeps the
    claim, on the reasoning that the narrower ones drifted off it.

    Only pieces of the SAME semantic type are compared. Overlap on its own says
    nothing - a throw pillow is entirely inside the sofa's box and is not the
    sofa - and two sofas that share no pixels are two sofas, which is a mistake
    worth naming because I made it from the crops alone.
    """
    flagged = 0
    by_key: dict[tuple[str, str], list] = {}
    for el in reading.elements:
        if el.bbox and el.check != "duplicate":
            by_key.setdefault((el.room_id, el.semantic_type), []).append(el)
    for els in by_key.values():
        els.sort(key=lambda e: -((e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1])))
        for i, el in enumerate(els):
            if el.check == "duplicate":
                continue
            for other in els[i + 1:]:
                if other.check == "duplicate":
                    continue
                iou, inside = _overlap(el.bbox, other.bbox)
                if iou >= DUPLICATE_IOU or inside >= DUPLICATE_INSIDE:
                    other.check = "duplicate"
                    other.check_note = (f"{max(iou, inside):.0%} the same box as "
                                        f"{el.name!r}, already claimed")
                    flagged += 1
    return flagged


def flag_implausible(reading: SceneReading, room_types: dict[str, str]) -> int:
    """Mark pieces that cannot belong to the room they were read from.

    Valid JSON is not valid semantics. A `freestanding bath` came back inside a
    living room: structurally perfect, correctly boxed, and wrong. Salvage will
    happily preserve a hallucination, so something has to say so before a human
    is asked to approve spend on it.

    Deliberately narrow. Only `vocab.ROOM_BOUND_TYPES` is consulted, which lists
    the handful of pieces genuinely impossible elsewhere - a bath, a hob, a bed.
    Everything else is left alone, because most furniture is room-agnostic and a
    warning that fires on ordinary designs teaches the reviewer to ignore
    warnings.

    Flags, never deletes, and never overwrites a verdict the isolated crop check
    or the duplicate pass already reached: those looked at the picture, this only
    looks at the label, and the picture is the better evidence.
    """
    flagged = 0
    for el in reading.elements:
        if el.check not in ("unchecked", "ok"):
            continue
        allowed = vocab.room_bound(el.semantic_type)
        if not allowed:
            continue
        room_type = (room_types.get(el.room_id) or el.room_id or "").strip().lower()
        if not room_type or room_type in allowed:
            continue
        el.check = "implausible"
        el.check_note = (f"a {el.semantic_type.replace('_', ' ')} in "
                         f"{room_type.replace('_', ' ')} - expected in: "
                         f"{', '.join(sorted(allowed))}")
        flagged += 1
    return flagged


# Elements that reduce to the same shape key are ONE piece of furniture seen
# more than once, and cost one generation between them. Three "black bar stool"
# boxes in a kitchen are three placements of one stool; generating each would
# buy the same mesh three times at 30 credits each.
#
# The room IS part of the key, which costs credits and is deliberate. Dropping
# it saved two more generations on the sample project by merging the master
# bedroom's bed with the second bedroom's - two plainly different beds in the
# moodboard, which would have put one of them in both rooms. That is the exact
# mismatch this whole path exists to remove, so the saving is refused. Within
# one room, two things named the same really are the same thing.
#
# Colour is not part of the key: the planner tints the placed object, and a
# tinted copy is free.
def shape_key(element: SceneElement) -> str:
    """What this element IS, within its room, ignoring which copy it is.

    Keyed on WHERE the piece sits, not what the model called it. The name is
    free text from a non-deterministic vision call: the same sofa came back as
    "striped turquoise sofa" on one read and "striped blue green sofa" on the
    next, and because this key is also the checkpoint filename, that wording
    change alone re-priced seven pieces we already owned at 30 credits each.

    A box centre rounded to a tenth of the image is stable across re-reads (the
    box moves a little, the piece does not) and still separates two sofas at
    opposite ends of one room. Pieces whose centres land in the same cell are
    the same piece seen twice - which is exactly the three overlapping bar-stool
    boxes that made dedup worth having.
    """
    box = element.bbox or (0.0, 0.0, 0.0, 0.0)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return f"{element.room_id}|{element.semantic_type}|{cx:.1f}x{cy:.1f}"


def _norm_attr(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def _dims_bucket(element: SceneElement) -> str:
    """Dimensions to the nearest 10 cm, so a 44 cm and a 46 cm stool agree."""
    if not element.dimensions_m:
        return ""
    return "x".join(f"{round(v * 10) / 10:.1f}" for v in element.dimensions_m)


def canonical_key(element: SceneElement) -> str:
    """What this element IS, with NOTHING about where it sits.

    `shape_key` keeps the box centre, and its own comment promised that three
    bar stools would be "three placements of one stool, one generation". Along
    a counter the three stools have three centres, so it bought the stool three
    times - measured on the real project, 90 credits for 30 credits of stool.

    This key is the winner of a six-way ablation over that project and five
    golden cases (research/element-first/identity-ablation.json): room, type,
    dimensions bucket, material and colour, scoring 0 false merges and 0 false
    splits. The production key scored 2 and 10.

    The rule that costs the most and matters the most: a piece with NO positive
    evidence - no material, no colour, no dimensions - keeps its own key. Two
    same-type pieces in one room that both say nothing are not known to be the
    same, and an unknown must not merge. A wrong merge puts one bed in two
    bedrooms; a missed merge buys a second stool. Only one of those is visible
    to the client.

    Room stays in the key on purpose. Dropping it merged the master bedroom's
    bed with the second bedroom's - two plainly different beds - and that is the
    mismatch this whole path exists to remove.
    """
    return canonical_key_for(element.room_id, element.semantic_type, element.material,
                             element.color, element.dimensions_m, element.element_id)


def canonical_key_for(room_id: str, semantic_type: str, material: str, color: str,
                      dimensions_m, fallback_id: str) -> str:
    """The identity rule itself, so a reading row and a plan item that describe
    the same piece land on the same key. `fallback_id` is what a piece with no
    evidence keeps to itself."""
    material, color = _norm_attr(material), _norm_attr(color)
    dims = ""
    if dimensions_m:
        dims = "x".join(f"{round(v * 10) / 10:.1f}" for v in dimensions_m)
    if not (material or color or dims):
        return f"{room_id}|{semantic_type}|?{fallback_id}"
    return f"{room_id}|{semantic_type}|{dims}|{material}|{color}"


def definitions_from_plan(plan: ObjectPlan) -> tuple[list[ElementDefinition], list[ElementInstance]]:
    """The inventory BEFORE any room is painted, from the object plan.

    The plan already folds the client's photographed pieces (with their crops)
    and the brief's pieces, per room, with `count`. Grouping them by the same
    canonical key the moodboard reading uses is what lets a piece decided here
    be recognised there. Deterministic; no model is asked anything.
    """
    groups: dict[str, list[ObjectPlanItem]] = {}
    for item in plan.items:
        key = canonical_key_for(item.room_id, item.semantic_type, item.material_hint,
                                item.color_hint, item.approx_dimensions, item.object_key)
        groups.setdefault(key, []).append(item)

    definitions: list[ElementDefinition] = []
    instances: list[ElementInstance] = []
    for key in sorted(groups):
        items = groups[key]
        lead = next((i for i in items if i.crop_ref), items[0])
        element_id = "cel_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        count = sum(i.count for i in items)
        definitions.append(ElementDefinition(
            element_id=element_id, room_id=lead.room_id, semantic_type=lead.semantic_type,
            canonical_name=lead.name, material=lead.material_hint, color=lead.color_hint,
            dimensions_m=lead.approx_dimensions,
            identity_method="unresolved" if "|?" in key else "room_type_dims_material_colour",
            instance_count=count, source_element_ids=[i.object_key for i in items]))
        n = 0
        for item in items:
            for _ in range(item.count):
                n += 1
                instances.append(ElementInstance(
                    instance_id=f"{element_id}.{n}", element_id=element_id,
                    room_id=item.room_id, source_element_id=item.object_key,
                    crop_ref=item.crop_ref))
    return definitions, instances


def distinct_shapes(elements: list[SceneElement]) -> dict[str, list[SceneElement]]:
    """Group elements by canonical key, best crop first within each group.

    Grouped by what the piece IS (`canonical_key`), not where it sits: the
    group is what gets generated once and placed N times. The biggest native
    crop leads: it is the one that gets generated, and more pixels of the same
    piece is the only thing here that is unambiguously better. Whether it is
    worth generating at all is not decided by size - that was measured and
    retired (ADR-003 s2) - only which of several views wins.

    Meshes already bought under the old centre-keyed name are still found: the
    generation handler resolves a group to an existing legacy file before it
    spends anything (`generate_elements.storage_key`).
    """
    groups: dict[str, list[SceneElement]] = {}
    for el in elements:
        groups.setdefault(canonical_key(el), []).append(el)
    for els in groups.values():
        els.sort(key=lambda e: -(e.crop_px[0] * e.crop_px[1]))
    return groups


def resolve_elements(reading: SceneReading) -> tuple[list[ElementDefinition], list[ElementInstance]]:
    """Fold the reading's rows into canonical definitions and their instances.

    Deterministic: ids are content-addressed from the canonical key, order is
    fixed, and nothing is asked of a model. Only trustworthy rows take part -
    a row a check removed is not evidence of a piece, and the inventory already
    records that it was read.
    """
    groups = distinct_shapes([el for el in reading.elements if trustworthy(el)])
    definitions: list[ElementDefinition] = []
    instances: list[ElementInstance] = []
    for key in sorted(groups):
        els = groups[key]
        lead = els[0]
        element_id = "cel_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        unresolved = "|?" in key
        definitions.append(ElementDefinition(
            element_id=element_id, room_id=lead.room_id, semantic_type=lead.semantic_type,
            canonical_name=lead.name, material=lead.material, color=lead.color,
            dimensions_m=lead.dimensions_m,
            identity_method="unresolved" if unresolved else "room_type_dims_material_colour",
            instance_count=len(els), source_element_ids=[e.element_id for e in els],
            canonical_asset_id=next((e.asset_id for e in els if e.asset_id), "")))
        for n, el in enumerate(els, start=1):
            instances.append(ElementInstance(
                instance_id=f"{element_id}.{n}", element_id=element_id, room_id=el.room_id,
                source_element_id=el.element_id, bbox=el.bbox, crop_ref=el.crop_ref))
    return definitions, instances


def carry_asset_bindings(previous: SceneReading, reading: SceneReading,
                         valid=lambda asset_id: True) -> dict[str, int]:
    """Re-bind meshes already paid for onto a freshly re-read reading - P1-ASSET-001.

    Reading ids are minted from `room|type|name|bbox`; a re-read moves every
    box, so every id changes, and the `asset_id` on the old row used to vanish
    with it. The next generation run then bought the same stool again. The
    binding now follows the PIECE, matched by the position-free canonical key,
    which is the same rule that makes three stools one purchase.

    Deliberately NOT the id: the id's instability is a symptom, the lost
    binding is the cost. A piece whose evidence changed (other colour, other
    material, other size) gets another key, carries nothing, and is generated
    afresh - which is the right outcome, it IS a different piece. A row with
    no evidence at all (`|?` key) is not known to be the same piece and never
    inherits a mesh.

    Second pass, loose key `room|type|material|colour`: a re-read that
    re-measures a piece across a 10 cm dimension bucket would otherwise change
    its key and re-buy it. Applied only when that loose key is unique on BOTH
    sides and the mesh was not already handed out, so one mesh can never reach
    two different pieces.

    `valid(asset_id)` lets the caller drop bindings whose asset no longer
    resolves (deleted, or a failed ingest); the default keeps everything.
    Approvals are NOT carried: a human said yes to the OLD crop, and spend on
    a crop nobody has seen is exactly what the approval gate exists to stop.
    """
    exact: dict[str, str] = {}
    loose: dict[str, set[str]] = {}
    for el in previous.elements:
        if not el.asset_id or not valid(el.asset_id):
            continue
        key = canonical_key(el)
        if "|?" in key:
            continue
        exact.setdefault(key, el.asset_id)
        loose.setdefault(_loose_key(el), set()).add(el.asset_id)

    counts = {"carried": 0, "carried_loose": 0, "unbound": 0}
    unmatched: dict[str, list[SceneElement]] = {}
    for el in reading.elements:
        if el.asset_id:
            continue
        key = canonical_key(el)
        if "|?" in key:
            continue
        asset_id = exact.get(key)
        if asset_id:
            el.asset_id = asset_id
            counts["carried"] += 1
        else:
            unmatched.setdefault(_loose_key(el), []).append(el)
    handed_out = {el.asset_id for el in reading.elements if el.asset_id}
    for lkey, els in unmatched.items():
        ids = loose.get(lkey, set()) - handed_out
        if len(ids) == 1 and len(els) == 1:
            els[0].asset_id = next(iter(ids))
            handed_out.add(els[0].asset_id)
            counts["carried_loose"] += 1
    bound_before = {el.asset_id for el in previous.elements if el.asset_id and valid(el.asset_id)}
    counts["unbound"] = len(bound_before - handed_out)
    return counts


def _loose_key(el: SceneElement) -> str:
    return f"{el.room_id}|{el.semantic_type}|{_norm_attr(el.material)}|{_norm_attr(el.color)}"


def trustworthy(element: SceneElement) -> bool:
    """Does this element describe something really in the approved picture?

    `ok` means the isolated second look agreed with the label. A human ticking
    `approved` overrides that either way: they can rescue a crop the check
    misjudged, and a rejection stands even if the check liked it.
    """
    if element.approved is not None:
        return element.approved
    return element.check == "ok"


def element_inventory(reading: SceneReading) -> list[ElementInventory]:
    """Count the instances the reading found, per room and per type.

    Derived from the rows, deterministically, in a fixed order - no model is
    asked how many there are. This exists because the number was previously
    implicit in `len(...)` at every stage, so a shortfall had nowhere to show:
    three bar stools whose boxes each ran to the image edge reach the plan as
    ONE piece, and before this the other two left no trace.

    Recomputed rather than trusted, so a reading edited by a human review - or
    one written before this field existed - still produces the right answer.
    """
    counts: dict[tuple[str, str], ElementInventory] = {}
    for el in reading.elements:
        key = (el.room_id, el.semantic_type)
        row = counts.get(key)
        if row is None:
            row = ElementInventory(room_id=el.room_id, semantic_type=el.semantic_type)
            counts[key] = row
        row.read += 1
        if trustworthy(el):
            row.usable += 1
        else:
            reason = el.check if el.check != "unchecked" else "unapproved"
            row.lost_to[reason] = row.lost_to.get(reason, 0) + 1
    return [counts[k] for k in sorted(counts)]


def inventory_notes(inventory: list[ElementInventory]) -> list[str]:
    """One line per room/type whose usable count is below what was read.

    A note, not an error. The reading is still the best evidence available and
    a flagged duplicate is usually genuinely a duplicate - but "three read, one
    usable" is a fact the approval screen and the job trail should be able to
    state, instead of quietly planning one stool.
    """
    notes = []
    for row in inventory:
        if not row.discrepant:
            continue
        lost = ", ".join(f"{n} {reason}" for reason, n in sorted(row.lost_to.items()))
        notes.append(f"{row.room_id}: read {row.read} "
                     f"{row.semantic_type.replace('_', ' ')}, {row.usable} usable ({lost})")
    return notes


def merge_reading_into_plan(plan: ObjectPlan, reading: SceneReading) -> tuple[ObjectPlan, list[str]]:
    """Let the approved picture decide what is in the rooms it shows.

    The object plan is written by the planner from the WRITTEN brief, and the
    moodboard is painted separately, so the two drifted completely apart: on the
    sample project the 3D bathroom and the moodboard bathroom had no object in
    common, and the living room shared two out of twelve. The client approves a
    picture and is shown a different room.

    So for any room the reading has a trustworthy view of, the reading wins: its
    elements become that room's plan items, carrying `element_id` so the asset
    ladder can pick the mesh generated from that exact crop. Rooms the reading
    did not cover keep the planner's items untouched - a bathroom whose render
    was unreadable is better served by a sensible catalog bathroom than by
    nothing at all.

    This is free and runs regardless of approval. Approval gates SPENDING, which
    is `generate_elements`; it does not gate the layout, because placing a
    catalog chair where the picture shows a chair costs nothing and is right.
    """
    notes: list[str] = []
    by_room: dict[str, list[SceneElement]] = {}
    for el in reading.elements:
        if trustworthy(el):
            by_room.setdefault(el.room_id, []).append(el)
    if not by_room:
        return plan, ["scene reading has no trustworthy elements; plan left as the brief wrote it"]

    kept = [i for i in plan.items if i.room_id not in by_room]
    merged: list[ObjectPlanItem] = list(kept)
    for room_id, els in by_room.items():
        was = sum(1 for i in plan.items if i.room_id == room_id)
        seen: dict[str, int] = {}
        for el in els:
            n = seen.get(el.semantic_type, 0)
            seen[el.semantic_type] = n + 1
            merged.append(
                ObjectPlanItem(
                    object_key=f"{room_id}.{el.semantic_type}.{n}",
                    semantic_type=el.semantic_type,
                    room_id=room_id,
                    name=el.name,
                    family=vocab.family_for(el.semantic_type),
                    placement=el.placement,
                    crop_ref=el.crop_ref,
                    element_id=el.element_id,
                    priority=1,                   # it is in the picture the client agreed to
                    material_hint=el.material,
                    color_hint=el.color,
                    against=el.against,
                    faces=el.faces,
                    # P22: the render-frame anchor rides along for the solver.
                    anchor_m=el.position_m,
                    anchor_source=el.position_source,
                    wall=el.wall,
                    facing_dir=el.facing_dir,
                    # `_target()` already prefers this over the per-type table,
                    # so a measured size reaches catalog fit scoring and
                    # procedural stand-ins too - not only generated meshes.
                    approx_dimensions=el.dimensions_m,
                    from_photo=True,
                )
            )
        notes.append(f"{room_id}: {was} planned item(s) replaced by {len(els)} from the approved render")

    plan.items = merged
    plan.rooms = sorted({i.room_id for i in merged})
    plan.warnings = list(plan.warnings) + notes
    return plan, notes


# Bounds an estimate must clear to be used at all. Not style limits - limits on
# what could physically be a piece of furniture in a room. The scale factor at
# ingest is `max(expected) / max(mesh)`, so one absurd number does not make a
# piece slightly wrong, it makes the whole mesh absurd: a sofa estimated at
# 16 m arrives sixteen metres long and is then placed, validated and rendered
# at that size without anything downstream objecting.
# Permissive on the short side and strict on the long one, deliberately. A rug
# really is a centimetre thick and a mirror five, and 0.03 rejected the rug at
# 1.6 x 0.01 x 2.2 m for being correct. Only the LONGEST edge drives the scale
# factor at ingest, so an honest thin edge is harmless while an absurd long one
# is what makes a whole mesh absurd.
MIN_EDGE_M = 0.005
MAX_EDGE_M = 4.0
MAX_VOLUME_M3 = 12.0


def _plausible(dims, room, warn: list[str], label: str) -> bool:
    w, h, d = dims
    if any(v != v or v <= 0 for v in dims):
        warn.append(f"{label}: estimate {dims} is not a positive size; kept the generic one")
        return False
    if min(dims) < MIN_EDGE_M or max(dims) > MAX_EDGE_M:
        warn.append(f"{label}: estimate {tuple(round(v, 2) for v in dims)} m is outside "
                    f"{MIN_EDGE_M}-{MAX_EDGE_M} m; kept the generic one")
        return False
    if w * h * d > MAX_VOLUME_M3:
        warn.append(f"{label}: estimate {tuple(round(v, 2) for v in dims)} m is "
                    f"{w * h * d:.1f} m3; kept the generic one")
        return False
    # It has to fit the room it was seen in, with the room's own slack.
    if room is not None:
        span = max(room.width_m, room.length_m) + 0.5
        if max(w, d) > span or h > room.height_m + 0.3:
            warn.append(f"{label}: estimate {tuple(round(v, 2) for v in dims)} m does not fit "
                        f"a {room.width_m:.1f}x{room.length_m:.1f} m room; kept the generic one")
            return False
    return True


def estimate_dimensions(reading: SceneReading, rooms: dict, vertical, provider,
                        warnings: list[str]) -> int:
    """Ask how big each piece really is, and record it where ingest can use it.

    Optional and non-blocking. A provider without the capability, an unsure
    answer, or an implausible one all leave the element's size unset, and the
    per-type table decides as it does today.
    """
    estimate = getattr(provider, "estimate_element_dimensions", None)
    if not callable(estimate):
        return 0
    by_room: dict[str, list] = {}
    for el in reading.elements:
        if el.crop_ref and trustworthy(el):
            by_room.setdefault(el.room_id, []).append(el)

    applied = 0
    for room_id, els in by_room.items():
        room = rooms.get(room_id)
        raw = estimate(room, els, vertical) or {}
        by_id = {e.element_id: e for e in els}
        for item in (raw.get("items") or []):
            el = by_id.get(str(item.get("ref") or ""))
            if el is None:
                continue
            if not item.get("sure", False):
                warnings.append(f"{el.name}: the reader was unsure of its size; kept the generic one")
                continue
            try:
                dims = (float(item["width_m"]), float(item["height_m"]), float(item["depth_m"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not _plausible(dims, room, warnings, el.name or el.semantic_type):
                continue
            el.dimensions_m = (round(dims[0], 3), round(dims[1], 3), round(dims[2], 3))
            applied += 1
    return applied


def approved_for_generation(reading: SceneReading) -> tuple[list, list[str]]:
    """The only list Stage 3 may spend on, plus what it is refusing and why.

    A human has to have said yes to each crop. `approved is None` means nobody
    looked, which is NOT consent - the automatic check narrows how much there
    is to look at, it does not stand in for the looking. Getting this backwards
    costs 30 credits per wrong mesh and produces a room full of confident
    rubbish, which is harder to notice than an empty one.
    """
    ready, held = [], []
    for el in reading.elements:
        if not el.crop_ref:
            continue                                  # no crop, nothing to generate from
        if el.approved is True:
            ready.append(el)
        elif el.approved is False:
            held.append(f"{el.room_id}/{el.name}: rejected by review")
        else:
            held.append(f"{el.room_id}/{el.name}: not reviewed yet"
                        + (f" (check: {el.check})" if el.check != "ok" else ""))
    return ready, held


def check_element_crops(reading: SceneReading, room_types: dict, vertical, project_root: Path,
                        provider) -> dict:
    """Show each crop back to the model ALONE and ask what it is.

    A box can be structurally perfect and around the wrong thing - a floor
    plank returned as "table lamp", the whole kitchen returned as "kitchen
    counter". Nothing about the geometry is wrong, so no geometric guard can
    see it. The only thing that can is a second look at the crop by itself.

    The expected label is deliberately NOT sent: asked "is this a table lamp?"
    a vision model says yes. The answer comes back cold and is compared here.

    A check that fails is `unreadable`, never a pass - it routes the crop to a
    human instead of waving it through to a paid generation.
    """
    mark_duplicates(reading)
    tally: dict[str, int] = {}
    for el in reading.elements:
        if el.check == "duplicate":
            tally["duplicate"] = tally.get("duplicate", 0) + 1
            continue
        if not el.crop_ref:
            continue                                    # nothing to look at
        crop = project_root / el.crop_ref
        raw = provider.check_element_crop(crop, room_types.get(el.room_id, "room"), vertical) or {}
        sees = str(raw.get("sees") or "").strip()
        if not sees:
            el.check, el.check_note = "unreadable", "the second look returned nothing"
        elif not raw.get("certain", True):
            el.check, el.check_note = "unreadable", f"could not tell: saw {sees!r}"
        elif not raw.get("fills_frame", True):
            el.check, el.check_note = "crowded", f"no single piece fills this crop; saw {sees!r}"
        else:
            got = vocab.canonical_type(sees, str(raw.get("semantic_type") or ""))
            if got == el.semantic_type or (got == "other" and el.semantic_type == "other"):
                el.check, el.check_note = "ok", sees
            else:
                el.check = "mismatch"
                el.check_note = f"looks like {sees!r} ({got}), labelled {el.semantic_type}"
        tally[el.check] = tally.get(el.check, 0) + 1

    # LAST, so the picture gets the first word. `flag_implausible` reasons from
    # the label alone; the crop check above actually looked at the pixels, and
    # where the two disagree the one that looked wins. It only ever touches
    # elements this pass left as `ok` or never examined.
    if flag_implausible(reading, room_types):
        # Recount rather than adjust: an element moved from `ok` to
        # `implausible` has to leave one bucket and join another, and doing that
        # by arithmetic on two keys double-counts.
        tally = {}
        for el in reading.elements:
            if el.check == "duplicate" or el.crop_ref or el.check == "implausible":
                tally[el.check] = tally.get(el.check, 0) + 1
    return tally


def _upscaled(crop):
    """Enlarge a crop towards the size image-to-3D was validated at.

    Never shrinks - a crop already that big is left alone. The long side is
    capped so a rug measured 522 x 90 does not become a 3,000 px strip whose
    base64 body is most of the request.
    """
    w, h = crop.size
    short, long_ = min(w, h), max(w, h)
    factor = min(UPSCALE_SHORT_PX / short, UPSCALE_MAX_LONG_PX / long_)
    if factor < UPSCALE_MIN_GAIN:
        # Resampling is not quite free - it softens - so a crop already near the
        # validated size is left as it is rather than nudged for a few per cent.
        return crop
    return crop.resize((max(1, round(w * factor)), max(1, round(h * factor))), Image.LANCZOS)


def write_element_crops(reading: SceneReading, images: dict, project_root: Path,
                        *, force: bool = False) -> list[str]:
    """Cut one PNG per element out of its room render; sets `crop_ref`.

    Sweeps files this run does not claim, for the same reason the photo crops
    do: names carry an index, so a re-read that finds different elements would
    otherwise orphan the old ones forever - the sample project once held 11
    crops for 6 read items.
    """
    warnings: list[str] = []
    if Image is None:
        return ["Pillow missing; no element crops written"]
    out_dir = project_root / CROP_DIR
    written: set[Path] = set()
    opened: dict[str, Any] = {}

    for index, element in enumerate(reading.elements):
        source = images.get(element.room_id)
        if source is None or not Path(source).is_file():
            element.crop_ref = ""
            warnings.append(f"{element.room_id}: no rendered image to cut {element.name!r} from")
            continue
        rel = f"{CROP_DIR}/{element.room_id}/{index:02d}_{vocab.slug(element.name)[:40]}.png"
        target = project_root / rel
        if target.exists() and not force:
            element.crop_ref = rel
            written.add(target)
            continue
        try:
            im = opened.get(element.room_id)
            if im is None:
                im = Image.open(source).convert("RGB")
                opened[element.room_id] = im
            w, h = im.size
            x0, y0, x1, y1 = element.bbox            # type: ignore[misc]
            px, py = (x1 - x0) * PAD, (y1 - y0) * PAD
            box = (int(max(0.0, x0 - px) * w), int(max(0.0, y0 - py) * h),
                   int(min(1.0, x1 + px) * w), int(min(1.0, y1 + py) * h))
            bw, bh = box[2] - box[0], box[3] - box[1]
            if min(bw, bh) < MIN_LEGIBLE_PX:
                warnings.append(
                    f"{element.name}: {bw}x{bh} px has no shape to read; skipped")
                element.crop_ref = ""
                continue
            crop = _upscaled(im.crop(box))
            element.crop_px = (bw, bh)      # the NATIVE size, before enlarging
            target.parent.mkdir(parents=True, exist_ok=True)
            crop.save(target, format="PNG", optimize=True)
            element.crop_ref = rel
            written.add(target)
        except Exception as exc:                  # one bad box never sinks the stage
            log.exception("%s: element crop failed", element.element_id)
            warnings.append(f"{element.name}: crop failed: {exc}")
            element.crop_ref = ""

    for im in opened.values():
        im.close()
    if out_dir.is_dir():
        for stale in out_dir.rglob("*.png"):
            if stale not in written:
                try:
                    stale.unlink()
                except OSError as exc:
                    warnings.append(f"could not remove stale crop {stale.name}: {exc}")
    return warnings


__all__ = ["coerce_room_reading", "write_element_crops", "check_element_crops", "approved_for_generation", "shape_key", "distinct_shapes",
           "merge_reading_into_plan", "trustworthy", "estimate_dimensions",
           "mark_duplicates", "flag_implausible", "CROP_DIR", "NOT_ELEMENTS"]

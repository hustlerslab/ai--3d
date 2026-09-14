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
from .schema import ObjectPlan, ObjectPlanItem, RoomSurfaces, SceneElement, SceneReading

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
        elements.append(
            SceneElement(
                element_id="el_" + hashlib.sha1(f"{seed}#{n}".encode("utf-8")).hexdigest()[:10],
                room_id=room.room_id,
                name=name or sem.replace("_", " "),
                semantic_type=sem,
                bbox=box,
                material=str(item.get("material") or "").strip(),
                color=_hex(item.get("color")),
                placement=vocab.placement_for(sem, str(item.get("placement") or "")),
                against=str(item.get("against") or "").strip(),
                faces=str(item.get("faces") or "").strip(),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.6) or 0.6))),
            )
        )

    raw_surfaces = raw.get("surfaces") or {}
    surfaces = None
    if raw_surfaces:
        surfaces = RoomSurfaces(
            room_id=room.room_id,
            wall_color=_hex(raw_surfaces.get("wall_color")),
            wall_material=_phrase(raw_surfaces.get("wall_material"), warnings,
                                  f"{room.room_id}.wall_material"),
            floor_color=_hex(raw_surfaces.get("floor_color")),
            floor_material=_phrase(raw_surfaces.get("floor_material"), warnings,
                                   f"{room.room_id}.floor_material"),
            notes=_phrase(raw_surfaces.get("notes"), warnings, f"{room.room_id}.notes", limit=400),
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


def distinct_shapes(elements: list[SceneElement]) -> dict[str, list[SceneElement]]:
    """Group elements by shape key, best crop first within each group.

    The biggest native crop leads: it is the one that gets generated, and more
    pixels of the same piece is the only thing here that is unambiguously
    better. Whether it is worth generating at all is not decided by size - that
    was measured and retired (ADR-003 s2) - only which of several views wins.
    """
    groups: dict[str, list[SceneElement]] = {}
    for el in elements:
        groups.setdefault(shape_key(el), []).append(el)
    for els in groups.values():
        els.sort(key=lambda e: -(e.crop_px[0] * e.crop_px[1]))
    return groups


def trustworthy(element: SceneElement) -> bool:
    """Does this element describe something really in the approved picture?

    `ok` means the isolated second look agreed with the label. A human ticking
    `approved` overrides that either way: they can rescue a crop the check
    misjudged, and a rejection stands even if the check liked it.
    """
    if element.approved is not None:
        return element.approved
    return element.check == "ok"


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
           "mark_duplicates", "CROP_DIR", "NOT_ELEMENTS"]

"""The provenance chain, queryable — P1-IDENTITY-005.

P1-IDENTITY-001…004 put identity *into* every hop: `SceneObject` carries
`element_id` and `instance_id`, the Blender manifest carries both onto the
rendered object, and the asset record names the element it was generated from.
Present is not the same as answerable. Until this module, answering *"which
photograph the client uploaded caused this rendered chair to exist?"* meant
opening four JSON documents by hand and scanning them.

**The chain, exactly as `task.md` states it:**

    render -> blender_object -> scene_object -> instance -> element
          -> definition.source_element_ids -> instance.source_element_id
          -> SceneElement.crop_ref -> DesignIntent.source_intent_ids
          -> input_id -> ref_NN.jpg

**Files remain the record; the database is an index.** `index_project()` can
rebuild every row from disk, so a stale index is an inconvenience rather than
data loss. What the index buys is the direction a file cannot go: an object id
straight to its instance without parsing three documents, and the cross-project
question — *what else was built from the mesh we already paid for?* — which one
project's files cannot answer at all.

**Two hops do not resolve on the projects currently on disk, and the resolver
does not pretend otherwise:**

* Every stored `scene_spec.json` predates P1-IDENTITY-002, so its objects carry
  `element_id: null`. The resolver falls back to the join identity was meant to
  remove — `plan_key` -> `ObjectPlanItem.object_key` -> `.element_id` — and says
  in the hop which route it took. Without the fallback the endpoint would answer
  "unknown" for every object built before today, which is true of the file and
  false of the object.
* `ObjectPlanItem.source_intent_ids` is empty on both real projects. An empty
  intent hop is reported as empty, with a note. It is not backfilled by guessing
  which reference "probably" justified a piece.

A hop that cannot resolve is `resolved: false` with a reason. Nothing here
invents an id.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .db.sqlite import get_db
from .projects.layout import file_url, project_dir

READING = "planning/scene_reading.json"
SCENE_SPEC = "planning/scene_spec.json"
OBJECT_PLAN = "planning/object_plan.json"
DESIGN_INTENT = "planning/design_intent.json"
BUILD_MANIFEST = "blender/build_manifest.json"
MOODBOARD = "analysis/moodboard_spec.json"

#: Files whose content the index is derived from. Newer than `indexed_at` means
#: the index is stale and `index_project()` runs again.
INDEX_SOURCES = (READING, SCENE_SPEC)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(root: Path, relative: str) -> Optional[dict]:
    path = root / relative
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _element_via_plan_key(plan_key: Optional[str], plan_items: dict[str, dict]) -> str:
    """The join P1-IDENTITY removed the *need* for, kept for files that predate it.

    `plan_key` is `"<object_key>"` for the first occurrence and `"<object_key>#N"`
    for the rest, so the suffix is stripped before lookup.
    """
    if not plan_key:
        return ""
    key = plan_key.split("#", 1)[0]
    item = plan_items.get(key) or {}
    return item.get("element_id", "") or ""


# ── the index ─────────────────────────────────────────────────────────────


def index_project(project_id: str) -> dict[str, int]:
    """Rebuild this project's identity index from its files. Idempotent.

    Delete-then-insert rather than upsert: an element removed from the reading
    has to disappear from the index too, and an upsert leaves it behind forever.
    One transaction, so a half-written index is never visible.
    """
    root = project_dir(project_id)
    reading = _load(root, READING) or {}
    spec = _load(root, SCENE_SPEC) or {}
    plan = _load(root, OBJECT_PLAN) or {}

    definitions = reading.get("definitions") or []
    instances = reading.get("instances") or []
    elements = {e.get("element_id", ""): e for e in (reading.get("elements") or [])}

    # source_element_id -> the scene object placed for it. Built from the spec's
    # own identity when it has one, and from the plan_key join when it does not
    # (every scene_spec.json written before P1-IDENTITY-002).
    placed: dict[str, str] = {}
    plan_items = {i.get("object_key", ""): i for i in (plan.get("items") or [])}
    for obj in spec.get("objects") or []:
        element_id = obj.get("element_id") or _element_via_plan_key(obj.get("plan_key"), plan_items)
        if element_id and element_id not in placed:
            placed[element_id] = obj.get("object_id", "")

    stamp = _now()
    db = get_db()
    with db.tx() as c:
        c.execute("DELETE FROM elements WHERE project_id = ?", (project_id,))
        c.execute("DELETE FROM element_instances WHERE project_id = ?", (project_id,))
        for d in definitions:
            c.execute(
                "INSERT INTO elements(project_id, element_id, room_id, semantic_type,"
                " canonical_name, identity_method, instance_count, canonical_asset_id,"
                " source_element_ids, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (project_id, d.get("element_id", ""), d.get("room_id", ""),
                 d.get("semantic_type", ""), d.get("canonical_name", ""),
                 d.get("identity_method", ""), int(d.get("instance_count") or 0),
                 d.get("canonical_asset_id", "") or "",
                 json.dumps(d.get("source_element_ids") or []), stamp),
            )
        for i in instances:
            source = i.get("source_element_id", "") or ""
            # The asset is a property of the piece as READ, so it comes off the
            # reading row rather than off the definition: a definition's
            # `canonical_asset_id` is empty until the asset ladder has run.
            asset_id = (elements.get(source, {}) or {}).get("asset_id", "") or ""
            c.execute(
                "INSERT INTO element_instances(project_id, instance_id, element_id,"
                " room_id, source_element_id, crop_ref, scene_object_id, asset_id,"
                " indexed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (project_id, i.get("instance_id", ""), i.get("element_id", ""),
                 i.get("room_id", ""), source, i.get("crop_ref", "") or "",
                 placed.get(source, ""), asset_id, stamp),
            )
    return {
        "elements": len(definitions),
        "instances": len(instances),
        "placed": sum(1 for i in instances if placed.get(i.get("source_element_id", ""))),
    }


def clear_index(project_id: str) -> None:
    """Drop a project's index rows. Called when the project itself is deleted."""
    db = get_db()
    with db.tx() as c:
        c.execute("DELETE FROM elements WHERE project_id = ?", (project_id,))
        c.execute("DELETE FROM element_instances WHERE project_id = ?", (project_id,))


def index_is_stale(project_id: str) -> bool:
    """True when a source file has changed since the index was written.

    Cheap enough to check on every read (two `stat` calls and one row), which is
    what lets the endpoint work on projects planned before this module existed
    without a backfill inside a schema migration — the kind of migration that
    parses every project's JSON and turns a deploy into an outage.
    """
    root = project_dir(project_id)
    newest = 0.0
    for rel in INDEX_SOURCES:
        path = root / rel
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    if newest == 0.0:
        return False                    # nothing to index
    row = get_db().one(
        "SELECT MAX(indexed_at) AS at FROM ("
        "  SELECT indexed_at FROM elements WHERE project_id = ?"
        "  UNION ALL SELECT indexed_at FROM element_instances WHERE project_id = ?)",
        (project_id, project_id))
    at = row["at"] if row else None
    if not at:
        return True
    try:
        indexed = datetime.fromisoformat(at).timestamp()
    except ValueError:
        return True
    return newest > indexed


def ensure_indexed(project_id: str) -> None:
    if index_is_stale(project_id):
        index_project(project_id)


# ── the chain ─────────────────────────────────────────────────────────────


class Hop(BaseModel):
    """One link.

    `resolved` says whether the hop was made. `gap` says whether failing to make
    it was a DEFECT. The two are not the same and conflating them is what makes
    a provenance report useless: a moodboard-read sideboard has no
    `DesignIntent` because no reference photograph showed it, and calling that a
    broken chain would bury the one break that does matter — an instance whose
    definition is missing — under a dozen that do not.
    """

    hop: str
    resolved: bool = False
    #: An unresolved hop whose inputs WERE present. Always False when resolved.
    gap: bool = False
    id: str = ""
    #: Why it did not resolve, or which route it took when there was more than
    #: one. Never empty on an unresolved hop.
    note: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class ProvenanceChain(BaseModel):
    project_id: str
    scene_object_id: str
    #: "moodboard_element" when the object is an occurrence of something the
    #: client approved; "planner_catalog" when the planner added it and there is
    #: genuinely nothing upstream; "unknown" when the object was not found.
    origin: str = "unknown"
    #: True when the chain reached a client-visible cause — an uploaded
    #: photograph or the approved moodboard render — with no hop marked `gap`.
    #: A catalog piece the planner added is complete at `scene_object`: there is
    #: nothing upstream of it, so there is no chain to break.
    complete: bool = False
    #: The hops that broke when they should not have, named. `complete` is never
    #: False without something here to explain it.
    gaps: list[str] = []
    #: The last hop that resolved.
    terminus: str = ""
    hops: list[Hop] = []
    #: The answer to the question the chain exists for: the uploaded photographs
    #: behind this object. Empty when nothing links it to one.
    source_images: list[dict[str, Any]] = []


def resolve(project_id: str, scene_object_id: str) -> ProvenanceChain:
    """Walk the chain for one scene object. Never raises on missing data."""
    root = project_dir(project_id)
    chain = ProvenanceChain(project_id=project_id, scene_object_id=scene_object_id)
    spec = _load(root, SCENE_SPEC)
    plan = _load(root, OBJECT_PLAN) or {}
    reading = _load(root, READING) or {}
    plan_items = {i.get("object_key", ""): i for i in (plan.get("items") or [])}

    # ── render -> blender_object ─────────────────────────────────────────
    # The Blender object is an Empty named after `object_id` (import_assets.py),
    # so this hop is name identity, and the manifest entry is the evidence that
    # the object reached the build at all.
    manifest = _load(root, BUILD_MANIFEST) or {}
    entry = next((o for o in (manifest.get("objects") or [])
                  if o.get("id") == scene_object_id), None)
    chain.hops.append(Hop(
        hop="blender_object",
        resolved=entry is not None,
        id=scene_object_id if entry else "",
        gap=entry is None and bool(manifest.get("objects")),
        note="" if entry else (
            "in blender/build_manifest.json the scene lists objects but not this one"
            if manifest.get("objects") else
            "the scene has not been built — blender/build_manifest.json is absent"),
        detail={"manifest_version": manifest.get("manifest_version", ""),
                "name": (entry or {}).get("name", "")} if entry else {},
    ))

    # ── scene_object ─────────────────────────────────────────────────────
    obj = next((o for o in ((spec or {}).get("objects") or [])
                if o.get("object_id") == scene_object_id), None)
    if obj is None:
        chain.hops.append(Hop(hop="scene_object",
                              note="no object with that id in planning/scene_spec.json"))
        return chain
    element_id = obj.get("element_id") or ""
    via = "scene_object.element_id"
    if not element_id:
        element_id = _element_via_plan_key(obj.get("plan_key"), plan_items)
        via = "plan_key join (scene_spec predates P1-IDENTITY-002)" if element_id else ""
    chain.hops.append(Hop(
        hop="scene_object", resolved=True, id=scene_object_id,
        note=f"identity read from {via}" if via else
             "carries no element_id and its plan item names none",
        detail={"semantic_type": obj.get("semantic_type", ""),
                "room_id": obj.get("room_id", ""),
                "name": obj.get("name", ""),
                "asset_id": obj.get("asset_id"),
                "plan_key": obj.get("plan_key"),
                "instance_id": obj.get("instance_id")},
    ))
    chain.terminus = "scene_object"

    if not element_id:
        # A catalog piece the planner added. Not a broken chain — there is no
        # element upstream of it, and inventing one would put a fiction into the
        # provenance record (the same reason the compiler writes None here).
        chain.origin = "planner_catalog"
        chain.complete = True
        return chain
    chain.origin = "moodboard_element"

    # ── instance ─────────────────────────────────────────────────────────
    ensure_indexed(project_id)
    db = get_db()
    inst = db.one(
        "SELECT * FROM element_instances WHERE project_id = ? AND source_element_id = ?",
        (project_id, element_id))
    chain.hops.append(Hop(
        hop="instance", resolved=inst is not None,
        id=inst["instance_id"] if inst else "",
        gap=inst is None and bool(reading.get("definitions")),
        note="" if inst else (
            "the reading resolved definitions but none covers this element"
            if reading.get("definitions") else
            "this reading predates resolve_elements() and holds no instances at all"),
        detail={"element_id": inst["element_id"], "room_id": inst["room_id"],
                "crop_ref": inst["crop_ref"], "asset_id": inst["asset_id"]} if inst else {},
    ))
    if inst is not None:
        chain.terminus = "instance"

        # ── element (the canonical definition) ────────────────────────────
        defn = db.one("SELECT * FROM elements WHERE project_id = ? AND element_id = ?",
                      (project_id, inst["element_id"]))
        chain.hops.append(Hop(
            hop="element", resolved=defn is not None, gap=defn is None,
            id=defn["element_id"] if defn else "",
            note="" if defn else f"instance names {inst['element_id']} but no definition "
                                 f"carries that id",
            detail={"canonical_name": defn["canonical_name"],
                    "semantic_type": defn["semantic_type"],
                    "identity_method": defn["identity_method"],
                    "instance_count": defn["instance_count"],
                    "source_element_ids": json.loads(defn["source_element_ids"]),
                    "canonical_asset_id": defn["canonical_asset_id"]} if defn else {},
        ))
        if defn is not None:
            chain.terminus = "element"

    # ── SceneElement.crop_ref ────────────────────────────────────────────
    element = next((e for e in (reading.get("elements") or [])
                    if e.get("element_id") == element_id), None)
    crop = (element or {}).get("crop_ref", "") or ""
    chain.hops.append(Hop(
        hop="scene_element", resolved=element is not None,
        gap=element is None, id=element_id,
        note="" if element is not None else
             "no reading row with this element_id — the moodboard was re-read after "
             "this scene was compiled (P1-ASSET-001)",
        detail={"name": element.get("name", ""), "crop_ref": crop,
                "crop_url": file_url(project_id, crop) if crop else "",
                "asset_id": element.get("asset_id", ""),
                "approved": element.get("approved"),
                "check": element.get("check", "")} if element else {},
    ))
    if element is not None:
        chain.terminus = "scene_element"

    # ── moodboard render ─────────────────────────────────────────────────
    # The crop was cut from a room render the client approved. Without this hop
    # an element-origin object stops at a PNG with nothing said about where the
    # PNG came from, and "what caused this to exist" is exactly what the chain
    # is for. The render also records whether a photograph of the client's own
    # pieces drove it, which is the only honest route to a reference image for a
    # piece that was read out of a moodboard rather than matched to a photo.
    board = _load(root, MOODBOARD) or {}
    room_id = (element or {}).get("room_id", "") or obj.get("room_id", "") or ""
    scene_row = next((r for r in (board.get("room_scenes") or [])
                      if r.get("room_id") == room_id), None)
    chain.hops.append(Hop(
        hop="moodboard", resolved=scene_row is not None,
        gap=scene_row is None and bool(board.get("room_scenes")), id=room_id,
        note="" if scene_row is not None else
             "analysis/moodboard_spec.json names no render for this room",
        detail={"url": scene_row.get("url", ""),
                "reference_resolved": bool(scene_row.get("reference_resolved")),
                "reference_note": scene_row.get("reference_note", "")} if scene_row else {},
    ))
    if scene_row is not None:
        chain.terminus = "moodboard"

    # ── DesignIntent -> input_id -> ref_NN.jpg ───────────────────────────
    item_key = (obj.get("plan_key") or "").split("#", 1)[0]
    intent_ids = list((plan_items.get(item_key) or {}).get("source_intent_ids") or [])
    intents = {i.get("intent_id", ""): i
               for i in ((_load(root, DESIGN_INTENT) or {}).get("intents") or [])}
    matched = [intents[i] for i in intent_ids if i in intents]
    chain.hops.append(Hop(
        hop="design_intent", resolved=bool(matched), gap=bool(intent_ids) and not matched,
        id=",".join(intent_ids),
        note="" if matched else (
            f"plan item {item_key or '(none)'} lists no source_intent_ids — this piece "
            f"came from the moodboard reading, not from a classified reference photo"
            if not intent_ids else
            "plan item names intents that planning/design_intent.json does not hold"),
        detail={"intents": [{"intent_id": i.get("intent_id", ""),
                             "reference_class": i.get("reference_class", ""),
                             "object_category": i.get("object_category", "")}
                            for i in matched]},
    ))

    # The uploaded photographs. Every intent names the input it was read from;
    # the input row names the file on disk.
    seen: set[str] = set()
    for intent in matched:
        prov = intent.get("provenance") or {}
        input_id = prov.get("input_id", "") or ""
        if not input_id or input_id in seen:
            continue
        seen.add(input_id)
        row = db.one("SELECT * FROM inputs WHERE input_id = ? AND project_id = ?",
                     (input_id, project_id))
        rel = (row["path"] if row else prov.get("image_ref", "")) or ""
        chain.source_images.append({
            "input_id": input_id,
            "filename": (row["filename"] if row else prov.get("filename", "")) or "",
            "path": rel,
            "url": file_url(project_id, rel) if rel else "",
            "in_inputs_table": row is not None,
            # EXACT: a classified intent says this photograph shows this piece.
            "via": "design_intent",
        })

    # The weaker route, labelled as weaker. A piece read out of a moodboard was
    # caused by the render, and the render was painted with these photographs in
    # view - but no one of them is "the photo of this chair". Collapsing the two
    # into one list would turn a contributing reference into a claim of identity,
    # which is the kind of confident wrong answer a provenance chain exists to
    # prevent. Only offered when nothing exact was found.
    if not chain.source_images and scene_row is not None and scene_row.get("reference_resolved"):
        for input_row in db.query(
                "SELECT * FROM inputs WHERE project_id = ? AND kind = 'reference'"
                " ORDER BY created_at ASC", (project_id,)):
            chain.source_images.append({
                "input_id": input_row["input_id"],
                "filename": input_row["filename"],
                "path": input_row["path"],
                "url": file_url(project_id, input_row["path"]),
                "in_inputs_table": True,
                "via": "moodboard_reference",
                "note": scene_row.get("reference_note", ""),
            })

    if chain.source_images:
        chain.terminus = "source_image"

    chain.gaps = [h.hop for h in chain.hops if h.gap]
    # Reaching a photograph is better than reaching the render, but the render is
    # a real answer: the client approved that picture, and it is what the crop
    # was cut from. Stopping at the crop is not.
    chain.complete = not chain.gaps and chain.terminus in ("source_image", "moodboard")
    return chain


def resolve_all(project_id: str) -> list[ProvenanceChain]:
    """Every object in the committed scene, in scene order. The shape the
    acceptance criterion is stated in: *for every object, the chain resolves.*"""
    spec = _load(project_dir(project_id), SCENE_SPEC) or {}
    return [resolve(project_id, o.get("object_id", ""))
            for o in (spec.get("objects") or [])]


def coverage(project_id: str) -> dict[str, Any]:
    """How much of the scene traces, and where it stops. Measured, not claimed."""
    chains = resolve_all(project_id)
    stops: dict[str, int] = {}
    origins: dict[str, int] = {}
    for c in chains:
        stops[c.terminus or "unresolved"] = stops.get(c.terminus or "unresolved", 0) + 1
        origins[c.origin] = origins.get(c.origin, 0) + 1
    def reached(c: ProvenanceChain, hop: str) -> bool:
        return any(h.hop == hop and h.resolved for h in c.hops)

    gaps: dict[str, int] = {}
    for c in chains:
        for g in c.gaps:
            gaps[g] = gaps.get(g, 0) + 1
    return {
        "objects": len(chains),
        "origins": origins,
        "terminus": stops,
        "traced_to_element": sum(1 for c in chains if reached(c, "element")),
        "traced_to_scene_element": sum(1 for c in chains if reached(c, "scene_element")),
        "reached_moodboard": sum(1 for c in chains if reached(c, "moodboard")),
        # Split, because "a photo of this exact piece" and "a photo that was in
        # view while the render was painted" are different claims.
        "reached_source_image_exact": sum(
            1 for c in chains if any(i.get("via") == "design_intent" for i in c.source_images)),
        "reached_source_image_via_moodboard": sum(
            1 for c in chains if c.source_images
            and all(i.get("via") == "moodboard_reference" for i in c.source_images)),
        "complete": sum(1 for c in chains if c.complete),
        "gaps": gaps,
    }

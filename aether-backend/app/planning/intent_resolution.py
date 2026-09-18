"""P11 asset resolution from typed design intent.

THE LADDER, in order, with an explicit bottom rung:

    1 EXACT_ASSET       an asset generated earlier from this very reference
    2 COMPATIBLE_ASSET  the best registry asset for the category, carrying the
                        intent's own colour/material rather than the palette's
    3 GENERATE          a STRUCTURED generation request built from the intent
    4 UNRESOLVED        nothing fits and nothing can be generated - said out
                        loud, with a reason, and surfaced for a human

WHY THE BOTTOM RUNG IS NEW. `AssetDecision.strategy` has four values and none
of them means "no". When the ladder in `asset_decision.py` runs out it returns
`strategy="procedural"` with `asset_id=None` - a coloured parametric box that
looks like a successful placement to every consumer downstream. P11 keeps that
behaviour for the ordinary planner path and adds a rung above it for the
intent path, so a reference the system cannot honour becomes a visible
`needs_input`, never a silent box.

NOT A SECOND SELECTOR. Rung 2 calls the existing `decide_asset` - same
candidates, same dimension veto, same style weighting. What this module adds
is (a) an `ObjectPlanItem` whose `color_hint`/`material_hint`/`style_notes`
come from the typed intent instead of a vision model's reading of an SD
render, and (b) a measurement of how much of the intent the chosen asset
actually satisfies.

NO GEOMETRY. Nothing here produces a position, rotation or scale. Resolution
answers "which asset", never "where" - the solver keeps that.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..catalog.catalog import all_items
from ..intelligence.design_intent import MergedIntent, VisualAttributes
from ..intelligence.schema import AssetDecision, ObjectPlanItem, StyleSpec
from .asset_decision import decide_asset


class ResolutionRung(str, Enum):
    EXACT_ASSET = "exact_asset"
    COMPATIBLE_ASSET = "compatible_asset"
    GENERATE = "generate"
    UNRESOLVED = "unresolved"


class GenerationRequest(BaseModel):
    """Structured evidence for a generator - deliberately not a free-text
    wish. The prompt is DERIVED from the attributes so it can never drift from
    them, and `reference_image` carries the client's own photo when there is
    one. A generator that accepts richer conditioning reads the fields; the
    current Meshy image-to-3D path uses `reference_image`, and the text path
    uses `prompt`, which until P11 contained no colour or material at all.
    """

    object_category: str
    attributes: VisualAttributes = Field(default_factory=VisualAttributes)
    reference_image: str = ""
    prompt: str = ""
    source_intent_ids: list[str] = []


class IntentResolution(BaseModel):
    object_category: str
    room_hint: str = ""
    rung: ResolutionRung
    asset_id: str = ""
    asset_name: str = ""
    strategy: str = ""
    #: Per stated attribute: did the resolved asset satisfy it? Only attributes
    #: the intent actually stated appear, so silence is never scored as a miss.
    attribute_match: dict[str, bool] = {}
    generation: Optional[GenerationRequest] = None
    needs_input: bool = False
    reason: str = ""
    source_intent_ids: list[str] = []

    @property
    def attribute_fidelity(self) -> Optional[float]:
        if not self.attribute_match:
            return None
        return round(sum(1 for v in self.attribute_match.values() if v) / len(self.attribute_match), 4)


def exact_asset_id(merged: MergedIntent) -> str:
    """Deterministic id for an asset generated from this exact intent, so a
    re-run finds the mesh it already paid for instead of buying it twice."""
    raw = "|".join(sorted(merged.sources)).encode("utf-8")
    return f"di_{merged.object_category}_{hashlib.sha1(raw).hexdigest()[:12]}".lower()


def generation_prompt(merged: MergedIntent) -> str:
    """Category first, then only the attributes the references actually
    stated. An intent that states nothing yields the bare category rather than
    inventing adjectives."""
    attrs = merged.attributes
    parts = [merged.object_category.replace("_", " ")]
    if attrs.color_words:
        parts.append(", ".join(attrs.color_words))
    for value in (attrs.upholstery, attrs.material, attrs.pattern, attrs.frame_finish):
        if value:
            parts.append(value)
    if attrs.style_descriptors:
        parts.append(", ".join(attrs.style_descriptors))
    if attrs.visual_descriptors:
        parts.append(", ".join(attrs.visual_descriptors))
    return ", ".join(p for p in parts if p)


def intent_to_plan_item(merged: MergedIntent, object_key: str, room_id: str) -> ObjectPlanItem:
    """The bridge into the existing planner vocabulary. This is where the
    typed attributes finally populate the three hint fields that previously
    arrived from a vision model reading an SD render."""
    attrs = merged.attributes
    color_hint = attrs.color_hex if attrs.color_hex.startswith("#") else ""
    descriptors = [*attrs.style_descriptors, *attrs.visual_descriptors]
    return ObjectPlanItem(
        object_key=object_key,
        semantic_type=merged.object_category,
        room_id=room_id,
        name=" ".join([*attrs.color_words, merged.object_category.replace("_", " ")]).strip(),
        color_hint=color_hint,
        material_hint=attrs.upholstery or attrs.material,
        style_notes=", ".join(descriptors),
        # P13: the three hints above are what the asset ladder can consume; the
        # block below is what the client actually said, carried whole so the
        # scene and the executor can still see "quilted" and "dark walnut".
        visual=attrs.model_copy(deep=True),
        source_intent_ids=list(merged.sources),
    )


def _asset_attribute_match(decision: AssetDecision, merged: MergedIntent,
                           asset_tags: tuple[list[str], list[str], str]) -> dict[str, bool]:
    """Compare what the references asked for against what the asset offers.

    Colour is matched on the resolved hex when the intent gave one, otherwise
    on the colour WORDS appearing in the asset's own name/tags - because the
    words are what a client said and a catalogue rarely stores a hex a human
    would recognise.
    """
    style_tags, material_tags, asset_color = asset_tags
    haystack = " ".join([decision.asset_name or "", *style_tags, *material_tags]).lower()
    attrs = merged.attributes
    match: dict[str, bool] = {}
    stated = attrs.stated()

    if "color_hex" in stated:
        match["color_hex"] = bool(asset_color) and asset_color.lower() == attrs.color_hex.lower()
    if "color_words" in stated:
        match["color_words"] = any(w.lower() in haystack for w in attrs.color_words)
    for name in ("material", "upholstery", "pattern", "frame_finish"):
        if name in stated:
            match[name] = str(stated[name]).lower() in haystack
    for name in ("style_descriptors", "visual_descriptors"):
        if name in stated:
            values = stated[name]
            match[name] = any(str(w).lower() in haystack for w in values)  # type: ignore[union-attr]
    return match


def resolve_intent(merged: MergedIntent, style: StyleSpec, *, room_id: str = "",
                   object_key: str = "", generation_available: bool = True,
                   reference_image: str = "") -> IntentResolution:
    """Walk the ladder for one merged intent. Never places anything."""
    key = object_key or f"intent_{merged.object_category}"
    base = {"object_category": merged.object_category, "room_hint": merged.room_hint,
            "source_intent_ids": list(merged.sources)}

    # An unresolved-by-construction case: the references contradict each other,
    # so choosing ANY asset would be inventing a decision the evidence does not
    # support. P10's rule - keep the uncertainty, do not collapse it.
    if merged.uncertain:
        return IntentResolution(
            **base, rung=ResolutionRung.UNRESOLVED, needs_input=True,
            reason="references disagree or were not classified with confidence; a human must choose",
            generation=None)

    item = intent_to_plan_item(merged, key, room_id)

    # ── rung 1: an asset already generated from this exact reference ───────
    wanted = exact_asset_id(merged)
    for record in all_items():
        if record.asset_id == wanted and record.model_url:
            return IntentResolution(
                **base, rung=ResolutionRung.EXACT_ASSET, asset_id=record.asset_id,
                asset_name=record.name, strategy="generated",
                attribute_match={k: True for k in merged.attributes.stated()},
                reason="asset previously generated from this reference")

    # ── rung 2: the best compatible registry asset, carrying the intent ────
    decision = decide_asset(item, style)
    if decision.has_model and decision.asset_id:
        tags: tuple[list[str], list[str], str] = ([], [], "")
        for record in all_items():
            if record.asset_id == decision.asset_id:
                tags = (record.style_tags, record.material_tags, record.color or "")
                break
        match = _asset_attribute_match(decision, merged, tags)
        unmet = sorted(k for k, ok in match.items() if not ok)
        # This rung is "closest compatible asset AND its visual attributes".
        # An asset of the right category and size that satisfies NOTHING the
        # client asked for visually is a shape, not their piece - so it loses
        # to a generator that can honour the attributes. Partial matches are
        # kept: half the intent beats a fresh guess.
        if match and len(unmet) == len(match) and generation_available:
            pass
        else:
            return IntentResolution(
                **base, rung=ResolutionRung.COMPATIBLE_ASSET, asset_id=decision.asset_id,
                asset_name=decision.asset_name, strategy=decision.strategy,
                attribute_match=match, needs_input=bool(match) and len(unmet) == len(match),
                reason=(f"closest compatible asset, but it satisfies none of the stated "
                        f"attributes ({', '.join(unmet)}) and no generator is available"
                        if match and len(unmet) == len(match)
                        else decision.reason or "closest compatible registry asset"))

    # ── rung 3: generate, from structured evidence ─────────────────────────
    if generation_available:
        return IntentResolution(
            **base, rung=ResolutionRung.GENERATE, strategy="generated",
            attribute_match={k: True for k in merged.attributes.stated()},
            generation=GenerationRequest(
                object_category=merged.object_category, attributes=merged.attributes,
                reference_image=reference_image, prompt=generation_prompt(merged),
                source_intent_ids=list(merged.sources)),
            reason="no compatible registry asset; generating from the reference's own attributes")

    # ── rung 4: say no ─────────────────────────────────────────────────────
    return IntentResolution(
        **base, rung=ResolutionRung.UNRESOLVED, needs_input=True,
        reason="no compatible registry asset and generation is unavailable")


def resolve_all(merged: list[MergedIntent], style: StyleSpec, *, room_id: str = "",
                generation_available: bool = True) -> list[IntentResolution]:
    """Deterministic: input order is already fixed by `merge_intents`."""
    return [resolve_intent(m, style, room_id=room_id, object_key=f"intent_{n}_{m.object_category}",
                           generation_available=generation_available)
            for n, m in enumerate(merged)]


def apply_intents_to_plan(items: list[ObjectPlanItem], merged: list[MergedIntent],
                          room_for: dict[str, str], default_room_id: str = "") -> tuple[list[ObjectPlanItem], list[str]]:
    """Reconcile typed intent with the planner's own list.

    A client who shows us their sofa must end up with ONE sofa - theirs. So an
    intent whose category the planner already put in that room ENRICHES that
    item instead of appending a second one; only a category the planner missed
    adds an item.

    PRECEDENCE, and why it differs from `apply_spatial_graph`. That function
    never overwrites a filled field, because it infers relations from
    image-space heuristics - weaker evidence than the planner's own reading. A
    reference is the opposite: the client photographed the actual piece, so on
    appearance it outranks a guess the planner made from prose. Measured on
    this very path: the planner had already written `material_hint="fabric"`
    from the brief while the reference said `linen`, and a never-overwrite rule
    silently kept "fabric" - the exact class of loss this phase exists to end.
    So a stated attribute wins, and the note records what it replaced.

    Returns the new item list and one note per action, so the job log can say
    what the references changed.
    """
    out = [i.model_copy(deep=True) for i in items]
    notes: list[str] = []
    for n, m in enumerate(merged):
        if m.uncertain or not (m.instantiate or m.influences_appearance):
            continue
        room_id = room_for.get(m.room_hint.lower(), default_room_id)
        if not room_id:
            continue
        donor = intent_to_plan_item(m, f"intent_{n}_{m.object_category}", room_id)
        existing = next((i for i in out
                         if i.semantic_type == m.object_category and i.room_id == room_id), None)
        if existing is None:
            # Only an EXACT_OBJECT may bring a piece into existence. A
            # DESIGN_REFERENCE says "a sofa LIKE this" - it shapes the sofa the
            # planner wanted, and conjures nothing when there is none.
            if not m.instantiate:
                continue
            out.append(donor)
            notes.append(f"{m.object_category}: added from reference "
                         f"({', '.join(m.sources)})")
            continue
        changed = []
        for field in ("color_hint", "material_hint", "style_notes"):
            stated = getattr(donor, field)
            if not stated:
                continue
            previous = getattr(existing, field)
            if previous == stated:
                continue
            setattr(existing, field, stated)
            changed.append(f"{field}={stated!r}" + (f" (was {previous!r})" if previous else ""))
        # P13: the full appearance block travels too, under the same rule -
        # an attribute the reference STATED wins; one it never mentioned leaves
        # whatever was already there alone.
        for field, value in donor.visual.stated().items():
            if getattr(existing.visual, field) != value:
                setattr(existing.visual, field, value)
                changed.append(f"visual.{field}={value!r}")
        for source in donor.source_intent_ids:
            if source not in existing.source_intent_ids:
                existing.source_intent_ids.append(source)
        notes.append(f"{m.object_category}: enriched the planner's own item"
                     + (f" ({', '.join(changed)})" if changed else " (already matched)"))
    return out, notes


def intent_plan_items(merged: list[MergedIntent], room_for: dict[str, str],
                      default_room_id: str = "") -> list[ObjectPlanItem]:
    """Plan items for the intents that ask for an object to EXIST.

    The gate is `MergedIntent.instantiate`, which comes from POLICY - so a
    STYLE_REFERENCE or INSPIRATION_ONLY photo cannot produce an item here no
    matter what attributes it carried, and a contradicted category is held back
    for a human instead of being guessed at.

    These items join the planner's own list; they do not replace it, and they
    carry no coordinates. `place_objects` still decides whether each one fits
    and where it goes - an intent states that a piece is wanted, never where.
    """
    items: list[ObjectPlanItem] = []
    for n, m in enumerate(merged):
        if not m.instantiate or m.uncertain:
            continue
        room_id = room_for.get(m.room_hint.lower(), default_room_id)
        if not room_id:
            continue
        items.append(intent_to_plan_item(m, f"intent_{n}_{m.object_category}", room_id))
    return items


__all__ = ["ResolutionRung", "GenerationRequest", "IntentResolution", "exact_asset_id",
           "generation_prompt", "intent_to_plan_item", "resolve_intent", "resolve_all",
           "intent_plan_items", "apply_intents_to_plan"]

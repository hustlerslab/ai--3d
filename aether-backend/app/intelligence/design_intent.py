"""P11 typed design intent: what a reference image actually MEANS.

WHY THIS EXISTS. Before P11 a reference photo reached the 3D scene through
exactly one channel: it conditioned a Stable Diffusion moodboard render (one
IP-Adapter image at 0.35 strength plus a 34-word CLIP prompt with hex codes
deliberately stripped), a vision model then read that RENDER back into
`SceneElement`s, and `merge_reading_into_plan` replaced the planner's items
for the room with what it found. Past that line no object carried any link to
any file the client uploaded, and the only per-object appearance that survived
into Blender was one hex tint over one of four project-wide materials.

This module is the typed channel that does not go through an image. A
reference becomes a `DesignIntent` - a category, a class, measured visual
attributes, a confidence and the provenance of the photo it came from - and
that record travels to asset resolution intact.

WHAT IT DOES NOT DO. It states intent; it never decides geometry. Nothing here
produces a position, a rotation or a scale, and no model output reaches the
solver through it: `instantiate` says an object is WANTED, and the spatial
engine remains the only thing that decides whether and where one can go.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "p11.1"


class ReferenceClass(str, Enum):
    """What the client meant by showing us this picture.

    The five classes are not a confidence ladder - they are five different
    INSTRUCTIONS, and conflating them is how a mood photo becomes a sofa.
    """

    #: "I own this / I want exactly this piece." Must appear in the 3D scene
    #: when the geometry permits it.
    EXACT_OBJECT = "exact_object"
    #: "Something like this, in this colour/material." Must shape the asset
    #: chosen or generated for its category, without being copied literally.
    DESIGN_REFERENCE = "design_reference"
    #: "This is the feel I want." Palette, material and style only - never an
    #: object on its own.
    STYLE_REFERENCE = "style_reference"
    #: Saved for mood. Must never be instantiated and must not pull the
    #: palette around either.
    INSPIRATION_ONLY = "inspiration_only"
    #: The model could not tell. Must surface for a human; must never quietly
    #: become a scene object.
    UNCERTAIN = "uncertain"


class IntentPolicy(BaseModel):
    """The instruction each class carries, as data rather than scattered ifs."""

    instantiate: bool
    influences_appearance: bool
    influences_style: bool
    needs_input: bool


#: The one place the class semantics live. Every consumer reads this table;
#: nothing re-derives the rules from the enum.
POLICY: dict[ReferenceClass, IntentPolicy] = {
    ReferenceClass.EXACT_OBJECT: IntentPolicy(
        instantiate=True, influences_appearance=True, influences_style=True, needs_input=False),
    ReferenceClass.DESIGN_REFERENCE: IntentPolicy(
        instantiate=False, influences_appearance=True, influences_style=True, needs_input=False),
    ReferenceClass.STYLE_REFERENCE: IntentPolicy(
        instantiate=False, influences_appearance=False, influences_style=True, needs_input=False),
    ReferenceClass.INSPIRATION_ONLY: IntentPolicy(
        instantiate=False, influences_appearance=False, influences_style=False, needs_input=False),
    ReferenceClass.UNCERTAIN: IntentPolicy(
        instantiate=False, influences_appearance=False, influences_style=False, needs_input=True),
}


class VisualAttributes(BaseModel):
    """Appearance as the reference actually described it.

    `color_words` exists because `SpottedObject.color` accepts only a 7-char
    hex, so every colour the model named in words ("sage green", "brushed
    brass") became an empty string at the coercion boundary. The words are the
    evidence; the hex is a derived convenience and may be blank.
    """

    color_words: list[str] = []
    color_hex: str = ""
    material: str = ""
    upholstery: str = ""
    pattern: str = ""
    frame_finish: str = ""
    style_descriptors: list[str] = []
    visual_descriptors: list[str] = []

    def is_empty(self) -> bool:
        return not any((self.color_words, self.color_hex, self.material, self.upholstery,
                        self.pattern, self.frame_finish, self.style_descriptors,
                        self.visual_descriptors))

    def stated(self) -> dict[str, object]:
        """Only the attributes this reference actually stated - the basis for
        fidelity scoring, so an unstated attribute is never counted as a miss."""
        out: dict[str, object] = {}
        for name in ("color_words", "color_hex", "material", "upholstery", "pattern",
                     "frame_finish", "style_descriptors", "visual_descriptors"):
            value = getattr(self, name)
            if value:
                out[name] = value
        return out


class IntentProvenance(BaseModel):
    """Which picture said this, and who read it. Never empty in practice: an
    intent with no source cannot be audited and must not steer a scene."""

    input_id: str = ""
    filename: str = ""
    #: Project-relative path of the reference image itself.
    image_ref: str = ""
    #: Project-relative path of the crop this intent was read from, if any.
    crop_ref: str = ""
    #: Which pass produced it: "reference_classification" | "user_override" |
    #: "scene_reading" | "analysis".
    stage: str = "reference_classification"
    #: Provider label, e.g. "gemini:gemini-2.5-flash" or "mock".
    model: str = ""


def intent_id(input_id: str, reference_class: str, object_category: str, room_hint: str = "") -> str:
    """Deterministic, content-addressed - never `uuid4()`, never Python's
    salted `hash()`. Two runs over the same references produce the same ids,
    which is what makes the determinism scenario in the P11 benchmark and the
    byte-identical `design_intent.json` checkpoint meaningful."""
    raw = f"{input_id}|{reference_class}|{object_category}|{room_hint}".encode("utf-8")
    return f"di_{hashlib.sha1(raw).hexdigest()[:16]}"


class DesignIntent(BaseModel):
    """One typed statement of visual intent, traceable to one reference."""

    intent_id: str = ""
    reference_class: ReferenceClass = ReferenceClass.UNCERTAIN
    #: Canonical semantic type when the intent names an object; "" for a pure
    #: style or inspiration reference.
    object_category: str = ""
    #: Free-text room name from the reference, matched to a room later. Never
    #: a room_id: the intent is stated before rooms are laid out.
    room_hint: str = ""
    attributes: VisualAttributes = Field(default_factory=VisualAttributes)
    confidence: float = 0.0
    notes: str = ""
    provenance: IntentProvenance = Field(default_factory=IntentProvenance)

    @classmethod
    def create(cls, reference_class: ReferenceClass, provenance: IntentProvenance, *,
               object_category: str = "", room_hint: str = "",
               attributes: Optional[VisualAttributes] = None, confidence: float = 0.0,
               notes: str = "") -> "DesignIntent":
        return cls(
            intent_id=intent_id(provenance.input_id, reference_class.value, object_category, room_hint),
            reference_class=reference_class, object_category=object_category, room_hint=room_hint,
            attributes=attributes or VisualAttributes(), confidence=confidence, notes=notes,
            provenance=provenance)

    @property
    def policy(self) -> IntentPolicy:
        return POLICY[self.reference_class]

    @property
    def instantiate(self) -> bool:
        """Whether this reference asks for an object to exist. An EXACT_OBJECT
        with no category cannot be instantiated - there is nothing to place -
        so it degrades to False rather than inventing a category."""
        return self.policy.instantiate and bool(self.object_category)

    @property
    def needs_input(self) -> bool:
        return self.policy.needs_input or (
            self.reference_class is ReferenceClass.EXACT_OBJECT and not self.object_category)


class IntentConflict(BaseModel):
    """Two references that cannot both be honoured. Recorded, never resolved
    by silently preferring one - P10's rule that UNKNOWN must stay UNKNOWN."""

    object_category: str
    room_hint: str = ""
    attribute: str
    values: list[str]
    intent_ids: list[str]
    message: str = ""


class DesignIntentSet(BaseModel):
    """Every reference, classified. The unit the pipeline persists and audits."""

    schema_version: str = SCHEMA_VERSION
    #: Every reference this set was built from, in upload order. Lets a cached
    #: classification be compared against the project's CURRENT references, so
    #: a newly uploaded photo is never ignored because an older set exists.
    reference_ids: list[str] = []
    intents: list[DesignIntent] = []
    conflicts: list[IntentConflict] = []
    #: References that produced no intent at all, with the reason. A reference
    #: is never dropped silently: if it could not be read, it says so here.
    unread: list[str] = []
    warnings: list[str] = []

    def by_class(self, reference_class: ReferenceClass) -> list[DesignIntent]:
        return [i for i in self.intents if i.reference_class is reference_class]

    def to_instantiate(self) -> list[DesignIntent]:
        """Sorted deterministically: confidence first, then the content-addressed
        id, so the same references always yield the same order."""
        return sorted((i for i in self.intents if i.instantiate),
                      key=lambda i: (-i.confidence, i.intent_id))

    def needing_input(self) -> list[DesignIntent]:
        return sorted((i for i in self.intents if i.needs_input), key=lambda i: i.intent_id)

    def appearance_intents(self) -> list[DesignIntent]:
        """Intents allowed to shape an asset's appearance, best evidence first."""
        return sorted((i for i in self.intents if i.policy.influences_appearance and i.object_category),
                      key=lambda i: (-i.confidence, i.intent_id))

    def style_intents(self) -> list[DesignIntent]:
        return sorted((i for i in self.intents if i.policy.influences_style),
                      key=lambda i: (-i.confidence, i.intent_id))


class MergedIntent(BaseModel):
    """What several references, taken together, ask for in one category.

    `attributes` holds only what the references AGREE on. A disagreement does
    not pick a winner: the attribute is left blank, the clash is recorded in
    `conflicts`, and the category is marked `uncertain` so a human decides.
    """

    object_category: str
    room_hint: str = ""
    attributes: VisualAttributes = Field(default_factory=VisualAttributes)
    #: May an object of this category be CREATED because of these references?
    #: Only EXACT_OBJECT earns this.
    instantiate: bool = False
    #: May these references shape an object of this category that already
    #: exists? DESIGN_REFERENCE earns this without earning `instantiate` -
    #: "a sofa like this" changes the sofa, it does not conjure one.
    influences_appearance: bool = False
    uncertain: bool = False
    #: Every intent that fed this, best evidence first.
    sources: list[str] = []
    conflicts: list[IntentConflict] = []


#: Attributes merged as a single value, where two different answers is a real
#: contradiction rather than two compatible facts.
_SCALAR_ATTRS = ("color_hex", "material", "upholstery", "pattern", "frame_finish")
#: Attributes merged as a union, where more evidence is simply more evidence.
_LIST_ATTRS = ("color_words", "style_descriptors", "visual_descriptors")


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())


def merge_intents(intents: list[DesignIntent]) -> list[MergedIntent]:
    """Deterministically fold per-reference intents into per-category intent.

    Order is fixed by (category, room_hint) and, within a group, by descending
    confidence then content-addressed id - never by dict or upload order, so
    re-running over the same references gives the same answer.

    Only intents whose class permits appearance influence contribute
    attributes (POLICY): a STYLE_REFERENCE colours the palette, not the sofa,
    and an INSPIRATION_ONLY photo contributes nothing at all.
    """
    groups: dict[tuple[str, str], list[DesignIntent]] = {}
    for intent in intents:
        if not intent.object_category:
            continue
        if not (intent.policy.influences_appearance or intent.policy.instantiate
                or intent.reference_class is ReferenceClass.UNCERTAIN):
            continue
        groups.setdefault((intent.object_category, intent.room_hint), []).append(intent)

    merged: list[MergedIntent] = []
    for (category, room_hint) in sorted(groups):
        members = sorted(groups[(category, room_hint)], key=lambda i: (-i.confidence, i.intent_id))
        contributing = [i for i in members if i.policy.influences_appearance]
        attributes = VisualAttributes()
        conflicts: list[IntentConflict] = []

        for name in _SCALAR_ATTRS:
            seen: dict[str, list[DesignIntent]] = {}
            for intent in contributing:
                value = getattr(intent.attributes, name)
                if value:
                    seen.setdefault(_norm(value), []).append(intent)
            if not seen:
                continue
            if len(seen) == 1:
                setattr(attributes, name, getattr(contributing and seen[next(iter(seen))][0].attributes, name))
                continue
            ordered = sorted(seen)
            conflicts.append(IntentConflict(
                object_category=category, room_hint=room_hint, attribute=name,
                values=ordered,
                intent_ids=sorted(i.intent_id for group in seen.values() for i in group),
                message=(f"{len(seen)} references disagree on {name} for {category}"
                         f"{' in ' + room_hint if room_hint else ''}: {', '.join(ordered)}")))

        for name in _LIST_ATTRS:
            union: list[str] = []
            for intent in contributing:
                for value in getattr(intent.attributes, name):
                    if value and _norm(value) not in {_norm(v) for v in union}:
                        union.append(value)
            if union:
                setattr(attributes, name, sorted(union))

        merged.append(MergedIntent(
            object_category=category, room_hint=room_hint, attributes=attributes,
            instantiate=any(i.instantiate for i in members),
            influences_appearance=any(i.policy.influences_appearance for i in members),
            uncertain=bool(conflicts) or any(i.needs_input for i in members),
            sources=[i.intent_id for i in members], conflicts=conflicts))
    return merged


__all__ = ["SCHEMA_VERSION", "ReferenceClass", "IntentPolicy", "POLICY", "VisualAttributes",
           "IntentProvenance", "intent_id", "DesignIntent", "IntentConflict", "DesignIntentSet",
           "MergedIntent", "merge_intents"]

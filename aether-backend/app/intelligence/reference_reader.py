"""P11 reference classification: every uploaded photo becomes typed intent.

WHAT THIS REPLACES. References used to reach the design exactly twice: as up
to six images bolted onto one `analyze_input` call (a hardcoded cap while
uploads allowed twelve), and as one IP-Adapter image conditioning the
moodboard render. Neither produced a record of what a given photo MEANT, so
"this is the sofa I own" and "I like this mood" were indistinguishable
downstream, and references seven and eight simply never existed.

WHAT IT DOES. One focused call per reference - not one call carrying every
reference - producing a `DesignIntent` per photo. Per-reference is deliberate:
the capacity probe (docs/benchmarks/p11_reference_capacity.json) found that
while twelve images fit comfortably inside the context window, the model's
attribute extraction thins out as images pile onto a single call. Reading each
photo on its own keeps the evidence attributable and keeps one busy image from
crowding out another.

FAIL-SAFE DIRECTION. Every uncertainty resolves DOWN the instantiation ladder,
never up: an unreadable photo, an unknown class or a class the model invented
all become UNCERTAIN, which needs human input and can never become a scene
object on its own. A reference that could not be read is listed in
`DesignIntentSet.unread` - never dropped in silence, which is the failure this
phase exists to end.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from . import vocab
from .design_intent import (DesignIntent, DesignIntentSet, IntentProvenance, ReferenceClass,
                            VisualAttributes, merge_intents)
from .schema import InputBundle

log = logging.getLogger("aether.reference_reader")

#: Classes a model is allowed to assert. Anything else becomes UNCERTAIN.
_CLASS_BY_NAME = {c.value: c for c in ReferenceClass}

#: A classification this weak is not evidence. The threshold is deliberately
#: generous - it exists to catch "the model shrugged", not to second-guess a
#: confident read.
MIN_CONFIDENCE = 0.25


def _accepts_filename(fn: Any) -> bool:
    try:
        return "filename" in inspect.signature(fn).parameters
    except (TypeError, ValueError):                                     # noqa: BLE001
        return False


def _clean(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) and str(value).strip() else ""


def _clean_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = _clean(item)
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:limit]


def _hex(value: Any) -> str:
    text = _clean(value)
    return text if len(text) == 7 and text.startswith("#") else ""


def attributes_from_raw(raw: dict[str, Any]) -> VisualAttributes:
    return VisualAttributes(
        color_words=_clean_list(raw.get("color_words")),
        color_hex=_hex(raw.get("color_hex")),
        material=_clean(raw.get("material")),
        upholstery=_clean(raw.get("upholstery")),
        pattern=_clean(raw.get("pattern")),
        frame_finish=_clean(raw.get("frame_finish")),
        style_descriptors=_clean_list(raw.get("style_descriptors")),
        visual_descriptors=_clean_list(raw.get("visual_descriptors")),
    )


def intent_from_raw(raw: dict[str, Any], provenance: IntentProvenance) -> DesignIntent:
    """Coerce one model answer into a typed intent, downgrading anything it
    cannot justify. An unknown class, a missing category on an EXACT_OBJECT, or
    a confidence below the floor all land on UNCERTAIN rather than guessing."""
    stated = _clean(raw.get("reference_class")).lower().replace(" ", "_")
    reference_class = _CLASS_BY_NAME.get(stated, ReferenceClass.UNCERTAIN)
    note = _clean(raw.get("notes"))
    if stated and stated not in _CLASS_BY_NAME:
        note = f"model returned unknown class {stated!r}; treated as uncertain. {note}".strip()

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    name = _clean(raw.get("object_name")) or _clean(raw.get("object_category"))
    category = vocab.canonical_type(name, _clean(raw.get("object_category"))) if name else ""
    if category == "other":
        category = ""

    if reference_class in (ReferenceClass.EXACT_OBJECT, ReferenceClass.DESIGN_REFERENCE):
        if not category:
            reference_class = ReferenceClass.UNCERTAIN
            note = (f"classified {stated} but named no recognisable object type; "
                    f"treated as uncertain. {note}").strip()
        elif confidence < MIN_CONFIDENCE:
            reference_class = ReferenceClass.UNCERTAIN
            note = (f"classified {stated} at confidence {confidence:.2f}, below the "
                    f"{MIN_CONFIDENCE} floor; treated as uncertain. {note}").strip()

    return DesignIntent.create(
        reference_class, provenance, object_category=category,
        room_hint=_clean(raw.get("room_hint")), attributes=attributes_from_raw(raw),
        confidence=confidence, notes=note)


def classify_references(bundle: InputBundle, provider: Any) -> DesignIntentSet:
    """Turn every reference in the bundle into typed intent.

    No cap: the whole point is that nothing is dropped. A provider without the
    optional `classify_reference` capability yields an empty set with a warning
    naming the provider - honest emptiness, never invented classifications.
    """
    intents: list[DesignIntent] = []
    unread: list[str] = []
    warnings: list[str] = []

    reference_ids = [r.input_id for r in bundle.references]
    classify = getattr(provider, "classify_reference", None)
    if not callable(classify):
        label = getattr(provider, "label", provider.__class__.__name__)
        return DesignIntentSet(
            reference_ids=reference_ids,
            unread=[r.filename or r.input_id for r in bundle.references],
            warnings=[f"{label} cannot classify references: no classify_reference capability. "
                      f"{len(bundle.references)} reference(s) contributed no typed design intent."])

    for ref in bundle.references:
        provenance = IntentProvenance(
            input_id=ref.input_id, filename=ref.filename or "", image_ref=ref.path,
            stage="reference_classification",
            model=str(getattr(provider, "label", provider.__class__.__name__)))
        try:
            # The uploader renames every reference to `ref_NN.ext` on disk, so
            # the client's own filename travels separately or it is lost.
            # `filename` is optional on the capability: a provider written
            # against the three-argument form must keep working (ADR-001's rule
            # that a vendor implementing the smaller contract is never broken).
            if _accepts_filename(classify):
                raw = classify(Path(ref.path), bundle.description, bundle.vertical,
                               filename=ref.filename or "") or {}
            else:
                raw = classify(Path(ref.path), bundle.description, bundle.vertical) or {}
        except Exception as exc:                                        # noqa: BLE001
            log.exception("classify_reference failed for %s", ref.filename)
            unread.append(ref.filename or ref.input_id)
            warnings.append(f"could not classify {ref.filename or ref.input_id}: "
                            f"{type(exc).__name__}: {exc}")
            continue
        if raw.get("_error"):
            unread.append(ref.filename or ref.input_id)
            warnings.append(f"could not classify {ref.filename or ref.input_id}: {raw['_error']}")
            continue
        intents.append(intent_from_raw(raw, provenance))

    merged = merge_intents(intents)
    conflicts = [c for m in merged for c in m.conflicts]
    if unread:
        warnings.append(f"{len(unread)} of {len(bundle.references)} reference(s) produced no design "
                        "intent; their visual direction is NOT represented in the plan")
    return DesignIntentSet(reference_ids=reference_ids, intents=intents, conflicts=conflicts,
                           unread=unread, warnings=warnings)


def style_words(intent_set: DesignIntentSet) -> list[str]:
    """Palette/material/style vocabulary the references justify, deterministic.

    STYLE_REFERENCE and the appearance classes contribute; INSPIRATION_ONLY and
    UNCERTAIN contribute nothing, which is the whole point of separating them.
    """
    words: list[str] = []
    for intent in intent_set.style_intents():
        attrs = intent.attributes
        for value in (*attrs.style_descriptors, *attrs.color_words, attrs.material,
                      attrs.frame_finish, attrs.pattern):
            if value and value.lower() not in {w.lower() for w in words}:
                words.append(value)
    return words


__all__ = ["MIN_CONFIDENCE", "attributes_from_raw", "intent_from_raw", "classify_references",
           "style_words"]

"""P11 visual-intent fidelity: did the 3D scene keep what the references said?

Answers the question visual inspection cannot answer repeatably - "is the
client's sage-green linen sofa actually in there, and is it sage green?" - by
comparing the typed `DesignIntentSet` against the committed `Scene` and the
asset/material assignments that reach the executor (`app/blender/manifest.py`;
the same rows would feed any other executor placed behind that boundary).

FOUR SEPARATE RATES, NEVER ONE SCORE. P10's rule: a single number hides which
half failed. An INSPIRATION_ONLY photo that correctly produced no object and a
DESIGN_REFERENCE whose colour was ignored are different outcomes, and
averaging them into one percentage is how a regression disappears.

    instantiation_fidelity        EXACT_OBJECT intents that became an object
    appearance_fidelity           stated attributes the resolved asset honours
    non_instantiation_compliance  intents that must NOT create an object and
                                  did not - the one rate that must stay 1.0
    traceability                  scene objects whose appearance can be traced
                                  back to a named reference

An unstated attribute is never counted as a miss, and a rate over an empty
population is `None`, not 1.0 - "nothing to check" is not "everything passed".
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from enum import Enum

from ..intelligence.design_intent import DesignIntentSet, ReferenceClass
from ..scene.schema import Scene
from .intent_resolution import IntentResolution, ResolutionRung

SCHEMA_VERSION = "p11.1"


class ExecutorSupport(str, Enum):
    """What the CURRENT executor can actually do with an attribute.

    Kept separate from whether the attribute survived. An attribute can reach
    the manifest perfectly and still not be painted, and calling that "rendered"
    would be the fabricated success this programme keeps refusing.
    """

    #: The executor changes what you see because of it, always.
    PRESERVED_AND_RENDERED = "preserved_and_rendered"
    #: The executor CAN paint it, but only when the object earns it - the word
    #: resolves to a real registry material and the asset has somewhere to put
    #: it. The per-object answer lives in the manifest's `finish.state`, never
    #: assumed from the attribute alone.
    CONDITIONALLY_RENDERED = "conditionally_rendered"
    #: It crosses the boundary intact and is queryable, but nothing in Blender
    #: consumes it yet.
    PRESERVED_METADATA_ONLY = "preserved_metadata_only"
    #: No representation at all.
    NOT_SUPPORTED = "not_supported"


class AttributeContract(BaseModel):
    scene_field: str
    executor: ExecutorSupport
    how: str


#: REFERENCE ATTRIBUTE -> SCENE ATTRIBUTE -> EXECUTOR BEHAVIOUR.
#:
#: Derived by reading `blender/scripts/apply_materials.py`, not by assumption:
#: `for_object` takes exactly two things - `material_overrides["primary"]` (a
#: registry material with real PBR maps) and `color` (a hex tinted in at
#: strength 0.85). There is ONE material slot per object, so a frame finish
#: distinct from an upholstery cannot be expressed, and there is no procedural
#: pattern generator, so "quilted" cannot become geometry or a texture.
VISUAL_ATTRIBUTE_CONTRACT: dict[str, AttributeContract] = {
    "color_hex": AttributeContract(
        scene_field="color", executor=ExecutorSupport.PRESERVED_AND_RENDERED,
        how="tinted into the object's material at strength 0.85 (apply_materials.for_object)"),
    "material": AttributeContract(
        scene_field="visual.material", executor=ExecutorSupport.PRESERVED_AND_RENDERED,
        how="resolved to a registry material id in material_overrides['primary'] with its PBR maps"),
    "upholstery": AttributeContract(
        scene_field="visual.upholstery", executor=ExecutorSupport.PRESERVED_AND_RENDERED,
        how="same channel as material - it is preferred over material when both are stated"),
    "color_words": AttributeContract(
        scene_field="visual.color_words", executor=ExecutorSupport.PRESERVED_METADATA_ONLY,
        how="no colour-word to hex resolution exists in the repository; the rendered colour "
            "channel is color_hex. Resolving words against the material registry's own "
            "base_colors is a scoped future step, deliberately not invented here"),
    "pattern": AttributeContract(
        scene_field="visual.pattern", executor=ExecutorSupport.PRESERVED_METADATA_ONLY,
        how="no procedural pattern or texture synthesis exists; 'quilted' cannot become "
            "geometry or a map, so it is carried as metadata rather than faked"),
    "frame_finish": AttributeContract(
        scene_field="visual.frame_finish", executor=ExecutorSupport.CONDITIONALLY_RENDERED,
        how="P14: resolved by `compiler.finish_material_for` to a material that already exists "
            "and is applies_to=furniture (veneer_walnut, veneer_oak, metal_brass, metal_black, "
            "glass_clear), then painted by `import_assets._apply_frame_finish` onto the trim "
            "meshes `_apply_upholstery` deliberately skips. Requires the asset to have more "
            "than one material region: MEASURED at 10 of 58 registry assets, so most pieces "
            "report metadata_only. Per-object state is in the manifest's `finish.state`. "
            "MEASURED on 8 real photographs: Gemini populates this field 0 times, so a stated "
            "frame finish is currently rare and the descriptor route below carries it instead"),
    "descriptors": AttributeContract(
        scene_field="visual.descriptors", executor=ExecutorSupport.CONDITIONALLY_RENDERED,
        how="P14: a descriptor that names a structural part AND resolves to an existing registry "
            "material ('wooden frame', 'gold accent trim') supplies the frame finish and is "
            "painted by `import_assets._apply_frame_finish`, recorded as `finish.source == "
            "'descriptor'` and never counted as a stated frame_finish. MEASURED on 8 real "
            "photographs: 2 of 8 carry frame evidence this way. The surface-quality words "
            "(matte/satin/glossy) are resolved to `finish.roughness` in the manifest but NO "
            "Blender script reads that key, so they are carried, not applied - and they appear "
            "in 0 of the 8 measured references. Everything else ('luxurious', 'contemporary', "
            "'rounded') has no defensible mapping and stays semantic metadata; it still "
            "influences asset SELECTION upstream through style_notes"),
}


class AttributeSurvival(BaseModel):
    attribute: str
    stated: int
    reached_scene: int
    rate: Optional[float] = None
    executor: ExecutorSupport
    note: str = ""


class FidelityRow(BaseModel):
    """One intent, and what became of it."""

    intent_id: str
    reference_class: str
    object_category: str
    room_hint: str = ""
    expected_instantiated: bool
    instantiated: bool
    rung: str = ""
    attribute_match: dict[str, bool] = {}
    attribute_fidelity: Optional[float] = None
    traced_object_ids: list[str] = []
    needs_input: bool = False
    note: str = ""


class FidelityReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    metrics: dict[str, Optional[float]] = {}
    counts: dict[str, int] = {}
    rows: list[FidelityRow] = []
    #: Per-attribute reference-to-scene survival, never averaged into `metrics`.
    survival: list[AttributeSurvival] = []
    unresolved: list[str] = []
    warnings: list[str] = []

    @property
    def compliant(self) -> bool:
        """The one hard invariant: nothing that must not be instantiated was."""
        return self.metrics.get("non_instantiation_compliance") in (None, 1.0)


def _rate(hits: int, total: int) -> Optional[float]:
    return None if total == 0 else round(hits / total, 4)


#: How an intent attribute is spelled once it is on a scene object. The two
#: descriptor lists merge into one, and colour resolves to the object's hex.
_SCENE_READERS = {
    "color_words": lambda o: list(o.visual.color_words),
    "color_hex": lambda o: [o.color] if o.color else [],
    "material": lambda o: [o.visual.material] if o.visual.material else [],
    "upholstery": lambda o: [o.visual.upholstery] if o.visual.upholstery else [],
    "pattern": lambda o: [o.visual.pattern] if o.visual.pattern else [],
    "frame_finish": lambda o: [o.visual.frame_finish] if o.visual.frame_finish else [],
    "descriptors": lambda o: list(o.visual.descriptors),
}
#: Intent-side names that feed each scene attribute.
_INTENT_SOURCES = {
    "descriptors": ("style_descriptors", "visual_descriptors"),
}


def attribute_survival(intent_set: DesignIntentSet, scene: Scene) -> list[AttributeSurvival]:
    """Did each stated attribute actually reach a scene object of its category?

    Measured against the COMMITTED scene, per attribute, never averaged - the
    whole point is that "material arrived and pattern did not" stays visible.
    An attribute nobody stated has `rate=None`: nothing to check is not
    everything passed.
    """
    by_category: dict[str, list] = {}
    for obj in scene.objects:
        by_category.setdefault(obj.semantic_type, []).append(obj)

    out: list[AttributeSurvival] = []
    for attribute, contract in VISUAL_ATTRIBUTE_CONTRACT.items():
        stated = reached = 0
        for intent in intent_set.intents:
            if not intent.object_category or not intent.policy.influences_appearance:
                continue
            names = _INTENT_SOURCES.get(attribute, (attribute,))
            values: list[str] = []
            for name in names:
                value = getattr(intent.attributes, name, "")
                values.extend(value if isinstance(value, list) else ([value] if value else []))
            if not values:
                continue
            stated += 1
            objects = by_category.get(intent.object_category, [])
            present = {str(v).lower() for o in objects for v in _SCENE_READERS[attribute](o)}
            # color_hex is RESOLVED on the way to the scene (a word becomes a
            # palette slot), so its survival is "the object carries a colour",
            # not "the object carries this exact string".
            if attribute == "color_hex":
                reached += int(bool(present))
            elif any(str(v).lower() in present for v in values):
                reached += 1
        out.append(AttributeSurvival(
            attribute=attribute, stated=stated, reached_scene=reached,
            rate=_rate(reached, stated), executor=contract.executor,
            note=contract.how if stated else "not stated by any reference"))
    return out


def visual_intent_fidelity(intent_set: DesignIntentSet, resolutions: list[IntentResolution],
                           scene: Scene) -> FidelityReport:
    """Compare stated intent against the scene that was actually built."""
    by_category: dict[str, list] = {}
    for obj in scene.objects:
        by_category.setdefault(obj.semantic_type, []).append(obj)

    resolution_for: dict[str, IntentResolution] = {}
    for res in resolutions:
        for source in res.source_intent_ids:
            resolution_for[source] = res

    rows: list[FidelityRow] = []
    inst_hits = inst_total = 0
    attr_hits = attr_total = 0
    comply_hits = comply_total = 0
    traced_ids: set[str] = set()

    for intent in sorted(intent_set.intents, key=lambda i: i.intent_id):
        res = resolution_for.get(intent.intent_id)
        objects = by_category.get(intent.object_category, []) if intent.object_category else []
        instantiated = bool(objects)
        expected = intent.instantiate

        row = FidelityRow(
            intent_id=intent.intent_id, reference_class=intent.reference_class.value,
            object_category=intent.object_category, room_hint=intent.room_hint,
            expected_instantiated=expected, instantiated=instantiated,
            rung=res.rung.value if res else "",
            attribute_match=dict(res.attribute_match) if res else {},
            attribute_fidelity=res.attribute_fidelity if res else None,
            needs_input=bool(res and res.needs_input) or intent.needs_input)

        if expected:
            inst_total += 1
            inst_hits += int(instantiated)
            if not instantiated:
                row.note = "EXACT_OBJECT intent produced no object of its category"
        else:
            # The compliance population is only the classes that are FORBIDDEN
            # from creating an object on their own. A DESIGN_REFERENCE does not
            # instantiate by itself, but an object of that category appearing
            # because the planner wanted one anyway is not a violation.
            if intent.reference_class in (ReferenceClass.INSPIRATION_ONLY, ReferenceClass.UNCERTAIN):
                comply_total += 1
                spurious = bool(res and res.rung is not ResolutionRung.UNRESOLVED and instantiated)
                comply_hits += int(not spurious)
                if spurious:
                    row.note = (f"{intent.reference_class.value} intent was resolved to an asset "
                                f"and an object of its category exists")

        if res and res.attribute_match:
            attr_total += len(res.attribute_match)
            attr_hits += sum(1 for ok in res.attribute_match.values() if ok)

        if res and instantiated and intent.policy.influences_appearance:
            ids = [o.object_id for o in objects]
            row.traced_object_ids = ids
            traced_ids.update(ids)

        rows.append(row)

    unresolved = sorted({r.object_category for r in resolutions
                         if r.rung is ResolutionRung.UNRESOLVED or r.needs_input})

    report = FidelityReport(
        metrics={
            "instantiation_fidelity": _rate(inst_hits, inst_total),
            "appearance_fidelity": _rate(attr_hits, attr_total),
            "non_instantiation_compliance": _rate(comply_hits, comply_total),
            "traceability": _rate(len(traced_ids), len(scene.objects)),
        },
        counts={
            "intents": len(intent_set.intents),
            "conflicts": len(intent_set.conflicts),
            "unread_references": len(intent_set.unread),
            "scene_objects": len(scene.objects),
            "expected_objects": inst_total,
            "stated_attributes": attr_total,
            "needs_input": sum(1 for r in rows if r.needs_input),
            "generated": sum(1 for r in resolutions if r.rung is ResolutionRung.GENERATE),
            "exact_assets": sum(1 for r in resolutions if r.rung is ResolutionRung.EXACT_ASSET),
            "compatible_assets": sum(1 for r in resolutions if r.rung is ResolutionRung.COMPATIBLE_ASSET),
        },
        rows=rows, survival=attribute_survival(intent_set, scene), unresolved=unresolved,
        warnings=list(intent_set.warnings))

    if intent_set.unread:
        report.warnings.append(
            f"{len(intent_set.unread)} reference(s) produced no intent - design evidence was lost "
            "before scene planning")
    return report


__all__ = ["SCHEMA_VERSION", "ExecutorSupport", "AttributeContract", "VISUAL_ATTRIBUTE_CONTRACT",
           "AttributeSurvival", "attribute_survival", "FidelityRow", "FidelityReport",
           "visual_intent_fidelity"]

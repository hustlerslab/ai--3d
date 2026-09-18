"""P11: design intent survives from reference photo to 3D scene.

The ten brief scenarios run as one parametrised case each (the benchmark owns
the scenarios so the suite and the standalone run can never disagree), plus the
invariants that must hold whatever a model returns.
"""
from __future__ import annotations

import pytest

from app.intelligence.design_intent import (POLICY, DesignIntent, IntentProvenance, ReferenceClass,
                                            VisualAttributes, intent_id, merge_intents)
from app.intelligence.mock_provider import MockProvider
from app.intelligence.reference_reader import MIN_CONFIDENCE, classify_references, intent_from_raw
from app.intelligence.schema import InputBundle, ReferenceImage, Vertical
from app.planning.intent_resolution import ResolutionRung, apply_intents_to_plan, resolve_intent
from research.p11_intent_benchmark import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda f: f.__name__)
def test_p11_scenario(scenario):
    detail = scenario()
    assert detail.pop("ok") is True, detail


def _prov(n: int = 1) -> IntentProvenance:
    return IntentProvenance(input_id=f"in_{n}", filename=f"r{n}.jpg", model="test")


def test_only_exact_object_instantiates():
    """The class table IS the contract: three of five classes may never create
    an object, and UNCERTAIN must ask a human instead."""
    assert [c for c in ReferenceClass if POLICY[c].instantiate] == [ReferenceClass.EXACT_OBJECT]
    for cls in (ReferenceClass.STYLE_REFERENCE, ReferenceClass.INSPIRATION_ONLY,
                ReferenceClass.UNCERTAIN):
        intent = DesignIntent.create(cls, _prov(), object_category="sofa", confidence=0.99)
        assert intent.instantiate is False
    assert POLICY[ReferenceClass.UNCERTAIN].needs_input is True
    assert POLICY[ReferenceClass.INSPIRATION_ONLY].influences_style is False


@pytest.mark.parametrize("raw,reason", [
    ({"reference_class": "buy_this_one", "object_category": "sofa", "confidence": 0.99}, "invented class"),
    ({"reference_class": "exact_object", "object_category": "", "object_name": "", "confidence": 0.99}, "no category"),
    ({"reference_class": "exact_object", "object_category": "sofa", "object_name": "sofa",
      "confidence": MIN_CONFIDENCE - 0.01}, "below the confidence floor"),
    ({"reference_class": "design_reference", "object_category": "sofa", "object_name": "sofa",
      "confidence": "very sure"}, "unparseable confidence"),
])
def test_a_model_can_never_talk_its_way_into_an_object(raw, reason):
    """Every uncertainty resolves DOWN the ladder. A model cannot reach the
    scene by asserting a class it did not earn."""
    intent = intent_from_raw(raw, _prov())
    assert intent.reference_class is ReferenceClass.UNCERTAIN, reason
    assert intent.instantiate is False
    assert intent.needs_input is True
    assert intent.notes, "a downgrade must say why"


def test_no_reference_is_ever_dropped_silently():
    class Broken:
        label = "broken"

        def classify_reference(self, image, description, vertical):
            if "b.jpg" in str(image):
                raise RuntimeError("vision timeout")
            return {"reference_class": "style_reference", "confidence": 0.8}

    bundle = InputBundle(
        project_id="t", description="d", vertical=Vertical.RESIDENTIAL,
        references=[ReferenceImage(input_id="in_1", path="/p/a.jpg", filename="a.jpg"),
                    ReferenceImage(input_id="in_2", path="/p/b.jpg", filename="b.jpg")])
    result = classify_references(bundle, Broken())
    assert len(result.intents) + len(result.unread) == len(bundle.references)
    assert result.unread == ["b.jpg"]
    assert any("b.jpg" in w for w in result.warnings)


def test_a_provider_without_the_capability_invents_nothing():
    class Plain:
        label = "plain"

    bundle = InputBundle(
        project_id="t", description="d", vertical=Vertical.RESIDENTIAL,
        references=[ReferenceImage(input_id="in_1", path="/p/a.jpg", filename="a.jpg")])
    result = classify_references(bundle, Plain())
    assert result.intents == []
    assert result.unread == ["a.jpg"]
    assert "classify_reference" in result.warnings[0]


def test_conflicting_references_blank_the_attribute_and_refuse_to_resolve():
    intents = [
        DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(1), object_category="sofa",
                            attributes=VisualAttributes(material="linen"), confidence=0.9),
        DesignIntent.create(ReferenceClass.DESIGN_REFERENCE, _prov(2), object_category="sofa",
                            attributes=VisualAttributes(material="velvet"), confidence=0.85),
    ]
    merged = merge_intents(intents)[0]
    assert merged.attributes.material == "", "a clash must not be resolved by preferring one side"
    assert merged.uncertain is True
    assert merged.conflicts[0].values == ["linen", "velvet"]

    mock = MockProvider()
    bundle = InputBundle(project_id="t", description="warm flat", vertical=Vertical.RESIDENTIAL)
    style = mock.create_style_spec(mock.analyze_input(bundle), bundle)
    resolution = resolve_intent(merged, style)
    assert resolution.rung is ResolutionRung.UNRESOLVED
    assert resolution.needs_input is True


def test_ids_are_content_addressed_and_stable():
    assert intent_id("in_1", "exact_object", "sofa", "living") == \
        intent_id("in_1", "exact_object", "sofa", "living")
    assert intent_id("in_1", "exact_object", "sofa") != intent_id("in_2", "exact_object", "sofa")


def test_a_reference_outranks_a_planner_guess_but_only_where_it_spoke():
    """The client photographed the piece; the planner guessed from prose. On a
    stated attribute the photo wins - on an unstated one the planner keeps
    what it had."""
    from app.intelligence.schema import ObjectPlanItem

    planned = [ObjectPlanItem(object_key="sofa", semantic_type="sofa", room_id="r1",
                              material_hint="fabric", style_notes="warm")]
    merged = merge_intents([DesignIntent.create(
        ReferenceClass.EXACT_OBJECT, _prov(), object_category="sofa",
        attributes=VisualAttributes(material="linen"), confidence=0.9)])
    items, notes = apply_intents_to_plan(planned, merged, {}, default_room_id="r1")

    assert len(items) == 1, "the client's sofa must BE the room's sofa, not a second one"
    assert items[0].material_hint == "linen"
    assert items[0].style_notes == "warm", "an unstated attribute is left alone"
    assert "was 'fabric'" in notes[0], "a replacement must be auditable"


def test_intents_never_carry_geometry():
    """The representation states what is wanted, never where it goes - the
    solver keeps that decision."""
    intent = DesignIntent.create(ReferenceClass.EXACT_OBJECT, _prov(), object_category="sofa",
                                 attributes=VisualAttributes(material="linen"), confidence=0.9)
    dumped = intent.model_dump()
    for banned in ("position", "rotation", "rotation_y", "scale", "x", "y", "z", "transform"):
        assert banned not in dumped
        assert banned not in dumped["attributes"]

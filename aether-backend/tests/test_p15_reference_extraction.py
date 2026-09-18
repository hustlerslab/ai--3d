"""P15: the reference prompt asks for the structured fields, and asking is safe.

P14 measured `frame_finish` at 0 of 8 real photographs: Gemini saw the frames
and wrote them into `visual_descriptors` instead. The prompt invited exactly
that by saying "leave a field out otherwise", and the schema let it.

These are offline. They assert the CONTRACT - what the prompt asks for, what the
schema requires, and that asking harder cannot invent a material - because the
live-model measurement belongs in research/p15_extraction_experiment.py, where
it costs API calls and can be scored against real pictures.
"""
from __future__ import annotations

import pytest

from app.blender.manifest import _descriptor_finish, _finish_entry
from app.intelligence.prompts import (REFERENCE_CLASSIFICATION_SCHEMA,
                                      reference_classification_prompt)
from app.intelligence.reference_reader import attributes_from_raw
from app.planning.compiler import finish_material_for
from app.scene.schema import ObjectVisual, SceneObject

ATTRIBUTE_FIELDS = ["material", "upholstery", "frame_finish", "color_words",
                    "color_hex", "pattern", "visual_descriptors", "style_descriptors"]


@pytest.fixture
def prompt() -> str:
    return reference_classification_prompt("Warm and calm two bedroom flat.", "residential")


# -- the schema must force the model to consider every field ----------------

@pytest.mark.parametrize("field", ATTRIBUTE_FIELDS)
def test_every_attribute_field_is_required_so_it_cannot_be_silently_omitted(field):
    """The repository learned this once already with `against`/`faces`: an
    optional field is indistinguishable from one the model never considered."""
    assert field in REFERENCE_CLASSIFICATION_SCHEMA["required"]
    assert field in REFERENCE_CLASSIFICATION_SCHEMA["properties"]


def test_a_required_field_may_still_come_back_empty():
    """Required means answered, not populated. Empty must survive parsing as
    empty rather than becoming a guess."""
    raw = {"reference_class": "design_reference", "confidence": 0.9,
           "material": "", "upholstery": "linen", "frame_finish": "",
           "color_words": [], "color_hex": "", "pattern": "",
           "visual_descriptors": [], "style_descriptors": []}
    attrs = attributes_from_raw(raw)

    assert attrs.upholstery == "linen"
    assert attrs.frame_finish == ""
    assert attrs.material == ""
    assert attrs.color_words == []


def test_a_field_the_model_omits_entirely_still_parses():
    """Backward compatibility with any cached pre-P15 classification."""
    attrs = attributes_from_raw({"reference_class": "style_reference", "confidence": 0.5})
    assert attrs.is_empty()


# -- the prompt must ask for each field, by name and by definition ----------

@pytest.mark.parametrize("field", ATTRIBUTE_FIELDS)
def test_the_prompt_names_every_structured_field(field, prompt):
    assert field in prompt


def test_the_prompt_says_the_structured_fields_are_what_gets_read(prompt):
    """The specific failure P15 fixes: evidence written only into
    visual_descriptors never reaches a downstream system."""
    assert "structured" in prompt.lower()
    assert "visual_descriptors and nowhere else is lost" in prompt


def test_the_prompt_no_longer_invites_omission(prompt):
    """The old wording told the model to leave fields out, and it obliged on
    frame_finish 8 times out of 8."""
    assert "leave a field out otherwise" not in prompt
    assert "empty is a correct" in prompt.lower()


def test_the_prompt_keeps_material_and_upholstery_distinct(prompt):
    assert "NOT the same field as material" in prompt


# -- the frame fix, which is the point of the phase -------------------------

def test_the_prompt_routes_part_evidence_into_frame_finish(prompt):
    for part in ("frame", "armrest", "leg", "base", "trim", "accent trim"):
        assert part in prompt
    assert "Do not leave it only in visual_descriptors" in prompt


def test_the_prompt_inspects_the_piece_in_parts(prompt):
    assert "INSPECT THE PIECE IN PARTS" in prompt
    for step in ("the main body", "the upholstered areas", "the structural frame",
                 "the legs or base", "the trim and accent regions"):
        assert step in prompt


@pytest.mark.parametrize("phrase,expected", [
    ("wooden frame", "wood"),
    ("wooden armrests", "wood"),
    ("black metal frame", "black metal"),
    ("gold metal trim", "gold metal"),
    ("brass trim", "brass"),
    ("blackened metal base", "blackened metal"),
])
def test_the_prompt_shows_the_routing_with_worked_examples(phrase, expected, prompt):
    assert f"'{phrase}'" in prompt
    assert f"frame_finish: '{expected}'" in prompt


# -- asking harder must not invent -----------------------------------------

def test_the_prompt_says_many_pieces_have_no_frame_at_all(prompt):
    """Four of the eight measured references are mattresses. Without this,
    a frame-hunting prompt has every reason to invent four frames."""
    assert "no visible frame at all" in prompt
    assert "mattress" in prompt
    assert "Never assume a frame exists" in prompt


def test_the_prompt_forbids_inventing_a_hex_from_a_colour_word(prompt):
    """P14 found no authoritative word-to-hex mapping in the repository, so
    there is nothing a hex could honestly be derived from."""
    assert "Do NOT convert a colour word into a hex value" in prompt
    assert "never a hex code" in prompt


def test_the_prompt_forbids_guessing_a_wood_species(prompt):
    """Generic wood grain is 'wood'. 'Walnut' is a claim the pixels rarely
    support, and it would pick a different registry material."""
    assert "Say what you can see, not what you can identify" in prompt
    assert "only if the image truly shows that species" in prompt


def test_the_prompt_restricts_pattern_to_something_actually_visible(prompt):
    assert "ONLY an actually visible pattern" in prompt
    assert "Not a style, not a mood" in prompt


@pytest.mark.parametrize("word", ["luxurious", "premium", "elegant", "warm", "contemporary"])
def test_an_ambiguous_word_still_resolves_to_no_material(word):
    """Whatever the model returns, an evaluative word must never become a
    registry material. The resolver is the guard and P15 does not touch it."""
    assert finish_material_for(word) == ""
    assert _descriptor_finish([word]) == ("", "")


@pytest.mark.parametrize("phrase", [
    "glass coffee table",   # whole object, not its trim
    "walnut",               # a material naming no part
    "luxurious sofa",
    "premium chair",
])
def test_p14_descriptor_promotion_is_not_broadened_by_p15(phrase):
    assert _descriptor_finish([phrase]) == ("", "")


# -- the two layers must compose in the documented order --------------------

def _obj(**visual) -> SceneObject:
    return SceneObject(semantic_type="sofa", room_id="r1", position=(0.0, 0.0, 0.0),
                       dimensions=(2.0, 0.8, 0.9), visual=ObjectVisual(**visual))


def test_an_explicitly_extracted_frame_finish_wins_over_a_descriptor():
    """P15 makes explicit extraction common; P14's fallback stays for the rest.
    Priority: explicit, then descriptor, then nothing."""
    entry = _finish_entry(_obj(frame_finish="gold metal trim",
                               descriptors=["wooden frame"]))
    assert entry["source"] == "stated"
    assert entry["frame_material"] == "metal_brass"


def test_the_descriptor_fallback_still_fires_when_extraction_is_empty():
    entry = _finish_entry(_obj(frame_finish="", descriptors=["wooden frame"]))
    assert entry["source"] == "descriptor"
    assert entry["frame_material"] == "veneer_oak"


def test_no_frame_evidence_anywhere_stays_empty():
    entry = _finish_entry(_obj(upholstery="quilted knit", pattern="quilted"))
    assert entry["source"] == ""
    assert entry["frame_material"] == ""


@pytest.mark.parametrize("extracted,expected", [
    ("gold metal trim", "metal_brass"),
    ("brass", "metal_brass"),
    ("black metal", "metal_black"),
    ("blackened metal", "metal_black"),
    ("dark wood", "veneer_oak"),
    ("wood", "veneer_oak"),
])
def test_the_values_p15_actually_extracts_resolve_through_the_p14_resolver(extracted, expected):
    """Measured outputs from the live run, checked against the resolver they
    have to pass through. A value the resolver drops renders nothing."""
    assert finish_material_for(extracted) == expected

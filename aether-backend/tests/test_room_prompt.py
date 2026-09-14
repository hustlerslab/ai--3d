"""The intelligence layer writes each room's image prompt.

Previously a keyword template joined a furniture list and style tags with
commas. The composed version reads as a sentence and carries the client's own
materials ("deep blue fabric upholstered sofa") rather than the bare type.

Two invariants matter more than the prose: it must never reach into another
room, and it must never be allowed to exceed CLIP's window — a prompt CLIP
truncates loses whatever is at the end, which is where the framing lives.
"""
from __future__ import annotations

import pytest

from app.intelligence.prompts import (
    ROOM_PROMPT_MAX_TOKENS,
    compose_room_prompt,
    room_prompt_request,
    scene_prompt_sd,
)
from app.intelligence.schema import DesignAnalysis, InputBundle, RoomAnalysis, SpottedObject, StyleSpec


def _analysis() -> DesignAnalysis:
    return DesignAnalysis(
        intent="a calm family home",
        rooms=[
            RoomAnalysis(room_id="living_room", name="Living Room", type="living_room", width_m=5.8, length_m=4.5),
            RoomAnalysis(room_id="bedroom", name="Bedroom", type="bedroom", width_m=4.0, length_m=3.6),
        ],
        spotted_objects=[
            SpottedObject(object_id="it_a", semantic_type="sofa", name="deep blue velvet sofa",
                          room_id="living_room", image_index=0, material="velvet", color="#20629A"),
            SpottedObject(object_id="it_b", semantic_type="bed", name="grey orthopedic mattress",
                          room_id="bedroom", image_index=1, material="fabric"),
            SpottedObject(object_id="it_c", semantic_type="sofa", name="shop display sofa",
                          room_id="living_room", image_index=2, role="reference"),
        ],
    )


_STYLE = StyleSpec(name="warm_modern", tags=["modern", "warm"], materials=["wood_oak", "paint_white"])
_BUNDLE = InputBundle(project_id="p", description="a calm family home")


def test_the_request_carries_only_this_rooms_pieces(env):
    a = _analysis()
    living = room_prompt_request(a, _STYLE, _BUNDLE, a.rooms[0])
    bedroom = room_prompt_request(a, _STYLE, _BUNDLE, a.rooms[1])

    assert "deep blue velvet sofa" in living
    assert "orthopedic mattress" not in living, "the bedroom's piece leaked into the living room"
    assert "orthopedic mattress" in bedroom
    assert "deep blue velvet sofa" not in bedroom, "the living room's piece leaked into the bedroom"
    # a reference piece is a shop photo, not furniture the client owns
    assert "shop display sofa" not in living


def test_a_provider_without_the_capability_falls_back_to_the_template(env):
    """The Protocol is pinned to three methods (ADR-001). A vendor provider that
    implements only those must still produce a prompt."""
    class OldProvider:                       # no compose_scene_prompt at all
        pass

    a = _analysis()
    prompt, source = compose_room_prompt(OldProvider(), a, _STYLE, _BUNDLE, a.rooms[0])
    assert source == "template"
    assert prompt == scene_prompt_sd(a, _STYLE, _BUNDLE, room=a.rooms[0])


@pytest.mark.parametrize("returned", ["", "   ", "word " * 400])
def test_an_empty_or_over_long_answer_falls_back_rather_than_shipping(env, returned):
    """CLIP silently truncates past 77 tokens, so an over-long prompt loses its
    framing without erroring. Falling back is the safe answer, not clipping."""
    class Chatty:
        def compose_scene_prompt(self, analysis, style, bundle, room):
            return returned

    a = _analysis()
    prompt, source = compose_room_prompt(Chatty(), a, _STYLE, _BUNDLE, a.rooms[0])
    assert source == "template", f"shipped a bad prompt: {prompt[:60]!r}"


def test_a_provider_that_raises_does_not_sink_the_room(env):
    class Broken:
        def compose_scene_prompt(self, analysis, style, bundle, room):
            raise RuntimeError("quota")

    a = _analysis()
    prompt, source = compose_room_prompt(Broken(), a, _STYLE, _BUNDLE, a.rooms[0])
    assert source == "template" and prompt


def test_the_budget_is_measured_with_clip_not_guessed(env):
    """The word-based estimate over-counted real prompts by 6-20 % — it scored
    the keyword template at 81 against a true 70, and rejected composed prompts
    that fit. An over-count is not the safe direction: it silently discards good
    work. Measure with the tokenizer that actually does the truncating."""
    from app.intelligence.prompts import CLIP_WINDOW, _clip_tokens_estimate, clip_tokens

    template = scene_prompt_sd(_analysis(), _STYLE, _BUNDLE, room=_analysis().rooms[0])
    real = clip_tokens(template)
    assert real <= CLIP_WINDOW, f"our own template overflows CLIP at {real}"
    if _clip_tokens_estimate(template) != real:
        assert _clip_tokens_estimate(template) > real, "the estimate was meant to be the pessimistic one"


def test_a_usable_answer_is_used_and_labelled(env):
    good = ("wide interior shot of a warm modern living room with a deep blue velvet sofa, "
            "oak coffee table and linen rug, white walls, warm daylight")

    class Good:
        def compose_scene_prompt(self, analysis, style, bundle, room):
            return good

    from app.intelligence.prompts import FRAMING_TAIL

    a = _analysis()
    prompt, source = compose_room_prompt(Good(), a, _STYLE, _BUNDLE, a.rooms[0])
    assert source == "llm"
    assert good.rstrip(" .,") in prompt, "the model's words must survive"
    # The framing is ours and is appended verbatim: asked to write it itself the
    # model produced "wide angle interior render" and the bathroom came back as
    # a close-up of the bathtub.
    assert prompt.endswith(FRAMING_TAIL), prompt
    assert ROOM_PROMPT_MAX_TOKENS < 77, "the budget must leave CLIP headroom"


def test_every_composed_prompt_carries_the_framing_clause(env):
    """Whatever the model returns, the render must still be told to stand back."""
    from app.intelligence.prompts import FRAMING_TAIL

    class Terse:
        def compose_scene_prompt(self, analysis, style, bundle, room):
            return "a warm minimal bathroom with an oak vanity, a toilet and a walk-in shower"

    a = _analysis()
    prompt, source = compose_room_prompt(Terse(), a, _STYLE, _BUNDLE, a.rooms[0])
    assert source == "llm" and prompt.endswith(FRAMING_TAIL)


def test_a_bathroom_is_offered_fixtures_the_planner_has_no_type_for(env):
    """SEMANTIC_TYPES has no toilet, basin or shower, so ROOM_SETS cannot offer
    them and the prompt named only vanity, mirror and bathtub — which rendered
    as a tub in an alcove. The picture may show fixtures nothing will place."""
    from app.intelligence.prompts import PICTURE_ONLY_FIXTURES, room_prompt_request
    from app.intelligence.schema import RoomAnalysis

    bathroom = RoomAnalysis(room_id="bathroom", name="Bathroom", type="bathroom",
                            width_m=2.5, length_m=2.0)
    a = _analysis()
    a.rooms.append(bathroom)
    request = room_prompt_request(a, _STYLE, _BUNDLE, bathroom)
    for fixture in ("toilet", "shower"):
        assert fixture in request, f"{fixture} was never offered to the model"
    # and a room with no such gap is unaffected
    assert "toilet" not in room_prompt_request(a, _STYLE, _BUNDLE, a.rooms[0])
    assert "living_room" not in PICTURE_ONLY_FIXTURES

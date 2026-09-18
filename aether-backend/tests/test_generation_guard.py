"""The guard between a local model and the pipeline.

Phase 0e made a looped generation *recoverable*. It still cost ~190s, and
salvage happily preserved a hallucination - a freestanding bath read into a
living room. This covers the two things that fixes: stopping the loop while it
is still happening, and saying so when an element cannot belong to its room.

Everything here runs without a GPU, without Ollama and without a network. The
loop cases replay two REAL captured failures committed under tests/fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.intelligence.ollama_provider import (
    REPEAT_THRESHOLD, GenerationStatus, OllamaProvider, OllamaTruncated,
    RepetitionDetector, salvage_elements)
from app.intelligence.scene_reading import flag_implausible
from app.intelligence.schema import SceneElement, SceneReading, StyleSpec

FIXTURES = Path(__file__).parent / "fixtures"


class _Room:
    room_id = name = "living_room"
    type = "living_room"
    width_m, length_m = 5.0, 4.0


def _png(tmp_path):
    path = tmp_path / "room.png"
    Image.new("RGB", (704, 448), (200, 190, 180)).save(path)
    return path


def _element(semantic_type, room_id, check="ok"):
    return SceneElement(room_id=room_id, semantic_type=semantic_type, name=semantic_type,
                        check=check, bbox=(0.1, 0.1, 0.4, 0.4), crop_ref="x.png")


# ── the detector: loops caught, real furniture left alone ────────────────

def test_a_real_captured_loop_is_caught_before_the_answer_ends():
    """The scene read that cost 190s. Every distinct element must already have
    arrived by the time the abort fires, or the guard destroys content."""
    text = (FIXTURES / "truncated_scene_read.txt").read_text(encoding="utf-8")
    detector = RepetitionDetector(key="elements")
    fired_at = None
    for i in range(0, len(text), 37):                 # arbitrary chunking, like a stream
        if detector.feed(text[i:i + 37]):
            fired_at = i + 37
            break
    assert fired_at is not None, "the loop must be detected"
    assert fired_at < len(text) * 0.2, "must fire early enough to be worth doing"
    assert len(detector.seen) == len(salvage_elements(text)), \
        "aborting must not cost a single distinct element"


def test_the_object_plan_loop_is_caught_too():
    text = (FIXTURES / "truncated_object_plan.txt").read_text(encoding="utf-8")
    detector = RepetitionDetector(key="items")
    assert any(detector.feed(text[i:i + 53]) for i in range(0, len(text), 53))
    assert len(detector.seen) == len(salvage_elements(text, key="items"))


def test_three_chairs_at_different_places_are_three_chairs():
    """The failure this guard must never cause. Legitimate repeats differ by
    box; only a byte-identical repeat is pathological."""
    detector = RepetitionDetector()
    body = '{"elements": [' + ",".join(
        '{"semantic_type": "chair", "bbox": [%d, 0, %d, 50]}' % (x, x + 40)
        for x in (0, 100, 200)) + "]}"
    assert detector.feed(body) is False
    assert len(detector.seen) == 3


def test_the_same_piece_repeated_is_one_piece():
    detector = RepetitionDetector()
    one = '{"semantic_type": "rug", "bbox": [2, 422, 1125, 728]}'
    assert detector.feed('{"elements": [' + ",".join([one] * 30) + "]}") is True
    assert len(detector.seen) == 1
    assert detector.repeated[1] >= REPEAT_THRESHOLD


def test_the_detector_ignores_the_documents_own_braces():
    """The bug that cost a probe run: the outer `{` is depth 1, so naive brace
    counting only closes at the very end and never sees an element at all."""
    detector = RepetitionDetector()
    detector.feed('{"provider": "ollama", "elements": '
                  '[{"semantic_type": "bed", "bbox": [0,0,9,9]}]}')
    assert len(detector.seen) == 1, "the wrapper object must not count as an element"


# ── the other shape the loop takes: one string that never closes ─────────

def test_a_runaway_string_is_caught_even_with_no_array_to_watch():
    """`create_style_spec` returned 40,962 characters in which `tags`,
    `palette` and `materials` each appeared exactly once - not a repeated
    object, a single string opened at character 294 that never closed. The
    object counter is blind to it, so the detector watches strings too."""
    from app.intelligence.ollama_provider import MAX_STRING_CHARS

    detector = RepetitionDetector(key=None)
    assert detector.feed('{"wall_material": "' + "seamlessly today " * 200 + '"}') is True
    assert detector.runaway_string is True
    assert MAX_STRING_CHARS >= 1000, "must leave room for a real sentence"


def test_an_ordinary_long_note_is_not_a_runaway():
    """The guard must not fire on a style note someone actually wrote."""
    detector = RepetitionDetector()
    body = ('{"elements": [{"semantic_type": "sofa", "bbox": [1,2,3,4], '
            '"style_notes": "' + "a tasteful note. " * 20 + '"}]}')
    assert detector.feed(body) is False


def test_escaped_quotes_do_not_confuse_the_string_watcher():
    detector = RepetitionDetector(key=None)
    assert detector.feed('{"note": "he said \\"hello\\" and left"}') is False


# ── generation status: never collapsed into worked/failed ────────────────

def _responds(content, done_reason="stop"):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": content},
                                         "done": True, "done_reason": done_reason})
    return handler


def _provider(handler):
    return OllamaProvider(transport=httpx.MockTransport(handler))


GOOD = json.dumps({"elements": [{"name": "sofa", "semantic_type": "sofa",
                                 "bbox": [100, 200, 400, 500]}], "surfaces": {}})


def test_a_clean_answer_is_complete(tmp_path):
    out = _provider(_responds(GOOD)).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert out.get("_status") is None, "a clean read carries no caveat"
    assert len(out["elements"]) == 1


def test_a_capped_answer_is_not_called_complete(tmp_path):
    """It parsed, so the old code called it a success. It is still an answer
    that ran out of room, and the reviewer should be told."""
    out = _provider(_responds(GOOD, done_reason="length")).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert out["_status"] == GenerationStatus.LENGTH_LIMIT.value
    assert out["_warnings"]


def test_an_empty_room_is_a_valid_answer_not_a_failure(tmp_path):
    out = _provider(_responds('{"elements": [], "surfaces": {}}')).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert out["elements"] == []
    assert out.get("_status") is None


def test_a_loop_reaching_the_provider_is_reported_as_repetition(tmp_path):
    looped = ('{"elements": [' + ",".join(
        ['{"semantic_type": "rug", "bbox": [2, 422, 1125, 728]}'] * 30)
        + ',{"semantic_type": "ru')
    out = _provider(_responds(looped, done_reason="length")).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert out["_status"] == GenerationStatus.REPETITION_SUSPECTED.value
    assert len(out["elements"]) == 1, "thirty copies of one rug are one rug"


def test_a_loop_with_nothing_complete_still_raises(tmp_path):
    with pytest.raises(OllamaTruncated):
        _provider(_responds('{"elements": [{"seman', done_reason="length")).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")


# ── plausibility: flagged, never deleted ─────────────────────────────────

ROOMS = {"living_room": "living_room", "master_bedroom": "master_bedroom",
         "kitchen": "kitchen", "bathroom": "bathroom"}


def test_the_bath_in_the_living_room_is_flagged_not_removed():
    """The observed hallucination. It must survive as an element so a human can
    overrule the flag - unusual designs exist."""
    reading = SceneReading(elements=[_element("bathtub", "living_room")])
    assert flag_implausible(reading, ROOMS) == 1
    assert len(reading.elements) == 1, "nothing may be deleted"
    assert reading.elements[0].check == "implausible"
    assert "bathroom" in reading.elements[0].check_note


def test_ordinary_furniture_in_any_room_is_never_flagged():
    """The false-positive case that ruled OBJECT_DEFAULT_ROOM out: it maps rug
    and plant to the living room, and the sample bedroom render has a rug."""
    reading = SceneReading(elements=[
        _element("rug", "master_bedroom"), _element("plant", "kitchen"),
        _element("mirror", "living_room"), _element("wall_art", "bathroom"),
        _element("side_table", "kitchen"), _element("pillows", "living_room")])
    assert flag_implausible(reading, ROOMS) == 0
    assert {e.check for e in reading.elements} == {"ok"}


def test_a_piece_in_its_own_room_is_silent():
    reading = SceneReading(elements=[
        _element("bathtub", "bathroom"), _element("bed", "master_bedroom"),
        _element("kitchen_counter", "kitchen")])
    assert flag_implausible(reading, ROOMS) == 0


def test_the_picture_outranks_the_label():
    """`mismatch` came from looking at the crop; this pass only reads the name.
    Where they disagree, the one that looked at pixels keeps its verdict."""
    reading = SceneReading(elements=[_element("bathtub", "living_room", check="mismatch")])
    assert flag_implausible(reading, ROOMS) == 0
    assert reading.elements[0].check == "mismatch"


def test_no_room_known_means_no_suspicion():
    reading = SceneReading(elements=[_element("bathtub", "")])
    assert flag_implausible(reading, {}) == 0, "with no room to judge against, say nothing"

"""The local provider can read an approved render.

Before this, `OllamaProvider` had no `read_scene_elements` at all. `scene_plan`
looks that method up with `getattr` and skips the read when it is absent, so a
local-only install produced an EMPTY SceneReading for every project: no crops,
no review, no meshes - and the only symptom was one line in the job feed saying
"the reader returned nothing", which is also what an empty room looks like.

These run without Ollama, without a GPU and without a network: the provider
takes an httpx transport, so the model is a fake that answers from memory.
"""
from __future__ import annotations

import json

import httpx
import pytest
from PIL import Image

from app.intelligence.mock_provider import MockProvider
from app.intelligence.ollama_provider import OllamaError, OllamaProvider
from app.intelligence.provider import ResilientProvider
from app.intelligence.schema import StyleSpec

ANSWER = {
    "elements": [
        {"name": "striped teal sofa", "semantic_type": "sofa",
         "bbox": [100, 200, 400, 500], "material": "fabric", "color": "#2E8B9A",
         "placement": "floor", "against": "the window", "faces": "into the room",
         "confidence": 0.8},
        {"name": "woven jute rug", "semantic_type": "rug",
         "bbox": [50, 600, 900, 950], "material": "jute", "color": "#C8B89A",
         "placement": "floor", "against": "", "faces": "", "confidence": 0.7},
    ],
    "surfaces": {"wall_color": "#EFE9DF", "wall_material": "plaster",
                 "floor_color": "#8B6F47", "floor_material": "oak"},
}


class _Room:
    room_id = name = "living_room"
    type = "living_room"
    width_m, length_m = 5.0, 4.0


def _png(tmp_path):
    path = tmp_path / "moodboard_room_living_room.png"
    Image.new("RGB", (704, 448), (200, 190, 180)).save(path)
    return path


def _provider(handler) -> OllamaProvider:
    return OllamaProvider(transport=httpx.MockTransport(handler))


def _ok(payload: dict):
    """A fake Ollama that records the request it was given."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(payload)}})

    return handler, seen


# ── the capability exists at all ─────────────────────────────────────────

def test_the_local_provider_can_read_renders():
    """The regression: this attribute simply did not exist, and `scene_plan`
    silently skips the read when it is missing."""
    assert callable(getattr(OllamaProvider, "read_scene_elements", None))


def test_it_matches_the_gemini_signature_so_scene_plan_cannot_tell_them_apart():
    import inspect

    from app.intelligence.gemini_provider import GeminiProvider

    mine = list(inspect.signature(OllamaProvider.read_scene_elements).parameters)
    theirs = list(inspect.signature(GeminiProvider.read_scene_elements).parameters)
    assert mine == theirs == ["self", "image", "room", "style", "vertical"]


# ── the happy path ───────────────────────────────────────────────────────

def test_a_valid_answer_comes_back_as_the_raw_dict(tmp_path):
    handler, _ = _ok(ANSWER)
    out = _provider(handler).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S", tags=["modern"]), "residential")
    assert [e["semantic_type"] for e in out["elements"]] == ["sofa", "rug"]
    assert out["surfaces"]["floor_material"] == "oak"


def test_it_sends_the_image_and_the_existing_prompt(tmp_path):
    """Phase 0a rewrote `scene_reading_prompt` to demand NAMED targets rather
    than 'left'/'front'. A second prompt written here would quietly undo that,
    so this pins that the path uses the shared one."""
    handler, seen = _ok(ANSWER)
    _provider(handler).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S", tags=["modern"]), "residential")

    message = seen["messages"][0]
    assert message["images"], "the render must reach the model"
    assert "NAME the piece of furniture this one backs onto" in message["content"]
    assert "NAME the piece this one is turned towards" in message["content"]
    # Measured in phase 1b: offering "into the room" beside the specific answer
    # made the model take it 10 times out of 14 and name a piece zero times.
    assert "ONLY if it faces no particular piece" in message["content"]
    assert "FLOOR IS NOT AN ANSWER" in message["content"]
    assert "WHOLE NUMBERS out of 1000" in message["content"]
    assert seen["format"], "output must stay schema-constrained"


def test_the_render_is_downscaled_for_its_own_budget():
    """One render can afford more pixels than eight reference photos, and box
    quality needs them - but the encoder itself is the existing one."""
    from app.core.config import get_settings

    s = get_settings()
    assert s.ollama_scene_image_max_px > s.ollama_image_max_px


# ── failures are reported, never mistaken for an empty room ──────────────

def test_a_non_json_answer_raises_rather_than_returning_nothing(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "I cannot see the image."}})

    with pytest.raises(OllamaError):
        _provider(handler).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")


def test_an_empty_answer_raises(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "   "}})

    with pytest.raises(OllamaError):
        _provider(handler).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")


def test_a_missing_model_says_so(tmp_path):
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(OllamaError, match="not pulled"):
        _provider(handler).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")


def test_fenced_json_is_salvaged_not_thrown_away(tmp_path):
    """A small model wraps its answer in prose often enough that discarding a
    whole GPU-minute over it is the wrong trade."""
    def handler(request):
        return httpx.Response(200, json={"message": {
            "content": "Here you go:\n```json\n" + json.dumps(ANSWER) + "\n```"}})

    out = _provider(handler).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert len(out["elements"]) == 2


# ── the wrapper tells failure apart from emptiness ───────────────────────

class _Broken:
    label = name = "broken"

    def read_scene_elements(self, image, room, style, vertical):
        raise RuntimeError("model timed out")


class _Deaf:
    """A provider with no reader at all - the exact shape of this whole bug."""

    label = name = "deaf"


def test_a_failed_read_is_reported_as_an_error_not_as_emptiness():
    out = ResilientProvider(_Broken(), MockProvider(), True).read_scene_elements(
        "x.png", _Room(), StyleSpec(name="S"), "residential")
    assert "model timed out" in out["_error"]


def test_a_provider_that_cannot_read_says_so_instead_of_going_quiet():
    out = ResilientProvider(_Deaf(), MockProvider(), True).read_scene_elements(
        "x.png", _Room(), StyleSpec(name="S"), "residential")
    assert "cannot read renders" in out["_error"]


def test_the_error_key_never_reaches_the_element_list():
    """`coerce_room_reading` reads `elements` and `surfaces`; `_error` exists
    only for the warning an operator sees."""
    from app.intelligence.scene_reading import coerce_room_reading

    warnings: list[str] = []
    elements, _surfaces = coerce_room_reading(
        {"_error": "boom"}, _Room(), "residential", warnings)
    assert elements == []


# ── truncation: a loop, not a long answer ────────────────────────────────
#
# Measured on qwen2.5vl:3b, 1 read in 3 on one image: the model repeats the
# elements it already found until the token cap, then the array never closes.
# One real failure carried 141 element objects of which 7 were distinct, in
# 21,494 characters. Raising num_predict buys a longer loop; a repeat_penalty
# high enough to break it cut legitimate output from 11 elements to 2. So the
# recovery is here, on the text.

LOOPED = ('{"elements": [' + ",".join(
    ['{"name": "rug", "semantic_type": "rug", "bbox": [2, 422, 1125, 728]},'
     '{"name": "tv", "semantic_type": "tv", "bbox": [743, 125, 1064, 328]}'] * 20)
    + ',{"name": "rug", "semantic_type": "rug", "bbox": [2, 4')   # cut mid-object


def _truncated(request):
    return httpx.Response(200, json={"message": {"content": LOOPED},
                                     "done_reason": "length"})


def test_a_looped_read_is_recovered_instead_of_lost(tmp_path):
    out = _provider(_truncated).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    types = [e["semantic_type"] for e in out["elements"]]
    assert types == ["rug", "tv"], "40 repeats of two pieces are two pieces"
    assert out["_warnings"], "recovery must be said out loud, not hidden"


def test_truncation_is_its_own_error_not_a_json_failure():
    from app.intelligence.ollama_provider import OllamaInvalidJSON, OllamaTruncated

    assert OllamaTruncated.code == "TRUNCATED_OUTPUT"
    assert OllamaInvalidJSON.code == "JSON_FAILURE"
    assert issubclass(OllamaTruncated, OllamaError), "existing handlers must still catch it"


def test_a_truncated_answer_with_nothing_recoverable_still_raises(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": '{"elements": [{"na'},
                                         "done_reason": "length"})

    from app.intelligence.ollama_provider import OllamaTruncated

    with pytest.raises(OllamaTruncated):
        _provider(handler).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")


def test_an_unreachable_ollama_is_its_own_code(tmp_path):
    from app.intelligence.ollama_provider import OllamaUnavailable

    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(OllamaUnavailable) as caught:
        _provider(handler).read_scene_elements(
            _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert caught.value.code == "OLLAMA_UNAVAILABLE"


def test_salvage_keeps_two_real_sofas_apart():
    """Dedupe is on (type, bbox). Two sofas at DIFFERENT boxes are two sofas -
    the position-based lesson from the shape-key work, applied here."""
    from app.intelligence.ollama_provider import salvage_elements

    text = ('{"elements": [{"semantic_type": "sofa", "bbox": [0, 0, 10, 10]},'
            '{"semantic_type": "sofa", "bbox": [90, 0, 99, 10]},'
            '{"semantic_type": "sofa", "bbox": [0, 0, 10, 10]},'
            '{"semantic_type": "so')
    assert len(salvage_elements(text)) == 2


def test_an_empty_room_is_not_a_failure(tmp_path):
    """`{"elements": []}` means the model looked and saw nothing worth boxing.
    That is a valid answer and must not be dressed up as an error."""
    def handler(request):
        return httpx.Response(200, json={"message": {
            "content": '{"elements": [], "surfaces": {}}'}, "done_reason": "stop"})

    out = _provider(handler).read_scene_elements(
        _png(tmp_path), _Room(), StyleSpec(name="S"), "residential")
    assert out["elements"] == []


# ── one optional integration test ────────────────────────────────────────

def _ollama_up() -> bool:
    try:
        return httpx.get("http://127.0.0.1:11434/api/tags", timeout=2).status_code == 200
    except Exception:                                          # noqa: BLE001
        return False


@pytest.mark.skipif(not _ollama_up(), reason="Ollama is not running on :11434")
def test_a_real_render_reads_into_real_elements():
    """The whole point of the phase, against the live model. Skipped, never
    failed, when Ollama is not there."""
    from pathlib import Path

    render = Path("data/projects/proj_553cb09794/analysis/moodboard_room_living_room.png")
    if not render.is_file():
        pytest.skip("no sample render on this machine")

    out = OllamaProvider().read_scene_elements(
        render, _Room(), StyleSpec(name="S", tags=["modern"]), "residential")
    assert out.get("elements"), "the live model read nothing out of a real render"
    for element in out["elements"]:
        assert element.get("bbox"), "every element needs a box or it cannot be cropped"

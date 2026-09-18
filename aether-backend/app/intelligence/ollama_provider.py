"""Ollama provider — the reasoning stages on a local model, no API key.

Implements the same IntelligenceProvider Protocol as Gemini and Claude, so
selecting it is one env var (INTELLIGENCE_PROVIDER=ollama) and nothing else in
the pipeline changes. Output goes through the same coerce_* functions, so a
weaker model degrades into a poorer plan rather than a broken one.

Two things differ from the cloud providers, and both matter:

1. This model runs on the SAME GPU as Blender. The job runner reroutes the
   stages that call it onto the render lane when a local provider is selected,
   so an analysis and a render never contend for the 6 GB — see
   JobRunner._lane_for.
2. Ollama constrains output with a JSON Schema passed as `format`, not with a
   vendor-specific responseSchema. The schemas here are the same plain JSON
   Schema the other providers use, minus `additionalProperties`, which some
   Ollama builds reject.

API shape (Ollama 0.34):
  POST /api/chat {model, messages:[{role, content, images:[<base64>]}],
                  format:<json schema>, stream:false,
                  options:{temperature, num_ctx}}
    → {"message":{"content":"<json text>"}, "done":true, ...}
"""
from __future__ import annotations

import base64
import io
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

from ..core.config import Settings, get_settings
from ..materials.registry import get_material_registry
from .coerce import coerce_analysis, coerce_object_plan, coerce_style
from .prompts import (
    OBJECT_PLAN_SCHEMA,
    analysis_prompt,
    analysis_schema,
    objects_prompt,
    style_prompt,
    style_schema,
)
from .schema import DesignAnalysis, InputBundle, ObjectPlan, StyleSpec

log = logging.getLogger("aether.intelligence.ollama")


class GenerationStatus(str, Enum):
    """Why a generation ended. Never collapsed into "it worked / it didn't".

    An answer that hit the token cap, an answer recovered from a loop and a
    clean answer are three different things with three different follow-ups,
    and a reviewer deciding whether to spend credits on the result deserves to
    know which one they are looking at.
    """

    COMPLETE = "complete"                            # ran to a natural stop
    LENGTH_LIMIT = "length_limit"                    # done_reason == "length"
    REPETITION_SUSPECTED = "repetition_suspected"    # detector cut it short
    SALVAGED = "salvaged"                            # recovered from partial text
    PARTIAL_JSON = "partial_json"
    FAILED = "failed"


class OllamaError(Exception):
    """Base for every local-provider failure. Carries a code so a caller can
    tell an empty room from an outage without parsing prose."""

    code = "MODEL_FAILURE"


class OllamaUnavailable(OllamaError):
    code = "OLLAMA_UNAVAILABLE"


class OllamaInvalidJSON(OllamaError):
    code = "JSON_FAILURE"


class OllamaTruncated(OllamaError):
    """The token cap cut the answer off mid-structure.

    Distinct from JSON_FAILURE because the partial text usually still contains
    every element the model actually saw - see `salvage_elements`.
    """

    code = "TRUNCATED_OUTPUT"

    def __init__(self, message: str, partial: str = ""):
        super().__init__(message)
        self.partial = partial


#: How many byte-identical objects before a generation is a loop, not an answer.
#: MEASURED, not chosen - research/phase0f_threshold.py replays two real captured
#: failures: at 2 the abort fires before the 7th distinct element has arrived and
#: loses it; at 3 nothing is lost on either case, and the abort lands 7.3% into
#: the scene read and 34.1% into the object plan. Three legitimate bar stools
#: have three different boxes, so three fingerprints, so this never fires on
#: them. Raising it only costs time; lowering it costs content.
REPEAT_THRESHOLD = 3

#: One JSON string longer than this is runaway generation, not a value. The
#: longest legitimate field here is a style note of a sentence or two, and
#: `_phrase()` already truncates surface descriptions at 120 characters after a
#: bathroom returned 39,640. Measured: a `create_style_spec` failure ran a
#: single unterminated string to 40,962 characters.
MAX_STRING_CHARS = 1000

#: Total attempts per call. ONE - retrying was tried and MEASURED WORSE.
#:
#: The idea was reasonable: once the guard made a runaway `create_style_spec`
#: fail in 8s rather than 194s, a second attempt looked like cheap upside, since
#: it succeeded about 1 run in 5. Measured over 5 runs each way it went the
#: other direction - 1/5 success became 0/5, and mean latency 7.4s became 53.1s
#: because one retry ran to the full token cap at 196.9s.
#:
#: The premise was wrong: these failures are not independent draws. This prompt
#: and this model run away together, so asking again mostly buys another runaway.
#: Left as a parameter, set to 1, so the finding is on the record rather than
#: rediscovered.
MAX_ATTEMPTS = 1


class RepetitionDetector:
    """Spots the element loop while the answer is still arriving.

    Feeds on streamed text and answers one question: has the model started
    repeating objects it already emitted? Deliberately NOT substring matching -
    a healthy response repeats `"semantic_type":` on every element, so raw text
    similarity flags good answers. It counts complete OBJECTS instead, using the
    same fingerprint `salvage_elements` dedupes on.

    The subtlety that cost a probe run: the document's own outer `{` is depth 1,
    so naive brace counting only closes at the very end and never sees an
    element at all. Counting starts after the array opens.
    """

    def __init__(self, key: Optional[str] = "elements", threshold: int = REPEAT_THRESHOLD,
                 max_string: int = MAX_STRING_CHARS):
        self._key = key
        self._threshold = threshold
        self._max_string = max_string
        self._armed = key is None          # no array to wait for: watch strings only
        self._depth = 0
        self._buf = ""
        self._pending = ""
        self._counts: dict = {}
        # String-runaway state. Tracked over the WHOLE response, not just inside
        # the array, because the runaway that motivated it was a `wall_material`
        # field in `surfaces`.
        self._in_string = False
        self._escaped = False
        self._string_len = 0
        self.seen: set = set()
        self.repeated: Optional[tuple] = None
        self.runaway_string: bool = False

    def _watch_strings(self, piece: str) -> bool:
        """True once one JSON string has run far past any sane field length.

        The second shape this model's looping takes, and invisible to the object
        counter above: `create_style_spec` returned 40,962 characters in which
        `tags`, `palette` and `materials` each appear exactly once - a single
        string that opened at character 294 and never closed. The same failure
        put 39,640 characters of filler into a bathroom's `wall_material`, which
        is why `_phrase()` truncates. Catching it here stops it three minutes
        earlier, and the cap is ~8x the longest field anyone would write.
        """
        for ch in piece:
            if self._escaped:
                self._escaped = False
                self._string_len += 1
                continue
            if ch == "\\" and self._in_string:
                self._escaped = True
                continue
            if ch == '"':
                self._in_string = not self._in_string
                self._string_len = 0
                continue
            if self._in_string:
                self._string_len += 1
                if self._string_len > self._max_string:
                    self.runaway_string = True
                    return True
        return False

    @property
    def looping(self) -> bool:
        return self.repeated is not None

    def feed(self, piece: str) -> bool:
        """Consume streamed text. True once a loop is certain."""
        if self._watch_strings(piece):
            return True
        if self._key is None:
            return False
        if not self._armed:
            self._pending += piece
            marker = self._pending.find(f'"{self._key}"')
            if marker < 0:
                self._pending = self._pending[-200:]      # keep a small overlap
                return False
            opening = self._pending.find("[", marker)
            if opening < 0:
                return False
            self._armed = True
            piece = self._pending[opening + 1:]
            self._pending = ""

        for ch in piece:
            if ch == "{":
                self._depth += 1
            if self._depth:
                self._buf += ch
            if ch == "}":
                self._depth -= 1
                if self._depth == 0:
                    raw, self._buf = self._buf, ""
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    fingerprint = (obj.get("object_key")
                                   or (obj.get("semantic_type"), json.dumps(obj.get("bbox"))))
                    self.seen.add(fingerprint)
                    self._counts[fingerprint] = self._counts.get(fingerprint, 0) + 1
                    if self._counts[fingerprint] >= self._threshold:
                        self.repeated = (fingerprint, self._counts[fingerprint])
                        return True
        return False


def salvage_elements(text: str, key: str = "elements") -> list[dict]:
    """Complete objects from a truncated array, deduplicated.

    A truncated loop is not a lost read. Measured on a real failure: 141 element
    objects came back, 7 of them distinct, the rest byte-identical repeats. The
    complete `{...}` objects parse individually even though the array never
    closed, so the answer is recoverable without spending another GPU minute.

    Dedupe is on (semantic_type, bbox): the same piece seen twice at the same
    box IS the same piece. Near-duplicates at slightly different boxes are left
    alone - `mark_duplicates` already decides those on IoU, and guessing here
    would drop a real second sofa.
    """
    start = text.find(f'"{key}"')
    if start < 0:
        return []
    opening = text.find("[", start)
    if opening < 0:
        return []

    found: list[dict] = []
    depth, buf = 0, ""
    for ch in text[opening + 1:]:
        if ch == "{":
            depth += 1
        if depth:
            buf += ch
        if ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    found.append(json.loads(buf))
                except json.JSONDecodeError:
                    pass                      # a half-written object; skip it
                buf = ""
        elif depth == 0 and ch == "]":
            break

    seen: set = set()
    unique: list[dict] = []
    for item in found:
        if not isinstance(item, dict):
            continue
        # `object_key` is the planner's own stable identity, so it wins where it
        # exists. Elements have no such key, and there the pair that matters is
        # type plus box: the same piece at the same box IS the same piece.
        fingerprint = (item.get("object_key")
                       or (item.get("semantic_type"), json.dumps(item.get("bbox"))))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(item)
    return unique


def _plain_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip `additionalProperties`, which some Ollama builds reject."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "properties":
            out[key] = {k: _plain_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _plain_schema(value)
        else:
            out[key] = value
    return out


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.BaseTransport] = None):
        self._settings = settings or get_settings()
        self.model = self._settings.ollama_model
        self._client = httpx.Client(
            base_url=self._settings.ollama_base_url.rstrip("/"),
            timeout=self._settings.ollama_timeout_seconds,
            transport=transport,
        )

    @property
    def label(self) -> str:
        return f"ollama:{self.model}"

    # ── transport ────────────────────────────────────────────────────────
    def _encode(self, path: Path, max_px: int) -> str:
        """Downscale, then base64.

        This is what makes a multi-photo read possible at all. qwen2.5-VL bills
        context by pixel area, so full-size uploads are ruinous: measured on the
        sample set, eight photos cost ~12.7k tokens at 512 px, ~6.5k image
        tokens at 768 px and ~11.6k at 1024 px — and sending four originals
        crashed llama-server outright with a stack overrun rather than
        returning an error. 512 px keeps all eight inside a 16k window with
        room for the prompt, and is still ample to tell a sofa from a mattress.
        Originals on disk are untouched; this resizes in memory only.
        """
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    def _images(self, bundle: InputBundle, limit: int) -> tuple[list[str], list[str]]:
        """Reference photos as downscaled base64, plus warnings for any that
        would not read."""
        out: list[str] = []
        warnings: list[str] = []
        max_px = self._settings.ollama_image_max_px
        for ref in bundle.references[:limit]:
            try:
                out.append(self._encode(Path(ref.path), max_px))
            except (OSError, ValueError) as exc:
                warnings.append(f"could not read {ref.filename or ref.path}: {exc}")
        if len(bundle.references) > limit:
            warnings.append(
                f"{len(bundle.references)} photos supplied; the local model was sent the first {limit}"
            )
        return out, warnings

    def _generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return self._generate_traced(prompt, schema, stage, images, attempts=MAX_ATTEMPTS)[0]

    def _generate_traced(
        self,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
        images: Optional[list[str]] = None,
        array_key: Optional[str] = None,
        attempts: int = 1,
    ) -> tuple[dict[str, Any], "GenerationStatus"]:
        """The call, plus WHY it ended. Streams so a loop can be cut short.

        Streaming is not for progress reporting - it is so `RepetitionDetector`
        can see the answer while it is still being written and abandon a
        generation that has started repeating itself. Measured: a looped read
        ran 187-193s to the token cap; aborted on the third repeat it ends in
        7-13s, having already seen every distinct object it was ever going to
        produce. Closing the response really does stop the server - probed, with
        a follow-up request answering in 0.7s afterwards.
        """
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        body = {
            "model": self.model,
            "messages": [message],
            "format": _plain_schema(schema),
            "stream": True,
            "options": {
                "temperature": 0.2,
                "num_ctx": self._settings.ollama_num_ctx,
                # Not raised to cure truncation: measured, the cap is reached by
                # a LOOP, not by a long answer (a healthy read is 179-1,323
                # tokens against 8,192). A bigger cap buys a longer loop.
                "num_predict": self._settings.ollama_num_predict,
            },
        }
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return self._attempt(body, stage, array_key)
            except OllamaTruncated as exc:
                # Only a runaway string is worth asking again for. A repetition
                # loop already handed back everything it found, and a second run
                # loops just as often.
                last = exc
                if not getattr(exc, "retryable", False) or attempt >= attempts:
                    raise
                log.warning("%s: %s; retrying (%d of %d)", stage, exc, attempt + 1, attempts)
        raise last                                              # pragma: no cover

    def _attempt(self, body: dict, stage: str,
                 array_key: Optional[str]) -> tuple[dict[str, Any], "GenerationStatus"]:
        detector = RepetitionDetector(key=array_key)
        text, done_reason = "", None
        try:
            with self._client.stream("POST", "/api/chat", json=body) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    if resp.status_code == 404:
                        raise OllamaError(
                            f"{stage}: model '{self.model}' is not pulled. "
                            f"Run: ollama pull {self.model}")
                    raise OllamaError(f"{stage}: HTTP {resp.status_code} {resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = ((chunk.get("message") or {}).get("content") or "")
                    text += piece
                    if piece and detector.feed(piece):
                        if detector.runaway_string:
                            log.warning("%s: a single string ran past %d characters; "
                                        "abandoning the generation", stage, MAX_STRING_CHARS)
                            failure = OllamaTruncated(
                                f"{stage}: the model ran one field away without closing it",
                                partial=text)
                            failure.retryable = True
                            raise failure
                        fingerprint, count = detector.repeated
                        log.warning("%s: repetition after %d distinct object(s) "
                                    "(%r seen %dx); abandoning the generation",
                                    stage, len(detector.seen), fingerprint, count)
                        recovered = salvage_elements(text, key=array_key)
                        if not recovered:
                            raise OllamaTruncated(
                                f"{stage}: started repeating itself and nothing "
                                f"complete had been written yet", partial=text)
                        return ({array_key: recovered},
                                GenerationStatus.REPETITION_SUSPECTED)
                    # Read it whenever it is present rather than only on a
                    # chunk flagged `done`: Ollama sends it on the final chunk,
                    # and a caller that waits for both can miss it entirely.
                    if chunk.get("done_reason"):
                        done_reason = chunk["done_reason"]
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(
                f"{stage}: cannot reach Ollama at {self._client.base_url} ({exc})") from exc

        return self._parse(text.strip(), stage, done_reason)

    def _parse(self, text: str, stage: str,
               done_reason: Optional[str]) -> tuple[dict[str, Any], "GenerationStatus"]:
        """Text to payload, plus why the generation ended.

        `done_reason` is the fact Ollama supplies and nothing used to read:
        `length` means the token cap cut the answer off mid-structure, which is
        a different defect from "the model emitted rubbish" and has a different
        fix. Reported as its own status either way, even when the JSON happens
        to parse - a capped answer is not a complete one.
        """
        if not text:
            raise OllamaError(f"{stage}: empty response from {self.model}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # `format` should guarantee JSON, but a small model can still emit a
            # fenced block or trailing prose. Salvage the object rather than
            # throwing away a whole GPU-minute of work.
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1]), GenerationStatus.SALVAGED
                except json.JSONDecodeError:
                    pass
            if done_reason == "length":
                raise OllamaTruncated(
                    f"{stage}: output hit the {self._settings.ollama_num_predict}-token cap "
                    f"({len(text)} chars) and was cut off mid-structure",
                    partial=text,
                ) from exc
            raise OllamaInvalidJSON(f"{stage}: response is not JSON ({exc})") from exc

        if done_reason == "length":
            return payload, GenerationStatus.LENGTH_LIMIT
        return payload, GenerationStatus.COMPLETE

    # ── the Protocol ─────────────────────────────────────────────────────
    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        images, warnings = self._images(bundle, self._settings.ollama_max_images)
        prompt = analysis_prompt(bundle)
        if images:
            prompt += f"\n\n{len(images)} reference photo(s) are attached."
        raw = self._generate_traced(prompt, analysis_schema(bundle.vertical),
                                    "analyze_input", images,
                                    array_key="spotted_objects")[0]
        return coerce_analysis(raw, bundle, warnings, provider=self.label)

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        materials = get_material_registry().list()
        catalog = [
            {"id": m.material_id, "category": m.category, "style_tags": m.style_tags, "applies_to": m.applies_to}
            for m in materials
        ]
        images, warnings = self._images(bundle, self._settings.ollama_max_images)
        raw = self._generate(
            style_prompt(analysis, bundle, catalog), style_schema(bundle.vertical), "create_style_spec", images
        )
        return coerce_style(
            raw, {m.material_id for m in materials}, warnings, provider=self.label, vertical=bundle.vertical
        )

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        from ..catalog.catalog import planning_summary

        catalog = planning_summary([r.type for r in analysis.rooms])
        try:
            raw, status = self._generate_traced(
                objects_prompt(analysis, style, bundle, catalog),
                OBJECT_PLAN_SCHEMA, "plan_objects", array_key="items")
            if status is not GenerationStatus.COMPLETE:
                log.warning("plan_objects finished as %s", status.value)
        except OllamaTruncated as exc:
            # The same loop as the scene reader, and worse here: measured 4 of 5
            # runs truncated, one repeating `kitchen.window` 34 times out of 46
            # keys. Salvage recovered 11 items - exactly what the single clean
            # run produced - so the planner's answer survives its own repetition.
            items = salvage_elements(exc.partial, key="items")
            if not items:
                raise
            log.warning("plan_objects: %s; salvaged %d distinct item(s)", exc, len(items))
            raw = {"items": items}
        return coerce_object_plan(raw, analysis, provider=self.label)

    # ── optional capabilities ────────────────────────────────────────────
    #
    # NOT part of the IntelligenceProvider Protocol, which is pinned to three
    # methods by test_provider_protocol_signatures_are_unchanged. `scene_plan`
    # finds this with getattr and skips the read when it is absent - which is
    # exactly what happened here: with no implementation on this class, a local
    # install produced an EMPTY SceneReading for every project. No crops, no
    # review, no meshes, and the only symptom was one warning in the job feed.

    def read_scene_elements(self, image: Path, room, style: StyleSpec, vertical) -> dict:
        """Box every piece in ONE approved room render, plus its surfaces.

        Same signature, same prompt and same return shape as the Gemini
        implementation, so `scene_plan` cannot tell the two apart and
        `coerce_room_reading` validates both. Returning the raw dict is
        deliberate: this method reports what the model said, and coercion
        decides what survives.
        """
        from .prompts import SCENE_READING_SCHEMA, scene_reading_prompt

        encoded = self._encode(Path(image), self._settings.ollama_scene_image_max_px)
        try:
            payload, status = self._generate_traced(
                scene_reading_prompt(room, style, vertical),
                SCENE_READING_SCHEMA,
                "read_scene_elements",
                images=[encoded],
                array_key="elements",
            )
            if status is not GenerationStatus.COMPLETE:
                payload = {**payload, "_status": status.value,
                           "_warnings": [_STATUS_NOTE[status]]}
            return payload
        except OllamaTruncated as exc:
            # Recover rather than retry. Measured on this model, a truncated
            # read is a loop around the elements it already found, so the answer
            # is in the text - a second call would cost another 3 GPU-minutes
            # for output we already hold, and would loop again just as often
            # (1 in 3 on the image that reproduces it).
            elements = salvage_elements(exc.partial)
            if not elements:
                raise
            log.warning("read_scene_elements: %s; salvaged %d distinct element(s)",
                        exc, len(elements))
            return {"elements": elements, "surfaces": {},
                    "_warnings": [f"the reader looped and was cut off; "
                                  f"{len(elements)} element(s) recovered from the partial answer"]}


__all__ = ["GenerationStatus", "OllamaError", "OllamaInvalidJSON", "OllamaProvider",
           "OllamaTruncated", "RepetitionDetector", "REPEAT_THRESHOLD",
           "OllamaUnavailable", "MAX_ATTEMPTS", "MAX_STRING_CHARS",
           "salvage_elements"]


_STATUS_NOTE = {
    GenerationStatus.REPETITION_SUSPECTED:
        "the reader started repeating itself and was stopped early; "
        "the pieces it had already found were kept",
    GenerationStatus.LENGTH_LIMIT:
        "the reader hit its output cap, so the list may be incomplete",
    GenerationStatus.SALVAGED:
        "the answer was recovered from a partial response",
}

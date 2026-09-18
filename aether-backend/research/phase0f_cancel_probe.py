"""Phase 0f: does abandoning an Ollama stream actually stop the GPU working?

    python research/phase0f_cancel_probe.py

The whole early-termination idea rests on one assumption I refuse to build on
untested: that closing the HTTP response makes Ollama stop generating. If the
server keeps going to its token cap regardless, cancellation is cosmetic - the
call returns early, the GPU stays busy, and the next request queues behind the
loop we thought we killed. That would be a latency "fix" that fixes nothing.

Measured three ways, because only the third is conclusive:

  1. wall-clock to abort             - how long the caller waits
  2. a tiny request straight after   - if the GPU is still looping, this queues
  3. /api/ps before and after        - what the server says it is holding

Run with the model already warm, so load time is not mistaken for queueing.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx                                                          # noqa: E402

from app.core.config import get_settings                              # noqa: E402
from app.intelligence.ollama_provider import RepetitionDetector, _plain_schema            # noqa: E402
from app.intelligence.prompts import (                                # noqa: E402
    SCENE_READING_SCHEMA, scene_reading_prompt)
from app.intelligence.schema import StyleSpec                         # noqa: E402

REPEAT_THRESHOLD = 3          # measured in phase0f_threshold.py; 2 loses content
# The image that reproduces the loop about one run in three.
IMAGE = "data/archive/proj_5db681f48c/moodboard/moodboard_room_living_room.png"


class _Room:
    room_id = name = "living_room"
    type = "living_room"
    width_m, length_m = 5.0, 4.0


def _encoded(path: Path, max_px: int) -> str:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _ps(client: httpx.Client) -> str:
    try:
        models = client.get("/api/ps", timeout=5).json().get("models", [])
    except Exception as exc:                                       # noqa: BLE001
        return f"(unreadable: {exc})"
    if not models:
        return "nothing resident"
    return ", ".join(f"{m['name']} {m.get('size_vram', 0) / 1e9:.2f}GB" for m in models)


def stream_until_repetition(client: httpx.Client, body: dict):
    """Stream, abort on the Nth repeat. Returns (seconds, chars, distinct, why)."""
    body = {**body, "stream": True}
    detector = RepetitionDetector(key="elements", threshold=REPEAT_THRESHOLD)
    text = ""
    started = time.perf_counter()
    why = "finished normally"
    with client.stream("POST", "/api/chat", json=body, timeout=900) as response:
        for line in response.iter_lines():
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            piece = ((chunk.get("message") or {}).get("content") or "")
            text += piece
            if detector.feed(piece):
                fp, n = detector.repeated
                # Leaving the `with` block closes the response, which is the
                # thing under test: does the server stop, or keep grinding?
                return (time.perf_counter() - started, len(text),
                        len(detector.seen), f"repetition: {fp} seen {n}x")
            if chunk.get("done"):
                why = f"done_reason={chunk.get('done_reason')!r}"
    return time.perf_counter() - started, len(text), len(detector.seen), why


def main() -> int:
    s = get_settings()
    client = httpx.Client(base_url=s.ollama_base_url.rstrip("/"), timeout=900)
    body = {
        "model": s.ollama_model,
        "messages": [{"role": "user",
                      "content": scene_reading_prompt(
                          _Room(), StyleSpec(name="Probe", tags=["modern"]), "residential"),
                      "images": [_encoded(ROOT / IMAGE, s.ollama_scene_image_max_px)]}],
        "format": _plain_schema(SCENE_READING_SCHEMA),
        "options": {"temperature": 0.2, "num_ctx": s.ollama_num_ctx,
                    "num_predict": s.ollama_num_predict},
    }

    print(f"model: {s.ollama_model}  threshold: {REPEAT_THRESHOLD}")
    print(f"before: {_ps(client)}\n")

    for attempt in range(1, 7):
        secs, chars, distinct, why = stream_until_repetition(client, body)
        aborted = why.startswith("repetition")
        print(f"  attempt {attempt}: {secs:6.1f}s  {chars:7,} chars  "
              f"{distinct:2} distinct  [{why}]", flush=True)
        if not aborted:
            continue

        # The conclusive part. If the server is still grinding through the loop
        # it thinks we are still listening to, this follow-up queues behind it.
        print(f"  ps immediately after abort: {_ps(client)}")
        probe_body = {**body, "stream": False,
                      "messages": [{"role": "user", "content": "Reply with {}"}],
                      "options": {**body["options"], "num_predict": 16}}
        t0 = time.perf_counter()
        client.post("/api/chat", json=probe_body, timeout=900)
        follow = time.perf_counter() - t0
        print(f"  tiny follow-up request took {follow:.1f}s\n")
        if follow < 10:
            print("  VERDICT: cancellation WORKS - the GPU was free straight after.")
        else:
            print("  VERDICT: cancellation is COSMETIC - the follow-up queued behind")
            print("           the loop, so the server kept generating. Do not ship")
            print("           streaming abort as a latency fix.")
        return 0

    print("\n  no loop reproduced in 6 attempts; re-run (it is roughly 1 in 3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

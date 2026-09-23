"""Meshy adapter — text-to-3D generation.

Only URL shapes, payloads and polling live here. Everything product-specific
(when to generate, what to do with the result) belongs to the job handler, and
ingestion is the shared asset pipeline. Swapping Meshy for another generator
means replacing this file and nothing else.

API shape (verified against the live API, 11 Sep 2026):
  POST /openapi/v2/text-to-3d   {mode, prompt, art_style, should_remesh}
                                → 202 {"result": "<task_id>"}
                                  `prompt` is required; omitting it is a 400.
  GET  /openapi/v2/text-to-3d/{id}
                                → {status, progress, model_urls{glb,fbx,obj,
                                   usdz,stl}, thumbnail_url, texture_urls,
                                   consumed_credits, task_error{message}}
  GET  /openapi/v1/balance      → {"balance": <int>}

`mode: "preview"` returns geometry only — `texture_urls` comes back empty. A
textured model needs a second `refine` call carrying the preview's task id.
A preview of a simple object took roughly 75 s end to end.

Model URLs are pre-signed and long-lived, but treat them as short-lived: fetch
the file as soon as the task succeeds rather than storing the URL.
"""
from __future__ import annotations

import asyncio
import base64
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

BASE = "https://api.meshy.ai"
LICENSE = "meshy-commercial"          # per Meshy's terms for paid plans
LICENSE_URL = "https://www.meshy.ai/terms"

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"}


class MeshyError(RuntimeError):
    """Any non-recoverable Meshy failure: bad request, refusal, dead task."""


class MeshyTaskFailed(MeshyError):
    """The VENDOR ended the task: FAILED, CANCELED or EXPIRED. Distinct from a
    timeout or a dropped connection, which say nothing about the task - it may
    still be running - and which a retry should therefore poll, not re-submit
    (P1-ASSET-002)."""


class MeshyRateLimited(MeshyError):
    """429 `RateLimitExceeded`: too many REQUESTS per second (20/s on Pro,
    Premium, Ultra and Studio; 100/s Enterprise). The right response is to slow
    the request rate down - exponential backoff - and try again."""


class MeshyNoConcurrentSlots(MeshyError):
    """429 `NoMoreConcurrentTasks`: the account's QUEUE is full (10 tasks on
    Pro, 30 Premium, 100 Ultra, 20 Studio; per account, across every API key).
    Not a rate problem: sending slower does nothing, a slot frees only when a
    task finishes. The right response is to wait for one.

    Both forms are 429 and only the body's `message` tells them apart
    (docs.meshy.ai/en/api/rate-limits, read 2026-09-22). Treated generically,
    a full queue burned every retry against the wrong limit (P1-ASSET-003)."""


class MeshyOutOfCredits(MeshyError):
    """402 from the API. Distinct so callers can stop a batch instead of
    retrying every remaining item into the same wall."""


@dataclass
class GeneratedModel:
    task_id: str
    glb_url: str
    thumbnail_url: str
    credits: int
    textured: bool


def _message(resp: httpx.Response) -> str:
    try:                                      # errors are {"message": ...}
        return str(resp.json().get("message", "") or "")
    except Exception:
        return resp.text[:200]


def _raise_for(resp: httpx.Response, what: str) -> None:
    if resp.status_code == 402:
        raise MeshyOutOfCredits(f"{what}: Meshy reports no remaining credits")
    if resp.status_code == 429:
        detail = _message(resp)
        if "nomoreconcurrenttasks" in detail.replace(" ", "").lower():
            raise MeshyNoConcurrentSlots(f"{what}: {detail}")
        # `RateLimitExceeded`, or a 429 that names neither: slowing down is the
        # safe reading of an unknown 429, waiting for a slot is not.
        raise MeshyRateLimited(f"{what}: {detail or 'RateLimitExceeded'}")
    if resp.status_code >= 400:
        raise MeshyError(f"{what}: HTTP {resp.status_code} {_message(resp)}".strip())


#: How long to keep trying against each 429. Meshy documents no Retry-After,
#: so the waits are ours: doubling from half a second for the request rate
#: (~30 s in total before giving up), and a steady poll-length wait for a queue
#: slot, because a slot appears when a task finishes (~60-90 s) and asking
#: faster changes nothing. Module attributes so tests can shrink them.
RATE_LIMIT_ATTEMPTS = 6
RATE_LIMIT_BASE_SECONDS = 0.5
SLOT_WAIT_SECONDS = 10.0
SLOT_WAIT_ATTEMPTS = 90                   # 15 minutes for a slot
_sleep = asyncio.sleep                    # patched in tests


async def _send(client: httpx.AsyncClient, method: str, url: str, what: str, **kw: Any) -> httpx.Response:
    """One request, with the right wait for each kind of 429."""
    rate_tries = slot_tries = 0
    while True:
        resp = await client.request(method, url, **kw)
        try:
            _raise_for(resp, what)
            return resp
        except MeshyNoConcurrentSlots:
            slot_tries += 1
            if slot_tries > SLOT_WAIT_ATTEMPTS:
                raise
            await _sleep(SLOT_WAIT_SECONDS)
        except MeshyRateLimited:
            rate_tries += 1
            if rate_tries > RATE_LIMIT_ATTEMPTS:
                raise
            await _sleep(RATE_LIMIT_BASE_SECONDS * 2 ** (rate_tries - 1) * (1 + 0.25 * random.random()))


async def balance(client: httpx.AsyncClient) -> int:
    """Remaining credits. Cheap — use it to fail fast before a batch."""
    resp = await _send(client, "GET", f"{BASE}/openapi/v1/balance", "balance")
    return int(resp.json().get("balance", 0))


async def submit_text_to_3d(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    mode: str = "preview",
    art_style: str = "realistic",
    should_remesh: bool = True,
    target_polycount: int = 30_000,
    negative_prompt: str = "",
) -> str:
    """Queue a generation. Returns the task id.

    `should_remesh` defaults to True, unlike Meshy's own default. Measured on
    the same prompt: remesh off gave 1,926,510 triangles in a 34.7 MB glb —
    past this pipeline's hard limit, so the asset ingests as `failed` and is
    unusable. Remesh on at 30k gave 30,573 triangles in 0.83 MB, which passes
    validation and loads in the web viewer. Turn it off only for a hero piece
    that will be decimated by hand.
    """
    if not prompt.strip():
        raise MeshyError("submit_text_to_3d: prompt is required")
    body: dict[str, Any] = {
        "mode": mode,
        "prompt": prompt.strip(),
        "art_style": art_style,
        "should_remesh": should_remesh,
    }
    if should_remesh and target_polycount > 0:
        body["target_polycount"] = int(target_polycount)
        body["topology"] = "triangle"
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    resp = await _send(client, "POST", f"{BASE}/openapi/v2/text-to-3d", "submit_text_to_3d", json=body)
    task_id = resp.json().get("result")
    if not task_id:
        raise MeshyError("submit_text_to_3d: no task id in the response")
    return str(task_id)


async def submit_refine(client: httpx.AsyncClient, preview_task_id: str) -> str:
    """Second stage: texture a finished preview. Returns a new task id."""
    resp = await _send(client, "POST", f"{BASE}/openapi/v2/text-to-3d", "submit_refine",
                       json={"mode": "refine", "preview_task_id": preview_task_id})
    task_id = resp.json().get("result")
    if not task_id:
        raise MeshyError("submit_refine: no task id in the response")
    return str(task_id)


# Which Meshy endpoint a task belongs to. Image-to-3D lives on v1 and
# text-to-3D on v2 — probing the live API, GET /openapi/v1/text-to-3d/<id>
# answers 404 NoMatchingRoute while /openapi/v1/image-to-3d/<id> answers
# 400 Invalid ID, so the versions are not interchangeable. A task id alone
# does not say which endpoint made it, so callers carry it.
TEXT_TO_3D = "openapi/v2/text-to-3d"
IMAGE_TO_3D = "openapi/v1/image-to-3d"


def _data_uri(image: Path) -> str:
    """Meshy takes a publicly reachable URL or a data URI. Our crops live on
    a developer's disk behind no web server, so the bytes travel inline."""
    suffix = image.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(suffix)
    if mime is None:
        raise MeshyError(f"unsupported reference image type: {image.suffix!r}")
    return f"data:image/{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")


async def submit_image_to_3d(
    client: httpx.AsyncClient,
    image: Path,
    *,
    should_remesh: bool = True,
    target_polycount: int = 30_000,
    enable_pbr: bool = True,
    symmetry_mode: str = "auto",
) -> str:
    """Queue a generation from ONE image. Returns the task id.

    `should_remesh` defaults True for the same reason as the text path:
    unremeshed output measured 1.9 M triangles, past the ingester's hard limit,
    so the asset registers as `failed` and cannot be used.

    Unlike text-to-3D there is no preview/refine split here — image-to-3D
    returns a textured model in one task.
    """
    if not image.is_file():
        raise MeshyError(f"submit_image_to_3d: {image} does not exist")
    body: dict[str, Any] = {
        "image_url": _data_uri(image),
        "enable_pbr": enable_pbr,
        "should_remesh": should_remesh,
        "symmetry_mode": symmetry_mode,
    }
    if should_remesh and target_polycount > 0:
        body["target_polycount"] = int(target_polycount)
        body["topology"] = "triangle"
    resp = await _send(client, "POST", f"{BASE}/{IMAGE_TO_3D}", "submit_image_to_3d", json=body)
    task_id = resp.json().get("result")
    if not task_id:
        raise MeshyError(f"submit_image_to_3d: no task id in {resp.text[:200]}")
    return str(task_id)


async def get_task(client: httpx.AsyncClient, task_id: str, endpoint: str = TEXT_TO_3D) -> dict[str, Any]:
    resp = await _send(client, "GET", f"{BASE}/{endpoint}/{task_id}", f"get_task {task_id}")
    return resp.json()


async def wait_for(
    client: httpx.AsyncClient,
    task_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = 10.0,
    on_progress: Optional[Callable[[str, int], None]] = None,
    endpoint: str = TEXT_TO_3D,
) -> GeneratedModel:
    """Poll until the task reaches a terminal state.

    Raises MeshyError on failure or timeout. A preview of a simple object
    finishes in roughly 60-90 s, so the default poll is deliberately coarse.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    last = -1
    while True:
        task = await get_task(client, task_id, endpoint)
        status = str(task.get("status", ""))
        progress = int(task.get("progress", 0) or 0)
        if on_progress is not None and progress != last:
            on_progress(status, progress)
            last = progress

        if status == "SUCCEEDED":
            glb = (task.get("model_urls") or {}).get("glb")
            if not glb:
                raise MeshyError(f"task {task_id} succeeded without a glb url")
            return GeneratedModel(
                task_id=task_id,
                glb_url=glb,
                thumbnail_url=task.get("thumbnail_url") or "",
                credits=int(task.get("consumed_credits", 0) or 0),
                textured=bool(task.get("texture_urls")),
            )
        if status in TERMINAL:
            why = (task.get("task_error") or {}).get("message") or status
            raise MeshyTaskFailed(f"task {task_id} ended as {status}: {why}")

        if loop.time() >= deadline:
            raise MeshyError(
                f"task {task_id} still {status or 'PENDING'} at {progress}% "
                f"after {timeout_seconds:.0f}s"
            )
        await asyncio.sleep(poll_seconds)


#: Attempts at pulling a finished mesh down. The model is already generated and
#: already paid for by the time this runs, so giving up on the first blip
#: throws away the whole purchase: measured on proj_a25a006c88, three of six
#: pieces - the client's television among them - reached 100% at Meshy and were
#: then lost to "All connection attempts failed", leaving a catalog cabinet
#: standing where the TV should be. A transient network error is not a reason
#: to lose a mesh.
DOWNLOAD_ATTEMPTS = 4


async def download_glb(client: httpx.AsyncClient, url: str, dest: Path) -> Path:
    """Stream the model to disk, retrying a transient network failure.

    Retries only what is worth retrying: a connection or timeout error, and a
    5xx from the CDN. A 404 or a 403 means the URL is wrong or expired, and
    trying it three more times only delays the real message.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Optional[Exception] = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 500:
                    raise MeshyError(f"CDN returned {resp.status_code}")
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        fh.write(chunk)
            if dest.stat().st_size == 0:
                dest.unlink(missing_ok=True)
                raise MeshyError(f"downloaded an empty file from {url[:80]}")
            return dest
        except (httpx.TransportError, httpx.StreamError, MeshyError) as exc:
            last = exc
            dest.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                break
            await asyncio.sleep(min(8.0, 1.5 ** attempt))
    raise MeshyError(f"could not download the finished mesh after {DOWNLOAD_ATTEMPTS} "
                     f"attempt(s): {type(last).__name__}: {last}")


async def download_thumbnail(client: httpx.AsyncClient, url: str, dest: Path) -> Optional[Path]:
    """Keep the vendor's preview image next to the mesh, or nothing.

    P1-ASSET-004: the thumbnail URL is signed and expires with the vendor's
    retention window, so it must not be stored. One attempt, never fatal - a
    preview is a convenience; the mesh is the purchase.
    """
    if not url:
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
        if dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:                                      # noqa: BLE001
        dest.unlink(missing_ok=True)
        return None


def make_client(api_key: str, timeout_seconds: float = 300.0) -> httpx.AsyncClient:
    if not api_key:
        raise MeshyError("MESHY_API_KEY is not set")
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "aether-asset-pipeline/0.1",
        },
    )

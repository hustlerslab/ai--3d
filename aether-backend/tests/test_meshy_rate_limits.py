"""P1-ASSET-003 - the two Meshy 429s are two different problems.

Both come back as 429 and only the body's `message` says which:
`RateLimitExceeded` means too many REQUESTS per second - slow down and retry;
`NoMoreConcurrentTasks` means the account's QUEUE is full - sending slower
changes nothing, a slot frees when a task finishes, so wait for one. Treated
generically, a full queue burned every retry against the wrong limit and a
rate blip stalled for minutes.

Every test runs against a mocked transport; sleeps are recorded, not slept.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.intelligence.schema import SceneElement
from app.jobs.handlers import generate_elements as gen
from app.providers import meshy

RATE = {"message": "RateLimitExceeded"}
QUEUE = {"message": "NoMoreConcurrentTasks"}
OK = {"result": "task_1"}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer t"})


@pytest.fixture
def sleeps(monkeypatch):
    seen: list[float] = []

    async def record(seconds):
        seen.append(seconds)

    monkeypatch.setattr(meshy, "_sleep", record)
    return seen


def _answers(*responses):
    """A transport that returns the given (status, body) pairs in order and
    then keeps returning the last one."""
    queue = list(responses)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json=body)

    return handler, calls


def _submit(handler) -> str:
    async def go():
        async with _client(handler) as c:
            return await meshy.submit_text_to_3d(c, "a vase")
    return asyncio.run(go())


# -- RateLimitExceeded: back off on the request rate ----------------------------

def test_a_rate_limit_backs_off_exponentially_and_then_succeeds(sleeps):
    handler, calls = _answers((429, RATE), (429, RATE), (429, RATE), (202, OK))
    assert _submit(handler) == "task_1"
    assert calls["n"] == 4
    assert len(sleeps) == 3, "one wait per 429"
    assert sleeps[0] >= meshy.RATE_LIMIT_BASE_SECONDS
    assert sleeps[1] > sleeps[0] and sleeps[2] > sleeps[1], "doubling, with jitter"
    assert all(s < meshy.SLOT_WAIT_SECONDS for s in sleeps), "never the slot wait"


def test_a_rate_limit_that_never_clears_raises_the_typed_error(sleeps, monkeypatch):
    monkeypatch.setattr(meshy, "RATE_LIMIT_ATTEMPTS", 2)
    handler, calls = _answers((429, RATE))
    with pytest.raises(meshy.MeshyRateLimited):
        _submit(handler)
    assert calls["n"] == 3 and len(sleeps) == 2, "the first try plus the attempts, then give up"


def test_an_unnamed_429_is_treated_as_a_rate_limit_not_a_full_queue(sleeps):
    handler, _ = _answers((429, {"message": ""}), (202, OK))
    assert _submit(handler) == "task_1"
    assert len(sleeps) == 1 and sleeps[0] < meshy.SLOT_WAIT_SECONDS


# -- NoMoreConcurrentTasks: wait for a slot ----------------------------------------

def test_a_full_queue_waits_for_a_slot_at_a_steady_cadence(sleeps):
    handler, calls = _answers((429, QUEUE), (429, QUEUE), (429, QUEUE), (202, OK))
    assert _submit(handler) == "task_1"
    assert calls["n"] == 4
    assert sleeps == [meshy.SLOT_WAIT_SECONDS] * 3, "a slot wait, not a request-rate backoff"


def test_a_queue_that_never_frees_raises_the_typed_error(sleeps, monkeypatch):
    monkeypatch.setattr(meshy, "SLOT_WAIT_ATTEMPTS", 3)
    handler, calls = _answers((429, QUEUE))
    with pytest.raises(meshy.MeshyNoConcurrentSlots):
        _submit(handler)
    assert calls["n"] == 4 and sleeps == [meshy.SLOT_WAIT_SECONDS] * 3


def test_the_message_is_matched_case_and_space_insensitively():
    def handler(request):
        return httpx.Response(429, json={"message": "no more concurrent tasks"})

    async def go():
        async with _client(handler) as c:
            meshy._raise_for(await c.get("https://api.meshy.ai/x"), "probe")

    with pytest.raises(meshy.MeshyNoConcurrentSlots):
        asyncio.run(go())


def test_the_two_errors_are_distinct_and_both_are_meshy_errors():
    assert issubclass(meshy.MeshyRateLimited, meshy.MeshyError)
    assert issubclass(meshy.MeshyNoConcurrentSlots, meshy.MeshyError)
    assert not issubclass(meshy.MeshyNoConcurrentSlots, meshy.MeshyRateLimited)
    assert not issubclass(meshy.MeshyRateLimited, meshy.MeshyNoConcurrentSlots)


# -- polling is rate-limited too ----------------------------------------------------

def test_polling_backs_off_on_a_rate_limit_and_still_finishes(sleeps):
    done = {"id": "t", "status": "SUCCEEDED", "progress": 100,
            "model_urls": {"glb": "https://assets.example/m.glb"}, "consumed_credits": 5}
    handler, calls = _answers((429, RATE), (200, {"status": "IN_PROGRESS", "progress": 50}), (200, done))

    async def go():
        async with _client(handler) as c:
            return await meshy.wait_for(c, "t", timeout_seconds=30, poll_seconds=0)

    model = asyncio.run(go())
    assert model.glb_url.endswith("m.glb") and calls["n"] == 3
    assert len(sleeps) == 1 and sleeps[0] < meshy.SLOT_WAIT_SECONDS


# -- the in-flight cap ----------------------------------------------------------------

def test_in_flight_tasks_never_exceed_the_configured_cap(env, monkeypatch):
    """Six pieces, a cap of two: at no moment are more than two generating."""
    monkeypatch.setenv("MESHY_API_KEY", "test-key")
    monkeypatch.setenv("MESHY_MAX_CONCURRENT_TASKS", "2")
    from app.core import config
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.meshy_max_concurrent_tasks == 2

    inflight = {"now": 0, "max": 0}

    async def fake_generate(client, ctx, key, element, s):
        inflight["now"] += 1
        inflight["max"] = max(inflight["max"], inflight["now"])
        await asyncio.sleep(0.01)                      # let the others contend
        inflight["now"] -= 1
        return f"asset_{key}", 0

    async def balance(*a, **k):
        return 100

    monkeypatch.setattr(gen, "_generate_one", fake_generate)
    monkeypatch.setattr(meshy, "balance", balance)
    ctx = SimpleNamespace(project_id="proj_cap", job=SimpleNamespace(job_id="job_cap", created_by=""),
                          emit=lambda *a, **k: None, log=logging.getLogger("test.cap"))
    todo = {f"k{i}": SceneElement(element_id=f"e{i}", room_id="r", semantic_type="chair", name=f"chair {i}",
                                  crop_ref="planning/scene_crops/x.png") for i in range(6)}
    result = asyncio.run(gen._run(ctx, todo, settings))
    assert len(result["made"]) == 6
    assert inflight["max"] == 2, f"cap breached: {inflight['max']} in flight"


def test_the_default_cap_sits_below_the_pro_queue_limit():
    from app.core.config import Settings

    assert 0 < Settings().meshy_max_concurrent_tasks < 10

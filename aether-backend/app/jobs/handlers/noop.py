"""No-op job: exercises the runner, events and checkpoints without any work.

Params:
  steps        number of fake stages (default 3)
  sleep        seconds per stage (default 0.05)
  fail_until   raise on every attempt below this number (default 0 = never)
"""
from __future__ import annotations

import time

from ..context import JobContext
from ..registry import register
from ..schema import JobLane


@register("noop", lane=JobLane.ai, max_attempts=3, description="No-op pipeline exercise")
def noop(ctx: JobContext) -> dict:
    steps = int(ctx.params.get("steps", 3))
    sleep = float(ctx.params.get("sleep", 0.05))
    fail_until = int(ctx.params.get("fail_until", 0))
    done: list[str] = []

    for i in range(1, steps + 1):
        name = f"logs/noop_step_{i}.json"
        if ctx.has_checkpoint(name):
            ctx.emit(f"noop.step{i}", "checkpoint present, skipped")
            done.append(name)
            continue
        time.sleep(sleep)
        if ctx.job.attempt < fail_until and i == steps:
            raise RuntimeError(f"simulated failure on attempt {ctx.job.attempt}")
        ctx.write_json(name, {"step": i, "attempt": ctx.job.attempt})
        ctx.mark_checkpoint(name)
        ctx.emit(f"noop.step{i}", f"step {i}/{steps} done")
        done.append(name)

    return {"steps": steps, "checkpoints": done, "attempt": ctx.job.attempt}

#!/usr/bin/env python
"""Poll ONE job to a terminal state against the live API, then exit.

Why this exists
---------------
Three separate rounds of debugging were lost to reading a file before the job
writing it had finished, and then reporting the previous run's contents as the
current result. Twice that produced a confident, wrong diagnosis.

The product never had this bug — the Studio gates every read on
`job?.status === "SUCCEEDED"`, and the API answers `ANALYSIS_NOT_READY` with the
job's status when an artifact is missing. The bug was always in ad-hoc
verification: `runner.wait_idle()` asks "is the worker pool idle", which is not
the same question as "has MY job finished", and a monitor on a timer is not
asking any question at all.

The rule
--------
Never read a job's output on a timer, a guess, or immediately after triggering
it. Take the `job_id` the trigger returns and poll that job until its status is
terminal. Only then read the file.

    POST /api/projects/{id}/analyze      -> {"data": {"job": {"job_id": ...}}}
    python scripts/wait_for_job.py <job_id>
    GET  /api/projects/{id}/analysis     <- now safe to read

Usage
-----
    python scripts/wait_for_job.py <job_id> [--base http://127.0.0.1:8000] [--timeout 1800]

Exit code 0 when the job SUCCEEDED, 1 for any other terminal state or timeout,
so it composes with `&&` in a shell.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_job(job_id: str, base: str, timeout: float = 1800.0, poll: float = 3.0) -> dict:
    """Block until `job_id` reaches a terminal state. Returns the job row."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            body = _get(f"{base.rstrip('/')}/api/jobs/{job_id}")
        except urllib.error.HTTPError as exc:
            # 404 means NO SUCH JOB — waiting will never make it exist. Treating
            # it as retryable once spun for forty minutes on a job id that had
            # been mis-parsed out of the trigger's response, which is exactly
            # the kind of silent stall this script was written to prevent.
            if exc.code == 404:
                raise SystemExit(
                    f"no job {job_id!r} at {base} (HTTP 404). Check the id came from "
                    "the trigger's response: POST /analyze returns {'success':..,'job':..} "
                    "unwrapped, while GET /jobs/{id} nests under 'data'."
                )
            raise
        except urllib.error.URLError as exc:
            # a restarting server IS a transient condition; keep waiting
            print(f"  (api unreachable: {exc}); retrying", flush=True)
            time.sleep(poll)
            continue
        data = body.get("data", body)
        job = data.get("job", data)
        status = str(job.get("status", "")).upper()
        if status != last:
            print(f"  {job_id} {status}", flush=True)
            last = status
        if status in TERMINAL:
            return job
        time.sleep(poll)
    raise TimeoutError(f"{job_id} still {last or 'unknown'} after {timeout:.0f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for one pipeline job to finish.")
    ap.add_argument("job_id")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--poll", type=float, default=3.0)
    ns = ap.parse_args()
    try:
        job = wait_for_job(ns.job_id, ns.base, ns.timeout, ns.poll)
    except TimeoutError as exc:
        print(f"TIMEOUT: {exc}", file=sys.stderr)
        return 1
    status = str(job.get("status", "")).upper()
    print(json.dumps({k: job.get(k) for k in ("job_id", "type", "lane", "status", "error")}, indent=2))
    return 0 if status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

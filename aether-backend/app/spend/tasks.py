"""The generation-task ledger — P1-ASSET-002, the fourth spend gate.

P0-SEC-003 made sure nobody can spend past a cap. This makes sure a RETRY
cannot spend at all: a generation job killed after the vendor accepted the
task - process restart, worker crash, `max_attempts=2` re-running the handler
- used to submit the same crop again and pay for it twice.

Every submission is a row here, written the moment the task id comes back
and before anything waits on it. The row is keyed by WHAT was asked for:

    request_id = sha1(canonical piece key | sha256(crop bytes) | params)

so the same piece, from the same picture, with the same settings, is the same
request whichever job asks. The canonical key rather than the reading row id
because the row id is minted from the crop box and a re-read moves every box
(P1-ASSET-001); the crop checksum already pins the exact picture.

A retry that finds a `SUBMITTED` row polls that task. Only the vendor ending
the task (`FAILED`, `CANCELED`, `EXPIRED`) or the ingester rejecting the mesh
clears the way for a new submission - a timeout or a dropped connection says
nothing about the task and must not turn into a second purchase.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..db.sqlite import get_db

#: A row in one of these states may be picked up again by polling its task.
#: SUCCEEDED is here for P1-ASSET-004: a mesh whose bytes were lost after the
#: fact is re-downloaded from the vendor's still-open task while the retention
#: window lasts, instead of being bought again. Once the vendor says EXPIRED
#: the poll raises MeshyTaskFailed, the row becomes FAILED, and only then is a
#: fresh submission the answer.
RESUMABLE = ("SUBMITTED", "SUCCEEDED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_key(item_key: str, image: Path, params: dict[str, Any]) -> tuple[str, str]:
    """Deterministic for identical inputs. Returns (request_id, image_sha256).

    The parameters are serialised sorted so dict order cannot change the key;
    a changed polycount or remesh setting IS a different generation.
    """
    digest = hashlib.sha256(Path(image).read_bytes()).hexdigest()
    raw = f"{item_key}|{digest}|{json.dumps(params, sort_keys=True, default=str)}".encode("utf-8")
    return "gr_" + hashlib.sha1(raw).hexdigest()[:20], digest


def get_task(request_id: str) -> Optional[dict[str, Any]]:
    row = get_db().one("SELECT * FROM generation_tasks WHERE request_id = ?", (request_id,))
    return dict(row) if row else None


def resumable_task(request_id: str) -> Optional[dict[str, Any]]:
    """The in-flight submission for this request, if one exists."""
    row = get_task(request_id)
    if row and row["task_id"] and row["status"] in RESUMABLE:
        return row
    return None


def record_submission(request_id: str, *, project_id: str, job_id: str, item_key: str,
                      element_id: str, image_sha256: str, params: dict[str, Any],
                      task_id: str, endpoint: str, provider: str = "meshy") -> None:
    """Write the receipt. INSERT OR REPLACE: a request re-submitted after a
    vendor failure gets a fresh row under the same key, and the old task id
    - which the vendor has already closed - is not worth keeping."""
    now = _now_iso()
    with get_db().tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO generation_tasks(request_id, project_id, job_id, item_key,"
            " element_id, image_sha256, params, provider, endpoint, task_id, status, asset_id,"
            " credits, error, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,'SUBMITTED','',NULL,'',?,?)",
            (request_id, project_id, job_id, item_key, element_id, image_sha256,
             json.dumps(params, sort_keys=True, default=str), provider, endpoint, task_id, now, now),
        )


def mark_task(request_id: str, status: str, *, asset_id: str = "",
              credits: Optional[int] = None, error: str = "") -> None:
    """Record the outcome. `credits` is the vendor's own consumed figure."""
    with get_db().tx() as c:
        c.execute(
            "UPDATE generation_tasks SET status = ?, asset_id = COALESCE(NULLIF(?, ''), asset_id),"
            " credits = COALESCE(?, credits), error = ?, updated_at = ? WHERE request_id = ?",
            (status, asset_id, credits, error[:500], _now_iso(), request_id),
        )


def project_tasks(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in get_db().query(
        "SELECT * FROM generation_tasks WHERE project_id = ? ORDER BY created_at", (project_id,))]

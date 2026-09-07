"""What a job handler gets to work with."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ..projects.layout import CHECKPOINTS, ensure_layout, file_url
from ..projects.schema import ProjectRecord
from ..projects.store import ProjectStore
from .schema import Job
from .store import JobStore


class JobContext:
    def __init__(
        self,
        job: Job,
        project: ProjectRecord,
        job_store: JobStore,
        project_store: ProjectStore,
    ):
        self.job = job
        self.project = project
        self.jobs = job_store
        self.projects = project_store
        self.project_id = project.project_id
        self.params: dict[str, Any] = dict(job.params)
        self.dir: Path = ensure_layout(project.project_id)
        self.log = self._make_logger()
        self._stage_started = time.monotonic()

    # ── logging ──────────────────────────────────────────────────
    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"aether.job.{self.job.job_id}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        # one file handler per job attempt; the file lives under logs/
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()
        log_path = self.dir / "logs" / f"{self.job.job_id}.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        self.log_path = log_path
        return logger

    def close(self) -> None:
        for h in list(self.log.handlers):
            self.log.removeHandler(h)
            h.close()

    # ── events ───────────────────────────────────────────────────
    def emit(self, stage: str, message: str = "", status: str = "progress") -> None:
        now = time.monotonic()
        duration_ms = int((now - self._stage_started) * 1000)
        self._stage_started = now
        self.log.info("[%s] %s %s", stage, status, message)
        self.jobs.add_event(
            self.project_id, stage, status, message, job_id=self.job.job_id, duration_ms=duration_ms
        )

    # ── checkpoints ──────────────────────────────────────────────
    def path(self, relative: str) -> Path:
        return self.dir / relative

    def checkpoint_path(self, name: str) -> Path:
        return self.dir / CHECKPOINTS.get(name, name)

    def has_checkpoint(self, name: str) -> bool:
        return self.checkpoint_path(name).exists()

    def mark_checkpoint(self, name: str) -> None:
        """Record the last completed step on the job row (the file itself is
        the durable checkpoint; this is for the UI and for resume messages)."""
        self.job = self.jobs.update(self.job.job_id, checkpoint=name)

    def write_json(self, relative: str, data: Any) -> Path:
        target = self.dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
        tmp.replace(target)  # atomic on the same volume
        return target

    def read_json(self, relative: str) -> Any:
        return json.loads((self.dir / relative).read_text(encoding="utf-8"))

    def url(self, relative: str) -> str:
        return file_url(self.project_id, relative)

    def add_output(self, kind: str, relative: str, meta: Optional[dict] = None) -> dict:
        return self.projects.add_output(self.project_id, kind, relative, self.url(relative), meta)


def _json_default(o: Any) -> Any:
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")

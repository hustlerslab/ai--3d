"""Structured logging — P0-OBSERVABILITY-001.

One JSON object per line, every line carrying the four ids that let a support
engineer reconstruct one customer's project from the logs alone:

    correlation_id   one run, end to end, across every request and job
    project_id       whose project
    job_id           which job
    stage            where in the pipeline

The ids are ambient, not arguments. A logging call that needs four extra
parameters is a logging call somebody omits under pressure — and the line
nobody bothered to enrich is the one you need at 3am. They live in contextvars
set at the edges (request middleware, job runner), and the formatter attaches
them, so `log.info("job.start")` is already correlated.

**What never goes in a log line.** Ids only. Not the brief, not a prompt, not
an image path, not a key, not an email address. A log aggregator is a second
copy of everything it ingests, usually with different access rules and longer
retention than the database — so a brief logged "temporarily for debugging"
outlives the project it describes. `SENSITIVE_KEYS` below is a backstop, not a
licence to pass secrets and rely on redaction.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

#: Ambient run context. Empty string, never None, so a formatter never has to
#: decide what a missing id looks like.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
project_id: ContextVar[str] = ContextVar("project_id", default="")
job_id: ContextVar[str] = ContextVar("job_id", default="")
stage: ContextVar[str] = ContextVar("stage", default="")

#: Substrings that must never appear as a field name in a record's extras.
#: Redaction is a seatbelt: the rule is that these are not passed at all.
SENSITIVE_KEYS = ("key", "token", "secret", "password", "authorization", "credential")

#: Fields the stdlib puts on every LogRecord. Anything else a caller attached
#: is theirs, and is carried through.
_STANDARD = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "taskName", "thread", "threadName",
}


def new_correlation_id() -> str:
    """Minted at project creation and carried for the life of that run."""
    return "cid_" + uuid.uuid4().hex[:12]


def install_record_factory() -> None:
    """Stamp the ambient ids onto every record AS IT IS CREATED.

    Three mechanisms were tried; only this one is correct.

    * In the FORMATTER - wrong. A formatter runs when a handler writes the
      line: inline for a StreamHandler, but later and on another thread for a
      QueueHandler or anything buffered, where the contextvars are gone or
      belong to somebody else. The line still has ids, and they name the wrong
      customer - the worst kind of failure.
    * A filter on the ROOT LOGGER - wrong. `Logger.filter()` applies to records
      logged on THAT logger; records from `aether.jobs` propagate to root's
      handlers without ever passing root's filters.
    * The RECORD FACTORY - right. It runs once, for every record, whatever
      logger made it and whatever handler consumes it, at the moment of
      creation. The ids become real attributes, so caplog and any other handler
      can read them too.
    """
    existing = logging.getLogRecordFactory()
    if getattr(existing, "_allure_context", False):
        return                                   # already installed; idempotent

    def factory(*args, **kwargs):
        record = existing(*args, **kwargs)
        for name, var in (("correlation_id", correlation_id),
                          ("project_id", project_id),
                          ("job_id", job_id),
                          ("stage", stage)):
            if not getattr(record, name, ""):
                setattr(record, name, var.get(""))
        return record

    factory._allure_context = True               # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Deliberately not a dependency. `json.dumps` with `default=str` covers every
    value a log line can hold, and a formatter is forty lines — adding a
    library to a path that runs on every request buys nothing here.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # ISO-8601 UTC with a Z. Never local time: a log read in a
            # different timezone than it was written in is a log that misleads.
            "ts": datetime.fromtimestamp(record.created, timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # Read off the RECORD, stamped by the record factory at creation.
            # The contextvar is only a fallback for a record made before
            # install_record_factory() ran.
            "correlation_id": getattr(record, "correlation_id", "") or correlation_id.get(""),
            "project_id": getattr(record, "project_id", "") or project_id.get(""),
            "job_id": getattr(record, "job_id", "") or job_id.get(""),
            "stage": getattr(record, "stage", "") or stage.get(""),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD or key in payload or key.startswith("_"):
                continue
            if any(s in key.lower() for s in SENSITIVE_KEYS):
                payload[key] = "[redacted]"
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_type"] = getattr(record.exc_info[0], "__name__", "Exception")
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO, json_output: bool = True) -> None:
    """Replace whatever handlers exist with exactly one.

    Wholesale replacement on purpose: uvicorn installs its own handlers, and
    leaving them attached means every line is emitted twice — once as JSON and
    once as prose. A half-structured log cannot be parsed by anything.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    install_record_factory()

    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if json_output
        else logging.Formatter("%(levelname)-8s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn's access and error loggers propagate to root once their own
    # handlers are gone, so request lines join the same JSON stream.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


class bind:
    """Set log context for a block, and put it back afterwards.

        with bind(project_id="proj_x", job_id="job_y", stage="analyze"):
            log.info("job.start")

    A context manager rather than a setter, because a job that fails must not
    leave its ids attached to whatever the worker thread picks up next — a log
    line naming the wrong customer is worse than one naming none.
    """

    _VARS = {
        "correlation_id": correlation_id,
        "project_id": project_id,
        "job_id": job_id,
        "stage": stage,
    }

    def __init__(self, **values: Optional[str]):
        unknown = set(values) - set(self._VARS)
        if unknown:
            raise ValueError(f"unknown log context field(s): {', '.join(sorted(unknown))}")
        self._values = {k: v for k, v in values.items() if v is not None}
        self._tokens: dict = {}

    def __enter__(self) -> "bind":
        for key, value in self._values.items():
            self._tokens[key] = self._VARS[key].set(str(value))
        return self

    def __exit__(self, *_exc) -> None:
        for key, token in self._tokens.items():
            self._VARS[key].reset(token)


def current_context() -> dict[str, str]:
    """What would be attached to a log line right now. For tests, and for
    carrying the correlation id onto an event row."""
    return {
        "correlation_id": correlation_id.get(""),
        "project_id": project_id.get(""),
        "job_id": job_id.get(""),
        "stage": stage.get(""),
    }

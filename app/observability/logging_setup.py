"""Process-level structured JSON logging for runtime services (#3895).

The API, worker, and watcher processes install :class:`JsonLogFormatter` on
the root logger at process setup so every existing stdlib
``logging.getLogger(__name__)`` call site emits one JSON object per line on
stdout — call sites are untouched; only the process-level handler/formatter
changes.

Field names reuse the span-schema conventions of ``app.observability.log``
documented in ``docs/OBSERVABILITY.md :: JSON log and span schema``
(``trace_id``, ``status``, ``extra``) so general service logs and
instrumented spans correlate with the same jq recipes. ``trace_id`` is read
from the :mod:`app.observability.tracer` contextvar when a record does not
carry one explicitly, which is how span/trace context threads into ordinary
log lines. No external aggregation stack is involved: output is plain
line-delimited JSON on stdout.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import IO, Any, Optional

from app.observability.tracer import current_trace_id

# Attributes owned by the stdlib LogRecord contract; anything else on the
# record arrived via ``logger.info(..., extra={...})`` and is surfaced under
# the span-schema ``extra`` field.
_RESERVED_RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "asctime",
    "message",
    "taskName",
}


class JsonLogFormatter(logging.Formatter):
    """Render one stdlib log record as one JSON line (span-schema field names)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "status": "error" if record.levelno >= logging.ERROR else "ok",
        }
        trace_id = getattr(record, "trace_id", None) or current_trace_id()
        if trace_id:
            payload["trace_id"] = str(trace_id)
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and key != "trace_id"
        }
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_json_logging(
    level: int = logging.INFO,
    *,
    stream: Optional[IO[str]] = None,
) -> logging.Handler:
    """Install the JSON formatter on the root logger (idempotent).

    Keeps the stdlib ``logging.getLogger(__name__)`` call-site API: only the
    process-level handler/formatter changes. Re-invocation never adds a second
    handler; it rebinds the existing one to the current ``sys.stdout`` (or the
    explicit ``stream``) so pytest ``capsys``-replaced streams stay aligned —
    the same realignment contract the worker's pre-#3895 local setup carried.
    """
    target = stream if stream is not None else sys.stdout
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, JsonLogFormatter
        ):
            current = handler.stream
            if current is target:
                return handler
            if getattr(current, "closed", False):
                # StreamHandler.setStream() flushes the old stream before it
                # rebinds. Pytest capture streams can already be closed by the
                # time another runtime entrypoint configures process logging.
                # Assign under the handler lock only for that closed-stream
                # case; live streams keep the normal flush-on-rebind contract.
                handler.acquire()
                try:
                    handler.stream = target
                finally:
                    handler.release()
            else:
                handler.setStream(target)
            return handler
    handler = logging.StreamHandler(target)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handler


__all__ = ["JsonLogFormatter", "configure_json_logging"]

"""Logging and metrics configuration helpers (package re-export)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import timezone, datetime
from typing import Any

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.settings import settings


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured logs."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - simple formatting
        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


instrumentator = Instrumentator(should_group_status_codes=True)


def configure_metrics(app: FastAPI) -> None:
    """Instrument FastAPI app with Prometheus metrics when enabled."""
    if not getattr(settings, "metrics_enabled", False):
        return
    instrumentator.instrument(app).expose(app, include_in_schema=False, should_gzip=True)


from app.observability.log import json_log, span, with_trace_id  # noqa: E402 — re-export from merged log module

__all__ = ["configure_metrics", "setup_logging", "json_log", "span", "with_trace_id"]

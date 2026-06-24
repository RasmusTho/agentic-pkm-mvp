"""Logging and metrics configuration helpers.

FastAPI and Prometheus imports are deferred into the functions that use them so
that importing any submodule of app.observability (e.g. app.observability.log)
does not force the full API dependency stack to load.  Non-API callers (agents,
LLM tracing, CLI) can safely import app.observability.log without requiring
FastAPI or prometheus_fastapi_instrumentator to be installed.
"""

from __future__ import annotations


def setup_logging() -> None:
    import json
    import logging
    import sys
    from datetime import timezone, datetime
    from typing import Any

    class JsonFormatter(logging.Formatter):
        """Minimal JSON formatter for structured logs."""

        def format(self, record: logging.LogRecord) -> str:  # pragma: no cover
            payload: dict[str, Any] = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def configure_metrics(app: object) -> None:
    """Instrument FastAPI app with Prometheus metrics when enabled."""
    from app.settings import settings

    if not getattr(settings, "metrics_enabled", False):
        return

    from fastapi import FastAPI
    from prometheus_fastapi_instrumentator import Instrumentator

    assert isinstance(app, FastAPI)
    instrumentator = Instrumentator(should_group_status_codes=True)
    instrumentator.instrument(app).expose(app, include_in_schema=False, should_gzip=True)


__all__ = ["configure_metrics", "setup_logging"]

"""Logging and metrics configuration helpers.

FastAPI and Prometheus imports are deferred into the functions that use them so
that importing any submodule of app.observability (e.g. app.observability.log)
does not force the full API dependency stack to load.  Non-API callers (agents,
LLM tracing, CLI) can safely import app.observability.log without requiring
FastAPI or prometheus_fastapi_instrumentator to be installed.
"""

from __future__ import annotations


def setup_logging() -> None:
    """Install the process-wide JSON log formatter (structured logging #3895).

    Delegates to :mod:`app.observability.logging_setup` so API, worker, and
    watcher processes share one formatter implementation (span-schema field
    conventions: trace_id, status, extra). Import stays deferred per this
    module's contract above.
    """
    from app.observability.logging_setup import configure_json_logging

    configure_json_logging()


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

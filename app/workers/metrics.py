"""Minimal opt-in Prometheus metrics endpoint for the outbox worker.

Off by default: the /metrics HTTP server only starts when WORKER_METRICS_PORT
is set to a TCP port in the range 1–65535 (builder-ops-stability spec Issue 6). The
metric objects themselves are always defined so call sites stay unconditional;
they are only observable once the server is enabled.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from wsgiref.simple_server import WSGIServer

from prometheus_client import Counter, Gauge, start_http_server

logger = logging.getLogger(__name__)

WORKER_METRICS_PORT_ENV = "WORKER_METRICS_PORT"

WORKER_LAST_TICK_TIMESTAMP = Gauge(
    "pkm_worker_last_tick_timestamp_seconds",
    "Unix timestamp of the outbox worker's most recent poll tick.",
)
WORKER_PROCESSED = Counter(
    "pkm_worker_processed_total",
    "Outbox messages processed by the worker.",
)


def resolve_worker_metrics_port(environ: Mapping[str, str] | None = None) -> int | None:
    """Return the configured metrics port, or None when metrics are off."""
    raw = (environ if environ is not None else os.environ).get(WORKER_METRICS_PORT_ENV, "")
    raw = raw.strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; worker metrics stay off", WORKER_METRICS_PORT_ENV, raw)
        return None
    if not 1 <= port <= 65535:
        return None
    return port


def maybe_start_worker_metrics_server(
    environ: Mapping[str, str] | None = None,
) -> WSGIServer | None:
    """Start the prometheus_client /metrics server when configured; else no-op."""
    port = resolve_worker_metrics_port(environ)
    if port is None:
        return None
    server, _thread = start_http_server(port)
    logger.info("worker metrics server listening on port %s (/metrics)", port)
    return server

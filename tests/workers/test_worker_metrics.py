"""Opt-in Prometheus metrics endpoint for the outbox worker (builder-ops-stability Issue 6).

Contract: the worker exposes /metrics via prometheus_client only when
WORKER_METRICS_PORT is a TCP port in the range 1–65535; it stays off by default.
"""

from __future__ import annotations

import socket
import urllib.request

import pytest

from app.workers.metrics import (
    WORKER_METRICS_PORT_ENV,
    maybe_start_worker_metrics_server,
    resolve_worker_metrics_port,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_metrics_server_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKER_METRICS_PORT_ENV, raising=False)
    assert resolve_worker_metrics_port() is None
    assert maybe_start_worker_metrics_server() is None


@pytest.mark.parametrize("raw", ["", "   ", "0", "-1", "65536", "not-a-port"])
def test_metrics_port_invalid_values_stay_off(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    def fail_if_started(port: int) -> None:
        raise AssertionError(f"metrics server unexpectedly started on port {port}")

    monkeypatch.setenv(WORKER_METRICS_PORT_ENV, raw)
    monkeypatch.setattr("app.workers.metrics.start_http_server", fail_if_started)
    assert resolve_worker_metrics_port() is None
    assert maybe_start_worker_metrics_server() is None


def test_metrics_server_starts_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv(WORKER_METRICS_PORT_ENV, str(port))
    server = maybe_start_worker_metrics_server()
    assert server is not None
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/metrics", timeout=5
        ) as response:
            assert response.status == 200
            body = response.read()
    finally:
        server.shutdown()
    assert b"pkm_worker_last_tick_timestamp_seconds" in body
    assert b"pkm_worker_processed_total" in body

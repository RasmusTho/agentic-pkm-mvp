"""Regression tests for the prod-down backstop probe alert state machine."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROBE_MODULE_DIR = Path(__file__).parent.parent.parent / "ops" / "host-setup" / "mac-mini"
sys.path.insert(0, str(PROBE_MODULE_DIR))

import prod_probe  # noqa: E402


def _healthy_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    if url.endswith("/readyz"):
        return 200, {"state": "running", "reason": "ok"}
    if url.endswith("/api/health"):
        return 200, {"ok": True, "required_ok": True, "checks": {}}
    raise AssertionError(f"unexpected URL: {url}")


def _down_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    if url.endswith("/readyz"):
        raise ConnectionError("Connection refused")
    if url.endswith("/api/health"):
        return 200, {"ok": False, "required_ok": False}
    raise AssertionError(f"unexpected URL: {url}")


def _required_ok_false_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    if url.endswith("/readyz"):
        return 200, {"state": "degraded", "reason": "required checks failing"}
    if url.endswith("/api/health"):
        return 200, {"ok": True, "required_ok": False, "checks": {"db": {"ok": False}}}
    raise AssertionError(f"unexpected URL: {url}")


def _make_spy_channel() -> MagicMock:
    return MagicMock(spec=prod_probe.NullChannel)


def _write_fresh_heartbeat(tmp_path: Path) -> Path:
    hb_path = tmp_path / "worker_heartbeat.json"
    hb_path.write_text(json.dumps({"ts": time.time()}))
    return hb_path


def test_sustained_outage_alerts_once_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)

    hb_path = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()
    down_kwargs: dict[str, Any] = dict(
        base_url="http://localhost:9999",
        heartbeat_path=str(hb_path),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_down_http_get,
    )
    healthy_kwargs: dict[str, Any] = dict(
        base_url="http://localhost:9999",
        heartbeat_path=str(hb_path),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_healthy_http_get,
    )

    assert prod_probe.run_probe(**down_kwargs) is False
    assert channel.send.call_count == 1
    assert "down" in channel.send.call_args_list[0].args[0].lower()
    assert state_file.exists()
    assert json.loads(state_file.read_text())["status"] == "down"

    assert prod_probe.run_probe(**down_kwargs) is False
    assert channel.send.call_count == 1
    assert state_file.exists()

    assert prod_probe.run_probe(**healthy_kwargs) is True
    assert channel.send.call_count == 2
    assert "recover" in channel.send.call_args_list[1].args[0].lower()
    assert not state_file.exists()


def test_distinct_outage_realerts_after_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)

    hb_path = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()
    common_kwargs: dict[str, Any] = dict(
        base_url="http://localhost:9999",
        heartbeat_path=str(hb_path),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_down_http_get,
    )

    assert prod_probe.run_probe(**common_kwargs) is False
    assert channel.send.call_count == 1

    assert prod_probe.run_probe(
        **{**common_kwargs, "http_get": _healthy_http_get}
    ) is True
    assert channel.send.call_count == 2
    assert "recover" in channel.send.call_args_list[1].args[0].lower()
    assert not state_file.exists()

    assert prod_probe.run_probe(**common_kwargs) is False
    assert channel.send.call_count == 3
    assert "down" in channel.send.call_args_list[2].args[0].lower()
    assert state_file.exists()


def test_probe_reads_required_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)

    hb_path = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()

    result = prod_probe.run_probe(
        base_url="http://localhost:9999",
        heartbeat_path=str(hb_path),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_required_ok_false_http_get,
    )

    assert result is False
    channel.send.assert_called_once()
    assert "required_ok" in channel.send.call_args[0][1].lower()

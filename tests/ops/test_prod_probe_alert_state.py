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


def test_probe_uses_explicit_environment_and_correlates_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "test-probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
    heartbeat = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()
    common = {
        "base_url": "http://127.0.0.1:18002",
        "heartbeat_path": str(heartbeat),
        "heartbeat_stale_seconds": 300.0,
        "channel": channel,
        "environment": "test",
    }

    assert prod_probe.run_probe(**common, http_get=_down_http_get) is False
    down_subject, down_body = channel.send.call_args.args
    assert down_subject == "TEST down - Yggdrasil"
    assert "environment: test" in down_body
    assert "severity: warning" in down_body
    assert "transition: down" in down_body
    assert "timestamp_utc:" in down_body
    assert "source_system: yggdrasil-host-probe" in down_body
    assert "remediation: https://github.com/" in down_body
    correlation_id = json.loads(state_file.read_text())["correlation_id"]
    assert correlation_id in down_body

    assert prod_probe.run_probe(**common, http_get=_healthy_http_get) is True
    recovery_subject, recovery_body = channel.send.call_args_list[-1].args
    assert recovery_subject == "TEST recovered - Yggdrasil"
    assert "transition: recovered" in recovery_body
    assert "severity: info" in recovery_body
    assert correlation_id in recovery_body


def test_probe_runtime_refuses_missing_environment_and_target_config(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(prod_probe, "PROBE_ENVIRONMENT", "")
    monkeypatch.setattr(prod_probe, "PROBE_BASE_URL", "")
    monkeypatch.setattr(prod_probe, "WORKER_HEARTBEAT_PATH", "")
    monkeypatch.setattr(prod_probe, "PROBE_ALERT_CHANNEL", "")
    monkeypatch.delenv("PROBE_STATE_FILE", raising=False)
    monkeypatch.delenv("PROD_PROBE_STATE_FILE", raising=False)

    assert prod_probe.main([]) == 78
    assert "PROBE_ENVIRONMENT must be test or prod" in caplog.text


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"])
def test_non_finite_worker_heartbeat_timestamp_fails_closed(
    tmp_path: Path, timestamp: float | str
) -> None:
    heartbeat = tmp_path / "worker_heartbeat.json"
    heartbeat.write_text(json.dumps({"ts": timestamp}))

    healthy, reason = prod_probe._probe_worker_heartbeat(str(heartbeat))

    assert healthy is False
    assert reason == "worker heartbeat timestamp invalid"


def test_future_worker_heartbeat_timestamp_fails_closed(tmp_path: Path) -> None:
    heartbeat = tmp_path / "worker_heartbeat.json"
    heartbeat.write_text(json.dumps({"ts": time.time() + 60}))

    healthy, reason = prod_probe._probe_worker_heartbeat(str(heartbeat))

    assert healthy is False
    assert reason == "worker heartbeat timestamp invalid"


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_non_finite_or_non_positive_heartbeat_threshold_fails_closed(
    tmp_path: Path, threshold: float
) -> None:
    heartbeat = _write_fresh_heartbeat(tmp_path)

    healthy, reason = prod_probe._probe_worker_heartbeat(
        str(heartbeat), stale_seconds=threshold
    )

    assert healthy is False
    assert reason == "worker heartbeat stale threshold invalid"


@pytest.mark.parametrize("threshold", ["nan", "inf", "-inf", "0", "-1", "invalid"])
def test_runtime_config_rejects_invalid_heartbeat_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, threshold: str
) -> None:
    monkeypatch.setattr(prod_probe, "PROBE_ENVIRONMENT", "test")
    monkeypatch.setattr(prod_probe, "PROBE_BASE_URL", "http://127.0.0.1:18002")
    monkeypatch.setattr(
        prod_probe, "WORKER_HEARTBEAT_PATH", str(tmp_path / "worker_heartbeat.json")
    )
    monkeypatch.setattr(prod_probe, "PROBE_ALERT_CHANNEL", "discord")
    monkeypatch.setenv("PROBE_STATE_FILE", str(tmp_path / "probe.state"))
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", threshold)

    with pytest.raises(ValueError, match="WORKER_HEARTBEAT_STALE_SECONDS is invalid"):
        prod_probe._runtime_config()

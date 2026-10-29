"""Regression tests for the prod-down backstop probe alert state machine."""

from __future__ import annotations

import json
import io
import sys
import time
from email.message import Message
from pathlib import Path
from typing import Any
import urllib.request
import urllib.response
from unittest.mock import MagicMock

import pytest

PROBE_MODULE_DIR = Path(__file__).parent.parent.parent / "ops" / "host-setup" / "mac-mini"
sys.path.insert(0, str(PROBE_MODULE_DIR))

import prod_probe  # noqa: E402
import notification_channels  # noqa: E402


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


def test_unconfirmed_discord_delivery_does_not_commit_outage_state(
    tmp_path, monkeypatch
):
    """Exercise the probe, real adapter and real opener error policy together."""
    state_file = tmp_path / "probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
    secret_file = tmp_path / "runtime.env"
    secret_file.write_text(
        "DISCORD_WEBHOOK=https://discord.com/api/webhooks/123456789/synthetic-token\n"
    )
    secret_file.chmod(0o600)
    channel = notification_channels.DiscordChannel(secret_file)
    statuses = iter([204, 200, 204, 200])
    requests = []

    def https_open(_handler, request):
        requests.append(request)
        status = next(statuses)
        body = json.dumps({
            "id": "123456790", "channel_id": "123456791", "webhook_id": "123456789"
        }).encode() if status == 200 else b""
        response = urllib.response.addinfourl(
            io.BytesIO(body), Message(), request.full_url, status
        )
        response.msg = "synthetic response"
        return response

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", https_open)
    monkeypatch.setattr(urllib.request, "_opener", None)
    arguments = {
        "channel": channel,
        "environment": "test",
        "http_get": _down_http_get,
        "heartbeat_path": _write_fresh_heartbeat(tmp_path),
    }
    assert prod_probe.run_probe(**arguments) is False
    assert not state_file.exists()
    assert prod_probe.run_probe(**arguments) is False
    incident = json.loads(state_file.read_text())
    assert incident["environment"] == "test"
    correlation = incident["correlation_id"]
    assert prod_probe.run_probe(**arguments) is False
    assert len(requests) == 2
    assert json.loads(state_file.read_text())["correlation_id"] == correlation
    arguments["http_get"] = _healthy_http_get
    assert prod_probe.run_probe(**arguments) is True
    assert len(requests) == 3
    assert json.loads(state_file.read_text())["correlation_id"] == correlation
    assert prod_probe.run_probe(**arguments) is True
    assert len(requests) == 4
    assert not state_file.exists()
    payloads = [json.loads(request.data)["content"] for request in requests]
    assert correlation in payloads[1]
    assert correlation in payloads[2]
    assert correlation in payloads[3]


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
        environment="test",
    )
    healthy_kwargs: dict[str, Any] = dict(
        base_url="http://localhost:9999",
        heartbeat_path=str(hb_path),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_healthy_http_get,
        environment="test",
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
        environment="test",
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


@pytest.mark.parametrize("heartbeat_payload", [[], None, 1, "heartbeat"])
def test_non_object_heartbeat_json_still_sends_down_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    heartbeat_payload: Any,
) -> None:
    state_file = tmp_path / "probe.state"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
    heartbeat = tmp_path / "worker_heartbeat.json"
    heartbeat.write_text(json.dumps(heartbeat_payload))
    channel = _make_spy_channel()

    result = prod_probe.run_probe(
        base_url="http://127.0.0.1:18000",
        heartbeat_path=str(heartbeat),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_required_ok_false_http_get,
        environment="prod",
    )

    assert result is False
    channel.send.assert_called_once()
    assert "worker heartbeat malformed: expected an object" in channel.send.call_args.args[1]
    assert json.loads(state_file.read_text())["environment"] == "prod"


@pytest.mark.parametrize(
    "invalid_state",
    [
        {"status": "down"},
        {
            "status": "down",
            "ts": True,
            "environment": "prod",
            "correlation_id": "89e3b9b9-5869-4f74-91ef-446d99b63295",
            "failures": ["health down"],
        },
        {
            "status": "down",
            "ts": 1,
            "environment": "prod",
            "correlation_id": "not-a-uuid",
            "failures": ["health down"],
        },
        {
            "status": "down",
            "ts": 1,
            "environment": "prod",
            "correlation_id": "89e3b9b9-5869-4f74-91ef-446d99b63295",
            "failures": "health down",
        },
    ],
)
def test_invalid_saved_alert_state_does_not_suppress_down_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_state: dict[str, Any],
) -> None:
    state_file = tmp_path / "probe.state"
    state_file.write_text(json.dumps(invalid_state))
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
    heartbeat = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()

    assert prod_probe.run_probe(
        base_url="http://127.0.0.1:18000",
        heartbeat_path=str(heartbeat),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_required_ok_false_http_get,
        environment="prod",
    ) is False

    channel.send.assert_called_once()
    saved_state = json.loads(state_file.read_text())
    assert saved_state["status"] == "down"
    assert saved_state["environment"] == "prod"
    assert saved_state["correlation_id"] in channel.send.call_args.args[1]


def test_alert_state_from_other_environment_does_not_suppress_down_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "probe.state"
    state_file.write_text(
        json.dumps(
            {
                "status": "down",
                "ts": 1,
                "environment": "test",
                "correlation_id": "89e3b9b9-5869-4f74-91ef-446d99b63295",
                "failures": ["test health down"],
            }
        )
    )
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
    heartbeat = _write_fresh_heartbeat(tmp_path)
    channel = _make_spy_channel()

    assert prod_probe.run_probe(
        base_url="http://127.0.0.1:18000",
        heartbeat_path=str(heartbeat),
        heartbeat_stale_seconds=300.0,
        channel=channel,
        http_get=_required_ok_false_http_get,
        environment="prod",
    ) is False

    channel.send.assert_called_once()
    assert "PROD down" in channel.send.call_args.args[0]


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

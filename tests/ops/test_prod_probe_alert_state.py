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


@pytest.fixture
def asynchronous_health(monkeypatch, tmp_path):
    """Actual API -> run_health -> observer/aggregation, with local terminal probes."""
    import asyncio
    import importlib
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    from app.api.routes import health as health_route
    from app.config import activation_scope
    from app.model_access import capability_health
    from app.model_access.health_observer import ProductHealthObserver

    health_module = importlib.import_module("app.cli.health")
    state = SimpleNamespace(
        second=0.0, pending=[], samples=[], requests=[], snapshots=[],
        sample_result="available", complete=True, failure=None, cache_failure=None,
        scope="full", http_seconds=0.0, sample_delay=1.0, readyz_seconds=0.0, iterations=[],
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=state.second)

    class Executor:
        def submit(self, function, *args):
            state.pending.append((state.second + state.sample_delay, function, args))

    def advance(seconds):
        target = state.second + seconds
        if state.complete:
            while state.pending and min(item[0] for item in state.pending) <= target:
                due, function, args = min(state.pending, key=lambda item: item[0])
                state.pending.remove((due, function, args))
                state.second = due
                function(*args)
        state.second = target

    observer = ProductHealthObserver(max_workers=1, max_in_flight=1, clock=Clock.now)
    observer._executor.shutdown(wait=True)
    observer._executor = Executor()
    monkeypatch.setattr(health_module, "PRODUCT_HEALTH_OBSERVER", observer)
    monkeypatch.setattr(health_module, "datetime", Clock)
    monkeypatch.setattr(capability_health, "datetime", Clock)
    monkeypatch.setattr(activation_scope, "runtime_activation_scope", lambda: state.scope)
    monkeypatch.setattr(prod_probe, "time", SimpleNamespace(
        monotonic=lambda: state.second, time=time.time, sleep=advance,
    ))
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", tmp_path / "incident.json")
    monkeypatch.setattr(health_module, "_route_health_observation_key", lambda *_: "synthetic-route")
    monkeypatch.setattr(health_module, "_check_llm_router", lambda: {
        "ok": True, "route_policies": {
            kind: {"effective": {"provider": "synthetic-remote"}, "intent": {}}
            for kind in ("qa", "summary")
        },
    })

    def sample(*_args, **_kwargs):
        state.samples.append(state.second)
        if state.sample_result == "exception":
            raise RuntimeError("synthetic terminal failure")
        return {"status": state.sample_result, "reason_code": (
            "adapter_ready" if state.sample_result == "available" else "adapter_unavailable"
        ), "capabilities": {}}

    monkeypatch.setattr(health_module, "_probe_selected_route", sample)
    for name in (
        "_check_ffmpeg", "_check_yt_dlp", "_check_outbox_path", "_check_dead_letters",
        "_check_panel_actions", "_check_obsidian_dependencies", "_check_llm_providers",
        "_check_companion_diagnostics", "_check_youtube_sync", "_settings_ingestion_status",
        "check_v6_seams", "_check_authority_spine", "_watcher_runtime_status",
    ):
        monkeypatch.setattr(health_module, name, lambda *_a, **_kw: {"ok": True})
    for symbol, failure in (("_db_runtime_status", "db"), ("_worker_runtime_status", "worker"),
                            ("_check_embedding_index", "embedding")):
        monkeypatch.setattr(health_module, symbol,
                            lambda name=failure: {"ok": state.failure != name})
    monkeypatch.setattr(health_module, "_health_vault_root", lambda *_: None)
    monkeypatch.setattr(health_module, "get_runtime_version", lambda: {"git_sha": "synthetic"})
    monkeypatch.setattr(health_module, "active_environment", lambda: "test")
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")

    def http_get(url, timeout=10):
        state.requests.append((state.second, url, timeout))
        if url.endswith("/readyz"):
            state.iterations.append(state.second)
            advance(state.readyz_seconds)
            return (503 if state.failure == "readyz" else 200), {}
        mode = parse_qs(urlsplit(url).query).get("model_access_sampling", ["background"])[0]
        if mode == "cache" and state.cache_failure:
            if state.cache_failure == "unreachable":
                raise ConnectionError("synthetic private endpoint/token must not escape")
            if state.cache_failure == "http":
                return 503, {}
            return 200, []
        assert timeout > 0
        advance(min(state.http_seconds, timeout))
        if timeout < state.http_seconds:
            raise TimeoutError("synthetic finite HTTP deadline")
        payload = asyncio.run(health_route.health(model_access_sampling=mode))
        state.snapshots.append(payload)
        return 200, payload

    state.http_get = http_get
    state.advance = advance
    state.observer = observer
    state.channel = _make_spy_channel()
    state.heartbeat = _write_fresh_heartbeat(tmp_path)
    state.run = lambda: prod_probe.run_probe(
        base_url="http://synthetic", environment="test", http_get=http_get,
        heartbeat_path=str(state.heartbeat), channel=state.channel,
    )
    return state


def test_probe_qualifies_fresh_background_health_at_normal_cadence(asynchronous_health):
    health = asynchronous_health
    health.failure = "embedding"
    assert health.run() is False
    health.failure = None
    incident = prod_probe._load_alert_state()
    assert incident is not None
    correlation = incident["correlation_id"]
    health.second = 60
    assert health.run() is True
    assert health.snapshots[-2]["required_ok"] is False
    assert health.snapshots[-2]["checks"]["llm_access"]["capabilities"]["text_generation"]["freshness"] == "stale"
    assert health.snapshots[-1]["required_ok"] is True
    assert health.samples == [1, 61]
    assert prod_probe._load_alert_state() is None
    assert health.channel.send.call_count == 2
    assert correlation in health.channel.send.call_args.args[1]
    health.second = 120
    assert health.run() is True
    assert health.samples == [1, 61, 121]
    assert health.channel.send.call_count == 2


@pytest.mark.parametrize("failure", [
    "pending", "unavailable", "exception", "stale", "malformed", "unreachable", "http",
    "db", "worker", "embedding", "heartbeat", "readyz", "text-capture",
])
def test_probe_health_acquisition_fails_closed_and_preserves_incident(
    asynchronous_health, failure, caplog,
):
    health = asynchronous_health
    health.failure = "embedding"
    assert health.run() is False
    health.failure = None
    incident = prod_probe._load_alert_state()
    health.second = 60
    if failure == "pending":
        health.complete = False
    elif failure == "stale":
        health.complete = False
    elif failure in {"unavailable", "exception"}:
        health.sample_result = failure
    elif failure in {"malformed", "unreachable", "http"}:
        health.cache_failure = failure
    elif failure == "text-capture":
        health.scope = failure
    elif failure == "heartbeat":
        health.heartbeat.unlink()
    else:
        health.failure = failure
    assert health.run() is False
    assert prod_probe._load_alert_state() == incident
    assert health.channel.send.call_count == 1
    assert "synthetic private" not in caplog.text
    assert len([url for _, url, _ in health.requests if "?" not in url and url.endswith("/api/health")]) == 2


def test_probe_health_qualification_bounds_sampling_and_cache_reads(asynchronous_health, monkeypatch):
    health = asynchronous_health
    health.complete = False
    started = health.second
    assert health.run() is False
    assert health.second - started == 45
    health_requests = [(url, timeout) for _, url, timeout in health.requests if "/api/health" in url]
    assert health_requests[0][0] == "http://synthetic/api/health"
    assert all(url.endswith("?model_access_sampling=cache") for url, _ in health_requests[1:])
    assert len(health_requests) <= 91
    assert len(health.observer._in_flight) == 1
    assert not health.observer._pending_cold and not health.observer._pending_refresh
    assert not health.samples
    # An independent count bound also terminates when the monotonic clock stalls.
    monkeypatch.setattr(prod_probe.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(prod_probe.time, "sleep", lambda _: None)
    health.requests.clear()
    assert health.run() is False
    assert len([url for _, url, _ in health.requests if "/api/health" in url]) == 91
    assert len(health.observer._in_flight) == 1


@pytest.mark.parametrize("reason", [[], {}, None, 42])
def test_malformed_capability_reason_preserves_down_delivery_retry(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", tmp_path / "incident.json")
    channel = _make_spy_channel()
    channel.send.side_effect = [RuntimeError("synthetic delivery failure"), None]
    payload = {"required_ok": False, "checks": {"llm_access": {"capabilities": {
        "text_generation": {"status": "unknown", "reason_code": reason},
    }}}}

    def get(url, timeout=10):
        return 200, {} if url.endswith("/readyz") else payload

    arguments = dict(environment="test", http_get=get, channel=channel,
                     heartbeat_path=str(_write_fresh_heartbeat(tmp_path)))
    assert prod_probe.run_probe(**arguments) is False
    assert not prod_probe.ALERT_STATE_FILE.exists()
    assert prod_probe.run_probe(**arguments) is False
    incident = prod_probe._load_alert_state()
    assert incident is not None
    assert prod_probe.run_probe(**arguments) is False
    assert prod_probe._load_alert_state() == incident
    assert channel.send.call_count == 2




def _synthetic_child_transport(phase, marker_path):
    """Test bootstrap replaces only terminal I/O inside the real disposable child."""
    import ctypes
    import http.client
    import io
    from pathlib import Path
    import socket
    import time

    marked = [None]

    def mark(label):
        if marked[0] != label:
            Path(marker_path).write_text(label)
            marked[0] = label

    def native_block():
        mark(phase)
        ctypes.CDLL(None).usleep(2_000_000)

    if phase == "resolver":
        def resolve(*_a, **_kw):
            native_block()
            raise OSError("synthetic resolver must not connect")
        socket.getaddrinfo = resolve
        return

    body = b'{"required_ok":true}'
    status = 503 if phase in {"error_body", "error_body_fast"} else 200
    header = (f"HTTP/1.1 {status} Synthetic\r\nContent-Length: {len(body)}\r\n\r\n").encode()

    class Stream(io.RawIOBase):
        def __init__(self):
            self.header, self.body = header, body

        def readable(self):
            return True

        def readinto(self, buffer):
            if self.header:
                if phase == "headers":
                    mark(phase)
                    time.sleep(0.02)
                count = 1 if phase == "headers" else len(self.header)
                data, self.header = self.header[:count], self.header[count:]
            elif self.body:
                if phase in {"body", "error_body"}:
                    mark(phase)
                    time.sleep(0.02)
                data, self.body = self.body[:1], self.body[1:]
            else:
                return 0
            buffer[:len(data)] = data
            return len(data)

    class Socket:
        def makefile(self, *_a, **_kw):
            return io.BufferedReader(Stream())

        def sendall(self, _data):
            pass

        def close(self):
            pass

    def connect(connection):
        if phase == "connect":
            native_block()
        connection.sock = Socket()

    http.client.HTTPConnection.connect = connect
    mark("ready")


@pytest.fixture
def http_child_transport(monkeypatch, tmp_path):
    import inspect
    import subprocess
    from types import SimpleNamespace

    original_popen = subprocess.Popen
    state = SimpleNamespace(phase="healthy", children=[], marker=tmp_path / "phase", reply=None, exit_code=0)
    bootstrap = inspect.getsource(_synthetic_child_transport)

    def spawn(arguments, **kwargs):
        assert arguments == [
            sys.executable, "-I", "-c", prod_probe._HTTP_CHILD_CODE,
            str(Path(prod_probe.__file__).resolve().parent),
        ]
        assert kwargs == dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, env={})
        # Keep the production interpreter/isolation/import path and private pipe
        # entry; inject only the deterministic terminal transport after import.
        arguments = list(arguments)
        arguments[3] = (
            "import sys; sys.path.insert(0, sys.argv[1]); import prod_probe\n"
            + bootstrap + f"\n_synthetic_child_transport({state.phase!r}, {str(state.marker)!r})\n"
            + "prod_probe._http_get_child()"
        )
        if state.phase == "startup":
            arguments[3] = (
                f"from pathlib import Path; Path({str(state.marker)!r}).write_text('startup'); "
                "import ctypes; ctypes.CDLL(None).usleep(2_000_000)\n"
                + arguments[3]
            )
        if state.reply is not None:
            reply_code = f"b'x' * {len(state.reply)}" if len(state.reply) > 1024 else repr(state.reply)
            arguments[3] = (
                "import sys; sys.path.insert(0, sys.argv[1]); import prod_probe; "
                f"sys.stdout.buffer.write({reply_code}); sys.stdout.buffer.flush(); "
                f"sys.exit({state.exit_code})"
            )
        child = original_popen(arguments, **kwargs)
        state.children.append(child)
        return child

    monkeypatch.setattr(prod_probe.subprocess, "Popen", spawn)
    return state


@pytest.mark.parametrize("phase", ["startup", "resolver", "connect", "headers", "body", "error_body"])
def test_http_child_deadline_covers_native_resolver_and_actual_urllib(
    http_child_transport, phase,
):
    import os

    transport = http_child_transport
    transport.phase = phase
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        prod_probe._http_get("http://synthetic/api/health", timeout=0.3)
    assert 0.3 <= time.monotonic() - started < 1.3
    assert transport.marker.read_text() == phase
    child, = transport.children
    assert child.returncode is not None
    assert child.stdin.closed and child.stdout.closed
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)


def test_http_child_success_and_error_status_use_private_bounded_protocol(http_child_transport):
    transport = http_child_transport
    assert prod_probe._http_get("http://synthetic/api/health", timeout=1) == (200, {"required_ok": True})
    transport.phase = "error_body_fast"
    # Exercise a normal completed HTTP error without treating the parsed body as success.
    assert prod_probe._http_get("http://synthetic/api/health", timeout=1) == (503, {"required_ok": True})
    assert all(child.returncode == 0 for child in transport.children)


def test_http_child_timeout_preserves_incident_delivery_retry(http_child_transport, tmp_path, monkeypatch):
    transport = http_child_transport
    transport.phase = "resolver"
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", tmp_path / "incident.json")
    channel = _make_spy_channel()
    channel.send.side_effect = [RuntimeError("synthetic delivery failure"), None]

    def get(url, timeout=10):
        if url.endswith("/readyz"):
            return 200, {}
        return prod_probe._http_get(url, timeout=0.3)

    arguments = dict(base_url="http://synthetic", environment="test", http_get=get,
                     channel=channel, heartbeat_path=str(_write_fresh_heartbeat(tmp_path)))
    assert prod_probe.run_probe(**arguments) is False
    assert not prod_probe.ALERT_STATE_FILE.exists()
    assert prod_probe.run_probe(**arguments) is False
    incident = prod_probe._load_alert_state()
    assert incident is not None
    assert prod_probe.run_probe(**arguments) is False
    assert prod_probe._load_alert_state() == incident
    assert channel.send.call_count == 2
    assert len(transport.children) == 3
    assert all(child.returncode is not None for child in transport.children)


def test_http_child_unconfirmed_reaping_stops_before_next_request(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    calls = []
    def wait(*, timeout):
        assert timeout == prod_probe._HTTP_CHILD_CLEANUP_SECONDS
        raise subprocess.TimeoutExpired("synthetic child", timeout)
    def communicate(*_a, **_kw):
        raise subprocess.TimeoutExpired("synthetic child", 0.1)
    child = SimpleNamespace(poll=lambda: None, kill=lambda: calls.append("kill"),
                            wait=wait, communicate=communicate, stdin=None, stdout=None, stderr=None)
    monkeypatch.setattr(prod_probe.subprocess, "Popen", lambda *_a, **_kw: child)
    monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", tmp_path / "incident.json")
    with pytest.raises(prod_probe._HttpChildCleanupFailed, match="termination unconfirmed"):
        prod_probe.run_probe(base_url="http://synthetic", environment="test",
                             heartbeat_path=str(_write_fresh_heartbeat(tmp_path)), channel=_make_spy_channel())
    assert calls == ["kill"]


@pytest.mark.parametrize("payload", [
    b"not json", b'{"status":true,"body":{}}', b'{"status":200,"body":[]}',
    b'{"status":200,"body":{},"error":true}', b"x" * (prod_probe._HTTP_MAX_BYTES + 1),
], ids=["invalid-json", "boolean-status", "list-body", "extra-key", "oversized"])
def test_http_child_rejects_malformed_or_oversized_private_response(http_child_transport, payload):
    transport = http_child_transport
    transport.reply = payload
    with pytest.raises((ValueError, TimeoutError), match="probe HTTP"):
        prod_probe._http_get("http://synthetic/api/health", timeout=1)
    assert all(child.returncode == 0 for child in transport.children)


def test_http_child_does_not_accept_partial_success_from_failed_child(http_child_transport):
    transport = http_child_transport
    transport.reply = b'{"status":200,"body":{"required_ok":true}}'
    transport.exit_code = 1
    with pytest.raises(TimeoutError, match="response unavailable"):
        prod_probe._http_get("http://synthetic/api/health", timeout=1)
    assert transport.children[0].returncode == 1


def test_http_child_bounds_private_request_before_spawning(monkeypatch):
    monkeypatch.setattr(prod_probe.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("must not spawn"))
    with pytest.raises(ValueError, match="request too large"):
        prod_probe._http_get("http://synthetic/" + "x" * prod_probe._HTTP_MAX_REQUEST_BYTES)


@pytest.mark.parametrize("sample_delay", [25, 50, 85, 100])
def test_probe_main_qualifies_slow_samples_at_nominal_cadence(asynchronous_health, monkeypatch, sample_delay):
    import subprocess
    from uuid import uuid4

    health = asynchronous_health
    health.sample_delay = sample_delay
    health.http_seconds = 2.0
    correlation = str(uuid4())
    prod_probe._record_outage_state(["synthetic prior outage"], environment="test", correlation_id=correlation)
    initial_state = prod_probe._load_alert_state()
    packets = []

    class StopLoop(BaseException):
        pass

    # Actual main -> run_probe -> _http_get private request/remaining-budget
    # boundary -> actual API/run_health/observer. Real child kill/reap and native
    # transport waits are proved separately by the subprocess regressions.
    class Child:
        stdin = stdout = stderr = None
        returncode = None

        def communicate(self, request, *, timeout):
            packet = json.loads(request)
            packets.append((health.second, packet, timeout))
            assert 0 < timeout <= packet["timeout"] <= 10
            try:
                status, body = health.http_get(packet["url"], timeout=timeout)
            except TimeoutError:
                raise subprocess.TimeoutExpired("synthetic reader", timeout) from None
            self.returncode = 0
            return json.dumps({"status": status, "body": body}).encode(), None

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self, *, timeout):
            assert timeout == prod_probe._HTTP_CHILD_CLEANUP_SECONDS
            return self.returncode

    monkeypatch.setattr(prod_probe.subprocess, "Popen", lambda *_a, **_kw: Child())
    monkeypatch.setattr(prod_probe, "_runtime_config", lambda: ("test", 60, 60.0))
    monkeypatch.setenv("PROBE_STATE_FILE", str(prod_probe.ALERT_STATE_FILE))
    original_run = prod_probe.run_probe
    monkeypatch.setattr(prod_probe, "run_probe", lambda **kwargs: original_run(
        **kwargs, base_url="http://synthetic", heartbeat_path=str(health.heartbeat), channel=health.channel,
    ))
    original_advance = health.advance
    sleeps = []

    def sleep(seconds):
        original_advance(seconds)
        if seconds > 0.5:
            sleeps.append(seconds)
            if prod_probe._load_alert_state() is None:
                raise StopLoop()
            assert prod_probe._load_alert_state() == initial_state
            assert len(sleeps) < 4, "finite healthy sample must recover at nominal cadence"
            health.readyz_seconds = 9.0  # Slow success below the existing 10-second HTTP deadline.

    monkeypatch.setattr(prod_probe.time, "sleep", sleep)
    with pytest.raises(StopLoop):
        prod_probe.main(["--loop"])
    assert health.iterations == ([0.0] if sample_delay == 25 else [0.0, 60.0])
    assert health.channel.send.call_count == 1
    assert "recovered" in health.channel.send.call_args.args[0]
    assert correlation in health.channel.send.call_args.args[1]
    assert health.samples == [2.0 + sample_delay]
    assert health.snapshots[-1]["checks"]["llm_access"]["capabilities"]["text_generation"]["freshness"] == "fresh"
    assert len([packet for _, packet, _ in packets if packet["url"].endswith("/api/health")]) == len(health.iterations)
    assert all(packet["url"].endswith(("/readyz", "/api/health", "?model_access_sampling=cache")) for _, packet, _ in packets)
    assert any(timeout < 10 for _, _, timeout in packets) if sample_delay != 25 else True

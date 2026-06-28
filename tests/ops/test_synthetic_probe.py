"""tests/ops/test_synthetic_probe.py — unit tests for the prod-down backstop probe.

Tests exercise the REAL probe script logic (prod_probe.run_probe + helpers)
with an injected HTTP layer and notification channel — NOT a stub of the thing
under test.  All three acceptance-criteria tests correspond 1:1 to Verify targets
in the issue and spec doc.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import the probe module under test
# ---------------------------------------------------------------------------
PROBE_MODULE_DIR = (
    Path(__file__).parent.parent.parent
    / "ops" / "host-setup" / "mac-mini"
)
sys.path.insert(0, str(PROBE_MODULE_DIR))

import prod_probe  # noqa: E402 — intentional late import after sys.path edit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _healthy_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    """Stub that simulates a fully healthy prod stack."""
    if url.endswith("/readyz"):
        return 200, {"state": "running", "reason": "ok"}
    if url.endswith("/api/health"):
        return 200, {"ok": True, "required_ok": True, "checks": {}}
    return 404, {}


def _down_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    """Stub that simulates a prod-down scenario (readyz 503, health required_ok=false)."""
    if url.endswith("/readyz"):
        raise Exception("Connection refused")
    if url.endswith("/api/health"):
        # Even if we somehow reach health, required_ok is false
        return 200, {"ok": False, "required_ok": False}
    return 503, {}


def _health_ok_but_required_ok_false_http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    """Stub: top-level ok=true but required_ok=false — must still alert."""
    if url.endswith("/readyz"):
        return 200, {"state": "degraded", "reason": "required checks failing"}
    if url.endswith("/api/health"):
        return 200, {"ok": True, "required_ok": False, "checks": {"db": {"ok": False}}}
    return 404, {}


def _make_null_channel() -> prod_probe.NullChannel:
    return prod_probe.NullChannel()


def _make_spy_channel() -> MagicMock:
    """A mock that records calls to send()."""
    channel = MagicMock(spec=prod_probe.NullChannel)
    return channel


def _write_fresh_heartbeat(tmp_path: Path) -> Path:
    hb_path = tmp_path / "worker_heartbeat.json"
    # Real shape: app/runtime/worker_heartbeat.py writes the epoch under "ts".
    hb_path.write_text(json.dumps({"ts": time.time()}))
    return hb_path


def _write_stale_heartbeat(tmp_path: Path) -> Path:
    hb_path = tmp_path / "worker_heartbeat.json"
    # 120 s old — stale at any reasonable threshold. Real field is "ts".
    hb_path.write_text(json.dumps({"ts": time.time() - 120}))
    return hb_path


# ---------------------------------------------------------------------------
# AC1: test_probe_pushes_once_on_prod_down
# ---------------------------------------------------------------------------
class TestProbePushesOnceOnProdDown:
    """AC1 — exactly ONE push on prod-down, within the probe interval."""

    def test_probe_pushes_once_on_prod_down(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate prod-down (stub HTTP to fail); assert probe dispatches exactly one push."""
        state_file = tmp_path / "probe.state"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        # Fresh heartbeat so only the HTTP checks fail (isolate the test to network failure)
        hb_path = _write_fresh_heartbeat(tmp_path)

        channel = _make_spy_channel()

        result = prod_probe.run_probe(
            base_url="http://localhost:9999",  # nothing listening — will fail
            heartbeat_path=str(hb_path),
            heartbeat_stale_seconds=300.0,
            channel=channel,
            http_get=_down_http_get,
        )

        assert result is False, "probe should report unhealthy"
        channel.send.assert_called_once(), "exactly one push must be dispatched on first prod-down"
        call_args = channel.send.call_args
        # subject should mention prod-down
        subject = call_args[0][0]
        assert "Prod down" in subject or "prod" in subject.lower()


# ---------------------------------------------------------------------------
# AC2: test_probe_no_duplicate_push
# ---------------------------------------------------------------------------
class TestProbeNoDuplicatePush:
    """AC2 — debounce: second prod-down in same interval does NOT send duplicate."""

    def test_probe_no_duplicate_push(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two consecutive prod-down calls within the same epoch bucket → only 1 push total."""
        state_file = tmp_path / "probe.state"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        hb_path = _write_fresh_heartbeat(tmp_path)

        channel = _make_spy_channel()
        common_kwargs: dict[str, Any] = dict(
            base_url="http://localhost:9999",
            heartbeat_path=str(hb_path),
            heartbeat_stale_seconds=300.0,
            channel=channel,
            http_get=_down_http_get,
        )

        # First call — alert should fire
        result1 = prod_probe.run_probe(**common_kwargs)
        assert result1 is False
        assert channel.send.call_count == 1, "first call must send exactly one alert"

        # Second call in the same epoch — NO additional push (debounce)
        result2 = prod_probe.run_probe(**common_kwargs)
        assert result2 is False
        assert channel.send.call_count == 1, (
            "second prod-down in the same interval must not send a duplicate push"
        )

    def test_probe_no_duplicate_push_after_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restart does not re-fire if state file is present from same epoch."""
        state_file = tmp_path / "probe.state"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        hb_path = _write_fresh_heartbeat(tmp_path)
        channel = _make_spy_channel()
        common_kwargs: dict[str, Any] = dict(
            base_url="http://localhost:9999",
            heartbeat_path=str(hb_path),
            heartbeat_stale_seconds=300.0,
            channel=channel,
            http_get=_down_http_get,
        )

        # First run sends alert
        prod_probe.run_probe(**common_kwargs)
        assert channel.send.call_count == 1

        # Simulated restart: fresh channel object (different object), same state file
        channel2 = _make_spy_channel()
        prod_probe.run_probe(**{**common_kwargs, "channel": channel2})
        assert channel2.send.call_count == 0, (
            "a restart within the same interval must not re-fire the alert"
        )


# ---------------------------------------------------------------------------
# AC3: test_probe_reads_required_ok
# ---------------------------------------------------------------------------
class TestProbeReadsRequiredOk:
    """AC3 — probe gates on /api/health required_ok, not the top-level ok."""

    def test_probe_reads_required_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ok=true but required_ok=false MUST trigger an alert.

        This is the key correctness test: if the probe mistakenly checked
        top-level ok it would miss this failure condition.
        """
        state_file = tmp_path / "probe.state"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        hb_path = _write_fresh_heartbeat(tmp_path)
        channel = _make_spy_channel()

        result = prod_probe.run_probe(
            base_url="http://localhost:9999",
            heartbeat_path=str(hb_path),
            heartbeat_stale_seconds=300.0,
            channel=channel,
            http_get=_health_ok_but_required_ok_false_http_get,
        )

        assert result is False, (
            "probe must report unhealthy when required_ok=false, even if ok=true"
        )
        channel.send.assert_called_once()
        # The alert body should indicate the health check is the failure
        body = channel.send.call_args[0][1]
        assert "required_ok" in body.lower() or "health" in body.lower(), (
            "alert body should reference the health/required_ok failure"
        )

    def test_probe_healthy_when_required_ok_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When required_ok=true (and readyz+heartbeat healthy), no alert is sent."""
        state_file = tmp_path / "probe.state"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        hb_path = _write_fresh_heartbeat(tmp_path)
        channel = _make_spy_channel()

        result = prod_probe.run_probe(
            base_url="http://localhost:9999",
            heartbeat_path=str(hb_path),
            heartbeat_stale_seconds=300.0,
            channel=channel,
            http_get=_healthy_http_get,
        )

        assert result is True
        channel.send.assert_not_called()


# ---------------------------------------------------------------------------
# Additional unit tests for sub-components
# ---------------------------------------------------------------------------
class TestProbeHelpers:
    """Unit tests for internal probe helpers."""

    def test_probe_health_required_ok_rejects_missing_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A health response with no required_ok field counts as failure."""
        def http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
            if url.endswith("/api/health"):
                return 200, {"ok": True}  # required_ok absent
            return 404, {}

        ok, reason = prod_probe._probe_health_required_ok(
            "http://x", http_get=http_get
        )
        assert ok is False
        assert "required_ok" in reason.lower() or "None" in reason

    def test_probe_worker_heartbeat_stale(self, tmp_path: Path) -> None:
        hb_path = _write_stale_heartbeat(tmp_path)
        ok, reason = prod_probe._probe_worker_heartbeat(
            str(hb_path), stale_seconds=30.0
        )
        assert ok is False
        assert "stale" in reason.lower()

    def test_probe_worker_heartbeat_missing(self, tmp_path: Path) -> None:
        ok, reason = prod_probe._probe_worker_heartbeat(
            str(tmp_path / "nonexistent.json"), stale_seconds=30.0
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_build_channel_ntfy(self) -> None:
        ch = prod_probe.build_channel("ntfy")
        assert isinstance(ch, prod_probe.NtfyChannel)

    def test_build_channel_telegram(self) -> None:
        ch = prod_probe.build_channel("telegram")
        assert isinstance(ch, prod_probe.TelegramChannel)

    def test_build_channel_mail(self) -> None:
        ch = prod_probe.build_channel("mail")
        assert isinstance(ch, prod_probe.MailChannel)

    def test_build_channel_none(self) -> None:
        ch = prod_probe.build_channel("none")
        assert isinstance(ch, prod_probe.NullChannel)

    def test_build_channel_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown PROD_PROBE_CHANNEL"):
            prod_probe.build_channel("carrier-pigeon")

    def test_alert_state_debounce_epoch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_alert_already_sent returns False before first send, True after _record_alert_sent."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(prod_probe, "ALERT_STATE_FILE", state_file)
        monkeypatch.setattr(prod_probe, "PROBE_INTERVAL_SECONDS", 60)

        assert prod_probe._alert_already_sent() is False
        prod_probe._record_alert_sent()
        assert prod_probe._alert_already_sent() is True


# ---------------------------------------------------------------------------
# Real-environment wiring (the Codex P1s: ts field / host port / host path / install)
# ---------------------------------------------------------------------------
class TestProbeRealEnvironmentWiring:
    """Guards that the probe is configured for the REAL host prod environment,
    not the in-container defaults (these are the four Codex P1s)."""

    _PROBE_PY = PROBE_MODULE_DIR / "prod_probe.py"
    _PLIST = PROBE_MODULE_DIR / "com.yggdrasil.prod-probe.plist"
    _INSTALL = PROBE_MODULE_DIR / "install.sh"

    def test_heartbeat_reads_ts_field(self, tmp_path: Path) -> None:
        """The probe must read the real heartbeat `ts` field (epoch). A fresh
        `ts` heartbeat is NOT stale; an old `ts` IS stale."""
        fresh = tmp_path / "fresh.json"
        fresh.write_text(json.dumps({"ts": time.time()}))
        ok, _ = prod_probe._probe_worker_heartbeat(str(fresh), 60.0)
        assert ok, "a fresh `ts` heartbeat must be read as healthy"

        stale = tmp_path / "stale.json"
        stale.write_text(json.dumps({"ts": time.time() - 600}))
        ok, reason = prod_probe._probe_worker_heartbeat(str(stale), 60.0)
        assert not ok and "stale" in reason, "an old `ts` heartbeat must be stale"

    def test_default_base_url_targets_host_prod_port_18000(self) -> None:
        """Default probe URL must be the HOST prod port 18000, not in-container 8000."""
        src = self._PROBE_PY.read_text()
        assert '"http://127.0.0.1:18000"' in src, "prod_probe.py default must target :18000"
        assert "localhost:8000" not in src, "must not default to the in-container :8000"
        plist = self._PLIST.read_text()
        assert "127.0.0.1:18000" in plist and "localhost:8000" not in plist

    def test_plist_uses_host_heartbeat_path_not_container(self) -> None:
        """The launchd plist (runs on the macOS host) must not point at the
        container /app/tmp path; it uses a substituted absolute host path."""
        plist = self._PLIST.read_text()
        assert "/app/tmp/worker_heartbeat.json" not in plist
        assert "__HEARTBEAT__" in plist

    def test_install_substitutes_and_loads_prod_probe_plist(self) -> None:
        """install.sh must substitute the plist placeholders and load it, else the
        documented install path leaves no working probe."""
        install = self._INSTALL.read_text()
        for ph in ("__PYTHON__", "__PROBE__", "__HEARTBEAT__"):
            assert ph in install, f"install.sh must substitute {ph}"
        assert "com.yggdrasil.prod-probe.plist" in install
        assert "launchctl load" in install and "PROBE_PLIST" in install
        # The plist still carries the placeholders to be substituted at install.
        plist = self._PLIST.read_text()
        assert "__PYTHON__" in plist and "__PROBE__" in plist

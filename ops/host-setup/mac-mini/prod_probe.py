#!/usr/bin/env python3
"""Scheduled channel health probe — transition-based backstop alert.

Curls /readyz AND /api/health required_ok, checks worker-heartbeat staleness.
On the first transition into an outage it dispatches one down alert and records
the down state. Repeated down probes suppress while the outage remains active.
On the first healthy run after recovery it emits one recovery signal and clears
the outage state so a later distinct outage can alert again.

The environment, endpoint, heartbeat path, state path, and alert channel are
explicit runtime inputs. The Linux systemd host unit supplies them for TARS;
the old Mac LaunchAgent remains a legacy template only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from notification_channels import (
    NotificationChannel,
    NullChannel as NullChannel,
    ascii_header as ascii_header,
    build_channel,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [prod-probe] %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("prod_probe")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# The probe is shared by target channels. Runtime endpoints and environment must
# come from an explicit target config; never infer production from a default.
PROBE_BASE_URL = os.environ.get("PROBE_BASE_URL", "")
WORKER_HEARTBEAT_PATH = os.environ.get("WORKER_HEARTBEAT_PATH", "")
WORKER_HEARTBEAT_STALE_SECONDS = float(
    os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", "60")
)
ALERT_STATE_FILE = Path(
    os.environ.get("PROBE_STATE_FILE")
    or os.environ.get("PROD_PROBE_STATE_FILE")
    or "tmp/probe_alert.state"
)
PROBE_ENVIRONMENT = os.environ.get("PROBE_ENVIRONMENT", "")
PROBE_ALERT_CHANNEL = os.environ.get("PROBE_ALERT_CHANNEL") or os.environ.get(
    "PROD_PROBE_CHANNEL", ""
)
PROBE_REMEDIATION_URL = os.environ.get(
    "PROBE_REMEDIATION_URL",
    "https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md",
)
PROBE_SOURCE_SYSTEM = "yggdrasil-host-probe"


# ---------------------------------------------------------------------------
# Outage state
# ---------------------------------------------------------------------------
def _load_alert_state() -> dict[str, Any] | None:
    """Return the persisted alert state, or None if absent/invalid."""
    if not ALERT_STATE_FILE.exists():
        return None
    try:
        payload = json.loads(ALERT_STATE_FILE.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _outage_state_is_active(state: dict[str, Any] | None) -> bool:
    return bool(state and state.get("status") == "down")


def _record_outage_state(
    failures: list[str], *, environment: str, correlation_id: str
) -> None:
    """Persist the current outage state after a successful down alert."""
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_FILE.write_text(
        json.dumps(
            {
                "status": "down",
                "ts": int(time.time()),
                "environment": environment,
                "correlation_id": correlation_id,
                "failures": failures,
            },
            sort_keys=True,
        )
    )


def _clear_alert_state() -> None:
    try:
        ALERT_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def _alert_severity(environment: str) -> str:
    return "critical" if environment == "prod" else "warning"


def _alert_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _alert_body(
    *,
    environment: str,
    severity: str,
    transition: str,
    correlation_id: str,
    details: list[str],
) -> str:
    lines = [
        f"source_system: {PROBE_SOURCE_SYSTEM}",
        f"environment: {environment}",
        f"severity: {severity}",
        f"transition: {transition}",
        f"timestamp_utc: {_alert_timestamp()}",
        f"correlation_id: {correlation_id}",
    ]
    if details:
        lines.extend(["failures:", *[f"  - {detail}" for detail in details]])
    lines.append(f"remediation: {PROBE_REMEDIATION_URL}")
    return "\n".join(lines)


def _send_down_alert(
    channel: NotificationChannel,
    failures: list[str],
    *,
    environment: str,
    correlation_id: str,
) -> bool:
    subject = f"{environment.upper()} down - Yggdrasil"
    body = _alert_body(
        environment=environment,
        severity=_alert_severity(environment),
        transition="down",
        correlation_id=correlation_id,
        details=failures,
    )
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send prod-down alert: %s", exc)
        return False
    _record_outage_state(
        failures, environment=environment, correlation_id=correlation_id
    )
    log.warning("probe-down alert sent and outage state recorded: environment=%s", environment)
    return True


def _send_recovery_alert(
    channel: NotificationChannel,
    state: dict[str, Any],
    *,
    environment: str,
) -> bool:
    correlation_id = state.get("correlation_id")
    if not isinstance(correlation_id, str) or not correlation_id:
        correlation_id = str(uuid4())
    subject = f"{environment.upper()} recovered - Yggdrasil"
    body = _alert_body(
        environment=environment,
        severity="info",
        transition="recovered",
        correlation_id=correlation_id,
        details=[],
    )
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send probe-recovered alert: %s", exc)
        return False
    _clear_alert_state()
    log.info("probe-recovered alert sent; outage state cleared: environment=%s", environment)
    return True


# ---------------------------------------------------------------------------
# HTTP helpers (injectable for testing)
# ---------------------------------------------------------------------------
def _http_get(url: str, timeout: int = 10) -> tuple[int, dict[str, Any]]:
    """GET url, return (status_code, json_body). Raises on network error."""
    import urllib.request

    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except Exception as exc:
        # urllib raises HTTPError for 4xx/5xx with no body read
        import urllib.error

        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        raise


# ---------------------------------------------------------------------------
# Core probe logic
# ---------------------------------------------------------------------------
def _probe_readyz(
    base_url: str,
    http_get: Any = None,
) -> tuple[bool, str]:
    """Check /readyz. Returns (ok, reason)."""
    if http_get is None:
        http_get = _http_get
    try:
        status, _ = http_get(f"{base_url}/readyz")
        if status == 200:
            return True, "readyz ok"
        return False, f"readyz returned HTTP {status}"
    except Exception:
        return False, "readyz unreachable"


def _probe_health_required_ok(
    base_url: str,
    http_get: Any = None,
) -> tuple[bool, str]:
    """Check /api/health required_ok field (NOT the top-level ok).

    A payload with ok=true but required_ok=false MUST trigger an alert.
    """
    if http_get is None:
        http_get = _http_get
    try:
        status, body = http_get(f"{base_url}/api/health")
        if status != 200:
            return False, f"/api/health returned HTTP {status}"
        # Intentionally ignore the top-level ok; we only gate on required_ok.
        required_ok = body.get("required_ok")
        if required_ok is True:
            return True, "health required_ok=true"

        return False, f"health required_ok={required_ok!r}"
    except Exception:
        return False, "/api/health unreachable"


def _probe_worker_heartbeat(
    heartbeat_path: str = WORKER_HEARTBEAT_PATH,
    stale_seconds: float = WORKER_HEARTBEAT_STALE_SECONDS,
) -> tuple[bool, str]:
    """Check worker-heartbeat staleness.

    Returns (ok, reason). A missing heartbeat file or stale timestamp is a
    failure; the threshold is controlled by WORKER_HEARTBEAT_STALE_SECONDS.
    """
    path = Path(heartbeat_path)
    if not path.exists():
        return False, f"worker heartbeat missing at {heartbeat_path}"
    try:
        hb = json.loads(path.read_text())
    except Exception as exc:
        return False, f"worker heartbeat malformed: {exc}"
    # The real worker heartbeat (app/runtime/worker_heartbeat.py) writes the epoch
    # timestamp under "ts"; accept "timestamp" only as a legacy fallback.
    ts = hb.get("ts")
    if ts is None:
        ts = hb.get("timestamp")
    if ts is None:
        return False, "worker heartbeat has no timestamp (expected `ts`)"
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return False, "worker heartbeat timestamp invalid"
    if age > stale_seconds:
        return False, f"worker heartbeat stale by {age:.0f}s (threshold {stale_seconds}s)"
    return True, f"worker heartbeat fresh ({age:.0f}s old)"


def run_probe(
    base_url: str = PROBE_BASE_URL,
    heartbeat_path: str = WORKER_HEARTBEAT_PATH,
    heartbeat_stale_seconds: float = WORKER_HEARTBEAT_STALE_SECONDS,
    channel: NotificationChannel | None = None,
    http_get: Any = None,
    environment: str | None = None,
) -> bool:
    """Run the full probe. Return True if the selected target is healthy.

    This function is the unit-testable boundary: tests import and call it
    directly with injected http_get / channel to exercise real probe logic
    without touching the network or sending real notifications.
    """
    selected_environment = environment or PROBE_ENVIRONMENT or "unknown"
    if channel is None:
        if not PROBE_ALERT_CHANNEL:
            raise ValueError("probe alert channel is not configured")
        channel = build_channel(PROBE_ALERT_CHANNEL)

    failures: list[str] = []

    ok_readyz, reason_readyz = _probe_readyz(base_url, http_get=http_get)
    if not ok_readyz:
        failures.append(reason_readyz)

    ok_health, reason_health = _probe_health_required_ok(base_url, http_get=http_get)
    if not ok_health:
        failures.append(reason_health)

    ok_hb, reason_hb = _probe_worker_heartbeat(heartbeat_path, heartbeat_stale_seconds)
    if not ok_hb:
        failures.append(reason_hb)

    if not failures:
        log.info(
            "probe ok: readyz=%s health=%s heartbeat=%s",
            reason_readyz,
            reason_health,
            reason_hb,
        )
        state = _load_alert_state()
        if _outage_state_is_active(state):
            _send_recovery_alert(channel, state or {}, environment=selected_environment)
        elif state is not None:
            _clear_alert_state()
        return True

    # Something is down — suppress duplicate alerts while the outage remains active.
    state = _load_alert_state()
    if _outage_state_is_active(state):
        log.info(
            "probe-down detected but outage already recorded; suppressing duplicate alert. environment=%s",
            selected_environment,
        )
        return False

    # First detection in this outage: send push + record state only after a successful send.
    correlation_id = str(uuid4())
    _send_down_alert(
        channel,
        failures,
        environment=selected_environment,
        correlation_id=correlation_id,
    )
    return False


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def _runtime_config() -> tuple[str, int]:
    environment = PROBE_ENVIRONMENT.strip().lower()
    if environment not in {"test", "prod"}:
        raise ValueError("PROBE_ENVIRONMENT must be test or prod")
    base_url = PROBE_BASE_URL.strip().rstrip("/")
    parsed_url = urlsplit(base_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("PROBE_BASE_URL is invalid")
    if not WORKER_HEARTBEAT_PATH.strip():
        raise ValueError("WORKER_HEARTBEAT_PATH is required")
    if not Path(WORKER_HEARTBEAT_PATH).is_absolute():
        raise ValueError("WORKER_HEARTBEAT_PATH must be absolute")
    if not PROBE_ALERT_CHANNEL:
        raise ValueError("PROBE_ALERT_CHANNEL is required")
    if PROBE_ALERT_CHANNEL.lower() not in {"ntfy", "telegram", "mail", "none", "discord"}:
        raise ValueError("PROBE_ALERT_CHANNEL is invalid")
    try:
        interval = int(os.environ.get("PROBE_INTERVAL_SECONDS", "60"))
    except ValueError:
        raise ValueError("PROBE_INTERVAL_SECONDS is invalid") from None
    if interval < 1:
        raise ValueError("PROBE_INTERVAL_SECONDS is invalid")
    state_file = os.environ.get("PROBE_STATE_FILE") or os.environ.get(
        "PROD_PROBE_STATE_FILE"
    )
    if not state_file:
        raise ValueError("PROBE_STATE_FILE is required")
    if not Path(state_file).is_absolute():
        raise ValueError("PROBE_STATE_FILE must be absolute")
    return environment, interval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe one configured Yggdrasil channel")
    parser.add_argument("--loop", action="store_true", help="probe repeatedly at the configured interval")
    args = parser.parse_args(argv)
    try:
        environment, interval = _runtime_config()
        global ALERT_STATE_FILE
        state_file = os.environ.get("PROBE_STATE_FILE") or os.environ.get(
            "PROD_PROBE_STATE_FILE"
        )
        assert state_file is not None
        ALERT_STATE_FILE = Path(state_file)
    except ValueError as exc:
        log.error("probe configuration invalid: %s", exc)
        return 78

    if args.loop:
        while True:
            try:
                run_probe(environment=environment)
            except Exception:
                log.exception("probe iteration failed: environment=%s", environment)
            time.sleep(interval)

    try:
        healthy = run_probe(environment=environment)
    except Exception:
        log.exception("probe execution failed: environment=%s", environment)
        return 1
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())

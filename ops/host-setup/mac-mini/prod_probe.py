#!/usr/bin/env python3
"""Scheduled prod-down probe — transition-based hard-down backstop alert.

Curls /readyz AND /api/health required_ok, checks worker-heartbeat staleness.
On the first transition into an outage it dispatches one down alert and records
the down state. Repeated down probes suppress while the outage remains active.
On the first healthy run after recovery it emits one recovery signal and clears
the outage state so a later distinct outage can alert again.

Channel selection
-----------------
Set PROD_PROBE_CHANNEL to one of:
  - "ntfy"      (default) — posts to ntfy.sh topic $NTFY_TOPIC
  - "telegram"  — sends via Telegram Bot $TELEGRAM_BOT_TOKEN / $TELEGRAM_CHAT_ID
  - "mail"      — sends via Python's smtplib (requires SMTP_* env vars)
  - "none"      — dry-run; logs but does not push

The channel is swappable without changing the launchd job.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Protocol

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
# The prod stack exposes the API on host port 18000 (docker-compose maps
# 18000:8000; 8000 is the in-CONTAINER port). This script runs on the macOS HOST
# (launchd / `make live-prod-probe`), so it must target the host port.
PROBE_BASE_URL = os.environ.get("PROBE_BASE_URL", "http://127.0.0.1:18000")
# This script runs on the HOST, not inside the worker container. The worker
# writes its heartbeat to <repo>/tmp/worker_heartbeat.json (the container path
# /app/tmp/... is the same file via the repo bind-mount). Resolve the host path
# from this file's location so `make live-prod-probe` works without env.
WORKER_HEARTBEAT_PATH = os.environ.get(
    "WORKER_HEARTBEAT_PATH",
    str(Path(__file__).resolve().parents[3] / "tmp" / "worker_heartbeat.json"),
)
WORKER_HEARTBEAT_STALE_SECONDS = float(
    os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", "60")
)
ALERT_STATE_FILE = Path(
    os.environ.get("PROD_PROBE_STATE_FILE", "tmp/prod_probe_alert.state")
)
ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

PROD_PROBE_CHANNEL = os.environ.get("PROD_PROBE_CHANNEL", "ntfy")

# Launchd cadence mirror only; alert transitions are state-based, not bucketed.
PROBE_INTERVAL_SECONDS = int(os.environ.get("PROBE_INTERVAL_SECONDS", "60"))


# ---------------------------------------------------------------------------
# Notification channel protocol + adapters
# ---------------------------------------------------------------------------
class NotificationChannel(Protocol):
    def send(self, subject: str, body: str) -> None:
        ...


class NtfyChannel:
    """ntfy.sh push via HTTP POST."""

    def __init__(self) -> None:
        self.topic = os.environ.get("NTFY_TOPIC", "yggdrasil-prod-alerts")
        self.server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

    def send(self, subject: str, body: str) -> None:
        import urllib.request

        url = f"{self.server}/{self.topic}"
        data = body.encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Title": subject,
                "Priority": "high",
                "Tags": "warning,robot",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("ntfy push sent: %s %s", resp.status, url)


class TelegramChannel:
    """Telegram Bot API push."""

    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def send(self, subject: str, body: str) -> None:
        import urllib.parse
        import urllib.request

        text = f"*{subject}*\n{body}"
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode(
            {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        ).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("telegram push sent: %s", resp.status)


class MailChannel:
    """SMTP mail push."""

    def send(self, subject: str, body: str) -> None:
        import smtplib
        from email.mime.text import MIMEText

        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        from_addr = os.environ.get("SMTP_FROM", "probe@yggdrasil.local")
        to_addr = os.environ.get("SMTP_TO", "operator@yggdrasil.local")
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(from_addr, [to_addr], msg.as_string())
        log.info("mail push sent to %s", to_addr)


class NullChannel:
    """Dry-run: log only."""

    def send(self, subject: str, body: str) -> None:
        log.info("[dry-run] would push: %s — %s", subject, body)


def build_channel(name: str) -> NotificationChannel:
    """Return the appropriate channel adapter by name (env-selected)."""
    mapping: dict[str, type] = {
        "ntfy": NtfyChannel,
        "telegram": TelegramChannel,
        "mail": MailChannel,
        "none": NullChannel,
    }
    cls = mapping.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown PROD_PROBE_CHANNEL={name!r}. Choose one of: {list(mapping)}"
        )
    return cls()


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


def _record_outage_state(failures: list[str]) -> None:
    """Persist the current outage state after a successful down alert."""
    ALERT_STATE_FILE.write_text(
        json.dumps(
            {
                "status": "down",
                "ts": int(time.time()),
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


def _send_down_alert(channel: NotificationChannel, failures: list[str]) -> bool:
    subject = "Prod down — Yggdrasil"
    body = "Failures detected:\n" + "\n".join(f"  - {f}" for f in failures)
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send prod-down alert: %s", exc)
        return False
    _record_outage_state(failures)
    log.warning("prod-down alert sent and outage state recorded. failures=%s", failures)
    return True


def _send_recovery_alert(channel: NotificationChannel) -> bool:
    subject = "Prod recovered — Yggdrasil"
    body = "The prod probe saw a healthy run after a previous outage."
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send prod-recovered alert: %s", exc)
        return False
    _clear_alert_state()
    log.info("prod-recovered alert sent; outage state cleared")
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
    except Exception as exc:
        return False, f"readyz unreachable: {exc}"


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
    except Exception as exc:
        return False, f"/api/health unreachable: {exc}"


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
    age = time.time() - float(ts)
    if age > stale_seconds:
        return False, f"worker heartbeat stale by {age:.0f}s (threshold {stale_seconds}s)"
    return True, f"worker heartbeat fresh ({age:.0f}s old)"


def run_probe(
    base_url: str = PROBE_BASE_URL,
    heartbeat_path: str = WORKER_HEARTBEAT_PATH,
    heartbeat_stale_seconds: float = WORKER_HEARTBEAT_STALE_SECONDS,
    channel: NotificationChannel | None = None,
    http_get: Any = None,
) -> bool:
    """Run the full probe. Return True if prod is healthy, False on failure.

    This function is the unit-testable boundary: tests import and call it
    directly with injected http_get / channel to exercise real probe logic
    without touching the network or sending real notifications.
    """
    if channel is None:
        channel = build_channel(PROD_PROBE_CHANNEL)

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
            _send_recovery_alert(channel)
        elif state is not None:
            _clear_alert_state()
        return True

    # Something is down — suppress duplicate alerts while the outage remains active.
    state = _load_alert_state()
    if _outage_state_is_active(state):
        log.info(
            "prod-down detected but outage already recorded; suppressing duplicate alert. failures=%s",
            failures,
        )
        return False

    # First detection in this outage: send push + record state only after a successful send.
    _send_down_alert(channel, failures)
    return False


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    healthy = run_probe()
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()

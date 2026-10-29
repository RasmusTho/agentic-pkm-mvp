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
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
DEFAULT_WORKER_HEARTBEAT_STALE_SECONDS = 60.0
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
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("status") != "down"
        or payload.get("environment") not in {"test", "prod"}
        or not isinstance(payload.get("ts"), int)
        or isinstance(payload.get("ts"), bool)
        or payload["ts"] <= 0
        or not isinstance(payload.get("failures"), list)
        or not payload["failures"]
        or any(not isinstance(item, str) or not item for item in payload["failures"])
    ):
        return None
    correlation_id = payload.get("correlation_id")
    if not isinstance(correlation_id, str):
        return None
    try:
        UUID(correlation_id)
    except (ValueError, AttributeError):
        return None
    return payload


def _outage_state_is_active(
    state: dict[str, Any] | None, *, environment: str
) -> bool:
    return bool(
        state
        and state.get("status") == "down"
        and state.get("environment") == environment
    )


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


# Only producer-owned identifiers become human text. Diagnostic values never do.
_REQUIRED_CHECK_LABELS = {
    "index_outbox": "indexets utkorg",
    "obsidian": "Obsidian-beroenden",
    "llm_access": "modellåtkomst",
    "llm_task_routes": "modellrutter",
    "embedding_index": "sökindex",
}
_RUNTIME_LABELS = {"db": "databas", "worker": "worker", "llm": "modellkörning"}
_UNKNOWN_CAUSE = "UNKNOWN – detaljerad felorsak saknas eller kan inte tolkas säkert"
_RUNBOOK_URL = (
    "https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/"
    "docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md"
)


def _health_failure_reason(body: dict[str, Any]) -> str:
    """Project the producer's required conjunction into finite internal tokens.

    db/worker/llm are mandatory in _runtime_ok. Watcher is conditional on a
    producer-local setting absent from this payload, so do not infer its role.
    """
    tokens = []
    checks = body.get("checks")
    runtime = body.get("runtime")
    if isinstance(checks, dict):
        for key in _REQUIRED_CHECK_LABELS:
            item = checks.get(key)
            if (isinstance(item, dict) and item.get("ok") is False
                    and item.get("required", True) is True):
                tokens.append("check." + key)
    if isinstance(runtime, dict):
        for key in _RUNTIME_LABELS:
            item = runtime.get(key)
            if isinstance(item, dict) and item.get("ok") is False:
                tokens.append("runtime." + key)
    # Unknown components and malformed metadata are deliberately not interpolated.
    return "health required_ok=false" + (":" + ",".join(tokens) if tokens else "")


def _human_observations(details: list[str]) -> list[str]:
    observations = []
    labels = {"check." + k: v for k, v in _REQUIRED_CHECK_LABELS.items()}
    labels.update({"runtime." + k: v for k, v in _RUNTIME_LABELS.items()})
    for detail in details[:3]:  # readyz, health, host heartbeat only
        if detail.startswith("health required_ok=false"):
            tokens = detail.partition(":")[2].split(",")
            names = [label for key, label in labels.items() if key in tokens]
            observations.append("Obligatoriska kontroller rapporterar fel: " + ", ".join(names)
                                if names else "Obligatorisk hälsa: " + _UNKNOWN_CAUSE)
        elif detail == "/api/health unreachable":
            observations.append("Hälsokontrollen kunde inte nå API:t; orsaken är UNKNOWN.")
        elif detail.startswith("/api/health returned HTTP "):
            observations.append("Hälsokontrollen fick ett HTTP-felsvar; orsaken är UNKNOWN.")
        elif detail == "health acquisition deadline exceeded":
            observations.append("Hälsokontrollen hann inte slutföras inom tidsgränsen; orsaken är UNKNOWN.")
        elif detail == "health response malformed":
            observations.append("Hälsosvaret kunde inte tolkas; orsaken är UNKNOWN.")
        elif detail == "health full channel unqualified":
            observations.append("Hälsosvaret bekräftar inte att hela kanalen är kvalificerad.")
        elif detail.startswith("/readyz"):
            observations.append("Readiness-kontrollen misslyckades; API-beredskap är inte bekräftad.")
        elif detail.startswith("worker heartbeat"):
            observations.append("Workerns heartbeat-kontroll misslyckades; aktuell livssignal är inte bekräftad.")
        else:
            observations.append(_UNKNOWN_CAUSE)
    return list(dict.fromkeys(observations)) or [_UNKNOWN_CAUSE]


def _alert_body(
    *,
    environment: str,
    severity: str,
    transition: str,
    correlation_id: str,
    details: list[str],
) -> str:
    timestamp = _alert_timestamp()
    instant = datetime.fromisoformat(timestamp)
    try:
        local = instant.astimezone(ZoneInfo("Europe/Stockholm"))
        local_time = local.strftime("%Y-%m-%d kl. %H:%M:%S %Z (%z)")
    except (ZoneInfoNotFoundError, OSError, ValueError):
        local_time = instant.strftime("%Y-%m-%d kl. %H:%M:%S UTC (lokal tidszon saknas)")
    environment = environment if environment in {"test", "prod"} else "unknown"
    try:
        correlation_id = str(UUID(correlation_id))
    except (ValueError, TypeError, AttributeError):
        correlation_id = "UNKNOWN"
    lines = [f"Tid: {local_time}"]
    if transition == "recovered":
        lines.append("De övervakade kontrollerna är åter gröna: readiness, obligatorisk hälsa och worker-heartbeat.")
        lines.append("Detta bekräftar inte att hela systemet eller alla funktioner är felfria.")
    else:
        lines.extend(_human_observations(details))
        lines.append("Påverkan utöver dessa observationer: UNKNOWN. Fullständigt driftstopp är inte fastställt.")
    lines.extend([
        "Nästa steg: kontrollera aktuell hälsa och följ incidentrunbooken nedan.",
        "Teknisk metadata:",
        f"source_system: {PROBE_SOURCE_SYSTEM}",
        f"environment: {environment}",
        f"severity: {severity}",
        f"transition: {transition}",
        f"timestamp_utc: {timestamp}",
        f"correlation_id: {correlation_id}",
        # Fixed owner URL: runtime configuration is not trusted notification text.
        f"remediation: {_RUNBOOK_URL}",
    ])
    return "\n".join(lines)


def _send_down_alert(
    channel: NotificationChannel,
    failures: list[str],
    *,
    environment: str,
    correlation_id: str,
) -> bool:
    subject = f"{environment.upper() if environment in {'prod', 'test'} else 'UNKNOWN'} hälsoproblem - Yggdrasil"
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
    subject = f"{environment.upper() if environment in {'prod', 'test'} else 'UNKNOWN'} övervakade kontroller återställda - Yggdrasil"
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
_HTTP_MAX_BYTES = 1024 * 1024
_HTTP_MAX_REQUEST_BYTES = 16384
_HTTP_CHILD_CLEANUP_SECONDS = 1.0
_HTTP_CHILD_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "import prod_probe; prod_probe._http_get_child()"
)


class _HttpChildCleanupFailed(BaseException):
    """Stop this probe if exact child termination/reaping cannot be confirmed."""


def _terminate_http_child(child: subprocess.Popen[bytes]) -> None:
    try:
        if child.poll() is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
        child.wait(timeout=_HTTP_CHILD_CLEANUP_SECONDS)
    except BaseException:
        raise _HttpChildCleanupFailed("HTTP child termination unconfirmed; stopping probe") from None
    finally:
        for pipe in (child.stdin, child.stdout, child.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass  # Never hide an unconfirmed child-reaping failure.


def _http_get(url: str, timeout: float = 10) -> tuple[int, dict[str, Any]]:
    """One serial, disposable reader; parent bounds even native DNS/header reads."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise TimeoutError("probe HTTP deadline exceeded")
    deadline = time.monotonic() + timeout
    request = json.dumps({"url": url, "timeout": timeout}).encode()
    if len(request) > _HTTP_MAX_REQUEST_BYTES:
        raise ValueError("probe HTTP request too large")
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", _HTTP_CHILD_CODE, str(Path(__file__).resolve().parent)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={},
    )
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("probe HTTP reader", timeout)
        output, _ = child.communicate(request, timeout=remaining)
    except subprocess.TimeoutExpired:
        _terminate_http_child(child)
        raise TimeoutError("probe HTTP deadline exceeded") from None
    except BaseException:
        _terminate_http_child(child)
        raise
    if child.returncode is None:
        _terminate_http_child(child)
        raise TimeoutError("probe HTTP child completion unconfirmed")
    if child.returncode != 0 or time.monotonic() >= deadline or len(output) > _HTTP_MAX_BYTES:
        raise TimeoutError("probe HTTP response unavailable")
    try:
        result = json.loads(output)
        if (
            not isinstance(result, dict) or set(result) != {"status", "body"}
            or type(result["status"]) is not int or not 100 <= result["status"] <= 599
            or not isinstance(result["body"], dict)
        ):
            raise ValueError("invalid response")
        return result["status"], result["body"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("probe HTTP response malformed") from None


def _http_get_child() -> None:
    """Private bounded pipe protocol; no URL, environment or raw error output."""
    try:
        raw = sys.stdin.buffer.read(_HTTP_MAX_REQUEST_BYTES + 1)
        if len(raw) > _HTTP_MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        request = json.loads(raw)
        if (
            not isinstance(request, dict) or set(request) != {"url", "timeout"}
            or not isinstance(request["url"], str)
            or type(request["timeout"]) not in {int, float}
            or not math.isfinite(request["timeout"]) or request["timeout"] <= 0
        ):
            raise ValueError("invalid request")
        status, body = _read_http_json(request["url"], request["timeout"])
        output = json.dumps({"status": status, "body": body}, ensure_ascii=False).encode()
        if len(output) > _HTTP_MAX_BYTES:
            raise ValueError("response too large")
    except Exception:
        output = b'{"error":true}'
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()


def _read_http_json(url: str, timeout: float) -> tuple[int, dict[str, Any]]:
    """GET url, return (status_code, json_body). Raises on network error."""
    import urllib.request

    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(_HTTP_MAX_BYTES + 1)
            if len(raw) > _HTTP_MAX_BYTES:
                raise ValueError("response too large")
            return resp.status, json.loads(raw.decode())
    except Exception as exc:
        # urllib raises HTTPError for 4xx/5xx with no body read
        import urllib.error

        if isinstance(exc, urllib.error.HTTPError):
            try:
                raw = exc.read(_HTTP_MAX_BYTES + 1)
                if len(raw) > _HTTP_MAX_BYTES:
                    raise ValueError("response too large")
                body = json.loads(raw.decode())
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


# Qualification reads never enqueue work; these bounds cover one acquisition,
# including HTTP time. The normal loop still sleeps its configured interval.
_HEALTH_ACQUISITION_SECONDS = 45.0
_HEALTH_CACHE_READS = 90
_HEALTH_CACHE_INTERVAL_SECONDS = 0.5


def _health_observation_pending(body: dict[str, Any]) -> bool:
    """Only cold/stale model snapshots justify waiting for the scheduled sample."""
    if body.get("full_channel_qualified") is False:
        return False
    checks = body.get("checks")
    if not isinstance(checks, dict):
        return False
    llm = checks.get("llm_access")
    if not isinstance(llm, dict):
        return False
    capabilities = llm.get("capabilities")
    return isinstance(capabilities, dict) and any(
        isinstance(item, dict)
        and item.get("status") == "unknown"
        and isinstance(item.get("reason_code"), str)
        and item.get("reason_code") in {
            "readiness_unknown", "missing_observation", "stale_observation"
        }
        for item in capabilities.values()
    )


def _probe_health_required_ok(
    base_url: str,
    http_get: Any = None,
) -> tuple[bool, str]:
    """Acquire required health with one background request, then passive reads.

    Trust only the API's final required_ok, never a prior success or top-level ok.
    A cold/stale model snapshot may finish asynchronously within this finite budget.
    """
    if http_get is None:
        http_get = _http_get
    deadline = time.monotonic() + _HEALTH_ACQUISITION_SECONDS
    url = f"{base_url}/api/health"
    for attempt in range(_HEALTH_CACHE_READS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, "health acquisition deadline exceeded"
        try:
            status, body = http_get(url, timeout=min(10.0, remaining))
        except Exception:
            return False, "/api/health unreachable"
        if time.monotonic() >= deadline:
            return False, "health acquisition deadline exceeded"
        if status != 200:
            return False, f"/api/health returned HTTP {status}"
        if not isinstance(body, dict):
            return False, "health response malformed"
        if body.get("full_channel_qualified") is False:
            return False, "health full channel unqualified"
        if body.get("required_ok") is True:
            return True, "health required_ok=true"
        if not _health_observation_pending(body) or attempt == _HEALTH_CACHE_READS:
            return False, _health_failure_reason(body)
        time.sleep(max(0.0, min(_HEALTH_CACHE_INTERVAL_SECONDS, deadline - time.monotonic())))
        url = f"{base_url}/api/health?model_access_sampling=cache"
    return False, "health required_ok=false"


def _probe_worker_heartbeat(
    heartbeat_path: str = WORKER_HEARTBEAT_PATH,
    stale_seconds: float = DEFAULT_WORKER_HEARTBEAT_STALE_SECONDS,
) -> tuple[bool, str]:
    """Check worker-heartbeat staleness.

    Returns (ok, reason). A missing heartbeat file or stale timestamp is a
    failure; the threshold is controlled by WORKER_HEARTBEAT_STALE_SECONDS.
    """
    if not math.isfinite(stale_seconds) or stale_seconds <= 0:
        return False, "worker heartbeat stale threshold invalid"
    path = Path(heartbeat_path)
    if not path.exists():
        return False, f"worker heartbeat missing at {heartbeat_path}"
    try:
        hb = json.loads(path.read_text())
    except Exception as exc:
        return False, f"worker heartbeat malformed: {exc}"
    if not isinstance(hb, dict):
        return False, "worker heartbeat malformed: expected an object"
    # The real worker heartbeat (app/runtime/worker_heartbeat.py) writes the epoch
    # timestamp under "ts"; accept "timestamp" only as a legacy fallback.
    ts = hb.get("ts")
    if ts is None:
        ts = hb.get("timestamp")
    if ts is None:
        return False, "worker heartbeat has no timestamp (expected `ts`)"
    try:
        timestamp = float(ts)
    except (TypeError, ValueError):
        return False, "worker heartbeat timestamp invalid"
    if not math.isfinite(timestamp) or timestamp <= 0:
        return False, "worker heartbeat timestamp invalid"
    age = time.time() - timestamp
    if not math.isfinite(age) or age < 0:
        return False, "worker heartbeat timestamp invalid"
    if age > stale_seconds:
        return False, f"worker heartbeat stale by {age:.0f}s (threshold {stale_seconds}s)"
    return True, f"worker heartbeat fresh ({age:.0f}s old)"


def run_probe(
    base_url: str = PROBE_BASE_URL,
    heartbeat_path: str = WORKER_HEARTBEAT_PATH,
    heartbeat_stale_seconds: float = DEFAULT_WORKER_HEARTBEAT_STALE_SECONDS,
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
        if _outage_state_is_active(state, environment=selected_environment):
            _send_recovery_alert(channel, state or {}, environment=selected_environment)
        elif state is not None:
            _clear_alert_state()
        return True

    # Something is down — suppress duplicate alerts while the outage remains active.
    state = _load_alert_state()
    if _outage_state_is_active(state, environment=selected_environment):
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
def _runtime_config() -> tuple[str, int, float]:
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
    try:
        heartbeat_stale_seconds = float(
            os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", "60")
        )
    except ValueError:
        raise ValueError("WORKER_HEARTBEAT_STALE_SECONDS is invalid") from None
    if not math.isfinite(heartbeat_stale_seconds) or heartbeat_stale_seconds <= 0:
        raise ValueError("WORKER_HEARTBEAT_STALE_SECONDS is invalid")
    state_file = os.environ.get("PROBE_STATE_FILE") or os.environ.get(
        "PROD_PROBE_STATE_FILE"
    )
    if not state_file:
        raise ValueError("PROBE_STATE_FILE is required")
    if not Path(state_file).is_absolute():
        raise ValueError("PROBE_STATE_FILE must be absolute")
    return environment, interval, heartbeat_stale_seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe one configured Yggdrasil channel")
    parser.add_argument("--loop", action="store_true", help="probe repeatedly at the configured interval")
    args = parser.parse_args(argv)
    try:
        environment, interval, heartbeat_stale_seconds = _runtime_config()
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
            iteration_started = time.monotonic()
            try:
                run_probe(
                    environment=environment,
                    heartbeat_stale_seconds=heartbeat_stale_seconds,
                )
            except Exception:
                log.exception("probe iteration failed: environment=%s", environment)
            time.sleep(max(0.0, interval - (time.monotonic() - iteration_started)))

    try:
        healthy = run_probe(
            environment=environment,
            heartbeat_stale_seconds=heartbeat_stale_seconds,
        )
    except Exception:
        log.exception("probe execution failed: environment=%s", environment)
        return 1
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())

"""GitHub API call structured logger and kill switch.

Every gh/GraphQL call should emit a structured record via ``log_github_call``.
The kill switch reads the captured ``remaining`` value and disables expensive
scans when it falls below a configurable threshold.

Design constraints:
- Never log tokens, secrets, or credential values.
- Kill switch fails safe: when uncertain, allow essential reads and disable
  expensive scans only.
- Records are appended to a JSON-lines log file for operator inspection.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_KILL_SWITCH_THRESHOLD = 200

_DEFAULT_LOG_PATH = Path("logs/github_api_calls.jsonl")


def _kill_switch_threshold() -> int:
    try:
        return int(os.environ.get("GITHUB_RATELIMIT_KILL_THRESHOLD", _DEFAULT_KILL_SWITCH_THRESHOLD))
    except (ValueError, TypeError):
        return _DEFAULT_KILL_SWITCH_THRESHOLD


def _log_path() -> Path:
    raw = os.environ.get("GITHUB_CALL_LOG_PATH", "")
    return Path(raw) if raw else _DEFAULT_LOG_PATH


# ---------------------------------------------------------------------------
# Structured record emission
# ---------------------------------------------------------------------------

def log_github_call(
    *,
    operation: str,
    direction: str,
    status: int | None = None,
    remaining: int | None = None,
    reset: str | None = None,
    retry_count: int = 0,
    latency_ms: float | None = None,
    cost: int | None = None,
    error: str | None = None,
) -> None:
    """Emit a structured record for a single GitHub API call.

    Parameters
    ----------
    operation:
        Human-readable name for the call (e.g. ``"gh issue list"``).
    direction:
        ``"read"`` or ``"write"``.
    status:
        HTTP status code, if available.
    remaining:
        ``x-ratelimit-remaining`` header value, if captured.
    reset:
        ``x-ratelimit-reset`` header value, if captured.
    retry_count:
        Number of retries before this result.
    latency_ms:
        Round-trip latency in milliseconds.
    cost:
        GraphQL query cost units, if available.
    error:
        Short error description, if the call failed.

    Note: Never pass tokens or secret values to any parameter.
    """
    record: dict[str, Any] = {
        "schema": "github_call/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "direction": direction,
        "status": status,
        "remaining": remaining,
        "reset": reset,
        "retry_count": retry_count,
        "latency_ms": latency_ms,
        "cost": cost,
        "error": error,
    }
    # Omit None fields except the key ones operators commonly query.
    output = {k: v for k, v in record.items() if v is not None}
    output.setdefault("status", None)
    output.setdefault("remaining", None)
    output.setdefault("reset", None)

    _append_record(output)

    if remaining is not None and remaining < _kill_switch_threshold():
        logger.warning(
            "github_call_logger: rate limit low remaining=%d threshold=%d — kill switch active",
            remaining,
            _kill_switch_threshold(),
        )


def _append_record(record: dict[str, Any]) -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("github_call_logger: could not write log record: %s", exc)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------
#
# SHARED ENFORCEMENT POINT (#2746): this is the single source of truth for the
# GitHub-API kill-switch decision. Every development-time GitHub API consumer
# (dispatcher pull sync, scripts/reconcile_project_status.py, the poll/wait
# helpers in app/dispatcher/poll_backoff.py) consults ``is_kill_switch_active``
# here. Future GitHub-API consumers must wire through it too — do not add a
# parallel gate or re-parse GITHUB_RATELIMIT_KILL_THRESHOLD elsewhere.

def is_kill_switch_active(remaining: int | None) -> bool:
    """Return True when the GitHub API kill switch should activate.

    Fails safe: if ``remaining`` is None (unknown), returns False so that
    essential reads are still permitted. Only activates on a confirmed low value.
    """
    if remaining is None:
        return False
    return remaining < _kill_switch_threshold()


def get_last_known_remaining(sync_meta: dict[str, Any] | None) -> int | None:
    """Extract last captured ``rate_limit_remaining`` from a sync-meta record."""
    if sync_meta is None:
        return None
    extra = sync_meta.get("extra") or {}
    val = extra.get("rate_limit_remaining")
    if val is None:
        val = sync_meta.get("rate_limit_remaining")
    if isinstance(val, int):
        return val
    return None


# ---------------------------------------------------------------------------
# Timed gh call helper
# ---------------------------------------------------------------------------

def timed_gh_call(
    operation: str,
    direction: str,
    fn: Callable[..., Any],
    /,
    *args: Any,
    retry_count: int = 0,
    **kwargs: Any,
) -> Any:
    """Run *fn(*args, **kwargs)* and emit a structured log record with latency.

    Exceptions propagate after being recorded.
    """
    t0 = time.monotonic()
    error: str | None = None
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
        log_github_call(
            operation=operation,
            direction=direction,
            latency_ms=latency_ms,
            retry_count=retry_count,
            error=error,
        )

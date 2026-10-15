"""Read-only YouTube Source Sync health and status projection.

YSS-09 deliberately keeps the operator surfaces as projections over the
existing account, source, queue, quota, and scheduler state stores.  This
module is the small shared seam used by ``/api/status`` and the CLI doctor;
it does not create a new persistence channel and it never returns secret
material.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.config.environment import active_environment

RUNNER_STALE_SECONDS = 600
_DEFAULT_GATES = {
    "youtubeSync.enabled": False,
    "youtubeSync.runnerEnabled": False,
}


def _safe_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _parse_time(value: Any) -> datetime | None:
    text = _safe_iso(value)
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _setting_value(settings: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key, default)
    value = getattr(value, "value", value)
    return value if isinstance(value, bool) else default


def _accepted_gates(vault_context: Any = None) -> dict[str, bool]:
    """Read the existing accepted settings seam, failing closed on absence."""

    values = dict(_DEFAULT_GATES)
    if vault_context is None:
        return values
    try:
        from app.vault.settings_service import SettingsService

        accepted = SettingsService().resolve_accepted_runtime_gating(vault_context)
    except Exception:
        return values
    for key in values:
        values[key] = _setting_value(accepted, key, values[key])
    return values


def _source_rows(source_registry: Any) -> tuple[Any, ...]:
    try:
        rows = source_registry.list_all()
    except Exception:
        return ()
    return tuple(rows or ())


def _queue_rows(request_store: Any) -> tuple[Any, ...]:
    try:
        rows = request_store.list_all()
    except Exception:
        return ()
    return tuple(rows or ())


def _reason(error: Any) -> str | None:
    if isinstance(error, Mapping):
        value = error.get("reason_code")
        return str(value).strip() if value else None
    return None


def _safe_error(error: Any) -> dict[str, str] | None:
    """Keep stored errors bounded to the contract reason and timestamp."""

    if not isinstance(error, Mapping):
        return None
    reason = _reason(error)
    if not reason:
        return None
    return {
        "reason_code": reason,
        "at": _safe_iso(error.get("at")) or "",
    }


def _auth_projection(account_store: Any, token_store: Any) -> dict[str, Any]:
    try:
        bindings = tuple(account_store.list_all() or ())
    except Exception:
        bindings = ()
    binding = bindings[0] if bindings else None
    binding_id = getattr(binding, "account_binding_id", None)
    state = getattr(binding, "state", None) if binding is not None else None
    reason_code = getattr(binding, "reason_code", None) if binding is not None else "auth_missing"
    try:
        token_record_present = bool(binding_id and token_store.has_record(binding_id))
    except Exception:
        token_record_present = False

    # Checking key validity is intentionally boolean.  The key itself is
    # never copied into this projection, a log message, or a receipt.
    key_present = False
    try:
        from app.knowledge_acquisition.youtube_token_store import resolve_token_store_key

        resolve_token_store_key()
        key_present = True
    except Exception:
        pass

    if binding is None:
        status = "degraded"
        reason_code = "auth_missing"
    elif state == "connected" and token_record_present and key_present:
        status = "connected"
        reason_code = None
    else:
        status = "degraded"
        if state != "connected" and not reason_code:
            reason_code = "auth_missing"
        elif state == "connected" and not token_record_present:
            reason_code = "auth_missing"
        elif state == "connected" and not key_present:
            reason_code = "auth_key_missing"

    return {
        "status": status,
        "reason_code": reason_code,
        "binding_id": str(binding_id) if binding_id else None,
        "token_record_present": token_record_present,
        "token_store_key_present": key_present,
    }


def _quota_projection(quota_store: Any) -> dict[str, Any]:
    try:
        from app.knowledge_acquisition.youtube_api_client import DEFAULT_QUOTA_BUDGET

        quota = dict(quota_store.status(DEFAULT_QUOTA_BUDGET))
    except Exception:
        quota = {
            "spent_today": 0,
            "budget": 0,
            "exhausted": False,
            "available": False,
        }
    spent = quota.get("spent_today")
    budget = quota.get("budget")
    exhausted = bool(quota.get("exhausted"))
    remaining = None
    if isinstance(spent, int) and isinstance(budget, int):
        remaining = max(budget - spent, 0)
    return {
        "spent_today": spent,
        "budget": budget,
        "remaining": remaining,
        "exhausted": exhausted,
        "available": quota.get("available", True),
    }


def _health_contract_projection() -> dict[str, Any]:
    """Reuse the existing outbox dead-letter health-contract calculation."""
    try:
        from app.health_contract import dead_letter_snapshot

        snapshot = dead_letter_snapshot()
        return {
            "dead_lettered_count": snapshot.get("dead_lettered_count"),
            "oldest_undelivered_age_seconds": snapshot.get("oldest_undelivered_age_seconds"),
            "dead_letter_status": snapshot.get("dead_letter_status"),
        }
    except Exception:
        return {
            "dead_lettered_count": None,
            "oldest_undelivered_age_seconds": None,
            "dead_letter_status": "unknown",
        }


def collect_youtube_sync_status(
    *,
    now: datetime | None = None,
    vault_context: Any = None,
    source_registry: Any = None,
    request_store: Any = None,
    account_store: Any = None,
    token_store: Any = None,
    quota_store: Any = None,
    sync_state: Any = None,
    runner_stale_seconds: int = RUNNER_STALE_SECONDS,
    gates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one bounded, secret-free sync projection.

    Collaborators are optional so tests can inject the memory backends without
    changing production composition. Runtime construction remains lazy and all
    failures degrade this optional diagnostic instead of breaking `/healthz` or
    `/api/status`.
    """

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    effective_gates = dict(gates) if gates is not None else _accepted_gates(vault_context)
    enabled = _setting_value(effective_gates, "youtubeSync.enabled")
    runner_enabled = _setting_value(effective_gates, "youtubeSync.runnerEnabled")

    if source_registry is None:
        try:
            from app.knowledge_acquisition.source_registry import SourceRegistry

            source_registry = SourceRegistry.for_runtime()
        except Exception:
            source_registry = None
    if request_store is None:
        try:
            from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests

            request_store = AcquisitionRequests.for_runtime()
        except Exception:
            request_store = None
    if account_store is None:
        try:
            from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore

            account_store = AccountBindingStore.for_runtime()
        except Exception:
            account_store = None
    if token_store is None:
        try:
            from app.knowledge_acquisition.youtube_token_store import YouTubeTokenStore

            token_store = YouTubeTokenStore()
        except Exception:
            token_store = None
    if quota_store is None:
        try:
            from app.knowledge_acquisition.youtube_api_client import YouTubeQuotaStore

            quota_store = YouTubeQuotaStore.for_runtime()
        except Exception:
            quota_store = None
    if sync_state is None:
        try:
            from app.knowledge_acquisition.sync_state import for_runtime

            sync_state = for_runtime()
        except Exception:
            sync_state = None

    sources = _source_rows(source_registry) if source_registry is not None else ()
    requests = _queue_rows(request_store) if request_store is not None else ()
    enabled_sources = tuple(row for row in sources if bool(getattr(row, "enabled", False)))
    source_errors = tuple(
        error
        for row in sources
        for error in (_safe_error(getattr(row, "last_error", None)),)
        if error is not None
    )
    pending = tuple(row for row in requests if getattr(row, "status", None) == "pending")
    in_progress = tuple(row for row in requests if getattr(row, "status", None) == "in_progress")
    dead_lettered = tuple(row for row in requests if getattr(row, "status", None) == "dead_lettered")
    queue_depth = len(pending) + len(in_progress)

    auth = _auth_projection(account_store, token_store) if account_store and token_store else {
        "status": "degraded",
        "reason_code": "auth_missing",
        "binding_id": None,
        "token_record_present": False,
        "token_store_key_present": False,
    }
    quota = _quota_projection(quota_store) if quota_store is not None else {
        "spent_today": None,
        "budget": None,
        "remaining": None,
        "exhausted": False,
        "available": False,
    }
    health_contract = _health_contract_projection()

    tick: dict[str, Any] | None = None
    if sync_state is not None:
        try:
            tick_value = sync_state.get("last_tick")
            tick = dict(tick_value) if isinstance(tick_value, Mapping) else None
        except Exception:
            tick = None
    last_tick_at = _safe_iso((tick or {}).get("at"))
    tick_time = _parse_time(last_tick_at)
    staleness = None if tick_time is None else max(0, int((moment - tick_time).total_seconds()))
    runner_offline = bool(
        enabled
        and runner_enabled
        and (tick_time is None or (staleness is not None and staleness > runner_stale_seconds))
    )

    last_success_values = []
    for row in sources:
        parsed_success = _parse_time(getattr(row, "last_success_at", None))
        if parsed_success is not None:
            last_success_values.append(parsed_success)
    last_success = max(last_success_values).isoformat() if last_success_values else None
    next_due_values: list[datetime] = []
    try:
        from app.knowledge_acquisition.sync_scheduler import backoff_delay_seconds, resolve_cadence_seconds

        for row in enabled_sources:
            last_attempt = _parse_time(getattr(row, "last_attempt_at", None))
            if last_attempt is not None:
                failures = 0
                if sync_state is not None:
                    try:
                        backoff = sync_state.get(f"backoff:{getattr(row, 'binding_id', '')}")
                        if isinstance(backoff, Mapping):
                            candidate = backoff.get("consecutive_failures")
                            if isinstance(candidate, int) and candidate > 0:
                                failures = candidate
                    except Exception:
                        pass
                next_due_values.append(
                    last_attempt.replace()
                    + timedelta(
                        seconds=resolve_cadence_seconds(row)
                        + backoff_delay_seconds(failures)
                    )
                )
            else:
                next_due_values.append(moment)
    except Exception:
        pass
    next_due = min(next_due_values).isoformat() if next_due_values else None

    reason_codes: list[str] = []
    if not enabled or not runner_enabled:
        reason_codes.append("paused")
    if auth.get("reason_code"):
        reason_codes.append(str(auth["reason_code"]))
    if quota.get("exhausted"):
        reason_codes.append("quota_exhausted")
    if runner_offline:
        reason_codes.append("runner_offline")
    if dead_lettered:
        reason_codes.append("dead_letters_present")
    if (
        isinstance(health_contract.get("dead_lettered_count"), int)
        and health_contract["dead_lettered_count"] > 0
        and "dead_letters_present" not in reason_codes
    ):
        reason_codes.append("dead_letters_present")
    for error in source_errors:
        code = error.get("reason_code")
        if code and code not in reason_codes:
            reason_codes.append(code)

    if runner_offline:
        state = "offline"
    elif not enabled or not runner_enabled:
        state = "paused"
    elif reason_codes:
        state = "degraded"
    else:
        state = "connected"

    sources_payload = {
        "total": len(sources),
        "enabled": len(enabled_sources),
        "degraded": len(source_errors),
        "next_due_at": next_due,
    }
    queue_payload = {
        "depth": queue_depth,
        "pending": len(pending),
        "in_progress": len(in_progress),
        "dead_letters": len(dead_lettered),
        "oldest_pending_at": min(
            (getattr(row, "requested_at", "") for row in pending),
            default=None,
        ),
        "health_contract_dead_letters": health_contract["dead_lettered_count"],
        "oldest_undelivered_age_seconds": health_contract["oldest_undelivered_age_seconds"],
    }
    return {
        "status": state,
        "ok": state == "connected",
        "reason_code": reason_codes[0] if reason_codes else None,
        "reason_codes": reason_codes,
        "enabled": enabled,
        "runner_enabled": runner_enabled,
        "auth": auth,
        "auth_status": auth.get("status"),
        "auth_reason_code": auth.get("reason_code"),
        "token_store_key_present": auth.get("token_store_key_present", False),
        "sources": sources_payload,
        "sources_total": len(sources),
        "sources_enabled": len(enabled_sources),
        "sources_degraded": len(source_errors),
        "queue": queue_payload,
        "queue_depth": queue_depth,
        "dead_letters": len(dead_lettered),
        "health_contract": health_contract,
        "quota": quota,
        "last_tick_at": last_tick_at,
        "last_success_at": last_success,
        "latest_error": source_errors[-1] if source_errors else None,
        "runner_offline": runner_offline,
        "staleness_seconds": staleness,
        "channel": active_environment(),
        "channel_database": active_environment(),
        "suggested_actions": _suggested_actions(reason_codes),
    }


def _suggested_actions(reason_codes: list[str]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if any(code in reason_codes for code in {"auth_missing", "auth_expired", "auth_revoked", "auth_disconnected"}):
        actions.append({"reason_code": next(code for code in reason_codes if code in {"auth_missing", "auth_expired", "auth_revoked", "auth_disconnected"}), "command_hint": "youtube-auth connect"})
    if "auth_key_missing" in reason_codes:
        actions.append({"reason_code": "auth_key_missing", "command_hint": "Provision YOUTUBE_TOKEN_STORE_KEY per the YouTube OAuth runbook"})
    if "quota_exhausted" in reason_codes:
        actions.append({"reason_code": "quota_exhausted", "command_hint": "youtube-sync run"})
    if "runner_offline" in reason_codes:
        actions.append({"reason_code": "runner_offline", "command_hint": "youtube-sync run"})
    if "dead_letters_present" in reason_codes:
        actions.append({"reason_code": "dead_letters_present", "command_hint": "youtube-sync run"})
    return actions


__all__ = ["RUNNER_STALE_SECONDS", "collect_youtube_sync_status"]

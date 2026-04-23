from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


DELIVERY_SLA_DELIVERED = "delivered"
DELIVERY_SLA_TIMEOUT = "timeout_terminal"
DELIVERY_SLA_FAILED = "failed_terminal"
DELIVERY_SLA_ROLLED_BACK = "rolled_back_terminal"

_TIMEOUT_ERROR_TYPES = {"tool_timeout", "timeout", "plan_timeout"}


def map_delivery_sla_terminal_state(*, status: str, error_type: str | None = None) -> str:
    normalized_status = (status or "").strip().lower()
    normalized_error = (error_type or "").strip().lower()

    if normalized_status == "ok":
        return DELIVERY_SLA_DELIVERED
    if normalized_status == "rolled_back":
        return DELIVERY_SLA_ROLLED_BACK
    if normalized_error in _TIMEOUT_ERROR_TYPES:
        return DELIVERY_SLA_TIMEOUT
    return DELIVERY_SLA_FAILED


def summarize_delivery_sla_outcomes(results: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {
        DELIVERY_SLA_DELIVERED: 0,
        DELIVERY_SLA_TIMEOUT: 0,
        DELIVERY_SLA_FAILED: 0,
        DELIVERY_SLA_ROLLED_BACK: 0,
    }
    for item in results:
        if str(item.get("step_id") or "") == "__compensation__":
            continue
        state = map_delivery_sla_terminal_state(
            status=str(item.get("status") or ""),
            error_type=(str(item.get("error_type")) if item.get("error_type") is not None else None),
        )
        summary[state] = summary.get(state, 0) + 1
    return summary


def map_delivery_sla_from_event_record(record: Mapping[str, Any]) -> str | None:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    details = payload.get("details")
    if not isinstance(details, Mapping):
        return None

    raw_state = details.get("delivery_sla_state")
    if isinstance(raw_state, str) and raw_state.strip():
        return raw_state.strip()

    error_type = details.get("error_type")
    if isinstance(error_type, str) and error_type.strip():
        return map_delivery_sla_terminal_state(status="error", error_type=error_type)
    return None


__all__ = [
    "DELIVERY_SLA_DELIVERED",
    "DELIVERY_SLA_TIMEOUT",
    "DELIVERY_SLA_FAILED",
    "DELIVERY_SLA_ROLLED_BACK",
    "map_delivery_sla_terminal_state",
    "summarize_delivery_sla_outcomes",
    "map_delivery_sla_from_event_record",
]

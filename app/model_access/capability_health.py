"""Provider-neutral aggregation for model capability health observations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from math import isfinite
from typing import Any

_STATUSES = frozenset({"available", "degraded", "unavailable", "unknown"})
_STATUS_ORDER = {"available": 0, "degraded": 1, "unavailable": 2, "unknown": 3}
_SAFE_REASONS = frozenset(
    {
        "adapter_ready",
        "adapter_unavailable",
        "capability_not_observable",
        "capability_unsupported",
        "capability_unavailable",
        "clock_skew",
        "malformed_observation",
        "missing_observation",
        "observation_unavailable",
        "probe_failed",
        "readiness_degraded",
        "readiness_unknown",
        "route_not_configured",
        "route_transport_unsupported",
        "stale_observation",
        "transport_fallback_used",
        "transport_not_required",
        "transport_reachable",
        "transport_unavailable",
        "transport_unknown",
    }
)


def _parse_observed_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_reason(value: Any) -> str:
    return value if isinstance(value, str) and value in _SAFE_REASONS else "readiness_unknown"


def aggregate_capability_health(
    required_capability_ids: Iterable[str],
    observations: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> dict[str, Any]:
    """Aggregate fresh adapter observations without carrying route identity forward.

    Duplicate observations for a required capability are combined pessimistically:
    every configured task route that requires it must report it available.
    """

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    if isinstance(max_age_seconds, bool) or not isfinite(max_age_seconds) or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")

    required = sorted({item for item in required_capability_ids if isinstance(item, str) and item})
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        capability_id = observation.get("capability_id")
        if isinstance(capability_id, str) and capability_id in required:
            grouped[capability_id].append(observation)

    capabilities: dict[str, dict[str, str]] = {}
    for capability_id in required:
        candidates = grouped.get(capability_id, [])
        if not candidates:
            capabilities[capability_id] = {
                "status": "unknown",
                "freshness": "unknown",
                "reason_code": "missing_observation",
            }
            continue

        evaluated: list[dict[str, str]] = []
        for observation in candidates:
            status = observation.get("status")
            observed_at = _parse_observed_at(observation.get("observed_at"))
            reason = _safe_reason(observation.get("reason_code"))
            if not isinstance(status, str) or status not in _STATUSES or observed_at is None:
                evaluated.append(
                    {
                        "status": "unknown",
                        "freshness": "unknown",
                        "reason_code": "malformed_observation",
                    }
                )
                continue
            age = (instant - observed_at).total_seconds()
            if age < 0:
                evaluated.append(
                    {
                        "status": "unknown",
                        "freshness": "unknown",
                        "reason_code": "clock_skew",
                    }
                )
            elif age > max_age_seconds:
                evaluated.append(
                    {
                        "status": "unknown",
                        "freshness": "stale",
                        "reason_code": "stale_observation",
                    }
                )
            else:
                evaluated.append(
                    {
                        "status": status,
                        "freshness": "fresh",
                        "reason_code": reason,
                    }
                )

        worst = max(
            evaluated,
            key=lambda item: (
                _STATUS_ORDER[item["status"]],
                {"fresh": 0, "stale": 1, "unknown": 2}[item["freshness"]],
                item["reason_code"],
            ),
        )
        capabilities[capability_id] = worst

    return {
        "ok": all(
            item["status"] == "available" and item["freshness"] == "fresh"
            for item in capabilities.values()
        ),
        "capabilities": capabilities,
    }


def aggregate_transport_health(
    observations: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> dict[str, str]:
    """Aggregate network-path observations without exposing path identity."""

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    if isinstance(max_age_seconds, bool) or not isfinite(max_age_seconds) or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")

    evaluated: list[dict[str, str]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        status = observation.get("status")
        observed_at = _parse_observed_at(observation.get("observed_at"))
        reason = _safe_reason(observation.get("reason_code"))
        if not isinstance(status, str) or status not in {*_STATUSES, "not_applicable"} or observed_at is None:
            evaluated.append(
                {
                    "status": "unknown",
                    "freshness": "unknown",
                    "reason_code": "malformed_observation",
                }
            )
            continue

        age = (instant - observed_at).total_seconds()
        if age < 0:
            evaluated.append(
                {
                    "status": "unknown",
                    "freshness": "unknown",
                    "reason_code": "clock_skew",
                }
            )
        elif age > max_age_seconds:
            evaluated.append(
                {
                    "status": "unknown",
                    "freshness": "stale",
                    "reason_code": "stale_observation",
                }
            )
        else:
            evaluated.append(
                {"status": status, "freshness": "fresh", "reason_code": reason}
            )

    if not evaluated:
        return {
            "status": "not_applicable",
            "freshness": "fresh",
            "reason_code": "transport_not_required",
        }

    applicable = [item for item in evaluated if item["status"] != "not_applicable"]
    if not applicable:
        return {
            "status": "not_applicable",
            "freshness": "fresh",
            "reason_code": "transport_not_required",
        }

    status_order = {**_STATUS_ORDER, "not_applicable": -1}
    return max(
        applicable,
        key=lambda item: (
            status_order[item["status"]],
            {"fresh": 0, "stale": 1, "unknown": 2}[item["freshness"]],
            item["reason_code"],
        ),
    )


__all__ = ["aggregate_capability_health", "aggregate_transport_health"]

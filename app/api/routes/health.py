from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.cli.health import _safe_endpoint_origin, run_health

router = APIRouter()


_SENSITIVE_DETAIL_RE = re.compile(
    r"Traceback|File \"|/[^\\s:]+|[A-Za-z]:\\\\|secret|token|password|api[_-]?key",
    re.IGNORECASE,
)

_LLM_ROUTE_DETAIL_KEYS = frozenset(
    {"provider", "providers", "model", "transport_id", "endpoint", "base_url"}
)
_TRANSPORT_STATUSES = frozenset(
    {"available", "degraded", "unavailable", "unknown", "not_applicable"}
)
_TRANSPORT_FRESHNESS = frozenset({"fresh", "stale", "unknown"})
_TRANSPORT_REASONS = frozenset(
    {
        "clock_skew",
        "malformed_observation",
        "stale_observation",
        "transport_fallback_used",
        "transport_not_required",
        "transport_reachable",
        "transport_unavailable",
        "transport_unknown",
    }
)


def _strip_llm_route_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_llm_route_details(item)
            for key, item in value.items()
            if str(key) not in _LLM_ROUTE_DETAIL_KEYS
        }
    if isinstance(value, list):
        return [_strip_llm_route_details(item) for item in value]
    return value


def _strip_transport_path_details(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {
            "status": "unknown",
            "freshness": "unknown",
            "reason_code": "transport_unknown",
        }
    status = value.get("status")
    freshness = value.get("freshness")
    reason_code = value.get("reason_code")
    return {
        "status": (
            status
            if isinstance(status, str) and status in _TRANSPORT_STATUSES
            else "unknown"
        ),
        "freshness": (
            freshness
            if isinstance(freshness, str) and freshness in _TRANSPORT_FRESHNESS
            else "unknown"
        ),
        "reason_code": (
            reason_code
            if isinstance(reason_code, str) and reason_code in _TRANSPORT_REASONS
            else "transport_unknown"
        ),
    }


def _neutralize_llm_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep public health focused on capabilities, not selected route identity."""
    result = deepcopy(payload)
    checks = result.get("checks")
    if isinstance(checks, dict):
        for key, detail in (
            ("llm_router", "route configuration loaded"),
            ("llm_providers", "adapter declarations loaded"),
        ):
            check = checks.get(key)
            if isinstance(check, dict):
                summary = {
                    "ok": bool(check.get("ok")),
                    "detail": detail,
                }
                for metadata_key in ("required", "severity"):
                    if metadata_key in check:
                        summary[metadata_key] = check[metadata_key]
                checks[key] = summary
        for key in ("llm_access", "llm_task_routes"):
            check = checks.get(key)
            if isinstance(check, dict):
                neutral = _strip_llm_route_details(check)
                neutral.pop("routes", None)
                neutral.pop("route_policies", None)
                neutral.pop("selected_defaults", None)
                neutral.pop("forced_overrides", None)
                if "transport_observation" in neutral:
                    neutral["transport_observation"] = _strip_transport_path_details(
                        neutral["transport_observation"]
                    )
                checks[key] = neutral

    runtime = result.get("runtime")
    if isinstance(runtime, dict) and isinstance(runtime.get("llm"), dict):
        runtime["llm"] = _strip_llm_route_details(runtime["llm"])
        if "transport_observation" in runtime["llm"]:
            runtime["llm"]["transport_observation"] = _strip_transport_path_details(
                runtime["llm"]["transport_observation"]
            )
    return result


def _sanitize_health_value(value: Any, *, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_health_value(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_health_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and parent_key == "base_url":
        return _safe_endpoint_origin(value)
    if isinstance(value, str) and _SENSITIVE_DETAIL_RE.search(value):
        if parent_key == "dsn" and "***" in value:
            return value
        if parent_key == "detail":
            return "health check detail redacted; inspect server logs with trace_id"
        return "[redacted]"
    return value


@router.get("/health")
async def health() -> dict[str, Any]:
    payload = await run_in_threadpool(run_health)
    if isinstance(payload, dict):
        payload = _neutralize_llm_diagnostics(payload)
    return _sanitize_health_value(payload)


__all__ = ["router"]

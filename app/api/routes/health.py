from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.cli.health import run_health

router = APIRouter()


_SENSITIVE_DETAIL_RE = re.compile(
    r"Traceback|File \"|/[^\\s:]+|[A-Za-z]:\\\\|secret|token|password|api[_-]?key",
    re.IGNORECASE,
)
_OPERATOR_VISIBLE_URL_KEYS = {"base_url"}


def _sanitize_health_value(value: Any, *, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_health_value(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_health_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and _SENSITIVE_DETAIL_RE.search(value):
        if parent_key in _OPERATOR_VISIBLE_URL_KEYS:
            return value
        if parent_key == "dsn" and "***" in value:
            return value
        if parent_key == "detail":
            return "health check detail redacted; inspect server logs with trace_id"
        return "[redacted]"
    return value


@router.get("/health")
async def health() -> dict[str, Any]:
    # `run_health()` is synchronous and does blocking I/O (bounded provider
    # probes, an obsidian subprocess, DB/index diagnostics). Running it inline
    # in this async handler blocked the single-process uvicorn event loop; with
    # companion-ui polling `/api/health` continuously, requests stacked and even
    # `/healthz` timed out externally — an effective prod outage (#3461). Offload
    # to a worker thread so a slow probe can never saturate the loop.
    payload = await run_in_threadpool(run_health)
    return _sanitize_health_value(payload)


__all__ = ["router"]

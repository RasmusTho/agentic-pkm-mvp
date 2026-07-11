from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter

from app.cli.health import run_health

router = APIRouter()


_SENSITIVE_DETAIL_RE = re.compile(
    r"Traceback|File \"|/[^\\s:]+|[A-Za-z]:\\\\|secret|token|password|api[_-]?key",
    re.IGNORECASE,
)
_OPERATOR_VISIBLE_URL_KEYS = {"base_url"}

# run_health() performs blocking network I/O (httpx calls to Ollama — once
# directly via the top-level ollama check, then again per LLM task route in
# _check_llm_task_routes) that can take 20s+ end to end. Running it inline
# inside this `async def` route blocks the single uvicorn event loop for
# every other coroutine on the process, including the trivial /healthz
# probe that container healthchecks and deploy tooling depend on. A single
# continuous poller (e.g. companion-ui hitting /api/health) was enough to
# starve the loop and take prod's /healthz and /readyz down with it
# (incident 2026-07-11). Offload the blocking work to a worker thread and
# bound both the per-call duration and the number of concurrent probes in
# flight so polling traffic can never saturate the loop or the default
# thread pool.
_HEALTH_CHECK_TIMEOUT_S = 20.0
_MAX_CONCURRENT_HEALTH_CHECKS = 2
_health_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_HEALTH_CHECKS)


def _timeout_health_payload(timeout_s: float) -> dict[str, Any]:
    return {
        "ok": False,
        "required_ok": False,
        "detail": f"health check exceeded {timeout_s:.0f}s timeout; upstream probe (e.g. Ollama) is likely unresponsive",
        "checks": {},
        "runtime": {},
    }


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
    async with _health_semaphore:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_health), timeout=_HEALTH_CHECK_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            result = _timeout_health_payload(_HEALTH_CHECK_TIMEOUT_S)
    return _sanitize_health_value(result)


__all__ = ["router"]

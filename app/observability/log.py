from __future__ import annotations

import json
import sys
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict, Optional


def with_trace_id(trace_id: Optional[str]) -> str:
    return trace_id or str(uuid.uuid4())


def json_log(**fields: Any) -> None:
    sys.stdout.write(json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def span(node: str) -> Callable:
    """
    Decorator that logs latency + metadata for a function call.
    Respects `_span_extra`, `_token_in`, `_token_out` kwargs (removed before invoking wrapped fn).
    Always injects/propagates `trace_id`.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            extra = kwargs.pop("_span_extra", None) or {}
            token_in = kwargs.pop("_token_in", None)
            token_out = kwargs.pop("_token_out", None)

            trace_id = with_trace_id(kwargs.get("trace_id"))
            kwargs["trace_id"] = trace_id

            start = time.perf_counter()
            status = "ok"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                status = "error"
                extra = {**extra, "error": f"{exc.__class__.__name__}: {exc}"}
                raise
            finally:
                latency_ms = round((time.perf_counter() - start) * 1000, 3)
                payload: Dict[str, Any] = {
                    "trace_id": trace_id,
                    "node": node,
                    "latency_ms": latency_ms,
                    "token_in": token_in,
                    "token_out": token_out,
                    "extra": extra,
                    "status": status,
                }
                json_log(**payload)

        return wrapper

    return decorator


__all__ = ["json_log", "span", "with_trace_id"]

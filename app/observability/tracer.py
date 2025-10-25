from __future__ import annotations

import contextlib
from typing import Dict, Optional

try:
    from opentelemetry import trace
    from opentelemetry.trace import Span
    _tracer = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - optional dependency
    trace = None
    _tracer = None

from app.observability.trace_log import log_span

@contextlib.contextmanager
def start_span(name: str, trace_id: str, attributes: Optional[Dict[str, object]] = None):
    span: Optional[Span] = None
    token = None
    if trace and _tracer:
        span = _tracer.start_span(name=name, attributes=attributes or {})
        token = trace.use_span(span, end_on_exit=True)
    try:
        log_span(name, trace_id, attributes)
        yield span
    finally:
        if token is not None:
            token.__exit__(None, None, None)

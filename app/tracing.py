from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Dict, Optional


@contextmanager
def start_span(name: str, trace_id: Optional[str], attrs: Dict[str, Any]):
    """
    Minimal no-op tracing span.

    In future:
    - attach trace_id
    - emit OTLP to Jaeger
    - record timing / errors

    For now we just yield to satisfy callers.
    """
    try:
        yield {
            "span_name": name,
            "trace_id": trace_id,
            "attrs": attrs,
        }
    finally:
        pass

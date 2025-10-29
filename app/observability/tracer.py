from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Any, Optional

_current_trace_id: ContextVar[Optional[str]] = ContextVar("_current_trace_id", default=None)

def current_trace_id() -> Optional[str]:
    return _current_trace_id.get()

@contextmanager
def start_span(name: str, trace_id: Optional[str] = None, attrs: Optional[Dict[str, Any]] = None):
    token = None
    try:
        if trace_id is not None:
            token = _current_trace_id.set(trace_id)
        yield {"name": name, "trace_id": _current_trace_id.get(), "attrs": attrs or {}}
    finally:
        if token is not None:
            _current_trace_id.reset(token)

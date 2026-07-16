from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Dict, Any, Optional

_current_trace_id: ContextVar[Optional[str]] = ContextVar("_current_trace_id", default=None)

def current_trace_id() -> Optional[str]:
    return _current_trace_id.get()

def bind_trace_id(trace_id: str) -> Token:
    """Bind ``trace_id`` to the current context; returns the reset token.

    Non-span propagation seam (#3895): lets process boundaries (e.g. the API
    trace middleware) thread a trace id into the contextvar that
    ``JsonLogFormatter`` reads, without opening an instrumented span.
    """
    return _current_trace_id.set(trace_id)

def reset_trace_id(token: Token) -> None:
    _current_trace_id.reset(token)

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

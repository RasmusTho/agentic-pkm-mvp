from __future__ import annotations

from typing import Any, Callable, Dict, List

_subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}


def subscribe(event: str, fn: Callable[[Dict[str, Any]], None]) -> None:
    _subs.setdefault(event, []).append(fn)


def emit(event: str, payload: Dict[str, Any]) -> None:
    for fn in _subs.get(event, []):
        try:
            fn(payload)
        except Exception:
            continue


def clear(event: str | None = None) -> None:
    """Remove subscribers for an event (or all events when None)."""
    if event is None:
        _subs.clear()
    else:
        _subs.pop(event, None)

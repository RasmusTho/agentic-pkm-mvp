from __future__ import annotations
from typing import Any, Iterable, Dict, List

def latest_heartbeat(repo: Any) -> Dict[str, Any] | None:
    try:
        for name in ("last_heartbeat", "get_last_heartbeat", "latest_heartbeat"):
            fn = getattr(repo, name, None)
            if callable(fn):
                return fn()
        hb = getattr(repo, "heartbeats", None)
        data = hb() if callable(hb) else hb
        items: list[dict[str, Any]] = []
        if isinstance(data, dict):
            items = list(data.values())
        elif isinstance(data, Iterable):
            items = list(data)
        if not items:
            return None
        try:
            items.sort(key=lambda x: x.get("created_at"), reverse=True)
        except Exception:
            pass
        return items[0]
    except Exception:
        return None

def interesting_items(repo: Any) -> List[Dict[str, Any]]:
    try:
        items = getattr(repo, "interesting_items", None)
        items = items() if callable(items) else items
        if items is None:
            return []
        if isinstance(items, dict):
            return list(items.values())
        if isinstance(items, Iterable):
            return list(items)  # type: ignore[return-value]
        return []
    except Exception:
        return []

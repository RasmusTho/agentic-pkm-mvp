from __future__ import annotations

import os
from typing import Any, Dict, Iterable

try:
    from app.stores.provider import get_stores
except Exception:
    get_stores = None  # type: ignore


def _as_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    out: Dict[str, Any] = {}
    for k in ("id", "object_id", "agent", "kind", "key", "value", "created_at"):
        if hasattr(row, k):
            try:
                out[k] = getattr(row, k)
            except Exception:
                pass
    if not out:
        out["row"] = repr(row)
    return out


def _normalize_key(d: Dict[str, Any]) -> Dict[str, Any]:
    if "key" not in d or d.get("key") in (None, ""):
        alt = d.get("kind") or d.get("type")
        if alt:
            d["key"] = alt
    return d


def _safe_iter(x: Any) -> Iterable[Any]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return x
    try:
        return list(x)
    except Exception:
        return [x]


def _fetch_decisions(object_id: str) -> list[Dict[str, Any]]:
    if get_stores is None:
        return []
    _, decisions = get_stores()  # type: ignore
    rows: Iterable[Any] = []
    for attempt in (
        lambda: decisions.list_by_object(object_id),            # preferred
        lambda: decisions.list(object_id=object_id),            # alt signature
        lambda: [r for r in _safe_iter(decisions.list()) if str(_as_dict(r).get("object_id")) == str(object_id)],  # fallback
    ):
        try:
            rows = attempt()
            break
        except Exception:
            continue
    result = [_normalize_key(_as_dict(r)) for r in _safe_iter(rows)]
    return result


__all__ = ["_fetch_decisions"]

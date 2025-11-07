from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends

try:
    # Riktig dependency (kräver Request i app.deps)
    from app.deps import get_agent_repository  # type: ignore
except Exception:  # pragma: no cover
    # Extrem fallback för smoke/offline
    def get_agent_repository():  # type: ignore
        class _Dummy:
            interesting_items: Dict[str, Any] = {}
        return _Dummy()

router = APIRouter()

def _filter_and_serialize(
    repo: Any,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    items = getattr(repo, "interesting_items", {})
    values = items.values() if hasattr(items, "values") else []
    out: List[Dict[str, Any]] = []
    for it in values:
        payload = it.get("payload", {})
        if system_intent and payload.get("system_intent") != system_intent:
            continue
        if tag and tag not in (payload.get("emergent_tags") or []):
            continue
        d = dict(it)
        oid = d.get("object_id")
        d["object_id"] = str(oid) if oid is not None else None
        out.append(d)
    # enkel topp-N
    return out[: max(0, int(limit))]

@router.get("/interesting")
def list_interesting(
    limit: int = 50,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    repo: Any = Depends(get_agent_repository),
) -> Dict[str, Any]:
    return {"items": _filter_and_serialize(repo, system_intent, tag, limit)}

@router.get("/interesting/summary")
def interesting_summary(
    limit: int = 50,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    repo: Any = Depends(get_agent_repository),
) -> Dict[str, Any]:
    items = _filter_and_serialize(repo, system_intent, tag, limit)
    return {"count": len(items)}

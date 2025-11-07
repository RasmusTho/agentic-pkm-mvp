from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter

# För smoke: undvik hårda beroenden – hämta repo via deps, falla tillbaka till tomt
try:
    from app.deps import get_agent_repository  # type: ignore
except Exception:  # pragma: no cover
    def get_agent_repository():  # type: ignore
        class _Dummy:
            interesting_items: Dict[str, Any] = {}
        return _Dummy()

router = APIRouter()

def _serialize_items(repo: Any) -> List[Dict[str, Any]]:
    items = getattr(repo, "interesting_items", {})
    pairs = items.items() if hasattr(items, "items") else []
    out: List[Dict[str, Any]] = []
    for oid, item in pairs:
        d = dict(item)
        d["object_id"] = str(d.get("object_id", oid))
        out.append(d)
    return out

@router.get("/interesting")
def list_interesting() -> Dict[str, Any]:
    repo = get_agent_repository()
    return {"items": _serialize_items(repo)}

@router.get("/interesting/summary")
def interesting_summary() -> Dict[str, Any]:
    data = list_interesting()
    return {"count": len(data["items"])}

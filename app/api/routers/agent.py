from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Any, Dict, List

from app.deps import get_agent_repository

router = APIRouter()

@router.get("/agent/health")
def agent_health(repo = Depends(get_agent_repository)) -> Dict[str, Any]:
    get_hb = getattr(repo, "get_last_heartbeat", None)
    hb = get_hb() if callable(get_hb) else None
    status = (hb or {}).get("status", "unknown")
    return {"status": status, "heartbeat": hb or {"status": status}}

@router.get("/agent/interesting")
def agent_interesting(repo = Depends(get_agent_repository)) -> Dict[str, List[Dict[str, Any]]]:
    li = getattr(repo, "list_interesting", None)
    items = li() if callable(li) else []
    return {"items": items}

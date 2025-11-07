from __future__ import annotations
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel

try:
    # Riktig dependency (via Request i app.deps)
    from app.deps import get_agent_repository  # type: ignore
except Exception:  # pragma: no cover
    # Minimal fallback för smoke/offline
    def get_agent_repository():  # type: ignore
        class _Dummy:
            interesting_items: Dict[str, Any] = {}
        return _Dummy()

router = APIRouter()

class InterestingItem(BaseModel):
    object_id: Optional[str] = None
    run_id: Optional[str] = None
    novelty: Optional[float] = None
    anomaly: Optional[float] = None
    uncertainty: Optional[float] = None
    value: Optional[float] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    payload: Dict[str, Any] = {}
    created_at: Optional[datetime] = None

class InterestingList(BaseModel):
    items: List[InterestingItem]

class InterestingSummary(BaseModel):
    count: int

def _to_item(it: Dict[str, Any]) -> InterestingItem:
    d = dict(it)
    oid = d.get("object_id")
    rid = d.get("run_id")
    if isinstance(oid, UUID):
        d["object_id"] = str(oid)
    if isinstance(rid, UUID):
        d["run_id"] = str(rid)
    return InterestingItem(**d)

def _filter_and_serialize(
    repo: Any,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
) -> List[InterestingItem]:
    items = getattr(repo, "interesting_items", {})
    values = items.values() if hasattr(items, "values") else []
    out: List[InterestingItem] = []
    for it in values:
        payload = it.get("payload", {})
        if system_intent and payload.get("system_intent") != system_intent:
            continue
        if tag and tag not in (payload.get("emergent_tags") or []):
            continue
        out.append(_to_item(it))
    return out[: max(0, int(limit))]

@router.get("/interesting", response_model=InterestingList)
def list_interesting(
    limit: int = 50,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    repo: Any = Depends(get_agent_repository),
) -> InterestingList:
    return InterestingList(items=_filter_and_serialize(repo, system_intent, tag, limit))

@router.get("/interesting/summary", response_model=InterestingSummary)
def interesting_summary(
    limit: int = 50,
    system_intent: Optional[str] = None,
    tag: Optional[str] = None,
    repo: Any = Depends(get_agent_repository),
) -> InterestingSummary:
    items = _filter_and_serialize(repo, system_intent, tag, limit)
    return InterestingSummary(count=len(items))

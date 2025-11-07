from __future__ import annotations
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_agent_repository

router = APIRouter()

# ---------- Pydantic-modeller ----------
class InterestingItem(BaseModel):
    object_id: UUID
    run_id: Optional[UUID] = None
    novelty: float
    anomaly: float
    uncertainty: float
    value: float
    score: float
    reason: str
    payload: Dict[str, Any]
    created_at: datetime

class InterestingList(BaseModel):
    items: List[InterestingItem]

class InterestingSummary(BaseModel):
    total: int
    count: int
    system_intent: Dict[str, int] = Field(default_factory=dict)

# ---------- Hjälpare ----------
def _filter_and_serialize(
    repo: Any,
    system_intent: Optional[str],
    tag: Optional[str],
    limit: int,
) -> List[InterestingItem]:
    raw_items = getattr(repo, "interesting_items", {})
    values = raw_items.values() if hasattr(raw_items, "values") else []

    out: List[InterestingItem] = []
    for it in values:
        payload = it.get("payload", {}) or {}
        if system_intent and payload.get("system_intent") != system_intent:
            continue
        tags = payload.get("emergent_tags") or []
        if tag and tag not in tags:
            continue

        out.append(
            InterestingItem(
                object_id=it["object_id"],
                run_id=it.get("run_id"),
                novelty=it.get("novelty", 0.0),
                anomaly=it.get("anomaly", 0.0),
                uncertainty=it.get("uncertainty", 0.0),
                value=it.get("value", 0.0),
                score=it.get("score", 0.0),
                reason=it.get("reason", ""),
                payload=payload,
                created_at=it.get("created_at", datetime.now(timezone.utc)),
            )
        )
    out.sort(key=lambda x: x.score, reverse=True)
    return out[:limit]

def _summarize_system_intent(items: List[InterestingItem]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for it in items:
        key = it.payload.get("system_intent")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts

# ---------- Endpoints + funktions-API ----------
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
    return InterestingSummary(
        total=len(items),
        count=len(items),
        system_intent=_summarize_system_intent(items),
    )

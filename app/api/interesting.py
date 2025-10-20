from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agent.repository import AgentRepository
from app.deps import get_agent_repository
from app.schemas.interesting import InterestingItem, InterestingResponse, InterestingSummary

router = APIRouter(prefix="/interesting", tags=["interesting"])


@router.get("", response_model=InterestingResponse)
def list_interesting(
    limit: int = 20,
    system_intent: str | None = None,
    tag: str | None = None,
    repo: AgentRepository = Depends(get_agent_repository),
) -> InterestingResponse:
    records = repo.fetch_top_interesting(limit=limit, system_intent=system_intent, tag=tag)
    items = [
        InterestingItem(
            object_id=row["object_id"],
            score=row["score"],
            novelty=row["novelty"],
            anomaly=row["anomaly"],
            uncertainty=row["uncertainty"],
            value=row["value"],
            reason=row["reason"],
            payload=row["payload"],
            created_at=row["created_at"],
        )
        for row in records
    ]
    return InterestingResponse(items=items)


@router.get("/summary", response_model=InterestingSummary)
def interesting_summary(
    repo: AgentRepository = Depends(get_agent_repository),
) -> InterestingSummary:
    summary = repo.interesting_summary()
    return InterestingSummary(**summary)

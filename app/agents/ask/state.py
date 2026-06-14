from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.agent_memory.recall_explanation import RecallExplanation
from app.agents.runtime_state import RuntimeStateModel


class RetrievedHit(BaseModel):
    object_id: str
    score: float
    ask_score: Optional[float] = None
    origin: Optional[str] = None
    zone: Optional[str] = None
    trust: Optional[str] = None
    title: Optional[str] = None
    path: Optional[str] = None
    snippet: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentState(RuntimeStateModel):
    trace_id: Optional[str] = None
    query: str
    hits: List[RetrievedHit] = Field(default_factory=list)
    recalled: List[RecallExplanation] = Field(default_factory=list)
    answer: Optional[str] = None
    reasoning: Optional[List[str]] = None
    llm_route: dict[str, Any] | None = None

    model_config = {"arbitrary_types_allowed": True}

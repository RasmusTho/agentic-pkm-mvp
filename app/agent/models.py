from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    id: str
    text: str
    tags: List[str] = []
    source: str = "json"


class AgentState(BaseModel):
    run_id: str
    task: str
    profile: str = "work"  # work | home | creative
    ctx: List[ContextItem] = Field(default_factory=list)
    result: Optional[str] = None
    cites: List[str] = Field(default_factory=list)
    feedback: Optional[str] = None
    error: Optional[str] = None

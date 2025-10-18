from __future__ import annotations

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    source: str = "json"


class AgentState(BaseModel):
    run_id: str
    task: str
    user_input: str | None = None
    profile: str = "work"  # work | home | creative
    ctx: list[ContextItem] = Field(default_factory=list)
    result: str | None = None
    cites: list[str] = Field(default_factory=list)
    feedback: str | None = None
    error: str | None = None

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


class ToolDescriptor(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    kind: Literal["mcp", "internal", "cli"]
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    allowed_args: Dict[str, str] = Field(default_factory=dict)
    mock_result: Dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> Dict[str, Any]:
        return self.schema_


class PlanStep(BaseModel):
    id: str
    kind: Literal["agent_call", "tool_call", "decision", "note"]
    description: str
    agent: Optional[str] = None
    agent_id: Optional[str] = None
    intent: Optional[str] = None
    reason: Optional[str] = None
    explanation: Optional[str] = None
    tool: Optional[str] = None
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlanMetadata(BaseModel):
    goal: str
    source_object_uuid: str
    created_by: str
    trace_id: Optional[str] = None


class PlanTrigger(BaseModel):
    event_type: str
    event_id: str
    trace_id: Optional[str] = None


class Plan(BaseModel):
    id: str
    meta: PlanMetadata
    steps: List[PlanStep] = Field(default_factory=list)
    trigger: Optional[PlanTrigger] = None
    goal: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


def new_plan_id() -> str:
    return f"plan-{uuid.uuid4()}"


def make_simple_plan(*, goal: str, source_object_uuid: str, created_by: str = "planner.mock") -> Plan:
    return Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal=goal, source_object_uuid=source_object_uuid, created_by=created_by),
        steps=[
            PlanStep(
                id="step-1",
                kind="agent_call",
                description="Review the note context",
                agent="review-agent",
                intent="analyze",
                reason="Review context to ground follow-up actions",
            ),
            PlanStep(
                id="step-2",
                kind="decision",
                description="Decide whether follow-up actions are needed",
                depends_on=["step-1"],
                reason="Guardrail before taking further steps",
            ),
        ],
        goal=goal,
    )


__all__ = [
    "Plan",
    "PlanMetadata",
    "PlanTrigger",
    "PlanStep",
    "ToolDescriptor",
    "new_plan_id",
    "make_simple_plan",
]

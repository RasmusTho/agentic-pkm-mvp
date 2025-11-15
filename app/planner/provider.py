from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.agents.base.audit import audit_log
from app.services.llm import call_llm

from .prompts import PLANNER_SYSTEM_PROMPT, build_planner_user_prompt
from .schema import Plan, PlanMetadata, PlanStep, new_plan_id


class PlannerRelation(BaseModel):
    source: str
    target: str
    type: str


class PlannerInput(BaseModel):
    object_uuid: str
    goal: str
    text: str
    relations: List[PlannerRelation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BasePlanner(Protocol):
    def plan(self, inp: PlannerInput) -> Plan:
        ...


class MockPlanner(BasePlanner):
    def plan(self, inp: PlannerInput) -> Plan:
        plan_id = new_plan_id()
        meta = PlanMetadata(
            goal=inp.goal,
            source_object_uuid=inp.object_uuid,
            created_by="planner.mock",
            trace_id=inp.metadata.get("trace_id"),
        )
        steps = [
            PlanStep(
                id="step-1",
                kind="agent_call",
                description="Summarize the object and identify follow-ups",
                agent="ingest-agent",
                intent="summarize",
            ),
            PlanStep(
                id="step-2",
                kind="tool_call",
                description="Append insights to the vault note",
                tool="mcp.vault.append_note",
                tool_args={"note_id": inp.object_uuid, "content": "Summaries from ingest-agent"},
                depends_on=["step-1"],
            ),
            PlanStep(
                id="step-3",
                kind="decision",
                description="Decide whether to route to relations agent",
                depends_on=["step-1"],
            ),
        ]
        return Plan(id=plan_id, meta=meta, steps=steps)


class LLMPlanner(BasePlanner):
    def __init__(self) -> None:
        self._fallback = MockPlanner()

    def plan(self, inp: PlannerInput) -> Plan:
        prompt = build_planner_user_prompt(
            goal=inp.goal,
            object_text=inp.text,
            relations=[rel.model_dump() for rel in inp.relations],
            metadata=inp.metadata,
        )
        raw = call_llm(
            "planner",
            {
                "system": PLANNER_SYSTEM_PROMPT,
                "user": prompt,
            },
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback_plan(inp, f"llm-json-error: {exc}")
        try:
            plan = Plan.model_validate(payload)
        except ValidationError as exc:
            return self._fallback_plan(inp, f"llm-validation-error: {exc}")
        plan.meta.goal = plan.meta.goal or inp.goal
        plan.meta.source_object_uuid = inp.object_uuid
        plan.meta.created_by = "planner.llm"
        if not plan.id:
            plan.id = new_plan_id()
        return plan

    def _fallback_plan(self, inp: PlannerInput, reason: str) -> Plan:
        audit_log(
            object_id=inp.object_uuid,
            agent="planner-agent",
            action="planner.plan.fallback",
            trace_id=inp.metadata.get("trace_id"),
            details={"reason": reason},
        )
        return self._fallback.plan(inp)


def get_planner() -> BasePlanner:
    provider = os.getenv("PLANNER_PROVIDER", "mock").strip().lower()
    llm_provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    if provider == "llm":
        if llm_provider == "mock":
            audit_log(
                object_id=None,
                agent="planner-agent",
                action="planner.plan.fallback",
                trace_id=None,
                details={"reason": "llm-provider-disabled"},
            )
            return MockPlanner()
        return LLMPlanner()
    return MockPlanner()


__all__ = [
    "PlannerInput",
    "PlannerRelation",
    "BasePlanner",
    "MockPlanner",
    "LLMPlanner",
    "get_planner",
]

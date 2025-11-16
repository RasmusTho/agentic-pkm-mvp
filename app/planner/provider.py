from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.agents.base.audit import audit_log
from app.events.types import PLANNER_PLAN_FALLBACK
from app.services.llm import call_llm

from .prompts import PLANNER_SYSTEM_PROMPT, build_planner_user_prompt
from .schema import Plan, PlanMetadata, PlanStep, PlanTrigger, new_plan_id


def _merge_context(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    if not base and not override:
        return {}
    merged: Dict[str, Any] = {}
    if base:
        merged.update(base)
    if override:
        merged.update(override)
    return merged


def _merge_tags(existing: List[str], new_tags: List[str]) -> List[str]:
    if not existing and not new_tags:
        return []
    if not existing:
        return list(dict.fromkeys(new_tags))
    merged = list(existing)
    for tag in new_tags:
        if tag not in merged:
            merged.append(tag)
    return merged


def _enrich_plan(plan: Plan, inp: "PlannerInput") -> Plan:
    plan.meta.goal = plan.meta.goal or inp.goal
    plan.meta.source_object_uuid = plan.meta.source_object_uuid or inp.object_uuid
    trace_id = inp.metadata.get("trace_id")
    if trace_id and not plan.meta.trace_id:
        plan.meta.trace_id = trace_id
    if inp.trigger and plan.trigger is None:
        plan.trigger = inp.trigger
    if not plan.goal:
        plan.goal = plan.meta.goal
    plan.context = _merge_context(inp.context, plan.context or {})
    plan.tags = _merge_tags(plan.tags or [], inp.tags)
    return plan


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
    trigger: PlanTrigger | None = None
    context: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


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
        plan = Plan(id=plan_id, meta=meta, steps=steps, trigger=inp.trigger, context=dict(inp.context), goal=inp.goal, tags=list(inp.tags))
        return _enrich_plan(plan, inp)


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
        return _enrich_plan(plan, inp)

    def _fallback_plan(self, inp: PlannerInput, reason: str) -> Plan:
        audit_log(
            object_id=inp.object_uuid,
            agent="planner-agent",
            action=PLANNER_PLAN_FALLBACK,
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
                action=PLANNER_PLAN_FALLBACK,
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

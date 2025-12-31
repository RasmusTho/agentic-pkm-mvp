from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Protocol, Sequence

from pydantic import BaseModel, Field, ValidationError

from app.agents.base.audit import audit_log
from app.events.types import PLANNER_PLAN_FALLBACK
from app.components.llm.fabric import get_chat_client
from app.components.llm.router import LLMTaskIntent

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


def select_flow_pattern_prompt(flow_profiles: Sequence[Mapping[str, Any]] | None) -> Dict[str, Any] | None:
    if not flow_profiles:
        return None
    first = flow_profiles[0]
    patterns = first.get("suggested_patterns") or []
    prompts = first.get("prompt_profiles") or []
    return {
        "flow_id": first.get("flow_id"),
        "flow": first,
        "pattern": patterns[0] if patterns else None,
        "prompt_profile": prompts[0] if prompts else None,
    }


def _step_from_target(step_data: Any, index: int, inp: "PlannerInput") -> PlanStep:
    if isinstance(step_data, BaseModel):
        raw_entry = step_data.model_dump()
    elif isinstance(step_data, dict):
        raw_entry = dict(step_data)
    else:
        raw_entry = {"target": step_data}
    target_value = str(raw_entry.get("target", "")).strip()
    description = raw_entry.get("description")
    intent = raw_entry.get("intent")
    metadata = dict(raw_entry.get("metadata") or {})
    reason_text = raw_entry.get("reason") or raw_entry.get("rationale")
    explanation = raw_entry.get("explanation")
    args = dict(raw_entry.get("args") or {})
    prefix = ""
    remainder = target_value
    if ":" in target_value:
        prefix, remainder = target_value.split(":", 1)
        prefix = prefix.strip().lower()
        remainder = remainder.strip()
    description_fallback = remainder or target_value or f"step-{index}"
    step_id = f"step-{index}"
    if prefix == "agent":
        return PlanStep(
            id=step_id,
            kind="agent_call",
            description=description or f"Execute agent '{description_fallback}'",
            agent=remainder or None,
            intent=intent,
            reason=reason_text or description or f"Agent call for {remainder or description_fallback}",
            explanation=explanation,
        )
    if prefix in {"tool", "mcp"}:
        tool_name = remainder
        if prefix == "mcp" and remainder and not remainder.startswith("mcp"):
            tool_name = f"mcp.{remainder}"
        tool_args = dict(args)
        if tool_name == "mcp.vault.append_note":
            tool_args.setdefault("title", f"Planner note for {inp.object_uuid}")
            tool_args.setdefault("body", f"Planner output for {inp.object_uuid}")
            tool_args.setdefault("tags", ["planner-auto"])
        return PlanStep(
            id=step_id,
            kind="tool_call",
            description=description or f"Invoke tool '{tool_name}'",
            tool=tool_name,
            tool_args=tool_args,
            reason=reason_text or description or f"Tool call for {tool_name}",
            explanation=explanation,
        )
    if prefix == "decision":
        return PlanStep(
            id=step_id,
            kind="decision",
            description=description or f"Decision: {description_fallback}",
            reason=reason_text or description or f"Decision for {description_fallback}",
            explanation=explanation,
            metadata=metadata,
        )
    return PlanStep(
        id=step_id,
        kind="note",
        description=description or f"Note: {description_fallback}",
        reason=reason_text or description or f"Note about {description_fallback}",
        explanation=explanation,
        metadata={"target": target_value, **metadata},
    )


def _steps_from_pattern(pattern: Dict[str, Any] | None, inp: "PlannerInput") -> List[PlanStep]:
    if not pattern:
        return []
    raw_steps = pattern.get("steps") if isinstance(pattern, dict) else None
    if not isinstance(raw_steps, list) or not raw_steps:
        return []
    return [_step_from_target(step, idx + 1, inp) for idx, step in enumerate(raw_steps)]


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
        selection = select_flow_pattern_prompt(inp.context.get("flow_profiles"))
        pattern_steps: List[PlanStep] = []
        plan_context = dict(inp.context)
        if selection:
            pattern_steps = _steps_from_pattern(selection.get("pattern"), inp)
            plan_context.setdefault(
                "profile_selection",
                {
                    "flow_id": selection.get("flow_id"),
                    "pattern": selection.get("pattern"),
                    "prompt_profile": selection.get("prompt_profile"),
                },
            )
        if not pattern_steps:
            pattern_steps = [
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="Summarize the object and identify follow-ups",
                    agent="ingest-agent",
                    intent="summarize",
                    reason="Summaries guide the follow-up actions",
                ),
                PlanStep(
                    id="step-2",
                    kind="tool_call",
                    description="Append insights to the vault note",
                    tool="mcp.vault.append_note",
                    tool_args={
                        "title": f"Summary for {inp.object_uuid}",
                        "body": "Summaries from ingest-agent",
                        "tags": ["ingest-summary"],
                    },
                    depends_on=["step-1"],
                    reason="Persist the summary back to the note",
                ),
                PlanStep(
                    id="step-3",
                    kind="decision",
                    description="Decide whether to route to relations agent",
                    depends_on=["step-1"],
                    reason="Decide if relation building is warranted",
                ),
            ]
        plan = Plan(
            id=plan_id,
            meta=meta,
            steps=pattern_steps,
            trigger=inp.trigger,
            context=plan_context,
            goal=inp.goal,
            tags=list(inp.tags),
        )
        return _enrich_plan(plan, inp)


class LLMPlanner(BasePlanner):
    def __init__(self) -> None:
        self._fallback = MockPlanner()

    def plan(self, inp: PlannerInput) -> Plan:
        flow_profiles_ctx = inp.context.get("flow_profiles")
        if not isinstance(flow_profiles_ctx, list):
            flow_profiles_ctx = None
        selection = select_flow_pattern_prompt(flow_profiles_ctx)
        planning_guidance = None
        if selection:
            flow_data = selection.get("flow") or {}
            planning_guidance = {
                "flow_id": selection.get("flow_id"),
                "intent": flow_data.get("intent"),
                "planner_mode": flow_data.get("planner_mode"),
                "selected_pattern": selection.get("pattern"),
                "selected_prompt_profile": selection.get("prompt_profile"),
            }
        prompt = build_planner_user_prompt(
            goal=inp.goal,
            object_text=inp.text,
            relations=[rel.model_dump() for rel in inp.relations],
            metadata=inp.metadata,
            planning_guidance=planning_guidance,
        )
        trace_id = None
        if isinstance(inp.metadata, dict):
            trace_id = inp.metadata.get("trace_id")
        client = get_chat_client(LLMTaskIntent(task_kind="plan", complexity_hint="high"))
        raw = client.chat(
            "planner",
            {
                "system": PLANNER_SYSTEM_PROMPT,
                "user": prompt,
            },
            agent="planner",
            kind="planner.plan",
            trace_id=trace_id,
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
        if selection:
            plan.context = plan.context or {}
            plan.context.setdefault(
                "profile_selection",
                {
                    "flow_id": selection.get("flow_id"),
                    "pattern": selection.get("pattern"),
                    "prompt_profile": selection.get("prompt_profile"),
                },
            )
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
    provider = os.getenv("PLANNER_PROVIDER", "").strip().lower()
    llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    ci = os.getenv("CI", "") == "1"

    if provider in {"mock", "golden"} or (ci and provider == ""):
        return MockPlanner()

    if provider == "":
        provider = "llm"

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
    "select_flow_pattern_prompt",
    "get_planner",
]

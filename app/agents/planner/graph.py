from __future__ import annotations

import os
from typing import Optional

from langgraph.graph import StateGraph, START, END

from app.agents.base.graph import AgentState
from app.agents.planner.agent import PlannerAgent
from app.domain.state_axes import normalize_plan_state_action
from app.domain.plan import Plan
from app.store.object_store import ObjectStore
import app.guardrails as guardrails


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


DEFAULT_MAX_PLAN_DEPTH = _env_int("PLANNER_MAX_DEPTH", 2)
DEFAULT_MAX_STEPS_PER_PLAN = _env_int("PLANNER_MAX_STEPS_PER_PLAN", 10)
DEFAULT_MAX_REPLANS_PER_PLAN = _env_int("PLANNER_MAX_REPLANS_PER_PLAN", 1)
DEFAULT_MAX_TOTAL_STEPS = _env_int("PLANNER_MAX_TOTAL_STEPS_PER_TASK", 50)


class PlannerGraph:
    """
    Minimal execution-plan graph with planner -> executor -> evaluator nodes.
    This graph manages runtime execution steps, not human commitment or project semantics.
    """

    def __init__(
        self,
        goal: str,
        *,
        store: Optional[ObjectStore] = None,
        max_steps: int = DEFAULT_MAX_STEPS_PER_PLAN,
        max_replans: int = DEFAULT_MAX_REPLANS_PER_PLAN,
        max_depth: int = DEFAULT_MAX_PLAN_DEPTH,
        max_total_steps: int = DEFAULT_MAX_TOTAL_STEPS,
    ) -> None:
        self.goal = goal
        self.store = store or ObjectStore()
        self.agent = PlannerAgent(store=self.store)
        self.max_steps = max_steps
        self.max_replans = max_replans
        self.max_depth = max_depth
        self.max_total_steps = max_total_steps
        self.graph = self._build_graph()

    def _planner_node(self, state: AgentState) -> AgentState:
        current_plan_id = state.get("current_plan_id")
        plan: Plan

        if current_plan_id:
            stored = self.store.get_object(current_plan_id)
            if stored:
                plan = Plan.from_object(stored)
            else:
                plan = self.agent.build_plan(self.goal, max_steps=self.max_steps, max_replans=self.max_replans)
                self.agent.save_plan(plan)
        else:
            plan = self.agent.build_plan(self.goal, max_steps=self.max_steps, max_replans=self.max_replans)
            self.agent.save_plan(plan)
            state["current_plan_id"] = plan.uuid

        plan.max_steps = plan.max_steps or self.max_steps
        plan.max_replans = plan.max_replans or self.max_replans
        state["plan"] = plan
        state["goal"] = state.get("goal") or self.goal
        state.setdefault("current_step_id", None)
        state["current_plan_id"] = plan.uuid
        commitment_handles = self.agent.build_commitment_handles(
            state["goal"],
            target=next((step.target for step in plan.steps if step.target), None),
        )
        state["commitment_handles"] = commitment_handles
        state["primary_commitment_handle"] = self.agent.select_primary_commitment_handle(commitment_handles)
        return state

    def _executor_node(self, state: AgentState) -> AgentState:
        plan: Plan = state.get("plan")  # type: ignore[assignment]
        if not isinstance(plan, Plan):
            return state

        total_steps = state.get("total_steps", 0) or 0
        max_total_steps = state.get("max_total_steps", self.max_total_steps) or self.max_total_steps

        loop_guard = 0
        while loop_guard < (plan.max_steps or self.max_steps):
            loop_guard += 1
            if total_steps >= max_total_steps:
                plan.status = "failed"
                break
            if plan.executed_steps >= (plan.max_steps or self.max_steps):
                plan.status = "failed"
                break

            pending = next((s for s in plan.steps if s.state == "pending"), None)
            if pending is None:
                break

            if pending.kind == "composite":
                subplan = plan.try_create_subplan_for_step(
                    pending.id,
                    max_depth=self.max_depth,
                    max_steps=self.max_steps,
                    max_replans=self.max_replans,
                )
                if subplan:
                    if not subplan.steps:
                        subplan.steps.append(
                            self.agent.build_seed_primitive_step(
                                subplan.goal,
                                pending.target or plan.goal,
                                step_id="primitive-1",
                            )
                        )
                    self.agent.save_plan(subplan)
                    sub_graph = PlannerGraph(
                        goal=subplan.goal,
                        store=self.store,
                        max_steps=self.max_steps,
                        max_replans=self.max_replans,
                        max_depth=self.max_depth,
                        max_total_steps=self.max_total_steps,
                    )
                    sub_state: AgentState = {
                        "input": {"goal": subplan.goal},
                        "goal": subplan.goal,
                        "current_plan_id": subplan.uuid,
                        "current_step_id": None,
                    }
                    sub_graph.run(sub_state)
                    stored_sub = self.store.get_object(subplan.uuid)
                    if stored_sub:
                        subplan = Plan.from_object(stored_sub)
                    pending.state = "done" if subplan.status == "done" else "failed"
                else:
                    pending.kind = "primitive"
                    pending.action = pending.action or "noop"
                    pending.state = "pending"

                state["plan"] = plan
                self.agent.save_plan(plan)
                continue

            pre_decision = guardrails.run_pre_guardrails(
                pending.action or "unknown_action",
                pending.args,
                state,
            )
            if pre_decision.status in ("block", "fail"):
                pending.state = "failed"
                plan.status = "failed"
                self.agent.save_plan(plan)
                state["plan"] = plan
                break
            args = pre_decision.modified_args if pre_decision.status == "modify" else pending.args
            if pre_decision.status == "modify":
                pending.args = args

            result = self._run_primitive_action(pending.action, pending.target, args)
            post_decision = guardrails.run_post_guardrails(
                pending.action or "unknown_action",
                args,
                result,
                state,
            )
            result_ok = bool(result.get("ok"))
            if post_decision.status == "fail":
                pending.state = "failed"
                plan.status = "failed"
            elif post_decision.status == "modify":
                result = post_decision.modified_result or result
                result_ok = bool(result.get("ok", True))
                if result_ok:
                    pending.state = "done"
                    plan.executed_steps += 1
                else:
                    pending.state = "failed"
                    plan.status = "failed"
            else:
                if result_ok:
                    pending.state = "done"
                    plan.executed_steps += 1
                else:
                    pending.state = "failed"
                    plan.status = "failed"

            state["last_result"] = result
            total_steps += 1
            state["total_steps"] = total_steps
            state["max_total_steps"] = max_total_steps

            self.agent.save_plan(plan)
            state["plan"] = plan

            if plan.status == "failed":
                break

        self.agent.save_plan(plan)
        state["plan"] = plan
        return state

    def _run_primitive_action(self, action: Optional[str], target: Optional[str], args: dict) -> dict:
        action_name = action or "noop"
        if action_name == "noop":
            return {"ok": True, "action": "noop"}

        if not target:
            return {"ok": False, "reason": "missing_target"}

        obj = self.store.get_object(target)
        if not obj:
            return {"ok": False, "reason": "missing_object", "target": target}

        normalized_action, normalized_args = normalize_plan_state_action(action_name, args)

        if normalized_action in ("set_review_state", "set_maturity", "request_promotion_transition"):
            payload = obj.payload or {}
            frontmatter = payload.get("frontmatter") or {}

            if normalized_action in ("set_review_state", "request_promotion_transition"):
                frontmatter["review_state"] = normalized_args.get("review_state") or "provisional"

            if normalized_action in ("set_maturity", "request_promotion_transition"):
                new_maturity = normalized_args.get("maturity")
                if new_maturity:
                    frontmatter["maturity"] = str(new_maturity)

            payload["frontmatter"] = frontmatter
            obj.payload = payload
            self.store.save_object(obj, emit_outbox=False)

            result = {"ok": True, "action": normalized_action, "target": target}
            if "review_state" in frontmatter:
                result["review_state"] = frontmatter["review_state"]
            if "maturity" in frontmatter:
                result["maturity"] = frontmatter["maturity"]
            return result

        return {"ok": False, "reason": "unknown_action", "action": action_name, "target": target}

    def _evaluator_node(self, state: AgentState) -> AgentState:
        plan: Plan = state.get("plan")  # type: ignore[assignment]
        if not isinstance(plan, Plan):
            return state

        if plan.executed_steps > (plan.max_steps or self.max_steps):
            plan.status = "failed"

        if plan.status != "failed":
            if all(step.state == "done" for step in plan.steps):
                plan.status = "done"
            elif any(step.state == "failed" for step in plan.steps):
                plan.status = "failed"
            else:
                plan.status = "in_progress"

        self.agent.save_plan(plan)
        state["plan"] = plan
        return state

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("planner_node", self._planner_node)
        graph.add_node("executor_node", self._executor_node)
        graph.add_node("evaluator_node", self._evaluator_node)

        graph.add_edge(START, "planner_node")
        graph.add_edge("planner_node", "executor_node")
        graph.add_edge("executor_node", "evaluator_node")
        graph.add_edge("evaluator_node", END)
        return graph.compile()

    def run(self, state: AgentState) -> AgentState:
        return self.graph.invoke(state)


def run_planner_for_goal(
    goal: str,
    *,
    store: Optional[ObjectStore] = None,
    max_steps: int = DEFAULT_MAX_STEPS_PER_PLAN,
    max_replans: int = DEFAULT_MAX_REPLANS_PER_PLAN,
    max_depth: int = DEFAULT_MAX_PLAN_DEPTH,
    max_total_steps: int = DEFAULT_MAX_TOTAL_STEPS,
) -> Plan:
    planner = PlannerGraph(
        goal=goal,
        store=store,
        max_steps=max_steps,
        max_replans=max_replans,
        max_depth=max_depth,
        max_total_steps=max_total_steps,
    )
    initial_state: AgentState = {
        "input": {"goal": goal},
        "goal": goal,
        "current_plan_id": None,
        "current_step_id": None,
        "total_steps": 0,
        "max_total_steps": max_total_steps,
    }
    final_state = planner.run(initial_state)
    plan = final_state.get("plan")
    if isinstance(plan, Plan):
        return plan

    plan_id = final_state.get("current_plan_id")
    if plan_id:
        stored = planner.store.get_object(plan_id)
        if stored:
            return Plan.from_object(stored)
    raise RuntimeError("planner did not produce a Plan")

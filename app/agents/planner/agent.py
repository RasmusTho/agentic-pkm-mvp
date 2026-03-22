from __future__ import annotations

import re
from typing import Optional

from app.domain.state_axes import normalize_plan_state_action
from app.domain.plan import Plan, PlanStep
from app.store.object_store import ObjectStore


class PlannerAgent:
    """
    Minimal planner agent placeholder.
    Creates a top-level plan for a given goal; execution is delegated to PlannerGraph.
    """

    def __init__(self, store: Optional[ObjectStore] = None) -> None:
        self.store = store or ObjectStore()

    def _extract_target_uuid(self, goal: str) -> Optional[str]:
        uuid_re = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
        match = uuid_re.search(goal)
        if match:
            return match.group(0)
        # fallback: last token if it looks like a uuid-ish string
        tokens = goal.split()
        if tokens:
            last = tokens[-1]
            if uuid_re.fullmatch(last):
                return last
        return None

    def _new_step_id(self, prefix: str, index: int) -> str:
        return f"{prefix}-{index}"

    def _goal_wants_evergreen(self, goal: str) -> bool:
        return "evergreen" in goal.lower()

    def build_seed_primitive_step(self, goal: str, target: Optional[str], *, step_id: str = "primitive-1") -> PlanStep:
        wants_evergreen = self._goal_wants_evergreen(goal)
        primitive_action, primitive_args = normalize_plan_state_action(
            "request_promotion_transition" if wants_evergreen else "set_review_state",
            {"maturity": "evergreen"} if wants_evergreen else {"review_state": "processed"},
        )
        return PlanStep(
            id=step_id,
            kind="primitive",
            action=primitive_action,
            target=target,
            args=primitive_args,
        )

    def build_plan(self, goal: str, *, max_steps: int = 10, max_replans: int = 0) -> Plan:
        plan = Plan.create_top_level(goal=goal, max_steps=max_steps, max_replans=max_replans)
        target_uuid = self._extract_target_uuid(goal)

        plan.steps = [
            PlanStep(
                id=self._new_step_id("composite", 1),
                kind="composite",
                goal=f"Process goal: {goal}",
                target=target_uuid,
                args={},
            ),
            self.build_seed_primitive_step(goal, target_uuid, step_id=self._new_step_id("primitive", 1)),
        ]
        plan.max_steps = max_steps
        plan.max_replans = max_replans
        return plan

    def save_plan(self, plan: Plan) -> None:
        obj = plan.to_object()
        self.store.save_object(obj, emit_outbox=False)

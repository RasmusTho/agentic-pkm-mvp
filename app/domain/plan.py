from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from app.objects import DomainObject


PlanStatus = Literal["planned", "in_progress", "done", "failed"]
PlanStepKind = Literal["composite", "primitive"]
PlanStepState = Literal["pending", "in_progress", "done", "failed"]


@dataclass
class PlanStep:
    id: str
    kind: PlanStepKind
    goal: Optional[str] = None
    action: Optional[str] = None
    target: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    state: PlanStepState = "pending"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        return cls(
            id=data.get("id") or data.get("uuid") or "",
            kind=data.get("kind", "primitive"),
            goal=data.get("goal"),
            action=data.get("action"),
            target=data.get("target"),
            args=dict(data.get("args") or {}),
            state=data.get("state", "pending"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "goal": self.goal,
            "action": self.action,
            "target": self.target,
            "args": dict(self.args),
            "state": self.state,
        }


@dataclass
class Plan:
    uuid: str
    parent_plan: Optional[str]
    depth: int
    goal: str
    status: PlanStatus
    steps: List[PlanStep] = field(default_factory=list)
    replans_used: int = 0
    max_replans: int = 0
    executed_steps: int = 0
    max_steps: int = 0

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def create_subplan_for_step(self, step_id: str, *, max_steps: int, max_replans: int) -> "Plan":
        step = self.get_step(step_id)
        if step is None:
            raise ValueError(f"step {step_id} not found")
        goal = step.goal or self.goal
        return Plan(
            uuid=str(uuid4()),
            parent_plan=self.uuid,
            depth=self.depth + 1,
            goal=goal,
            status="planned",
            steps=[],
            replans_used=0,
            max_replans=max_replans,
            executed_steps=0,
            max_steps=max_steps,
        )

    def try_create_subplan_for_step(
        self,
        step_id: str,
        *,
        max_depth: int,
        max_steps: int,
        max_replans: int,
    ) -> Optional["Plan"]:
        if self.depth >= max_depth:
            return None
        return self.create_subplan_for_step(step_id, max_steps=max_steps, max_replans=max_replans)

    @classmethod
    def create_top_level(cls, goal: str, max_steps: int, max_replans: int) -> "Plan":
        return cls(
            uuid=str(uuid4()),
            parent_plan=None,
            depth=0,
            goal=goal,
            status="planned",
            steps=[],
            replans_used=0,
            max_replans=max_replans,
            executed_steps=0,
            max_steps=max_steps,
        )

    @classmethod
    def from_object(cls, obj: DomainObject | Dict[str, Any]) -> "Plan":
        # Accept either DomainObject or plain dict with payload.
        payload: Dict[str, Any]
        uuid_value: Optional[str] = None
        if isinstance(obj, DomainObject):
            payload = obj.payload or {}
            uuid_value = obj.uuid
        else:
            payload = obj.get("payload") or {}
            uuid_value = obj.get("uuid")

        plan_payload = payload.get("plan") or payload
        raw_steps = plan_payload.get("steps", [])
        steps: List[PlanStep] = []
        for step in raw_steps:
            if isinstance(step, PlanStep):
                steps.append(step)
            else:
                steps.append(PlanStep.from_dict(step or {}))
        return cls(
            uuid=plan_payload.get("uuid") or uuid_value or "",
            parent_plan=plan_payload.get("parent_plan"),
            depth=int(plan_payload.get("depth", 0)),
            goal=plan_payload.get("goal") or "",
            status=plan_payload.get("status", "planned"),
            steps=steps,
            replans_used=int(plan_payload.get("replans_used", 0)),
            max_replans=int(plan_payload.get("max_replans", 0)),
            executed_steps=int(plan_payload.get("executed_steps", 0)),
            max_steps=int(plan_payload.get("max_steps", 0)),
        )

    def to_object(
        self,
        *,
        origin: str = "planner",
        source_ref: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> DomainObject:
        created_at = created_at or datetime.now(timezone.utc)
        plan_payload = {
            "uuid": self.uuid,
            "parent_plan": self.parent_plan,
            "depth": self.depth,
            "goal": self.goal,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "replans_used": self.replans_used,
            "max_replans": self.max_replans,
            "executed_steps": self.executed_steps,
            "max_steps": self.max_steps,
        }
        frontmatter = {
            "uuid": self.uuid,
            "origin": origin,
            "created": created_at.isoformat(),
            "updated": created_at.isoformat(),
            "type": "plan",
            "parent_plan": self.parent_plan,
        }
        payload = {
            "frontmatter": frontmatter,
            "plan": plan_payload,
        }
        return DomainObject(
            uuid=self.uuid,
            kind="plan",
            payload=payload,
            source_ref=source_ref,
            created_at=created_at,
        )


__all__ = ["Plan", "PlanStep", "PlanStatus", "PlanStepKind", "PlanStepState"]

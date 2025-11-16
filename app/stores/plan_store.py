from __future__ import annotations

from typing import Dict, List, Optional

from app.planner.schema import Plan


class PlanStore:
    def save(self, plan: Plan) -> None:
        raise NotImplementedError

    def get(self, plan_id: str) -> Optional[Plan]:
        raise NotImplementedError

    def list_by_event(self, event_id: str) -> List[Plan]:
        raise NotImplementedError


class MemoryPlanStore(PlanStore):
    def __init__(self) -> None:
        self._plans: Dict[str, Plan] = {}
        self._by_event: Dict[str, List[str]] = {}

    def save(self, plan: Plan) -> None:
        self._plans[plan.id] = plan
        event_id = plan.trigger.event_id if plan.trigger else None
        if not event_id:
            return
        slots = self._by_event.setdefault(event_id, [])
        if plan.id not in slots:
            slots.append(plan.id)

    def get(self, plan_id: str) -> Optional[Plan]:
        return self._plans.get(plan_id)

    def list_by_event(self, event_id: str) -> List[Plan]:
        ids = self._by_event.get(event_id) or []
        return [self._plans[pid] for pid in ids if pid in self._plans]


_PLAN_STORE: MemoryPlanStore | None = None


def get_plan_store() -> PlanStore:
    global _PLAN_STORE
    if _PLAN_STORE is None:
        _PLAN_STORE = MemoryPlanStore()
    return _PLAN_STORE


def reset_plan_store() -> None:
    global _PLAN_STORE
    _PLAN_STORE = MemoryPlanStore()


__all__ = ["PlanStore", "MemoryPlanStore", "get_plan_store", "reset_plan_store"]

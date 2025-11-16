from __future__ import annotations

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.agents.pipeline import maybe_plan_for_object
from app.events.types import PLANNER_PLAN_CREATED

pytestmark = pytest.mark.not_pg


def test_maybe_plan_emits_audit_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNER_ENABLE", "1")
    monkeypatch.setenv("PLANNER_PROVIDER", "mock")
    before = _audit_ring_snapshot()
    plan = maybe_plan_for_object("obj-20", "text body", "trace-20")
    assert plan is not None
    after = _audit_ring_snapshot()
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == PLANNER_PLAN_CREATED and evt["payload"].get("details", {}).get("plan_id") == plan.id for evt in new_events)


def test_maybe_plan_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANNER_ENABLE", raising=False)
    plan = maybe_plan_for_object("obj-21", "text body", "trace-21")
    assert plan is None

from __future__ import annotations

import pytest

from app.agents.pipeline import maybe_plan_for_object

pytestmark = pytest.mark.not_pg


def test_pipeline_executes_plan_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNER_ENABLE", "1")
    monkeypatch.setenv("PLANNER_PROVIDER", "mock")
    monkeypatch.setenv("ORCHESTRATOR_ENABLE", "1")

    captured: dict[str, str] = {}

    class StubOrchestrator:
        def run_plan(self, plan):
            captured["plan_id"] = plan.id
            return [{"step_id": "stub", "status": "ok"}]

    monkeypatch.setattr("app.agents.pipeline._get_orchestrator", lambda: StubOrchestrator())

    plan = maybe_plan_for_object("obj-202", "text body for orchestration", "trace-202")
    assert plan is not None
    assert captured["plan_id"] == plan.id

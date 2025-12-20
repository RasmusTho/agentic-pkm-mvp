from __future__ import annotations

import pytest

pytestmark = pytest.mark.not_pg

from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    monkeypatch.delenv("POLICY_ENFORCE", raising=False)
    yield


def _context(agent_id: str | None) -> StepContext:
    meta = PlanMetadata(goal="test", source_object_uuid="obj-1", created_by="planner.mock")
    return StepContext(
        plan_id="plan-1",
        object_id=None,
        trace_id=None,
        metadata=meta,
        results={},
        agent_id=agent_id,
    )


def test_tool_policy_allows_known_tool(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "1")
    executor = MockPlanExecutor()
    step = PlanStep(id="s1", kind="tool_call", description="search", tool="mcp.search.objects", tool_args={"query": "foo"})
    ctx = _context("ask.v1")

    result = executor.execute_step(step, ctx)
    assert result["tool"] == "mcp.search.objects"


def test_tool_policy_blocks_missing_agent_id(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "1")
    executor = MockPlanExecutor()
    step = PlanStep(id="s1", kind="tool_call", description="search", tool="mcp.search.objects", tool_args={"query": "foo"})
    ctx = _context(None)

    with pytest.raises(StepExecutionError) as excinfo:
        executor.execute_step(step, ctx)
    assert excinfo.value.error_type == "policy_denied"
    assert "agent_id" in str(excinfo.value)


def test_tool_policy_disabled_allows_any_tool(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "0")
    executor = MockPlanExecutor()
    step = PlanStep(id="s1", kind="tool_call", description="append", tool="mcp.vault.append_note", tool_args={"title": "t", "body": "b"})
    ctx = _context(None)

    result = executor.execute_step(step, ctx)
    assert result["tool"] == "mcp.vault.append_note"


def test_orchestrator_uses_step_agent_id_for_policy(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "1")
    plan = Plan(
        id="plan-allow",
        meta=PlanMetadata(goal="test", source_object_uuid="obj-123", created_by="planner.mock"),
        steps=[
            PlanStep(
                id="s1",
                kind="tool_call",
                description="search",
                tool="mcp.search.objects",
                tool_args={"query": "foo"},
                agent_id="ask.v1",
            )
        ],
    )

    results = Orchestrator().run_plan(plan)
    assert results[0]["status"] == "ok"

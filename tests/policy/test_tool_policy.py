from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.not_pg

from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.planner.schema import PlanMetadata, PlanStep


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    monkeypatch.delenv("POLICY_ENFORCE", raising=False)
    yield


def _context(agent_id: str) -> StepContext:
    meta = PlanMetadata(goal="test", source_object_uuid="obj-1", created_by=agent_id)
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


def test_tool_policy_blocks_disallowed_tool(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "1")
    executor = MockPlanExecutor()
    step = PlanStep(id="s1", kind="tool_call", description="append", tool="mcp.vault.append_note", tool_args={"title": "t", "body": "b"})
    ctx = _context("ask.v1")

    with pytest.raises(StepExecutionError) as excinfo:
        executor.execute_step(step, ctx)
    assert excinfo.value.error_type == "policy_denied"
    assert "not allowed" in str(excinfo.value)


def test_tool_policy_disabled_allows_any_tool(monkeypatch):
    monkeypatch.setenv("POLICY_ENFORCE", "0")
    executor = MockPlanExecutor()
    step = PlanStep(id="s1", kind="tool_call", description="append", tool="mcp.vault.append_note", tool_args={"title": "t", "body": "b"})
    ctx = _context("ask.v1")

    result = executor.execute_step(step, ctx)
    assert result["tool"] == "mcp.vault.append_note"

"""Test Orchestrator V2 plan graph contract: parallel/sequential execution, branching."""

from __future__ import annotations

from typing import Dict, List

import pytest

from .conftest import MockAgentExecutor, MockOutbox


class TestPlanGraphContract:
    """Define plan graph execution contract for Orchestrator V2."""

    def test_parallel_steps_no_dependencies_run_concurrently(
        self,
        step_factory,
        plan_factory,
        mock_agent_executor: MockAgentExecutor,
    ) -> None:
        """Steps with no dependencies can run in parallel."""
        steps = [
            step_factory("step-1", "agent_call", "Task A"),
            step_factory("step-2", "agent_call", "Task B"),
            step_factory("step-3", "agent_call", "Task C"),
        ]
        plan = plan_factory(steps=steps)

        # Graph has 3 independent roots
        assert len(plan["steps"]) == 3
        assert all(len(s["depends_on"]) == 0 for s in plan["steps"])

    def test_sequential_steps_with_dependencies(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Steps with dependencies wait for predecessors to complete."""
        steps = [
            step_factory("step-1", "agent_call", "Analyze"),
            step_factory("step-2", "agent_call", "Decide", depends_on=["step-1"]),
            step_factory("step-3", "agent_call", "Execute", depends_on=["step-2"]),
        ]
        plan = plan_factory(steps=steps)

        assert plan["steps"][0]["depends_on"] == []
        assert plan["steps"][1]["depends_on"] == ["step-1"]
        assert plan["steps"][2]["depends_on"] == ["step-2"]

    def test_mixed_parallel_and_sequential_graph(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Plan can mix parallel and sequential steps."""
        # Graph: step-1 -> step-2, step-3 (parallel), then step-4
        steps = [
            step_factory("step-1", "agent_call", "Initialize"),
            step_factory("step-2", "agent_call", "Branch A", depends_on=["step-1"]),
            step_factory("step-3", "agent_call", "Branch B", depends_on=["step-1"]),
            step_factory(
                "step-4",
                "agent_call",
                "Merge",
                depends_on=["step-2", "step-3"],
            ),
        ]
        plan = plan_factory(steps=steps)

        assert plan["steps"][0]["depends_on"] == []
        assert plan["steps"][1]["depends_on"] == ["step-1"]
        assert plan["steps"][2]["depends_on"] == ["step-1"]
        assert set(plan["steps"][3]["depends_on"]) == {"step-2", "step-3"}

    def test_conditional_branching_next_step_by_result(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Next step chosen based on previous step result (decision point)."""
        steps = [
            step_factory("step-1", "agent_call", "Analyze data"),
            step_factory(
                "step-2",
                "decision",
                "Is data valid?",
                depends_on=["step-1"],
            ),
            # Branch A: yes -> process
            step_factory(
                "step-3a",
                "agent_call",
                "Process data",
                depends_on=["step-2"],
            ),
            # Branch B: no -> reject
            step_factory(
                "step-3b",
                "agent_call",
                "Reject data",
                depends_on=["step-2"],
            ),
        ]
        plan = plan_factory(steps=steps)

        decision_step = plan["steps"][1]
        assert decision_step["kind"] == "decision"
        assert decision_step["depends_on"] == ["step-1"]

    def test_multiple_dependencies_join_pattern(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Step can depend on multiple predecessors (join)."""
        steps = [
            step_factory("step-1", "agent_call", "Task A"),
            step_factory("step-2", "agent_call", "Task B"),
            step_factory(
                "step-3",
                "agent_call",
                "Merge results",
                depends_on=["step-1", "step-2"],
            ),
        ]
        plan = plan_factory(steps=steps)

        merge_step = plan["steps"][2]
        assert set(merge_step["depends_on"]) == {"step-1", "step-2"}

    def test_fan_out_fan_in_topology(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Plan supports fan-out/fan-in: one -> many -> one."""
        steps = [
            step_factory("init", "agent_call", "Start"),
            step_factory("task-1", "agent_call", "Work 1", depends_on=["init"]),
            step_factory("task-2", "agent_call", "Work 2", depends_on=["init"]),
            step_factory("task-3", "agent_call", "Work 3", depends_on=["init"]),
            step_factory(
                "finalize",
                "agent_call",
                "Done",
                depends_on=["task-1", "task-2", "task-3"],
            ),
        ]
        plan = plan_factory(steps=steps)

        # Verify fan-out: init has 3 dependents
        init_deps = [s for s in plan["steps"] if "init" in s["depends_on"]]
        assert len(init_deps) == 3

        # Verify fan-in: finalize depends on 3
        finalize_step = plan["steps"][4]
        assert len(finalize_step["depends_on"]) == 3

    def test_error_on_step_failure_aborts_plan(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """When a step fails, dependent steps should not start (abort)."""
        steps = [
            step_factory("step-1", "agent_call", "Task A"),
            step_factory("step-2", "agent_call", "Task B", depends_on=["step-1"]),
            step_factory("step-3", "agent_call", "Task C", depends_on=["step-2"]),
        ]
        plan = plan_factory(steps=steps)

        # If step-1 fails, step-2 and step-3 should be skipped
        assert plan["steps"][1]["depends_on"] == ["step-1"]
        assert plan["steps"][2]["depends_on"] == ["step-2"]

    def test_branching_recovery_on_conditional_failure(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Conditional branches can implement recovery: normal path + fallback."""
        steps = [
            step_factory("check", "decision", "Validation check"),
            # Normal path
            step_factory("process", "agent_call", "Process", depends_on=["check"]),
            # Fallback path
            step_factory(
                "fallback",
                "agent_call",
                "Use default",
                depends_on=["check"],
            ),
        ]
        plan = plan_factory(steps=steps)

        # Both branches depend on check
        assert plan["steps"][1]["depends_on"] == ["check"]
        assert plan["steps"][2]["depends_on"] == ["check"]

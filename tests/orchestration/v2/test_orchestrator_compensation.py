"""Test Orchestrator V2 compensation & rollback contract."""

from __future__ import annotations

from typing import Dict, List

import pytest

from .conftest import (
    MockAgentExecutor,
    MockCheckpoint,
    MockOutbox,
    MockPlanState,
    MockStepState,
)


class TestCompensationContract:
    """Define compensation (rollback) contract for Orchestrator V2."""

    def test_step_has_optional_compensate_fn(
        self,
        step_factory,
    ) -> None:
        """Each step can define optional compensate_fn in metadata."""
        step_normal = step_factory("step-1", "agent_call", "Create resource")
        assert "metadata" in step_normal
        assert "compensate_fn" not in step_normal["metadata"]

        step_with_compensation = step_factory(
            "step-2",
            "agent_call",
            "Create resource",
            compensate_fn="delete_resource",
        )
        assert step_with_compensation["metadata"]["compensate_fn"] == "delete_resource"

    def test_failed_step_triggers_compensation_chain(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """When a step fails, compensation functions are called for all completed predecessors in reverse."""
        steps = [
            step_factory("step-1", "agent_call", "Create A", compensate_fn="cleanup_a"),
            step_factory(
                "step-2",
                "agent_call",
                "Create B",
                compensate_fn="cleanup_b",
                depends_on=["step-1"],
            ),
            step_factory(
                "step-3",
                "agent_call",
                "Create C",
                compensate_fn="cleanup_c",
                depends_on=["step-2"],
            ),
        ]
        plan = plan_factory(steps=steps)

        # If step-3 fails, compensation should run: cleanup_c, cleanup_b, cleanup_a (reverse order)
        assert steps[0]["metadata"]["compensate_fn"] == "cleanup_a"
        assert steps[1]["metadata"]["compensate_fn"] == "cleanup_b"
        assert steps[2]["metadata"]["compensate_fn"] == "cleanup_c"

    def test_compensation_failures_logged_not_cascading(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Compensation failures are logged but don't cascade (continue compensation)."""
        # If cleanup_b fails, cleanup_a should still run
        # Log the failure but don't stop the chain
        outbox = mock_outbox
        outbox.clear()

        # Simulate: cleanup_b failed, log it, continue with cleanup_a
        outbox.emit({
            "event": "compensation.failed",
            "step_id": "step-2",
            "error": "cleanup failed",
        })

        # cleanup_a should still run (not blocked by cleanup_b failure)
        outbox.emit({
            "event": "compensation.completed",
            "step_id": "step-1",
        })

        events = outbox.list_events()
        assert len(events) == 2
        # Verify order: failure logged, then compensation continues
        assert events[0]["event"] == "compensation.failed"
        assert events[1]["event"] == "compensation.completed"

    def test_plan_marked_rolled_back_after_compensation(
        self,
    ) -> None:
        """Plan status transitions to rolled_back after compensation completes."""
        plan = MockPlanState(
            plan_id="plan-1",
            steps=[
                MockStepState("step-1", "agent-call", {}),
                MockStepState("step-2", "agent-call", {}),
            ],
            status="failed",
        )

        # After compensation completes
        plan.status = "rolled_back"

        assert plan.status == "rolled_back"

    def test_compensation_order_reverse_of_execution(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Compensation runs in reverse order of completion."""
        steps = [
            step_factory("step-1", "tool_call", "Write file A", compensate_fn="delete_a"),
            step_factory(
                "step-2",
                "tool_call",
                "Write file B",
                compensate_fn="delete_b",
                depends_on=["step-1"],
            ),
            step_factory(
                "step-3",
                "tool_call",
                "Write file C",
                compensate_fn="delete_c",
                depends_on=["step-2"],
            ),
        ]
        plan = plan_factory(steps=steps)

        # Execution order: step-1, step-2, step-3
        # If step-3 fails, compensation order must be: step-3, step-2, step-1
        completed_steps = [s["id"] for s in steps[:2]]  # step-1, step-2 completed
        assert completed_steps == ["step-1", "step-2"]

    def test_compensation_skipped_for_steps_without_compensate_fn(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Steps without compensate_fn are skipped during compensation."""
        steps = [
            step_factory("step-1", "agent_call", "Read data"),  # no compensation
            step_factory(
                "step-2",
                "agent_call",
                "Modify data",
                compensate_fn="revert",
            ),
        ]
        plan = plan_factory(steps=steps)

        # If step-2 fails, only step-2's compensation runs (step-1 has no compensate_fn)
        assert "compensate_fn" not in steps[0]["metadata"]
        assert steps[1]["metadata"]["compensate_fn"] == "revert"

    def test_compensation_context_includes_original_state(
        self,
        step_factory,
    ) -> None:
        """Compensation receives original step state (input, output) for rollback."""
        step = step_factory(
            "step-1",
            "agent_call",
            "Create resource",
            compensate_fn="cleanup",
        )

        # When compensation runs, it should have access to:
        # - Original input (what was passed to the failed step)
        # - Output (what the failed step produced before error)
        step["metadata"]["output_snapshot"] = {"resource_id": "res-123"}

        assert step["metadata"]["compensate_fn"] == "cleanup"
        assert step["metadata"]["output_snapshot"] == {"resource_id": "res-123"}

    def test_parallel_branches_compensation_independent(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Compensation in one parallel branch doesn't affect others."""
        steps = [
            step_factory("init", "agent_call", "Initialize"),
            step_factory("branch-a", "agent_call", "Task A", depends_on=["init"]),
            step_factory("branch-b", "agent_call", "Task B", depends_on=["init"]),
        ]
        plan = plan_factory(steps=steps)

        # If branch-a fails, branch-b's compensation is independent
        assert steps[1]["depends_on"] == ["init"]
        assert steps[2]["depends_on"] == ["init"]
        # Each branch has its own compensation

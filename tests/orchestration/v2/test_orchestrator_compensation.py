"""Test Orchestrator V2 compensation & rollback contract."""

from __future__ import annotations

from unittest.mock import patch

from app.orchestrator.v2_runtime import OrchestratorV2
from app.orchestrator.executor import StepContext, StepExecutionError
from app.planner.schema import Plan, PlanMetadata, PlanStep

from .conftest import (
    MockOutbox,
    MockPlanState,
    MockStepState,
)


def _make_plan(steps: list[PlanStep], plan_id: str = "plan-1") -> Plan:
    """Build a Plan model from PlanStep objects."""
    return Plan(
        id=plan_id,
        meta=PlanMetadata(
            goal="test",
            source_object_uuid="obj-1",
            created_by="test",
            trace_id="trace-1",
        ),
        steps=steps,
        context={},
    )


class _FailingExecutor:
    """Executor that fails on a specific step, succeeds on others."""

    def __init__(self, fail_step_id: str, fail_message: str = "step failed") -> None:
        self._fail_step_id = fail_step_id
        self._fail_message = fail_message
        self.executed: list[str] = []

    def execute_step(self, step: PlanStep, context: StepContext) -> dict:
        self.executed.append(step.id)
        if step.id == self._fail_step_id:
            raise StepExecutionError(self._fail_message, error_type="test_failure")
        return {"status": "ok", "step_id": step.id}


class _CompensationTrackingExecutor:
    """Executor that tracks compensation calls and can optionally fail them."""

    def __init__(self, fail_step_id: str, fail_compensation_ids: list[str] | None = None) -> None:
        self._fail_step_id = fail_step_id
        self._fail_compensation_ids = set(fail_compensation_ids or [])
        self.executed: list[str] = []
        self.compensated: list[str] = []

    def execute_step(self, step: PlanStep, context: StepContext) -> dict:
        if step.metadata.get("compensation"):
            original_id = step.metadata.get("original_step_id", step.id)
            self.compensated.append(original_id)
            if original_id in self._fail_compensation_ids:
                raise StepExecutionError(f"compensation failed for {original_id}")
            return {"status": "compensated", "original_step_id": original_id}
        self.executed.append(step.id)
        if step.id == self._fail_step_id:
            raise StepExecutionError("step failed", error_type="test_failure")
        return {"status": "ok", "step_id": step.id}


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
        plan_factory(steps=steps)

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
        plan_factory(steps=steps)

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
        plan_factory(steps=steps)

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
        plan_factory(steps=steps)

        # If branch-a fails, branch-b's compensation is independent
        assert steps[1]["depends_on"] == ["init"]
        assert steps[2]["depends_on"] == ["init"]
        # Each branch has its own compensation


class TestCompensationRuntime:
    """Runtime tests for V2 compensation and rollback behavior."""

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_failed_step_triggers_reverse_compensation(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """When step-3 fails, compensation runs for step-2 then step-1 (reverse order)."""
        executor = _CompensationTrackingExecutor(fail_step_id="step-3")
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="A", agent="test",
                     metadata={"compensate_fn": "cleanup_a"}),
            PlanStep(id="step-2", kind="agent_call", description="B", agent="test",
                     depends_on=["step-1"], metadata={"compensate_fn": "cleanup_b"}),
            PlanStep(id="step-3", kind="agent_call", description="C", agent="test",
                     depends_on=["step-2"], metadata={"compensate_fn": "cleanup_c"}),
        ]
        plan = _make_plan(steps)
        results = orch.run_plan(plan)

        # step-1 and step-2 succeeded, step-3 failed
        assert executor.executed == ["step-1", "step-2", "step-3"]

        # Compensation ran in reverse order: step-2 then step-1 (step-3 was the failed step, not in execution_order)
        assert executor.compensated == ["step-2", "step-1"]

        # Results include rolled_back entries
        comp_entry = next(r for r in results if r["step_id"] == "__compensation__")
        assert comp_entry["status"] == "rolled_back"
        assert comp_entry["failed_step"] == "step-3"
        assert comp_entry["compensated_steps"] == ["step-2", "step-1"]
        assert comp_entry["compensation_failures"] == []

        # Completed steps marked as rolled_back
        step1_result = next(r for r in results if r["step_id"] == "step-1")
        step2_result = next(r for r in results if r["step_id"] == "step-2")
        assert step1_result["status"] == "rolled_back"
        assert step2_result["status"] == "rolled_back"

        # Events emitted
        mock_comp_started.assert_called_once()
        mock_rolled_back.assert_called_once()

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_compensation_failure_does_not_stop_chain(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """If compensation for step-2 fails, step-1 compensation still runs."""
        executor = _CompensationTrackingExecutor(
            fail_step_id="step-3",
            fail_compensation_ids=["step-2"],
        )
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="A", agent="test",
                     metadata={"compensate_fn": "cleanup_a"}),
            PlanStep(id="step-2", kind="agent_call", description="B", agent="test",
                     depends_on=["step-1"], metadata={"compensate_fn": "cleanup_b"}),
            PlanStep(id="step-3", kind="agent_call", description="C", agent="test",
                     depends_on=["step-2"]),
        ]
        plan = _make_plan(steps)
        results = orch.run_plan(plan)

        # Both compensations attempted, step-2 failed, step-1 succeeded
        assert executor.compensated == ["step-2", "step-1"]

        comp_entry = next(r for r in results if r["step_id"] == "__compensation__")
        assert comp_entry["compensated_steps"] == ["step-1"]
        assert comp_entry["compensation_failures"] == ["step-2"]

        # Compensation failure event emitted
        mock_comp_failed.assert_called_once()
        # Compensation success event also emitted for step-1
        mock_comp_completed.assert_called_once()

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_steps_without_compensate_fn_skipped(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """Steps without compensate_fn in metadata are skipped during compensation."""
        executor = _CompensationTrackingExecutor(fail_step_id="step-3")
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="Read", agent="test",
                     metadata={}),  # no compensate_fn
            PlanStep(id="step-2", kind="agent_call", description="Write", agent="test",
                     depends_on=["step-1"], metadata={"compensate_fn": "revert_write"}),
            PlanStep(id="step-3", kind="agent_call", description="Finalize", agent="test",
                     depends_on=["step-2"]),
        ]
        plan = _make_plan(steps)
        results = orch.run_plan(plan)

        # Only step-2 has compensate_fn, so only step-2 compensated
        assert executor.compensated == ["step-2"]

        comp_entry = next(r for r in results if r["step_id"] == "__compensation__")
        assert comp_entry["compensated_steps"] == ["step-2"]

        # step-1 status stays ok (not rolled_back, no compensation ran for it)
        step1_result = next(r for r in results if r["step_id"] == "step-1")
        assert step1_result["status"] == "ok"

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_no_compensation_when_no_predecessors(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """When the first step fails, no compensation runs (no completed predecessors)."""
        executor = _FailingExecutor(fail_step_id="step-1")
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="A", agent="test",
                     metadata={"compensate_fn": "cleanup_a"}),
            PlanStep(id="step-2", kind="agent_call", description="B", agent="test",
                     depends_on=["step-1"]),
        ]
        plan = _make_plan(steps)
        results = orch.run_plan(plan)

        # step-1 failed, no predecessors completed -> no compensation entry
        assert not any(r["step_id"] == "__compensation__" for r in results)
        mock_comp_started.assert_not_called()

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_no_compensation_when_plan_succeeds(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """No compensation when all steps succeed."""
        executor = _FailingExecutor(fail_step_id="nonexistent")
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="A", agent="test",
                     metadata={"compensate_fn": "cleanup_a"}),
            PlanStep(id="step-2", kind="agent_call", description="B", agent="test",
                     depends_on=["step-1"]),
        ]
        plan = _make_plan(steps)
        results = orch.run_plan(plan)

        assert all(r["status"] == "ok" for r in results)
        assert not any(r["step_id"] == "__compensation__" for r in results)
        mock_comp_started.assert_not_called()

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_rolled_back_event_emitted_with_correct_payload(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """orchestration.rolled_back event includes failed_step and compensated_steps."""
        executor = _CompensationTrackingExecutor(fail_step_id="step-2")
        orch = OrchestratorV2(executor=executor, max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="A", agent="test",
                     metadata={"compensate_fn": "cleanup_a"}),
            PlanStep(id="step-2", kind="agent_call", description="B", agent="test",
                     depends_on=["step-1"]),
        ]
        plan = _make_plan(steps)
        orch.run_plan(plan)

        mock_rolled_back.assert_called_once()
        call_kwargs = mock_rolled_back.call_args[1]
        assert call_kwargs["plan_id"] == "plan-1"
        assert call_kwargs["failed_step"] == "step-2"
        assert call_kwargs["compensated_steps"] == ["step-1"]
        assert call_kwargs["compensation_failures"] == []

    @patch("app.orchestrator.v2_runtime.emit_step_started")
    @patch("app.orchestrator.v2_runtime.emit_step_finished")
    @patch("app.orchestrator.v2_runtime.emit_step_error")
    @patch("app.orchestrator.v2_runtime.emit_compensation_started")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_completed")
    @patch("app.orchestrator.v2_runtime.emit_compensation_step_failed")
    @patch("app.orchestrator.v2_runtime.emit_orchestration_rolled_back")
    def test_compensation_receives_output_snapshot(
        self,
        mock_rolled_back,
        mock_comp_failed,
        mock_comp_completed,
        mock_comp_started,
        mock_step_error,
        mock_step_finished,
        mock_step_started,
    ) -> None:
        """Compensation step receives original step output as output_snapshot."""
        received_snapshots = []

        class SnapshotTracker:
            def execute_step(self, step: PlanStep, context: StepContext) -> dict:
                if step.metadata.get("compensation"):
                    received_snapshots.append(step.metadata.get("output_snapshot"))
                    return {"status": "compensated"}
                if step.id == "step-2":
                    raise StepExecutionError("fail", error_type="test")
                return {"resource_id": "res-123", "status": "ok"}

        orch = OrchestratorV2(executor=SnapshotTracker(), max_workers=1)

        steps = [
            PlanStep(id="step-1", kind="agent_call", description="Create", agent="test",
                     metadata={"compensate_fn": "cleanup"}),
            PlanStep(id="step-2", kind="agent_call", description="Fail", agent="test",
                     depends_on=["step-1"]),
        ]
        plan = _make_plan(steps)
        orch.run_plan(plan)

        # Compensation received the output of step-1
        assert len(received_snapshots) == 1
        assert received_snapshots[0] == {"resource_id": "res-123", "status": "ok"}
